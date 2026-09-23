import time

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

CALL_COUNT = 50
P95_BUDGET_MS = 100  # Headroom under the 500ms Alexa+ round-trip requirement.


def _p95(latencies_ms: list[float]) -> float:
    latencies_ms = sorted(latencies_ms)
    return latencies_ms[int(len(latencies_ms) * 0.95) - 1]


async def test_tool_call_p95_latency_under_budget(server_url: str) -> None:
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            latencies_ms: list[float] = []
            for _ in range(CALL_COUNT):
                start = time.perf_counter()
                result = await session.call_tool("list_my_appliances", {"household_id": "house-001"})
                latencies_ms.append((time.perf_counter() - start) * 1000)
                assert result.isError is False

            p95_ms = _p95(latencies_ms)
            assert p95_ms < P95_BUDGET_MS, f"p95 latency {p95_ms:.2f}ms exceeded {P95_BUDGET_MS}ms budget"


async def test_diagnose_error_p95_latency_under_budget_with_index_loaded(server_url: str) -> None:
    """The full committed error-code index is loaded into the server exactly
    once at startup (fixit_mcp.retrieval.codes.load_index) -- this confirms
    the per-request path is pure in-memory lookups, not re-reading the file,
    by timing repeated calls against the already-running server."""
    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            latencies_ms: list[float] = []
            for _ in range(CALL_COUNT):
                start = time.perf_counter()
                result = await session.call_tool(
                    "diagnose_error", {"error_code": "tE1", "household_id": "house-002"}
                )
                latencies_ms.append((time.perf_counter() - start) * 1000)
                assert result.isError is False

            p95_ms = _p95(latencies_ms)
            assert p95_ms < P95_BUDGET_MS, f"p95 latency {p95_ms:.2f}ms exceeded {P95_BUDGET_MS}ms budget"
