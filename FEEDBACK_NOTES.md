# Feedback notes

Per-tool/SDK notes from building the FixIt MCP server scaffold.

## `mcp` (official Model Context Protocol Python SDK)

- **Used for**: The entire server — `FastMCP` for the Streamable HTTP server,
  tool registration/schema generation, and the client SDK for integration tests.
- **What worked well**: `FastMCP` is genuinely fast to get a working server
  from — a decorated function with type hints becomes a fully schema'd tool
  (including structured output) with almost no boilerplate. Protocol version
  negotiation (`SUPPORTED_PROTOCOL_VERSIONS`, echoing the client's requested
  version) is exactly right out of the box and needed zero custom code.
  Stateless HTTP mode is well thought through: internally marking a stateless
  session pre-initialized means a client can call a tool without a full
  handshake round-trip, which is a nice fit for the "many short-lived calls"
  shape this project needs.
- **What needs work**: The PyPI default (`mcp` 2.x) is a breaking rewrite
  (`FastMCP` → `MCPServer`) that isn't flagged anywhere obvious before you hit
  the `ModuleNotFoundError` — see `FRICTION_LOG.md`. The reference
  `ClientSession` also can't be told to request an older `protocolVersion`,
  which made backward-compatibility testing require dropping to
  `send_request`/`send_notification` directly instead of `.initialize()`.
- **Onboarding experience**: Good once past the version confusion above —
  signatures are fully typed, and reading the source (`session.py`,
  `streamable_http_manager.py`) to understand stateless-mode semantics was
  straightforward and confirmed exactly what the docs implied.
- **Would build again**: Yes, pinned to 1.30.x for this project.

## `uv`

- **Used for**: Project scaffolding (`uv init --package`), dependency
  management, running scripts (`uv run`), and the local venv.
- **What worked well**: `uv init --package --python 3.12` produced the correct
  `src/` layout immediately; `uv add`/`uv add --dev` resolved and installed
  everything (including transitive deps) in well under a second per call.
- **What needs work**: Nothing hit in this step.
- **Onboarding experience**: Zero friction — a single binary, no separate
  Python install/venv dance needed.
- **Would build again**: Yes.

## `pydantic-settings`

- **Used for**: `Settings` (host/port/path/log level/response mode), loaded
  from `FIXIT_*` env vars or a `.env` file.
- **What worked well**: Exactly what was needed with almost no code —
  `SettingsConfigDict(env_prefix=..., env_file=...)` and a plain class body.
- **What needs work**: Nothing hit in this step (scope was small: five scalar
  fields).
- **Onboarding experience**: Trivial for anyone who already knows Pydantic.
- **Would build again**: Yes.

## `structlog`

- **Used for**: JSON structured logging, specifically per-tool-call latency
  logging (`tool_call_completed` / `tool_call_failed` events with
  `latency_ms`), which is how the <500ms Alexa+ budget gets monitored.
- **What worked well**: `structlog.configure(...)` with `JSONRenderer` gave
  clean, greppable JSON log lines immediately; wrapping a tool function in a
  small decorator to time and log it was simple.
- **What needs work**: Nothing hit in this step.
- **Onboarding experience**: Straightforward for anyone who's used stdlib
  `logging` before.
- **Would build again**: Yes.

## `ruff`

- **Used for**: Linting and formatting (`make lint`, `make format`).
- **What worked well**: Fast, single binary, sensible defaults; one
  `ruff format` call fixed the one formatting issue the suite had.
- **What needs work**: Nothing hit in this step.
- **Onboarding experience**: Trivial.
- **Would build again**: Yes.

## `pytest` / `pytest-asyncio`

- **Used for**: Unit tests (repository) and integration tests (real server
  over real Streamable HTTP, including a 50-call latency benchmark).
- **What worked well**: `asyncio_mode = "auto"` in `pyproject.toml` meant no
  per-test markers were needed; async fixtures (`pytest_asyncio.fixture`) made
  it easy to spin up and tear down a real uvicorn server per test.
- **What needs work**: Nothing hit in this step.
- **Onboarding experience**: Standard, no surprises.
- **Would build again**: Yes.
