import asyncio
import socket
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
import uvicorn

from fixit_mcp.config import Settings
from fixit_mcp.server import create_server


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest_asyncio.fixture
async def server_url(tmp_path: Path) -> AsyncIterator[str]:
    """Start a real FixIt MCP server on a free local port for the duration of a
    test. Uses the real "sqlite" repository backend (like a real run), but
    pointed at a fresh tmp_path file each test, so tests exercise the real
    persistence path while staying isolated from each other and from any
    real data/state/appliances.db on disk."""
    settings = Settings(
        host="127.0.0.1",
        port=_free_port(),
        log_level="WARNING",
        json_response=True,
        repository_backend="sqlite",
        sqlite_path=tmp_path / "appliances.db",
    )
    mcp_server = create_server(settings=settings)
    config = uvicorn.Config(
        mcp_server.streamable_http_app(),
        host=settings.host,
        port=settings.port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)

    try:
        yield f"http://{settings.host}:{settings.port}{settings.streamable_http_path}"
    finally:
        server.should_exit = True
        await serve_task
