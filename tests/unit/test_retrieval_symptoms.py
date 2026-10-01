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


def test_one_filler_word_the_manuals_do_not_contain_does_not_raise_the_bar() -> None:
    assert _phrases("drum stays still totally")[0] == "Drum stays still"
    assert _phrases("whistling absolutely")[0] == "Whistling"  # a single real word plus one filler


def test_two_unknown_words_keep_the_two_matched_words_requirement() -> None:
    assert _phrases("my drum plays music") == []  # one real word, two unknown ones
    assert (
        _phrases("drum music") == []
    )  # step 27e: an unknown word no longer lets one distinctive word carry it


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


# --- step 27c: query analysis, polarity, spelling, evidence rules ---------------------------------------

from fixit_mcp.retrieval.symptoms import (  # noqa: E402
    _PHRASES,
    _SYNONYM_WORDS,
    DISTINCTIVE_MAX_SYMPTOMS,
    OOV_WEIGHT_SHARE,
    Spelling,
    _fold,
    analyze_query,
    build_index,
    is_negated,
)


@pytest.mark.parametrize(
    ("text", "terms", "negated"),
    [
        ("the washer won't turn on", ["operat"], True),
        ("my washer doesn't start", ["operat"], True),
        ("nothing happens when I press it", ["operat", "press"], True),
        ("it just stopped working", ["operat"], True),
        ("the machine is dead", ["machin", "operat"], True),
        ("it turns on by itself", ["operat", "itself"], False),
        ("there is standing water", ["drain"], True),
        ("the fridge is not cold", ["cool"], True),
        ("the fridge is too warm", ["cool"], True),
        ("water all over the floor", ["leak"], False),
        ("not enough water", ["low", "water"], False),
        ("the lid is hard to close", ["lid", "difficult", "clos"], False),
    ],
)
def test_phrases_and_negation_become_the_manuals_words(text: str, terms: list[str], negated: bool) -> None:
    a = analyze_query(text)

    assert (a.terms, a.negated) == (terms, negated)


def test_negation_is_read_from_the_description_and_from_a_stored_symptoms_own_wording() -> None:
    assert analyze_query("it is dead").negated is True
    assert analyze_query("it is lit").negated is False
    assert is_negated("Water won’t drain") and is_negated("No fill") and not is_negated("Too many suds")


@pytest.mark.parametrize(
    ("text", "terms"),
    [
        ("really loud vibrating like crazy", ["sound", "rock"]),
        ("shirts and jeans came out torn", ["tear"]),
        ("a light is on", ["lit"]),
    ],
)
def test_fillers_and_garments_are_ignored_and_synonyms_folded(text: str, terms: list[str]) -> None:
    assert analyze_query(text).terms == terms


def test_an_unknown_word_stays_a_term_rather_than_being_ignored() -> None:
    assert "banana" in analyze_query("the washer smells of banana").terms


def test_polarity_must_agree_so_a_wont_spin_description_never_reaches_a_pauses_during_spin_row() -> None:
    index = build_index(
        [
            rec(WASHER, ["Drum won't spin"], ["Belt"], ["Replace it."]),
            rec(WASHER, ["Drum pauses during the spin cycle"], ["Soak option"], ["Wait."], page=6),
        ]
    )

    refused = index.search(index.analyze("my washer won't spin").terms, negated=True)
    positive = index.search(index.analyze("my washer spins and pauses").terms, negated=False)
    unfiltered = index.search(["spin"])

    assert [s.group.phrases[0] for s in refused] == ["Drum won't spin"]
    assert [s.group.phrases[0] for s in positive] == ["Drum pauses during the spin cycle"]
    assert [g.negated for g in index.groups] == [True, False]
    assert len(unfiltered) == 2, "without a polarity the search is as before"


def test_an_unknown_word_weighs_against_a_match_and_two_of_them_defeat_it() -> None:
    assert OOV_WEIGHT_SHARE >= 0.6
    assert _phrases("drum stays still totally") == ["Drum stays still"]  # 'totally' is a listed filler
    assert _phrases("drum stays still banana") == ["Drum stays still"]  # two real words outweigh one unknown
    assert (
        _phrases("drum banana") == []
    )  # an unknown word may be the real subject: one distinctive word is not enough
    assert _phrases("drum banana mango") == []


def test_one_distinctive_word_can_carry_a_match_and_a_common_word_cannot() -> None:
    assert DISTINCTIVE_MAX_SYMPTOMS == 2
    assert _phrases("chirping") == ["Alarm chirps"]  # a symptom word only one symptom uses
    assert _phrases("pours") != []  # used by two symptoms: still distinctive
    assert _phrases("pours banana") == []  # ...but not when the description also has an unknown word
    assert _phrases("inside banana") == []  # used by three symptoms: not distinctive at all


def test_a_word_found_only_in_a_cause_never_counts_toward_the_minimum() -> None:
    assert _phrases("hatch mildew") == []  # both are cause-only words
    assert _phrases("hatch latched") == []


def test_one_common_word_that_fits_many_symptoms_matches_none_of_them() -> None:
    many = build_index([rec(WASHER, [f"Sound number {n}"], ["c"], ["a"], page=n + 1) for n in range(5)])
    few = build_index([rec(WASHER, [f"Sound number {n}"], ["c"], ["a"], page=n + 1) for n in range(2)])

    assert many.search(["sound"]) == []
    assert len(few.search(["sound"])) == 2
    assert len(many.search(["sound", "number"])) == 5, "two matched words identify the group of symptoms"


# --- spelling -----------------------------------------------------------------------------------------


def _spelling(*terms: str) -> Spelling:
    return Spelling(frozenset(terms))


@pytest.mark.parametrize(
    ("typo", "fixed"),
    [("wrinkeld", "wrinkled"), ("dispencer", "dispenser"), ("refridgerator", "refrigerator")],
)
def test_a_one_character_slip_on_a_longer_word_is_mended(typo: str, fixed: str) -> None:
    assert _spelling("wrinkl", "dispenser", "drain").correct(typo) == fixed


def test_a_short_word_is_never_corrected() -> None:
    assert _spelling("leak").correct("leek") == "leek"
    assert _spelling("beep").correct("beap") == "beap"


def test_a_known_word_is_never_corrected_even_when_another_word_is_one_edit_away() -> None:
    assert _spelling("drain", "drawn").correct("drain") == "drain"
    assert _spelling("drain", "drawn").correct("drawn") == "drawn"


def test_two_equally_close_words_leave_the_word_alone() -> None:
    assert _spelling("gutter", "butter").correct("sutter") == "sutter"
    assert _spelling("gutter").correct("sutter") == "gutter"


def test_a_slip_two_edits_away_is_not_mended() -> None:
    assert _spelling("wrinkl").correct("wrnkeld") == "wrnkeld"


def test_a_misspelt_word_is_matched_after_the_correction() -> None:
    index = build_index([rec(WASHER, ["Wrinkling"], ["Overloading"], ["Load less."])])

    assert index.analyze("clothes come out wrinkeld").terms == ["cloth", "wrinkl"]
    assert [s.group.phrases[0] for s in index.search(index.analyze("wrinkeld").terms)] == ["Wrinkling"]


# --- every synonym and phrase maps onto words the stored rows use -------------------------------------


COMMITTED = load_symptom_index(DEFAULT_SYMPTOMS_PATH)
# "frozen" -> freeze was written in step 25b; its target only appears in a cause
# ("Water in reservoir is frozen"), so it is not required to be in a symptom phrase
CAUSE_ONLY_TARGETS = {"freez"}


def _targets() -> set[str]:
    out = {_fold(v) for v in _SYNONYM_WORDS.values()}
    for _phrase, produced in _PHRASES:
        out |= {_fold(t) for t in produced.split() if t and t != "!neg"}
    return out


def test_every_synonym_and_phrase_target_is_a_word_the_stored_rows_use() -> None:
    assert len(_targets()) >= 20
    for target in _targets():
        assert target in COMMITTED.idf, f"{target!r} appears in no stored row"
        if target not in CAUSE_ONLY_TARGETS:
            assert COMMITTED.symptom_df.get(target, 0) >= 1, f"{target!r} is in no symptom phrase"


def test_a_synonym_key_that_a_stored_symptom_phrase_uses_is_folded_the_same_way_on_both_sides() -> None:
    """A fold applies to the stored rows too, so tokenizing a stored phrase gives the same word as
    tokenizing the customer's version of it."""
    assert tokenize("Washer rocking/ moving") == ["washer", "rock", "mov"]
    assert tokenize("Washer shaking") == ["washer", "rock"]
    assert tokenize("Water won’t drain") == ["water", "drain"]


# --- step 27e: off-topic descriptions, nearest phrases, and spelling that must never delete a word -------


def test_a_description_with_an_unknown_word_and_no_distinctive_known_word_is_off_topic() -> None:
    assert INDEX.is_off_topic(INDEX.analyze("car inside").terms)  # 'inside' fits three symptoms
    assert not INDEX.is_off_topic(INDEX.analyze("car drum").terms)  # 'drum' is distinctive
    assert not INDEX.is_off_topic(INDEX.analyze("inside").terms)  # no unknown word at all
    assert not INDEX.is_off_topic([])


def test_an_off_topic_description_matches_nothing_even_with_two_known_common_words() -> None:
    from fixit_mcp.retrieval.symptoms import build_index

    index = build_index(
        [
            rec(WASHER, ["Water leaks"], ["Hose"], ["Tighten it."]),
            rec(WASHER, ["Water leaks from the door seal"], ["Seal"], ["Wipe it."], page=6),
            rec(WASHER, ["Water leaks under the tub"], ["Tub"], ["Level it."], page=7),
        ]
    )

    assert len(index.search(index.analyze("water leaks").terms)) == 3
    assert index.search(index.analyze("water leaks from the car").terms) == []
    assert index.nearest_phrases(index.analyze("water leaks from the car").terms) == []


def test_nearest_phrases_are_withheld_when_the_description_is_off_topic_and_kept_otherwise() -> None:
    assert (
        INDEX.nearest_phrases(INDEX.analyze("my car inside").terms) == []
    )  # unknown 'car', only a common word
    assert INDEX.nearest_phrases(INDEX.analyze("the drum plays music at night").terms) == ["Drum stays still"]
    assert INDEX.nearest_phrases(INDEX.analyze("cabinet inside").terms) != [], "no unknown word: offered"


def test_with_an_unknown_word_only_symptoms_that_share_a_distinctive_word_are_suggested() -> None:
    phrases = INDEX.nearest_phrases(INDEX.analyze("the drum is inside a banana").terms)

    assert phrases == ["Drum stays still"], "'inside' alone would also reach the fridge and washer rows"


def test_spelling_never_corrects_toward_a_word_the_matcher_ignores() -> None:
    # "turn" is a stopword on the query side but a word of the manuals' causes: "burning" must stay "burning"
    spelling = _spelling("turn", "drum")

    assert spelling.correct("burning") == "burning"
    assert analyze_query("burning smell", spelling).terms == ["burn", "odor"]


def test_phrase_words_are_known_words_but_never_correction_targets() -> None:
    spelling = _spelling("drum")

    assert spelling.correct("balls") == "balls"  # part of the 'fuzz balls' phrase: known, left alone
    assert spelling.correct("burning") == "burning"


def test_a_description_of_the_load_is_context_not_a_symptom_word() -> None:
    assert analyze_query("my whites are turning yellow").terms == ["yellow"]
    assert analyze_query("dark bedding came out gray").terms == ["gray"]
