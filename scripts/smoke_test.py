"""End-to-end smoke checks against a running FixIt MCP server, at any URL.

Used to confirm the Docker image (`make docker-smoke`) behaves the same as
the local dev server, and intended to be pointed at the AgentCore Runtime
endpoint unchanged once one exists (step 4b). Drives the server with the
official MCP client over real Streamable HTTP -- nothing is mocked.

    uv run python scripts/smoke_test.py [--url http://localhost:8000/mcp]

Pass --skip-latency when the server is an arm64 image running under QEMU
on an x86_64 host (`make docker-smoke` does this automatically): emulation
makes round trips ~10x slower than real Graviton, so the latency check there
measures QEMU, not the server.

Exits non-zero on the first failed check. Every check that mutates state
(add_appliance) uses a throwaway household id and cleans up after itself,
so running this against a server with real data is safe.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from collections.abc import Awaitable, Callable

import httpx
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client

DEFAULT_URL = "http://localhost:8000/mcp"
LATEST_PROTOCOL_VERSION = "2025-11-25"
# What the Alexa+ MCP Toolkit docs show its client sending (CLAUDE.md rule 2).
ALEXA_PLUS_PROTOCOL_VERSION = "2025-03-26"
EXPECTED_TOOLS = {"list_my_appliances", "add_appliance", "remove_appliance", "diagnose_error"}
DIAGNOSE_CARD_URI = "ui://fixit-mcp/diagnose-error-card"
LATENCY_CALLS = 20
P95_BUDGET_MS = 500  # The Alexa+ round-trip requirement itself, not the tighter local test budget.


class SmokeCheckFailed(AssertionError):
    pass


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeCheckFailed(message)


async def _with_session(url: str, body: Callable[[ClientSession], Awaitable[None]]) -> None:
    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await body(session)


async def check_latest_protocol(url: str) -> str:
    async def body(session: ClientSession) -> None:
        result = await session.initialize()
        _check(
            result.protocolVersion == LATEST_PROTOCOL_VERSION,
            f"negotiated {result.protocolVersion!r}, expected {LATEST_PROTOCOL_VERSION!r}",
        )

    await _with_session(url, body)
    return f"initialize negotiates {LATEST_PROTOCOL_VERSION}"


async def check_legacy_protocol(url: str) -> str:
    async def body(session: ClientSession) -> None:
        result = await session.send_request(
            types.ClientRequest(
                types.InitializeRequest(
                    params=types.InitializeRequestParams(
                        protocolVersion=ALEXA_PLUS_PROTOCOL_VERSION,
                        capabilities=types.ClientCapabilities(),
                        clientInfo=types.Implementation(name="fixit-smoke-legacy", version="1.0"),
                    )
                )
            ),
            types.InitializeResult,
        )
        await session.send_notification(types.ClientNotification(types.InitializedNotification()))
        _check(
            result.protocolVersion == ALEXA_PLUS_PROTOCOL_VERSION,
            f"legacy client got {result.protocolVersion!r}, expected {ALEXA_PLUS_PROTOCOL_VERSION!r}",
        )
        listed = await session.call_tool("list_my_appliances", {"household_id": "house-002"})
        _check(listed.isError is False, f"list_my_appliances failed under legacy protocol: {listed}")

    await _with_session(url, body)
    return f"initialize negotiates legacy {ALEXA_PLUS_PROTOCOL_VERSION} and tool calls still work"


async def check_tools_listed(url: str) -> str:
    async def body(session: ClientSession) -> None:
        await session.initialize()
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        _check(EXPECTED_TOOLS <= tools.keys(), f"missing tools: {EXPECTED_TOOLS - tools.keys()}")
        meta = tools["diagnose_error"].meta or {}
        _check(
            meta.get("ui", {}).get("resourceUri") == DIAGNOSE_CARD_URI,
            f"diagnose_error ui meta wrong: {meta}",
        )

    await _with_session(url, body)
    return f"tools/list returns {sorted(EXPECTED_TOOLS)}"


async def check_list_my_appliances(url: str) -> str:
    async def body(session: ClientSession) -> None:
        await session.initialize()
        result = await session.call_tool("list_my_appliances", {"household_id": "house-002"})
        _check(result.isError is False, f"list_my_appliances errored: {result}")
        brands = {a["brand"] for a in result.structuredContent["appliances"]}
        _check(brands == {"GE", "LG"}, f"house-002 seed data wrong: {brands}")

    await _with_session(url, body)
    return "list_my_appliances(house-002) returns the seeded GE + LG appliances"


async def check_diagnose_error(url: str) -> str:
    async def body(session: ClientSession) -> None:
        await session.initialize()
        result = await session.call_tool("diagnose_error", {"error_code": "tE1", "household_id": "house-002"})
        _check(result.isError is False, f"diagnose_error errored: {result}")
        content = result.structuredContent
        _check(content["status"] == "found", f"expected found, got {content['status']!r}")
        _check(content["appliance"]["brand"] == "LG", f"wrong appliance: {content['appliance']}")

    await _with_session(url, body)
    return "diagnose_error(tE1, house-002) finds the LG dryer code (error-code index loaded)"


async def check_diagnose_card(url: str) -> str:
    async def body(session: ClientSession) -> None:
        await session.initialize()
        result = await session.read_resource(DIAGNOSE_CARD_URI)
        _check(len(result.contents) == 1, f"expected one resource content, got {len(result.contents)}")
        _check(
            result.contents[0].mimeType == "text/html;profile=mcp-app",
            f"wrong card MIME type: {result.contents[0].mimeType!r}",
        )

    await _with_session(url, body)
    return f"resources/read {DIAGNOSE_CARD_URI} returns the MCP Apps card"


async def check_add_links_manual(url: str) -> str:
    """add_appliance links to a manual only if data/manuals/manifest.yaml
    was found at startup -- load_manual_catalog() silently returns an empty
    catalog when it isn't, so this is the check that catches a missing file."""
    household_id = f"smoke-{uuid.uuid4().hex[:12]}"

    async def body(session: ClientSession) -> None:
        await session.initialize()
        added = await session.call_tool(
            "add_appliance",
            {
                "household_id": household_id,
                "brand": "Bosch",
                "model": "SHE53B75UC",
                "appliance_type": "dishwasher",
            },
        )
        _check(added.isError is False, f"add_appliance errored: {added}")
        appliance_id = added.structuredContent["appliance"]["appliance_id"]
        try:
            _check(
                added.structuredContent["manual_linked"] is True,
                "add_appliance didn't link the Bosch manual -- manual catalog not loaded?",
            )
        finally:
            await session.call_tool(
                "remove_appliance", {"household_id": household_id, "appliance_id": appliance_id}
            )

    await _with_session(url, body)
    return "add_appliance links a known model to its manual (manifest loaded), then cleans up"


async def check_platform_session_id_accepted(url: str) -> str:
    """AgentCore injects its own Mcp-Session-Id on every request; a stateless
    server must not reject a session id it never issued (CLAUDE.md rule 5)."""
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Mcp-Session-Id": f"agentcore-platform-{uuid.uuid4()}",
        "Mcp-Protocol-Version": LATEST_PROTOCOL_VERSION,
    }
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "list_my_appliances", "arguments": {"household_id": "house-001"}},
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(url, json=payload, headers=headers)
    _check(response.status_code == 200, f"foreign Mcp-Session-Id rejected: HTTP {response.status_code}")
    _check("result" in response.json(), f"no JSON-RPC result: {response.text[:200]}")
    return "a foreign, platform-style Mcp-Session-Id header is accepted, not rejected"


async def check_latency(url: str) -> str:
    latencies_ms: list[float] = []

    async def body(session: ClientSession) -> None:
        await session.initialize()
        for _ in range(LATENCY_CALLS):
            start = time.perf_counter()
            result = await session.call_tool(
                "diagnose_error", {"error_code": "tE1", "household_id": "house-002"}
            )
            latencies_ms.append((time.perf_counter() - start) * 1000)
            _check(result.isError is False, f"diagnose_error errored during latency run: {result}")

    await _with_session(url, body)
    latencies_ms.sort()
    p95 = latencies_ms[int(len(latencies_ms) * 0.95) - 1]
    _check(p95 < P95_BUDGET_MS, f"diagnose_error p95 {p95:.1f}ms exceeds {P95_BUDGET_MS}ms")
    return f"diagnose_error p95 {p95:.1f}ms over {LATENCY_CALLS} calls (budget {P95_BUDGET_MS}ms)"


CHECKS: list[Callable[[str], Awaitable[str]]] = [
    check_latest_protocol,
    check_legacy_protocol,
    check_tools_listed,
    check_list_my_appliances,
    check_diagnose_error,
    check_diagnose_card,
    check_add_links_manual,
    check_platform_session_id_accepted,
    check_latency,
]


def selected_checks(skip_latency: bool = False) -> list[Callable[[str], Awaitable[str]]]:
    return [check for check in CHECKS if not (skip_latency and check is check_latency)]


async def run_smoke_checks(url: str, skip_latency: bool = False) -> list[str]:
    """Run every check in order; raise SmokeCheckFailed on the first failure."""
    return [await check(url) for check in selected_checks(skip_latency)]


async def _wait_until_up(url: str, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient(timeout=2) as client:
        while True:
            try:
                await client.get(url)
                return
            except httpx.TransportError:
                if time.monotonic() > deadline:
                    raise
                await asyncio.sleep(0.5)


async def _main(url: str, wait_s: float, skip_latency: bool) -> int:
    await _wait_until_up(url, wait_s)
    checks = selected_checks(skip_latency)
    for check in checks:
        try:
            print(f"PASS  {await check(url)}")
        except SmokeCheckFailed as exc:
            print(f"FAIL  {check.__name__}: {exc}")
            return 1
    if skip_latency:
        print("SKIP  check_latency (--skip-latency)")
    print(f"All {len(checks)} smoke checks passed against {url}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--wait", type=float, default=30, help="seconds to wait for the server to come up")
    parser.add_argument(
        "--skip-latency",
        action="store_true",
        help="skip the p95 latency check -- for an arm64 image running under QEMU emulation on an "
        "x86_64 host, where round trips are ~10x slower than on real Graviton (FRICTION_LOG.md, step 4a)",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.url, args.wait, args.skip_latency)))
