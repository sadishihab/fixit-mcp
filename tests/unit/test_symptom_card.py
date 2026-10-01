"""Tests for the diagnose_symptom MCP Apps visual card (step 27a).

Like test_diagnose_card.py: the card's buildCardHtml() is DOM-free, so it is executed in Node against
invented results (Acme/Bravo, no manual text). Skipped, not failed, if `node` is not on PATH.
"""

import json
import re
import shutil
import subprocess

import pytest

from fixit_mcp.apps.resources import (
    DIAGNOSE_CARD_HTML,
    SYMPTOM_CARD_HTML,
    SYMPTOM_CARD_NAME,
    SYMPTOM_CARD_PATH,
    SYMPTOM_CARD_RESOURCE_URI,
    assemble_card,
)

NODE_PATH = shutil.which("node")
requires_node = pytest.mark.skipif(NODE_PATH is None, reason="node is not on PATH")


def _pure_render_js() -> str:
    script = re.search(r"<script>([\s\S]*?)</script>", SYMPTOM_CARD_HTML).group(1)
    return script.partition("// MCP Apps handshake")[0]


def build(result: dict | None) -> str:
    js = _pure_render_js() + f"\nconsole.log(buildCardHtml({json.dumps(result)}));\n"
    return subprocess.run(
        [NODE_PATH, "-e", js], capture_output=True, text=True, timeout=10, check=True
    ).stdout.strip()


ROW = {
    "possible_causes": ["Loose widget"],
    "what_to_do": ["Tighten the widget.", "Call the shop."],
    "response_label": "What To Do",
    "footnotes": [],
    "text_incomplete": False,
    "page": 5,
}
MATCH = {
    "symptom": ["Gizmo hums loudly", "Gizmo rattles"],
    "symptom_label": "Problem",
    "rows": [ROW, {**ROW, "possible_causes": ["Dirty sprocket"], "what_to_do": ["Wipe it."]}],
    "citation": {"brand": "Acme", "model": "W100", "page": 5, "section": "Troubleshooting Tips"},
    "score": 1.0,
}
FOUND = {
    "status": "found",
    "message": "Found 1 similar entry",
    "symptom": "gizmo hums",
    "appliance": {
        "appliance_id": "a-w",
        "brand": "Acme",
        "model": "W100",
        "appliance_type": "washing_machine",
    },
    "appliance_registered": True,
    "matches": [MATCH],
    "candidate_appliances": [],
    "nearest_phrases": [],
    "suggest_add_appliance": False,
}
NOT_FOUND = {
    "status": "not_found",
    "message": "No symptom in our manuals matches 'the cat is hungry'. "
    "If the customer can read an error code, use diagnose_error.",
    "symptom": "the cat is hungry",
    "matches": [],
    "candidate_appliances": [],
    "nearest_phrases": ["Gizmo hums loudly", "Drum stays still"],
    "suggest_add_appliance": False,
}
AMBIGUOUS = {
    "status": "ambiguous_appliance",
    "message": "More than one of this household's appliances has a manual entry for a similar problem "
    "-- which appliance is it?",
    "symptom": "water pours out",
    "matches": [],
    "candidate_appliances": [
        {"appliance_id": "a-w", "brand": "Acme", "model": "W100", "appliance_type": "washing_machine"},
        {"appliance_id": "a-f", "brand": "Bravo", "model": "R200", "appliance_type": "refrigerator"},
    ],
}
CLICK_MARKERS = ("onclick", "<a ", "<button", 'addEventListener("click')


# --- the template and what it shares --------------------------------------------------------------


def test_the_resource_uri_is_the_symptom_card_and_uses_the_ui_scheme() -> None:
    assert SYMPTOM_CARD_RESOURCE_URI == "ui://fixit-mcp/diagnose-symptom-card"


def test_the_document_is_complete_with_every_shared_part_filled_in() -> None:
    assert SYMPTOM_CARD_HTML.strip().lower().startswith("<!doctype html>")
    assert "</html>" in SYMPTOM_CARD_HTML
    assert "@@" not in SYMPTOM_CARD_HTML, "an unreplaced marker"
    assert SYMPTOM_CARD_HTML == assemble_card(SYMPTOM_CARD_PATH, SYMPTOM_CARD_NAME)


def test_the_card_has_no_network_fetching_and_no_external_resources() -> None:
    for forbidden in ("fetch(", "XMLHttpRequest", "http://", "https://", "<link", "<img", "src="):
        assert forbidden not in SYMPTOM_CARD_HTML, forbidden


def test_both_cards_share_the_same_css_escape_helper_and_handshake() -> None:
    def between(html: str, start: str, end: str) -> str:
        return html[html.index(start) : html.index(end)]

    for start, end in (
        (":root {", ".card-header {"),
        ("function esc(", "function listHtml"),
        ("// MCP Apps handshake", "clientInfo:"),
        (".citation {", ".suggestions {"),
    ):
        assert between(SYMPTOM_CARD_HTML, start, end) == between(DIAGNOSE_CARD_HTML, start, end), start


def test_the_handshake_is_the_same_apart_from_the_card_name() -> None:
    def handshake(html: str) -> str:
        return html[
            html.index("// MCP Apps handshake") : html.index("</script>", html.index("// MCP Apps handshake"))
        ]

    assert handshake(SYMPTOM_CARD_HTML).replace(SYMPTOM_CARD_NAME, "NAME") == handshake(
        DIAGNOSE_CARD_HTML
    ).replace("fixit-mcp-diagnose-card", "NAME")
    assert "ui/initialize" in SYMPTOM_CARD_HTML and "ui/notifications/tool-result" in SYMPTOM_CARD_HTML


# --- found -----------------------------------------------------------------------------------------


@requires_node
def test_found_shows_the_symptom_phrases_as_the_title_and_the_appliance() -> None:
    out = build(FOUND)

    assert '<h2 class="symptom"><span class="symptom-phrase">Gizmo hums loudly</span>' in out
    assert '<span class="symptom-phrase">Gizmo rattles</span>' in out
    assert "Acme W100" in out and "From the manual" in out


@requires_node
def test_found_shows_each_rows_causes_and_what_to_do_in_order() -> None:
    out = build(FOUND)

    assert out.count('class="row"') == 2
    assert "<h3>Possible causes</h3><ul><li>Loose widget</li></ul>" in out
    assert "<h3>What To Do</h3><ul><li>Tighten the widget.</li><li>Call the shop.</li></ul>" in out
    assert out.index("Loose widget") < out.index("Dirty sprocket") < out.index("Wipe it.")


@requires_node
def test_a_reason_row_is_labelled_by_its_own_response_label() -> None:
    sound = {
        **MATCH,
        "symptom": ["Whistling"],
        "symptom_label": "Sounds",
        "rows": [{**ROW, "response_label": "Reason"}],
    }

    out = build({**FOUND, "matches": [sound]})

    assert "<h3>Reason</h3>" in out and "<h3>What To Do</h3>" not in out
    assert '<span class="symptom-label">Sounds</span>' in out


@requires_node
def test_the_default_problem_label_is_not_repeated_on_every_match() -> None:
    assert "symptom-label" not in build(FOUND)


@requires_node
def test_found_shows_the_citation_with_manual_and_page() -> None:
    out = build(FOUND)

    assert '<div class="citation">Source: Acme W100 manual, p. 5 — Troubleshooting Tips</div>' in out


@requires_node
def test_up_to_three_matches_are_shown_as_separate_blocks_and_no_more() -> None:
    four = [{**MATCH, "symptom": [f"Symptom {i}"]} for i in range(4)]

    out = build({**FOUND, "matches": four})

    assert out.count('<section class="match">') == 3
    assert "Symptom 2" in out and "Symptom 3" not in out


@requires_node
def test_a_row_that_ends_mid_sentence_gets_the_incomplete_marker() -> None:
    incomplete = {**MATCH, "rows": [{**ROW, "text_incomplete": True}, ROW]}

    out = build({**FOUND, "matches": [incomplete]})

    assert out.count("incomplete in the manual") == 1
    assert "incomplete in the manual" not in build(FOUND)


@requires_node
def test_footnotes_are_shown_as_muted_lines() -> None:
    noted = {**MATCH, "rows": [{**ROW, "footnotes": ["*Select models only"]}]}

    assert '<p class="footnote">*Select models only</p>' in build({**FOUND, "matches": [noted]})


@requires_node
def test_an_unregistered_appliance_gets_the_muted_notice_before_the_content() -> None:
    result = {**FOUND, "appliance_registered": False}

    out = build(result)

    assert "Documented for Acme W100, which isn't registered to your household." in out
    assert out.index("registration-notice") < out.index('class="match"')
    assert "registration-notice" not in build(FOUND)
    assert "registration-notice" not in build({k: v for k, v in FOUND.items() if k != "appliance_registered"})


@requires_node
def test_nothing_is_invented_for_an_empty_cell() -> None:
    bare = {**MATCH, "rows": [{**ROW, "possible_causes": []}]}

    out = build({**FOUND, "matches": [bare]})

    assert "Possible causes" not in out and "<h3>What To Do</h3>" in out


# --- not_found and ambiguous --------------------------------------------------------------------------


@requires_node
def test_not_found_is_a_muted_state_with_the_customers_words_and_the_nearest_phrases() -> None:
    out = build(NOT_FOUND)

    assert 'class="state-card state-not-found"' in out and "Not found" in out
    assert "the cat is hungry" in out
    assert "<li>Gizmo hums loudly</li><li>Drum stays still</li>" in out and "Closest in the manual" in out
    assert "error code" not in out, "the assistant-facing message is not shown"
    assert 'class="card"' not in out


@requires_node
def test_not_found_without_nearest_phrases_omits_the_list() -> None:
    out = build({**NOT_FOUND, "nearest_phrases": []})

    assert "Closest in the manual" not in out and "<ul" not in out


@requires_node
def test_ambiguous_lists_the_candidates_with_the_backend_message() -> None:
    out = build(AMBIGUOUS)

    assert 'class="state-card state-ambiguous"' in out and "Which appliance?" in out
    assert "<li>Acme W100 (washing_machine)</li>" in out and "<li>Bravo R200 (refrigerator)</li>" in out
    assert "which appliance is it?" in out


@requires_node
def test_no_result_or_an_unknown_status_renders_nothing() -> None:
    assert build(None) == ""
    assert build({"status": "mystery"}) == ""


@requires_node
@pytest.mark.parametrize("result", [FOUND, NOT_FOUND, AMBIGUOUS])
def test_no_state_has_a_click_handler(result: dict) -> None:
    out = build(result)

    assert not any(marker in out for marker in CLICK_MARKERS)


# --- escaping ------------------------------------------------------------------------------------------


@requires_node
def test_every_field_is_escaped() -> None:
    evil = "<img src=x onerror=alert(1)>"
    match = {
        "symptom": [evil],
        "symptom_label": evil,
        "rows": [
            {
                **ROW,
                "possible_causes": [evil],
                "what_to_do": [evil],
                "response_label": evil,
                "footnotes": [evil],
                "text_incomplete": True,
            }
        ],
        "citation": {"brand": evil, "model": evil, "page": evil, "section": evil},
        "score": 1,
    }
    found = {
        **FOUND,
        "appliance": {**FOUND["appliance"], "brand": evil, "model": evil},
        "appliance_registered": False,
        "matches": [match],
    }
    not_found = {**NOT_FOUND, "symptom": evil, "nearest_phrases": [evil]}
    ambiguous = {
        **AMBIGUOUS,
        "message": evil,
        "candidate_appliances": [{"brand": evil, "model": evil, "appliance_type": evil}],
    }

    for result in (found, not_found, ambiguous):
        out = build(result)
        assert "<img" not in out and "&lt;img" in out, result["status"]
