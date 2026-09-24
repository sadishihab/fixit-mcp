"""Tests for the diagnose_error MCP Apps visual card.

buildCardHtml() (in diagnose_card.html) is deliberately DOM-free and pure --
a plain string-templating function with no `document`/`postMessage`
dependency -- specifically so it can be exercised directly in a real JS
runtime (Node) without a browser or jsdom, giving these tests actual
coverage of the exact JS the resource ships, not a Python reimplementation
that could drift out of sync. Skipped (not failed) if `node` isn't on PATH,
so `make test` still passes on a machine without Node -- see FRICTION_LOG.md.
"""

import json
import re
import shutil
import subprocess

import pytest

from fixit_mcp.apps.resources import DIAGNOSE_CARD_HTML, DIAGNOSE_CARD_PATH, DIAGNOSE_CARD_RESOURCE_URI

NODE_PATH = shutil.which("node")
requires_node = pytest.mark.skipif(NODE_PATH is None, reason="node is not on PATH")


def _pure_render_js() -> str:
    """Extract buildCardHtml/esc/listHtml -- the DOM-free part of the
    template's <script> -- for direct execution in Node."""
    script = re.search(r"<script>([\s\S]*?)</script>", DIAGNOSE_CARD_HTML).group(1)
    pure_js, _, _handshake = script.partition("// MCP Apps handshake")
    return pure_js


def _build_card_html(result: dict) -> str:
    js = _pure_render_js() + f"\nconsole.log(buildCardHtml({json.dumps(result)}));\n"
    completed = subprocess.run([NODE_PATH, "-e", js], capture_output=True, text=True, timeout=10, check=True)
    return completed.stdout.strip()


FOUND_RESULT = {
    "status": "found",
    "error_code": "tE1",
    "code_normalized": "TE1",
    "appliance": {"appliance_id": "app-005", "brand": "LG", "model": "DLEX8000W", "appliance_type": "dryer"},
    "meaning": "Temperature sensor failure",
    "likely_causes": ["Temperature sensor failure"],
    "repair_steps": ["Turn off the dryer.", "Call for service."],
    "parts_needed": [],
    "safety_warnings": ["Do not touch the heating element."],
    "difficulty": "call_service",
    "confidence": 0.95,
    "citation": {"brand": "LG", "model": "DLEX8000W", "page": 31, "section": "Error Codes"},
}

NOT_FOUND_RESULT = {
    "status": "not_found",
    "message": "No manual in our index documents an error code matching 'E24'.",
    "error_code": "E24",
    "code_normalized": "E24",
    "nearest_matches": ["E9240", "TE2", "E6102"],
}

AMBIGUOUS_RESULT = {
    "status": "ambiguous_appliance",
    "message": "More than one of this household's appliances has a manual documenting E1 -- "
    "which appliance is showing this code?",
    "error_code": "E1",
    "code_normalized": "E1",
    "candidate_appliances": [
        {"appliance_id": "app-1", "brand": "GE", "model": "GFE28GYNFS", "appliance_type": "refrigerator"},
        {"appliance_id": "app-2", "brand": "Bosch", "model": "SHE53B75UC", "appliance_type": "dishwasher"},
    ],
}

NO_CLICK_HANDLER_MARKERS = ("onclick", "<a ", "<button", 'addEventListener("click')


# --- static template file -------------------------------------------------


def test_template_file_is_a_valid_html5_document() -> None:
    assert DIAGNOSE_CARD_HTML.strip().lower().startswith("<!doctype html>")
    assert "<html" in DIAGNOSE_CARD_HTML
    assert "</html>" in DIAGNOSE_CARD_HTML


def test_template_is_loaded_once_at_import_time_not_per_call() -> None:
    # DIAGNOSE_CARD_HTML is a plain module-level str constant, not a
    # function -- reading DIAGNOSE_CARD_PATH here is the *test's* check that
    # the loaded constant matches the file, not something the server does
    # per request.
    assert DIAGNOSE_CARD_HTML == DIAGNOSE_CARD_PATH.read_text()


def test_resource_uri_uses_the_ui_scheme() -> None:
    assert DIAGNOSE_CARD_RESOURCE_URI.startswith("ui://")


def test_template_has_no_client_side_network_fetching() -> None:
    """All data must arrive via the postMessage handshake, never a fetch."""
    assert "fetch(" not in DIAGNOSE_CARD_HTML
    assert "XMLHttpRequest" not in DIAGNOSE_CARD_HTML


# --- rendering logic (executed in a real JS runtime) -------------------------------------------------


@requires_node
def test_found_result_renders_error_code_and_appliance() -> None:
    html = _build_card_html(FOUND_RESULT)
    assert "tE1" in html
    assert "LG DLEX8000W" in html


@requires_node
def test_found_result_renders_numbered_repair_steps_in_order() -> None:
    html = _build_card_html(FOUND_RESULT)
    assert html.index("Turn off the dryer.") < html.index("Call for service.")
    assert "<ol>" in html


@requires_node
def test_found_result_renders_safety_warnings_in_a_distinct_block() -> None:
    html = _build_card_html(FOUND_RESULT)
    assert 'class="safety-warnings"' in html
    assert "Do not touch the heating element." in html


@requires_node
def test_found_result_renders_citation() -> None:
    html = _build_card_html(FOUND_RESULT)
    assert "LG DLEX8000W" in html
    assert "31" in html
    assert "Error Codes" in html


@requires_node
def test_found_result_without_safety_warnings_omits_the_block() -> None:
    result = {**FOUND_RESULT, "safety_warnings": []}
    html = _build_card_html(result)
    assert "safety-warnings" not in html


@requires_node
def test_found_result_with_empty_meaning_does_not_fabricate_one() -> None:
    """Regression case for the real LG PS/PF/nP records: an empty meaning
    field must stay absent from the card, never filled in with placeholder
    text."""
    result = {**FOUND_RESULT, "meaning": ""}
    html = _build_card_html(result)
    assert 'class="meaning"' not in html


@requires_node
def test_html_special_characters_in_content_are_escaped() -> None:
    result = {**FOUND_RESULT, "meaning": '<script>alert(1)</script> & "quoted"'}
    html = _build_card_html(result)
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


@requires_node
def test_none_result_renders_nothing() -> None:
    assert _build_card_html(None) == ""


@requires_node
def test_unrecognized_status_renders_nothing() -> None:
    assert _build_card_html({"status": "something_else"}) == ""


# --- not_found: muted, informational state -------------------------------------------------


@requires_node
def test_not_found_shows_the_queried_code() -> None:
    html = _build_card_html(NOT_FOUND_RESULT)
    assert "E24" in html


@requires_node
def test_not_found_shows_a_short_message() -> None:
    html = _build_card_html(NOT_FOUND_RESULT)
    assert "state-message" in html


@requires_node
def test_not_found_lists_nearest_matches() -> None:
    html = _build_card_html(NOT_FOUND_RESULT)
    for code in NOT_FOUND_RESULT["nearest_matches"]:
        assert code in html


@requires_node
def test_not_found_with_no_nearest_matches_omits_the_list() -> None:
    result = {**NOT_FOUND_RESULT, "nearest_matches": []}
    html = _build_card_html(result)
    assert "Closest known codes" not in html


@requires_node
def test_not_found_is_visually_distinct_from_the_found_card() -> None:
    html = _build_card_html(NOT_FOUND_RESULT)
    assert 'class="state-card state-not-found"' in html
    assert 'class="card">' not in html


@requires_node
def test_not_found_uses_muted_styling_not_a_found_style_class() -> None:
    html = _build_card_html(NOT_FOUND_RESULT)
    # No difficulty/warning classes -- those are reserved for the found card
    # and would visually read as "error" rather than "different state".
    assert "difficulty" not in html
    assert "safety-warnings" not in html


@requires_node
def test_not_found_has_no_click_handlers() -> None:
    html = _build_card_html(NOT_FOUND_RESULT)
    for marker in NO_CLICK_HANDLER_MARKERS:
        assert marker not in html


# --- ambiguous_appliance: muted, informational state -------------------------------------------------


@requires_node
def test_ambiguous_lists_candidate_appliances() -> None:
    html = _build_card_html(AMBIGUOUS_RESULT)
    assert "GE GFE28GYNFS" in html
    assert "refrigerator" in html
    assert "Bosch SHE53B75UC" in html
    assert "dishwasher" in html


@requires_node
def test_ambiguous_shows_the_backend_message() -> None:
    html = _build_card_html(AMBIGUOUS_RESULT)
    assert "which appliance is showing this code" in html


@requires_node
def test_ambiguous_with_no_candidates_omits_the_list() -> None:
    result = {**AMBIGUOUS_RESULT, "candidate_appliances": []}
    html = _build_card_html(result)
    assert "<ul" not in html


@requires_node
def test_ambiguous_is_visually_distinct_from_the_found_and_not_found_cards() -> None:
    html = _build_card_html(AMBIGUOUS_RESULT)
    assert 'class="state-card state-ambiguous"' in html
    assert "state-not-found" not in html
    assert 'class="card">' not in html


@requires_node
def test_ambiguous_has_no_click_handlers() -> None:
    html = _build_card_html(AMBIGUOUS_RESULT)
    for marker in NO_CLICK_HANDLER_MARKERS:
        assert marker not in html


@requires_node
def test_ambiguous_candidate_html_is_escaped() -> None:
    result = {
        **AMBIGUOUS_RESULT,
        "candidate_appliances": [
            {"appliance_id": "app-1", "brand": "<b>Evil</b>", "model": "X", "appliance_type": "widget"}
        ],
    }
    html = _build_card_html(result)
    assert "<b>Evil</b>" not in html
    assert "&lt;b&gt;" in html
