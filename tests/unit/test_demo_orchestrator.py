"""demo.orchestrator: the Bedrock Converse tool-use loop, against a fake
Bedrock client and a fake MCP session -- no AWS, no real server."""

from __future__ import annotations

from typing import Any

from mcp import types

from demo.mcp_session import ToolDef
from demo.orchestrator import ConversationStore, build_system_prompt, build_tool_config, run_turn

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
