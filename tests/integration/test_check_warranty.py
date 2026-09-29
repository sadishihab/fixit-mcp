from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def test_check_warranty_expired_over_streamable_http(server_url: str) -> None:
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "check_warranty", {"household_id": "house-002", "appliance_type": "dryer"}
            )

            assert result.isError is False
            content = result.structuredContent
            assert content["status"] == "expired"
            assert content["appliance"]["brand"] == "LG"
            assert content["warranty_end_date"] == "2025-01-15"
            assert content["days_since_expiry"] > 0
            assert content["days_remaining"] is None
            assert "recorded" in content["message"]


async def test_check_warranty_ambiguous_appliance_over_streamable_http(server_url: str) -> None:
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # house-001's seed data has two GE appliances (app-001 fridge, app-004 oven).
            result = await session.call_tool("check_warranty", {"household_id": "house-001", "brand": "GE"})

            assert result.isError is False
            content = result.structuredContent
            assert content["status"] == "ambiguous_appliance"
            assert len(content["candidate_appliances"]) == 2


async def test_check_warranty_appliance_id_takes_precedence_over_streamable_http(server_url: str) -> None:
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "check_warranty",
                {"household_id": "house-001", "appliance_id": "app-001", "appliance_type": "dryer"},
            )

            assert result.isError is False
            content = result.structuredContent
            assert content["appliance"]["appliance_id"] == "app-001"


async def test_check_warranty_not_found_over_streamable_http(server_url: str) -> None:
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "check_warranty", {"household_id": "house-002", "appliance_type": "refrigerator"}
            )

            assert result.isError is False
            content = result.structuredContent
            assert content["status"] == "not_found"
            assert content["appliance"] is None
