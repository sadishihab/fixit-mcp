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
| Round-trip tool latency < 500ms | **Done** (local) | `tests/integration/test_latency.py` asserts p95 < 100ms locally over 50 calls, well inside the 500ms budget. Real-world latency once deployed remotely still needs re-validation. |
| Server reachable via a remote HTTPS URL | **In progress (step 4a)** | Not deployed yet. `make tunnel` gives a temporary HTTPS URL via cloudflared for local demos. Step 4a built and locally verified the AgentCore Runtime container (`Dockerfile`, linux/arm64, `make docker-build`/`docker-run`/`docker-smoke`). The durable URL comes from the AgentCore deployment in step 4b, which is **blocked on the household-state decision** (SQLite is per-microVM on AgentCore, see `FRICTION_LOG.md`, step 4a). |
| MCP Apps extension (visual repair cards) | **Started (step 3d)** | `diagnose_error` declares a `ui://` visual card per the current MCP Apps spec (`_meta.ui.resourceUri` on the tool definition, HTML+JS resource served via `resources/read`) — see `CLAUDE.md`'s persistence/MCP Apps bullets and `FRICTION_LOG.md`. Alexa+'s own docs confirm it "supports the MCP Apps extension" via a webview but don't give wire-level specifics; not yet verified against a real Alexa+ device. Only `diagnose_error` has a card so far. |
| OAuth 2.1 + PKCE account linking | **Not built this step** | No auth in this step by design — single unauthenticated tool, no per-customer account linking yet. Required before any customer-specific/write tool ships. |
| `resource` parameter (RFC 8707) on auth requests | **Not needed yet** | Depends on OAuth account linking above. |
| Checkout / payment handoff (for ordering parts) | **Not built this step** | Part-ordering tool is a future milestone; checkout flow depends on it. |
| `addon.json` manifest (store listing, icons, MCP endpoint URL) | **Todo** | Needed at submission/certification time, not for local dev. Requires: name/description (≤123 chars), example phrases, privacy policy + terms URLs, 6 icon sizes (72/64/88/126/180/241 px), and the HTTPS MCP endpoint URL. |
| Deploy/register via Agent Skill or Alexa AI CLI (`alexa-ai deploy`) | **Todo** | Depends on the remote HTTPS URL and `addon.json` above. |
