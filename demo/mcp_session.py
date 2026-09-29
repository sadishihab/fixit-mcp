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

import asyncio
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


class _SessionOwner:
    """Runs one MCP session's entire `async with` lifetime -- open through
    close -- inside a single dedicated asyncio task, and exposes the live
    ClientSession to whichever *other* task calls it.

    Why a dedicated task, not an AsyncExitStack entered from whatever task
    happens to call get() first: streamable_http_client's implementation
    uses an anyio task group internally, and anyio's cancel scopes are
    task-affine -- exiting one from a different task than the one that
    entered it raises `RuntimeError: Attempted to exit cancel scope in a
    different task than it was entered in` (hit for real: SessionManager
    used to open a session inside the first /chat request's task, then
    close it from the FastAPI lifespan's own task at shutdown -- crashed
    every time. See FRICTION_LOG.md, step 6b). Calling the *session's own
    methods* (call_tool, read_resource, ...) from other tasks is fine --
    only entering/exiting its context is task-affine -- so ordinary use
    from request handlers is unaffected by this.
    """

    def __init__(self, target: MCPTarget) -> None:
        self._target = target
        self.session: ClientSession | None = None
        self._ready = asyncio.Event()
        self._close_requested = asyncio.Event()
        self._error: BaseException | None = None
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            async with (
                create_mcp_http_client(auth=self._target.auth) as http_client,
                streamable_http_client(self._target.url, http_client=http_client) as (
                    read_stream,
                    write_stream,
                    _,
                ),
                ClientSession(read_stream, write_stream) as session,
            ):
                await session.initialize()
                self.session = session
                self._ready.set()
                await self._close_requested.wait()
        except BaseException as exc:  # noqa: BLE001 -- re-raised to the waiting get() below
            self._error = exc
            self._ready.set()

    async def wait_ready(self) -> ClientSession:
        await self._ready.wait()
        if self._error is not None:
            raise self._error
        assert self.session is not None
        return self.session

    def is_dead(self) -> bool:
        """True once the background task has exited with a fatal error --
        e.g. the underlying connection/session itself broke, not just a
        single request on it (that's a per-call failure, handled by
        orchestrator._call_tool_with_retry, and never touches this).
        Checked without blocking: unlike wait_ready(), this never waits on
        an owner that's still starting up -- one still becoming ready is not
        dead, so SessionManager.get() doesn't evict it out from under
        whichever caller is already waiting on it."""
        return self._ready.is_set() and self._error is not None

    async def aclose(self) -> None:
        self._close_requested.set()
        await self._task


class SessionManager:
    """Owns one persistent MCP ClientSession per demo session_id, reused
    across every /chat turn in that conversation -- see AgentCore's own MCP
    contract: a client "must capture the Mcp-Session-Id returned in the
    response and include it in all subsequent requests to ensure session
    affinity," warning that without it "each request may be routed to a new
    microVM," i.e. a fresh cold start (FRICTION_LOG.md's cold-start
    entries), rather than a fresh MCP session (and a fresh cold start) per
    message.

    get() also recovers from a dead owner (its background task exited with a
    fatal error -- see _SessionOwner.is_dead): rather than replaying that
    cached error forever, the next get() for that session_id closes it and
    starts a fresh one, so one bad session doesn't stay broken for every
    later turn without the customer having to start a new conversation. A
    per-session_id lock (created lazily, one per session_id ever seen --
    unbounded but negligible for a demo's session count) serializes the
    "is it dead, do I need to replace it" decision so two concurrent /chat
    requests for the *same* session_id can't each spawn their own owner;
    requests for different session_ids use different locks and never block
    each other on this.
    """

    def __init__(self, target: MCPTarget) -> None:
        self._target = target
        self._owners: dict[str, _SessionOwner] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = self._locks[session_id] = asyncio.Lock()
        return lock

    def is_open(self, session_id: str) -> bool:
        """True if this session_id already has a live (not dead) session --
        so a caller can tell, before calling get(), whether the next get()
        will pay for a fresh MCP session (a cold AgentCore Runtime session,
        if pointed at a deployed runtime) or reuse a warm one."""
        owner = self._owners.get(session_id)
        return owner is not None and not owner.is_dead()

    async def get(self, session_id: str) -> ClientSession:
        async with self._lock_for(session_id):
            owner = self._owners.get(session_id)
            if owner is not None and owner.is_dead():
                await owner.aclose()
                owner = None
            if owner is None:
                owner = self._owners[session_id] = _SessionOwner(self._target)
            return await owner.wait_ready()

    async def evict(self, session_id: str) -> None:
        """Force the next get() for this session_id to open a brand-new
        session, even though the current owner's background task hasn't
        itself failed -- is_dead() can't detect this case. Needed for the
        MCP transport's own "Session terminated" signal (a stale/misrouted
        Mcp-Session-Id the platform no longer recognizes): the transport
        never clears its stored session id after that error (confirmed by
        reading mcp.client.streamable_http and by
        tests/unit/test_demo_session_recovery.py), so retrying a tool call
        on the *same* owner would send the identical stale id and fail
        identically forever -- only a fresh owner (a fresh `initialize()`,
        a fresh id) can recover. A no-op if the session_id has no owner.
        """
        async with self._lock_for(session_id):
            owner = self._owners.pop(session_id, None)
        if owner is not None:
            await owner.aclose()

    async def aclose(self) -> None:
        for owner in self._owners.values():
            await owner.aclose()
        self._owners.clear()
