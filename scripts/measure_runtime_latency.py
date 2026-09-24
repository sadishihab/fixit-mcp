"""Measure end-to-end latency against a deployed FixIt AgentCore Runtime --
cold sessions and warm calls -- and split it into its parts.

    uv run python scripts/measure_runtime_latency.py --agent-arn <arn> [--cold 5] [--warm 30]

What a client-measured tool call contains:

    client latency = network RTT + AgentCore Runtime overhead + our handler (incl. AgentCore Memory)

This script measures the first directly, reads the third from the server's
own `tool_call_completed` logs in CloudWatch, and reports the remainder as
the Runtime-overhead estimate (plus FixIt's own ~17ms request stack) --
the number step 4c exists to pin down
(FRICTION_LOG's unverified "~200ms warm p50"). Run it from AWS CloudShell in
the runtime's region for the cleanest numbers; from farther away, the RTT
subtraction still makes the overhead estimate usable, just noisier.

- cold: N brand-new MCP sessions (no Mcp-Session-Id => AgentCore provisions
  a new session/microVM), timing initialize and the first tool call. The
  very first one after a fresh deploy is the "genuinely cold" sample.
- warm: M sequential calls in one session (sticky microVM).
Every tool call is `diagnose_error(tE1, house-002)` -- a real AgentCore
Memory read per call, the same path Alexa+ will exercise most.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import socket
import statistics
import sys
import time
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

TOOL = "diagnose_error"
TOOL_ARGS = {"error_code": "tE1", "household_id": "house-002"}


def _load_smoke():
    path = Path(__file__).resolve().parent / "smoke_test.py"
    spec = importlib.util.spec_from_file_location("fixit_smoke_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def percentile(samples: list[float], pct: float) -> float:
    ordered = sorted(samples)
    return ordered[max(0, min(len(ordered) - 1, int(round(len(ordered) * pct / 100)) - 1))]


def summarize(label: str, samples: list[float]) -> str:
    if not samples:
        return f"{label}: no samples"
    return (
        f"{label}: n={len(samples)} p50={statistics.median(samples):.1f}ms "
        f"p95={percentile(samples, 95):.1f}ms min={min(samples):.1f}ms max={max(samples):.1f}ms"
    )


def measure_tcp_rtt(host: str, port: int = 443, samples: int = 5) -> list[float]:
    """TCP connect time ~= one network round trip to the endpoint."""
    rtts = []
    for _ in range(samples):
        start = time.perf_counter()
        with socket.create_connection((host, port), timeout=5):
            rtts.append((time.perf_counter() - start) * 1000)
    return rtts


async def _timed(coro) -> tuple[Any, float]:
    start = time.perf_counter()
    result = await coro
    return result, (time.perf_counter() - start) * 1000


async def cold_sample(url: str, auth: httpx.Auth | None) -> tuple[float, float]:
    """(initialize ms, first tool call ms) on a brand-new session."""
    async with create_mcp_http_client(auth=auth) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                _, init_ms = await _timed(session.initialize())
                result, call_ms = await _timed(session.call_tool(TOOL, TOOL_ARGS))
                if result.isError:
                    raise RuntimeError(f"{TOOL} failed: {result.content}")
                return init_ms, call_ms


async def warm_samples(url: str, auth: httpx.Auth | None, calls: int) -> list[float]:
    latencies = []
    async with create_mcp_http_client(auth=auth) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                await session.call_tool(TOOL, TOOL_ARGS)  # settle the session before timing
                for _ in range(calls):
                    result, ms = await _timed(session.call_tool(TOOL, TOOL_ARGS))
                    if result.isError:
                        raise RuntimeError(f"{TOOL} failed: {result.content}")
                    latencies.append(ms)
    return latencies


def parse_handler_latencies(messages: list[str], tool: str = TOOL) -> list[float]:
    """latency_ms of our own `tool_call_completed` structlog lines for `tool`."""
    latencies = []
    for message in messages:
        try:
            record = json.loads(message)
        except json.JSONDecodeError:
            continue
        if record.get("event") == "tool_call_completed" and record.get("tool") == tool:
            latencies.append(float(record["latency_ms"]))
    return latencies


def fetch_handler_latencies(logs: Any, runtime_id: str, since_ms: int) -> list[float]:
    """Best effort: our handler's own latency lines from the runtime's
    CloudWatch log groups. Returns [] if logs aren't readable."""
    messages: list[str] = []
    prefix = f"/aws/bedrock-agentcore/runtimes/{runtime_id}"
    for group in logs.describe_log_groups(logGroupNamePrefix=prefix).get("logGroups", []):
        kwargs: dict[str, Any] = {
            "logGroupName": group["logGroupName"],
            "startTime": since_ms,
            "filterPattern": '"tool_call_completed"',
        }
        while True:
            response = logs.filter_log_events(**kwargs)
            messages.extend(event["message"] for event in response.get("events", []))
            if not response.get("nextToken"):
                break
            kwargs["nextToken"] = response["nextToken"]
    return parse_handler_latencies(messages)


async def run(
    url: str,
    auth: httpx.Auth | None,
    cold: int,
    warm: int,
    handler_latencies: Callable[[], list[float]] | None = None,
) -> dict[str, Any]:
    host = urllib.parse.urlparse(url).hostname
    rtt = measure_tcp_rtt(host) if host not in ("localhost", "127.0.0.1") else [0.0]
    print(summarize("network RTT (TCP connect)", rtt))

    cold_init, cold_call = [], []
    for i in range(cold):
        init_ms, call_ms = await cold_sample(url, auth)
        cold_init.append(init_ms)
        cold_call.append(call_ms)
        print(f"  cold session {i + 1}: initialize {init_ms:.1f}ms, first {TOOL} {call_ms:.1f}ms")
    print(summarize("cold: initialize (new session)", cold_init))
    print(summarize(f"cold: first {TOOL} in new session", cold_call))

    warm_ms = await warm_samples(url, auth, warm) if warm else []
    print(summarize(f"warm: {TOOL} (same session)", warm_ms))

    result: dict[str, Any] = {"rtt": rtt, "cold_init": cold_init, "cold_call": cold_call, "warm": warm_ms}
    handler = handler_latencies() if handler_latencies else []
    if handler:
        print(summarize(f"server-side {TOOL} handler (from CloudWatch)", handler))
        if warm_ms:
            overhead = statistics.median(warm_ms) - statistics.median(rtt) - statistics.median(handler)
            result["runtime_overhead_p50"] = overhead
            print(
                f"=> client p50 - RTT - handler = {overhead:.1f}ms: AgentCore Runtime overhead PLUS "
                f"FixIt's own MCP request stack outside the handler (~17ms server-side, measured "
                f"locally with curl; see FRICTION_LOG.md step 4c)"
            )
    else:
        print("(server-side handler latencies unavailable -- overhead not split out)")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agent-arn", help="deployed runtime ARN (SigV4 auth implied)")
    parser.add_argument("--url", help="plain URL instead, e.g. http://localhost:8000/mcp (no auth)")
    parser.add_argument("--cold", type=int, default=5, help="number of brand-new sessions")
    parser.add_argument("--warm", type=int, default=30, help="calls in one warm session")
    args = parser.parse_args()
    if not (args.agent_arn or args.url):
        parser.error("pass --agent-arn or --url")

    smoke = _load_smoke()
    handler_latencies = None
    if args.agent_arn:
        import boto3

        url = smoke.runtime_invocation_url(args.agent_arn)
        region = args.agent_arn.split(":")[3]
        auth = smoke.SigV4Auth(region)
        runtime_id = args.agent_arn.rsplit("/", 1)[1]
        since_ms = int(time.time() * 1000)
        logs = boto3.client("logs", region_name=region)

        def handler_latencies() -> list[float]:
            time.sleep(10)  # CloudWatch ingestion lag
            try:
                return fetch_handler_latencies(logs, runtime_id, since_ms)
            except Exception as exc:  # noqa: BLE001 -- the client-side numbers still stand
                print(f"(could not read CloudWatch logs: {exc})")
                return []
    else:
        url, auth = args.url, None

    asyncio.run(run(url, auth, args.cold, args.warm, handler_latencies))
    return 0


if __name__ == "__main__":
    sys.exit(main())
