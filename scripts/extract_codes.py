#!/usr/bin/env python3
"""Extract structured error-code records from data/manuals/parsed/*.json.

Writes data/index/error_codes.json -- COMMIT this file, it's the artifact
the running MCP server will eventually load. Caches per chunk by a content
hash (data/index/.extract_cache/, gitignored) so re-runs cost nothing once a
chunk's text hasn't changed.

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

from fixit_mcp.ingestion.extraction import (
    BedrockExtractor,
    ErrorCodeRecord,
    ExtractionSettings,
    make_extractor,
)
from fixit_mcp.ingestion.parser import ManualChunk, looks_like_table

REPO_ROOT = Path(__file__).resolve().parent.parent
PARSED_DIR = REPO_ROOT / "data" / "manuals" / "parsed"
INDEX_DIR = REPO_ROOT / "data" / "index"
OUTPUT_PATH = INDEX_DIR / "error_codes.json"
CACHE_DIR = INDEX_DIR / ".extract_cache"

_TROUBLESHOOTING_HEADING_RE = re.compile(r"troubleshoot|error code|fault code|before you call", re.I)

# Rough estimate only, for the printed cost figure -- update if the
# configured model differs. Approximate Sonnet-class Bedrock on-demand
# pricing per 1K tokens as of 2026-09.
ESTIMATED_INPUT_COST_PER_1K = 0.003
ESTIMATED_OUTPUT_COST_PER_1K = 0.015


def is_worth_extracting_from(chunk: ManualChunk) -> bool:
    """Only feed chunks that plausibly contain error codes -- most of a
    manual (safety notices, installation steps, feature descriptions) never
    does, and sending it anyway would just cost money for empty results."""
    if chunk.is_table:
        return True
    if looks_like_table(chunk.text):
        return True
    return bool(_TROUBLESHOOTING_HEADING_RE.search(chunk.section_heading or ""))


def chunk_cache_key(chunk: ManualChunk) -> str:
    """Content hash of the chunk text -- a re-run after re-parsing costs
    nothing as long as the chunk's text hasn't actually changed."""
    return hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()[:16]


def load_chunks(manual_id: str) -> list[ManualChunk]:
    path = PARSED_DIR / f"{manual_id}.json"
    data = json.loads(path.read_text())
    return [ManualChunk.model_validate(item) for item in data]


def load_cached_records(cache_path: Path) -> list[ErrorCodeRecord] | None:
    if not cache_path.exists():
        return None
    return [ErrorCodeRecord.model_validate(item) for item in json.loads(cache_path.read_text())]


def write_cached_records(cache_path: Path, records: list[ErrorCodeRecord]) -> None:
    cache_path.write_text(json.dumps([r.model_dump() for r in records], indent=2))


def process_manual(manual_id: str, extractor, force: bool) -> tuple[list[ErrorCodeRecord], dict]:
    chunks = load_chunks(manual_id)
    candidates = [c for c in chunks if is_worth_extracting_from(c)]

    records: list[ErrorCodeRecord] = []
    cache_hits = 0
    sent = 0
    input_tokens = 0
    output_tokens = 0

    for chunk in candidates:
        cache_path = CACHE_DIR / f"{chunk_cache_key(chunk)}.json"
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

    new_records: list[ErrorCodeRecord] = []
    total_input_tokens = 0
    total_output_tokens = 0

    for manual_id in target_manual_ids:
        records, stats = process_manual(manual_id, extractor, args.force)
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

    est_cost = (
        total_input_tokens / 1000 * ESTIMATED_INPUT_COST_PER_1K
        + total_output_tokens / 1000 * ESTIMATED_OUTPUT_COST_PER_1K
    )
    print(f"Total codes in {OUTPUT_PATH.relative_to(REPO_ROOT)}: {len(final_records)}")
    if total_input_tokens or total_output_tokens:
        print(f"This run's estimated tokens: {total_input_tokens} in / {total_output_tokens} out")
        print(f"This run's estimated cost: ${est_cost:.4f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
