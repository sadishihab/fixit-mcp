# FixIt MCP server

## What this is

FixIt is a self-hosted MCP server built for the "Build, Ship, Shape: Amazon
Developer Hackathon" (Alexa+ track). It connects to Alexa+ via the official
Alexa+ MCP Toolkit and helps customers with home appliances:

- Diagnose appliance error codes from knowledge extracted from real appliance manuals.
- Remember which appliances a household owns.
- Guide repairs with visual cards (MCP Apps).
- Order replacement parts.
- Schedule maintenance.

## Architecture goals (full project, most not built yet)

- **Runtime**: this MCP server, built on the official Python SDK (`mcp` package),
  Streamable HTTP transport, deployed to **Amazon Bedrock AgentCore Runtime**.
- **Client**: **Alexa+**, connected via the official **Alexa+ MCP Toolkit**.
- **Offline ingestion pipeline** (separate from the runtime, not built yet): parses
  appliance manuals and builds a searchable knowledge base using **Amazon Bedrock**
  and **Strands** for the heavy AI work (extraction, chunking, embeddings). This is
  where RAG lives.
- **Visual repair guidance**: MCP Apps extension, rendered by the Alexa+ client.

## Hard requirements (do not violate)

1. **MCP spec 2025-11-25 over Streamable HTTP.** Both the hackathon rules and the
   Alexa+ MCP Toolkit require this.
2. **Negotiate correctly with older clients.** The Alexa+ docs show its client
   sending `protocolVersion: "2025-03-26"` on `initialize`. The server must still
   negotiate and serve that client. Pin `mcp>=1.30,<2` — `mcp` 2.x renamed
   `FastMCP` to `MCPServer` and changed the API; 1.30.0 is the last 1.x release
   and its `SUPPORTED_PROTOCOL_VERSIONS` list includes both `2025-11-25` and
   `2025-03-26`, and it's what AWS's own AgentCore docs sample against.
3. **No LLM calls inside tool handlers, ever.** Tools are fast, pre-indexed
   lookups. Alexa+ does all language generation from the structured data tools
   return. Heavy AI work (manual parsing, embeddings, retrieval index building)
   happens **offline, at ingestion time**, in a separate pipeline — never inside
   a request/response tool call.
4. **Every tool call must complete well under 500ms round-trip** (Alexa+
   requirement). This is only achievable if rule 3 is followed — an LLM call
   inside a tool would blow this budget immediately.
5. **Stateless HTTP mode** (`stateless_http=True`) for AgentCore Runtime
   compatibility — it manages its own session routing via `Mcp-Session-Id` and
   expects the server not to reject its platform-generated session IDs.
6. **AgentCore Runtime container contract** (for future deployment): serve at
   `0.0.0.0:8000/mcp`, ARM64 container.

## Coding conventions

- Python 3.12, `src/` layout, package `fixit_mcp`, dependency management via `uv`.
- Storage is accessed through repository interfaces (e.g.
  `fixit_mcp.repository.base.ApplianceRepository`), never directly, so in-memory
  seed stores can be swapped for real databases later without touching callers.
- Config via `pydantic-settings` (`fixit_mcp.config.Settings`), env-prefixed
  `FIXIT_*`.
- Structured (JSON) logging via `structlog`; every tool call logs its latency in
  milliseconds — this is how the 500ms budget gets monitored, not guessed at.
- Tool descriptions are written for an LLM client (Alexa+) to read, not for
  humans skimming API docs: state plainly when to call the tool and what it needs.
- Ruff for linting and formatting (`make lint`, `make format`).
- Real appliance manuals are tracked as metadata only, in
  `data/manuals/manifest.yaml` (id, brand, model, appliance_type, source_url,
  source_note). The actual PDFs are downloaded on demand by
  `scripts/fetch_manuals.py` (`make fetch-manuals`) into `data/manuals/pdf/`,
  which is gitignored — **never commit manual PDFs**, only the manifest.
  Seeded `Appliance` records (`fixit_mcp.repository.in_memory`) link to a
  manifest entry via `manual_id`; brand+model must match the manifest entry
  they reference.

## Testing

**Every change needs tests.** No exceptions for "small" changes.

- Unit tests for repositories and domain logic.
- Integration tests spin up the real server (uvicorn + `FastMCP.streamable_http_app()`)
  on a local port and drive it with the official MCP client — no mocking the
  MCP protocol layer itself.
- Any change touching protocol negotiation must keep both the `2025-11-25` and
  the legacy `2025-03-26` integration tests passing.
- Any change to tool handlers must keep the latency test's p95 budget passing.
- Run `make test` before considering work done; `make lint` and `make format`
  should be clean too.

## What's explicitly out of scope for the current milestone

RAG/ingestion pipeline, auth/account linking, AWS deployment, MCP Apps UI, and
any web client. See `docs/alexa-plus-requirements.md` for the full
done/todo/not-needed checklist against the Alexa+ MCP Toolkit requirements.
