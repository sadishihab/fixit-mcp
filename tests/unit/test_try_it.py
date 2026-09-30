"""scripts/try_it.py's formatting and walkthrough logic with fakes: no server,
no network. The real-server run is in tests/integration/test_try_it_script.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
spec = importlib.util.spec_from_file_location("fixit_try_it", SCRIPTS / "try_it.py")
try_it = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = try_it
spec.loader.exec_module(try_it)

DRYER = {"appliance_id": "app-005", "brand": "LG", "model": "DLEX8000W", "appliance_type": "dryer"}
WASHER = {"appliance_id": "", "brand": "LG", "model": "WM4000HWA", "appliance_type": "washing_machine"}

FOUND = {
    "status": "found",
    "message": "tE1: Temperature sensor failure",
    "appliance": DRYER,
    "appliance_registered": True,
    "meaning": "Temperature sensor failure",
    "likely_causes": ["Temperature sensor failure"],
    "repair_steps": ["Turn off the dryer", "Call for service"],
    "parts_needed": [],
    "safety_warnings": ["Unplug before servicing"],
    "citation": {"brand": "LG", "model": "DLEX8000W", "page": 31, "section": "Error codes"},
    "suggest_add_appliance": False,
}
NOT_FOUND = {
    "status": "not_found",
    "message": "No manual in our index documents an error code matching 'ZZ99'.",
    "nearest_matches": [],
    "family_note": None,
    "suggest_add_appliance": False,
}
EXPIRED = {
    "status": "expired",
    "message": "The recorded warranty for this LG DLEX8000W ended on 2025-01-15, 623 days ago.",
    "appliance": DRYER,
    "purchase_date": "2023-01-15",
    "warranty_end_date": "2025-01-15",
    "days_remaining": None,
    "days_since_expiry": 623,
    "candidate_appliances": [],
}


def test_found_diagnosis_shows_meaning_numbered_steps_warnings_and_citation() -> None:
    text = try_it.format_diagnosis(FOUND)

    assert "status: found" in text
    assert "LG DLEX8000W (dryer), registered to this household" in text
    assert "meaning: Temperature sensor failure" in text
    assert "1. Turn off the dryer" in text and "2. Call for service" in text
    assert "safety warnings:" in text and "- Unplug before servicing" in text
    assert 'source: LG DLEX8000W manual, page 31, section "Error codes"' in text
    assert "parts:" not in text  # empty lists are omitted, not printed empty


def test_found_for_an_unregistered_appliance_says_so_and_flags_add_appliance() -> None:
    result = {**FOUND, "appliance": WASHER, "appliance_registered": False, "suggest_add_appliance": True}

    text = try_it.format_diagnosis(result)

    assert "LG WM4000HWA (washing_machine), NOT registered to this household" in text
    assert "suggest_add_appliance: true" in text


def test_found_with_an_empty_meaning_never_fills_one_in() -> None:
    text = try_it.format_diagnosis({**FOUND, "meaning": "", "citation": None})

    assert "meaning: (the manual does not say)" in text
    assert "source:" not in text


def test_not_found_shows_the_message_and_no_diagnosis_fields() -> None:
    text = try_it.format_diagnosis(NOT_FOUND)

    assert "status: not_found" in text
    assert "'ZZ99'" in text
    assert "nearest codes: (none close enough)" in text
    assert "meaning:" not in text and "repair steps" not in text


def test_not_found_lists_nearest_codes_and_family_note() -> None:
    text = try_it.format_diagnosis(
        {**NOT_FOUND, "nearest_matches": ["tE1", "tE2"], "family_note": "E:xx-yy codes are pump faults."}
    )

    assert "nearest codes: tE1, tE2" in text
    assert "family note: E:xx-yy codes are pump faults." in text


def test_ambiguous_lists_candidates() -> None:
    text = try_it.format_diagnosis(
        {
            "status": "ambiguous_appliance",
            "message": "PF is documented for two appliances.",
            "candidate_appliances": [DRYER, WASHER],
        }
    )

    assert "status: ambiguous_appliance" in text
    assert "- LG DLEX8000W (dryer)" in text and "- LG WM4000HWA (washing_machine)" in text


def test_warranty_shows_dates_and_the_recorded_message_but_skips_null_fields() -> None:
    text = try_it.format_warranty(EXPIRED)

    assert "status: expired" in text
    assert "warranty_end_date: 2025-01-15" in text
    assert "days_since_expiry: 623" in text
    assert "days_remaining" not in text
    assert "recorded warranty" in text
    assert "never a coverage claim" in text


def test_format_result_dispatches_on_the_tool() -> None:
    assert try_it.format_result("check_warranty", EXPIRED) == try_it.format_warranty(EXPIRED)
    assert try_it.format_result("diagnose_error", FOUND) == try_it.format_diagnosis(FOUND)


def test_format_tools_keeps_the_name_column_and_the_first_sentence_only() -> None:
    text = try_it.format_tools(
        [("diagnose_error", "Look up an error code.  Call it when...\n more"), ("x", "")]
    )
    lines = text.splitlines()

    assert lines[0] == "  diagnose_error       Look up an error code"
    assert lines[1].startswith("  x    ")
    assert all(len(line) <= try_it.WIDTH for line in lines)


def test_format_tools_shortens_a_long_first_sentence_to_the_width() -> None:
    line = try_it.format_tools([("check_warranty", "word " * 40)])

    assert len(line) <= try_it.WIDTH
    assert line.endswith("...")


def test_long_lines_wrap_at_the_width() -> None:
    text = try_it.format_diagnosis({**FOUND, "repair_steps": ["a very long step " * 12]})

    assert all(len(line) <= try_it.WIDTH for line in text.splitlines() if "source:" not in line)


class FakeSession:
    def __init__(self, results: dict[str, Any]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict]] = []

    async def initialize(self) -> Any:
        return SimpleNamespace(serverInfo=SimpleNamespace(name="fixit-mcp"), protocolVersion="2025-11-25")

    async def list_tools(self) -> Any:
        return SimpleNamespace(tools=[SimpleNamespace(name="diagnose_error", description="Look up a code.")])

    async def call_tool(self, name: str, arguments: dict) -> Any:
        self.calls.append((name, arguments))
        result = self.results[arguments.get("error_code", name)]
        if isinstance(result, str):
            return SimpleNamespace(
                isError=True, content=[SimpleNamespace(text=result)], structuredContent=None
            )
        return SimpleNamespace(isError=False, content=[], structuredContent=result)


async def test_walkthrough_runs_every_step_in_order_and_formats_each_result() -> None:
    session = FakeSession({"tE1": FOUND, "check_warranty": EXPIRED, "IE": FOUND, "ZZ99": NOT_FOUND})

    sections = await try_it.walkthrough(session)
    text = "\n".join(sections)

    assert [call for call, _ in session.calls] == [tool for _, tool, _ in try_it.STEPS]
    assert all(args.get("household_id") == "house-002" for _, args in session.calls)
    assert "Connected: fixit-mcp, MCP protocol 2025-11-25" in text
    assert "diagnose_error       Look up a code" in text
    assert '> diagnose_error(error_code="ZZ99", household_id="house-002")' in text
    assert "status: expired" in text and "status: not_found" in text


async def test_walkthrough_reports_a_tool_error_and_keeps_going() -> None:
    session = FakeSession({"tE1": "boom", "check_warranty": EXPIRED, "IE": FOUND, "ZZ99": NOT_FOUND})

    text = "\n".join(await try_it.walkthrough(session))

    assert "tool error: boom" in text
    assert "status: not_found" in text


def test_every_step_is_read_only() -> None:
    assert {tool for _, tool, _ in try_it.STEPS} <= {"diagnose_error", "check_warranty", "list_my_appliances"}
