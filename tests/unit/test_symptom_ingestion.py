"""Symptom-table reading, the audit gate, the Nova extractor and the record builder.

Synthetic strings and a synthetic ruled-table PDF only: no real manual text, no
network, no AWS (a fake Bedrock client stands in for `converse`).
"""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from fixit_mcp.ingestion.symptom_extraction import (
    Budget,
    BudgetExceeded,
    ExtractedRow,
    NovaSymptomExtractor,
    TableResult,
    assert_nova_model,
    audit_rows,
    build_records,
    ends_mid_sentence,
    expected_footnotes,
    parse_rows,
)
from fixit_mcp.ingestion.symptom_tables import (
    SymptomTable,
    TableReadError,
    TableRow,
    read_symptom_tables,
    render_for_model,
    repair_span,
)

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load_script():
    spec = importlib.util.spec_from_file_location("fixit_extract_symptoms", SCRIPTS / "extract_symptoms.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


extract_symptoms = _load_script()


# --- synthetic table + PDF -------------------------------------------------


def _table(
    rows: list[tuple[list[str], list[str], list[str]]], footnotes: list[str] | None = None
) -> SymptomTable:
    return SymptomTable(
        manual_id="acme-x1",
        page=3,
        table_index=0,
        headers=("Problem", "Possible Causes", "What To Do"),
        rows=[TableRow(*r) for r in rows],
        footnotes=footnotes or [],
        section="Troubleshooting Tips",
    )


ROWS = [
    (["Gizmo hums loudly", "Gizmo rattles"], ["Loose widget"], ["Tighten the widget.", "Call the shop."]),
    ([], ["Dirty sprocket"], ["Wipe the sprocket with a cloth."]),
    (["Lamp stays dark*"], ["Bulb is out"], ["Fit a new bulb**"]),
]
FOOTNOTES = ["*Select models only", "**Order the bulb from the shop."]


def _make_pdf(path: Path, headers: tuple[str, str, str], rows: list[list[str]], notes: list[str]) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((60, 60), "Troubleshooting Tips", fontsize=14)
    xs = [50, 200, 350, 560]
    row_h = 60
    top = 80
    all_rows = [list(headers), *rows]
    for r, cells in enumerate(all_rows):
        y0 = top + r * row_h
        for c in range(3):
            rect = pymupdf.Rect(xs[c], y0, xs[c + 1], y0 + row_h)
            page.draw_rect(rect, color=(0, 0, 0), width=0.8)
            if cells[c]:
                page.insert_textbox(rect + (4, 4, -4, -4), cells[c], fontsize=9)
    page.insert_text((50, top + len(all_rows) * row_h + 20), "\n".join(notes), fontsize=8)
    doc.save(str(path))
    doc.close()


def test_read_symptom_tables_returns_rows_with_blank_cells_and_footnotes(tmp_path: Path) -> None:
    pdf = tmp_path / "t.pdf"
    _make_pdf(
        pdf,
        ("Problem", "Possible Causes", "What To Do"),
        [
            ["Gizmo hums", "Loose widget", "Tighten it."],
            ["", "Dirty sprocket", "Wipe it."],
            ["Lamp dark*", "Bulb out", "New bulb**"],
        ],
        ["*Select models only", "**Order the bulb from the shop."],
    )

    (table,) = read_symptom_tables(pdf, "acme-x1", offset=None)

    assert table.page == 1
    assert table.headers == ("Problem", "Possible Causes", "What To Do")
    assert [r.text(0) for r in table.rows] == ["Gizmo hums", "", "Lamp dark*"]
    assert [r.text(2) for r in table.rows] == ["Tighten it.", "Wipe it.", "New bulb**"]
    assert table.footnotes == ["*Select models only", "**Order the bulb from the shop."]
    assert table.section == "Troubleshooting Tips"


def test_a_table_with_other_headers_is_not_a_symptom_table(tmp_path: Path) -> None:
    pdf = tmp_path / "t.pdf"
    _make_pdf(pdf, ("Item", "Possible Causes", "Cost"), [["a", "b", "c"]], [])

    assert read_symptom_tables(pdf, "acme-x1", offset=None) == []


def test_a_sounds_table_keeps_its_own_headers(tmp_path: Path) -> None:
    pdf = tmp_path / "t.pdf"
    _make_pdf(pdf, ("Sounds", "Possible Causes", "Reason"), [["Buzzing", "Motor", "It spins."]], [])

    (table,) = read_symptom_tables(pdf, "acme-x1", offset=None)

    assert table.headers == ("Sounds", "Possible Causes", "Reason")


def test_render_for_model_shows_each_cell_as_printed_lines_and_blank_cells() -> None:
    text = render_for_model(_table([ROWS[1]]))

    assert "ROW 1" in text
    assert "  Problem: (blank)" in text
    assert "    | Dirty sprocket" in text


# --- span repair ------------------------------------------------------------


def test_repair_span_shifts_a_corrupted_span_by_the_established_offset() -> None:
    corrupted = "".join(chr(ord(c) - 29) for c in "Hello, world.")  # space -> \x03

    assert repair_span(corrupted, 29) == "Hello, world."


def test_repair_span_leaves_clean_text_alone_even_with_an_offset() -> None:
    assert repair_span("Already clean text.", 29) == "Already clean text."


def test_repair_span_without_an_offset_never_guesses() -> None:
    corrupted = "".join(chr(ord(c) - 29) for c in "Hello world")

    assert repair_span(corrupted, None) == corrupted


def test_repair_span_restores_control_characters_that_stand_for_punctuation() -> None:
    # tab, VT and CR are '&', '(' and '*' in a +29 font; a flattening step would turn them into spaces
    corrupted = "".join(chr(ord(c) - 29) for c in "A&B (x) y**")

    assert repair_span(corrupted, 29) == "A&B (x) y**"


def test_repair_span_maps_the_hand_checked_quote_characters_only_inside_a_corrupted_span() -> None:
    corrupted = "³" + "".join(chr(ord(c) - 29) for c in "Hi there") + "´"

    assert repair_span(corrupted, 29) == "“Hi there”"
    assert repair_span("³ clean", 29) == "³ clean"


def test_unrepaired_control_characters_fail_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    from fixit_mcp.ingestion import symptom_tables

    monkeypatch.setattr(symptom_tables, "_span_lines", lambda page, clip, offset: [(0.0, "a\x03b")])

    with pytest.raises(TableReadError, match="control characters"):
        symptom_tables._cell_items(None, (0, 0, 1, 1), None)


# --- audit ------------------------------------------------------------------


def _answer(table: SymptomTable) -> list[ExtractedRow]:
    return [
        ExtractedRow(
            symptom=r.problem,
            possible_causes=r.causes,
            what_to_do=r.actions,
            footnotes=expected_footnotes(r, table.footnotes),
        )
        for r in table.rows
    ]


def test_a_faithful_answer_passes_the_audit() -> None:
    table = _table(ROWS, FOOTNOTES)

    assert audit_rows(table, _answer(table)) == []


def test_wrapped_lines_may_be_joined_with_one_space() -> None:
    table = _table([(["Gizmo hums", "loudly"], ["Loose"], ["Fix it"])])
    answer = [ExtractedRow(symptom=["Gizmo hums loudly"], possible_causes=["Loose"], what_to_do=["Fix it"])]

    assert audit_rows(table, answer) == []


def test_an_empty_answer_is_rejected() -> None:
    assert "empty answer" in audit_rows(_table(ROWS), [])[0].message


def test_a_short_answer_is_rejected_on_row_count() -> None:
    table = _table(ROWS, FOOTNOTES)

    (problem,) = audit_rows(table, _answer(table)[:2])

    assert "row count" in problem.message and problem.row is None


def test_a_dropped_line_is_caught() -> None:
    table = _table(ROWS, FOOTNOTES)
    answer = _answer(table)
    answer[0].what_to_do = ["Tighten the widget."]

    problems = audit_rows(table, answer)

    assert [p.row for p in problems] == [1] and "what_to_do" in problems[0].message


def test_an_added_word_is_caught() -> None:
    table = _table(ROWS, FOOTNOTES)
    answer = _answer(table)
    answer[1].possible_causes = ["Dirty sprocket, usually"]

    assert any("possible_causes" in p.message for p in audit_rows(table, answer))


def test_a_changed_case_or_quote_is_caught_because_nothing_but_whitespace_is_normalized() -> None:
    table = _table([(["It says “Go”"], ["Cause"], ["Act"])])
    answer = [ExtractedRow(symptom=['It says "Go"'], possible_causes=["Cause"], what_to_do=["Act"])]

    assert audit_rows(table, answer)


def test_a_symptom_given_for_a_blank_problem_cell_is_caught() -> None:
    table = _table(ROWS, FOOTNOTES)
    answer = _answer(table)
    answer[1].symptom = ["Gizmo hums loudly"]

    assert any("symptom" in p.message for p in audit_rows(table, answer))


def test_a_wrong_footnote_link_is_caught() -> None:
    table = _table(ROWS, FOOTNOTES)
    answer = _answer(table)
    answer[2].footnotes = ["*Select models only"]

    assert any("footnotes" in p.message for p in audit_rows(table, answer))


def test_an_empty_string_in_a_list_is_caught() -> None:
    table = _table([(["Gizmo"], ["Cause"], ["Act"])])
    answer = [ExtractedRow(symptom=["Gizmo", ""], possible_causes=["Cause"], what_to_do=["Act"])]

    assert any("empty string" in p.message for p in audit_rows(table, answer))


def test_expected_footnotes_follow_the_markers_in_the_row_itself() -> None:
    star = TableRow(["Dark*"], [], [])
    double = TableRow(["Dark"], [], ["Buy it**"])
    both = TableRow(["Dark*"], [], ["Buy it**"])
    none = TableRow(["Dark"], [], ["Buy it"])

    assert expected_footnotes(star, FOOTNOTES) == ["*Select models only"]
    assert expected_footnotes(double, FOOTNOTES) == ["**Order the bulb from the shop."]
    assert expected_footnotes(both, FOOTNOTES) == FOOTNOTES  # page order
    assert expected_footnotes(none, FOOTNOTES) == []


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("Switch to the thing such as", True),
        ("Switch to the thing such as .", True),
        ("Use less of the", True),
        ("Wipe it with a cloth.", False),
        ("Replace the filter, or install the plug **", False),
        ("Press Start and", True),
        ("See page 14.", False),
    ],
)
def test_ends_mid_sentence(text: str, flagged: bool) -> None:
    assert ends_mid_sentence(text) is flagged


# --- parse + extractor with a fake Bedrock client ----------------------------


class FakeConverse:
    """Stands in for bedrock-runtime. Replies are consumed in order; usage is fixed."""

    def __init__(self, replies: list[str], in_tokens: int = 1000, out_tokens: int = 500) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []
        self.usage = {"inputTokens": in_tokens, "outputTokens": out_tokens}

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        text = self.replies.pop(0)
        return {"output": {"message": {"content": [{"text": text}]}}, "usage": self.usage}


def _good_json(table: SymptomTable) -> str:
    return json.dumps([r.model_dump() for r in _answer(table)])


def _extractor(client: FakeConverse, **kw: Any) -> NovaSymptomExtractor:
    return NovaSymptomExtractor(client=client, budget=kw.pop("budget", Budget(cap_usd=1.0)), **kw)


def test_parse_rows_strips_a_code_fence_and_rejects_extra_keys() -> None:
    rows = parse_rows(
        '```json\n[{"symptom": ["a"], "possible_causes": [], "what_to_do": [], "footnotes": []}]\n```'
    )
    assert rows[0].symptom == ["a"]
    with pytest.raises(ValueError):
        parse_rows('[{"symptom": ["a"], "meaning": "invented"}]')
    with pytest.raises(ValueError):
        parse_rows('{"symptom": []}')


def test_extract_table_accepts_a_faithful_first_answer() -> None:
    table = _table(ROWS, FOOTNOTES)
    client = FakeConverse([_good_json(table)])

    result = _extractor(client).extract_table("Acme", "X1", "gizmo", table)

    assert result.accepted and result.attempts == 1 and len(client.calls) == 1
    assert client.calls[0]["inferenceConfig"]["temperature"] == 0


def test_an_empty_answer_is_retried_and_the_retry_can_succeed() -> None:
    table = _table(ROWS, FOOTNOTES)
    client = FakeConverse(["[]", _good_json(table)])

    result = _extractor(client).extract_table("Acme", "X1", "gizmo", table)

    assert result.accepted and result.attempts == 2
    assert "rejected" in client.calls[1]["messages"][0]["content"][0]["text"]


def test_a_short_answer_is_retried() -> None:
    table = _table(ROWS, FOOTNOTES)
    short = json.dumps([r.model_dump() for r in _answer(table)[:1]])
    client = FakeConverse([short, _good_json(table)])

    result = _extractor(client).extract_table("Acme", "X1", "gizmo", table)

    assert result.accepted and result.attempts == 2


def test_an_unparseable_answer_is_retried() -> None:
    table = _table(ROWS, FOOTNOTES)
    client = FakeConverse(["not json at all", _good_json(table)])

    assert _extractor(client).extract_table("Acme", "X1", "gizmo", table).accepted


def test_the_extractor_gives_up_after_max_attempts_and_reports_why() -> None:
    table = _table(ROWS, FOOTNOTES)
    client = FakeConverse(["[]", "[]", "[]"])

    result = _extractor(client, max_attempts=3).extract_table("Acme", "X1", "gizmo", table)

    assert not result.accepted and result.attempts == 3 and len(client.calls) == 3
    assert "empty answer" in result.problems[0].message


def test_an_accepted_answer_is_cached_and_the_second_run_makes_no_call(tmp_path: Path) -> None:
    table = _table(ROWS, FOOTNOTES)
    first = FakeConverse([_good_json(table)])
    _extractor(first, cache_dir=tmp_path).extract_table("Acme", "X1", "gizmo", table)

    second = FakeConverse([])
    result = _extractor(second, cache_dir=tmp_path).extract_table("Acme", "X1", "gizmo", table)

    assert result.accepted and result.cached and second.calls == []


def test_a_cached_answer_is_re_audited_not_trusted(tmp_path: Path) -> None:
    table = _table(ROWS, FOOTNOTES)
    first = FakeConverse([_good_json(table)])
    ex = _extractor(first, cache_dir=tmp_path)
    ex.extract_table("Acme", "X1", "gizmo", table)
    (cache_file,) = tmp_path.glob("*.json")
    cache_file.write_text("[]")

    second = FakeConverse([_good_json(table)])
    result = _extractor(second, cache_dir=tmp_path).extract_table("Acme", "X1", "gizmo", table)

    assert result.accepted and not result.cached and len(second.calls) == 1


def test_force_ignores_the_cache(tmp_path: Path) -> None:
    table = _table(ROWS, FOOTNOTES)
    _extractor(FakeConverse([_good_json(table)]), cache_dir=tmp_path).extract_table(
        "Acme", "X1", "gizmo", table
    )

    client = FakeConverse([_good_json(table)])
    result = _extractor(client, cache_dir=tmp_path, force=True).extract_table("Acme", "X1", "gizmo", table)

    assert not result.cached and len(client.calls) == 1


def test_the_budget_cap_stops_before_the_call_that_would_pass_it() -> None:
    table = _table(ROWS, FOOTNOTES)
    client = FakeConverse([_good_json(table)])

    with pytest.raises(BudgetExceeded):
        _extractor(client, budget=Budget(cap_usd=0.0000001)).extract_table("Acme", "X1", "gizmo", table)

    assert client.calls == []


def test_actual_spend_is_tracked_from_reported_usage() -> None:
    table = _table(ROWS, FOOTNOTES)
    budget = Budget(cap_usd=1.0)
    client = FakeConverse([_good_json(table)], in_tokens=1_000_000, out_tokens=1_000_000)

    _extractor(client, budget=budget).extract_table("Acme", "X1", "gizmo", table)

    assert budget.spent_usd == pytest.approx(0.80 + 3.20)


@pytest.mark.parametrize(
    "model_id",
    ["us.anthropic.claude-opus-4-6-v1", "anthropic.claude-sonnet-5", "us.meta.llama3-1-70b", "gpt-4"],
)
def test_only_nova_models_are_allowed(model_id: str) -> None:
    with pytest.raises(ValueError, match="Nova"):
        assert_nova_model(model_id)
    with pytest.raises(ValueError):
        NovaSymptomExtractor(model_id=model_id, client=FakeConverse([]), budget=Budget(cap_usd=1.0))


# --- records ------------------------------------------------------------------


def _result(table: SymptomTable) -> TableResult:
    return TableResult(table=table, rows=_answer(table))


def test_build_records_carries_the_symptom_into_blank_rows_and_derives_footnotes() -> None:
    records, notes = build_records(
        [_result(_table(ROWS, FOOTNOTES))], brand="Acme", model="X1", appliance_type="gizmo"
    )

    assert [r.symptom_continued for r in records] == [False, True, False]
    assert records[1].symptom == ["Gizmo hums loudly", "Gizmo rattles"]
    assert records[1].possible_causes == ["Dirty sprocket"]
    assert records[2].footnotes == [FOOTNOTES[0], FOOTNOTES[1]]
    assert all(r.response_label == "What To Do" and r.symptom_label == "Problem" for r in records)
    assert all(r.source_page == 3 and r.source_section == "Troubleshooting Tips" for r in records)
    assert notes == []


def test_build_records_flags_a_row_that_ends_mid_sentence() -> None:
    table = _table([(["Gizmo"], ["Cause"], ["Use a detergent such as"])])

    records, notes = build_records([_result(table)], brand="Acme", model="X1", appliance_type="gizmo")

    assert records[0].text_incomplete is True
    assert any("mid-sentence" in n for n in notes)


def test_build_records_continues_a_symptom_across_a_page_break() -> None:
    first = _table([(["Gizmo"], ["Cause"], ["Act"])])
    second = _table([([], ["More"], ["Steps"])])
    second.page = 4

    records, notes = build_records(
        [_result(first), _result(second)], brand="Acme", model="X1", appliance_type="gizmo"
    )

    assert records[1].symptom == ["Gizmo"] and records[1].symptom_continued is True
    assert records[1].source_page == 4
    assert any("previous table" in n for n in notes)


def test_build_records_refuses_a_blank_first_problem_cell() -> None:
    with pytest.raises(ValueError, match="nothing to continue"):
        build_records([_result(_table([([], ["c"], ["a"])]))], brand="A", model="M", appliance_type="t")


# --- the script's merge --------------------------------------------------------


def test_merge_index_replaces_only_the_named_manuals_records(tmp_path: Path) -> None:
    path = tmp_path / "symptoms.json"
    path.write_text(json.dumps([{"manual_id": "old", "x": 1}, {"manual_id": "other", "x": 2}]))

    kept, written = extract_symptoms.merge_index(path, {"old"}, [{"manual_id": "old", "x": 3}])

    assert (kept, written) == (1, 1)
    assert json.loads(path.read_text()) == [{"manual_id": "old", "x": 3}, {"manual_id": "other", "x": 2}]


def test_the_script_dry_run_makes_no_bedrock_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(extract_symptoms, "PDF_DIR", tmp_path)  # no PDFs: the run reports and exits 1
    monkeypatch.setattr(
        extract_symptoms,
        "NovaSymptomExtractor",
        lambda **kw: (_ for _ in ()).throw(AssertionError("a dry run must not build an extractor")),
    )

    assert extract_symptoms.main(["--dry-run"]) == 1


def test_the_default_manuals_are_the_two_supported_ge_manuals() -> None:
    assert extract_symptoms.DEFAULT_MANUAL_IDS == ("ge-gfe28gynfs-refrigerator", "ge-gtw680bsjws-washer")
    assert extract_symptoms.DEFAULT_MAX_COST_USD == 1.00


# --- line joining, reviewed fixes, attempt history ---------------------------------------


def test_join_lines_joins_after_a_real_hyphen_without_a_space() -> None:
    from fixit_mcp.ingestion.symptom_tables import join_lines

    assert join_lines(["a non-", "stick pan"]) == "a non-stick pan"
    assert join_lines(["re-", "assembled"]) == "re-assembled"
    assert join_lines(["Step one -", "Step two"]) == "Step one - Step two"  # a dash, not a word hyphen
    assert join_lines(["ends with a-", "Capital"]) == "ends with a- Capital"
    assert join_lines(["plain", "", "lines"]) == "plain lines"
    assert join_lines(["at 120\u00b0F\u2013140\u00b0F (48\u00b0C\u2013", "60\u00b0C)"]) == (
        "at 120\u00b0F\u2013140\u00b0F (48\u00b0C\u201360\u00b0C)"
    )
    assert join_lines(["a pause \u2013", "then more"]) == "a pause \u2013 then more"


def test_a_row_cell_text_uses_the_hyphen_aware_join() -> None:
    table = _table([(["Gizmo"], ["If doors were re-", "assembled"], ["Act"])])
    answer = [
        ExtractedRow(symptom=["Gizmo"], possible_causes=["If doors were re-assembled"], what_to_do=["Act"])
    ]

    assert audit_rows(table, answer) == []


def test_reviewed_text_fixes_apply_only_to_the_named_string() -> None:
    from fixit_mcp.ingestion.symptom_tables import _apply_fixes

    assert _apply_fixes(",MPORTANT: Do not", {",MPORTANT:": "IMPORTANT:"}) == "IMPORTANT: Do not"
    assert _apply_fixes("Leave , alone", {",MPORTANT:": "IMPORTANT:"}) == "Leave , alone"
    assert _apply_fixes("unchanged", None) == "unchanged"


def test_each_rejected_attempt_keeps_its_problems_for_the_report() -> None:
    table = _table(ROWS, FOOTNOTES)
    client = FakeConverse(["[]", _good_json(table)])

    result = _extractor(client).extract_table("Acme", "X1", "gizmo", table)

    assert result.accepted and len(result.attempt_problems) == 1
    assert "empty answer" in result.attempt_problems[0][0].message
