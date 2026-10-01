#!/usr/bin/env python3
"""Extract troubleshooting-table rows (symptoms) from manual PDFs into data/index/symptoms.json.

Offline ingestion, Nova only (never Claude), with a spending cap. For each manual:
reads the "Problem / Possible Causes / What To Do" tables from the PDF geometry,
prints the row counts and a cost estimate, asks Amazon Nova Pro to copy each row
verbatim, then audits every answer against the table (expected row count, each row's
strings joined must equal its source cell, footnote links, mid-sentence flag) with a
bounded retry. A manual's records are written only if every one of its tables passed;
other manuals' records in the file are left alone.

    make extract-symptoms                       # the default manuals, asks before spending
    make extract-symptoms DRY_RUN=1             # read the tables, print the estimate, call nothing
    make extract-symptoms MANUAL=ge-gtw680bsjws-washer YES=1 MAX_COST=0.5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from fixit_mcp.ingestion.symptom_extraction import (
    DEFAULT_MODEL_ID,
    DEFAULT_REGION,
    PROMPT_VERSION,
    Budget,
    BudgetExceeded,
    NovaSymptomExtractor,
    TableResult,
    build_records,
    build_user_prompt,
    estimate_call_cost,
)
from fixit_mcp.ingestion.symptom_tables import document_offset, read_symptom_tables

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "data" / "manuals" / "manifest.yaml"
PDF_DIR = REPO_ROOT / "data" / "manuals" / "pdf"
OUTPUT_PATH = REPO_ROOT / "data" / "index" / "symptoms.json"
CACHE_DIR = REPO_ROOT / "data" / "index" / ".extract_cache" / "symptoms"

# The manuals whose troubleshooting tables the reader supports (step 25b). The GE range's table is
# unruled and needs a different reader, so it is not here yet.
DEFAULT_MANUAL_IDS = ("ge-gfe28gynfs-refrigerator", "ge-gtw680bsjws-washer")
DEFAULT_MAX_COST_USD = 1.00


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, dict]:
    return {e["id"]: e for e in (yaml.safe_load(path.read_text()) or [])}


def merge_index(path: Path, manual_ids: set[str], new_records: list[dict]) -> tuple[int, int]:
    """Replace only these manuals' records; every other record stays as it was. Returns (kept, written)."""
    existing = json.loads(path.read_text()) if path.exists() else []
    kept = [r for r in existing if r["manual_id"] not in manual_ids]
    merged = sorted([*kept, *new_records], key=lambda r: r["manual_id"])  # stable: page order inside a manual
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    return len(kept), len(new_records)


def print_report(manual_id: str, results: list[TableResult]) -> None:
    print(f"\nAudit for {manual_id}")
    print(
        f"  {'page':>4} {'tbl':>3}  {'geometry rows':>13} {'extracted':>9} "
        f"{'attempts':>8} {'cached':>6}  result"
    )
    for r in results:
        verdict = "ACCEPTED" if r.accepted else "REJECTED"
        print(
            f"  {r.table.page:>4} {r.table.table_index:>3}  {len(r.table.rows):>13} {len(r.rows):>9} "
            f"{r.attempts:>8} {'yes' if r.cached else 'no':>6}  {verdict}  ${r.cost_usd:.4f}"
        )
        for problem in r.problems:
            print(f"        - {'row ' + str(problem.row) + ': ' if problem.row else ''}{problem.message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--manual", action="append", help="manual_id (repeatable). Default: the supported GE manuals."
    )
    parser.add_argument(
        "--max-cost", type=float, default=DEFAULT_MAX_COST_USD, help="hard cap in USD (default 1.00)"
    )
    parser.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    parser.add_argument(
        "--dry-run", action="store_true", help="read tables and estimate only; no Bedrock call"
    )
    parser.add_argument("--force", action="store_true", help="ignore the extraction cache")
    parser.add_argument(
        "--model-id", default=DEFAULT_MODEL_ID, help="a Nova model id (anything else is refused)"
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args(argv)

    manifest = load_manifest()
    manual_ids = args.manual or list(DEFAULT_MANUAL_IDS)
    unknown = [m for m in manual_ids if m not in manifest]
    if unknown:
        print(f"Not in the manifest: {unknown}")
        return 2

    budget = Budget(cap_usd=args.max_cost)
    extractor = None
    if not args.dry_run:
        extractor = NovaSymptomExtractor(
            model_id=args.model_id,
            region=DEFAULT_REGION,
            budget=budget,
            cache_dir=CACHE_DIR,
            force=args.force,
        )
    print(f"Model: {args.model_id} (Nova only), prompt {PROMPT_VERSION}, cap ${args.max_cost:.2f}")

    exit_code = 0
    for manual_id in manual_ids:
        entry = manifest[manual_id]
        pdf = PDF_DIR / f"{manual_id}.pdf"
        if not pdf.exists():
            print(f"\n{manual_id}: {pdf} is missing. Run `make fetch-manuals` first.")
            exit_code = 1
            continue
        offset = document_offset(pdf)
        tables = read_symptom_tables(pdf, manual_id, offset)
        brand, model, kind = entry["brand"], entry["model"], entry["appliance_type"]
        print(
            f"\n{manual_id}: font offset {offset:+d}" if offset else f"\n{manual_id}: no font repair needed"
        )
        if not tables:
            print("  no troubleshooting table with Problem/Possible Causes/What To Do columns found")
            exit_code = 1
            continue
        prompts = [build_user_prompt(brand, model, kind, t) for t in tables]
        estimate = sum(
            estimate_call_cost(args.model_id, p, len(t.rows)) for t, p in zip(tables, prompts, strict=True)
        )
        for t in tables:
            print(f"  p.{t.page} table {t.table_index}: {len(t.rows)} rows, columns {' | '.join(t.headers)}")
        print(f"  estimate for {len(tables)} table calls (one attempt each, +25% margin): ${estimate:.4f}")
        print(
            f"  running total ${budget.spent_usd:.4f} of ${args.max_cost:.2f}; "
            "a retry costs extra, the cap is enforced"
        )
        if budget.spent_usd + estimate > args.max_cost:
            print("  would pass the cap; stopping")
            return 3
        if args.dry_run:
            continue
        if not args.yes and input("  type 'yes' to run this batch on Bedrock: ").strip().lower() != "yes":
            print("  skipped")
            continue

        results: list[TableResult] = []
        try:
            for table in tables:
                results.append(extractor.extract_table(brand, model, kind, table))
        except BudgetExceeded as exc:
            print(f"  STOPPED: {exc}")
            return 3
        print_report(manual_id, results)
        if not all(r.accepted for r in results):
            print(f"  {manual_id}: not every table passed the audit, nothing written for this manual")
            exit_code = 1
            continue
        records, notes = build_records(results, brand=brand, model=model, appliance_type=kind)
        kept, written = merge_index(args.output, {manual_id}, [r.model_dump() for r in records])
        print(f"  wrote {written} records for {manual_id} to {args.output} ({kept} other records kept)")
        for note in notes:
            print(f"  note: {note}")

    print(
        f"\nSpent ${budget.spent_usd:.4f} of ${args.max_cost:.2f} ({budget.calls} calls, "
        f"{budget.input_tokens} in / {budget.output_tokens} out tokens; assumed list prices)"
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
