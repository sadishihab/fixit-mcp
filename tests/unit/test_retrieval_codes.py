import json
from pathlib import Path

from fixit_mcp.domain.models import ErrorCodeRecord
from fixit_mcp.retrieval.codes import is_lookupable, load_index


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


# --- is_lookupable -------------------------------------------------


def test_is_lookupable_accepts_a_real_short_code() -> None:
    assert is_lookupable(make_record(error_code="E:20-60", code_normalized="E2060")) is True


def test_is_lookupable_accepts_a_short_letter_code() -> None:
    assert is_lookupable(make_record(error_code="tE1", code_normalized="TE1")) is True


def test_is_lookupable_rejects_a_range_description() -> None:
    record = make_record(error_code="E:01-00 to E:90-10", code_normalized="E0100TOE9010")
    assert is_lookupable(record) is False


def test_is_lookupable_rejects_a_placeholder_with_english_words() -> None:
    record = make_record(error_code="F— and a number or letter", code_normalized="FANDANUMBERORLETTER")
    assert is_lookupable(record) is False


# --- load_index: dedup -------------------------------------------------


def _write_index(tmp_path: Path, records: list[ErrorCodeRecord]) -> Path:
    path = tmp_path / "error_codes.json"
    path.write_text(json.dumps([r.model_dump() for r in records]))
    return path


def test_load_index_dedups_preferring_more_populated_record(tmp_path: Path) -> None:
    sparse = make_record(repair_steps=[], safety_warnings=[], extraction_confidence=0.99)
    rich = make_record(
        repair_steps=["Step one.", "Step two."],
        safety_warnings=["Do not do X."],
        extraction_confidence=0.5,
    )
    path = _write_index(tmp_path, [sparse, rich])

    index = load_index(path)

    winner = index.by_manual_and_code[("acme-widget", "E1")]
    assert winner.repair_steps == ["Step one.", "Step two."]
    assert winner.safety_warnings == ["Do not do X."]


def test_load_index_dedup_tiebreak_uses_confidence_when_populated_fields_tie(tmp_path: Path) -> None:
    """Regression test for the real Bosch E:34-00 case (step 3a's friction
    log): both records have one populated repair_steps list (just of
    different lengths, which doesn't affect the populated-*field*-count
    tiebreak), so confidence must decide."""
    incomplete = make_record(repair_steps=["Turn off the water faucet."], extraction_confidence=0.95)
    complete = make_record(
        repair_steps=["Turn off the water faucet.", "Call customer service."],
        extraction_confidence=1.0,
    )
    path = _write_index(tmp_path, [incomplete, complete])

    index = load_index(path)

    winner = index.by_manual_and_code[("acme-widget", "E1")]
    assert winner.extraction_confidence == 1.0
    assert len(winner.repair_steps) == 2


def test_load_index_keeps_records_from_different_manuals_separate(tmp_path: Path) -> None:
    a = make_record(manual_id="acme-widget-a")
    b = make_record(manual_id="acme-widget-b")
    path = _write_index(tmp_path, [a, b])

    index = load_index(path)

    assert len(index.by_manual_and_code) == 2


# --- load_index: lookupable vs family views -------------------------------------------------


def test_load_index_excludes_non_lookupable_from_lookupable_by_code(tmp_path: Path) -> None:
    family = make_record(error_code="F— and a number or letter", code_normalized="FANDANUMBERORLETTER")
    path = _write_index(tmp_path, [family])

    index = load_index(path)

    assert index.by_code("FANDANUMBERORLETTER") == []


def test_load_index_puts_non_lookupable_records_into_family_by_manual(tmp_path: Path) -> None:
    family = make_record(
        manual_id="acme-widget",
        error_code="F— and a number or letter",
        code_normalized="FANDANUMBERORLETTER",
        meaning="General fault family.",
    )
    path = _write_index(tmp_path, [family])

    index = load_index(path)

    note = index.family_note_for_manual("acme-widget")
    assert note is not None
    assert note.meaning == "General fault family."


def test_family_note_for_manual_is_none_when_manual_has_no_family_record(tmp_path: Path) -> None:
    record = make_record()
    path = _write_index(tmp_path, [record])

    index = load_index(path)

    assert index.family_note_for_manual("acme-widget") is None


# --- lookups -------------------------------------------------


def test_by_code_returns_empty_list_for_unknown_code(tmp_path: Path) -> None:
    path = _write_index(tmp_path, [make_record()])

    index = load_index(path)

    assert index.by_code("NOPE") == []


def test_by_code_returns_matching_records(tmp_path: Path) -> None:
    path = _write_index(tmp_path, [make_record()])

    index = load_index(path)

    results = index.by_code("E1")
    assert len(results) == 1
    assert results[0].error_code == "E1"


def test_nearest_codes_returns_close_matches(tmp_path: Path) -> None:
    records = [
        make_record(manual_id="a", error_code="E12", code_normalized="E12"),
        make_record(manual_id="b", error_code="E13", code_normalized="E13"),
        make_record(manual_id="c", error_code="Z999", code_normalized="Z999"),
    ]
    path = _write_index(tmp_path, records)

    index = load_index(path)

    nearest = index.nearest_codes("E14")
    assert "E12" in nearest or "E13" in nearest
    assert "Z999" not in nearest
