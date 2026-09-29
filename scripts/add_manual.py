#!/usr/bin/env python3
"""Add one appliance manual to FixIt's knowledge base, from URL to cited records.

One command runs the whole offline pipeline for a single manual:

  1. validate the arguments (refuses a duplicate id or brand+model)
  2. download the URL and verify it is a real PDF (same checks as fetch_manuals)
  3. content check: the PDF must mention the model and contain a
     troubleshooting/error-code keyword (--force overrides)
  --dry-run stops here and changes nothing.
  4. append the entry to data/manuals/manifest.yaml, keep the PDF in data/manuals/pdf/
  5. parse (with the font-encoding repair) into data/manuals/parsed/<id>.json
  6. extract error-code records with the configured extractor
     (FIXIT_EXTRACTOR=stub|bedrock; bedrock prints an estimate and asks for "yes")
  7. merge the records into data/index/error_codes.json, leaving every other
     manual's records untouched

Re-running with the same arguments is idempotent: the existing manifest entry
is recognised (not duplicated), and only this manual's records are replaced.

Usage:
    uv run python scripts/add_manual.py --id acme-x100-oven --brand Acme --model X100 \\
        --type oven --url https://example.com/x100.pdf --note "Linked from ..., free, no login"
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract_codes  # noqa: E402
import fetch_manuals  # noqa: E402
import parse_manuals  # noqa: E402

from fixit_mcp.ingestion.extraction import (  # noqa: E402
    _SYSTEM_PROMPT,
    ErrorCodeExtractor,
    ErrorCodeRecord,
    ExtractionSettings,
    StubExtractor,
    _build_user_prompt,
    make_extractor,
)
from fixit_mcp.ingestion.parser import ManualMeta, extract_lines, parse_manual  # noqa: E402

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MIN_NOTE_CHARS = 20

# A manual that has none of these is almost certainly a spec sheet, install
# guide or brochure (FRICTION_LOG.md: the Bosch SHXM4AY55N spec-sheet mixup).
TROUBLESHOOTING_KEYWORDS = re.compile(
    r"troubleshoot|error code|fault code|error message|diagnostic|problem solver|"
    r"before you call|possible cause|display code|fault",
    re.IGNORECASE,
)

TERMS_REMINDER = (
    "REMINDER: check the manufacturer's terms of use before redistributing anything extracted\n"
    "from this manual. The PDF itself is gitignored and never committed, but the extracted\n"
    "records in data/index/error_codes.json ARE committed (and ship in the image)."
)

# The extraction prompt asks for a JSON array of full records; a rough guess
# per chunk, printed as an estimate only.
ESTIMATED_OUTPUT_TOKENS_PER_CHUNK = 1000
CHARS_PER_TOKEN = 4


class Abort(Exception):
    """A step failed in a way the user should fix; message is printed as-is."""


@dataclass(frozen=True)
class Paths:
    manifest: Path
    pdf_dir: Path
    parsed_dir: Path
    index: Path
    cache_dir: Path

    @classmethod
    def default(cls) -> Paths:
        return cls(
            manifest=fetch_manuals.MANIFEST_PATH,
            pdf_dir=fetch_manuals.PDF_DIR,
            parsed_dir=parse_manuals.PARSED_DIR,
            index=extract_codes.OUTPUT_PATH,
            cache_dir=extract_codes.CACHE_DIR,
        )


@dataclass(frozen=True)
class ContentCheck:
    pages: int
    model_match: str | None  # "exact", "series", or None
    keywords: list[str]

    @property
    def ok(self) -> bool:
        return self.model_match is not None and bool(self.keywords)


def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


# --- 1. arguments --------------------------------------------------------


def load_manifest_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text()) or []


def validate_args(entry: dict, existing: list[dict]) -> bool:
    """Raise Abort on bad input or a conflict. Returns True when `entry` is
    identical to what the manifest already holds (a re-run/resume), so the
    caller skips appending it again."""
    if not ID_RE.match(entry["id"]):
        raise Abort(f"invalid --id {entry['id']!r}: use lowercase letters, digits and dashes only.")
    for field in ("brand", "model", "appliance_type"):
        if not entry[field].strip():
            raise Abort(f"--{'type' if field == 'appliance_type' else field} must not be empty.")
    if not re.match(r"^https?://\S+$", entry["source_url"]):
        raise Abort(f"--url must be an http(s) URL, got {entry['source_url']!r}.")
    if len(entry["source_note"].strip()) < MIN_NOTE_CHARS:
        raise Abort(
            f"--note is required (at least {MIN_NOTE_CHARS} characters): say where the URL came from "
            "and why the PDF is freely downloadable."
        )

    same_id = next((e for e in existing if e["id"] == entry["id"]), None)
    if same_id is not None:
        identical = all(
            str(same_id[k]).strip().lower() == entry[k].strip().lower()
            for k in ("brand", "model", "appliance_type", "source_url")
        )
        if not identical:
            raise Abort(
                f"id {entry['id']!r} already exists in the manifest with different "
                "brand/model/type/url. Pick a new id, or edit the manifest entry by hand."
            )
    for other in existing:
        if other["id"] != entry["id"] and (
            other["brand"].strip().lower() == entry["brand"].strip().lower()
            and other["model"].strip().lower() == entry["model"].strip().lower()
        ):
            raise Abort(
                f"brand+model {entry['brand']} {entry['model']} is already in the manifest as "
                f"{other['id']!r}. One manual per model."
            )
    return same_id is not None


# --- 3. content check ----------------------------------------------------


def series_stem(model: str) -> str | None:
    """The model with its trailing letter run stripped (GFE28GYNFS -> GFE28):
    manufacturers often publish one manual for a whole series and print only
    the stem. None when nothing distinctive is left."""
    stem = re.sub(r"[a-z]+$", "", _alnum(model))
    return stem if len(stem) >= 4 and re.search(r"\d", stem) else None


def check_content(pdf_path: Path, model: str) -> ContentCheck:
    # extract_lines (not raw PyMuPDF) so the encoding repair applies: two of
    # the corpus's manuals have corrupted fonts and a raw scan misses text.
    pages = extract_lines(pdf_path)
    text = "\n".join(line.text for page in pages for line in page)
    collapsed = _alnum(text)

    model_match = None
    if _alnum(model) in collapsed:
        model_match = "exact"
    else:
        stem = series_stem(model)
        if stem and stem in collapsed:
            model_match = "series"

    keywords = sorted({m.lower() for m in TROUBLESHOOTING_KEYWORDS.findall(text)})
    return ContentCheck(pages=len(pages), model_match=model_match, keywords=keywords)


# --- 4. manifest ---------------------------------------------------------


def append_manifest_entry(path: Path, entry: dict) -> None:
    """Append as text, not by re-serialising the file, so the manifest's
    header comments and existing entries stay byte-for-byte untouched."""
    block = yaml.safe_dump([entry], sort_keys=False, default_flow_style=False, width=88, allow_unicode=True)
    existing = path.read_text() if path.exists() else ""
    separator = "" if not existing else ("\n" if existing.endswith("\n") else "\n\n")
    path.write_text(existing + separator + block)


# --- 6. extraction planning ---------------------------------------------


def plan_extraction(manual_id: str, tag: str, paths: Paths, force: bool) -> tuple[int, int, int]:
    """(chunks worth extracting, chunks that need a real call, estimated input tokens)."""
    chunks = extract_codes.load_chunks(manual_id, paths.parsed_dir)
    candidates = [c for c in chunks if extract_codes.is_worth_extracting_from(c)]
    to_send = [
        c
        for c in candidates
        if force or not (paths.cache_dir / f"{extract_codes.chunk_cache_key(c, tag)}.json").exists()
    ]
    input_chars = sum(len(_SYSTEM_PROMPT) + len(_build_user_prompt(c)) for c in to_send)
    return len(candidates), len(to_send), input_chars // CHARS_PER_TOKEN


# --- 7. index merge ------------------------------------------------------


def merge_index(index_path: Path, manual_id: str, new_records: list[ErrorCodeRecord]) -> tuple[int, int]:
    """Replace only `manual_id`'s records; every other record is kept as the
    raw dict it already is, in place. Returns (records replaced, total after)."""
    existing: list[dict] = json.loads(index_path.read_text()) if index_path.exists() else []
    kept = [r for r in existing if r.get("manual_id") != manual_id]
    final = kept + [r.model_dump() for r in new_records]
    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = index_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(final, indent=2))
    tmp.replace(index_path)
    return len(existing) - len(kept), len(final)


def existing_records_have_content(index_path: Path, manual_id: str) -> bool:
    if not index_path.exists():
        return False
    return any(
        r.get("manual_id") == manual_id and r.get("meaning") for r in json.loads(index_path.read_text())
    )


# --- the run -------------------------------------------------------------


def run(
    args: argparse.Namespace,
    paths: Paths,
    *,
    transport: httpx.BaseTransport | None = None,
    extractor: ErrorCodeExtractor | None = None,
    input_fn: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
) -> int:
    entry = {
        "id": args.id,
        "brand": args.brand.strip(),
        "model": args.model.strip(),
        "appliance_type": args.type.strip(),
        "source_url": args.url.strip(),
        "source_note": " ".join(args.note.split()),
    }
    try:
        return _run(entry, args, paths, transport, extractor, input_fn, say)
    except Abort as exc:
        say(f"\nSTOPPED: {exc}")
        return 1


def _run(entry, args, paths, transport, extractor, input_fn, say) -> int:
    manual_id = entry["id"]

    say("[1/7] Validating arguments")
    already_in_manifest = validate_args(entry, load_manifest_entries(paths.manifest))
    say(
        "      ok"
        + (" (id already in the manifest with identical fields: re-run)" if already_in_manifest else "")
    )

    with tempfile.TemporaryDirectory(prefix="fixit-add-manual-") as tmp:
        tmp_pdf = Path(tmp) / f"{manual_id}.pdf"

        say(f"[2/7] Downloading {entry['source_url']}")
        result = fetch_manuals.download_pdf(manual_id, entry["source_url"], tmp_pdf, transport=transport)
        if not result.ok:
            raise Abort(f"the URL did not give a usable PDF: {result.detail}")
        say(f"      ok: real PDF, {result.pages} pages, {result.size_bytes / 1024:.0f} KB")

        say(f"[3/7] Content check (model {entry['model']!r} + troubleshooting/error-code keywords)")
        check = check_content(tmp_pdf, entry["model"])
        say(f"      model number: {check.model_match or 'NOT FOUND'}")
        say(f"      keywords: {', '.join(check.keywords) or 'NONE FOUND'}")
        if check.model_match == "series":
            say("      note: only the model's series stem appears, so this looks like a family manual.")
        if not check.ok:
            problems = []
            if check.model_match is None:
                problems.append(f"the model number {entry['model']!r} never appears in the text")
            if not check.keywords:
                problems.append("no troubleshooting or error-code keyword appears")
            why = "; ".join(problems)
            if not args.force:
                raise Abort(
                    f"this PDF does not look like the manual you want: {why}. It may be a spec sheet, "
                    "install guide or the wrong model. Open it and check, or pass --force to add it anyway."
                )
            say(f"      --force given: continuing despite: {why}")

        if args.dry_run:
            say("\nDry run: stopping here. Nothing was changed (manifest, PDFs, parsed files, index).")
            return 0

        settings = ExtractionSettings()
        if extractor is None:
            extractor = make_extractor(settings)
        is_stub = isinstance(extractor, StubExtractor)
        if is_stub and not args.allow_downgrade and existing_records_have_content(paths.index, manual_id):
            raise Abort(
                f"the index already has fully extracted records for {manual_id!r}, and the stub "
                "extractor would replace them with bare codes. Set FIXIT_EXTRACTOR=bedrock, or pass "
                "--allow-downgrade if you really want that."
            )

        say("[4/7] Recording the manual")
        if already_in_manifest:
            say("      manifest entry already present, left as is")
        else:
            append_manifest_entry(paths.manifest, entry)
            say(f"      appended to {paths.manifest.name}")
        paths.pdf_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tmp_pdf, paths.pdf_dir / f"{manual_id}.pdf")
        say(f"      PDF kept at {paths.pdf_dir / f'{manual_id}.pdf'} (gitignored, never commit it)")
        say("      " + TERMS_REMINDER.replace("\n", "\n      "))

    say("[5/7] Parsing (with encoding repair)")
    meta = ManualMeta(
        id=manual_id, brand=entry["brand"], model=entry["model"], appliance_type=entry["appliance_type"]
    )
    chunks = parse_manual(paths.pdf_dir / f"{manual_id}.pdf", meta)
    paths.parsed_dir.mkdir(parents=True, exist_ok=True)
    (paths.parsed_dir / f"{manual_id}.json").write_text(
        json.dumps([c.model_dump() for c in chunks], indent=2)
    )
    say(f"      {len(chunks)} chunks")
    if not chunks:
        raise Abort(
            "the PDF parsed into 0 chunks (scanned images? no extractable text?). Nothing to extract."
        )

    tag = "stub" if is_stub else f"bedrock:{settings.bedrock_model_id}"
    candidates, to_send, est_in = plan_extraction(manual_id, tag, paths, force=False)
    say(f"[6/7] Extracting with the {'stub' if is_stub else 'bedrock'} extractor")
    say(f"      {candidates} chunks look worth extracting from, {to_send} not yet cached")
    if not is_stub and to_send:
        est_out = to_send * ESTIMATED_OUTPUT_TOKENS_PER_CHUNK
        say(f"      About to send {to_send} chunks to Amazon Bedrock ({settings.bedrock_model_id}).")
        say(f"      Estimated tokens: ~{est_in} in / ~{est_out} out (rough guess)")
        say(f"      Estimated cost: ~${extract_codes.cost_usd(est_in, est_out):.2f}")
        if not args.yes:
            try:
                answer = input_fn('      Type "yes" to proceed: ')
            except EOFError:
                answer = ""
            if answer.strip().lower() != "yes":
                say(
                    "\nSTOPPED: not confirmed, nothing was sent. The manifest entry and parsed chunks are "
                    "kept; re-run the same command to continue."
                )
                return 1

    paths.cache_dir.mkdir(parents=True, exist_ok=True)
    records, stats = extract_codes.process_manual(
        manual_id, extractor, tag, False, parsed_dir=paths.parsed_dir, cache_dir=paths.cache_dir
    )

    say("[7/7] Merging into the index")
    replaced, total = merge_index(paths.index, manual_id, records)
    say(f"      replaced {replaced} old records for this manual; index now has {total} records")

    cost = extract_codes.cost_usd(stats["input_tokens"], stats["output_tokens"])
    say("\nSummary")
    say(f"  codes found: {stats['codes_found']}")
    say(f"  chunks sent: {stats['sent']} (cache hits: {stats['cache_hits']})")
    say(f"  cost: ${cost:.4f}" + ("" if not is_stub else " (stub extractor, no AWS)"))
    if is_stub:
        say("  note: the stub only finds known code shapes and fills in no meaning/steps.")
    if not records:
        say("  WARNING: 0 codes found. Check the manual has a real code table; see CONTRIBUTING.md.")
    say("\nNext: `make validate-manifest`, `make test`, review the diff, commit. The deployed server only")
    say(
        "gets this manual after an image rebuild and runtime update "
        "(make docker-build docker-push deploy-runtime)."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--id", required=True, help="Stable manual id, e.g. acme-x100-oven.")
    p.add_argument("--brand", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--type", required=True, help="Appliance type, e.g. dishwasher.")
    p.add_argument("--url", required=True, help="Direct http(s) URL of the manual PDF.")
    p.add_argument("--note", required=True, help="Where the URL came from and why it is freely downloadable.")
    p.add_argument("--dry-run", action="store_true", help="Stop after the content check; change nothing.")
    p.add_argument("--force", action="store_true", help="Add even if the content check fails.")
    p.add_argument("--yes", action="store_true", help="Skip the Bedrock cost confirmation.")
    p.add_argument(
        "--allow-downgrade",
        action="store_true",
        help="Let the stub extractor replace existing fully-extracted records for this manual.",
    )
    return p


def main() -> int:
    return run(build_parser().parse_args(), Paths.default())


if __name__ == "__main__":
    sys.exit(main())
