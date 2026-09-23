from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

LATEST_PROTOCOL_VERSION = "2025-11-25"


async def test_negotiates_latest_protocol_version(server_url: str) -> None:
    """The hackathon and Alexa+ both require MCP spec 2025-11-25 over Streamable HTTP."""
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            result = await session.initialize()

            assert result.protocolVersion == LATEST_PROTOCOL_VERSION


async def test_list_my_appliances_over_streamable_http(server_url: str) -> None:
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool("list_my_appliances", {"household_id": "house-001"})

            assert result.isError is False
            assert result.structuredContent is not None
            assert result.structuredContent["household_id"] == "house-001"
            assert len(result.structuredContent["appliances"]) == 2
            assert {a["brand"] for a in result.structuredContent["appliances"]} == {"Whirlpool", "Bosch"}


async def test_list_my_appliances_unknown_household_returns_empty_list(server_url: str) -> None:
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool("list_my_appliances", {"household_id": "no-such-household"})

            assert result.isError is False
            assert result.structuredContent["appliances"] == []
