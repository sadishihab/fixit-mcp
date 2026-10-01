"""The symptom loader and the deterministic matcher, on invented data (tests/symptom_fixtures.py)."""

import json
from pathlib import Path

import pytest

from fixit_mcp.catalog.manifest import load_manual_catalog
from fixit_mcp.domain.models import SymptomRecord
from fixit_mcp.retrieval.symptoms import (
    DEFAULT_SYMPTOMS_PATH,
    MIN_MATCHED_TERMS,
    MIN_SCORE,
    appliance_types_in,
    build_groups,
    load_symptom_index,
    query_terms,
    stem,
    tokenize,
)
from tests.symptom_fixtures import FRIDGE, WASHER, rec, synthetic_index, synthetic_records

INDEX = synthetic_index()


def _phrases(query: str, **kw) -> list[str]:
    return [s.group.phrases[0] for s in INDEX.search(query_terms(query), **kw)]


# --- loader -------------------------------------------------------------------------


def test_the_loader_reads_records_and_groups_continued_rows(tmp_path: Path) -> None:
    path = tmp_path / "symptoms.json"
    path.write_text(json.dumps([r.model_dump() for r in synthetic_records()]))

    index = load_symptom_index(path)

    drum = next(g for g in index.groups if g.phrases == ["Drum stays still"])
    assert [row.possible_causes for row in drum.rows] == [["Hatch not latched"], ["Plug is loose"]]
    assert len(index.groups) == len(synthetic_records()) - 1  # one continued row joined its symptom
    assert index.manual_ids == {WASHER, FRIDGE}


def test_a_continued_row_never_joins_another_manuals_symptom() -> None:
    records = [
        rec(WASHER, ["Hums"], ["a"], ["b"]),
        rec(FRIDGE, ["Hums"], ["c"], ["d"], continued=True),
    ]

    groups = build_groups(records)

    assert [(g.manual_id, len(g.rows)) for g in groups] == [(WASHER, 1), (FRIDGE, 1)]


def test_a_missing_index_file_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_symptom_index(tmp_path / "nope.json")


def test_a_malformed_record_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "symptoms.json"
    path.write_text(json.dumps([{"manual_id": "x"}]))

    with pytest.raises(ValueError):
        load_symptom_index(path)


def test_the_committed_index_loads_and_is_consistent_with_the_manifest() -> None:
    index = load_symptom_index(DEFAULT_SYMPTOMS_PATH)
    raw = [SymptomRecord.model_validate(r) for r in json.loads(DEFAULT_SYMPTOMS_PATH.read_text())]
    manual_ids = {e.manual_id for e in load_manual_catalog().entries}

    assert index.groups and raw
    assert {r.manual_id for r in raw} <= manual_ids
    assert all(r.symptom for r in raw), "every row, including a continued one, carries its symptom"
    assert all(g.rows[0].symptom_continued is False for g in index.groups)
    assert all(r.source_page > 0 and r.response_label and r.symptom_label for r in raw)
    assert all(r.possible_causes or r.what_to_do for r in raw)


# --- tokenizing ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("leaking", "leak"),
        ("leaks", "leak"),
        ("dripping", "drip"),
        ("clogged", "clog"),
        ("noises", "nois"),
        ("beeping", "beep"),
        ("clothes", "cloth"),
        ("glass", "glass"),
        ("make", "mak"),
        ("making", "mak"),
    ],
)
def test_stem(word: str, expected: str) -> None:
    assert stem(word) == expected


def test_contractions_open_and_stopwords_drop() -> None:
    assert tokenize("It won't drain") == ["drain"]
    assert tokenize("doesn't spin") == ["spin"]
    assert tokenize("my washer can't start") == ["washer", "operat"]


def test_everyday_words_fold_onto_the_manuals_words() -> None:
    assert tokenize("making a noise") == ["sound"]
    assert tokenize("it smells") == ["odor"]
    assert tokenize("it won't start") == tokenize("it doesn't work") == ["operat"]


def test_appliance_type_words_are_context_not_terms() -> None:
    assert query_terms("my washing machine is leaking") == ["leak"]
    assert query_terms("the fridge keeps beeping") == ["beep"]
    assert query_terms("the clothes come out wet") == ["cloth", "wet"]  # 'clothes' alone is not a type word
    assert appliance_types_in("my fridge is leaking") == {"refrigerator"}
    assert appliance_types_in("the washing machine and the dryer") == {"washing_machine", "dryer"}
    assert appliance_types_in("outside the normal range") == set()  # 'range' alone must not narrow a search


# --- paraphrases that must match ---------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("the drum stays still", "Drum stays still"),
        ("my drum is staying still", "Drum stays still"),
        ("water overflowing onto my floor", "Tub overflows onto the floor"),
        ("the tub overflows", "Tub overflows onto the floor"),
        ("it vibrates when it spins", "Vibrates while spinning"),
        ("the washer is making a whistling noise", "Whistling"),
        ("the fridge alarm keeps chirping", "Alarm chirps"),
        ("the cabinet is warm", "Cabinet is warm inside"),
        ("there is a bad smell inside", "Foul odor inside"),
    ],
)
def test_paraphrases_match_the_right_symptom_first(query: str, expected: str) -> None:
    assert _phrases(query)[0] == expected


def test_a_single_word_description_can_match() -> None:
    assert _phrases("whistling") == ["Whistling"]
    assert _phrases("chirping") == ["Alarm chirps"]


def test_a_second_phrase_of_the_same_symptom_matches_too() -> None:
    assert "Tub overflows onto the floor" in _phrases("water pours out")


def test_the_sounds_header_counts_as_a_word_of_the_symptom() -> None:
    assert _phrases("making a sound")[0] == "Whistling"
    assert "Whistling" not in _phrases("making a rattle")


# --- off-topic descriptions must not match ----------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "my television shows a blurry picture",
        "the cat is hungry",
        "something is wrong",
        "it is broken",
        "error code E24 on the display",
        "the car makes a grinding noise on the highway",
        "",
        "   ",
    ],
)
def test_off_topic_descriptions_return_nothing(query: str) -> None:
    assert _phrases(query) == []


def test_a_word_found_only_in_a_cause_never_matches() -> None:
    # "mildew" and "soap" appear only in cause text
    assert _phrases("mildew") == []
    assert _phrases("too much soap") == []


def test_one_matching_word_among_several_is_not_enough() -> None:
    assert "Drum stays still" not in _phrases("the drum plays music every night")


def test_the_minimum_score_and_matched_terms_are_the_documented_values() -> None:
    assert (MIN_SCORE, MIN_MATCHED_TERMS) == (0.5, 2)


def test_every_returned_match_clears_the_score_and_term_thresholds() -> None:
    for query in ("water pours out", "foul odor", "drum still", "alarm chirps loudly at night"):
        terms = query_terms(query)
        for s in INDEX.search(terms):
            assert s.score >= MIN_SCORE
            assert s.matched >= min(MIN_MATCHED_TERMS, len(terms))
            assert s.matched_in_symptom >= 1


def test_ties_go_to_the_symptom_the_query_covers_most_fully() -> None:
    records = [
        rec(WASHER, ["Water leaks from the door seal during long hot cycles"], ["a"], ["b"]),
        rec(WASHER, ["Water leaks"], ["c"], ["d"]),
    ]
    from fixit_mcp.retrieval.symptoms import build_index

    ranked = build_index(records).search(query_terms("water leaks"))

    assert [s.group.phrases[0] for s in ranked] == [
        "Water leaks",
        "Water leaks from the door seal during long hot cycles",
    ]


# --- two manuals, filters, nearest phrases ---------------------------------------------------------


def test_a_description_can_match_two_manuals() -> None:
    manuals = {s.group.manual_id for s in INDEX.search(query_terms("foul odor inside"))}

    assert manuals == {WASHER, FRIDGE}


def test_search_can_be_limited_to_manuals_or_a_type() -> None:
    terms = query_terms("water pours out")

    assert {s.group.manual_id for s in INDEX.search(terms, manual_ids={FRIDGE})} == {FRIDGE}
    assert {s.group.manual_id for s in INDEX.search(terms, appliance_type="washing_machine")} == {WASHER}


def test_nearest_phrases_are_verbatim_manual_phrases_that_share_a_word() -> None:
    nearest = INDEX.nearest_phrases(query_terms("the drum plays music at night"))

    assert nearest == ["Drum stays still"]
    assert INDEX.nearest_phrases(query_terms("television picture")) == []
    assert INDEX.nearest_phrases(query_terms("drum"), manual_ids={FRIDGE}) == []
