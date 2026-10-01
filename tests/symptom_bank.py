"""Evaluate diagnose_symptom against the paraphrase bank (tests/fixtures/symptom_paraphrases.yaml).

Used by tests/unit/test_symptom_bank.py, and runnable as a report:
    uv run python -m tests.symptom_bank
"""

from __future__ import annotations

import collections
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from fixit_mcp.domain.models import Appliance, SymptomRecord
from fixit_mcp.repository.in_memory import InMemoryApplianceRepository
from fixit_mcp.retrieval.symptoms import DEFAULT_SYMPTOMS_PATH, SymptomIndex, build_index
from fixit_mcp.tools.symptoms import diagnose_symptom

BANK_PATH = Path(__file__).parent / "fixtures" / "symptom_paraphrases.yaml"
BASELINE_PATH = Path(__file__).parent / "fixtures" / "symptom_baseline.json"
MANUALS = {"fridge": "ge-gfe28gynfs-refrigerator", "washer": "ge-gtw680bsjws-washer"}
HOUSEHOLD = "h-both"

# Outcomes. For an expected case: right | miss (not_found) | ambiguous (asked which appliance) |
# wrong (a different symptom first). For a `none` case: ok (not_found) | wrong (anything else).
RIGHT, MISS, AMBIGUOUS, WRONG, OK = "right", "miss", "ambiguous", "wrong", "ok"


@dataclass
class Result:
    case: dict
    outcome: str
    top: tuple[str, int, int] | None  # (appliance, page, row) of the first match returned
    in_top3: bool = False


def load_bank(path: Path = BANK_PATH) -> list[dict]:
    cases = yaml.safe_load(path.read_text())["cases"]
    assert len({c["id"] for c in cases}) == len(cases), "duplicate case id"
    return cases


def load_records(path: Path = DEFAULT_SYMPTOMS_PATH) -> list[SymptomRecord]:
    return [SymptomRecord.model_validate(r) for r in json.loads(path.read_text())]


def _refs(records: list[SymptomRecord]) -> dict[tuple[str, int, tuple[str, ...]], tuple[str, int, int]]:
    """(model, page, symptom phrases) of a group's first row -> (appliance, page, row index on that page)."""
    kind = {manual: name for name, manual in MANUALS.items()}
    seen: collections.Counter = collections.Counter()
    refs: dict = {}
    for r in records:
        row = seen[(r.manual_id, r.source_page)]
        seen[(r.manual_id, r.source_page)] += 1
        if not r.symptom_continued:
            refs[(r.model, r.source_page, tuple(r.symptom))] = (kind[r.manual_id], r.source_page, row)
    return refs


def household() -> InMemoryApplianceRepository:
    def appliance(app_id: str, kind: str, brand: str, model: str, type_: str) -> Appliance:
        return Appliance(
            appliance_id=app_id, brand=brand, model=model, appliance_type=type_, manual_id=MANUALS[kind]
        )

    return InMemoryApplianceRepository(
        seed={
            HOUSEHOLD: [
                appliance("a-f", "fridge", "GE", "GFE28GYNFS", "refrigerator"),
                appliance("a-w", "washer", "GE", "GTW680BSJWS", "washing_machine"),
            ]
        }
    )


def evaluate(records: list[SymptomRecord] | None = None, cases: list[dict] | None = None) -> list[Result]:
    records = records if records is not None else load_records()
    cases = cases if cases is not None else load_bank()
    index: SymptomIndex = build_index(records)
    refs = _refs(records)
    repo = household()
    results: list[Result] = []
    for case in cases:
        out = diagnose_symptom(index, repo, HOUSEHOLD, case["query"])
        tops = [refs[(m.citation.model, m.citation.page, tuple(m.symptom))] for m in out.matches]
        top = tops[0] if tops else None
        if case["expect"] == "none":
            outcome = OK if out.status == "not_found" else WRONG
            results.append(Result(case, outcome, top))
            continue
        accepted = {(e["appliance"], e["page"], e["row"]) for e in case["expect"]}
        if out.status == "not_found":
            outcome = MISS
        elif out.status == "ambiguous_appliance":
            outcome = AMBIGUOUS
        else:
            outcome = RIGHT if top in accepted else WRONG
        results.append(Result(case, outcome, top, in_top3=bool(accepted & set(tops))))
    return results


def _split(results: list[Result], heldout: bool) -> list[Result]:
    return [r for r in results if (r.case.get("split") == "heldout") == heldout]


def summarize(results: list[Result]) -> dict:
    expected = [r for r in results if r.case["expect"] != "none"]
    none = [r for r in results if r.case["expect"] == "none"]
    count = lambda rs, o: sum(1 for r in rs if r.outcome == o)  # noqa: E731
    return {
        "cases": len(results),
        "expected_cases": len(expected),
        "right": count(expected, RIGHT),
        "right_in_top3": sum(1 for r in expected if r.in_top3),
        "miss": count(expected, MISS),
        "ambiguous": count(expected, AMBIGUOUS),
        "wrong_among_expected": count(expected, WRONG),
        "none_cases": len(none),
        "none_ok": count(none, OK),
        "none_wrongly_matched": count(none, WRONG),
        "by_outcome": {r.case["id"]: r.outcome for r in results},
    }


def report(results: list[Result], heldout: bool = False) -> str:
    """The tuning split's report by default; the held-out split only on request."""
    results = _split(results, heldout)
    s = summarize(results)
    lines = [
        f"{'HELD-OUT' if heldout else 'TUNING'} split, {s['cases']} cases: "
        f"{s['expected_cases']} expect a match, {s['none_cases']} expect none",
        f"expected matches: right {s['right']}/{s['expected_cases']} (in top 3: {s['right_in_top3']}), "
        f"missed (not_found) {s['miss']}, asked which appliance {s['ambiguous']}, "
        f"WRONG symptom first {s['wrong_among_expected']}",
        f"none cases: correctly not_found {s['none_ok']}/{s['none_cases']}, "
        f"WRONGLY MATCHED {s['none_wrongly_matched']}",
        "",
    ]
    for r in results:
        if r.outcome in (MISS, AMBIGUOUS, WRONG):
            want = (
                "none"
                if r.case["expect"] == "none"
                else [(e["appliance"], e["page"], e["row"]) for e in r.case["expect"]]
            )
            lines.append(
                f"  {r.outcome.upper():9} {r.case['id']:28} {r.case['query']!r}  want={want} got={r.top}"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    results = evaluate()
    print(report(results))
    if "--heldout" in sys.argv:
        print()
        print(report(results, heldout=True))
    else:
        h = summarize(_split(results, True))
        print(f"\n(held-out split: {h['cases']} cases, not shown)")
    if "--save" in sys.argv:
        BASELINE_PATH.write_text(
            json.dumps(
                {"tuning": summarize(_split(results, False)), "heldout": summarize(_split(results, True))},
                indent=2,
            )
            + "\n"
        )
        print(f"\nsaved {BASELINE_PATH}")
