"""demo.app's /chat reliability behavior (step 8e): structured failure
logging, the retry boundary's effect on a real turn, and /chat's error
response shape -- against the real local FixIt MCP server (no mocking the
MCP protocol layer), with only Amazon Bedrock faked so no AWS credentials
or network are needed. A controlled ConnectError (via SessionManager.get)
stands in for a session failing mid-conversation, per the project's own
guidance to use controlled fake failures rather than a real outage.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from httpx import ASGITransport, AsyncClient
from mcp import ClientSession, McpError
from mcp.types import ErrorData
from structlog.testing import capture_logs

from demo.app import create_app
from demo.config import DemoSettings
from demo.mcp_session import MCPTarget
from fixit_mcp.logging import configure_logging


def _fake_bedrock_client(reply_text: str) -> MagicMock:
    client = MagicMock()
    client.converse.return_value = {
        "output": {"message": {"role": "assistant", "content": [{"text": reply_text}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 5, "outputTokens": 3},
    }
    return client


def _fake_bedrock_tool_then_text(tool_name: str, tool_input: dict, reply_text: str) -> MagicMock:
    """A Converse client whose first call decides to call `tool_name`, and
    whose second (after the tool result comes back) just replies in text."""
    responses = iter(
        [
            {
                "usage": {"inputTokens": 20, "outputTokens": 8},
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [{"toolUse": {"toolUseId": "t1", "name": tool_name, "input": tool_input}}],
                    }
                },
                "stopReason": "tool_use",
            },
            {
                "usage": {"inputTokens": 10, "outputTokens": 5},
                "output": {"message": {"role": "assistant", "content": [{"text": reply_text}]}},
                "stopReason": "end_turn",
            },
        ]
    )
    client = MagicMock()
    client.converse.side_effect = lambda **kwargs: next(responses)
    return client


async def test_successful_chat_turn_logs_demo_chat_turn_and_not_failed(server_url: str) -> None:
    # The server_url fixture's own create_server() call configures
    # structlog's global level filter at WARNING (fixit_mcp.logging), which
    # would otherwise silently drop demo_chat_turn's .info() call -- raise it
    # back to INFO for this test, since demo/app.py itself never configures
    # a level (a real `python -m demo` process never shares structlog config
    # with a fixit_mcp server in the first place).
    configure_logging("INFO")
    target = MCPTarget(url=server_url, auth=None)
    with patch("demo.app.boto3.client", return_value=_fake_bedrock_client("Sure, what's the error code?")):
        app = create_app(target, DemoSettings())
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://demo.local") as client:
                with capture_logs() as logs:
                    response = await client.post("/chat", json={"message": "hi", "session_id": "chat-ok-1"})

    assert response.status_code == 200
    assert response.json()["reply_text"] == "Sure, what's the error code?"

    events = [entry["event"] for entry in logs]
    assert "demo_chat_turn" in events
    assert "demo_chat_turn_failed" not in events

    success_entry = next(entry for entry in logs if entry["event"] == "demo_chat_turn")
    assert success_entry["session_id"] == "chat-ok-1"
    assert "turn_id" in success_entry
    assert success_entry["retried_tool_calls"] == 0


async def test_chat_returns_structured_retryable_error_when_the_session_fails(server_url: str) -> None:
    """A session that fails mid-conversation (simulated here as a
    ConnectError from SessionManager.get, the same exception a real dropped
    connection or refused socket would raise) must surface as /chat's
    structured, retryable error shape, log demo_chat_turn_failed (and never
    demo_chat_turn), and never leak the raw exception text to the browser."""
    target = MCPTarget(url=server_url, auth=None)
    with patch("demo.app.boto3.client", return_value=_fake_bedrock_client("unused")):
        app = create_app(target, DemoSettings())
        async with app.router.lifespan_context(app):
            with patch("demo.app.SessionManager.get", side_effect=httpx.ConnectError("connection refused")):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://demo.local") as client:
                    with capture_logs() as logs:
                        response = await client.post(
                            "/chat", json={"message": "hi", "session_id": "chat-fail-1"}
                        )

    assert response.status_code == 502
    assert response.json() == {"error": "runtime_transport_error", "retryable": True}
    # Never the raw exception type or message anywhere in the response body.
    assert "ConnectError" not in response.text
    assert "connection refused" not in response.text

    events = [entry["event"] for entry in logs]
    assert "demo_chat_turn_failed" in events
    assert "demo_chat_turn" not in events

    failure_entry = next(entry for entry in logs if entry["event"] == "demo_chat_turn_failed")
    assert failure_entry["session_id"] == "chat-fail-1"
    assert failure_entry["operation"] == "session_setup"
    assert failure_entry["exception_type"] == "ConnectError"
    assert failure_entry["retryable"] is True
    assert "turn_id" in failure_entry
    assert "elapsed_ms" in failure_entry


async def test_chat_returns_a_generic_error_for_a_non_transient_exception(server_url: str) -> None:
    """An unexpected, non-transport exception must not be reported as
    retryable, and must never leak its own message to the response body --
    that message here deliberately looks like it could contain a secret, to
    prove the response body never echoes it."""
    target = MCPTarget(url=server_url, auth=None)
    with patch("demo.app.boto3.client", return_value=_fake_bedrock_client("unused")):
        app = create_app(target, DemoSettings())
        async with app.router.lifespan_context(app):
            with patch(
                "demo.app.SessionManager.get",
                side_effect=ValueError("unrelated bug, token=abc123"),
            ):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://demo.local") as client:
                    with capture_logs() as logs:
                        response = await client.post(
                            "/chat", json={"message": "hi", "session_id": "chat-fail-2"}
                        )

    assert response.status_code == 500
    assert response.json() == {"error": "internal_error", "retryable": False}
    assert "abc123" not in response.text
    assert "unrelated bug" not in response.text

    failure_entry = next(entry for entry in logs if entry["event"] == "demo_chat_turn_failed")
    assert failure_entry["retryable"] is False
    assert failure_entry["exception_type"] == "ValueError"


async def test_chat_recovers_through_evict_then_get_after_session_terminated(server_url: str) -> None:
    """End-to-end proof of the actual fix: a "session terminated" failure on
    the first tool call must not surface as a failed turn to the customer.
    run_turn's refresh_session (wired in demo/app.py to SessionManager.evict
    then get) should transparently open a fresh session and retry, so /chat
    still returns an ordinary successful reply. Only ClientSession.call_tool
    itself is faked, to fail exactly once (mirroring a stale/misrouted
    Mcp-Session-Id) -- SessionManager, the real local server, and the whole
    evict-then-get path are exercised for real, not mocked."""
    configure_logging("INFO")
    target = MCPTarget(url=server_url, auth=None)
    call_count = {"n": 0}
    real_call_tool = ClientSession.call_tool

    async def flaky_call_tool(self: ClientSession, name: str, arguments: dict) -> object:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise McpError(ErrorData(code=32600, message="Session terminated"))
        return await real_call_tool(self, name, arguments)

    bedrock = _fake_bedrock_tool_then_text(
        "list_my_appliances", {"household_id": "house-002"}, "You have two appliances."
    )
    with patch("demo.app.boto3.client", return_value=bedrock):
        app = create_app(target, DemoSettings())
        async with app.router.lifespan_context(app):
            with patch.object(ClientSession, "call_tool", flaky_call_tool):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://demo.local") as client:
                    with capture_logs() as logs:
                        response = await client.post(
                            "/chat", json={"message": "what do I have", "session_id": "chat-recover-1"}
                        )

    assert response.status_code == 200
    body = response.json()
    assert body["reply_text"] == "You have two appliances."
    assert body["tool_calls"][0]["name"] == "list_my_appliances"
    assert call_count["n"] == 2  # the failed attempt, then the retry on a fresh session

    events = [entry["event"] for entry in logs]
    assert "demo_chat_turn" in events
    assert "demo_chat_turn_failed" not in events  # recovered -- never surfaced as a failed turn

    retry_entry = next(entry for entry in logs if entry["event"] == "tool_call_retry_succeeded")
    assert retry_entry["session_refreshed"] is True

    success_entry = next(entry for entry in logs if entry["event"] == "demo_chat_turn")
    assert success_entry["retried_tool_calls"] == 1
