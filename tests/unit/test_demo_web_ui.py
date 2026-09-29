# ruff: noqa: E501  (embedded JavaScript harness lines)
"""Tests for the pure/DOM-free functions in demo/static/index.html's
script: the card-ownership decision (pickCardForTurn), the MCP Apps
handshake message builders, and the chip-text formatter.

Same rationale as tests/unit/test_diagnose_card.py: these are executed
directly in Node so the tests cover the exact JS the page ships, not a
Python reimplementation that could drift. Skipped (not failed) if `node`
isn't on PATH.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

INDEX_HTML_PATH = Path(__file__).resolve().parents[2] / "demo" / "static" / "index.html"
INDEX_HTML = INDEX_HTML_PATH.read_text()

NODE_PATH = shutil.which("node")
requires_node = pytest.mark.skipif(NODE_PATH is None, reason="node is not on PATH")


def _pure_js() -> str:
    """Everything in the page's <script> above the DOM-wiring marker."""
    script = re.search(r"<script>([\s\S]*?)</script>", INDEX_HTML).group(1)
    pure_js, _, _wiring = script.partition("// ---- DOM wiring below")
    return pure_js


def _run(js_tail: str) -> str:
    js = _pure_js() + "\n" + js_tail
    completed = subprocess.run([NODE_PATH, "-e", js], capture_output=True, text=True, timeout=10, check=True)
    return completed.stdout.strip()


def _run_json(js_expr: str) -> object:
    return json.loads(_run(f"console.log(JSON.stringify({js_expr}));"))


# --- static file sanity -------------------------------------------------


def test_no_cdn_or_external_script_references() -> None:
    assert "cdn." not in INDEX_HTML
    assert "<link" not in INDEX_HTML  # no external stylesheets/fonts
    assert 'src="http' not in INDEX_HTML


def test_page_talks_only_to_its_own_origin() -> None:
    assert 'fetch("/chat"' in INDEX_HTML
    assert "http://" not in INDEX_HTML
    assert "https://" not in INDEX_HTML


# --- formatChipText -------------------------------------------------


@requires_node
def test_chip_text_includes_tool_name_args_and_rounded_latency() -> None:
    call = {"name": "diagnose_error", "arguments": {"error_code": "tE1"}, "latency_ms": 87.6}
    out = _run(f"console.log(formatChipText({json.dumps(call)}));")
    assert out == "diagnose_error(error_code=tE1) · 88ms"


@requires_node
def test_chip_text_handles_no_arguments() -> None:
    call = {"name": "list_my_appliances", "arguments": {}, "latency_ms": 12.0}
    out = _run(f"console.log(formatChipText({json.dumps(call)}));")
    assert out == "list_my_appliances() · 12ms"


# --- pickCardForTurn -------------------------------------------------


@requires_node
def test_no_card_when_response_has_none() -> None:
    response = {"reply_text": "ok", "tool_calls": [], "card": None}
    assert _run_json(f"pickCardForTurn({json.dumps(response)})") is None


@requires_node
def test_card_owner_is_the_tool_call_with_a_known_status() -> None:
    response = {
        "reply_text": "ok",
        "tool_calls": [
            {"name": "list_my_appliances", "arguments": {}, "result": {"status": "ok"}, "latency_ms": 5},
            {
                "name": "diagnose_error",
                "arguments": {"error_code": "tE1"},
                "result": {"status": "found", "meaning": "temp sensor"},
                "latency_ms": 80,
            },
        ],
        "card": {"resource_uri": "ui://fixit-mcp/diagnose-error-card", "html": "<html>card</html>"},
    }

    result = _run_json(f"pickCardForTurn({json.dumps(response)})")

    assert result["html"] == "<html>card</html>"
    assert result["structuredContent"]["status"] == "found"
    assert result["arguments"] == {"error_code": "tE1"}


@requires_node
def test_card_owner_matches_not_found_and_ambiguous_statuses_too() -> None:
    for status in ("not_found", "ambiguous_appliance"):
        response = {
            "tool_calls": [
                {"name": "diagnose_error", "arguments": {}, "result": {"status": status}, "latency_ms": 1}
            ],
            "card": {"resource_uri": "ui://fixit-mcp/diagnose-error-card", "html": "<html>x</html>"},
        }
        result = _run_json(f"pickCardForTurn({json.dumps(response)})")
        assert result["structuredContent"]["status"] == status


# --- chatErrorMessage -------------------------------------------------


@requires_node
def test_chat_error_message_distinguishes_retryable_from_other_failures() -> None:
    retryable = _run("console.log(chatErrorMessage(true));")
    other = _run("console.log(chatErrorMessage(false));")

    assert retryable != other
    # Neither ever leaks an internal detail (status code, exception text).
    assert "HTTP" not in retryable and "HTTP" not in other
    assert "Error" not in retryable and "Error" not in other


@requires_node
def test_chat_error_message_treats_undefined_as_not_retryable() -> None:
    """A plain network exception (no structured body to read `retryable`
    from) must fall back to the same message as any other failure."""
    undefined = _run("console.log(chatErrorMessage(undefined));")
    other = _run("console.log(chatErrorMessage(false));")

    assert undefined == other


# --- handshake message builders -------------------------------------------------


@requires_node
def test_init_result_echoes_the_request_id_and_has_a_protocol_version() -> None:
    result = _run_json("buildInitResult(7)")
    assert result["id"] == 7
    assert result["jsonrpc"] == "2.0"
    assert result["result"]["protocolVersion"] == "2026-01-26"


@requires_node
def test_tool_input_notification_carries_the_call_arguments() -> None:
    notif = _run_json('buildToolInputNotification({"error_code": "tE1"})')
    assert notif["method"] == "ui/notifications/tool-input"
    assert notif["params"]["arguments"] == {"error_code": "tE1"}


@requires_node
def test_tool_result_notification_carries_structured_content() -> None:
    structured = {"status": "found", "meaning": "temp sensor"}
    notif = _run_json(f"buildToolResultNotification({json.dumps(structured)})")
    assert notif["method"] == "ui/notifications/tool-result"
    assert notif["params"]["structuredContent"] == structured
    assert isinstance(notif["params"]["content"], list)


# --- withSizeReporter -------------------------------------------------


@requires_node
def test_size_reporter_is_appended_without_breaking_the_outer_script_tag() -> None:
    out = _run('console.log(withSizeReporter("<div>card</div>"));')
    assert out.startswith("<div>card</div>")
    assert "ui/notifications/size-changed" in out
    # The reporter's own closing tag must not be a literal contiguous
    # "</script>" substring in the *source* we write (it would prematurely
    # close this page's real <script> block) -- it's fine for the
    # *executed/concatenated* output string to contain it, since by then
    # it's just string data, not live markup.
    assert "</" + "script>" in out


# --- one turn at a time: the DOM wiring, run against a stub DOM --------------------------------

_STUB_DOM = r"""
function makeEl(id) {
  return {
    id: id, disabled: false, value: "", className: "", textContent: "", style: {}, children: [],
    handlers: {}, firstChild: null, scrollTop: 0, scrollHeight: 0,
    classList: { add: function () {}, remove: function () {} },
    addEventListener: function (ev, fn) { this.handlers[ev] = fn; },
    appendChild: function (c) { this.children.push(c); return c; },
    setAttribute: function () {}, focus: function () {},
  };
}
var els = {};
["conversation","textInput","sendBtn","micBtn","muteBtn","newConvoBtn"].forEach(function (id) { els[id] = makeEl(id); });
var document = { getElementById: function (id) { return els[id]; }, createElement: function () { return makeEl("x"); } };
var window = { addEventListener: function () {}, crypto: { randomUUID: function () { return "sid-" + Math.random(); } } };
var pendingFetches = [];
var fetchBodies = [];
function fetch(url, opts) {
  fetchBodies.push(JSON.parse(opts.body));
  return new Promise(function (resolve, reject) { pendingFetches.push({ resolve: resolve, reject: reject }); });
}
"""


def _run_wiring(driver_js: str) -> object:
    script = re.search(r"<script>([\s\S]*?)</script>", INDEX_HTML).group(1)
    js = _STUB_DOM + script + "\n" + driver_js
    completed = subprocess.run([NODE_PATH, "-e", js], capture_output=True, text=True, timeout=10, check=True)
    return json.loads(completed.stdout.strip().splitlines()[-1])


_OK_RESPONSE = (
    '{ ok: true, json: function () { return Promise.resolve({ reply_text: "hi", tool_calls: [] }); } }'
)


@requires_node
def test_input_and_send_are_disabled_while_a_turn_is_pending_and_a_second_message_is_not_sent() -> None:
    result = _run_wiring(
        f"""
(async function () {{
  var t = els.textInput, s = els.sendBtn;
  t.value = "first"; s.handlers.click();
  var during = {{ input: t.disabled, send: s.disabled, mic: els.micBtn.disabled, newConvo: els.newConvoBtn.disabled }};
  t.value = "second"; s.handlers.click(); t.handlers.keydown({{ key: "Enter" }});
  var sentWhilePending = fetchBodies.length;
  pendingFetches[0].resolve({_OK_RESPONSE});
  await new Promise(function (r) {{ setTimeout(r, 20); }});
  var after = {{ input: t.disabled, send: s.disabled }};
  t.value = "third"; s.handlers.click();
  console.log(JSON.stringify({{ during: during, sentWhilePending: sentWhilePending, after: after, total: fetchBodies.length }}));
  process.exit(0);
}})();
"""
    )
    assert result["during"] == {"input": True, "send": True, "mic": True, "newConvo": True}
    assert result["sentWhilePending"] == 1  # neither the click nor Enter sent a second request
    assert result["after"] == {"input": False, "send": False}
    assert result["total"] == 2  # a later message goes through once the turn finished


@requires_node
def test_input_is_re_enabled_after_a_failed_turn_and_a_409_says_to_wait() -> None:
    result = _run_wiring(
        """
(async function () {
  var t = els.textInput, s = els.sendBtn;
  t.value = "first"; s.handlers.click();
  pendingFetches[0].resolve({ ok: false, status: 409, json: function () { return Promise.resolve({ error: "turn_in_progress", retryable: true }); } });
  await new Promise(function (r) { setTimeout(r, 20); });
  var afterConflict = { input: t.disabled, send: s.disabled };
  t.value = "second"; s.handlers.click();
  pendingFetches[1].reject(new Error("network down"));
  await new Promise(function (r) { setTimeout(r, 20); });
  console.log(JSON.stringify({ afterConflict: afterConflict, afterNetworkError: { input: t.disabled, send: s.disabled },
    msg409: chatErrorMessage(true, 409), msgOther: chatErrorMessage(true, 504) }));
  process.exit(0);
})();
"""
    )
    assert result["afterConflict"] == {"input": False, "send": False}
    assert result["afterNetworkError"] == {"input": False, "send": False}
    assert "still working" in result["msg409"]
    assert "hiccup" in result["msgOther"]


def test_the_page_gives_up_on_a_request_that_never_answers() -> None:
    assert "AbortController" in INDEX_HTML and "REQUEST_TIMEOUT_MS" in INDEX_HTML
