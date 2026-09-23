import time

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

CALL_COUNT = 50
P95_BUDGET_MS = 100  # Headroom under the 500ms Alexa+ round-trip requirement.


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

            latencies_ms.sort()
            p95_index = int(len(latencies_ms) * 0.95) - 1
            p95_ms = latencies_ms[p95_index]

            assert p95_ms < P95_BUDGET_MS, f"p95 latency {p95_ms:.2f}ms exceeded {P95_BUDGET_MS}ms budget"
