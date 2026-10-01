# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **An MCP Apps visual card for `diagnose_symptom`** (`ui://fixit-mcp/diagnose-symptom-card`), declared on the tool definition the way `diagnose_error` declares its own, in the same visual language: the matched symptom phrases as the title, each row's possible causes and the third column under its own label ("What To Do" or "Reason"), muted footnotes, a muted "incomplete in the manual" marker, a citation line per match (up to three matches), and muted states for `not_found` (with the manual's nearest phrases), `ambiguous_appliance` and the `appliance_registered: false` notice. No click handlers, no external resources, every field escaped.

### Changed

- The cards' shared CSS, escape helper and MCP Apps handshake now live once (`card_shared_*`, `card_handshake.js`) and are assembled into each card at import time. The `diagnose_error` card served over `resources/read` is byte-for-byte unchanged (a test pins its hash).
- The demo page's card iframe may grow to 2,400 px (was 900) so a three-match symptom card is not clipped.
- **`diagnose_symptom` matches more everyday phrasings, and gives fewer wrong answers.** Still deterministic
  and model-free, still `not_found` rather than a guess. What changed in the matcher:
  - A reviewed table of synonyms and multi-word phrases folds everyday words onto the manual's own
    ("won't turn on", "stopped working", "dead" -> does not operate; "shaking", "vibrating", "wobbling" ->
    rocking; "damp", "soaked" -> wet; "squealing", "creaking" -> squeaking; "alarm" -> beeping; "not cold",
    "too warm" -> not cooling; "water all over the floor" -> leaks; and similar). Every target is a word the stored
    rows use; a test enforces it.
  - **Negation must agree.** "won't spin" no longer reaches the row about how the washer "pauses during
    spin", and "my car won't start" no longer reaches "Washer won't operate".
  - Light spelling tolerance: a single-character slip on a word of five or more letters ("dispencer",
    "wrinkeld", "refridgerator") is mended, but only when exactly one known word is one edit away.
  - **Evidence rules.** A word the manuals do not contain now counts against a match (before, one such word
    was ignored); only a short list of fillers ("really", "way", "like crazy") is ignored. A match needs two
    matched symptom words or one distinctive word (used by at most two symptoms); a word found only in a cause
    no longer counts toward the minimum, and counts for less (weight 0.25, was 0.4). A bare "it doesn't work"
    with no appliance named is `not_found`. One common word that fits more than three symptoms ("my washer is
    noisy") matches none of them; before, it returned three arbitrary sounds as `found`.
- Measured on a bank of 90 invented phrasings (`tests/fixtures/symptom_paraphrases.yaml`; 74 used while
  tuning, 16 held out and not looked at until the end). Tuning split: correct matches 25 of 47 before, 43 of 47
  now; wrong symptom first 4 before, 0 now; descriptions that should find nothing but matched 5 of 27 before, 0
  now. Held-out split: correct matches 4 of 10 before and after (no gain); wrong symptom first 1 before and
  after; should-find-nothing but matched 2 of 6 before, 0 now. `tests/unit/test_symptom_bank.py` fails on any
  new wrong answer and if recall drops.

### Known limitations

These replace the 0.2.0 note about the symptom tool's matching; the other 0.1.0 and 0.2.0 limitations stand.

- **Matching is still keyword-based and can miss things.** The gain is real on phrasings its vocabulary
  covers, and none on ones it does not: on the held-out phrasings it found 4 of 10, the same as before.
  Phrasings that still find nothing include: "chirping" (for beeping), "stalls halfway through the spin",
  "a puddle under my washer", "soapy bubbles", "no water coming out of my fridge" (the word "water" fits too
  many symptoms), "my washer walks across the floor", "the dispenser overfills my glass", and long descriptions
  with several extra words ("I press the start button ... and nothing happens at all"). "Water drips from the
  dispenser" is `ambiguous_appliance` for a household with both a refrigerator and a washer, which is honest.
- **One known wrong answer remains**: "my washer is rocking back and forth" is sent to the Sounds row "Back
  and forth" because they share those two common words (the old matcher did the same). It is flagged in the
  bank; no clean general rule fixed it without breaking correct matches.
- The bank is invented wording written by the maintainer, not recorded customer speech, so the percentages
  say how the matcher does on these phrasings, not on real customers.
- Still true from 0.2.0: only the GE refrigerator and washer have symptom rows (the GE range's table is not
  extracted), the two "such as" rows end mid-sentence, and the ambiguous-household path was exercised live only
  on invented data.

## [0.2.0] - 2026-10-01

Adds a sixth tool, `diagnose_symptom`, for problems a customer describes without an
error code, and an optional spoken voice for the demo.

### Added

- **`diagnose_symptom`, a sixth tool.** It finds a problem described in the customer's own
  words (no error code) in the "Problem / Possible Causes / What To Do" tables of their
  appliances' manuals and returns the manual's own rows (the problem, the possible causes,
  what to do), cited to a manual page. Matching is deterministic keyword overlap with no
  model call: stopwords, light stemming, a small curated synonym table, rarity weights, a
  minimum score of 0.5 and at least two matched words (one query word that appears in no
  manual is not counted against the customer), and a cause text alone never matches. It
  resolves the household's appliances the way `diagnose_error` does: `found`,
  `ambiguous_appliance` (never guessed), an `appliance_registered: false` notice with
  `suggest_add_appliance` when the entry is for an appliance the household has not
  registered, and `not_found` with the manual's own nearest phrases and no invented cause.
  Every string in a match is stored manual text; the only text the server writes is a fixed
  `message`.
- **`data/index/symptoms.json`**: 114 rows, committed. 42 from the GE refrigerator
  (pages 46-48) and 72 from the GE washer (pages 26-28, including its "Sounds" table, whose
  third column is a "Reason", not an instruction). Each row is the manual's wording with a
  page citation; two rows are flagged `text_incomplete` because a brand logo in the PDF is
  an image and the sentence ends "such as". The image copies the file and startup fails if
  it is missing.
- **`make extract-symptoms`**: an offline pipeline that reads each table from the PDF
  geometry (PyMuPDF `find_tables()`), repairs the GE refrigerator's corrupted font per span
  with the offset the parser already established, and extracts the rows with Amazon Nova Pro
  (never Claude; any other model id is refused) under a hard spending cap (`--max-cost`,
  default $1.00) with an estimate printed first. Nothing the model returns is trusted until
  an audit passes: the expected row count from the table geometry, each row's strings
  joined must equal the source cell exactly (whitespace collapsed, nothing else), footnote
  links derived from the markers in the row, a mid-sentence flag, and a bounded retry on an
  empty, short or unparseable answer. A manual's rows are written only if every one of its
  tables passed, and cached answers are re-audited on every read. `DRY_RUN=1` calls nothing.
  The real run cost about $0.10 (at assumed list prices).
- **Optional Amazon Polly voice for the simulated Alexa+ demo** (`FIXIT_DEMO_POLLY=1`, off
  by default): `POST /speak` with the generative-engine voice Matthew, an audio cache keyed
  by text, a 500-character request cap, a 50,000-character per-run spend guard, and the
  browser voice as the fallback. Needs `polly:SynthesizeSpeech`
  (`deploy/iam/polly-policy.json`). Demo-only: the server makes no Polly calls.
- Six grounding-eval cases for `diagnose_symptom` (found, a `Reason` sound row, not found,
  ambiguous, unregistered, and an adversarial "is it dangerous / should I call someone"
  follow-up); the case file now has 72 cases, up from 66.
- A `diagnose_symptom` check in `scripts/smoke_test.py` (the sixth expected tool), and a
  p95 latency test for the tool's found and not-found paths.

### Changed

- `diagnose_error`'s tool description now says to call `diagnose_symptom` when the customer
  describes a problem with no code, and the server instructions mention described problems.
  `diagnose_error`'s behavior is unchanged.
- The shared household-to-manual resolution (`ApplianceChoice`, `to_choice`,
  `resolve_owned_appliances`, `pair_owned_with_records`) moved out of `tools/diagnose.py`
  into `tools/common.py`.
- The demo's system prompt has rules for symptom replies: state only what the returned rows
  say; never call a sound or symptom "can be normal" or "is normal" unless a row says so;
  make no statement about safety or warnings (a symptom result has no safety field), saying
  only that the troubleshooting table does not address safety. The existing
  empty-`safety_warnings` rule is now scoped to `diagnose_error` results. `diagnose_symptom`
  is also retry-safe in the demo.
- `make validate-manifest` also checks that every record in `symptoms.json` points at a
  manifest entry.

### Known limitations

These add to the 0.1.0 limitations, which still apply.

- **The GE range's symptom table is not extracted.** Its table is unruled, so
  `find_tables()` returns it as two merged columns; it needs its own reader. Only the GE
  refrigerator and washer have symptom rows, so `diagnose_symptom` answers nothing for the
  other five manuals.
- **The symptom tool is only as good as its keyword matching.** It matches words, not
  meaning: some everyday phrasings find nothing (a dry check showed that "won't turn on" and
  "vibrating like crazy" return `not_found`), a long, rambling description can fall below
  the threshold, and the synonym table is small. It says `not_found` rather than guess.
- **The ambiguous-household path was tested only on invented data**, in unit and
  integration tests. It was not exercised live: the demo household `house-002` owns a washer
  and a dryer, so a symptom that matches a refrigerator and a washer cannot arise there.
- Two washer rows end mid-sentence in the extracted text (the missing words are a logo image
  in the PDF); the tool flags them and tells the assistant not to complete them.
- The six new eval cases were run once (Nova Pro as both the answering model and the judge);
  3 of 6 passed. In that run the Nova judge passed a reply containing an invented "normal"
  that a deterministic check caught, so a Nova judge needs the deterministic checks beside
  it. The demo prompt was changed afterwards (see Changed) and the cases have not been
  re-run.

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

[Unreleased]: https://github.com/sadishihab/fixit-mcp/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/sadishihab/fixit-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/sadishihab/fixit-mcp/releases/tag/v0.1.0
