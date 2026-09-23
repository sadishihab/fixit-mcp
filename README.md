# FixIt MCP

A self-hosted MCP server for diagnosing appliance problems, built for the
**Build, Ship, Shape: Amazon Developer Hackathon** (Alexa+ track).

## Overview

FixIt connects to Alexa+ via the official Alexa+ MCP Toolkit and helps
customers with home appliances: diagnosing error codes from real appliance
manuals, remembering which appliances a household owns, guiding repairs with
visual cards, ordering replacement parts, and scheduling maintenance.

This repository is currently at the **scaffolding milestone**: a minimal,
tested MCP server running locally with one tool. RAG/ingestion, auth, AWS
deployment, MCP Apps UI, and a web client are not built yet — see
[`docs/alexa-plus-requirements.md`](docs/alexa-plus-requirements.md) for the
full requirements checklist and [`CLAUDE.md`](CLAUDE.md) for the target
architecture.

## Demo video

TODO: link once recorded.

## Architecture

```
Alexa+  <-- Streamable HTTP, MCP 2025-11-25 -->  FixIt MCP server (this repo)
                                                        |
                                          in-memory repository (today)
                                          -> swappable for a real DB later
```

Planned (not built yet): an offline ingestion pipeline using Amazon Bedrock +
Strands parses appliance manuals into a searchable knowledge base; the runtime
server (this repo) stays a thin, fast lookup layer with **no LLM calls in tool
handlers** — Alexa+ does all language generation. The runtime is intended to
deploy to Amazon Bedrock AgentCore Runtime.

## How this meets the Alexa+ track requirements

- **MCP SDK import and server entry point**: `src/fixit_mcp/server.py` imports
  `from mcp.server.fastmcp import FastMCP` and defines `create_server()` /
  `main()`. `src/fixit_mcp/tools/appliances.py` also imports `FastMCP` (for
  type hints) and registers the tool via `@mcp.tool(...)`.
  `src/fixit_mcp/__main__.py` is the process entry point (`python -m fixit_mcp`).
- **Protocol version**: pinned to `mcp>=1.30,<2`, whose `LATEST_PROTOCOL_VERSION`
  is `2025-11-25` and which correctly negotiates the `2025-03-26` version the
  Alexa+ client sends (verified in `tests/integration/`).
- **Transport**: Streamable HTTP, stateless mode, served at `0.0.0.0:8000/mcp`
  — matching both the Alexa+ Toolkit's requirements and Amazon Bedrock
  AgentCore Runtime's container contract for a future deployment.
- **Latency**: no LLM calls in any tool handler; `tests/integration/test_latency.py`
  asserts p95 < 100ms locally over 50 calls (well under the 500ms Alexa+ budget).
- Full requirement-by-requirement checklist: [`docs/alexa-plus-requirements.md`](docs/alexa-plus-requirements.md).

## Quickstart

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.12.

```bash
git clone <this-repo>
cd fixit-mcp
uv sync
cp .env.example .env   # optional, defaults work as-is
make run                # starts the server on http://0.0.0.0:8000/mcp
```

### Inspecting the server

```bash
make inspector
```

This starts the [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
(requires Node.js/npm). In the browser UI it opens, choose transport
**"Streamable HTTP"** and connect to `http://localhost:8000/mcp`.

### Exposing it remotely (for testing with Alexa+)

Alexa+ requires a remote HTTPS URL. For local development/demos, use a
[cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
quick tunnel:

```bash
# Install cloudflared first, e.g.:
#   macOS:   brew install cloudflared
#   Linux:   see https://pkg.cloudflare.com/index.html
make tunnel
```

This prints a temporary `https://*.trycloudflare.com` URL that proxies to
your local server.

## Running tests

```bash
make test    # pytest: unit + integration (spins up a real local server)
make lint    # ruff check
make format  # ruff format
```

Test suite:
- `tests/unit/test_repository.py` — in-memory repository behavior.
- `tests/integration/test_server_protocol.py` — negotiates MCP `2025-11-25` and
  calls `list_my_appliances` over real Streamable HTTP.
- `tests/integration/test_server_legacy_protocol.py` — negotiates the
  `2025-03-26` protocol version the Alexa+ client sends and confirms tool
  calls still work.
- `tests/integration/test_latency.py` — 50 tool calls, asserts p95 < 100ms.

## AWS services used

None yet at runtime — this milestone runs entirely locally. Planned: Amazon
Bedrock AgentCore Runtime (hosting), Amazon Bedrock + Strands (offline
ingestion pipeline for manual parsing / RAG).

## Open-source components

- [`mcp`](https://pypi.org/project/mcp/) (1.30.x) — official Model Context
  Protocol Python SDK.
- [`pydantic`](https://docs.pydantic.dev/) / [`pydantic-settings`](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — data models and config.
- [`structlog`](https://www.structlog.org/) — structured logging.
- [`uvicorn`](https://www.uvicorn.org/) — ASGI server (used internally by the MCP SDK's Streamable HTTP transport).
- [`pytest`](https://docs.pytest.org/) / [`pytest-asyncio`](https://pytest-asyncio.readthedocs.io/) — testing.
- [`ruff`](https://docs.astral.sh/ruff/) — linting and formatting.
- [MCP Inspector](https://github.com/modelcontextprotocol/inspector) — manual protocol testing tool.
- [`cloudflared`](https://github.com/cloudflare/cloudflared) — local HTTPS tunneling for demos.

## License

MIT — see [`LICENSE`](LICENSE).
