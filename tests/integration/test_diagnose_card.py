from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from fixit_mcp.apps.resources import DIAGNOSE_CARD_HTML, DIAGNOSE_CARD_RESOURCE_URI


async def test_diagnose_error_tool_declares_the_ui_resource(server_url: str) -> None:
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools = await session.list_tools()
            diagnose_tool = next(t for t in tools.tools if t.name == "diagnose_error")

            assert diagnose_tool.meta is not None
            assert diagnose_tool.meta["ui"]["resourceUri"] == DIAGNOSE_CARD_RESOURCE_URI


async def test_diagnose_card_resource_is_readable_over_streamable_http(server_url: str) -> None:
    """Confirms the ui:// resource survives a real Streamable HTTP round
    trip: resources/read over the wire, not just an in-process function call."""
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.read_resource(DIAGNOSE_CARD_RESOURCE_URI)

            assert len(result.contents) == 1
            content = result.contents[0]
            assert content.mimeType == "text/html;profile=mcp-app"
            assert content.text == DIAGNOSE_CARD_HTML


async def test_diagnose_error_plain_result_is_unaffected_by_the_ui_resource(server_url: str) -> None:
    """The MCP Apps card is additive -- the plain structured JSON a
    text-only client depends on must be byte-for-byte the same shape as
    before this resource existed."""
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "diagnose_error", {"error_code": "tE1", "household_id": "house-002"}
            )

            assert result.isError is False
            content = result.structuredContent
            assert content["status"] == "found"
            assert content["appliance"]["brand"] == "LG"
