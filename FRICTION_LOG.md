# Friction log

Template for each entry:

```
### YYYY-MM-DD — <short title>

- **Tool/SDK**: 
- **Task attempted**: 
- **Steps taken**: 
- **Expected**: 
- **Actual**: 
- **Severity**: Critical / High / Medium / Low
- **Workaround**: 
- **Actionable suggestion**: 
```

---

### 2026-09-23 — `pip install mcp` installs a version that breaks AWS's own sample code

- **Tool/SDK**: `mcp` (Model Context Protocol Python SDK), PyPI.
- **Task attempted**: Install the official MCP Python SDK to build a Streamable
  HTTP server per the AWS Bedrock AgentCore Runtime docs, which show:
  `from mcp.server.fastmcp import FastMCP`.
- **Steps taken**: Ran `pip install mcp` in a scratch venv (installs `2.2.0`,
  the current PyPI default), then tried `from mcp.server.fastmcp import FastMCP`.
- **Expected**: Import succeeds, matching the AWS AgentCore quickstart doc's
  sample code verbatim.
- **Actual**: `ModuleNotFoundError`, with a message explaining `mcp` 2.x
  renamed `FastMCP` to `MCPServer` and changed its API (moved from
  `mcp.server.fastmcp` to `mcp.server.mcpserver`), pointing to a migration
  guide. AWS's own docs (last checked 2026-09-23) still show the old
  `FastMCP` API and don't mention this at all — following them literally with
  a fresh `pip install mcp` breaks immediately.
- **Severity**: High — this is the very first line of code in AWS's own
  quickstart, and it silently breaks for anyone installing the SDK today.
- **Workaround**: Pin `mcp>=1.30,<2` (the last 1.x release). It has the same
  `FastMCP` API AWS's docs describe, and its `SUPPORTED_PROTOCOL_VERSIONS`
  already includes `2025-11-25` and `2025-03-26`, so no functionality is lost
  for this project.
- **Actionable suggestion**: AWS should either update the AgentCore docs'
  sample code for `mcp` 2.x's `MCPServer` API, or explicitly pin `mcp<2` in
  their own `pip install` instructions.

### 2026-09-23 — 404 fetching the python-sdk `CHANGELOG.md` from GitHub

- **Tool/SDK**: `modelcontextprotocol/python-sdk` GitHub repo.
- **Task attempted**: Before pinning a version, wanted to read the SDK's
  changelog to confirm protocol-version support and negotiation behavior
  across releases without spelunking through source.
- **Steps taken**: Fetched
  `https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/CHANGELOG.md`.
- **Expected**: A changelog listing releases and notable changes, including
  protocol-version support (this pattern works for most GitHub Python
  projects).
- **Actual**: HTTP 404 — the file doesn't exist at that path on `main` (the
  project apparently doesn't maintain a root `CHANGELOG.md`, or release notes
  live elsewhere, e.g. GitHub Releases).
- **Severity**: Low — didn't block anything, just meant switching approach.
- **Workaround**: Verified protocol-version support directly against the
  installed package instead of a changelog: installed both `mcp` 1.30.0 and
  2.2.0 in scratch venvs and inspected `mcp.types.LATEST_PROTOCOL_VERSION` /
  `mcp.shared.version.SUPPORTED_PROTOCOL_VERSIONS` (1.x) and
  `mcp_types.version.HANDSHAKE_PROTOCOL_VERSIONS` (2.x) directly, plus a
  `WebSearch` that surfaced the GitHub Releases page instead.
- **Actionable suggestion**: Either add a root `CHANGELOG.md` to the repo (the
  convention most tooling and humans expect), or make the README point
  explicitly to GitHub Releases as the source of truth for what changed
  between versions.

### 2026-09-23 — No way to make the official MCP client send an older `protocolVersion`

- **Tool/SDK**: `mcp` 1.30.0, `mcp.client.session.ClientSession`.
- **Task attempted**: Write an integration test proving the server correctly
  negotiates `protocolVersion: "2025-03-26"`, matching what the Alexa+ MCP
  Toolkit's client-lifecycle docs show its client sending.
- **Steps taken**: Looked for a parameter on `ClientSession.__init__` or
  `.initialize()` to set the requested protocol version; read the SDK source
  (`mcp/client/session.py`).
- **Expected**: Some supported way to request a specific `protocolVersion`,
  since real-world clients (like Alexa+, per its own docs) do this.
- **Actual**: `ClientSession.initialize()` hardcodes
  `protocolVersion=types.LATEST_PROTOCOL_VERSION` with no override — there is
  no supported way to make the reference client claim an older version.
- **Severity**: Medium — didn't block the work, but meant the test for this
  requirement couldn't use the SDK's own `.initialize()` and had to construct
  the raw `InitializeRequest` via `session.send_request(...)` directly (see
  `tests/integration/test_server_legacy_protocol.py`).
- **Workaround**: Call `session.send_request(types.ClientRequest(types.InitializeRequest(...)), types.InitializeResult)`
  directly with a custom `protocolVersion`, then send the
  `notifications/initialized` notification manually before continuing.
- **Actionable suggestion**: Add an optional `protocol_version` parameter to
  `ClientSession.__init__` or `.initialize()` so backward-compatibility testing
  doesn't require bypassing the public API.

### 2026-09-23 — `streamablehttp_client` deprecated with no compile-time signal

- **Tool/SDK**: `mcp` 1.30.0, `mcp.client.streamable_http`.
- **Task attempted**: Connect a test client to the local server over
  Streamable HTTP.
- **Steps taken**: Used `streamablehttp_client(url)` as shown in AWS's own
  AgentCore docs sample code; ran the test suite.
- **Expected**: Clean test run.
- **Actual**: Tests passed, but emitted a `DeprecationWarning: Use
  'streamable_http_client' instead.` The deprecation isn't visible anywhere in
  the docs consulted (AWS's sample still uses the old name) — only surfaces at
  runtime.
- **Severity**: Low.
- **Workaround**: Switched all test files to `mcp.client.streamable_http.streamable_http_client`
  (note: no underscore between `streamable` and `http` — easy to typo against
  the deprecated name).
- **Actionable suggestion**: Update AWS's sample code to the current function
  name.
