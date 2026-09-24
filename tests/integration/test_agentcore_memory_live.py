"""Against a REAL AgentCore Memory resource -- opt-in, needs AWS credentials.

    FIXIT_AGENTCORE_TESTS=1 FIXIT_AGENTCORE_MEMORY_ID=<id> \\
        uv run pytest tests/integration/test_agentcore_memory_live.py -v -s

Every test uses its own throwaway household id (`fixit-test-<uuid>`) and
deletes what it wrote, except the smoke test, which idempotently seeds the
demo households (house-001/002) because the smoke checks read them -- the
same thing `make seed-agentcore` does. `-s` shows the measured per-operation
latencies; AWS publishes none for AgentCore Memory, so these numbers are the
evidence for (or against) the 500ms budget -- see FRICTION_LOG.md, step 4b.
"""

import asyncio
import importlib.util
import os
import socket
import statistics
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from fixit_mcp.config import Settings
from fixit_mcp.domain.models import Appliance
from fixit_mcp.repository.agentcore_memory import (
    AgentCoreMemoryApplianceRepository,
    make_agentcore_memory_client,
)
from fixit_mcp.server import create_server

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SAMPLES = 20
TOOL_P95_BUDGET_MS = 500  # The Alexa+ requirement itself.

pytestmark = pytest.mark.skipif(
    os.environ.get("FIXIT_AGENTCORE_TESTS") != "1" or not os.environ.get("FIXIT_AGENTCORE_MEMORY_ID"),
    reason="live AgentCore Memory tests are opt-in: "
    "set FIXIT_AGENTCORE_TESTS=1 and FIXIT_AGENTCORE_MEMORY_ID",
)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"fixit_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _percentiles(label: str, samples_ms: list[float]) -> float:
    ordered = sorted(samples_ms)
    p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)]
    print(
        f"\n  {label}: n={len(ordered)} p50={statistics.median(ordered):.1f}ms "
        f"p95={p95:.1f}ms max={ordered[-1]:.1f}ms"
    )
    return p95


def _timed(fn: Callable[[], object]) -> float:
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000


def _appliance(appliance_id: str) -> Appliance:
    return Appliance(appliance_id=appliance_id, brand="GE", model="JBP26", appliance_type="range")


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(repository_backend="agentcore")


@pytest.fixture(scope="module")
def repository(settings: Settings) -> AgentCoreMemoryApplianceRepository:
    repo = AgentCoreMemoryApplianceRepository(
        memory_id=settings.agentcore_memory_id,
        client=make_agentcore_memory_client(settings.agentcore_region),
        registry_session_id=settings.agentcore_registry_session_id,
    )
    repo.warm_up()
    return repo


@pytest.fixture
def household(repository: AgentCoreMemoryApplianceRepository) -> Iterator[str]:
    household_id = f"fixit-test-{uuid.uuid4().hex[:12]}"
    try:
        yield household_id
    finally:
        for appliance in repository.list_by_household(household_id):
            repository.remove(household_id, appliance.appliance_id)


def test_round_trip_is_read_after_write_consistent(
    repository: AgentCoreMemoryApplianceRepository, household: str
) -> None:
    """The docs don't state ListEvents' consistency after CreateEvent. A
    customer who adds an appliance and immediately asks about it would hit
    exactly this, so it's checked with no delay at all."""
    appliance = _appliance("app-live-1")

    repository.add(household, appliance)
    assert repository.list_by_household(household) == [appliance]

    assert repository.remove(household, "app-live-1") is True
    assert repository.list_by_household(household) == []
    assert repository.remove(household, "app-live-1") is False


def test_repository_operation_latency(repository: AgentCoreMemoryApplianceRepository, household: str) -> None:
    add_ms = [
        _timed(lambda i=i: repository.add(household, _appliance(f"app-{i:03d}"))) for i in range(SAMPLES)
    ]
    list_ms = [_timed(lambda: repository.list_by_household(household)) for _ in range(SAMPLES)]
    remove_ms = [_timed(lambda i=i: repository.remove(household, f"app-{i:03d}")) for i in range(SAMPLES)]

    add_p95 = _percentiles("add (CreateEvent)", add_ms)
    list_p95 = _percentiles("list_by_household (ListEvents, ~20 events)", list_ms)
    remove_p95 = _percentiles("remove (ListEvents + DeleteEvent)", remove_ms)

    for label, p95 in (("add", add_p95), ("list", list_p95), ("remove", remove_p95)):
        assert p95 < TOOL_P95_BUDGET_MS, f"{label} alone is {p95:.0f}ms p95 -- over the whole tool budget"


@pytest_asyncio.fixture
async def live_server_url(
    settings: Settings, repository: AgentCoreMemoryApplianceRepository
) -> AsyncIterator[str]:
    _load("seed_agentcore_memory").seed_demo_households(repository)
    server_settings = settings.model_copy(
        update={"host": "127.0.0.1", "port": _free_port(), "log_level": "WARNING"}
    )
    mcp_server = create_server(settings=server_settings, repository=repository)
    server = uvicorn.Server(
        uvicorn.Config(
            mcp_server.streamable_http_app(),
            host=server_settings.host,
            port=server_settings.port,
            log_level="warning",
        )
    )
    serve_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    try:
        yield f"http://{server_settings.host}:{server_settings.port}{server_settings.streamable_http_path}"
    finally:
        server.should_exit = True
        await serve_task


async def test_smoke_checks_pass_against_real_agentcore_memory(live_server_url: str) -> None:
    """Same end-to-end suite as the dev server and the container, latency
    check included: diagnose_error with a household_id does a real
    ListEvents on every call."""
    smoke = _load("smoke_test")

    results = await smoke.run_smoke_checks(live_server_url)

    for line in results:
        print(f"\n  {line}")
    assert len(results) == len(smoke.CHECKS)


async def test_write_tool_round_trip_latency(live_server_url: str) -> None:
    """add_appliance and remove_appliance through the real MCP server --
    remove is the only two-AgentCore-call path, so it's the tightest."""
    household_id = f"fixit-test-{uuid.uuid4().hex[:12]}"
    add_ms: list[float] = []
    remove_ms: list[float] = []
    async with streamable_http_client(live_server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            for _ in range(SAMPLES // 2):
                start = time.perf_counter()
                added = await session.call_tool(
                    "add_appliance",
                    {
                        "household_id": household_id,
                        "brand": "GE",
                        "model": "JBP26",
                        "appliance_type": "range",
                    },
                )
                add_ms.append((time.perf_counter() - start) * 1000)
                appliance_id = added.structuredContent["appliance"]["appliance_id"]

                start = time.perf_counter()
                removed = await session.call_tool(
                    "remove_appliance", {"household_id": household_id, "appliance_id": appliance_id}
                )
                remove_ms.append((time.perf_counter() - start) * 1000)
                assert removed.structuredContent["removed"] is True

    assert _percentiles("add_appliance tool round trip", add_ms) < TOOL_P95_BUDGET_MS
    assert _percentiles("remove_appliance tool round trip", remove_ms) < TOOL_P95_BUDGET_MS
