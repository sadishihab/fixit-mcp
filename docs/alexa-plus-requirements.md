# Alexa+ MCP Toolkit requirements checklist

Compiled from the official Alexa+ MCP Toolkit docs. Status reflects this
repo's state as of the initial scaffolding step (`0.1.0`).

Sources:
- [MCP Toolkit overview](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-overview.html)
- [MCP Toolkit quickstart](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html)
- [MCP Toolkit client lifecycle](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-client-lifecycle.html)

| Requirement | Status | Notes |
|---|---|---|
| Streamable HTTP transport | **Done** | `FastMCP(..., stateless_http=True)`, served at `/mcp`. See `src/fixit_mcp/server.py`. |
| MCP spec 2025-11-25 support | **Done** | `mcp==1.30.0`'s `LATEST_PROTOCOL_VERSION`. Verified by `tests/integration/test_server_protocol.py`. |
| Negotiate older client protocol versions (docs show client sending `2025-03-26`) | **Done** | SDK echoes back any version in `SUPPORTED_PROTOCOL_VERSIONS`. Verified by `tests/integration/test_server_legacy_protocol.py`. |
| Round-trip tool latency < 500ms | **Warm calls fit the budget. Cold sessions are a known limitation.** | Local dev server: `tests/integration/test_latency.py` asserts p95 < 100ms, now across all five tools including `check_warranty` (step 8a; not yet separately measured against deployed AgentCore Memory). AgentCore Memory in-region (CloudShell): tool p95 of 138.4ms for `diagnose_error`, 109.9ms for `add_appliance`, 119.8ms for `remove_appliance`. Deployed Runtime, `platformVersion: "V2"`, measured from Dhaka (~320ms RTT to us-east-1): **warm** `diagnose_error` p50 571.8ms / p95 645.2ms client-side, of which ~317ms is RTT and ~54ms is our own handler — well inside budget once RTT is discounted to an in-region customer. **Cold sessions are not solved**: a brand-new session costs ~5s end to end (init + first tool call) regardless of platform version, and the specific ~1s internal hold between `initialize` and the first tool call being dispatched has a known cause ruled out (`/ping`, step 5d) but no known fix yet. Full numbers, what's documented vs. inferred, and what AWS should document: `FRICTION_LOG.md`, **"Cold-start latency: known limitation."** |
| Server reachable via a remote HTTPS URL | **Done: IAM-auth only; JWT/OAuth pending** | Deployed to Amazon Bedrock AgentCore Runtime (step 4c): runtime `fixit_mcp`, us-east-1, MCP protocol, pinned to the tested image digest, `agentcore` household backend. Durable HTTPS endpoint: `https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/<URL-encoded runtime ARN>/invocations?qualifier=DEFAULT`. The real ARN contains the account id, so it's not committed; `make deploy-runtime` prints it. Inbound auth is **IAM SigV4 only**, because AgentCore Runtime has no anonymous option. So the URL works for our own tooling (`make runtime-smoke`, 8/8 functional checks pass) but **not yet for Alexa+**, which needs the OAuth/JWT authorizer (see the OAuth row). Switching the authorizer later is an `UpdateAgentRuntime`, so the URL stays the same. Teardown: `make teardown-runtime`. |
| MCP Apps extension (visual repair cards) | **Started (step 3d)** | `diagnose_error` declares a `ui://` visual card per the current MCP Apps spec (`_meta.ui.resourceUri` on the tool definition, HTML+JS resource served via `resources/read`) — see `CLAUDE.md`'s persistence/MCP Apps bullets and `FRICTION_LOG.md`. Alexa+'s own docs confirm it "supports the MCP Apps extension" via a webview but don't give wire-level specifics; not yet verified against a real Alexa+ device. Only `diagnose_error` has a card so far. |
| OAuth 2.1 + PKCE account linking | **Not built this step** | No auth in this step by design — single unauthenticated tool, no per-customer account linking yet. Required before any customer-specific/write tool ships. |
| `resource` parameter (RFC 8707) on auth requests | **Not needed yet** | Depends on OAuth account linking above. |
| Checkout / payment handoff (for ordering parts) | **Not built this step** | Part-ordering tool is a future milestone; checkout flow depends on it. |
| `addon.json` manifest (store listing, icons, MCP endpoint URL) | **Todo** | Needed at submission/certification time, not for local dev. Requires: name/description (≤123 chars), example phrases, privacy policy + terms URLs, 6 icon sizes (72/64/88/126/180/241 px), and the HTTPS MCP endpoint URL. |
| Deploy/register via Agent Skill or Alexa AI CLI (`alexa-ai deploy`) | **Todo** | Depends on the remote HTTPS URL and `addon.json` above. |
