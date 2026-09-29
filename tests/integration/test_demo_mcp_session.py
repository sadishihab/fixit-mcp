"""demo.mcp_session.SessionManager against the real local FixIt MCP server
(no fakes here -- the bug this guards against is specific to anyio's real
task-affine cancel scopes inside mcp's streamable_http_client, which a fake
session object wouldn't exercise at all)."""

from __future__ import annotations

import asyncio

from demo.mcp_session import MCPTarget, SessionManager


async def test_session_survives_being_opened_and_closed_from_different_tasks(server_url: str) -> None:
    """Regression test (FRICTION_LOG.md, step 6b): a real FastAPI app opens
    a session inside whichever request task calls SessionManager.get()
    first, and closes it later from the lifespan's own, different task.
    Reproduce exactly that task boundary directly, without FastAPI."""
    target = MCPTarget(url=server_url, auth=None)
    sessions = SessionManager(target)

    # Simulates a /chat request handler running in its own task.
    async def open_in_its_own_task() -> None:
        session = await sessions.get("conversation-1")
        result = await session.call_tool("list_my_appliances", {"household_id": "house-002"})
        assert result.isError is False

    await asyncio.create_task(open_in_its_own_task())

    # Simulates the FastAPI lifespan's shutdown, running in yet another task
    # (the test function's own task) -- this is exactly what used to raise
    # "Attempted to exit cancel scope in a different task than it was
    # entered in".
    await sessions.aclose()


async def test_a_second_conversation_gets_its_own_independent_session(server_url: str) -> None:
    target = MCPTarget(url=server_url, auth=None)
    sessions = SessionManager(target)

    session_a = await sessions.get("conversation-a")
    session_b = await sessions.get("conversation-b")

    assert session_a is not session_b
    assert sessions.is_open("conversation-a")
    assert sessions.is_open("conversation-b")
    assert not sessions.is_open("conversation-c")

    await sessions.aclose()


async def test_a_healthy_session_is_reused_not_replaced(server_url: str) -> None:
    target = MCPTarget(url=server_url, auth=None)
    sessions = SessionManager(target)

    session_a = await sessions.get("conversation-healthy")
    session_b = await sessions.get("conversation-healthy")

    assert session_a is session_b
    assert sessions.is_open("conversation-healthy")

    await sessions.aclose()


async def test_a_dead_session_owner_is_evicted_and_replaced(server_url: str) -> None:
    """Regression for the "one bad session stays broken forever" gap: once
    an owner's background task has died (simulated here by cancelling it,
    the same BaseException path a real connection failure would take --
    _SessionOwner._run's `except BaseException` catches and caches it
    either way), the next get() for that session_id must not keep replaying
    the cached error -- it should close the dead owner and hand back a
    fresh, working session instead."""
    target = MCPTarget(url=server_url, auth=None)
    sessions = SessionManager(target)

    session_a = await sessions.get("conversation-dead")
    dead_owner = sessions._owners["conversation-dead"]
    dead_owner._task.cancel()
    await dead_owner._task  # let the cancellation land; _run's except sets _error
    assert dead_owner.is_dead()
    assert not sessions.is_open("conversation-dead")

    session_b = await sessions.get("conversation-dead")

    assert session_b is not session_a
    assert sessions._owners["conversation-dead"] is not dead_owner
    result = await session_b.call_tool("list_my_appliances", {"household_id": "house-002"})
    assert result.isError is False

    await sessions.aclose()


async def test_concurrent_get_for_the_same_session_id_never_creates_duplicate_owners(
    server_url: str,
) -> None:
    target = MCPTarget(url=server_url, auth=None)
    sessions = SessionManager(target)

    results = await asyncio.gather(*[sessions.get("conversation-concurrent") for _ in range(8)])

    assert all(session is results[0] for session in results)
    assert len(sessions._owners) == 1

    await sessions.aclose()
