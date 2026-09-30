"""demo.orchestrator: the Bedrock Converse tool-use loop, against a fake
Bedrock client and a fake MCP session -- no AWS, no real server."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from mcp import McpError, types
from mcp.types import ErrorData

from demo.mcp_session import ToolDef
from demo.orchestrator import (
    ConversationStore,
    build_system_prompt,
    build_tool_config,
    is_transient_transport_error,
    run_turn,
)

DIAGNOSE_TOOL = ToolDef(
    name="diagnose_error",
    description="Look up an error code.",
    input_schema={"type": "object", "properties": {"error_code": {"type": "string"}}},
    resource_uri="ui://fixit-mcp/diagnose-error-card",
)
LIST_TOOL = ToolDef(
    name="list_my_appliances",
    description="List appliances.",
    input_schema={"type": "object"},
    resource_uri=None,
)


class FakeConverse:
    """Returns each of `responses` in order, one per call; records every
    call's kwargs so tests can assert on what was sent to Bedrock.

    `messages` is snapshotted (shallow-copied) at call time: run_turn
    mutates the same list object across rounds, so storing the raw
    reference would make every recorded call show the loop's *final*
    message list instead of what that particular call actually saw."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return next(self._responses)


def _text_response(text: str, input_tokens: int = 10, output_tokens: int = 5) -> dict[str, Any]:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": input_tokens, "outputTokens": output_tokens},
    }


def _tool_use_response(
    tool_use_id: str, name: str, input_: dict[str, Any], input_tokens: int = 20, output_tokens: int = 8
) -> dict[str, Any]:
    return {
        "usage": {"inputTokens": input_tokens, "outputTokens": output_tokens},
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": tool_use_id, "name": name, "input": input_}}],
            }
        },
        "stopReason": "tool_use",
    }


class FakeSession:
    """Stands in for mcp.ClientSession's call_tool/read_resource."""

    def __init__(
        self,
        call_tool_result: types.CallToolResult,
        resource: types.ReadResourceResult | None = None,
    ) -> None:
        self._result = call_tool_result
        self._resource = resource
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.read_resource_calls: list[str] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        self.calls.append((name, arguments))
        return self._result

    async def read_resource(self, uri: str) -> types.ReadResourceResult:
        self.read_resource_calls.append(uri)
        assert self._resource is not None
        return self._resource


class FakeFlakySession:
    """Raises each of `exceptions` in order on call_tool, then returns
    `result` -- for testing the retry boundary with controlled failures,
    never a real network outage."""

    def __init__(self, exceptions: list[Exception], result: types.CallToolResult) -> None:
        self._exceptions = list(exceptions)
        self._result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        self.calls.append((name, arguments))
        if self._exceptions:
            raise self._exceptions.pop(0)
        return self._result


def _found_result(household_id: str = "house-002") -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text="found")],
        structuredContent={"status": "found", "appliance": {"brand": "LG"}, "meaning": "temperature sensor"},
        isError=False,
    )


def _ambiguous_result() -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text="ambiguous")],
        structuredContent={"status": "ambiguous_appliance", "candidate_appliances": [{"brand": "LG"}]},
        isError=False,
    )


def _not_found_result() -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text="not found")],
        structuredContent={"status": "not_found", "nearest_matches": ["tE2"]},
        isError=False,
    )


def _unknown_status_result() -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text="?")],
        structuredContent={"status": "something_else"},
        isError=False,
    )


def _card_resource() -> types.ReadResourceResult:
    return types.ReadResourceResult(
        contents=[
            types.TextResourceContents(uri="ui://fixit-mcp/diagnose-error-card", text="<html>card</html>")
        ]
    )


# --- build_tool_config / build_system_prompt -------------------------------------------------


def test_build_tool_config_reflects_advertised_tools_not_a_hardcoded_list() -> None:
    config = build_tool_config([DIAGNOSE_TOOL, LIST_TOOL])

    assert config == {
        "tools": [
            {
                "toolSpec": {
                    "name": "diagnose_error",
                    "description": "Look up an error code.",
                    "inputSchema": {
                        "json": {"type": "object", "properties": {"error_code": {"type": "string"}}}
                    },
                }
            },
            {
                "toolSpec": {
                    "name": "list_my_appliances",
                    "description": "List appliances.",
                    "inputSchema": {"json": {"type": "object"}},
                }
            },
        ]
    }


def test_build_tool_config_empty_when_no_tools() -> None:
    assert build_tool_config([]) is None


def test_system_prompt_carries_household_id() -> None:
    assert "house-002" in build_system_prompt("house-002")


def test_system_prompt_forbids_treating_an_empty_warning_list_as_confirmed_safe() -> None:
    """Regression: step 6b's live verification caught the model saying 'it's
    safe to turn it off' when safety_warnings was empty -- an empty list
    means no warning was extracted, not that the tool confirmed safety.
    See FRICTION_LOG.md."""
    prompt = build_system_prompt("house-002")

    assert "safety_warnings" in prompt
    assert "not that it's confirmed safe" in prompt
    assert "own explanation" in prompt  # also forbids adding unstated causes/consequences


def test_system_prompt_forbids_repeating_meaning_and_likely_causes() -> None:
    """Regression: step 6e's live verification caught a tE1 reply saying
    'which means temperature sensor failure. The likely cause is
    temperature sensor failure' -- meaning and likely_causes said the same
    thing twice in one reply. See FRICTION_LOG.md."""
    prompt = build_system_prompt("house-002")

    assert "meaning" in prompt
    assert "likely_causes" in prompt
    assert "state it once, not both" in prompt


def test_system_prompt_forbids_added_judgments_predictions_and_next_steps() -> None:
    """Regression: the step 16a grounding eval caught 'Good news, nothing's wrong'
    for Bosch UP (a judgment the record never made), and 'a technician would need
    to diagnose which temperature sensor component has failed' for tE1 (a next
    step and a component the record never named). See FRICTION_LOG.md."""
    prompt = build_system_prompt("house-002")

    assert "Never add a judgment of your own" in prompt
    assert "'good news'" in prompt and "'nothing's wrong'" in prompt
    assert "no prediction of what will happen" in prompt
    assert "no next step the tool result didn't state" in prompt
    assert "which part or component a technician would check" in prompt
    assert "if the result only says to call for service, say only that" in prompt


def test_system_prompt_forbids_glossing_a_codes_meaning_with_an_unstated_mechanism() -> None:
    """Regression: the step 16a/16b grounding eval's found-lg-washer-ie case caught
    'The IE code means inlet error, which happens when water isn't filling the washer
    properly' -- the clause after 'which happens' is an explanation the record's
    meaning ('INLET ERROR') never gave. See FRICTION_LOG.md."""
    prompt = build_system_prompt("house-002")

    assert "State a code's meaning and its repair steps exactly as the result gives them" in prompt
    assert "never" in prompt and "gloss, expand, or explain a code" in prompt
    assert "mechanism, cause, or condition the result" in prompt
    assert "which happens when water isn't filling the washer properly" in prompt


def test_system_prompt_restricts_not_found_replies_to_what_the_result_supports() -> None:
    """Regression: step 6e's live verification caught a not_found reply
    saying 'it's not documented for your LG dryer' and suggesting the
    customer contact LG support -- not_found means the whole index was
    searched, not one appliance, and the tool never suggested contacting
    anyone. Only nearest_matches and a suggest_add_appliance-based
    suggestion are tool-grounded content for this status. See
    FRICTION_LOG.md."""
    prompt = build_system_prompt("house-002")

    assert "not_found" in prompt
    assert "never name a brand or appliance" in prompt
    assert "nearest_matches" in prompt
    assert "adding the appliance" in prompt
    assert "never suggest contacting support" in prompt


def test_system_prompt_caps_replies_to_two_sentences_unless_steps_are_asked_for() -> None:
    prompt = build_system_prompt("house-002")

    assert "at most two sentences" in prompt
    assert "full repair steps" in prompt


def test_system_prompt_restricts_warranty_replies_to_the_recorded_date_fact() -> None:
    """Step 8a: check_warranty only ever reports a date comparison -- the
    system prompt must forbid the model from turning that into a coverage
    claim or an unstated suggestion, the same class of leak step 6b/6e
    caught for other tools."""
    prompt = build_system_prompt("house-002")

    assert "check_warranty" in prompt
    assert "never say whether a repair would be covered" in prompt
    assert "never suggest contacting anyone the tool result didn't mention" in prompt


def test_system_prompt_calls_the_warranty_date_recorded() -> None:
    """Step 8b: the dates come from what the customer registered, not a
    manufacturer lookup, so a reply must call it the *recorded* warranty
    date -- not just state a bare date -- to avoid sounding verified."""
    prompt = build_system_prompt("house-002")

    assert "the recorded warranty ended on" in prompt
    assert "not something verified with the manufacturer" in prompt


# --- run_turn: plain reply, no tool use -------------------------------------------------


async def test_plain_reply_makes_no_tool_calls() -> None:
    converse = FakeConverse([_text_response("Sure, what's the error code?")])
    session = FakeSession(call_tool_result=_found_result())
    history: list[dict[str, Any]] = []

    result = await run_turn(
        converse=converse,
        model_id="test-model",
        system_prompt="be helpful",
        messages=history,
        tool_defs=[DIAGNOSE_TOOL],
        session=session,
        user_message="my dryer is broken",
    )

    assert result.reply_text == "Sure, what's the error code?"
    assert result.tool_calls == []
    assert result.card is None
    assert session.calls == []
    # history now has the user turn and the assistant's reply.
    assert len(history) == 2
    assert history[0] == {"role": "user", "content": [{"text": "my dryer is broken"}]}


# --- run_turn: one tool call, found -> card fetched -------------------------------------------------


async def test_one_tool_call_found_returns_card() -> None:
    converse = FakeConverse(
        [
            _tool_use_response("t1", "diagnose_error", {"error_code": "tE1", "household_id": "house-002"}),
            _text_response("Your dryer's tE1 means a temperature sensor issue."),
        ]
    )
    session = FakeSession(call_tool_result=_found_result(), resource=_card_resource())

    result = await run_turn(
        converse=converse,
        model_id="test-model",
        system_prompt="be helpful",
        messages=[],
        tool_defs=[DIAGNOSE_TOOL],
        session=session,
        user_message="my dryer shows tE1",
    )

    assert result.reply_text == "Your dryer's tE1 means a temperature sensor issue."
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.name == "diagnose_error"
    assert call.arguments == {"error_code": "tE1", "household_id": "house-002"}
    assert call.result == {"status": "found", "appliance": {"brand": "LG"}, "meaning": "temperature sensor"}
    assert call.latency_ms >= 0
    assert session.calls == [("diagnose_error", {"error_code": "tE1", "household_id": "house-002"})]
    assert result.card is not None
    assert result.card.resource_uri == "ui://fixit-mcp/diagnose-error-card"
    assert result.card.html == "<html>card</html>"
    # summed across both Converse calls this turn made (default fakes: 20+10 in, 8+5 out).
    assert result.input_tokens == 30
    assert result.output_tokens == 13
    assert session.read_resource_calls == ["ui://fixit-mcp/diagnose-error-card"]

    # the toolResult sent back to Bedrock carries the tool's structured content.
    second_call_messages = converse.calls[1]["messages"]
    tool_result_message = second_call_messages[-1]
    assert tool_result_message["content"][0]["toolResult"]["toolUseId"] == "t1"
    assert tool_result_message["content"][0]["toolResult"]["content"] == [
        {"json": {"status": "found", "appliance": {"brand": "LG"}, "meaning": "temperature sensor"}}
    ]


# --- run_turn: ambiguous_appliance and not_found also get a card ------------------------------


async def test_ambiguous_appliance_follow_up_has_a_card_too() -> None:
    """A card is shown for ambiguous_appliance too, not just found -- the
    card's own template already renders a muted 'which appliance?' state
    for it (see diagnose_card.html), so there's no reason to withhold the
    card just because the status isn't found."""
    converse = FakeConverse(
        [
            _tool_use_response("t1", "diagnose_error", {"error_code": "tE1", "household_id": "house-002"}),
            _text_response("Which appliance is showing that code -- the dryer or the fridge?"),
        ]
    )
    session = FakeSession(call_tool_result=_ambiguous_result(), resource=_card_resource())

    result = await run_turn(
        converse=converse,
        model_id="test-model",
        system_prompt="be helpful",
        messages=[],
        tool_defs=[DIAGNOSE_TOOL],
        session=session,
        user_message="tE1 on my appliance",
    )

    assert result.reply_text == "Which appliance is showing that code -- the dryer or the fridge?"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].result["status"] == "ambiguous_appliance"
    assert result.card is not None
    assert result.card.resource_uri == "ui://fixit-mcp/diagnose-error-card"
    assert session.read_resource_calls == ["ui://fixit-mcp/diagnose-error-card"]


async def test_not_found_has_a_card_too() -> None:
    """Same reasoning as ambiguous_appliance above -- not_found gets its own
    muted card state from the template too."""
    converse = FakeConverse(
        [
            _tool_use_response("t1", "diagnose_error", {"error_code": "E24", "household_id": "house-002"}),
            _text_response("I don't have that exact code in our index."),
        ]
    )
    session = FakeSession(call_tool_result=_not_found_result(), resource=_card_resource())

    result = await run_turn(
        converse=converse,
        model_id="test-model",
        system_prompt="be helpful",
        messages=[],
        tool_defs=[DIAGNOSE_TOOL],
        session=session,
        user_message="E24 on my appliance",
    )

    assert result.tool_calls[0].result["status"] == "not_found"
    assert result.card is not None
    assert session.read_resource_calls == ["ui://fixit-mcp/diagnose-error-card"]


async def test_unknown_status_has_no_card() -> None:
    """A status outside the found/not_found/ambiguous_appliance convention
    is not assumed to have a matching card state -- no card is fetched."""
    converse = FakeConverse(
        [
            _tool_use_response("t1", "diagnose_error", {"error_code": "tE1"}),
            _text_response("..."),
        ]
    )
    session = FakeSession(call_tool_result=_unknown_status_result(), resource=_card_resource())

    result = await run_turn(
        converse=converse,
        model_id="test-model",
        system_prompt="be helpful",
        messages=[],
        tool_defs=[DIAGNOSE_TOOL],
        session=session,
        user_message="tE1",
    )

    assert result.card is None
    assert session.read_resource_calls == []


async def test_tool_without_resource_uri_has_no_card_even_when_found() -> None:
    """A tool with no _meta.ui.resourceUri never gets a card, regardless of
    its result's status -- the rule is generic over any tool, not
    hardcoded to diagnose_error, but a tool that never declared a UI
    resource has nothing to fetch."""
    converse = FakeConverse(
        [
            _tool_use_response("t1", "list_my_appliances", {"household_id": "house-002"}),
            _text_response("You have a dryer and a fridge."),
        ]
    )
    session = FakeSession(call_tool_result=_found_result(), resource=_card_resource())

    result = await run_turn(
        converse=converse,
        model_id="test-model",
        system_prompt="be helpful",
        messages=[],
        tool_defs=[LIST_TOOL],
        session=session,
        user_message="what appliances do I have",
    )

    assert result.tool_calls[0].result["status"] == "found"
    assert result.card is None
    assert session.read_resource_calls == []


# --- run_turn: tool error -------------------------------------------------


async def test_tool_error_is_reported_to_bedrock_as_an_error_result() -> None:
    error_result = types.CallToolResult(
        content=[types.TextContent(type="text", text="boom")], structuredContent=None, isError=True
    )
    converse = FakeConverse(
        [
            _tool_use_response("t1", "diagnose_error", {"error_code": "tE1"}),
            _text_response("Sorry, something went wrong looking that up."),
        ]
    )
    session = FakeSession(call_tool_result=error_result)

    result = await run_turn(
        converse=converse,
        model_id="test-model",
        system_prompt="be helpful",
        messages=[],
        tool_defs=[DIAGNOSE_TOOL],
        session=session,
        user_message="tE1",
    )

    assert result.card is None
    tool_result_message = converse.calls[1]["messages"][-1]
    assert tool_result_message["content"][0]["toolResult"]["status"] == "error"


# --- is_transient_transport_error classification -------------------------------------------------


def test_httpx_transport_error_is_transient() -> None:
    assert is_transient_transport_error(httpx.ConnectError("connection refused")) is True
    assert is_transient_transport_error(httpx.ReadTimeout("timed out")) is True


def test_httpx_gateway_status_errors_are_transient() -> None:
    request = httpx.Request("POST", "https://example.invalid/mcp")
    for status in (502, 503, 504):
        response = httpx.Response(status, request=request)
        exc = httpx.HTTPStatusError("bad gateway", request=request, response=response)
        assert is_transient_transport_error(exc) is True


def test_httpx_client_error_status_is_not_transient() -> None:
    request = httpx.Request("POST", "https://example.invalid/mcp")
    response = httpx.Response(400, request=request)
    exc = httpx.HTTPStatusError("bad request", request=request, response=response)
    assert is_transient_transport_error(exc) is False


def test_session_terminated_mcp_error_is_transient() -> None:
    exc = McpError(ErrorData(code=32600, message="Session terminated"))
    assert is_transient_transport_error(exc) is True


def test_an_ordinary_mcp_error_is_not_transient() -> None:
    """A real tool/application-level error over MCP (e.g. bad arguments) is
    deterministic -- retrying it would just get the same answer again."""
    exc = McpError(ErrorData(code=-32602, message="Invalid params"))
    assert is_transient_transport_error(exc) is False


def test_a_plain_value_error_is_not_transient() -> None:
    assert is_transient_transport_error(ValueError("something else broke")) is False


# --- run_turn: one automatic retry for a transient transport failure --------------------------


async def test_transient_failure_on_an_idempotent_tool_is_retried_and_succeeds() -> None:
    converse = FakeConverse(
        [
            _tool_use_response("t1", "check_warranty", {"household_id": "house-002"}),
            _text_response("The recorded warranty ended a while ago."),
        ]
    )
    session = FakeFlakySession(exceptions=[httpx.ReadTimeout("timed out")], result=_found_result())

    result = await run_turn(
        converse=converse,
        model_id="test-model",
        system_prompt="be helpful",
        messages=[],
        tool_defs=[DIAGNOSE_TOOL],
        session=session,
        user_message="is it still under warranty",
    )

    assert len(session.calls) == 2  # the failed attempt, then the retry
    assert result.tool_calls[0].retried is True
    assert result.tool_calls[0].result == {
        "status": "found",
        "appliance": {"brand": "LG"},
        "meaning": "temperature sensor",
    }


async def test_transient_failure_on_an_idempotent_tool_is_retried_and_still_fails() -> None:
    session = FakeFlakySession(
        exceptions=[httpx.ReadTimeout("timed out"), httpx.ReadTimeout("still timed out")],
        result=_found_result(),
    )
    converse = FakeConverse([_tool_use_response("t1", "check_warranty", {"household_id": "house-002"})])

    with pytest.raises(httpx.ReadTimeout):
        await run_turn(
            converse=converse,
            model_id="test-model",
            system_prompt="be helpful",
            messages=[],
            tool_defs=[DIAGNOSE_TOOL],
            session=session,
            user_message="is it still under warranty",
        )

    assert len(session.calls) == 2  # first attempt + the one retry, never a third


async def test_a_deterministic_mcp_error_is_never_retried() -> None:
    """An ordinary tool-level McpError (e.g. bad arguments) must not be
    retried -- it's a deterministic response, not a transport hiccup."""
    session = FakeFlakySession(
        exceptions=[McpError(ErrorData(code=-32602, message="Invalid params"))],
        result=_found_result(),
    )
    converse = FakeConverse([_tool_use_response("t1", "diagnose_error", {"error_code": "tE1"})])

    with pytest.raises(McpError):
        await run_turn(
            converse=converse,
            model_id="test-model",
            system_prompt="be helpful",
            messages=[],
            tool_defs=[DIAGNOSE_TOOL],
            session=session,
            user_message="tE1",
        )

    assert len(session.calls) == 1  # never retried


async def test_a_transient_failure_on_a_non_idempotent_tool_is_not_retried() -> None:
    """add_appliance isn't safe to blindly retry: a lost response after the
    server actually applied the write would duplicate the appliance."""
    add_appliance_tool = ToolDef(
        name="add_appliance",
        description="Add an appliance.",
        input_schema={"type": "object"},
        resource_uri=None,
    )
    session = FakeFlakySession(exceptions=[httpx.ReadTimeout("timed out")], result=_found_result())
    converse = FakeConverse(
        [_tool_use_response("t1", "add_appliance", {"household_id": "house-002", "brand": "GE"})]
    )

    with pytest.raises(httpx.ReadTimeout):
        await run_turn(
            converse=converse,
            model_id="test-model",
            system_prompt="be helpful",
            messages=[],
            tool_defs=[add_appliance_tool],
            session=session,
            user_message="add my new fridge",
        )

    assert len(session.calls) == 1  # never retried


async def test_session_terminated_error_with_a_fresh_session_retries_and_succeeds() -> None:
    """The MCP transport's own "session terminated" signal (a stale/
    misrouted Mcp-Session-Id caught before the request reached the tool
    handler) means the request is known never to have run -- safe to retry
    even for add_appliance, unlike an ordinary transport error. But (see
    tests/unit/test_demo_session_recovery.py) the transport never clears its
    stale session id, so the retry can only succeed against a genuinely
    fresh session -- never the one that just failed. refresh_session models
    exactly that: it hands back a different, healthy session object."""
    add_appliance_tool = ToolDef(
        name="add_appliance",
        description="Add an appliance.",
        input_schema={"type": "object"},
        resource_uri=None,
    )
    stale_session = FakeFlakySession(
        exceptions=[McpError(ErrorData(code=32600, message="Session terminated"))],
        result=_found_result(),
    )
    fresh_session = FakeFlakySession(exceptions=[], result=_found_result())

    async def refresh_session() -> FakeFlakySession:
        return fresh_session

    converse = FakeConverse(
        [
            _tool_use_response("t1", "add_appliance", {"household_id": "house-002", "brand": "GE"}),
            _text_response("Added."),
        ]
    )

    result = await run_turn(
        converse=converse,
        model_id="test-model",
        system_prompt="be helpful",
        messages=[],
        tool_defs=[add_appliance_tool],
        session=stale_session,
        user_message="add my new fridge",
        refresh_session=refresh_session,
    )

    assert len(stale_session.calls) == 1  # the one failed attempt, never retried on the stale session
    assert len(fresh_session.calls) == 1  # the retry, on the fresh session
    assert result.tool_calls[0].retried is True


async def test_session_terminated_error_without_a_fresh_session_fails_fast() -> None:
    """Without a way to open a fresh session, retrying on the same (known-
    stale) one is pointless -- proven in test_demo_session_recovery.py, it
    would just get the identical "Session terminated" error again. No
    refresh_session means no retry attempt at all, not a wasted one."""
    add_appliance_tool = ToolDef(
        name="add_appliance",
        description="Add an appliance.",
        input_schema={"type": "object"},
        resource_uri=None,
    )
    session = FakeFlakySession(
        exceptions=[McpError(ErrorData(code=32600, message="Session terminated"))],
        result=_found_result(),
    )
    converse = FakeConverse(
        [_tool_use_response("t1", "add_appliance", {"household_id": "house-002", "brand": "GE"})]
    )

    with pytest.raises(McpError):
        await run_turn(
            converse=converse,
            model_id="test-model",
            system_prompt="be helpful",
            messages=[],
            tool_defs=[add_appliance_tool],
            session=session,
            user_message="add my new fridge",
        )

    assert len(session.calls) == 1  # never retried


# --- run_turn: max_rounds caps a runaway loop -------------------------------------------------


async def test_max_rounds_caps_a_runaway_tool_use_loop() -> None:
    converse = FakeConverse(
        [_tool_use_response(f"t{i}", "diagnose_error", {"error_code": "tE1"}) for i in range(10)]
    )
    session = FakeSession(call_tool_result=_found_result(), resource=_card_resource())

    result = await run_turn(
        converse=converse,
        model_id="test-model",
        system_prompt="be helpful",
        messages=[],
        tool_defs=[DIAGNOSE_TOOL],
        session=session,
        user_message="tE1",
        max_rounds=3,
    )

    assert len(result.tool_calls) == 3
    assert len(converse.calls) == 3
    assert result.reply_text  # a fallback message, not an exception or a hang


# --- ConversationStore -------------------------------------------------


def test_conversation_store_keeps_history_per_session_id() -> None:
    store = ConversationStore()

    a = store.get("session-a")
    a.append({"role": "user", "content": [{"text": "hi"}]})

    assert store.get("session-a") == [{"role": "user", "content": [{"text": "hi"}]}]
    assert store.get("session-b") == []
