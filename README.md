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

### Running in Docker (AgentCore Runtime image)

The `Dockerfile` builds the image Amazon Bedrock AgentCore Runtime will run:
`linux/arm64`, non-root (UID 1000), prod dependencies only, serving
`0.0.0.0:8000/mcp` in stateless mode, the same defaults as `make run`, so
nothing is overridden. It's about 76 MB compressed and about 235 MB unpacked
(boto3 is included for the `agentcore` backend).

```bash
# x86_64 hosts only, once per boot: register QEMU so arm64 images can build/run.
docker run --privileged --rm tonistiigi/binfmt --install arm64

make docker-build   # docker buildx build --platform linux/arm64 -t fixit-mcp:latest --load .
make docker-run     # serves http://localhost:8000/mcp; SQLite state in the `fixit-mcp-state` volume
make docker-smoke   # in another terminal: end-to-end MCP checks against the running container
```

`make docker-smoke` runs `scripts/smoke_test.py`, which covers both protocol
versions, every tool, the MCP Apps card, and a foreign `Mcp-Session-Id`
header. On an x86_64 host it skips the latency check, because QEMU emulation
makes each call about 10x slower than native. Set `DOCKER_PLATFORM=linux/amd64`
for a native local build if you need real latency numbers. The container
tests are opt-in: `FIXIT_DOCKER_TESTS=1 uv run pytest tests/integration/test_container.py`.

### Household data in AgentCore Memory (`agentcore` backend)

On AgentCore Runtime, local disk belongs to a single session, so household
appliances are stored in **Amazon Bedrock AgentCore Memory** instead
(`FIXIT_REPOSITORY_BACKEND=agentcore`). Each household is an actor, and each
appliance is one event under a fixed `appliance-registry` session. See
`src/fixit_mcp/repository/agentcore_memory.py` for the storage model, and
`FRICTION_LOG.md` (step 4b) for why events rather than long-term records.
**Events expire after at most 365 days.**

One-time setup (region `us-east-1`):

1. **Create the memory resource**: *Amazon Bedrock AgentCore → Memory →
   Create memory*. Name it `FixItHouseholds`, set event expiry to **365 days**
   (the maximum), and add **no strategies**, since this is short-term memory
   only and no LLM extraction should run. Wait for status **ACTIVE**, then
   copy the **memory ID** (e.g. `FixItHouseholds-a1B2c3D4e5`, not the ARN).
2. **Grant the identity that runs the server** (your local IAM user now, the
   AgentCore Runtime execution role later) exactly these three actions on
   that one memory:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Sid": "FixItHouseholdAppliances",
       "Effect": "Allow",
       "Action": ["bedrock-agentcore:CreateEvent", "bedrock-agentcore:ListEvents", "bedrock-agentcore:DeleteEvent"],
       "Resource": "arn:aws:bedrock-agentcore:us-east-1:<ACCOUNT_ID>:memory/<MEMORY_ID>"
     }]
   }
   ```

   Creating the memory (step 1) additionally needs
   `bedrock-agentcore:CreateMemory` / `GetMemory` / `ListMemories` for
   whoever does it. Those are one-time setup permissions that the server
   itself never needs. No VPC is needed: the data plane is a public
   regional endpoint.
3. **Seed the demo households and verify**:

   ```bash
   export FIXIT_AGENTCORE_MEMORY_ID=<MEMORY_ID>
   make seed-agentcore           # idempotent; RESET=1 clears demo-household rehearsal data first
   FIXIT_AGENTCORE_TESTS=1 uv run pytest tests/integration/test_agentcore_memory_live.py -v -s
   FIXIT_REPOSITORY_BACKEND=agentcore make run      # or: make docker-run-agentcore
   ```

The backend **never seeds at runtime**. A household with no events is
simply empty. `make seed-agentcore` is the only way the demo households
get into AgentCore Memory.

### Deploying to AgentCore Runtime

The **direct path** (no CDK and no AgentCore CLI; see `FRICTION_LOG.md`,
step 4c):
1. Push the already-tested local image to ECR, unchanged.
2. Create or update the runtime with `CreateAgentRuntime`, pinned to that
   image's **digest**.

The runtime runs with the `agentcore` backend and **IAM (SigV4) inbound
auth**. Alexa+ can't call it until OAuth/JWT is added.

> ## 🛑 Stop paying for it: `make teardown-runtime`
>
> This deletes the runtime, its endpoint, and every session, which stops
> **all** Runtime compute charges. It's safe to re-run.
> `make teardown-runtime-all` also deletes the `fixit-mcp` ECR repository
> and its images (~$0.01/month).
> Neither touches the AgentCore Memory resource (household data) or the
> IAM role and policies. Delete those in the console if you want them gone.

One-time IAM setup: `make iam-policies` renders `deploy/iam/*.json` with
your account's values into `build/iam/` (gitignored). The deployer policy must be a
**customer managed** policy, because it exceeds the 2,048-character limit for
inline user policies. `deploy/iam/README.md`
says which file attaches where.

```bash
export FIXIT_AGENTCORE_MEMORY_ID=<MEMORY_ID>
make docker-build        # if not already built and tested
make docker-push         # push that exact image (no rebuild) -> ECR fixit-mcp
make deploy-runtime      # create or update the runtime; prints its ARN (idempotent)
make runtime-smoke   RUNTIME_ARN=<arn>   # scripts/smoke_test.py, SigV4-signed
make runtime-latency RUNTIME_ARN=<arn>   # cold vs warm latency, with the Runtime overhead split out
```

> **State persistence caveat (default `sqlite` backend).** The SQLite household store lives at
> `/app/data/state/appliances.db` inside the container. Locally,
> `make docker-run` mounts a named volume there so data survives `docker rm`.
> **AgentCore Runtime has no such volume by default.** Every new session
> runs in a fresh microVM created from the image, so appliances added in one
> Alexa+ conversation are gone in the next. Deploy with the `agentcore`
> backend (below) instead, which keeps household data outside the container.

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
- `tests/integration/test_smoke_script.py` — keeps `scripts/smoke_test.py`
  (the container/deployment smoke checks) passing against the dev server.
- `tests/unit/test_dockerfile.py` — guards the Dockerfile's contract
  (startup data files copied in, editable install, non-root, port 8000).
- `tests/integration/test_container.py` — opt-in (`FIXIT_DOCKER_TESTS=1`):
  runs the real image and checks the smoke suite plus state persistence.
  Its two agentcore tests also need `FIXIT_AGENTCORE_TESTS=1`.
- `tests/unit/test_agentcore_memory_repository.py` — the `agentcore` backend
  against a fake AgentCore Memory client (no AWS).
- `tests/integration/test_agentcore_backend_server.py` — the full smoke suite
  over real Streamable HTTP on the `agentcore` backend, with only AWS faked.
- `tests/integration/test_agentcore_memory_live.py` — opt-in
  (`FIXIT_AGENTCORE_TESTS=1`): real AgentCore Memory, including measured
  per-operation and per-tool latency.

## AWS services used

- **Amazon Bedrock AgentCore Memory**: household appliance storage at
  runtime, when `FIXIT_REPOSITORY_BACKEND=agentcore`. Short-term events only,
  with no LLM extraction strategies.
- **Amazon Bedrock** (Claude): offline error-code extraction from manuals
  (`FIXIT_EXTRACTOR=bedrock`), never at request time.
- Planned: Amazon Bedrock AgentCore Runtime (hosting).

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
