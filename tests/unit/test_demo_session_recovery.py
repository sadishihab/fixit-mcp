"""Proves the assumption demo/orchestrator.py's retry logic depends on:
after the MCP Streamable HTTP transport gets a 404 ("Session terminated"),
it never clears its stored Mcp-Session-Id, so a same-session retry sends the
identical stale id and fails identically -- confirmed here against the real
`mcp` SDK's streamable_http_client, with only the HTTP transport faked (a
`httpx.AsyncBaseTransport`, no real network, no real server), not against
demo code. See FRICTION_LOG.md and demo/mcp_session.py's SessionManager.evict.
"""

from __future__ import annotations

import json

import httpx
import pytest
from mcp import ClientSession, McpError
from mcp.client.streamable_http import streamable_http_client

# What mcp.client.streamable_http._send_session_terminated_error sends for a
# 404 on an in-flight request -- see that module's _handle_post_request.
_SESSION_TERMINATED_ERROR_CODE = 32600


class _StaleSessionTransport(httpx.AsyncBaseTransport):
    """Simulates a server that issues a session id at `initialize`, then no
    longer recognizes it on any later request -- the exact shape of a stale
    or misrouted Mcp-Session-Id (FRICTION_LOG.md's step 8d/8e incident).
    `initialize` and the `notifications/initialized` notification always
    succeed; every `tools/call` gets a 404, no matter how many times it's
    retried with the same id. Records the Mcp-Session-Id header sent with
    every request, so a test can prove it never changes across attempts.
    """

    def __init__(self, session_id: str = "session-abc-123") -> None:
        self._session_id = session_id
        self.session_ids_sent_for_tool_calls: list[str | None] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            # ClientSession's own teardown tries to terminate the session --
            # irrelevant to what this test proves, so just accept it quietly
            # rather than let an empty-body JSON parse below raise instead.
            return httpx.Response(200)
        body = json.loads(request.content)
        method = body.get("method")

        if method == "initialize":
            return httpx.Response(
                200,
                headers={"mcp-session-id": self._session_id, "content-type": "application/json"},
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "serverInfo": {"name": "fake-stale-server", "version": "0"},
                    },
                },
            )
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/call":
            self.session_ids_sent_for_tool_calls.append(request.headers.get("mcp-session-id"))
            return httpx.Response(404)
        raise AssertionError(f"unexpected method in this fake: {method!r}")  # pragma: no cover


async def test_streamable_http_client_never_clears_the_session_id_after_a_404() -> None:
    """Documents the exact bug a naive same-session retry would have: two
    tools/call attempts after the server has invalidated the session both
    send the identical Mcp-Session-Id, because nothing in the SDK ever
    resets it -- so both fail with the identical "Session terminated" error."""
    transport = _StaleSessionTransport()

    async with httpx.AsyncClient(transport=transport) as http_client:
        async with streamable_http_client("http://fake.local/mcp", http_client=http_client) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                with pytest.raises(McpError) as first:
                    await session.call_tool("some_tool", {})
                with pytest.raises(McpError) as second:
                    await session.call_tool("some_tool", {})

    assert first.value.error.code == _SESSION_TERMINATED_ERROR_CODE
    assert second.value.error.code == _SESSION_TERMINATED_ERROR_CODE
    assert first.value.error.message == "Session terminated"
    assert second.value.error.message == "Session terminated"

    # The crux of it: both attempts carried the exact same (now-invalid)
    # session id -- retrying on the same ClientSession can never recover.
    ids_sent = transport.session_ids_sent_for_tool_calls
    assert len(ids_sent) == 2
    assert ids_sent[0] == ids_sent[1] == "session-abc-123"
