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
  `fixit_mcp.repository.base.ApplianceRepository`), never directly, so the
  backend can be swapped without touching callers -- see the persistence
  bullet below for the three implementations that currently exist.
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
  `apply_token_level_repair()` (parser.py) further restricts the weak-signal
  path to sections that `looks_like_table` — same-line company from a
  strong-signal sibling turned out too wide a scope once a real document
  mixed genuinely-corrupted narrative text with uncorrupted data-table
  numbers (GE's EPA water-quality table: a corrupted chemical name next to a
  real, uncorrupted concentration value), see `FRICTION_LOG.md`. Every
  token-level repair under 0.6 confidence is also recorded on its
  `ManualChunk.uncertain_repairs` (original + repaired + confidence) so a
  downstream consumer isn't forced to trust a low-confidence repair blindly.
- `fixit_mcp.ingestion.extraction` (`scripts/extract_codes.py`, `make
  extract-codes`) turns `data/manuals/parsed/*.json` chunks into structured
  `ErrorCodeRecord`s, written to `data/index/error_codes.json` (**committed**
  -- this is the artifact a future MCP tool will load, unlike everything
  else under `data/`). Two extractors share one interface, selected via
  `FIXIT_EXTRACTOR=stub|bedrock`: `StubExtractor` is a deterministic,
  no-network regex matcher (used by tests and by anyone without AWS) that
  only ever fills in `error_code`/`code_normalized` -- it never guesses at
  meaning/causes/steps/parts/warnings, since a fixed regex has no honest
  basis to; `BedrockExtractor` calls Amazon Bedrock (Claude) via boto3 with a
  strict JSON schema, validates with pydantic, retries a bounded number of
  times on malformed output, and returns `[]` rather than ever guessing when
  a chunk has no real codes or every retry still fails. Both are still
  offline ingestion tooling only -- extraction never runs inside a tool
  handler (rule 3 above). The extraction prompt is told about a chunk's
  `uncertain_repairs` explicitly and instructed to distrust a repaired token
  that doesn't make sense as part of a code. Per-chunk extraction is cached
  by content hash (`data/index/.extract_cache/`, gitignored) so re-runs cost
  nothing once a chunk hasn't changed.
- `ErrorCodeRecord` and `normalize_code` live in `fixit_mcp.domain.models`
  (the neutral layer), not in `fixit_mcp.ingestion.extraction` where they
  were first written in step 3a — `fixit_mcp.retrieval.codes` (below) needs
  the same schema at server startup, and the running server must never
  import from `ingestion`. `extraction.py` re-exports both via `__all__` so
  existing call sites are unaffected. See `FRICTION_LOG.md` for why this
  moved.
- `fixit_mcp.retrieval.codes` loads `data/index/error_codes.json` into memory
  **once**, at server startup (`load_index()`, called from `create_server()`)
  — no file I/O or network in the request path, per rule 3/4. It also fixes
  two gaps left open in step 3a's committed index, entirely at load time
  (never by editing the committed JSON, so re-extraction stays idempotent):
  (1) deduplicates by `(manual_id, code_normalized)`, preferring the record
  with more populated content fields, then higher `extraction_confidence`
  (see `FRICTION_LOG.md`'s Bosch `E:34-00` chunk-boundary entry, step 3a);
  (2) routes records whose `error_code` is a manual's own range/placeholder
  description (e.g. `"E:01-00 to E:90-10"`, `"F— and a number or letter"` —
  see `FRICTION_LOG.md`, step 3a) into a separate `family_by_manual` view
  (`is_lookupable()`: normalized length or an English placeholder word in
  the original text) instead of `lookupable_by_code`, so they can never be
  returned as if they were a match for the specific code queried.
- `fixit_mcp.tools.diagnose` registers the `diagnose_error` tool. Resolution
  order: normalize the query code → exact match against
  `ErrorCodeIndex.by_code()` → if `household_id` is given, narrow to the
  household's owned appliances whose manual actually has that code (exactly
  one → `found`; several → structured `ambiguous_appliance`, never guess;
  none → fall back to brand/model filtering of the raw candidates) → no
  match at all → structured `not_found` with `nearest_codes()`
  (`difflib`-based, no LLM) and, if exactly one household appliance was
  resolved, that manual's `family_note` if it has a range/placeholder entry.
  A single response model (`status: Literal["found","ambiguous_appliance","not_found"]`)
  is used instead of a `Union`, for simpler structured-output schema
  generation. Never fabricates: an empty index field (e.g. LG's PS/PF/nP
  codes, which the manual never explains) stays empty in the response rather
  than being filled in. If `household_id` is given but resolves to no owned
  appliance at all, the not_found response also sets
  `suggest_add_appliance: true` rather than dead-ending -- the household may
  simply not have registered that appliance yet (`add_appliance`, below).
- **Household appliance persistence** (step 3c). `Appliance.purchase_date`/
  `warranty_end_date` are optional, and `manual_id` defaults to `""` (no
  manual on file yet), since a customer adding an appliance rarely knows all
  of this upfront. Three `ApplianceRepository` implementations:
  `InMemoryApplianceRepository` (`fixit_mcp.repository.in_memory`, plain
  dict, used by unit tests and available as the `FIXIT_REPOSITORY_BACKEND=memory`
  runtime option) and `SqliteApplianceRepository`
  (`fixit_mcp.repository.sqlite`, the default runtime backend), plus
  `AgentCoreMemoryApplianceRepository` (step 4b, see its own bullet
  below). SQLite (via
  stdlib `sqlite3`, no new dependency) was chosen over a flat JSON file
  because each add/remove is one atomic transactional statement -- a crash
  mid-write can't corrupt a whole household's data the way rewriting an
  entire JSON file can -- and per-household lookups use a real index instead
  of parsing the whole store on every call. **This is the dev/demo
  persistence layer only**: on AgentCore Runtime local disk is per-session,
  so production uses the `agentcore` backend (AgentCore Memory) instead. `Settings.repository_backend`
  (`FIXIT_REPOSITORY_BACKEND`, default `"sqlite"`) and `Settings.sqlite_path`
  (`FIXIT_SQLITE_PATH`, default `data/state/appliances.db`, gitignored)
  select and locate it. A fresh/empty store is seeded from the same default
  household data `InMemoryApplianceRepository` uses
  (`fixit_mcp.repository.in_memory.DEFAULT_SEED`), so the demo works out of
  the box on a clean checkout; a store that already has data is never
  reseeded. `fixit_mcp.catalog.manifest` loads
  `data/manuals/manifest.yaml` once at startup (same no-file-I/O-per-request
  rule as the error-code index) so `add_appliance` can link a newly-added
  appliance to its manual by brand+model, matched case-insensitively.
  `add_appliance`/`remove_appliance` (`fixit_mcp.tools.appliances`) are the
  corresponding tools; adding an appliance with no matching manual still
  saves it, but the response says diagnosis coverage will be limited rather
  than silently pretending it's fully supported.
- **MCP Apps visual card** (step 3d, `fixit_mcp.apps`). `diagnose_error`
  declares a companion `ui://fixit-mcp/diagnose-error-card` resource per the
  current MCP Apps spec (`modelcontextprotocol/ext-apps`,
  `specification/2026-01-26/apps.mdx`): `_meta.ui.resourceUri` is set on the
  **tool definition** (`@mcp.tool(..., meta={"ui": {"resourceUri": ...}})`),
  static and shared by every call -- the spec has no per-call UI metadata on
  a tool *result* at all, only on the tool itself. The resource
  (`fixit_mcp.apps.diagnose_card.html`, loaded once at import time, never
  read from disk per request) is a single self-contained HTML5 document,
  MIME type `text/html;profile=mcp-app`, with a small inline `<script>` that
  (a) implements the spec's postMessage handshake (`ui/initialize`, then
  listens for the host's `ui/notifications/tool-result`) -- no network
  fetching anywhere in it, all data arrives pushed from the host -- and (b)
  a pure, DOM-free `buildCardHtml(result)` function that dispatches on
  `result.status` to one of three distinct renderings: `found` shows the
  error code, appliance, meaning, numbered repair steps, a visually distinct
  (amber) safety-warnings block, and citation; `not_found` shows the queried
  code, a short fixed message, and `nearest_matches` as a plain list;
  `ambiguous_appliance` shows `candidate_appliances` as a plain list with the
  backend's own message. `not_found`/`ambiguous_appliance` are deliberately
  styled muted grey (`.state-card`, dashed border) rather than red/amber, so
  they read as "a different, non-diagnosis state," not an error -- and
  deliberately have **no click handlers**: the spec's View->Host message set
  does include `tools/call` (a view can invoke a tool through the host,
  subject to host-discretionary approval), confirmed by checking the spec
  rather than assuming, but building on that was scoped out for now -- no
  host's approval UX for it has been verified here, and it'd be a
  first-of-its-kind interactive pattern in this server. Any other `status`
  (including no result yet) returns `""` and the template's `render()` falls
  back to a plain "waiting" placeholder. The plain `content`/
  `structuredContent` the tool already returned is completely unmodified by
  any of this -- the card is a fully separate, additive discovery path.
  `buildCardHtml` is unit-tested by actually running it in Node (it's
  pure/DOM-free by design, so no jsdom or browser needed), skipped rather
  than failed if `node` isn't on PATH. See `FRICTION_LOG.md` for why a
  literal "per-call resourceUri, fully pre-rendered server-side, zero
  client-side JS" reading of the original request isn't what any current
  MCP Apps host looks for, and for the `tools/call` support finding above.
- **Container image** (step 4a, `Dockerfile`, `make docker-build`/`docker-run`/
  `docker-smoke`). linux/arm64, two-stage uv build, non-root UID 1000, prod
  deps only. It serves the unmodified `Settings` defaults (`0.0.0.0:8000/mcp`,
  stateless), which already match AgentCore's MCP container contract, so the
  Dockerfile must never override host/port/path. The project install is
  deliberately **editable** with `src/` copied next to `.venv`, because data
  paths are resolved via `Path(__file__).parents[N]` and a non-editable install
  would break them (`load_manual_catalog()` would silently go empty). Any new
  data file loaded at startup must be added to the Dockerfile's COPY lines
  (`tests/unit/test_dockerfile.py` enforces this for the current ones).
  `scripts/smoke_test.py` is the end-to-end check for any running server URL
  (container now, AgentCore in step 4b). Use `--skip-latency` under QEMU
  emulation, because the latency it reports there is QEMU's, not the server's
  (see `FRICTION_LOG.md`). On AgentCore every session is a fresh microVM,
  so the SQLite store is neither durable nor shared across conversations
  (step 4a finding). That's why the deployed image must run the `agentcore`
  backend, below.
- **AgentCore Memory household store** (step 4b,
  `fixit_mcp.repository.agentcore_memory`, `FIXIT_REPOSITORY_BACKEND=agentcore`).
  Uses AgentCore Memory **short-term events** as a keyed record store:
  actorId = household_id, one fixed registry sessionId
  (`FIXIT_AGENTCORE_REGISTRY_SESSION_ID`), one event per appliance with a
  `json` payload (`schema: fixit.appliance.v1`), and `extractionMode="SKIP"`
  so nothing ever reaches LLM-driven long-term extraction. Long-term memory
  records were rejected: they're built for semantic retrieval, use prefix
  namespace matching, and have a 30 TPS account-wide list quota. The
  accepted cost is that **events expire after at most 365 days** (the
  memory's `eventExpiryDuration`). list/add are one AgentCore call each;
  remove is two (ListEvents + DeleteEvent). Every call's latency is logged
  as `agentcore_memory_call`. The boto3 client has tight timeouts (1s
  connect, 2s read, at most 2 attempts), and the repository does one warm-up
  read at startup. AWS errors propagate as tool errors, never as an empty
  list. `clientToken` is a fresh uuid per `add()` call, never derived from
  appliance_id, because AWS silently ignores a repeated token, which would
  swallow a legitimate re-add. **Never seeds at runtime**: the demo
  households go in via `scripts/seed_agentcore_memory.py` (`make
  seed-agentcore`, idempotent by appliance_id, `RESET=1` clears only demo
  households). See `FRICTION_LOG.md` (step 4b) for the reasoning. boto3 is a
  runtime dependency as of this step. Unit tests use
  `tests/fakes.FakeAgentCoreMemoryClient`. Live tests
  (`tests/integration/test_agentcore_memory_live.py`) are opt-in via
  `FIXIT_AGENTCORE_TESTS=1` + `FIXIT_AGENTCORE_MEMORY_ID`.

- **AgentCore Runtime deployment** (step 4c): the **direct path**, not the
  AgentCore CLI (it always rebuilds container agents in CodeBuild and needs
  an admin CDK bootstrap; see `FRICTION_LOG.md`). `scripts/push_image.py`
  (`make docker-push`) pushes the already-tested local image unchanged and
  reports source drift. `scripts/deploy_runtime.py` (`make deploy-runtime`)
  idempotently creates or updates runtime `fixit_mcp`, **pinned to the
  image digest**, with MCP protocol, PUBLIC network, **IAM SigV4 inbound
  auth** (no authorizer; OAuth/JWT is a later step, so Alexa+ can't call
  it yet), and the `agentcore` backend env vars. `make teardown-runtime`
  stops all Runtime charges. IAM: `deploy/iam/*.json` templates
  (placeholders only, never an account id), rendered by `make iam-policies`
  into gitignored `build/iam/`. The deployer policy is a customer managed
  policy (too big for a user inline policy), and it includes the implicit
  `CreateAgentRuntimeEndpoint`/`CreateWorkloadIdentity` actions that
  `CreateAgentRuntime` fans out into. `scripts/smoke_test.py --agent-arn`
  SigV4-signs every request. `scripts/measure_runtime_latency.py` splits
  latency into RTT, Runtime overhead, and handler time (from CloudWatch).
  Measured: warm Runtime overhead ~125–155ms p50. Cold new sessions (1.3–8s
  initialize, ~2s first call) are the open latency risk.

- **Observability** (step 23c, `scripts/observability.py`, `make observability`/
  `observability-teardown`, `DRY_RUN=1` makes no AWS call). Four metric filters
  on the runtime log group turn our own `tool_call_completed`/`tool_call_failed`/
  `agentcore_memory_call_failed` JSON lines into namespace `FixIt` metrics
  (`ToolLatency` per `Tool`, `ToolLatencyAll`, `ToolCallFailed`, `MemoryCallFailed`);
  90-day log retention; dashboard `FixIt`; alarms `fixit-errors` and
  `fixit-tool-latency` (handler p95 > 300 ms, 2 of 3) emailing SNS topic
  `fixit-alerts` (address from `FIXIT_ALERT_EMAIL`, never committed). Every
  name starts with fixit/FixIt, matching the `FixItObservability` customer
  managed policy (`deploy/iam/observability-policy.json`). AgentCore metric
  dimensions (`Resource`, `Operation=InvokeAgentRuntime`, `Name=fixit_mcp::DEFAULT`
  for the runtime; `Resource`, `Operation` for Memory) come from a real
  list-metrics, never guessed; ids are resolved at run time, never written to
  a file. Idempotent: read, compare, write only on drift. Renaming a log event
  breaks its filter; `tests/unit/test_observability.py` checks every filter's
  event name is still logged by `src/`. Known gap: a front-door 504 that never
  reaches the container is invisible to it (`FRICTION_LOG.md`, step 23c).

- **`check_warranty` tool** (step 8a, `fixit_mcp.tools.warranty`). Answers
  "is it still under warranty?" from a deterministic server-side date
  comparison only -- the comparison itself always happens in code, never
  left to Alexa+'s model (rule 3). Resolution: `appliance_id` wins outright
  (no other filter narrows or excludes on top of it); otherwise the
  household's appliances are filtered by whichever of `appliance_type`
  (e.g. "dryer"), `brand`, `model` were given, so "is my dryer still under
  warranty" can resolve without an id. Exactly one match -> a dated result;
  several -> `ambiguous_appliance` with candidates, never guessed; none ->
  `not_found`. A single response model
  (`status: Literal["active","expired","unknown","ambiguous_appliance","not_found"]`)
  is used, same reasoning as `diagnose_error`'s single-model-over-`Union`
  choice. `status="unknown"` when the appliance has no `warranty_end_date`
  on file -- never guessed. The boundary decision: a `warranty_end_date`
  equal to today still counts as `active` (`days_remaining=0`) -- the
  recorded end date is the *last* day of coverage, not the first day of
  expiry; pinned by a dedicated boundary test. One clock source only: the
  pure `check_warranty()` function takes `as_of: date` as a required,
  caller-supplied argument (tests pass a fixed date), and only the
  `@mcp.tool` wrapper's `_utc_today()` ever reads the real clock, via
  `datetime.now(UTC)`. The response's `message` field states only the
  recorded date fact ("The recorded warranty ended on 2025-01-15, 620 days
  ago") and always says "recorded" -- since the dates come from what the
  customer registered, not a manufacturer lookup -- and never makes a
  coverage claim or names what a repair would cost; the demo backend's
  system prompt (`demo/orchestrator.py`) carries the same restriction
  forward into the model's own reply, the same class of leak
  `FRICTION_LOG.md`'s step 6b/6e entries caught for other tools.

- **Symptom card** (step 27a, `fixit_mcp.apps`). `diagnose_symptom` declares
  `ui://fixit-mcp/diagnose-symptom-card` exactly as `diagnose_error` declares
  its card (`meta={"ui": {"resourceUri": ...}}` on the tool definition, the
  resource registered in `register_symptom_tool`, `text/html;profile=mcp-app`,
  the same postMessage handshake, no click handlers, no network, every field
  escaped). `found` shows the matched symptom phrases as the title, then each
  row's possible causes and the third column under the row's own
  `response_label` ("What To Do" or "Reason"), muted footnotes, a muted
  "incomplete in the manual" marker for `text_incomplete` rows, and a citation
  line per match, up to 3 matches as separate blocks; `appliance_registered:
  false` is the same muted notice as the error card's; `not_found` is a muted
  state with the customer's words and the manual's `nearest_phrases`;
  `ambiguous_appliance` is muted with the candidates. The assistant-facing
  `message` of a `not_found` is never shown. **Shared parts**: the CSS head and
  tail, the `esc`/`listHtml` helpers and the handshake live once in
  `card_shared_head.css`, `card_shared_tail.css`, `card_shared.js` and
  `card_handshake.js`, and `fixit_mcp.apps.resources.assemble_card` fills them
  into each card's template (`diagnose_card.html`, `symptom_card.html`) at
  import time. `diagnose_error`'s served card is **byte-for-byte unchanged** by
  that move (`tests/unit/test_diagnose_card.py` pins its sha256). The only
  duplication is ~15 lines of `.appliance`/`h3`/`ul`/`li` rules, which sit
  between that card's own rules and so cannot join the shared runs without
  changing its bytes. The demo host needed no per-tool change (it reads each
  tool's own `resourceUri` and keys on result status); only its iframe height cap
  rose from 900 to 2400 px, since three matches are much taller.

- **Symptom tool** (step 25b). `diagnose_symptom` answers a problem the
  customer describes with no error code, from the manuals' "Problem / Possible
  Causes / What To Do" tables. Two halves, like the error-code path.
  *Offline* (`fixit_mcp.ingestion.symptom_tables`/`symptom_extraction`,
  `scripts/extract_symptoms.py`, `make extract-symptoms`, `DRY_RUN=1` calls
  nothing): rows come from PyMuPDF `find_tables()` geometry (the parser reads a
  3-column table as 2 columns and loses row alignment, `FRICTION_LOG.md` steps
  25a/25b), cell text from span-level extraction clipped to each cell, the GE
  fridge's corrupted spans repaired per span with the offset the parser already
  established (never searched; a span is corrupted iff it holds a C0 control
  character), line wraps after a real hyphen or en dash joined without a space,
  and `REVIEWED_TEXT_FIXES` (in the script, checked against the rendered page)
  for the one lone corrupted character no rule can see. **Nova only, never
  Claude** (`assert_nova_model` refuses anything else; the IAM user denies
  Claude and it is Marketplace-billed): Nova Pro, the v2 prompt, a hard
  `--max-cost` cap (default $1.00) with an estimate printed per manual and a
  `yes` prompt (`--yes` skips). Nothing the model returns is trusted until
  `audit_rows` passes: expected row count from the geometry, each row's strings
  joined must equal the source cell (whitespace collapsed, nothing else, so a
  curly quote or a dropped line fails), footnote links derived from the markers
  in the row's own text, empty or short or unparseable answers retried up to 3
  times with the problems named. A manual's rows are written to the committed
  `data/index/symptoms.json` only if every one of its tables passed; other
  manuals' rows are left alone. Accepted answers are cached in
  `data/index/.extract_cache/symptoms/` keyed by model, prompt and table text
  and **re-audited on every read**. The default manuals are the GE refrigerator
  (42 rows) and washer (72 rows, incl. the "Sounds" table, whose third column is
  headed "Reason", an explanation not an instruction); the GE range's table is
  unruled and needs its own reader. `SymptomRecord` (neutral layer) has no
  meaning/difficulty/parts/safety field and no model confidence: grounding is
  verified, not self-reported. Rows that end mid-sentence (a brand logo in the
  PDF is an image) carry `text_incomplete`. *Runtime*
  (`fixit_mcp.retrieval.symptoms`, `fixit_mcp.tools.symptoms`): the index loads
  once at startup (a missing file fails startup, like the error-code index;
  `Dockerfile` COPYs it, `tests/unit/test_dockerfile.py` enforces that).
  Matching is deterministic keyword overlap, no model call (step 25b, widened
  in step 27c): stopwords, light stemming, a reviewed synonym and multi-word
  phrase table (every target must be a word the stored rows use; a test checks
  it), a "does not happen" polarity that must agree between the description and
  the symptom ("won't spin" never reaches "pauses during spin"), spelling
  tolerance for one-character slips on words of 5+ letters only when exactly
  one known word is one edit away, IDF weights, score >= 0.5, and either two
  matched symptom words or one distinctive word (used by at most two
  symptoms). An unknown word counts against a match (only a short filler list
  is ignored), a cause word never counts toward the minimum and weighs 0.25,
  one common word that fits more than three symptoms ("noisy") matches none, a
  bare "it doesn't work" with no appliance is not_found, and ties go to the
  symptom the query covers most fully. Appliance-type words in the description
  narrow the search but are never matched on. Every mechanism can only rename a
  word or block a match, never invent one. The paraphrase bank
  (`tests/fixtures/symptom_paraphrases.yaml`, run as
  `uv run python -m tests.symptom_bank`) is the regression test: it fails on any
  wrong cited answer beyond the one flagged `known_wrong` and if recall drops;
  74 tuning cases plus 16 held-out ones (read only after tuning). Matching is
  still keyword-based and can miss things; see CHANGELOG's known limitations. Resolution mirrors `diagnose_error` via `fixit_mcp.tools.common`:
  one owned appliance matches -> `found`; several -> `ambiguous_appliance`
  (never guessed); none owned but another manual matches -> `found` with
  `appliance_registered: false` and `suggest_add_appliance`; nothing -> `not_found`
  with the manual's own nearest phrases (never a cause). Every string in a
  match is a stored verbatim manual string; the only server-written text is the
  fixed `message` templates. `diagnose_error`'s description points at it.
  The demo's system prompt keeps replies to the entries (no cause, step, safety
  judgment or reassurance of its own).

- **Add-a-manual path** (step 11a, `scripts/add_manual.py`, `make add-manual`,
  `CONTRIBUTING.md`). One command: validate args (duplicate id or brand+model
  refused; an id already present with identical brand/model/type/url is treated
  as a re-run, not a duplicate) -> download via `fetch_manuals.download_pdf`
  (shared with `make fetch-manuals`) -> content check (model number, or its
  series stem like `GFE28`, plus a troubleshooting/error-code keyword; runs on
  `extract_lines` output so the encoding repair applies; `--force` overrides)
  -> `--dry-run` stops here, touching nothing (download goes to a temp dir) ->
  append to the manifest as text (comments preserved; a non-empty `--note` is
  required, terms-of-use reminder printed) -> parse -> extract -> merge into
  `error_codes.json`, replacing only that manual's records (others stay as raw
  dicts). Bedrock extraction prints chunk count, token and cost estimates first
  and needs `yes`/`--yes`; the stub refuses to overwrite fully extracted records
  unless `--allow-downgrade`. `make validate-manifest`
  (`scripts/validate_manifest.py`) checks required fields, unique ids and
  brand+model, notes, seeded appliances' `manual_id`, and that every index
  record has a manifest entry; `tests/unit/test_manifest_validation.py` runs it
  on the real manifest, so `make test` covers it. A new manual only reaches the
  deployed server after an image rebuild and runtime update, because the index
  is baked into the image.

- **Chunk filter, page mode and code fixes** (step 11b). `is_worth_extracting_from`
  (`scripts/extract_codes.py`) drops chunks under 60 chars and table-of-contents
  entries (dot leaders) before the old table/heading test; it only ever sends
  fewer chunks than before, and `tests/unit/test_extract_filter.py` proves every
  chunk that produced an existing record still passes (skipped when the gitignored
  parsed files are absent). The parser can shatter a table into tiny fragments
  (bold code labels become false headings), which the heuristic misses. A manifest
  entry can therefore set `extraction_pages: 43-45`: only those pages are sent,
  fragments kept, merged into windows of up to 8,000 chars, and each record's
  `source_page` is the page of the first *line* containing its code
  (`ManualChunk.line_pages`), for every extraction, so a chunk or window that
  spans pages cites the right one (page citations are the PDF's page index,
  which equals the printed page number in every manual that has records). `code_fixes: {wrong: right}` applies
  reviewed corrections for codes a font renders as look-alike glyphs (LG's
  `dEz` -> `dE2`, `svd` -> `Sud`, `vs` -> `uS`); check the rendered page first.
  Bedrock cost estimates use calibrated output tokens: ~81 per chunk (3,311 out /
  41 chunks, first five real runs) and 1,200 per page-mode window (dense tables);
  both are labelled estimates and the real cost has been ~2-3x the window figure.
  The extraction cache is keyed by extractor and chunk text, **not the prompt**:
  after a prompt change use `FORCE=1` to re-extract.
  The model check in `add_manual` also accepts wildcard labels (`*`, `(X)` optional
  letter) as a `wildcard` match. Known cross-manual collision: `PF` (LG dryer and
  LG washer); `diagnose_error` returns `ambiguous_appliance`, never a silent pick.

- **Appliance-type synonyms** (step 16b, `fixit_mcp.domain.appliance_types`).
  `normalize_appliance_type` maps what customers say to the seed data's types
  (`washer`/`washing machine`/`clothes washer` -> `washing_machine`, `fridge`/`freezer`
  -> `refrigerator`, `oven`/`stove` -> `range`, ...). `check_warranty` compares
  normalize(stored) with normalize(query); `add_appliance` stores the normalized type.
  Stored values are never rewritten; they match because both sides are normalized.
  Unknown types pass through (lowercased, underscores), so they never match another type.

- **Grounding eval** (step 16a, `evals/cases.yaml`, `scripts/run_eval.py`,
  `make eval`). Drives `demo.orchestrator.run_turn` against the LOCAL server, one
  fresh `house-eval-<random>` household per case (seeded via `add_appliance`,
  removed after), grades the final reply with deterministic checks and a Bedrock
  judge given only the tool results and the reply. Judge default
  `us.anthropic.claude-opus-4-6-v1` (strongest invokable for this account on
  2026-09-30; newer Opus/Fable models are listed but AccessDenied). Estimate first,
  `--max-cost` guard (default $10). Evaluation tooling only; never imported by
  `src/` (a test checks). Results in gitignored `evals/results-*.json`.

- **Demo spoken replies via Polly** (step 24b, `demo/speech.py`, `POST /speak`).
  Demo-only and **off by default** (`FIXIT_DEMO_POLLY=0`); the MCP server never
  imports it or calls Polly (rule 3 is unaffected). Generative engine, voice
  Matthew, MP3. The page calls `/speak` after rendering a reply and falls back
  to `speechSynthesis` on any non-200 or failed playback; AWS credentials never
  reach the browser. Audio is cached in gitignored `demo/.audio_cache/` by a hash
  of engine, voice, format and text; a per-process character counter hard-stops
  at `FIXIT_DEMO_POLLY_MAX_CHARS` (50,000) and a request is capped at 500
  characters. IAM is one action in `deploy/iam/polly-policy.json` (customer
  managed policy `FixItPolly`). Tests use a fake Polly client; never call real
  Polly from a test.

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

Manual PDFs are fetched (`fixit_mcp.repository`, step 2a), parsed into chunks
(`fixit_mcp.ingestion.parser`, step 2b-2e), structured error codes are
extracted into a committed index (`fixit_mcp.ingestion.extraction`, step 3a),
`diagnose_error` (step 3b) serves exact-code lookups from that index
(`fixit_mcp.retrieval.codes`), a household's appliances are now real,
persistent state the customer can add to and remove via `add_appliance`/
`remove_appliance` (step 3c, `fixit_mcp.repository.sqlite`; step 4b adds
an AgentCore Memory backend for deployment), and
`diagnose_error` has its first MCP Apps visual card (step 3d,
`fixit_mcp.apps`; `diagnose_symptom` has one too, step 27a), and a customer can ask whether an appliance is still
under warranty (`check_warranty`, step 8a, `fixit_mcp.tools.warranty`,
date comparison only, no coverage claims), and a customer can describe a problem
with no error code and get the manual's own troubleshooting rows
(`diagnose_symptom`, step 25b, GE refrigerator and washer only) — but nothing beyond that yet:
no embeddings, no
fuzzy/semantic retrieval beyond `difflib` nearest-match suggestions and the
symptom tool's deterministic keyword matcher, no
Strands, no Alexa+-reachable deployment yet (the server runs on AgentCore
Runtime with IAM-only inbound auth, step 4c, and household data lives in
AgentCore Memory, step 4b), no auth/account
linking, no visual cards for the other tools, no web client, no
parts-ordering or maintenance-scheduling tools. See
`docs/alexa-plus-requirements.md` for the full done/todo/not-needed
checklist against the Alexa+ MCP Toolkit
requirements.
