from datetime import date

from fixit_mcp.domain.models import Appliance, ErrorCodeRecord
from fixit_mcp.repository.in_memory import InMemoryApplianceRepository
from fixit_mcp.retrieval.codes import ErrorCodeIndex, is_lookupable
from fixit_mcp.tools.diagnose import diagnose


def make_record(**overrides) -> ErrorCodeRecord:
    defaults = dict(
        manual_id="acme-widget",
        brand="Acme",
        model="W100",
        appliance_type="widget",
        error_code="E1",
        code_normalized="E1",
        meaning="Widget fault.",
        likely_causes=["Something broke."],
        repair_steps=["Turn it off and on again."],
        parts_needed=[],
        safety_warnings=[],
        difficulty="easy",
        source_page=5,
        source_section="Troubleshooting",
        source_chunk_id="acme-widget::chunk-0001",
        extraction_confidence=0.9,
    )
    defaults.update(overrides)
    return ErrorCodeRecord(**defaults)


def make_index(records: list[ErrorCodeRecord]) -> ErrorCodeIndex:
    by_key: dict[tuple[str, str], ErrorCodeRecord] = {}
    lookupable: dict[str, list[ErrorCodeRecord]] = {}
    family: dict[str, list[ErrorCodeRecord]] = {}
    for record in records:
        by_key[(record.manual_id, record.code_normalized)] = record
        if is_lookupable(record):
            lookupable.setdefault(record.code_normalized, []).append(record)
        else:
            family.setdefault(record.manual_id, []).append(record)
    return ErrorCodeIndex(by_manual_and_code=by_key, lookupable_by_code=lookupable, family_by_manual=family)


def make_appliance(
    appliance_id: str, brand: str, model: str, appliance_type: str, manual_id: str
) -> Appliance:
    return Appliance(
        appliance_id=appliance_id,
        brand=brand,
        model=model,
        appliance_type=appliance_type,
        purchase_date=date(2023, 1, 1),
        warranty_end_date=date(2025, 1, 1),
        manual_id=manual_id,
    )


EMPTY_REPO = InMemoryApplianceRepository(seed={})


# --- exact hit -------------------------------------------------


def test_diagnose_exact_hit_with_no_household_context() -> None:
    index = make_index([make_record()])

    result = diagnose(index, EMPTY_REPO, "E1")

    assert result.status == "found"
    assert result.meaning == "Widget fault."
    assert result.likely_causes == ["Something broke."]
    assert result.repair_steps == ["Turn it off and on again."]
    assert result.appliance is None
    assert result.citation is not None
    assert result.citation.brand == "Acme"
    assert result.citation.page == 5
    assert result.confidence == 0.9


# --- normalization variants -------------------------------------------------


def test_diagnose_normalizes_hyphenated_input() -> None:
    index = make_index([make_record()])

    result = diagnose(index, EMPTY_REPO, "E-1")

    assert result.status == "found"
    assert result.code_normalized == "E1"


def test_diagnose_normalizes_lowercase_spaced_input() -> None:
    index = make_index([make_record()])

    result = diagnose(index, EMPTY_REPO, "e 1")

    assert result.status == "found"


def test_diagnose_normalizes_colon_dash_input() -> None:
    index = make_index([make_record(error_code="E:20-60", code_normalized="E2060")])

    result = diagnose(index, EMPTY_REPO, "e20 60")

    assert result.status == "found"
    assert result.error_code == "E:20-60"  # preserved manufacturer spelling, not the query's spelling


# --- household resolution -------------------------------------------------


def test_diagnose_resolves_via_household_when_exactly_one_owned_appliance_matches() -> None:
    record = make_record(manual_id="acme-widget")
    other = make_record(manual_id="other-thing", error_code="E9", code_normalized="E9")
    index = make_index([record, other])
    appliance = make_appliance("app-1", "Acme", "W100", "widget", "acme-widget")
    other_appliance = make_appliance("app-2", "Other", "T1", "toaster", "other-thing")
    repo = InMemoryApplianceRepository(seed={"house-1": [appliance, other_appliance]})

    result = diagnose(index, repo, "E1", household_id="house-1")

    assert result.status == "found"
    assert result.appliance is not None
    assert result.appliance.appliance_id == "app-1"


def test_diagnose_ambiguous_when_multiple_owned_appliances_match() -> None:
    record_a = make_record(manual_id="acme-widget-a", brand="Acme", model="W100")
    record_b = make_record(manual_id="acme-widget-b", brand="Acme", model="W200")
    index = make_index([record_a, record_b])
    appliance_a = make_appliance("app-1", "Acme", "W100", "widget", "acme-widget-a")
    appliance_b = make_appliance("app-2", "Acme", "W200", "widget", "acme-widget-b")
    repo = InMemoryApplianceRepository(seed={"house-1": [appliance_a, appliance_b]})

    result = diagnose(index, repo, "E1", household_id="house-1")

    assert result.status == "ambiguous_appliance"
    assert {c.appliance_id for c in result.candidate_appliances} == {"app-1", "app-2"}
    # Never guesses which one -- no diagnosis content leaks into an ambiguous response.
    assert result.repair_steps == []
    assert result.meaning == ""


def test_diagnose_appliance_id_narrows_within_household() -> None:
    record_a = make_record(manual_id="acme-widget-a")
    record_b = make_record(manual_id="acme-widget-b", brand="Acme", model="W200")
    index = make_index([record_a, record_b])
    appliance_a = make_appliance("app-1", "Acme", "W100", "widget", "acme-widget-a")
    appliance_b = make_appliance("app-2", "Acme", "W200", "widget", "acme-widget-b")
    repo = InMemoryApplianceRepository(seed={"house-1": [appliance_a, appliance_b]})

    result = diagnose(index, repo, "E1", household_id="house-1", appliance_id="app-1")

    assert result.status == "found"
    assert result.appliance.appliance_id == "app-1"


# --- unknown code -------------------------------------------------


def test_diagnose_unknown_code_is_not_found_and_invents_nothing() -> None:
    index = make_index([make_record(error_code="E12", code_normalized="E12")])

    result = diagnose(index, EMPTY_REPO, "E13")

    assert result.status == "not_found"
    assert result.meaning == ""
    assert result.repair_steps == []
    assert result.likely_causes == []
    assert result.citation is None


def test_diagnose_unknown_code_suggests_nearest_matches() -> None:
    index = make_index([make_record(error_code="E12", code_normalized="E12")])

    result = diagnose(index, EMPTY_REPO, "E13")

    assert "E12" in result.nearest_matches


# --- record with empty meaning (PS/PF/nP-style) -------------------------------------------------


def test_diagnose_leaves_meaning_empty_when_index_has_none() -> None:
    """Regression test for the real LG PS/PF/nP records (step 3a): the
    manual never states what the abbreviation stands for, and the tool must
    not fabricate one just because a code was matched."""
    record = make_record(
        error_code="PS",
        code_normalized="PS",
        meaning="",
        likely_causes=["Electric dryer power cord is not connected correctly."],
    )
    index = make_index([record])

    result = diagnose(index, EMPTY_REPO, "PS")

    assert result.status == "found"
    assert result.meaning == ""
    assert result.likely_causes == ["Electric dryer power cord is not connected correctly."]


# --- range/placeholder family records -------------------------------------------------


def test_diagnose_never_exact_matches_a_family_placeholder_record() -> None:
    family = make_record(
        error_code="F— and a number or letter",
        code_normalized="FANDANUMBERORLETTER",
    )
    index = make_index([family])

    result = diagnose(index, EMPTY_REPO, "F— and a number or letter")

    assert result.status == "not_found"


def test_diagnose_surfaces_family_note_when_household_appliance_manual_has_one() -> None:
    family = make_record(
        manual_id="acme-widget",
        error_code="F— and a number or letter",
        code_normalized="FANDANUMBERORLETTER",
        meaning="",
    )
    index = make_index([family])
    appliance = make_appliance("app-1", "Acme", "W100", "widget", "acme-widget")
    repo = InMemoryApplianceRepository(seed={"house-1": [appliance]})

    result = diagnose(index, repo, "F7", household_id="house-1")

    assert result.status == "not_found"
    assert result.family_note is not None
    assert "F— and a number or letter" in result.family_note


def test_diagnose_no_family_note_without_a_single_resolved_appliance() -> None:
    family = make_record(manual_id="acme-widget", error_code="F— and a number", code_normalized="FANDANUMBER")
    index = make_index([family])

    result = diagnose(index, EMPTY_REPO, "F7")

    assert result.status == "not_found"
    assert result.family_note is None
