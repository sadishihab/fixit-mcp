"""Step 13 at the /chat boundary, against the real local FixIt MCP server
(only Bedrock faked): one turn at a time per session (409), a hung step ends
as a logged 504 naming the operation and timeout, and a failed turn leaves the
session usable (its history is valid on the next turn)."""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from unittest.mock import MagicMock, patch

from httpx import ASGITransport, AsyncClient
from mcp import ClientSession
from structlog.testing import capture_logs

from demo.app import create_app
from demo.config import DemoSettings
from demo.mcp_session import MCPTarget
from fixit_mcp.logging import configure_logging


def _text(text: str) -> dict[str, Any]:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 5, "outputTokens": 3},
    }


def _tool_use(tool_use_id: str = "t1") -> dict[str, Any]:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": tool_use_id,
                            "name": "diagnose_error",
                            "input": {"error_code": "tE1"},
                        }
                    }
                ],
            }
        },
        "stopReason": "tool_use",
        "usage": {"inputTokens": 5, "outputTokens": 3},
    }


def _assert_valid(messages: list[dict[str, Any]]) -> None:
    for i, message in enumerate(messages):
        if i:
            assert message["role"] != messages[i - 1]["role"]
        ids = [b["toolUse"]["toolUseId"] for b in message["content"] if "toolUse" in b]
        if ids:
            answered = [b["toolResult"]["toolUseId"] for b in messages[i + 1]["content"] if "toolResult" in b]
            assert set(ids) <= set(answered)


async def test_a_second_message_on_a_busy_session_gets_409_and_other_sessions_are_unaffected(
    server_url: str,
) -> None:
    release = threading.Event()
    entered = threading.Event()
    seen: list[list[dict[str, Any]]] = []

    def converse(**kwargs: Any) -> dict[str, Any]:
        seen.append([dict(m) for m in kwargs["messages"]])
        entered.set()
        release.wait(5)
        return _text("done")

    bedrock = MagicMock()
    bedrock.converse.side_effect = converse
    with patch("demo.app.boto3.client", return_value=bedrock):
        app = create_app(MCPTarget(url=server_url, auth=None), DemoSettings())
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://demo.local") as client:
                with capture_logs() as logs:
                    first = asyncio.create_task(
                        client.post("/chat", json={"message": "one", "session_id": "s"})
                    )
                    await asyncio.to_thread(entered.wait, 5)
                    busy = await client.post("/chat", json={"message": "two", "session_id": "s"})
                    release.set()
                    first_response = await first
                    after = await client.post("/chat", json={"message": "three", "session_id": "s"})
                    other = await client.post("/chat", json={"message": "hi", "session_id": "other"})

    assert busy.status_code == 409
    assert busy.json() == {"error": "turn_in_progress", "retryable": True}
    assert first_response.status_code == 200 and after.status_code == 200 and other.status_code == 200
    assert "demo_chat_turn_rejected" in [e["event"] for e in logs]
    # The rejected message never reached Bedrock or the history.
    assert all("two" not in str(call) for call in seen)
    _assert_valid(seen[-2])


async def test_a_hung_bedrock_call_becomes_a_504_naming_the_operation_and_the_session_recovers(
    server_url: str,
) -> None:
    configure_logging("INFO")
    calls: list[list[dict[str, Any]]] = []

    def converse(**kwargs: Any) -> dict[str, Any]:
        calls.append([dict(m) for m in kwargs["messages"]])
        if len(calls) == 1:
            threading.Event().wait(0.5)  # outlives the 0.1s budget below
        return _text("recovered")

    bedrock = MagicMock()
    bedrock.converse.side_effect = converse
    settings = DemoSettings(converse_timeout_seconds=0.1)
    with patch("demo.app.boto3.client", return_value=bedrock):
        app = create_app(MCPTarget(url=server_url, auth=None), settings)
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://demo.local") as client:
                with capture_logs() as logs:
                    hung = await client.post("/chat", json={"message": "one", "session_id": "t"})
                    ok = await client.post("/chat", json={"message": "two", "session_id": "t"})

    assert hung.status_code == 504
    assert hung.json() == {"error": "turn_timeout", "operation": "bedrock_converse", "retryable": True}
    failed = next(e for e in logs if e["event"] == "demo_chat_turn_failed")
    assert failed["operation"] == "bedrock_converse" and failed["timeout_s"] == 0.1
    assert "timed out after 0.1s" in failed["exception_message"]
    assert ok.status_code == 200 and ok.json()["reply_text"] == "recovered"
    assert len(calls[-1]) == 1  # the hung turn left nothing behind in the history


async def test_a_hung_tool_call_becomes_a_504_and_the_next_turn_has_a_valid_history(server_url: str) -> None:
    calls: list[list[dict[str, Any]]] = []
    responses = iter([_tool_use(), _text("Sorry, try again."), _text("fine")])

    def converse(**kwargs: Any) -> dict[str, Any]:
        calls.append([dict(m) for m in kwargs["messages"]])
        return next(responses)

    bedrock = MagicMock()
    bedrock.converse.side_effect = converse
    real_call_tool = ClientSession.call_tool

    async def hang_once(self: ClientSession, name: str, arguments: dict | None = None, *a: Any, **k: Any):
        if name == "diagnose_error" and not getattr(hang_once, "done", False):
            hang_once.done = True  # type: ignore[attr-defined]
            await asyncio.sleep(30)
        return await real_call_tool(self, name, arguments, *a, **k)

    settings = DemoSettings(tool_timeout_seconds=0.1)
    with (
        patch("demo.app.boto3.client", return_value=bedrock),
        patch.object(ClientSession, "call_tool", hang_once),
    ):
        app = create_app(MCPTarget(url=server_url, auth=None), settings)
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://demo.local") as client:
                with capture_logs() as logs:
                    hung = await client.post("/chat", json={"message": "uS?", "session_id": "u"})
                    ok = await client.post("/chat", json={"message": "hello?", "session_id": "u"})

    assert hung.status_code == 504
    assert hung.json()["operation"] == "tool_call:diagnose_error"
    failed = next(e for e in logs if e["event"] == "demo_chat_turn_failed")
    assert failed["operation"] == "tool_call:diagnose_error" and failed["timeout_s"] == 0.1
    assert ok.status_code == 200
    _assert_valid(calls[-1])  # no dangling toolUse from the hung turn
