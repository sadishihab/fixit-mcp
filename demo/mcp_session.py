"""MCP client plumbing for the demo backend: connecting to the FixIt MCP
server, discovering its tools, and keeping one persistent session per
conversation.

Session model: AgentCore's own MCP contract says a client "must capture the
Mcp-Session-Id returned in the response and include it in all subsequent
requests to ensure session affinity," warning that without it "each request
may be routed to a new microVM, which may result in additional latency due
to cold starts" (see FRICTION_LOG.md's cold-start entries). SessionManager
follows that: one persistent ClientSession per demo session_id, reused
across every /chat turn in that conversation, rather than a fresh MCP
session (and a fresh cold start) per message.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client


@dataclass(frozen=True)
class MCPTarget:
    """Where the demo's MCP client connects: the local dev server
    (unauthenticated) or a deployed AgentCore Runtime (SigV4-signed)."""

    url: str
    auth: httpx.Auth | None = None


@dataclass(frozen=True)
class ToolDef:
    """One tool as the server actually advertises it via tools/list --
    never hardcoded, so a tool added or changed on the server just shows up
    here next startup."""

    name: str
    description: str
    input_schema: dict[str, Any]
    # From the tool's own `_meta.ui.resourceUri` (the MCP Apps card
    # declaration -- see fixit_mcp.tools.diagnose), if it has one.
    resource_uri: str | None


async def list_tool_defs(session: ClientSession) -> list[ToolDef]:
    tools = (await session.list_tools()).tools
    return [
        ToolDef(
            name=tool.name,
            description=tool.description or "",
            input_schema=tool.inputSchema,
            resource_uri=(tool.meta or {}).get("ui", {}).get("resourceUri"),
        )
        for tool in tools
    ]


async def discover_tool_defs(target: MCPTarget) -> list[ToolDef]:
    """One-off tools/list call, used once at app startup to build the
    model's tool definitions from what the server actually advertises --
    never per conversation, never per turn."""
    async with (
        create_mcp_http_client(auth=target.auth) as http_client,
        streamable_http_client(target.url, http_client=http_client) as (read_stream, write_stream, _),
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await list_tool_defs(session)


class SessionManager:
    """Owns one persistent MCP ClientSession per demo session_id.

    Each session's streamable_http_client + ClientSession context is
    entered via an AsyncExitStack (rather than an ordinary `async with`
    block) specifically so it can stay open across independent /chat HTTP
    requests -- which arrive as separate calls into this process over time,
    not within one enclosing scope -- and be torn down explicitly
    (SessionManager.aclose) on app shutdown.
    """

    def __init__(self, target: MCPTarget) -> None:
        self._target = target
        self._sessions: dict[str, ClientSession] = {}
        self._stacks: dict[str, AsyncExitStack] = {}

    async def get(self, session_id: str) -> ClientSession:
        if session_id not in self._sessions:
            stack = AsyncExitStack()
            try:
                http_client = await stack.enter_async_context(create_mcp_http_client(auth=self._target.auth))
                read_stream, write_stream, _ = await stack.enter_async_context(
                    streamable_http_client(self._target.url, http_client=http_client)
                )
                session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
                await session.initialize()
            except BaseException:
                await stack.aclose()
                raise
            self._stacks[session_id] = stack
            self._sessions[session_id] = session
        return self._sessions[session_id]

    async def aclose(self) -> None:
        for stack in self._stacks.values():
            await stack.aclose()
        self._sessions.clear()
        self._stacks.clear()
