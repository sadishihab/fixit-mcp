"""Step 13: a turn must never leave the session's Converse history
half-written, and a hung step must time out instead of hanging the turn.
Fake Bedrock, fake MCP session: no AWS, no server."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from mcp import types
from structlog.testing import capture_logs

from demo.mcp_session import ToolDef
from demo.orchestrator import OperationTimeout, repair_history, run_turn

DIAGNOSE = ToolDef(
    name="diagnose_error",
    description="Look up an error code.",
    input_schema={"type": "object"},
    resource_uri="ui://fixit-mcp/diagnose-error-card",
)


def user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": [{"text": text}]}


def assistant(text: str) -> dict[str, Any]:
    return {"role": "assistant", "content": [{"text": text}]}


def tool_use(tool_use_id: str = "t1", name: str = "diagnose_error") -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": [{"toolUse": {"toolUseId": tool_use_id, "name": name, "input": {"error_code": "uS"}}}],
    }


def tool_result(tool_use_id: str = "t1") -> dict[str, Any]:
    return {
        "role": "user",
        "content": [{"toolResult": {"toolUseId": tool_use_id, "content": [{"json": {}}]}}],
    }


def tool_use_response(tool_use_id: str = "t1") -> dict[str, Any]:
    return {"output": {"message": tool_use(tool_use_id)}, "stopReason": "tool_use", "usage": {}}


def text_response(text: str = "ok") -> dict[str, Any]:
    return {"output": {"message": assistant(text)}, "stopReason": "end_turn", "usage": {}}


def assert_valid_history(messages: list[dict[str, Any]]) -> None:
    """What Bedrock enforces: alternating roles, and every toolUse answered by
    a toolResult in the very next message."""
    for i, message in enumerate(messages):
        if i:
            assert message["role"] != messages[i - 1]["role"], f"consecutive {message['role']} at {i}"
        ids = [b["toolUse"]["toolUseId"] for b in message["content"] if "toolUse" in b]
        if ids:
            following = [
                b["toolResult"]["toolUseId"] for b in messages[i + 1]["content"] if "toolResult" in b
            ]
            assert set(ids) <= set(following), f"dangling toolUse at {i}"


class Converse:
    def __init__(self, *responses: dict[str, Any], sleep: float = 0.0) -> None:
        self._responses = list(responses)
        self._sleep = sleep
        self.calls: list[list[dict[str, Any]]] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append([dict(m) for m in kwargs["messages"]])
        if self._sleep:
            time.sleep(self._sleep)
        return self._responses.pop(0)


class Session:
    def __init__(
        self, *, error: BaseException | None = None, hang: bool = False, hang_resource: bool = False
    ):
        self.error, self.hang, self.hang_resource = error, hang, hang_resource
        self.started = asyncio.Event()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        self.started.set()
        if self.hang:
            await asyncio.sleep(3600)
        if self.error:
            raise self.error
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="found")],
            structuredContent={"status": "found"},
            isError=False,
        )

    async def read_resource(self, uri: str) -> types.ReadResourceResult:
        if self.hang_resource:
            await asyncio.sleep(3600)
        return types.ReadResourceResult(contents=[types.TextResourceContents(uri=uri, text="<html/>")])


async def turn(messages, converse, session, **kwargs):
    return await run_turn(
        converse=converse,
        model_id="m",
        system_prompt="s",
        messages=messages,
        tool_defs=[DIAGNOSE],
        session=session,
        user_message="It's showing uS",
        **kwargs,
    )


# --- 1. history integrity -----------------------------------------------------------------


async def test_a_successful_turn_keeps_its_messages() -> None:
    messages = [user("hi"), assistant("hello")]
    await turn(messages, Converse(tool_use_response(), text_response("done")), Session())
    assert len(messages) == 6
    assert_valid_history(messages)


async def test_a_tool_error_after_tool_use_rolls_the_history_back() -> None:
    messages = [user("hi"), assistant("hello")]
    before = [dict(m) for m in messages]
    with pytest.raises(RuntimeError):
        await turn(messages, Converse(tool_use_response()), Session(error=RuntimeError("boom")))
    assert messages == before


async def test_a_converse_failure_on_the_second_round_rolls_the_history_back() -> None:
    def converse(**kwargs: Any) -> dict[str, Any]:
        if len(kwargs["messages"]) > 3:
            raise RuntimeError("ValidationException")
        return tool_use_response()

    messages = [user("hi"), assistant("hello")]
    with pytest.raises(RuntimeError):
        await turn(messages, converse, Session())
    assert messages == [user("hi"), assistant("hello")]


async def test_cancellation_during_a_tool_call_rolls_the_history_back() -> None:
    messages = [user("hi"), assistant("hello")]
    session = Session(hang=True)
    task = asyncio.create_task(turn(messages, Converse(tool_use_response()), session, tool_timeout_s=None))
    await asyncio.wait_for(session.started.wait(), 2)
    assert messages[-1]["content"][0].get("toolUse")  # the half-written state a disconnect would strand
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert messages == [user("hi"), assistant("hello")]


async def test_exhausting_max_rounds_does_not_leave_the_history_ending_on_tool_results() -> None:
    responses = [tool_use_response(f"t{i}") for i in range(3)]
    messages = [user("hi"), assistant("hello")]
    result = await turn(messages, Converse(*responses), Session(), max_rounds=3)
    assert "trouble" in result.reply_text
    assert messages == [user("hi"), assistant("hello")]
    assert_valid_history(messages + [user("next")])


# --- 2. timeouts ----------------------------------------------------------------------------


async def test_a_hung_tool_call_times_out_naming_the_tool_and_restores_history() -> None:
    messages = [user("hi"), assistant("hello")]
    with pytest.raises(OperationTimeout) as info:
        await turn(messages, Converse(tool_use_response()), Session(hang=True), tool_timeout_s=0.05)
    assert info.value.operation == "tool_call:diagnose_error"
    assert info.value.timeout_s == 0.05
    assert info.value.fixit_operation == "tool_call:diagnose_error"
    assert "timed out after 0.05s" in str(info.value)
    assert messages == [user("hi"), assistant("hello")]


async def test_a_hung_card_fetch_times_out_and_restores_history() -> None:
    messages = [user("hi")]
    with pytest.raises(OperationTimeout) as info:
        await turn(messages, Converse(tool_use_response()), Session(hang_resource=True), tool_timeout_s=0.05)
    assert info.value.operation == "read_resource:ui://fixit-mcp/diagnose-error-card"
    assert messages == [user("hi")]


async def test_a_slow_bedrock_call_times_out_and_restores_history() -> None:
    messages = [user("hi")]
    with pytest.raises(OperationTimeout) as info:
        await turn(messages, Converse(text_response(), sleep=0.3), Session(), converse_timeout_s=0.05)
    assert info.value.operation == "bedrock_converse"
    assert messages == [user("hi")]


# --- 4. repair --------------------------------------------------------------------------------


def test_repair_drops_a_dangling_tool_use_and_merges_the_user_messages() -> None:
    # The corrupt history from the live run: turn 2's toolUse never got a result.
    messages = [
        user("add it"),
        tool_use("a"),
        tool_result("a"),
        assistant("added"),
        user("uS?"),
        tool_use("b"),
    ]
    assert repair_history(messages) == 1
    assert messages == [user("add it"), tool_use("a"), tool_result("a"), assistant("added"), user("uS?")]


def test_repair_handles_a_dangling_tool_use_followed_by_a_new_user_message() -> None:
    messages = [user("uS?"), tool_use("b"), user("hello?")]
    assert repair_history(messages) == 1
    assert messages == [{"role": "user", "content": [{"text": "uS?"}, {"text": "hello?"}]}]
    assert_valid_history(messages)


def test_repair_drops_orphan_tool_results_and_leaves_a_valid_history_alone() -> None:
    orphan = [user("a"), tool_use("x"), user("b"), tool_result("x")]
    assert repair_history(orphan) == 1
    assert orphan == [{"role": "user", "content": [{"text": "a"}, {"text": "b"}]}]

    valid = [user("a"), tool_use("x"), tool_result("x"), assistant("done")]
    snapshot = [dict(m) for m in valid]
    assert repair_history(valid) == 0
    assert valid == snapshot


def test_repair_drops_a_tool_use_that_is_only_partly_answered() -> None:
    two = {
        "role": "assistant",
        "content": [
            {"toolUse": {"toolUseId": "p", "name": "x", "input": {}}},
            {"toolUse": {"toolUseId": "q", "name": "x", "input": {}}},
        ],
    }
    messages = [user("a"), two, tool_result("p")]
    assert repair_history(messages) == 1
    assert_valid_history(messages)


async def test_a_turn_on_a_corrupt_history_repairs_it_first_and_logs_that_it_did() -> None:
    messages = [
        user("add it"),
        tool_use("a"),
        tool_result("a"),
        assistant("added"),
        user("uS?"),
        tool_use("b"),
    ]
    converse = Converse(text_response("It's a vibration sensor error."))
    with capture_logs() as logs:
        result = await turn(messages, converse, Session())
    assert result.reply_text == "It's a vibration sensor error."
    assert [e for e in logs if e["event"] == "demo_history_repaired"][0]["dropped_tool_use_messages"] == 1
    for sent in converse.calls:
        assert_valid_history(sent)
    assert_valid_history(messages)
