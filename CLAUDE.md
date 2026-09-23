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
- `fixit_mcp.ingestion.parser` (`scripts/parse_manuals.py`, `make
  parse-manuals`) parses downloaded manual PDFs into section-aware
  `ManualChunk`s, written to `data/manuals/parsed/<manual_id>.json`
  (gitignored, derived data). Extraction is PyMuPDF-based; see
  `docs/pdf-extraction-library-choice.md` for why. Heading/table detection
  here is heuristic and best-effort by design — see `FRICTION_LOG.md` for the
  real failure modes hit (bold-at-body-size false headings, source-PDF font
  corruption) and how they were mitigated. This module is offline tooling
  only, never imported by the running server.
- `fixit_mcp.ingestion.text_repair` fixes two manuals' broken font encoding
  (a constant character-code offset per manual — +29 for
  `ge-gfe28gynfs-refrigerator.pdf`, +31 for `lg-dlex8000w-dryer.pdf` —
  confirmed empirically, never hardcoded as a shared value) before heading
  detection runs. It only repairs a run when a candidate offset clears hard
  gates (noise ratio, English letter-frequency, common-word evidence) *and*
  strictly beats leaving the run alone — a wrong "fix" on already-clean text
  is treated as worse than no fix. `repair_run()` returns a confidence so
  callers can flag uncertain repairs; it does not gate acceptance by itself.
  See `FRICTION_LOG.md` for the false-accept cases hit while tuning this
  (case-swap offsets, substring-match coincidences) and the known remaining
  limitation (a clean-prefix + corrupted-suffix run with no separating space
  is correctly left untouched rather than partially repaired).
  `infer_dominant_offset()`/`repair_line_tokens()` add a second, token-level
  pass for exactly that remaining case at the *sub-line* granularity: once a
  document's one true offset is established from many whole-line repairs
  (never guessed from a single short token), a short token with a strong
  corruption signal (a stray control character, or `&`/`'` next to a
  letter/digit — **not** `(`/`)`, which are too common next to ordinary
  numbers and caused real false positives, see `FRICTION_LOG.md`) is
  repaired on its own; a weaker one (a bare short number) is only repaired
  when it shares a line with a strong-signal sibling, so an ordinary
  quantity like "wait 5 minutes" is never touched. Still can't fix a
  corruption boundary that falls *inside* a single whitespace-delimited
  token (no space to split on) — the GE fridge's `AUTO FILL<corrupted
  tail>` case remains a known limitation for that reason.

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

Manual PDFs are now fetched (`fixit_mcp.repository`, step 2a) and parsed into
chunks (`fixit_mcp.ingestion.parser`, step 2b), but nothing downstream of
that yet: no embeddings, no retrieval/RAG, no error-code extraction tool, no
Bedrock/Strands, no AWS deployment, no auth/account linking, no MCP Apps UI,
no web client. See `docs/alexa-plus-requirements.md` for the full
done/todo/not-needed checklist against the Alexa+ MCP Toolkit requirements.
