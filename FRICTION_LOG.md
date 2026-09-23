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

### 2026-09-23 — whirlpool.com blocks all programmatic PDF fetches with a bare 403

- **Tool/SDK**: whirlpool.com's document CDN (`whirlpool.com/content/dam/global/documents/...`).
- **Task attempted**: Building `data/manuals/manifest.yaml` (step 2a), wanted
  to keep the household's original seed appliances (a Whirlpool refrigerator
  and dryer) and link them to their real, official manuals.
- **Steps taken**: Found several correct-looking `whirlpool.com/content/dam/...`
  PDF URLs via search (owner's manuals, spec sheets, repair parts lists).
  Verified each with `curl` first, including with a realistic Chrome
  `User-Agent` and an explicit `Referer: https://www.whirlpool.com/` header,
  both as `HEAD` and full `GET` requests.
- **Expected**: A `200` with `Content-Type: application/pdf`, same as every
  other manufacturer CDN checked in this step.
- **Actual**: Every single `whirlpool.com/content/dam/...` URL returned `403`
  with a small `text/html` body, regardless of URL, method, or headers —
  including URLs whose PDFs clearly exist and are linked from whirlpool.com's
  own pages. This looks like bot/IP-based blocking (e.g. Akamai) rather than
  anything about the specific request, since varying headers changed nothing.
- **Severity**: High for this task specifically — it eliminated an entire
  manufacturer (and the appliances already seeded from step 1) from being
  usable, not because the manuals don't exist or aren't free, but because the
  CDN won't serve them to a non-browser client from this environment.
- **Workaround**: Dropped Whirlpool from the manifest entirely and re-picked
  brands/models (GE, Bosch, LG) whose document CDNs served plain `curl`
  requests without issue. Updated the seed appliance data in
  `src/fixit_mcp/repository/in_memory.py` to match.
- **Actionable suggestion**: For the real ingestion pipeline (not this
  scaffolding step), don't assume "manufacturer publishes a free PDF" implies
  "that PDF is fetchable by a script" — verify with the exact fetch method
  (headless script, not a browser) that will run in production, and keep a
  fallback list of alternate sources (or manual re-hosting) for manufacturers
  known to block bots, Whirlpool included.

### 2026-09-23 — a filename/title match isn't proof the PDF is the right manual

- **Tool/SDK**: N/A (manual-sourcing research, `media3.bosch-home.com`).
- **Task attempted**: Verifying a Bosch dishwasher manual PDF found via search
  actually matches model `SHXM4AY55N` and contains an error-code table, before
  adding it to the manifest.
- **Steps taken**: Search returned `https://media3.bosch-home.com/Documents/MCDOC02675188_SHXM4AY55N.pdf`
  — model number literally in the filename. Downloaded it and checked with
  `pdfinfo`/`pdftotext` instead of trusting the filename.
- **Expected**: A full use-and-care manual with a troubleshooting/error-code
  section, matching the filename's implied model.
- **Actual**: It's a real, valid PDF for that exact model — but only a 3-page
  spec/tech-sheet (wattage, cycle count, dBA rating, etc.), with no
  troubleshooting or error-code content at all. Filename match was a false
  signal.
- **Severity**: Medium — would have silently shipped a manifest entry with a
  "manual" that's useless for the stated purpose (extracting error codes) if
  content hadn't been checked.
- **Workaround**: Actually opened every candidate PDF with `pdfinfo`/`pdftotext`
  and grepped for model numbers and error/fault/troubleshooting keywords
  before adding it to the manifest, rather than trusting search result titles
  or filenames. Switched the dishwasher entry to a different Bosch model
  (SHE53B75UC) whose manual is the real 60-page use-and-care guide with a
  troubleshooting chapter.
- **Actionable suggestion**: For the future ingestion pipeline, always run
  this same "does it actually contain what we need" content check as an
  automated manifest-validation step, not just a one-time manual check —
  manufacturer CDNs mix spec sheets, install guides, and full manuals under
  similar-looking filenames.

### 2026-09-23 — pdfplumber's table detector mangled a rotated sidebar into a phantom table

- **Tool/SDK**: `pdfplumber` 0.11.10 (evaluated, not adopted).
- **Task attempted**: Deciding which PDF library to use for
  `fixit_mcp/ingestion/parser.py`; tried `pdfplumber.Page.extract_tables()` on
  the GE range manual's actual "Problem / Possible Causes / What To Do"
  troubleshooting page to see if it could give real table structure for free.
- **Steps taken**: Ran `extract_tables()` on that page and inspected the result.
- **Expected**: A 3-column table (Problem / Possible Causes / What To Do), or
  at worst a failure to detect anything.
- **Actual**: It returned two "tables" — the second was a corrupted mess
  missing 2 of the table's 3 columns, and the *first* was pure garbage: a
  rotated vertical sidebar of chapter names elsewhere on the page got picked
  up as its own "table" with every line's characters in reversed order
  (`snoitcurtsnI\nytefaS` for "Safety Instructions"). On a different manual's
  error-code page (LG dryer), the same function worked reasonably well. No
  way to know in advance which behavior a given page would get.
- **Severity**: Medium — didn't block anything since it wasn't adopted, but
  cost real investigation time, and would have been a nasty silent-data-
  quality bug if trusted without checking real output.
- **Workaround**: Didn't use `pdfplumber`'s table extraction at all. Used
  PyMuPDF for extraction and a much simpler content heuristic
  (`looks_like_table()`: does the section's plain reading-order text pair a
  problem-side phrase with a solution-side phrase) instead of any geometric
  table reconstruction. See `docs/pdf-extraction-library-choice.md`.
- **Actionable suggestion**: Never trust a PDF table-extraction library's
  output on a new document type without inspecting a real result first —
  "table detected" and "table detected correctly" are very different claims,
  and the failure mode (silently wrong columns, reversed text) isn't obviously
  wrong at a glance.

### 2026-09-23 — bold text at body size falsely triggered heading detection, shredding the exact content we need

- **Tool/SDK**: `fixit_mcp.ingestion.parser` (this project's own code).
- **Task attempted**: Detecting section headings via font size/weight, per
  the step's own design ("layout signals (font size/weight if available)").
- **Steps taken**: First implementation treated any bold line as a heading
  candidate. Ran it on `ge-jbp26-range.pdf`'s actual F-code troubleshooting
  table and inspected the output chunks.
- **Expected**: The troubleshooting table (the single most important piece of
  content in this whole step) would stay as one coherent, readable section.
- **Actual**: GE typesets the "Problem"/"Possible Causes" half of that table
  in **bold at the same font size as body text**. Treating bold alone as a
  heading signal meant nearly every other line in the table was detected as
  a new section heading, fragmenting the F-code entry across dozens of
  one-line "sections" and producing 356 chunks for a 28-page manual.
- **Severity**: High — this directly broke the content the entire ingestion
  step exists to preserve, and would have silently shipped a garbage
  "error-code table" chunk if the raw output hadn't been inspected before
  moving on, as the task explicitly asked for.
- **Workaround**: Stopped trusting bold alone. A line only counts as a
  heading via the font-based signal when it's notably *larger* than body text
  (ratio ≥ 1.3), or bold *and* at least somewhat larger (ratio ≥ 1.2 with
  bold) — never bold at 100% body size alone. See `heading_info()` and its
  regression test `test_heading_info_ignores_bold_at_body_size`.
- **Actionable suggestion**: When building heading/structure detection from
  font metadata, always test against a real table or form with a bolded
  column header, not just prose headings — that's the case that breaks a
  naive "bold = heading" rule, and it's a common enough manual layout that it
  will show up in a real corpus, not just as an edge case.

### 2026-09-23 — corrupted font encoding in two manuals feeds bogus heading detection, compounding the damage

- **Tool/SDK**: `pymupdf` extraction of `ge-gfe28gynfs-refrigerator.pdf` and
  `lg-dlex8000w-dryer.pdf` (also affects `pypdf`, `pdfplumber` — see the
  fetch-step friction entries above for the base issue).
- **Task attempted**: Chunking these two manuals' troubleshooting/error-code
  sections without cutting the actual error content into fragments.
- **Steps taken**: These two PDFs have text runs whose extracted output is
  garbled (e.g. `)LOWHU FDUWULGJH` for "Filter cartridge", or `U&` for what
  should be a real LG dryer code like `tE1`) because of a broken font
  ToUnicode mapping in the source PDF. Inspected the resulting chunks around
  each manual's actual error/fault-code table.
- **Expected**: Garbled text would just look garbled inline within otherwise
  normal chunks.
- **Actual**: The garbled runs are *also* usually mostly-uppercase, which fed
  directly into the ALL-CAPS heading heuristic and got misdetected as new
  section headings — splitting the GE fridge's dispenser "Error message"
  reference and the LG dryer's Error Code table across several extra chunks
  they shouldn't have been split across. One data-quality problem in the
  source PDF compounded into a second, structural one in our own parsing.
- **Severity**: Medium — the affected content is still present and legible
  in the resulting chunks (nothing is silently lost), just spread across a
  couple more, smaller chunks than it should be.
- **Workaround**: Added a cheap guard to `is_allcaps_heading()`: reject
  candidates that don't start with an actual letter, since these corrupted
  runs typically start with a stray digit/punctuation glyph standing in for
  the real first letter. This measurably reduced (but did not eliminate —
  a garbled run that happens to start with a real letter, e.g. "AUTO
  FILLXQGHUILOOQRILOO", still slips through) the over-fragmentation. Did
  **not** attempt to fix the underlying font/glyph corruption itself
  (e.g. via OCR or CMap-offset detection) — out of scope for this step.
- **Actionable suggestion**: A real ingestion pipeline should flag pages with
  a high proportion of non-dictionary "words" (a cheap language-model-free
  check) as candidates for an OCR fallback pass, since PDF font/ToUnicode
  corruption like this appears to not be rare across real manufacturer PDFs
  (it showed up in 2 of 5 manuals here, from two different manufacturers).

### 2026-09-23 — the corruption offset differs by manual, confirmed empirically before writing any repair code

- **Tool/SDK**: PyMuPDF span metadata (`ge-gfe28gynfs-refrigerator.pdf`,
  `lg-dlex8000w-dryer.pdf`).
- **Task attempted**: Before writing `text_repair.py`, verify the hypothesis
  that both manuals' corruption is a constant character-code offset (per the
  task's own worked example: ")LOWHU FDUWULGJH" -> "Filter cartridge" via
  +29), and check whether that offset is the same in both manuals.
- **Steps taken**: Pulled raw span text (not just `page.get_text()`, which
  hides the actual bytes) via `page.get_text("dict")`, inspected the font
  name and the literal control-character byte each corrupted run uses as its
  space substitute, then brute-force-swept offsets -40..+40 scoring
  "does this look like English" to find the true winner independently for
  each manual, rather than trusting arithmetic done by eye.
- **Expected**: Confirm or refute +29 as a shared constant.
- **Actual**: Confirmed the constant-offset hypothesis, but the offset is
  **not** shared: GE's refrigerator manual (font `ArialMT`) uses `\x03` as
  its space substitute, decoding at **+29**
  (`)LOWHU\x03FDUWULGJH` -> "Filter cartridge"); LG's dryer manual (font
  `MyriadPro-Bold`/`MyriadPro-Regular`) uses `\x01`, decoding at **+31**
  (`3FNPWF\x01UIF\x01ESZJOH\x01SBDL` -> "Remove the drying rack"). Verified
  across ~17,000 lines total, not just the two example runs: >99% of every
  actually-corrupted line in each manual lands on its manual's single
  offset, and zero false positives were found scanning the three manuals
  with no known corruption.
- **Severity**: N/A (this was the confirmation step, not friction) --
  logged because the task explicitly asked to record what this step found
  before proceeding. It directly justified per-run offset inference over
  hardcoding, which a single-manual test would have hidden.
- **Actionable suggestion**: N/A.

### 2026-09-23 — a naive "does it look like English" score kept getting fooled, three different ways

- **Tool/SDK**: `fixit_mcp.ingestion.text_repair` (this project's own code).
- **Task attempted**: Score candidate offsets by English-likelihood to pick
  the right one per run, per the task's design ("no dictionary needed --
  letter-frequency or a small common-words set is fine").
- **Steps taken**: Iteratively built and stress-tested the scorer against
  real corpus samples plus deliberately adversarial inputs (short random
  strings, text mixing clean and corrupted content in one run) before
  trusting it -- three distinct false-accepts surfaced this way, each fixed
  before moving on:
  1. **Printable-ratio-only scoring accepted consonant salad.** An early
     version scored mostly on "fraction of printable characters," which a
     wrong offset can satisfy just as well as the right one (shifted noise
     is often still printable ASCII). Fixed by switching the primary signal
     to a classical cipher-breaking technique -- average log-likelihood
     under standard English letter frequencies -- plus hard, independent
     gates (noise ratio, letter frequency, word-match count) instead of one
     blended score.
  2. **Offsets of exactly +/-32 "fixed" already-clean text by only
     toggling ASCII letter case** (`'a'`-`'A'` are 32 apart), and since
     every score here is case-insensitive, `'system'` -> `'SYSTEM'` looked
     like a legitimate competing candidate purely by relabeling. Fixed by
     requiring a competing offset to strictly *beat* the unshifted
     baseline's score, not merely pass the gates independently -- a tie
     (which is all a pure case-swap can produce) no longer counts as a win.
  3. **Adding substring word-matching (to catch corrupted runs with no
     space character at all, e.g. `pressstartbutton`) let a coincidental
     4-letter substring outscore a genuinely correct 7-letter exact word.**
     `1SPCMFN` -> `Problem` (the correct decode, offset 31) was being
     rejected because "Problem"'s average letter frequency (-3.24) fell
     just under the general threshold (-3.0) -- normal for a single 7-letter
     sample, not a sign of wrongness -- while a wrong offset's `Sureohp`
     cleared the threshold on luck and picked up 4 points from "sure" as a
     substring. Fixed by letting a strong word-match (one long exact word,
     or enough cumulative word evidence) waive the letter-frequency gate,
     since that's independent, stronger evidence than raw letter statistics
     on a short sample.
- **Severity**: Medium -- none of these ever shipped (each was caught by
  testing against real samples and adversarial cases before moving to the
  next step), but collectively they took more iteration than the repair
  logic itself, and each is a natural mistake to make with this class of
  heuristic.
- **Workaround**: See `src/fixit_mcp/ingestion/text_repair.py`'s module
  docstring and `_passes_gates`/`repair_run` for the final design; regression
  tests for all three cases are in `tests/unit/test_text_repair.py`.
- **Actionable suggestion**: When scoring "which decoding looks most like
  real English," always test against (a) already-clean input, (b) inputs
  differing only by case or another group-symmetry of your transform, and
  (c) short single-token samples -- each broke a scorer that looked correct
  on ordinary multi-word sentences.

### 2026-09-23 — repair correctly declines to touch text that mixes clean and corrupted content, at the cost of a still-fragmented chunk

- **Tool/SDK**: `fixit_mcp.ingestion.parser` + `text_repair` interaction on
  `ge-gfe28gynfs-refrigerator.pdf`, page 47.
- **Task attempted**: Get the refrigerator's dispenser "Error message -> See
  page 14" line to land inside the same table-flagged chunk as the rest of
  its "Problem / Possible Causes / What to Do" row.
- **Steps taken**: Re-ran `make parse-manuals` after wiring in text_repair
  and inspected the resulting chunks around that content.
- **Expected**: With the font corruption repaired, the whole troubleshooting
  table on that page would merge into one coherent, table-flagged chunk.
- **Actual**: Improved, but not fully: the line just before "Error message"
  is `AUTO FILL<corrupted tail with no separating space>` -- clean text
  glued directly onto a corrupted run with no space between them. Per the
  design (a wrong fix on clean text is worse than no fix), `repair_run`
  correctly refuses to touch this mixed run, since shifting it by any
  offset corrupts the clean "AUTO FILL" prefix. But the untouched, partially
  garbled line still gets misdetected as an ALL-CAPS-style heading (it
  starts with a real letter, so the earlier letter-start guard doesn't catch
  it), which splits the section right before "Error message," landing it in
  its own small, non-table-flagged chunk instead of the main table chunk.
- **Severity**: Low -- the content is present and legible (not lost), just
  in a smaller neighboring chunk rather than the main one.
- **Workaround**: None applied; documenting as a known limitation rather
  than reaching for a riskier fix (e.g. attempting to repair a suffix of a
  mixed run) that could introduce the exact "wrong fix on clean text"
  failure mode this step was designed to avoid.
- **Actionable suggestion**: A future pass could detect "clean prefix +
  corrupted suffix with no separator" runs specifically (e.g. scan for the
  first position where noise starts climbing and try repairing only the
  tail) rather than an all-or-nothing whole-line decision -- worth doing if
  this pattern turns out to be common across a larger manual corpus, not
  worth the added complexity for the two manuals seen so far.
