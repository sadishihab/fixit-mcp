# FixIt demo backend -- simulated Alexa+

**This is not the real Alexa+ client.** It's a small local FastAPI backend
that plays the same role Alexa+ eventually will: a real MCP client over
Streamable HTTP, driving a tool-use LLM loop against the FixIt MCP server,
so the tool-calling and MCP Apps card behavior can be exercised and
demoed before a real Alexa+ integration exists (step 6a). A single-page
web UI (step 6c, `GET /`) drives it in a browser; the API can still be
driven directly with `curl` or any HTTP client.

Every API response says so explicitly (`"simulated_alexa_plus": true`).

## Running it

```bash
make demo                                    # against the local dev FixIt server (make run)
make demo AGENT_ARN=arn:aws:bedrock-agentcore:...   # against a deployed AgentCore Runtime
```

Binds to `127.0.0.1` only. It is never meant to be exposed beyond your own
machine. Open `http://127.0.0.1:8090/` in a browser for the web UI.

## Fresh household per conversation (for recording)

By default every conversation serves the one household in
`FIXIT_DEMO_HOUSEHOLD_ID` (`house-002`), so anything a conversation adds stays
there. For a clean start every time, turn on fresh-household mode:

```bash
FIXIT_DEMO_FRESH_HOUSEHOLD=1 make demo AGENT_ARN=<deployed runtime ARN>   # or without AGENT_ARN for the local server
make demo-cleanup AGENT_ARN=<the same ARN>                                # when you are done
```

Each new conversation (each new `session_id`, which is what the page's "New
conversation" button starts) gets its own `house-demo-<random>` household, and
the system prompt names it. On that conversation's first turn the backend
calls the server's `add_appliance` tool to give it the LG DLEX8000W dryer and
the GE GTW680BSJWS washer with house-002's dates (through the MCP server,
never straight into AgentCore Memory; it lists first, so a retry never
duplicates). The household id is written to `data/state/demo_households.txt`
(gitignored) before it is seeded; `make demo-cleanup` removes their
appliances with `remove_appliance` and only ever touches ids starting
`house-demo-`. House-002 is never touched in this mode.

## Web UI

`GET /` serves a single self-contained page (`demo/static/index.html`,
loaded once at import time by `demo/web.py` -- same no-file-I/O-per-request
convention as `fixit_mcp/apps/resources.py`): inline CSS/JS, no build
step, no CDN dependencies, so it works offline. It talks only to this
backend's own `/chat` endpoint (same origin) -- no AWS credentials ever
reach the page.

A dark, Echo-Show-style conversation view: a persistent "Simulated
Alexa+" label, a text input, and a mic button (hidden quietly if the
browser has no `SpeechRecognition`; the typed path always works).
Replies are spoken with the browser's `speechSynthesis`, or with Amazon
Polly when enabled (see "Spoken replies with Polly" below); a mute toggle
stops both. Each turn shows one chip per tool call (name, key
arguments, `latency_ms`), and a hidden-by-default "Details" disclosure
with the turn's raw `tool_calls` JSON -- the actual MCP data behind the
answer. A "New conversation" button starts a fresh `session_id`
(`crypto.randomUUID()`, reused for every turn of one conversation so the
AgentCore session stays warm).

**This page is the demo's MCP Apps host.** When a turn's response
includes a `card` (see below), the page renders it in a directly
sandboxed iframe (`sandbox="allow-scripts"`, srcdoc, **never**
`allow-same-origin` combined with `allow-scripts`) and answers the
card's own postMessage handshake: it responds to the card's
`ui/initialize` request, then immediately pushes
`ui/notifications/tool-input` and `ui/notifications/tool-result` with
that turn's `diagnose_error` arguments/result.

Two things confirmed by reading `src/fixit_mcp/apps/diagnose_card.html`'s
actual script and the MCP Apps spec
(`modelcontextprotocol/ext-apps`, `specification/2026-01-26/apps.mdx`)
directly, not assumed:

- **The card never sends `ui/notifications/initialized`.** The spec's
  lifecycle diagram shows the View sending that notification after the
  host answers `ui/initialize`, before the host pushes tool data. This
  card doesn't send it, so the host pushes `tool-input`/`tool-result`
  right after answering `ui/initialize` instead of waiting for a
  notification that will never arrive.
- **Deliberate spec deviation -- single sandboxed iframe, not the
  double-iframe Sandbox Proxy.** The spec requires web hosts to wrap the
  View in an intermediate Sandbox Proxy iframe on a different origin from
  the host. This demo renders the card directly in one sandboxed iframe
  instead (the spec's simpler "Desktop/Native hosts" path). Without
  `allow-same-origin`, a `srcdoc` iframe still gets a unique opaque
  origin distinct from this page, so the isolation goal -- the untrusted
  card can never reach this page's DOM -- holds without the second origin
  hop. Acceptable for a local single-user demo; a production web host
  should implement the full Sandbox Proxy.
- **Sizing**: the card's template has no SDK and never reports its own
  size. Rather than modify the file the MCP server actually serves via
  `resources/read`, the page appends a small inline script to the HTML
  *it* hands the iframe as `srcdoc` (a `ResizeObserver`-based
  `ui/notifications/size-changed` reporter) so the iframe grows to fit
  its content instead of showing a scrollbar or a blank area. The
  resource the server ships and `tests/unit/test_diagnose_card.py` tests
  is untouched.

## Spoken replies with Polly (optional, off by default)

`FIXIT_DEMO_POLLY=1` makes the page speak replies with Amazon Polly's
generative engine and the `Matthew` voice instead of the browser voice. It is
demo-only; the FixIt server never touches Polly.

- After a reply's text and card render, the page calls `POST /speak`
  (`{"text": "..."}`) and plays the returned MP3 with `Audio`. AWS credentials
  stay in the backend process; the browser only receives audio bytes.
- **Fallback:** any non-200, network error, or rejected/failed playback makes the
  page speak with `speechSynthesis` instead. With Polly off, `/speak` answers
  `503 {"error": "speech_disabled"}` and the page stops asking for the rest of
  that page load. **Mute** stops both the Polly audio and the browser voice.
- **Cache:** audio is stored in `demo/.audio_cache/` (gitignored), keyed by a
  hash of engine, voice, format and text, so an identical reply costs nothing,
  across restarts too. Replies the model words differently are new text.
- **Limits:** text over 500 characters is refused (`413`); blank text is `422`.
  Polly calls have a 5 s timeout and one attempt.
- **Spend guard:** the process counts characters it synthesized (cache hits are
  free and not counted) and logs the running total on every call. At 50,000 it
  stops (`503 speech_budget_exhausted`) until restart, or raise
  `FIXIT_DEMO_POLLY_MAX_CHARS`. Pricing and the cost estimate for the video are
  in the step 24a report: about $30 per million characters, so a typical
  one-to-two-sentence reply costs a fraction of a cent.
- IAM: `polly:SynthesizeSpeech` only; see `deploy/iam/polly-policy.json`.

## API

### `POST /chat`

```json
{"message": "my dryer shows tE1", "session_id": "conversation-1"}
```

```json
{
  "reply_text": "That's a temperature sensor issue on your LG dryer...",
  "tool_calls": [
    {"name": "diagnose_error", "arguments": {"error_code": "tE1", "household_id": "house-002"},
     "result": {"status": "found", "...": "..."}, "latency_ms": 87.3}
  ],
  "card": {"resource_uri": "ui://fixit-mcp/diagnose-error-card", "html": "<!doctype html>..."},
  "simulated_alexa_plus": true
}
```

`card` is only populated when a called tool declared an MCP Apps
`resourceUri` (via its own `_meta.ui.resourceUri`, exactly as `diagnose_error`
does -- see `CLAUDE.md`) *and* that call's result has a `status` of
`found`, `not_found`, or `ambiguous_appliance` -- the three states
`diagnose_card.html` itself knows how to render (a full card, or one of
its two muted informational states). This rule is generic over any tool
with a `resourceUri`, not hardcoded to `diagnose_error` by name. A tool
with no `resourceUri` at all, or a result whose `status` is none of those
three, leaves `card` as `null`.

Conversation history and household_id association are per `session_id`.
Send the same `session_id` for every turn of one conversation.

## Design notes

- **A turn never leaves the history half-written, and never hangs** (step 13).
  `run_turn` snapshots the session's Converse history and restores it on every
  failure path (an exception, a timeout, cancellation from a client disconnect,
  or exhausting `max_tool_rounds`); a history already corrupted by an earlier
  failure (a `toolUse` with no `toolResult`) is repaired first and logged as
  `demo_history_repaired`. Each tool call, card fetch and Converse call has a
  time budget; exceeding one is a `demo_chat_turn_failed` log line naming the
  operation and `timeout_s`, and a 504. `/chat` runs one turn per `session_id`
  at a time: a second request gets a 409 `turn_in_progress`, and the page
  disables its input while a turn is pending.

- **Tool definitions are never hardcoded.** At startup, the app calls
  `tools/list` once against the FixIt server and builds Amazon Bedrock's
  `toolConfig` from exactly what the server advertises (names,
  descriptions, JSON schemas). A tool added, removed, or changed on the
  server just shows up here on the next `make demo` restart.
- **One persistent MCP session per conversation**, not a fresh one per
  `/chat` call. AgentCore's own MCP contract says a client "must capture
  the `Mcp-Session-Id` ... and include it in all subsequent requests to
  ensure session affinity," warning that without it "each request may be
  routed to a new microVM" -- i.e. a fresh cold start
  (`FRICTION_LOG.md`'s cold-start entries). `demo/mcp_session.py`'s
  `SessionManager` keeps one `ClientSession` open per `session_id` for the
  life of the demo process.
- **Household**: there's no web UI yet, so there's no per-customer login
  to derive a household from. Every conversation is served as one fixed
  household (`FIXIT_DEMO_HOUSEHOLD_ID`, default `house-002` -- the seeded
  household with the LG dryer used throughout this project's smoke
  tests). Included in the system prompt so the model always passes the
  right `household_id` to tools.
- **The Bedrock Converse tool-use loop** (`demo/orchestrator.py`) follows
  the request/response shape documented at
  `docs.aws.amazon.com/bedrock/latest/userguide/tool-use-client-side.md`
  (`toolConfig.tools[].toolSpec`, `toolUse`/`toolResult` content blocks,
  looping while `stopReason == "tool_use"`), capped at
  `FIXIT_DEMO_MAX_TOOL_ROUNDS` (default 4) rounds so a misbehaving model
  can't loop forever without ever answering.
- **SigV4 signing is reused, not duplicated**: `demo/mcp_target.py` loads
  `scripts/smoke_test.py`'s `SigV4Auth`/`runtime_invocation_url` by file
  path (the same way `tests/unit/test_deploy_scripts.py` already does,
  since `scripts/` has no `__init__.py`).

## Security

- AWS credentials (for Amazon Bedrock and, against a deployed runtime, for
  SigV4-signing MCP requests) stay server-side only -- never returned in
  an API response, never logged.
- CORS is restricted to `localhost`/`127.0.0.1` origins only.
- Bound to `127.0.0.1`, never `0.0.0.0` -- not reachable from another
  machine even accidentally.

## Config

All `FIXIT_DEMO_*` environment variables (`demo/config.py`):

| Variable | Default | Meaning |
|---|---|---|
| `FIXIT_DEMO_HOST` | `127.0.0.1` | bind address |
| `FIXIT_DEMO_PORT` | `8090` | bind port |
| `FIXIT_DEMO_HOUSEHOLD_ID` | `house-002` | the one household every conversation is served as |
| `FIXIT_DEMO_BEDROCK_REGION` | `us-east-1` | Bedrock region |
| `FIXIT_DEMO_BEDROCK_MODEL_ID` | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | Converse model id |
| `FIXIT_DEMO_FRESH_HOUSEHOLD` | `0` | `1`: every new conversation gets its own seeded `house-demo-<random>` household (see below) |
| `FIXIT_DEMO_HOUSEHOLDS_FILE` | `data/state/demo_households.txt` | ledger of the demo households created (gitignored), used by `make demo-cleanup` |
| `FIXIT_DEMO_MAX_TOOL_ROUNDS` | `4` | cap on tool-use rounds per turn |
| `FIXIT_DEMO_TOOL_TIMEOUT_SECONDS` | `15` | budget for each MCP tool call / card fetch |
| `FIXIT_DEMO_CONVERSE_TIMEOUT_SECONDS` | `30` | budget for each Bedrock Converse call |
| `FIXIT_DEMO_TURN_TIMEOUT_SECONDS` | `90` | budget for a whole turn |
| `FIXIT_DEMO_POLLY` | `0` | `1`: speak replies with Amazon Polly (`POST /speak`), browser voice as fallback |
| `FIXIT_DEMO_POLLY_VOICE` | `Matthew` | Polly voice id |
| `FIXIT_DEMO_POLLY_ENGINE` | `generative` | Polly engine |
| `FIXIT_DEMO_POLLY_REGION` | `us-east-1` | Polly region |
| `FIXIT_DEMO_POLLY_MAX_CHARS` | `50000` | hard stop: characters synthesized per process |
| `FIXIT_DEMO_POLLY_REQUEST_MAX_CHARS` | `500` | longest text one `/speak` call accepts |
| `FIXIT_DEMO_POLLY_TIMEOUT_SECONDS` | `5` | Polly read timeout (one attempt) |
| `FIXIT_DEMO_POLLY_CACHE_DIR` | `demo/.audio_cache` | audio cache (gitignored) |
| `FIXIT_DEMO_LIVE_AGENT_ARN` | *(unset)* | only for the opt-in live test, below |

## Tests

```bash
make test    # includes demo/'s own tests (fakes only -- no AWS)
```

- `tests/unit/test_demo_mcp_session.py` -- tool discovery from a fake MCP
  session.
- `tests/unit/test_demo_orchestrator.py` -- the Converse tool-use loop
  against a fake Bedrock client: a plain reply, one tool call, a tool
  error, a runaway-loop cap, and the MCP Apps card being returned for
  `found`, `not_found`, and `ambiguous_appliance` results but not for an
  unrecognized status or a tool with no `resourceUri`.
- `tests/unit/test_demo_app.py` -- `GET /` serves the web UI page (fakes
  only, no AWS/MCP network), and `/chat`'s route is unchanged.
- `tests/unit/test_demo_web_ui.py` -- the web page's pure/DOM-free JS
  (card-ownership decision, handshake message builders, chip formatting)
  executed directly in Node, same rationale as
  `tests/unit/test_diagnose_card.py`. Skipped if `node` isn't on PATH.
- `tests/integration/test_demo_live.py` -- **opt-in**, real AWS (real
  Amazon Bedrock, and a real deployed AgentCore Runtime): runs one real
  conversation ("my dryer shows tE1") end to end and checks the LG dryer
  code is diagnosed with a card attached.

  ```bash
  FIXIT_DEMO_TESTS=1 FIXIT_DEMO_LIVE_AGENT_ARN=arn:aws:bedrock-agentcore:... \
      uv run --group demo pytest tests/integration/test_demo_live.py
  ```
