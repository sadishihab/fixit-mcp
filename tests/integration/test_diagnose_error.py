from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def test_diagnose_error_resolves_via_household_over_streamable_http(server_url: str) -> None:
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
            assert content["appliance"]["model"] == "DLEX8000W"
            assert content["difficulty"] == "call_service"
            assert content["citation"]["brand"] == "LG"


async def test_diagnose_error_normalizes_spoken_style_input(server_url: str) -> None:
    """A customer (or Alexa+'s ASR) is more likely to say "E twenty sixty" than
    type the manual's exact "E:20-60" punctuation -- normalization must still match."""
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool("diagnose_error", {"error_code": "e20 60"})

            assert result.isError is False
            content = result.structuredContent
            assert content["status"] == "found"
            assert content["error_code"] == "E:20-60"  # manufacturer's exact spelling, not the query's
            assert content["citation"]["brand"] == "Bosch"


async def test_diagnose_error_dedup_picks_the_complete_record(server_url: str) -> None:
    """Regression test for the real Bosch E:34-00 duplicate (step 3a/3b): the
    chunk-overlap boundary produced one incomplete and one complete record
    for this code; the server must only ever surface the complete one."""
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool("diagnose_error", {"error_code": "E:34-00"})

            assert result.isError is False
            content = result.structuredContent
            assert content["status"] == "found"
            assert content["confidence"] == 1.0
            assert len(content["repair_steps"]) == 2


async def test_diagnose_error_unknown_code_over_streamable_http(server_url: str) -> None:
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool("diagnose_error", {"error_code": "Z999-NOPE"})

            assert result.isError is False
            content = result.structuredContent
            assert content["status"] == "not_found"
            assert content["repair_steps"] == []
            assert content["meaning"] == ""
