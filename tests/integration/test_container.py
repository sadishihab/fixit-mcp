"""Runs the real Docker image and drives it from outside the container.

Opt-in (FIXIT_DOCKER_TESTS=1), because it needs Docker plus an already-built
image (`make docker-build`) and -- for the default linux/arm64 image on an
x86_64 host -- QEMU emulation, where each container cold start takes tens
of seconds. `make test` skips it rather than failing.

    make docker-build && FIXIT_DOCKER_TESTS=1 uv run pytest tests/integration/test_container.py -v

The two agentcore tests additionally need FIXIT_AGENTCORE_TESTS=1 and
FIXIT_AGENTCORE_MEMORY_ID (real AgentCore Memory, credentials from ~/.aws)
and skip without them.
"""

import asyncio
import importlib.util
import json
import os
import platform
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

IMAGE = os.environ.get("FIXIT_DOCKER_IMAGE", "fixit-mcp:latest")
SMOKE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smoke_test.py"
STARTUP_TIMEOUT_S = 120

pytestmark = pytest.mark.skipif(
    os.environ.get("FIXIT_DOCKER_TESTS") != "1" or shutil.which("docker") is None,
    reason="container tests are opt-in: set FIXIT_DOCKER_TESTS=1 (needs docker + `make docker-build`)",
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _image_arch() -> str:
    out = subprocess.run(
        ["docker", "image", "inspect", IMAGE], check=True, capture_output=True, text=True
    ).stdout
    return json.loads(out)[0]["Architecture"]


def _host_arch() -> str:
    return {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), platform.machine())


def _wait_until_up(url: str) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while True:
        try:
            httpx.get(url, timeout=2)
            return
        except httpx.TransportError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


def _start_container(port: int, volume: str | None = None, agentcore: bool = False) -> str:
    name = f"fixit-mcp-test-{uuid.uuid4().hex[:8]}"
    cmd = ["docker", "run", "-d", "--rm", "--name", name, "-p", f"127.0.0.1:{port}:8000"]
    if volume:
        cmd += ["-v", f"{volume}:/app/data/state"]
    if agentcore:
        # Local-only credential passing: the host's ~/.aws, read-only. On
        # AgentCore Runtime the execution role supplies credentials instead.
        cmd += [
            "-v",
            f"{Path.home() / '.aws'}:/aws:ro",
            "-e",
            "AWS_CONFIG_FILE=/aws/config",
            "-e",
            "AWS_SHARED_CREDENTIALS_FILE=/aws/credentials",
            "-e",
            "FIXIT_REPOSITORY_BACKEND=agentcore",
            "-e",
            f"FIXIT_AGENTCORE_MEMORY_ID={os.environ['FIXIT_AGENTCORE_MEMORY_ID']}",
        ]
    subprocess.run([*cmd, IMAGE], check=True, capture_output=True)
    return name


def _stop_container(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.fixture
def container_url() -> Iterator[str]:
    port = _free_port()
    name = _start_container(port)
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        _wait_until_up(url)
        yield url
    finally:
        _stop_container(name)


@pytest.fixture
def agentcore_container_url() -> Iterator[str]:
    if os.environ.get("FIXIT_AGENTCORE_TESTS") != "1" or not os.environ.get("FIXIT_AGENTCORE_MEMORY_ID"):
        pytest.skip(
            "also needs FIXIT_AGENTCORE_TESTS=1 and FIXIT_AGENTCORE_MEMORY_ID (real AgentCore Memory)"
        )
    port = _free_port()
    name = _start_container(port, agentcore=True)
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        _wait_until_up(url)
        yield url
    finally:
        _stop_container(name)


async def _household_count(url: str, household_id: str) -> int:
    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("list_my_appliances", {"household_id": household_id})
            return len(result.structuredContent["appliances"])


async def _add_one(url: str, household_id: str) -> None:
    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                "add_appliance",
                {"household_id": household_id, "brand": "GE", "model": "JBP26", "appliance_type": "range"},
            )
            assert result.isError is False


async def test_container_passes_the_same_smoke_checks_as_the_dev_server(container_url: str) -> None:
    spec = importlib.util.spec_from_file_location("fixit_smoke_test", SMOKE_SCRIPT)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    # Under QEMU the latency check would measure the emulator, not the
    # server -- only enforce it when the image runs natively.
    emulated = _image_arch() != _host_arch()

    results = await smoke.run_smoke_checks(container_url, skip_latency=emulated)

    assert len(results) == len(smoke.selected_checks(skip_latency=emulated))


def test_container_runs_as_non_root() -> None:
    out = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "id", IMAGE, "-u"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert out.stdout.strip() == "1000"


async def test_state_is_lost_in_a_fresh_container_without_a_volume() -> None:
    """Pins the behavior that matters for AgentCore Runtime: every new
    session gets a fresh microVM from the image, exactly like this second
    `docker run` -- so a household added in one is gone in the next."""
    household_id = f"persist-{uuid.uuid4().hex[:8]}"
    port = _free_port()
    url = f"http://127.0.0.1:{port}/mcp"

    first = _start_container(port)
    try:
        await asyncio.to_thread(_wait_until_up, url)
        await _add_one(url, household_id)
        assert await _household_count(url, household_id) == 1
    finally:
        _stop_container(first)

    second = _start_container(port)
    try:
        await asyncio.to_thread(_wait_until_up, url)
        assert await _household_count(url, household_id) == 0
    finally:
        _stop_container(second)


async def test_state_survives_a_fresh_container_with_a_named_volume() -> None:
    household_id = f"persist-{uuid.uuid4().hex[:8]}"
    volume = f"fixit-mcp-test-{uuid.uuid4().hex[:8]}"
    port = _free_port()
    url = f"http://127.0.0.1:{port}/mcp"

    try:
        first = _start_container(port, volume)
        try:
            await asyncio.to_thread(_wait_until_up, url)
            await _add_one(url, household_id)
        finally:
            _stop_container(first)

        second = _start_container(port, volume)
        try:
            await asyncio.to_thread(_wait_until_up, url)
            assert await _household_count(url, household_id) == 1
        finally:
            _stop_container(second)
    finally:
        subprocess.run(["docker", "volume", "rm", "-f", volume], capture_output=True)


async def test_container_on_real_agentcore_memory_passes_the_smoke_checks(
    agentcore_container_url: str,
) -> None:
    """The image as it will run on AgentCore Runtime: agentcore backend,
    real AgentCore Memory, household data outside the container. Needs the
    demo households seeded first (`make seed-agentcore`)."""
    spec = importlib.util.spec_from_file_location("fixit_smoke_test", SMOKE_SCRIPT)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    emulated = _image_arch() != _host_arch()

    results = await smoke.run_smoke_checks(agentcore_container_url, skip_latency=emulated)

    assert len(results) == len(smoke.selected_checks(skip_latency=emulated))


async def test_agentcore_state_survives_a_fresh_container(agentcore_container_url: str) -> None:
    """The exact failure step 4a flagged, now fixed: what one container
    (= one AgentCore session's microVM) writes, a brand-new one reads."""
    household_id = f"fixit-test-{uuid.uuid4().hex[:8]}"
    await _add_one(agentcore_container_url, household_id)

    port = _free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    second = _start_container(port, agentcore=True)
    try:
        await asyncio.to_thread(_wait_until_up, url)
        assert await _household_count(url, household_id) == 1
    finally:
        _stop_container(second)
        await _remove_all(agentcore_container_url, household_id)


async def _remove_all(url: str, household_id: str) -> None:
    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listed = await session.call_tool("list_my_appliances", {"household_id": household_id})
            for appliance in listed.structuredContent["appliances"]:
                await session.call_tool(
                    "remove_appliance",
                    {"household_id": household_id, "appliance_id": appliance["appliance_id"]},
                )
