import mcp.types as types
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

# The Alexa+ MCP Toolkit client-lifecycle docs show the Alexa+ client sending
# this protocolVersion on initialize. The mcp SDK's ClientSession always sends
# its own LATEST_PROTOCOL_VERSION, so this test drives the raw initialize
# request/notification to reproduce what an older client actually sends.
ALEXA_PLUS_DOCS_PROTOCOL_VERSION = "2025-03-26"


async def _initialize_with_protocol_version(
    session: ClientSession, protocol_version: str
) -> types.InitializeResult:
    result = await session.send_request(
        types.ClientRequest(
            types.InitializeRequest(
                params=types.InitializeRequestParams(
                    protocolVersion=protocol_version,
                    capabilities=types.ClientCapabilities(),
                    clientInfo=types.Implementation(name="alexa-plus-legacy-test-client", version="1.0"),
                )
            )
        ),
        types.InitializeResult,
    )
    await session.send_notification(types.ClientNotification(types.InitializedNotification()))
    return result


async def test_negotiates_legacy_protocol_version(server_url: str) -> None:
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            result = await _initialize_with_protocol_version(session, ALEXA_PLUS_DOCS_PROTOCOL_VERSION)

            assert result.protocolVersion == ALEXA_PLUS_DOCS_PROTOCOL_VERSION


async def test_tool_call_still_works_with_legacy_protocol_version(server_url: str) -> None:
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await _initialize_with_protocol_version(session, ALEXA_PLUS_DOCS_PROTOCOL_VERSION)

            result = await session.call_tool("list_my_appliances", {"household_id": "house-002"})

            assert result.isError is False
            assert result.structuredContent["household_id"] == "house-002"
            assert len(result.structuredContent["appliances"]) == 1
            assert result.structuredContent["appliances"][0]["brand"] == "LG"
