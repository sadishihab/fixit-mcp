"""The real server, over real Streamable HTTP, on the "agentcore" repository
backend -- with only the AWS client faked. Proves the tools behave the same
on this backend as on sqlite (same smoke checks), without AWS credentials.
The same checks against *real* AgentCore Memory live in
test_agentcore_memory_live.py (opt-in)."""

import asyncio
import importlib.util
import socket
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
import uvicorn

from fixit_mcp.config import Settings
from fixit_mcp.repository.agentcore_memory import AgentCoreMemoryApplianceRepository
from fixit_mcp.server import create_server
from tests.fakes import FakeAgentCoreMemoryClient

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"fixit_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest_asyncio.fixture
async def fake_agentcore_server() -> AsyncIterator[tuple[str, FakeAgentCoreMemoryClient]]:
    client = FakeAgentCoreMemoryClient()
    repository = AgentCoreMemoryApplianceRepository("FixItHouseholds-a1B2c3D4e5", client)
    _load("seed_agentcore_memory").seed_demo_households(repository)
    settings = Settings(
        _env_file=None,
        host="127.0.0.1",
        port=_free_port(),
        log_level="WARNING",
        repository_backend="agentcore",
    )
    mcp_server = create_server(settings=settings, repository=repository)
    server = uvicorn.Server(
        uvicorn.Config(
            mcp_server.streamable_http_app(), host=settings.host, port=settings.port, log_level="warning"
        )
    )
    serve_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    try:
        yield f"http://{settings.host}:{settings.port}{settings.streamable_http_path}", client
    finally:
        server.should_exit = True
        await serve_task


async def test_every_smoke_check_passes_on_the_agentcore_backend(
    fake_agentcore_server: tuple[str, FakeAgentCoreMemoryClient],
) -> None:
    url, _ = fake_agentcore_server
    smoke = _load("smoke_test")

    results = await smoke.run_smoke_checks(url)

    assert len(results) == len(smoke.CHECKS)


async def test_smoke_checks_leave_no_events_behind(
    fake_agentcore_server: tuple[str, FakeAgentCoreMemoryClient],
) -> None:
    """The smoke suite runs against real AgentCore Memory too (step 4b), so
    its add_appliance check must clean up after itself there as well."""
    url, client = fake_agentcore_server
    smoke = _load("smoke_test")

    await smoke.run_smoke_checks(url, skip_latency=True)

    leftover = {actor for (_, actor, _), events in client.events.items() if events}
    assert leftover == {"house-001", "house-002"}
