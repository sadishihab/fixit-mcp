"""The paraphrase bank (tests/fixtures/symptom_paraphrases.yaml) as a regression test for diagnose_symptom.

It runs invented customer phrasings through the real tool against the committed index. It fails on any
wrong cited answer (the wrong symptom first, or any match for a case that expects not_found) and if
recall drops below what was achieved. See tests/symptom_bank.py for the report.
"""

import collections
import json

from fixit_mcp.retrieval.symptoms import build_index
from tests.symptom_bank import (
    BASELINE_PATH,
    MANUALS,
    RIGHT,
    WRONG,
    _refs,
    _split,
    evaluate,
    load_bank,
    load_records,
    summarize,
)

# What the improved matcher achieves on each split (step 27c). A change that lowers either number fails.
TUNING_RIGHT_FLOOR = 43  # of 47 expected matches
HELDOUT_RIGHT_FLOOR = 4  # of 10: the held-out gain is only in removed wrong answers (see CHANGELOG)

RESULTS = evaluate()
TUNING = _split(RESULTS, False)
HELDOUT = _split(RESULTS, True)


def test_the_bank_is_big_varied_and_at_least_a_third_expects_none() -> None:
    cases = load_bank()

    assert len(cases) >= 60
    assert sum(c["expect"] == "none" for c in cases) / len(cases) >= 1 / 3
    tags = collections.Counter(c["tag"] for c in cases)
    assert {"plain", "slang", "misspelling", "short", "long", "other-appliance", "offtopic", "safety"} <= set(
        tags
    )
    assert {e["appliance"] for c in cases if c["expect"] != "none" for e in c["expect"]} == set(MANUALS)


def test_every_expected_row_exists_in_the_committed_index() -> None:
    records = load_records()
    refs = set(_refs(records).values())

    for case in load_bank():
        if case["expect"] == "none":
            continue
        for e in case["expect"]:
            assert (e["appliance"], e["page"], e["row"]) in refs, case["id"]


def test_no_phrasing_is_copied_manual_text() -> None:
    """The bank is invented wording: no case may be a verbatim stored symptom phrase."""
    stored = {p.lower().rstrip("*. ") for r in load_records() for p in r.symptom}
    for case in load_bank():
        assert case["query"].lower().rstrip("*. ") not in stored, case["id"]


def test_the_matcher_gives_no_wrong_cited_answer_beyond_the_known_ones() -> None:
    known = {c["id"] for c in load_bank() if c.get("known_wrong")}
    wrong = {r.case["id"] for r in RESULTS if r.outcome == WRONG}

    assert wrong - known == set(), "a wrong match is worse than not_found"
    assert known - wrong == set(), "a known-wrong case is no longer wrong: remove its known_wrong flag"


def test_there_is_no_known_wrong_answer_among_the_tuning_cases() -> None:
    assert [r.case["id"] for r in TUNING if r.outcome == WRONG] == []


def test_every_none_case_is_not_found() -> None:
    wrongly = [r.case["id"] for r in RESULTS if r.case["expect"] == "none" and r.outcome != "ok"]

    assert wrongly == []


def test_recall_on_the_tuning_split_does_not_drop() -> None:
    assert summarize(TUNING)["right"] >= TUNING_RIGHT_FLOOR


def test_recall_on_the_held_out_split_does_not_drop() -> None:
    assert summarize(HELDOUT)["right"] >= HELDOUT_RIGHT_FLOOR


def test_recall_is_meaningfully_above_the_saved_baseline_of_the_old_matcher() -> None:
    baseline = json.loads(BASELINE_PATH.read_text())

    assert summarize(TUNING)["right"] >= baseline["tuning"]["right"] + 10
    assert baseline["tuning"]["none_wrongly_matched"] > 0, (
        "the baseline is the old matcher's, with its wrong matches"
    )


def test_the_expected_symptom_is_first_not_just_somewhere_in_the_results() -> None:
    right = [r for r in RESULTS if r.outcome == RIGHT]

    assert right and all(r.top is not None for r in right)


def test_the_index_the_bank_runs_against_is_the_committed_one() -> None:
    assert len(build_index(load_records()).groups) == 67
