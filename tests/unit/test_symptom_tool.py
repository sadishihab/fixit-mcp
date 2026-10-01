"""diagnose_symptom's resolution logic, on invented data (tests/symptom_fixtures.py)."""

from pathlib import Path

import pytest

from fixit_mcp.tools.diagnose import DIAGNOSE_ERROR_DESCRIPTION
from fixit_mcp.tools.symptoms import DIAGNOSE_SYMPTOM_DESCRIPTION, DiagnoseSymptomResult, diagnose_symptom
from tests.symptom_fixtures import synthetic_index, synthetic_records, synthetic_repository

INDEX = synthetic_index()
REPO = synthetic_repository()
SRC = Path(__file__).resolve().parents[2] / "src" / "fixit_mcp"


def run(household: str, symptom: str, **kw) -> DiagnoseSymptomResult:
    return diagnose_symptom(INDEX, REPO, household, symptom, **kw)


def test_found_for_the_one_registered_appliance_whose_manual_matches() -> None:
    result = run("h-both", "the drum stays still")

    assert result.status == "found" and result.appliance_registered is True
    assert (result.appliance.appliance_id, result.appliance.brand) == ("a-w", "Acme")
    (match,) = result.matches
    assert match.symptom == ["Drum stays still"] and match.symptom_label == "Problem"
    assert [r.possible_causes for r in match.rows] == [["Hatch not latched"], ["Plug is loose"]]
    assert [r.what_to_do for r in match.rows] == [["Close the hatch firmly."], ["Push the plug in."]]
    assert match.citation.model_dump() == {
        "brand": "Acme",
        "model": "W100",
        "page": 5,
        "section": "Troubleshooting Tips",
    }
    assert 0 < match.score <= 1
    assert (
        result.candidate_appliances == []
        and result.nearest_phrases == []
        and not result.suggest_add_appliance
    )


def test_a_found_result_never_carries_a_customer_word_into_the_manual_fields() -> None:
    result = run("h-washer", "the tub overflows and my husband is furious")

    allowed = {
        s for r in synthetic_records() for s in [*r.symptom, *r.possible_causes, *r.what_to_do, *r.footnotes]
    }
    allowed |= {r.response_label for r in synthetic_records()} | {
        r.symptom_label for r in synthetic_records()
    }
    strings = [s for m in result.matches for s in m.symptom]
    strings += [
        s
        for m in result.matches
        for row in m.rows
        for s in [*row.possible_causes, *row.what_to_do, *row.footnotes, row.response_label]
    ]
    assert strings and set(strings) <= allowed


def test_footnotes_and_the_reason_label_are_carried_and_announced() -> None:
    overflow = run("h-washer", "tub overflows")
    sound = run("h-washer", "whistling noise")

    (row,) = overflow.matches[0].rows
    assert row.footnotes == ["*Select models only"] and "footnote" in overflow.message
    assert sound.matches[0].symptom_label == "Sounds" and sound.matches[0].rows[0].response_label == "Reason"


def test_an_incomplete_row_is_flagged_and_the_message_says_not_to_finish_it() -> None:
    result = run("h-washer", "foul odor inside")

    assert result.matches[0].rows[0].text_incomplete is True
    assert "mid-sentence" in result.message


def test_two_registered_appliances_with_a_matching_entry_are_ambiguous_never_guessed() -> None:
    result = run("h-both", "water pours out")

    assert result.status == "ambiguous_appliance" and result.matches == []
    assert {c.appliance_id for c in result.candidate_appliances} == {"a-w", "a-f"}
    assert "which appliance" in result.message


def test_two_identical_registered_appliances_are_ambiguous_until_an_id_is_given() -> None:
    assert run("h-twins", "drum stays still").status == "ambiguous_appliance"

    narrowed = run("h-twins", "drum stays still", appliance_id="a-w2")

    assert narrowed.status == "found" and narrowed.appliance.appliance_id == "a-w2"


def test_the_appliance_type_given_resolves_the_ambiguity() -> None:
    result = run("h-both", "water pours out", appliance_type="refrigerator")

    assert result.status == "found" and result.appliance.appliance_id == "a-f"
    assert result.matches[0].symptom == ["Water pours out near the crisper"]


def test_appliance_type_synonyms_are_understood() -> None:
    assert run("h-both", "foul odor inside", appliance_type="fridge").appliance.appliance_id == "a-f"
    assert run("h-both", "foul odor inside", appliance_type="washer").appliance.appliance_id == "a-w"


def test_the_customers_own_type_word_narrows_the_search_when_no_type_is_given() -> None:
    result = run("h-both", "my fridge smells and the odor is inside")

    assert result.status == "found" and result.appliance.appliance_id == "a-f"


def test_two_type_words_do_not_narrow_anything() -> None:
    assert run("h-both", "water pours out of the washer and the fridge").status == "ambiguous_appliance"


def test_a_documented_entry_for_an_appliance_the_household_has_not_registered_says_so() -> None:
    result = run("h-fridge", "the drum stays still")

    assert result.status == "found" and result.appliance_registered is False
    assert result.suggest_add_appliance is True
    assert (result.appliance.appliance_id, result.appliance.brand, result.appliance.model) == (
        "",
        "Acme",
        "W100",
    )
    assert "isn't registered to this household" in result.message and "add_appliance" in result.message


def test_a_household_with_no_appliances_gets_the_unregistered_notice_not_a_guess() -> None:
    result = run("h-none", "the drum stays still")

    assert result.status == "found" and result.appliance_registered is False and result.suggest_add_appliance


def test_an_unregistered_description_matching_several_manuals_asks_which_appliance() -> None:
    result = run("h-none", "foul odor inside")

    assert result.status == "ambiguous_appliance"
    assert {(c.brand, c.model, c.appliance_id) for c in result.candidate_appliances} == {
        ("Acme", "W100", ""),
        ("Bravo", "R200", ""),
    }


def test_not_found_is_plain_with_the_nearest_phrases_and_a_pointer_to_error_codes() -> None:
    result = run("h-washer", "the drum plays music at night")

    assert result.status == "not_found" and result.matches == []
    assert result.nearest_phrases == ["Drum stays still"]
    assert "diagnose_error" in result.message
    assert result.suggest_add_appliance is False and result.appliance is None


def test_not_found_never_offers_a_cause_or_step() -> None:
    result = run("h-washer", "the television shows a blurry picture")

    assert result.status == "not_found"
    assert result.nearest_phrases == [] and result.matches == [] and result.candidate_appliances == []
    assert "cause" not in result.message.lower() and "try" not in result.message.lower()


def test_nearest_phrases_stay_within_the_households_own_appliances() -> None:
    result = run("h-fridge", "the drum plays music at night")

    assert result.nearest_phrases == []  # the only candidate is a washer phrase; this household owns a fridge


def test_not_found_suggests_adding_the_appliance_when_none_of_that_type_is_registered() -> None:
    result = run("h-fridge", "the television shows a blurry picture", appliance_type="washer")

    assert result.status == "not_found" and result.suggest_add_appliance is True
    assert "add_appliance" in result.message


def test_a_description_with_no_content_words_is_not_found_with_its_own_message() -> None:
    result = run("h-washer", "it is just not, I do, but it is")

    assert result.status == "not_found" and "no specific words" in result.message


def test_a_description_for_another_type_than_the_one_given_is_not_found() -> None:
    result = run("h-both", "the drum stays still", appliance_type="refrigerator")

    assert result.status == "not_found"


def test_the_descriptions_route_between_the_two_diagnosis_tools() -> None:
    assert "diagnose_error" in DIAGNOSE_SYMPTOM_DESCRIPTION and "household_id" in DIAGNOSE_SYMPTOM_DESCRIPTION
    assert "add_appliance" in DIAGNOSE_SYMPTOM_DESCRIPTION and "Reason" in DIAGNOSE_SYMPTOM_DESCRIPTION
    assert "diagnose_symptom" in DIAGNOSE_ERROR_DESCRIPTION


@pytest.mark.parametrize("module", ["tools/symptoms.py", "retrieval/symptoms.py", "tools/common.py"])
def test_no_model_or_ingestion_code_is_imported_by_the_server_side_symptom_path(module: str) -> None:
    source = (SRC / module).read_text()

    for forbidden in ("boto3", "bedrock", "anthropic", "fixit_mcp.ingestion", "converse("):
        assert forbidden not in source.lower(), (module, forbidden)
