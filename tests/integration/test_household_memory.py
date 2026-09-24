import asyncio
import socket
from pathlib import Path

import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from fixit_mcp.config import Settings
from fixit_mcp.server import create_server


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _RunningServer:
    def __init__(self, url: str, server: uvicorn.Server, task: asyncio.Task) -> None:
        self.url = url
        self._server = server
        self._task = task

    async def stop(self) -> None:
        self._server.should_exit = True
        await self._task


async def _start_server(db_path: Path) -> _RunningServer:
    settings = Settings(
        host="127.0.0.1",
        port=_free_port(),
        log_level="WARNING",
        json_response=True,
        repository_backend="sqlite",
        sqlite_path=db_path,
    )
    mcp_server = create_server(settings=settings)
    config = uvicorn.Config(
        mcp_server.streamable_http_app(), host=settings.host, port=settings.port, log_level="warning"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    url = f"http://{settings.host}:{settings.port}{settings.streamable_http_path}"
    return _RunningServer(url, server, task)


async def test_add_appliance_then_list_shows_it_over_streamable_http(server_url: str) -> None:
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            before = await session.call_tool("list_my_appliances", {"household_id": "house-new"})
            assert before.structuredContent["appliances"] == []

            added = await session.call_tool(
                "add_appliance",
                {
                    "household_id": "house-new",
                    "brand": "Bosch",
                    "model": "SHE53B75UC",
                    "appliance_type": "dishwasher",
                },
            )
            assert added.isError is False
            assert added.structuredContent["manual_linked"] is True

            after = await session.call_tool("list_my_appliances", {"household_id": "house-new"})
            appliances = after.structuredContent["appliances"]
            assert len(appliances) == 1
            assert appliances[0]["brand"] == "Bosch"


async def test_add_appliance_without_a_manual_still_saves_it(server_url: str) -> None:
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "add_appliance",
                {
                    "household_id": "house-new",
                    "brand": "Samsung",
                    "model": "RF28",
                    "appliance_type": "refrigerator",
                },
            )

            content = result.structuredContent
            assert content["manual_linked"] is False
            assert content["appliance"]["manual_id"] == ""
            assert "limited" in content["message"].lower()


async def test_add_then_remove_appliance_round_trip(server_url: str) -> None:
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            added = await session.call_tool(
                "add_appliance",
                {
                    "household_id": "house-new",
                    "brand": "Bosch",
                    "model": "SHE53B75UC",
                    "appliance_type": "dishwasher",
                },
            )
            appliance_id = added.structuredContent["appliance"]["appliance_id"]

            removed = await session.call_tool(
                "remove_appliance", {"household_id": "house-new", "appliance_id": appliance_id}
            )
            assert removed.structuredContent["removed"] is True

            after = await session.call_tool("list_my_appliances", {"household_id": "house-new"})
            assert after.structuredContent["appliances"] == []


async def test_diagnose_error_resolves_via_a_newly_added_appliance(server_url: str) -> None:
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            await session.call_tool(
                "add_appliance",
                {
                    "household_id": "house-new",
                    "brand": "Bosch",
                    "model": "SHE53B75UC",
                    "appliance_type": "dishwasher",
                },
            )

            result = await session.call_tool(
                "diagnose_error", {"error_code": "E:20-60", "household_id": "house-new"}
            )

            content = result.structuredContent
            assert content["status"] == "found"
            assert content["appliance"]["brand"] == "Bosch"
            assert content["citation"]["brand"] == "Bosch"


async def test_diagnose_error_suggests_add_appliance_for_unregistered_household(server_url: str) -> None:
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "diagnose_error", {"error_code": "Z999-NOPE", "household_id": "house-brand-new-empty"}
            )

            content = result.structuredContent
            assert content["status"] == "not_found"
            assert content["suggest_add_appliance"] is True
            assert "add_appliance" in content["message"]


async def test_appliances_persist_across_a_server_restart(tmp_path: Path) -> None:
    """The whole point of step 3c: state survives the process restarting,
    not just a fresh repository object within the same process."""
    db_path = tmp_path / "restart-test.db"

    first = await _start_server(db_path)
    try:
        async with streamable_http_client(first.url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                await session.call_tool(
                    "add_appliance",
                    {
                        "household_id": "house-restart",
                        "brand": "Bosch",
                        "model": "SHE53B75UC",
                        "appliance_type": "dishwasher",
                    },
                )
    finally:
        await first.stop()

    second = await _start_server(db_path)
    try:
        async with streamable_http_client(second.url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool("list_my_appliances", {"household_id": "house-restart"})
                appliances = result.structuredContent["appliances"]
                assert len(appliances) == 1
                assert appliances[0]["brand"] == "Bosch"

                diagnosis = await session.call_tool(
                    "diagnose_error", {"error_code": "E:20-60", "household_id": "house-restart"}
                )
                assert diagnosis.structuredContent["status"] == "found"
    finally:
        await second.stop()
