#!/usr/bin/env python3
"""Extract structured error-code records from data/manuals/parsed/*.json.

Writes data/index/error_codes.json -- COMMIT this file, it's the artifact
the running MCP server will eventually load. Caches per chunk by a hash of
(chunk text + which extractor/model produced it) in data/index/.extract_cache/
(gitignored), so a re-run with the *same* extractor costs nothing once a
chunk's text hasn't changed -- but switching FIXIT_EXTRACTOR (e.g. stub ->
bedrock) always misses the cache and re-extracts for real, rather than
silently serving another extractor's stale output (see FRICTION_LOG.md).

Usage:
    FIXIT_EXTRACTOR=stub uv run python scripts/extract_codes.py
    FIXIT_EXTRACTOR=bedrock uv run python scripts/extract_codes.py --manual lg-dlex8000w-dryer
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

from fixit_mcp.ingestion.extraction import (
    BedrockExtractor,
    ErrorCodeRecord,
    ExtractionSettings,
    make_extractor,
    normalize_code,
)
from fixit_mcp.ingestion.parser import ManualChunk, looks_like_table

REPO_ROOT = Path(__file__).resolve().parent.parent
PARSED_DIR = REPO_ROOT / "data" / "manuals" / "parsed"
INDEX_DIR = REPO_ROOT / "data" / "index"
OUTPUT_PATH = INDEX_DIR / "error_codes.json"
CACHE_DIR = INDEX_DIR / ".extract_cache"
MANIFEST_PATH = REPO_ROOT / "data" / "manuals" / "manifest.yaml"

_TROUBLESHOOTING_HEADING_RE = re.compile(r"troubleshoot|error code|fault code|before you call", re.I)

# Amazon Bedrock on-demand pricing for Claude Sonnet 4.5 (the default
# bedrock_model_id), per 1K tokens, confirmed 2026-09 -- update if you
# change the configured model. $9.00 / $45.00 per 1M input/output tokens.
# An earlier, unverified guess here (0.003 / 0.015) understated real cost
# by ~3x -- see FRICTION_LOG.md.
ESTIMATED_INPUT_COST_PER_1K = 0.009
ESTIMATED_OUTPUT_COST_PER_1K = 0.045

# Output tokens per chunk sent, for *estimates* only. Calibrated from the real
# Bedrock runs on the first five manuals (commits 8e8d2b9, 42cdd04): 3,311
# output tokens over 41 chunks sent = 80.7, rounded to 81. Chunks with no
# codes cost ~6 tokens ("[]"); a chunk full of codes costs ~160 per record, so
# a dense code table costs far more per chunk than this average. It replaces a
# flat guess of 1,000 that was ~12x too high for the mixed chunks it was
# calibrated on.
CALIBRATED_OUTPUT_TOKENS_PER_CHUNK = 81
# A window of a real code table is dense, unlike the mixed chunks above: the
# two page-mode runs (LG washer 3 windows = ~2.5k output tokens, Samsung dryer
# 1 window = ~1.2k) show ~800-1,200 output tokens per window. The 81 average
# understated those runs ~4x ($0.04 estimated vs $0.144 real for LG).
CODE_WINDOW_OUTPUT_TOKENS = 1200
CODE_WINDOW_CALIBRATION_NOTE = (
    "calibrated: page-mode windows of real code tables cost ~800-1,200 output tokens each (2 real runs)"
)
CALIBRATION_NOTE = "calibrated: 3,311 output tokens / 41 chunks in the first five real runs = ~81 per chunk"

# A chunk shorter than this is a bare heading or table-of-contents stub
# ("TROUBLESHOOTING", "Troubleshooting Tips... 46") that cannot hold a code
# table. The shortest chunk that ever produced a record was 1,757 chars.
MIN_CHUNK_CHARS = 60
_DOT_LEADER_RE = re.compile(r"(?:\.\s?){3,}")


def is_toc_entry(text: str) -> bool:
    """A table-of-contents block: most non-empty lines carry dot leaders
    ("Troubleshooting Tips . . . 22"), so it names a section but holds no codes."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return bool(lines) and sum(bool(_DOT_LEADER_RE.search(ln)) for ln in lines) * 2 >= len(lines)


def parse_page_spec(spec: str) -> set[int]:
    """ "43-45,48" -> {43, 44, 45, 48} (1-indexed PDF pages)."""
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        lo, _, hi = part.partition("-")
        pages.update(range(int(lo), int(hi or lo) + 1))
    return pages


WINDOW_MAX_CHARS = 8000  # a whole code table in one window: a row split across two loses its code or causes


def select_candidates(chunks: list[ManualChunk], pages: set[int] | None = None) -> list[ManualChunk]:
    """The chunks to extract from. Normally the heuristic filter. When a human
    has named the pages that hold the code table (`pages`, from the manifest's
    optional `extraction_pages`), send *only* those pages, with consecutive
    chunks merged into windows of up to WINDOW_MAX_CHARS: the parser can shatter
    a table into many tiny fragments (bold code labels become false headings),
    and a fragment alone lacks the context to say what a code means. Short
    fragments are kept here on purpose: a 12-character "WATER OUTLET" is half of
    a code's name."""
    if not pages:
        return [c for c in chunks if is_worth_extracting_from(c)]
    on_pages = [c for c in chunks if pages & set(range(c.page_start, c.page_end + 1)) and c.text.strip()]
    windows: list[ManualChunk] = []
    for chunk in on_pages:
        if windows and len(windows[-1].text) + len(chunk.text) + 1 <= WINDOW_MAX_CHARS:
            last = windows[-1]
            windows[-1] = last.model_copy(
                update={
                    "text": last.text + "\n" + chunk.text,
                    "page_end": max(last.page_end, chunk.page_end),
                    "is_table": True,
                    "uncertain_repairs": last.uncertain_repairs + chunk.uncertain_repairs,
                }
            )
        else:
            windows.append(chunk.model_copy(update={"is_table": True}))
    return windows


def refine_citations(
    records: list[ErrorCodeRecord], chunks: list[ManualChunk], pages: set[int]
) -> list[ErrorCodeRecord]:
    """A merged window reports its *first* chunk's page, so a code on the
    window's third page would cite the wrong page. Re-point each record at the
    first original chunk on the named pages whose text contains its code as a
    whole word; keep the window's citation if none does."""
    on_pages = [c for c in chunks if pages & set(range(c.page_start, c.page_end + 1))]
    refined = []
    for record in records:
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(record.error_code)}(?![A-Za-z0-9])")
        first = next((c for c in on_pages if pattern.search(c.text)), None)
        if first is not None:
            record = record.model_copy(
                update={"source_page": first.page_start, "source_chunk_id": first.chunk_id}
            )
        refined.append(record)
    return refined


def is_worth_extracting_from(chunk: ManualChunk) -> bool:
    """Only feed chunks that plausibly contain error codes -- most of a
    manual (safety notices, installation steps, feature descriptions) never
    does, and sending it anyway would just cost money for empty results."""
    if len(chunk.text.strip()) < MIN_CHUNK_CHARS or is_toc_entry(chunk.text):
        return False
    if chunk.is_table:
        return True
    if looks_like_table(chunk.text):
        return True
    return bool(_TROUBLESHOOTING_HEADING_RE.search(chunk.section_heading or ""))


def extractor_tag(settings: ExtractionSettings) -> str:
    """Identifies which extractor+model produced a cached result. Mixed into
    the cache key so switching FIXIT_EXTRACTOR (or bedrock_model_id) can
    never silently serve another extractor's stale cached output -- see
    FRICTION_LOG.md for the real incident this fixes."""
    if settings.extractor == "stub":
        return "stub"
    return f"bedrock:{settings.bedrock_model_id}"


def chunk_cache_key(chunk: ManualChunk, tag: str) -> str:
    """Content hash of the chunk text plus the extractor tag -- a re-run
    with the same extractor after re-parsing costs nothing as long as the
    chunk's text hasn't actually changed, but switching extractors always
    misses the cache and re-extracts for real."""
    payload = f"{tag}::{chunk.text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens / 1000 * ESTIMATED_INPUT_COST_PER_1K
        + output_tokens / 1000 * ESTIMATED_OUTPUT_COST_PER_1K
    )


def load_chunks(manual_id: str, parsed_dir: Path = PARSED_DIR) -> list[ManualChunk]:
    path = parsed_dir / f"{manual_id}.json"
    data = json.loads(path.read_text())
    return [ManualChunk.model_validate(item) for item in data]


def load_cached_records(cache_path: Path) -> list[ErrorCodeRecord] | None:
    if not cache_path.exists():
        return None
    return [ErrorCodeRecord.model_validate(item) for item in json.loads(cache_path.read_text())]


def write_cached_records(cache_path: Path, records: list[ErrorCodeRecord]) -> None:
    cache_path.write_text(json.dumps([r.model_dump() for r in records], indent=2))


def process_manual(
    manual_id: str,
    extractor,
    tag: str,
    force: bool,
    *,
    parsed_dir: Path = PARSED_DIR,
    cache_dir: Path = CACHE_DIR,
    pages: set[int] | None = None,
    code_fixes: dict[str, str] | None = None,
) -> tuple[list[ErrorCodeRecord], dict]:
    chunks = load_chunks(manual_id, parsed_dir)
    candidates = select_candidates(chunks, pages)

    records: list[ErrorCodeRecord] = []
    cache_hits = 0
    sent = 0
    input_tokens = 0
    output_tokens = 0

    for chunk in candidates:
        cache_path = cache_dir / f"{chunk_cache_key(chunk, tag)}.json"
        cached = None if force else load_cached_records(cache_path)
        if cached is not None:
            records.extend(cached)
            cache_hits += 1
            continue

        sent += 1
        chunk_records = extractor.extract(chunk)
        write_cached_records(cache_path, chunk_records)
        records.extend(chunk_records)

        if isinstance(extractor, BedrockExtractor) and extractor.last_usage:
            input_tokens += extractor.last_usage["input_tokens"]
            output_tokens += extractor.last_usage["output_tokens"]

    if pages:
        records = refine_citations(records, chunks, pages)
    if code_fixes:
        records = apply_code_fixes(records, code_fixes)

    stats = {
        "chunks_considered": len(chunks),
        "chunks_worth_extracting": len(candidates),
        "sent": sent,
        "cache_hits": cache_hits,
        "codes_found": len(records),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    return records, stats


def load_manifest_extras(manifest: Path = MANIFEST_PATH) -> dict[str, dict]:
    """manual_id -> {"pages": set[int] | None, "code_fixes": dict[str, str]} from the
    manifest's optional `extraction_pages` and `code_fixes` keys."""
    entries = (yaml.safe_load(manifest.read_text()) or []) if manifest.exists() else []
    return {
        e["id"]: {
            "pages": parse_page_spec(str(e["extraction_pages"])) if e.get("extraction_pages") else None,
            "code_fixes": dict(e.get("code_fixes") or {}),
        }
        for e in entries
    }


def apply_code_fixes(records: list[ErrorCodeRecord], fixes: dict[str, str]) -> list[ErrorCodeRecord]:
    """Deterministic, reviewed corrections for codes a PDF's font renders as
    look-alike glyphs in its text layer (LG's seven-segment "dE2" reads as
    "dEz"). Set per manual in the manifest as `code_fixes: {wrong: right}`,
    only after checking the rendered page; never guessed."""
    return [
        r.model_copy(
            update={"error_code": fixes[r.error_code], "code_normalized": normalize_code(fixes[r.error_code])}
        )
        if r.error_code in fixes
        else r
        for r in records
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manual",
        action="append",
        help="Only process this manual_id (repeatable). Default: all parsed manuals.",
    )
    parser.add_argument("--force", action="store_true", help="Ignore the cache and re-extract everything.")
    args = parser.parse_args()

    settings = ExtractionSettings()
    extractor = make_extractor(settings)
    tag = extractor_tag(settings)

    all_manual_ids = sorted(p.stem for p in PARSED_DIR.glob("*.json"))
    if not all_manual_ids:
        print(f"No parsed manuals found in {PARSED_DIR}. Run `make parse-manuals` first.")
        return 1
    target_manual_ids = args.manual or all_manual_ids

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    print(
        f"Extractor: {settings.extractor}"
        + (f" ({settings.bedrock_model_id})" if settings.extractor == "bedrock" else "")
    )
    print()

    extras = load_manifest_extras()
    new_records: list[ErrorCodeRecord] = []
    total_input_tokens = 0
    total_output_tokens = 0

    for manual_id in target_manual_ids:
        records, stats = process_manual(
            manual_id,
            extractor,
            tag,
            args.force,
            pages=extras.get(manual_id, {}).get("pages"),
            code_fixes=extras.get(manual_id, {}).get("code_fixes"),
        )
        new_records.extend(records)
        total_input_tokens += stats["input_tokens"]
        total_output_tokens += stats["output_tokens"]

        print(manual_id)
        print(f"  chunks considered: {stats['chunks_considered']}")
        print(f"  chunks worth extracting from: {stats['chunks_worth_extracting']}")
        print(f"  sent to extractor: {stats['sent']}")
        print(f"  cache hits: {stats['cache_hits']}")
        print(f"  codes found: {stats['codes_found']}")
        print()

    # Merge with any existing output: keep records for manuals not touched
    # this run (e.g. `--manual` targeted just one), replace the rest.
    existing: list[dict] = json.loads(OUTPUT_PATH.read_text()) if OUTPUT_PATH.exists() else []
    kept = [r for r in existing if r.get("manual_id") not in target_manual_ids]
    final_records = kept + [r.model_dump() for r in new_records]
    OUTPUT_PATH.write_text(json.dumps(final_records, indent=2))

    est_cost = cost_usd(total_input_tokens, total_output_tokens)
    print(f"Total codes in {OUTPUT_PATH.relative_to(REPO_ROOT)}: {len(final_records)}")
    if total_input_tokens or total_output_tokens:
        print(f"This run's estimated tokens: {total_input_tokens} in / {total_output_tokens} out")
        print(f"This run's estimated cost: ${est_cost:.4f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
