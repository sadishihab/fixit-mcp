#!/usr/bin/env python3
"""Check data/manuals/manifest.yaml is well formed and consistent.

Checks: every entry has the required non-empty fields, ids are unique,
brand+model pairs are unique, source_url is http(s), source_note is present,
every seeded appliance's manual_id resolves to an entry with the same
brand+model, and every record in data/index/error_codes.json points at a
manifest entry. No network.

Usage:
    uv run python scripts/validate_manifest.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

from fixit_mcp.repository.in_memory import DEFAULT_SEED

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "data" / "manuals" / "manifest.yaml"
INDEX_PATH = REPO_ROOT / "data" / "index" / "error_codes.json"

REQUIRED_FIELDS = ("id", "brand", "model", "appliance_type", "source_url", "source_note")


def validate(entries: object, seed: dict, index_records: list[dict]) -> list[str]:
    """Return a list of human-readable problems; empty means valid."""
    if not isinstance(entries, list):
        return ["manifest must be a YAML list of entries"]

    problems: list[str] = []
    by_id: dict[str, dict] = {}
    seen_models: dict[tuple[str, str], str] = {}

    for i, entry in enumerate(entries):
        label = f"entry #{i + 1}" + (
            f" ({entry.get('id')})" if isinstance(entry, dict) and entry.get("id") else ""
        )
        if not isinstance(entry, dict):
            problems.append(f"{label}: not a mapping")
            continue
        for field in REQUIRED_FIELDS:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                problems.append(f"{label}: missing or empty {field!r}")
        if isinstance(entry.get("source_url"), str) and not re.match(r"^https?://\S+$", entry["source_url"]):
            problems.append(f"{label}: source_url must be an http(s) URL")
        manual_id = entry.get("id")
        if isinstance(manual_id, str) and manual_id:
            if manual_id in by_id:
                problems.append(f"{label}: duplicate id {manual_id!r}")
            by_id.setdefault(manual_id, entry)
        if isinstance(entry.get("brand"), str) and isinstance(entry.get("model"), str):
            key = (entry["brand"].strip().lower(), entry["model"].strip().lower())
            if key in seen_models:
                problems.append(f"{label}: brand+model duplicates {seen_models[key]!r}")
            seen_models.setdefault(key, str(manual_id))

    for household, appliances in seed.items():
        for appliance in appliances:
            if not appliance.manual_id:
                continue
            entry = by_id.get(appliance.manual_id)
            where = f"seeded appliance {appliance.appliance_id} ({household})"
            if entry is None:
                problems.append(f"{where}: manual_id {appliance.manual_id!r} is not in the manifest")
            elif (appliance.brand.lower(), appliance.model.lower()) != (
                str(entry.get("brand", "")).lower(),
                str(entry.get("model", "")).lower(),
            ):
                problems.append(f"{where}: brand+model does not match manifest entry {appliance.manual_id!r}")

    for manual_id in sorted({r.get("manual_id") for r in index_records} - set(by_id)):
        problems.append(f"error_codes.json has records for manual_id {manual_id!r}, not in the manifest")

    return problems


def main() -> int:
    entries = yaml.safe_load(MANIFEST_PATH.read_text())
    index_records = json.loads(INDEX_PATH.read_text()) if INDEX_PATH.exists() else []
    problems = validate(entries, DEFAULT_SEED, index_records)
    if problems:
        print(f"{MANIFEST_PATH.relative_to(REPO_ROOT)}: {len(problems)} problem(s)")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"{MANIFEST_PATH.relative_to(REPO_ROOT)}: {len(entries)} entries OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
