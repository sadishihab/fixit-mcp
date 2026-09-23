#!/usr/bin/env python3
"""Parse every PDF in data/manuals/pdf/ into section-aware chunks.

Writes data/manuals/parsed/<manual_id>.json (gitignored -- derived data) and
prints a per-manual summary. No LLM calls, no network, no AWS -- pure local
PDF parsing via fixit_mcp.ingestion.parser.

Usage:
    uv run python scripts/parse_manuals.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from fixit_mcp.ingestion.parser import (
    ManualChunk,
    ManualMeta,
    dominant_offset_for_pages,
    extract_lines,
    parse_manual,
)

LOW_CONFIDENCE_REPAIR_THRESHOLD = 0.6
LOW_CONFIDENCE_TOKEN_THRESHOLD = 0.6

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "data" / "manuals" / "manifest.yaml"
PDF_DIR = REPO_ROOT / "data" / "manuals" / "pdf"
PARSED_DIR = REPO_ROOT / "data" / "manuals" / "parsed"


def load_manifest_metas() -> dict[str, ManualMeta]:
    if not MANIFEST_PATH.exists():
        return {}
    with MANIFEST_PATH.open() as f:
        entries = yaml.safe_load(f) or []
    return {
        entry["id"]: ManualMeta(
            id=entry["id"],
            brand=entry["brand"],
            model=entry["model"],
            appliance_type=entry["appliance_type"],
        )
        for entry in entries
    }


def summarize(manual_id: str, chunks: list[ManualChunk], pdf_path: Path) -> str:
    lines_by_page = extract_lines(pdf_path)
    all_lines = [line for page_lines in lines_by_page for line in page_lines]
    repaired = [line for line in all_lines if line.repair_confidence is not None]
    low_confidence = [line for line in repaired if line.repair_confidence < LOW_CONFIDENCE_REPAIR_THRESHOLD]

    repair_summary = f"  text repairs applied: {len(repaired)} lines"
    if repaired:
        repair_summary += f" ({len(low_confidence)} below {LOW_CONFIDENCE_REPAIR_THRESHOLD} confidence)"

    dominant = dominant_offset_for_pages(lines_by_page)
    token_repairs = [tr for line in all_lines for tr in line.token_repairs]
    low_confidence_tokens = [tr for tr in token_repairs if tr.confidence < LOW_CONFIDENCE_TOKEN_THRESHOLD]

    token_summary_lines = []
    if dominant is not None:
        token_summary_lines.append(
            f"  dominant document offset: {dominant.offset:+d} "
            f"({dominant.count}/{dominant.total_repaired} repaired lines, {dominant.share:.0%})"
        )
    token_summary_lines.append(
        f"  token-level repairs applied: {len(token_repairs)} "
        f"({len(low_confidence_tokens)} below {LOW_CONFIDENCE_TOKEN_THRESHOLD} confidence)"
    )
    if low_confidence_tokens:
        token_summary_lines.append("  low-confidence token repairs (eyeball these):")
        for tr in low_confidence_tokens:
            token_summary_lines.append(f"    {tr.original!r} -> {tr.repaired!r} (confidence {tr.confidence})")
    token_summary = "\n".join(token_summary_lines)

    if not chunks:
        return f"{manual_id}: 0 chunks (nothing extracted)\n{repair_summary}\n{token_summary}"

    pages_covered = {p for c in chunks for p in range(c.page_start, c.page_end + 1)}
    table_like = [c for c in chunks if c.is_table]
    lengths = [len(c.text) for c in chunks]
    shortest = min(chunks, key=lambda c: len(c.text))
    longest = max(chunks, key=lambda c: len(c.text))

    lines = [
        f"{manual_id}",
        f"  chunks: {len(chunks)}",
        f"  page coverage: {len(pages_covered)} distinct pages "
        f"(range {min(pages_covered)}-{max(pages_covered)})",
        f"  troubleshooting/error-code-like chunks: {len(table_like)}",
        f"  shortest chunk: {len(shortest.text)} chars ({shortest.chunk_id}, page {shortest.page_start})",
        f"  longest chunk: {len(longest.text)} chars "
        f"({longest.chunk_id}, pages {longest.page_start}-{longest.page_end})",
        f"  avg chunk length: {sum(lengths) / len(lengths):.0f} chars",
        repair_summary,
        token_summary,
    ]
    return "\n".join(lines)


def main() -> int:
    metas = load_manifest_metas()
    pdf_paths = sorted(PDF_DIR.glob("*.pdf"))

    if not pdf_paths:
        print(f"No PDFs found in {PDF_DIR}. Run `make fetch-manuals` first.")
        return 1

    PARSED_DIR.mkdir(parents=True, exist_ok=True)

    for pdf_path in pdf_paths:
        manual_id = pdf_path.stem
        meta = metas.get(
            manual_id,
            ManualMeta(id=manual_id, brand="unknown", model="unknown", appliance_type="unknown"),
        )

        chunks = parse_manual(pdf_path, meta)

        out_path = PARSED_DIR / f"{manual_id}.json"
        out_path.write_text(json.dumps([c.model_dump() for c in chunks], indent=2))

        print(summarize(manual_id, chunks, pdf_path))
        print(f"  written to {out_path.relative_to(REPO_ROOT)}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
