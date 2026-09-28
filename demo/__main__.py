"""Run the FixIt simulated-Alexa+ demo backend (see demo/README.md).

    uv run --group demo python -m demo                            # local dev FixIt server
    uv run --group demo python -m demo --agent-arn arn:aws:...     # deployed AgentCore Runtime

Or via `make demo` / `make demo AGENT_ARN=arn:aws:...`.
"""

from __future__ import annotations

import argparse

import uvicorn

from demo.app import create_app
from demo.config import DemoSettings
from demo.mcp_target import build_target


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--url", default=None, help="local FixIt MCP server URL")
    parser.add_argument("--agent-arn", default=None, help="deployed AgentCore Runtime ARN (SigV4-signed)")
    args = parser.parse_args()

    settings = DemoSettings()
    target = build_target(args.url, args.agent_arn)
    app = create_app(target, settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
