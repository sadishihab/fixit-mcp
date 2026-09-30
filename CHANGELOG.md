# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-01

First release, built for the Alexa+ track of the *Build, Ship, Shape: Amazon
Developer Hackathon*.

### Added

- **MCP server** on the official Python SDK (`mcp>=1.30,<2`): spec 2025-11-25 over
  Streamable HTTP in stateless mode, served at `0.0.0.0:8000/mcp`. It also
  negotiates the `2025-03-26` version the Alexa+ documentation shows its client
  sending; both are covered by integration tests. No LLM calls in any tool handler.
- **Five tools**: `list_my_appliances`, `add_appliance`, `remove_appliance`,
  `diagnose_error` and `check_warranty`.
  - `diagnose_error` looks up an error code from the committed index and returns
    its meaning, causes, repair steps, parts and safety warnings, cited to the
    manual and page. It returns a structured `ambiguous_appliance` when a code
    matches several of a household's appliances, and `not_found` with nearest
    codes rather than an invented answer.
  - `check_warranty` is a deterministic date comparison of the *recorded* dates;
    it makes no coverage claim.
  - Appliance-type synonyms (`washer`, `fridge`, `stove`, ...) map to the stored types.
- **MCP Apps visual card** for `diagnose_error` (`ui://fixit-mcp/diagnose-error-card`),
  with distinct renderings for `found`, `not_found` and `ambiguous_appliance`.
- **Seven manuals** in `data/manuals/manifest.yaml` (GE, Bosch, LG, Samsung). Error-code
  records in `data/index/error_codes.json` come from five of them; the GE
  refrigerator and washer manuals yield none (the washer's troubleshooting is
  symptom-based, with no code table).
- **Offline extraction pipeline**: manual PDFs are fetched, parsed into section-aware
  chunks (with repair for two manuals' broken font encoding), and extracted into
  structured records with Amazon Bedrock at ingestion time, never inside a request.
  A deterministic, no-network `stub` extractor is the default.
- **`make add-manual`**: one command from a manual URL to validated, cited records,
  with a content check, `DRY_RUN=1`, and `make validate-manifest`. See `CONTRIBUTING.md`.
- **Household storage** with three backends: in-memory, SQLite (the local default),
  and Amazon Bedrock AgentCore Memory (`agentcore`) for the deployment.
- **Deployment to Amazon Bedrock AgentCore Runtime**: an arm64 container image and
  scripts to push it and to create or update the runtime, pinned to the image digest,
  plus `make teardown-runtime`. Household data lives in AgentCore Memory.
- **Grounding eval** (`make eval`): 66 scripted conversations run through the demo
  against the local server, graded by deterministic checks and a Bedrock judge model.
- **CloudWatch observability** (`make observability`): metric filters on the server's own
  log lines, a `FixIt` dashboard, alarms on errors and handler p95 latency, and 90-day
  log retention.
- **No-AWS quickstart**: `make run` then `make try-it` needs only Python 3.12 and `uv`.
- **Simulated Alexa+ demo** (`make demo`): a local backend with a small web UI that
  plays Alexa+'s role against the server.
- Open-source basics: CI, issue and pull request templates, `SECURITY.md`, and eight
  drafted good first issues in `docs/good-first-issues/`.

### Known limitations

- **Alexa+ is simulated.** The Alexa+ developer tools (account linking, the local
  inspector, add-on submission) are not available to hackathon participants, so the
  real client has not been connected. The demo is not the real Alexa+.
- **Inbound auth is IAM (SigV4) only.** The deployed runtime has no anonymous or OAuth
  inbound auth, so Alexa+ cannot call it.
- **Cold sessions take about 5 seconds.** A brand-new AgentCore Runtime session is slow
  to start; warm calls are much faster. The measured warm p50 was about 572 ms from
  Dhaka, of which about 320 ms is network; the in-region figure is an estimate, so the
  500 ms Alexa+ budget is not confirmed from inside the region.
- **Claude on Bedrock is not covered by the hackathon credit.** It is billed through
  AWS Marketplace. It is needed only for `FIXIT_EXTRACTOR=bedrock`, `make demo` and
  `make eval`; the server itself makes no model calls.
- AgentCore Memory events expire after at most 365 days.
- A new manual reaches the deployed server only after an image rebuild and runtime update.
- Not built: OAuth account linking, parts ordering, maintenance scheduling.

[Unreleased]: https://github.com/sadishihab/fixit-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/sadishihab/fixit-mcp/releases/tag/v0.1.0
