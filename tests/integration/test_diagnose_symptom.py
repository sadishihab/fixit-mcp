"""diagnose_symptom over real Streamable HTTP with the official MCP client.

Two servers: one built on invented data (so the assertions can be exact without quoting any manual),
and the default server on the committed index (a wiring check only, with short customer phrases).
"""

import asyncio
import socket
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from fixit_mcp.config import Settings
from fixit_mcp.server import create_server
from tests.symptom_fixtures import synthetic_index, synthetic_repository


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest_asyncio.fixture
async def synthetic_url(tmp_path: Path) -> AsyncIterator[str]:
    settings = Settings(host="127.0.0.1", port=_free_port(), log_level="WARNING", json_response=True)
    server_app = create_server(
        settings=settings, repository=synthetic_repository(), symptom_index=synthetic_index()
    ).streamable_http_app()
    server = uvicorn.Server(
        uvicorn.Config(server_app, host=settings.host, port=settings.port, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    try:
        yield f"http://{settings.host}:{settings.port}{settings.streamable_http_path}"
    finally:
        server.should_exit = True
        await task


async def _call(url: str, arguments: dict):
    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool("diagnose_symptom", arguments)


async def test_found_returns_the_manual_rows_with_a_citation(synthetic_url: str) -> None:
    result = await _call(synthetic_url, {"household_id": "h-washer", "symptom": "the drum stays still"})

    assert result.isError is False
    content = result.structuredContent
    assert content["status"] == "found" and content["appliance_registered"] is True
    (match,) = content["matches"]
    assert match["symptom"] == ["Drum stays still"]
    assert [r["what_to_do"] for r in match["rows"]] == [["Close the hatch firmly."], ["Push the plug in."]]
    assert match["citation"] == {
        "brand": "Acme",
        "model": "W100",
        "page": 5,
        "section": "Troubleshooting Tips",
    }


async def test_ambiguous_appliance_over_http(synthetic_url: str) -> None:
    result = await _call(synthetic_url, {"household_id": "h-both", "symptom": "water pours out"})

    content = result.structuredContent
    assert content["status"] == "ambiguous_appliance" and content["matches"] == []
    assert {c["appliance_id"] for c in content["candidate_appliances"]} == {"a-w", "a-f"}


async def test_appliance_type_resolves_it_over_http(synthetic_url: str) -> None:
    result = await _call(
        synthetic_url, {"household_id": "h-both", "symptom": "water pours out", "appliance_type": "fridge"}
    )

    assert result.structuredContent["status"] == "found"
    assert result.structuredContent["appliance"]["appliance_id"] == "a-f"


async def test_unregistered_appliance_notice_over_http(synthetic_url: str) -> None:
    result = await _call(synthetic_url, {"household_id": "h-fridge", "symptom": "the drum stays still"})

    content = result.structuredContent
    assert content["status"] == "found" and content["appliance_registered"] is False
    assert content["suggest_add_appliance"] is True and content["appliance"]["appliance_id"] == ""


async def test_not_found_over_http(synthetic_url: str) -> None:
    result = await _call(synthetic_url, {"household_id": "h-washer", "symptom": "my television is blurry"})

    content = result.structuredContent
    assert result.isError is False and content["status"] == "not_found" and content["matches"] == []


async def test_the_tool_is_listed_with_its_llm_facing_description(synthetic_url: str) -> None:
    async with streamable_http_client(synthetic_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = {t.name: t for t in (await session.list_tools()).tools}

    assert len(tools) == 6
    tool = tools["diagnose_symptom"]
    assert set(tool.inputSchema["required"]) == {"household_id", "symptom"}
    assert {"appliance_type", "appliance_id"} <= set(tool.inputSchema["properties"])
    assert "diagnose_error" in tool.description


@pytest.mark.parametrize("protocol_version", ["2025-11-25", "2025-03-26"])
async def test_both_protocol_versions_can_call_it(synthetic_url: str, protocol_version: str) -> None:
    import httpx

    async with httpx.AsyncClient() as client:
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        init = await client.post(
            synthetic_url,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": protocol_version,
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            },
        )
        assert init.json()["result"]["protocolVersion"] == protocol_version
        call = await client.post(
            synthetic_url,
            headers={**headers, "MCP-Protocol-Version": protocol_version},
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "diagnose_symptom",
                    "arguments": {"household_id": "h-washer", "symptom": "drum stays still"},
                },
            },
        )
    assert call.json()["result"]["structuredContent"]["status"] == "found"


async def test_the_default_server_serves_the_committed_index(server_url: str) -> None:
    """Wiring check against the real data: a short customer phrase finds a cited entry."""
    result = await _call(
        server_url, {"household_id": "house-001", "symptom": "the refrigerator keeps beeping"}
    )

    content = result.structuredContent
    assert result.isError is False and content["status"] == "found"
    assert content["appliance_registered"] is True and content["appliance"]["brand"] == "GE"
    assert content["matches"][0]["citation"]["page"] > 0


# --- the MCP Apps card (step 27a) -----------------------------------------------------------------


async def test_the_tool_definition_declares_the_symptom_card_resource(synthetic_url: str) -> None:
    from fixit_mcp.apps.resources import DIAGNOSE_CARD_RESOURCE_URI, SYMPTOM_CARD_RESOURCE_URI

    async with streamable_http_client(synthetic_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = {t.name: t for t in (await session.list_tools()).tools}

    assert tools["diagnose_symptom"].meta["ui"]["resourceUri"] == SYMPTOM_CARD_RESOURCE_URI
    assert tools["diagnose_error"].meta["ui"]["resourceUri"] == DIAGNOSE_CARD_RESOURCE_URI
    assert SYMPTOM_CARD_RESOURCE_URI != DIAGNOSE_CARD_RESOURCE_URI


async def test_both_card_resources_are_listed_and_the_symptom_card_is_readable(synthetic_url: str) -> None:
    from fixit_mcp.apps.resources import SYMPTOM_CARD_HTML, SYMPTOM_CARD_RESOURCE_URI

    async with streamable_http_client(synthetic_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listed = {str(r.uri): r for r in (await session.list_resources()).resources}
            read = await session.read_resource(SYMPTOM_CARD_RESOURCE_URI)

    assert set(listed) == {"ui://fixit-mcp/diagnose-error-card", SYMPTOM_CARD_RESOURCE_URI}
    assert listed[SYMPTOM_CARD_RESOURCE_URI].mimeType == "text/html;profile=mcp-app"
    (content,) = read.contents
    assert content.mimeType == "text/html;profile=mcp-app" and content.text == SYMPTOM_CARD_HTML


async def test_the_plain_symptom_result_is_unaffected_by_the_card(synthetic_url: str) -> None:
    result = await _call(synthetic_url, {"household_id": "h-washer", "symptom": "the drum stays still"})

    assert result.isError is False
    assert result.structuredContent["status"] == "found" and result.structuredContent["matches"]
