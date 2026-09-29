"""Remove the throwaway demo households (`house-demo-*`) this demo created.

    uv run --group demo python -m demo.cleanup                          # local dev FixIt server
    uv run --group demo python -m demo.cleanup --agent-arn arn:aws:...  # deployed AgentCore Runtime

Or `make demo-cleanup` / `make demo-cleanup AGENT_ARN=arn:aws:...`. Reads the
ledger of household ids the demo wrote (a gitignored local file), removes
their appliances through the FixIt MCP server's remove_appliance tool, and
never touches any household that does not start with `house-demo-`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from demo.config import DemoSettings
from demo.households import HouseholdLedger, remove_households
from demo.mcp_target import build_target


async def run(url: str | None, agent_arn: str | None, ledger_path: Path) -> int:
    ledger = HouseholdLedger(ledger_path)
    ids = ledger.read()
    if not ids:
        print(f"No demo households recorded in {ledger_path}. Nothing to clean up.")
        return 0
    target = build_target(url, agent_arn)
    print(f"Cleaning {len(ids)} demo household(s) via {'the deployed runtime' if agent_arn else target.url}")
    async with (
        create_mcp_http_client(auth=target.auth) as http_client,
        streamable_http_client(target.url, http_client=http_client) as (read_stream, write_stream, _),
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            removed, remaining = await remove_households(session, ledger)
    print(f"Removed {removed} appliance(s); {len(remaining)} household(s) left in the ledger.")
    return 1 if remaining else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--url", default=None, help="local FixIt MCP server URL")
    parser.add_argument("--agent-arn", default=None, help="deployed AgentCore Runtime ARN (SigV4-signed)")
    args = parser.parse_args()
    ledger_path = Path(DemoSettings().households_file)
    sys.exit(asyncio.run(run(args.url, args.agent_arn, ledger_path)))


if __name__ == "__main__":
    main()
