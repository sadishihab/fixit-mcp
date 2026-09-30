# FixIt MCP

[![CI](https://github.com/sadishihab/fixit-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/sadishihab/fixit-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A self-hosted MCP server for diagnosing appliance problems, built for the
**Build, Ship, Shape: Amazon Developer Hackathon** (Alexa+ track).

## Overview

FixIt is a self-hosted MCP server (spec 2025-11-25, Streamable HTTP) for home
appliance help, built for the Alexa+ track of the **Build, Ship, Shape: Amazon
Developer Hackathon**. It works today: it diagnoses appliance error codes from
structured, cited data extracted offline from real manuals (extraction runs on
Amazon Bedrock at ingestion time, never inside the live tools); it keeps a
household's appliances across sessions in Amazon Bedrock AgentCore Memory; it
answers "is it still under warranty?" with a deterministic date comparison; it
returns an MCP Apps visual card for diagnoses; and it runs on Amazon Bedrock
AgentCore Runtime.

Not built: OAuth account linking. The deployed server accepts only AWS-signed
(IAM SigV4) requests today, so the real Alexa+ client can't call it yet — also
because the Alexa+ developer tools (account linking, the local inspector,
add-on submission) are not available to hackathon participants; see
`FRICTION_LOG.md`'s Alexa+ tooling access entry. Also not built: parts
ordering; maintenance scheduling. The demo client (`make demo`) is a simulated
Alexa+, not the real one, for the same reason.
See [`docs/alexa-plus-requirements.md`](docs/alexa-plus-requirements.md) for the
full requirements checklist and [`CLAUDE.md`](CLAUDE.md) for the architecture.

## Tools

| Tool | What it does |
|---|---|
| `list_my_appliances` | Lists a household's registered appliances. |
| `add_appliance` | Registers a new appliance for a household, linking it to a manual on file when one matches. |
| `remove_appliance` | Removes an appliance from a household's registry. |
| `diagnose_error` | Looks up an appliance error code's meaning, causes, repair steps, parts, and safety warnings, cited to the source manual; has an MCP Apps visual card. |
| `check_warranty` | Reports whether a registered appliance's recorded warranty is active or expired, from a deterministic server-side date comparison — never a coverage claim. |

## Project status

**Works today**
- The MCP server (spec 2025-11-25, also negotiates 2025-03-26) with five tools:
  appliance registry, error-code diagnosis from real manuals (with a visual
  card), and a recorded-date warranty check.
- Offline ingestion of manuals into a committed error-code index, and a
  one-command way to add a manual (`make add-manual`).
- A container image and a deployment to AgentCore Runtime with household data
  in AgentCore Memory. **The deployed server accepts only AWS-signed (IAM
  SigV4) requests today** — it has no anonymous or OAuth inbound auth.

**Simulated**
- The **Alexa+ client**. The demo (`make demo`) is a small local backend that
  plays Alexa+'s role: an MCP client driving an LLM tool-use loop. It is not
  the real client, because the Alexa+ developer tools (account linking, the
  local inspector, add-on submission) are not available to hackathon
  participants — see `FRICTION_LOG.md`'s Alexa+ tooling access entry.

**Roadmap**
- OAuth account linking, so real Alexa+ can reach the deployed server — if
  Alexa+ tooling becomes available.
- Parts ordering.
- Maintenance scheduling.
- More manuals (see [`CONTRIBUTING.md`](CONTRIBUTING.md) and
  [`docs/good-first-issues/`](docs/good-first-issues/)).

## Demo video

TODO: link once recorded.

## Architecture

```
Alexa+ (real client: not connected yet; the demo simulates it)
   |  Streamable HTTP, MCP 2025-11-25 (also negotiates 2025-03-26)
   v
FixIt MCP server  (AgentCore Runtime; `make run` locally)
   |-- error-code index: data/index/error_codes.json, loaded once at startup
   `-- household appliances: AgentCore Memory (`agentcore` backend), SQLite
       or in-memory for local dev

Offline, never in a request: manual PDFs -> parser -> Bedrock extraction ->
committed error-code index (`make add-manual`)
```

The runtime server is a thin, fast lookup layer with **no LLM calls in tool
handlers**: Alexa+ does all language generation from the structured data the
tools return. The heavy AI work (parsing and extracting manuals) happens
offline, in the ingestion pipeline.

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
  AgentCore Runtime's container contract (the image is deployed there today).
- **Latency**: no LLM calls in any tool handler; `tests/integration/test_latency.py`
  asserts p95 < 100ms locally over 50 calls. On the deployed AgentCore Runtime,
  the **measured** warm p50 was about 572 ms from Dhaka, of which about 320 ms is
  network to us-east-1. The in-region figure of roughly 200-250 ms is an
  **estimate**, not a measurement, so the 500ms Alexa+ budget is not yet
  confirmed from inside the region. **Cold sessions** (a brand-new session) take
  about 5 seconds and are a known limitation; see `FRICTION_LOG.md`'s
  "Cold-start latency: known limitation" entry.
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
> backend (above) instead, which keeps household data outside the container.

## Simulated Alexa+ demo

There's no real Alexa+ integration yet (see the OAuth row in
[`docs/alexa-plus-requirements.md`](docs/alexa-plus-requirements.md)). In
the meantime, [`demo/`](demo/README.md) is a local FastAPI backend that
plays Alexa+'s role -- a real MCP client driving a tool-use LLM loop
against this server, including the MCP Apps card -- so the tool-calling
behavior can be exercised and demoed. It has a small single-page web UI, and every
response is clearly labeled `"simulated_alexa_plus": true`.

```bash
make demo                                          # against the local dev server
make demo AGENT_ARN=<deployed runtime ARN>          # against a deployed AgentCore Runtime
```

## Add a manual

One command takes a manufacturer manual from a URL to validated, cited records in
`data/index/error_codes.json`:

```bash
make add-manual ID=acme-x100-oven BRAND=Acme MODEL=X100 TYPE=oven \
  URL=https://example.com/x100.pdf NOTE="Public support page, free download, no login"
make add-manual ... DRY_RUN=1   # verify the PDF and its content, change nothing
make validate-manifest          # check the manifest is consistent
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for what makes a good source and the
terms-of-use rule. A new manual only reaches the deployed server after an image
rebuild and runtime update.

## Data and sources

The error-code records in `data/index/error_codes.json` are factual, cited
extractions from manufacturers' publicly downloadable manuals: each record names
its manual and page. Every source is linked in
[`data/manuals/manifest.yaml`](data/manuals/manifest.yaml), with a note on where
the URL came from. The manual PDFs themselves are not stored in this repository,
and the records do not reproduce manual text.

All trademarks belong to their owners. This project is not affiliated with or
endorsed by any manufacturer. A manufacturer that wants its records removed can
ask, and the maintainer will remove them.

## How we measure grounding

The server never generates language; the assistant does, from the structured tool
results. To check that the assistant says only what those results say, `make eval`
runs about 60 scripted conversations (found and unknown codes, safety questions,
warranty questions, and adversarial follow-ups like "how much will the repair cost?")
through the demo against the local server. Each reply is checked deterministically
(right tool, right arguments, required or forbidden phrases) and by a second model
acting as judge, which lists any claim the tool results do not support. The judge
can be wrong, and it cannot catch a claim that merely sounds supported; see
[`CONTRIBUTING.md`](CONTRIBUTING.md#how-we-measure-grounding) for details and limits.

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
- `tests/integration/test_latency.py` — 50 tool calls per tool, asserts p95 < 100ms.
- `tests/unit/test_warranty_tool.py` / `tests/integration/test_check_warranty.py` —
  `check_warranty`'s date resolution (active/expired/unknown/ambiguous/not_found,
  the ends-today boundary, appliance_id precedence) and its real Streamable HTTP wiring.
- `tests/unit/test_add_manual.py` / `tests/unit/test_manifest_validation.py` —
  the add-a-manual script (duplicates, wrong-content PDFs, dry run, idempotent
  merge; synthetic PDFs, mocked HTTP) and the manifest validator, which also
  checks the real manifest.
- `tests/unit/test_run_eval.py` — the grounding eval runner (case loading, seeding
  and cleanup, deterministic checks, judge parsing and retry, cost, summary) with fakes.
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
- **Amazon Bedrock AgentCore Runtime**: hosts the server (IAM inbound auth only
  for now).

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
