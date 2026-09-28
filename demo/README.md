# FixIt demo backend -- simulated Alexa+

**This is not the real Alexa+ client.** It's a small local FastAPI backend
that plays the same role Alexa+ eventually will: a real MCP client over
Streamable HTTP, driving a tool-use LLM loop against the FixIt MCP server,
so the tool-calling and MCP Apps card behavior can be exercised and
demoed before a real Alexa+ integration exists (step 6a). There's no web
UI yet -- this is the backend only, driven with `curl` or any HTTP client.

Every API response says so explicitly (`"simulated_alexa_plus": true`).

## Running it

```bash
make demo                                    # against the local dev FixIt server (make run)
make demo AGENT_ARN=arn:aws:bedrock-agentcore:...   # against a deployed AgentCore Runtime
```

Binds to `127.0.0.1` only. It is never meant to be exposed beyond your own
machine.

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
does -- see `CLAUDE.md`) *and* that call's result has `status == "found"`.
Every other tool result -- `not_found`, `ambiguous_appliance`, or a plain
tool with no card at all -- leaves `card` as `null`.

Conversation history and household_id association are per `session_id`.
Send the same `session_id` for every turn of one conversation.

## Design notes

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
| `FIXIT_DEMO_MAX_TOOL_ROUNDS` | `4` | cap on tool-use rounds per turn |
| `FIXIT_DEMO_LIVE_AGENT_ARN` | *(unset)* | only for the opt-in live test, below |

## Tests

```bash
make test    # includes demo/'s own tests (fakes only -- no AWS)
```

- `tests/unit/test_demo_mcp_session.py` -- tool discovery from a fake MCP
  session.
- `tests/unit/test_demo_orchestrator.py` -- the Converse tool-use loop
  against a fake Bedrock client: a plain reply, one tool call, an
  `ambiguous_appliance` follow-up, a tool error, a runaway-loop cap, and
  the MCP Apps card being returned only for a `found` result.
- `tests/integration/test_demo_live.py` -- **opt-in**, real AWS (real
  Amazon Bedrock, and a real deployed AgentCore Runtime): runs one real
  conversation ("my dryer shows tE1") end to end and checks the LG dryer
  code is diagnosed with a card attached.

  ```bash
  FIXIT_DEMO_TESTS=1 FIXIT_DEMO_LIVE_AGENT_ARN=arn:aws:bedrock-agentcore:... \
      uv run --group demo pytest tests/integration/test_demo_live.py
  ```
