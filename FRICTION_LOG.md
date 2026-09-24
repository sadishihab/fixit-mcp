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

### 2026-09-23 — the "leftover" garbled short tokens were the same +31 cipher, not a separate quirk (confirmed before building)

- **Tool/SDK**: N/A (arithmetic verification), `fixit_mcp.ingestion.text_repair`.
- **Task attempted**: Before writing any token-level repair code, verify
  whether the remaining garbled short tokens on LG's Error Code table
  (`U&`, `14`, `1'`, `O1`) were the same already-confirmed +31 corruption, or
  a distinct font/glyph issue as speculated in the prior step's friction log.
- **Steps taken**: Shifted each token by +31 by hand and independently in
  Python, then checked the results against context and LG's own published
  dryer error-code terminology.
- **Expected**: Uncertain -- the prior step's friction log had flagged these
  as "a separate, still-unexplained third font quirk."
- **Actual**: Same cipher. `U&`+31 = `tE` (matches its row's cause,
  "Temperature sensor failure" -- LG's real code is `tE1`/`tE2`); `14`+31 =
  `PS`, `1'`+31 = `PF`, `O1`+31 = `nP` -- all three are genuine LG
  power-supply-fault codes, matching that row's causes exactly. They were
  never touched by whole-line repair because each sits on a line with
  already-clean English (`"or"`), so shifting the *whole* line by any offset
  would corrupt that clean word -- the noise gate correctly vetoes it, same
  root cause as the GE "AUTO FILL&lt;corrupted tail&gt;" case already logged.
- **Severity**: N/A (confirmation, not friction) -- logged because it
  directly justified building token-level repair as a real fix for a
  correctly-identified problem, rather than chasing a hypothetical unrelated
  font bug.
- **Actionable suggestion**: N/A.

### 2026-09-23 — parentheses are far too common next to real numbers to trust as a corruption signal

- **Tool/SDK**: `fixit_mcp.ingestion.text_repair.repair_line_tokens` (this
  project's own code).
- **Task attempted**: Detect a short corrupted token via "mixes letters with
  symbols like `&` `'` `(` `)` in a word position," per the task's own
  suggested signal list.
- **Steps taken**: Implemented the signal literally (all four symbols),
  then ran it against the real GE refrigerator and LG dryer manuals (not
  just the four target tokens) before trusting it.
- **Expected**: A modest number of additional genuine repairs.
- **Actual**: Dozens of false positives, all on completely ordinary text:
  unit conversions (`(35.6` next to `cm)`, from "14 in. (35.6 cm)"),
  numbered list markers (`(1)`, `(2)`), and catalog abbreviations (`(SD)`
  for "Standard Depth"). Parentheses sit directly next to digits and letters
  constantly in normal English; `&` and `'` next to a letter/digit do not
  (outside real contractions, which are excluded separately).
- **Severity**: High if shipped -- would have silently corrupted ordinary
  measurements and list markers throughout both manuals.
- **Workaround**: Dropped `(` and `)` from the strong-signal symbol set,
  keeping only `&` and `'`. Re-verified against the full corpus afterward:
  zero token repairs on the three manuals with no known corruption, and the
  false positives on the two affected manuals disappeared.
- **Actionable suggestion**: When a task specification lists example
  detection signals, test each one individually against real data before
  combining them -- "the task suggested it" isn't the same as "it's safe on
  this corpus." Symbols that are rare-next-to-alphanumerics in the *target*
  language's corruption pattern can still be common-next-to-alphanumerics in
  ordinary prose.

### 2026-09-23 — the real target tokens have a control character glued on, so "becomes pure alphabetic" was the wrong acceptance test

- **Tool/SDK**: `fixit_mcp.ingestion.text_repair._repair_token`.
- **Task attempted**: Verify token-level repair against the *actual* PDF
  content, not just the four token strings quoted in the task, before
  declaring it done.
- **Steps taken**: Ran the finished repair pass on the real LG dryer PDF and
  checked whether the "U& or U&" line in the output chunk was actually fixed.
- **Expected**: `U&` -> `tE` on both occurrences, per the already-verified
  arithmetic.
- **Actual**: Still broken. The real extracted line is
  `"U&\x12 or U&\x13"` -- LG's superscript code markers (`tE1`, `tE2`) are
  attached directly to `U&` with no space, so `\x12`/`\x13` are part of the
  *same token*. `\x12`+31 = `"1"` and `\x13`+31 = `"2"`, so the correct
  decode is `tE1`/`tE2` -- which **ends in a digit**. The acceptance rule at
  the time only accepted a shift that produced a purely alphabetic result
  (`str.isalpha()`), so it rejected the correct decode outright.
- **Severity**: Medium -- would have silently left the exact codes this step
  was built to fix still broken, while apparently "working" on every other
  test case.
- **Workaround**: Changed the acceptance test from "becomes purely
  alphabetic" to "becomes a clean alphanumeric token with no leftover
  control characters" (`str.isalnum()`), since several of this cipher's real
  targets are a short abbreviation plus a trailing digit, not pure letters.
  Added the exact `"U&\x12 or U&\x13"` line as a regression test.
- **Actionable suggestion**: Always test a fix against the literal bytes
  extracted from the source document, not a cleaned-up version of the
  example quoted in a task description -- real PDF text carries adjacent
  artifacts (here, an attached control-character digit with no separating
  space) that a hand-typed test string won't reproduce.

### 2026-09-23 — weak-signal token repair silently mangled real data-table numbers

- **Tool/SDK**: `fixit_mcp.ingestion.text_repair.repair_line_tokens` (this
  project's own code).
- **Task attempted**: The weak-signal rule added in step 2d (repair a bare
  short number when it shares a line with a strong-signal sibling) was meant
  for cases like LG's `14 or 1' or O1`. Checking it against the rest of the
  corpus surfaced a second real false-positive class beyond the parentheses
  issue already logged: GE's EPA water-quality/contaminant table has
  genuinely corrupted chemical names (`&DUEDPD]HSLQH` -> `Carbamazepine`)
  sitting on the same table row as ordinary, uncorrupted concentration
  values. The chemical name's strong signal was making its numeric row-mate
  look like a candidate too, and the shift produced another plausible-looking
  number: `86`->`US`, `5`->`R`, `24`->`OQ`, `3.`->`P.`, `80`->`UM`.
- **Severity**: High -- worse than the earlier false positives, because a
  wrong *number* that still looks like plausible data fails silently
  downstream (a wrong word is usually obviously wrong; a wrong concentration
  value is not), and this is real regulatory/certification data.
- **Fix chosen (of the three offered, in order)**: **Option 1** --
  restrict weak-signal repair to sections that look like error-code/
  troubleshooting content, reusing `looks_like_table` on the section's own
  text. This was picked over option 2 (a negative unit/measurement signal)
  because the data supported it being sufficient on its own: the EPA table's
  section is headed by a misdetected corrupted unit label (`"PJ\x12/"`,
  itself `"mg/L"` shifted) and never contains `"possible causes"`/
  `"solutions"`/`"error code"`-style wording, so `looks_like_table` already
  and correctly returns False for it -- no separate unit-detection heuristic
  needed. Verified empirically before and after: all five reported false
  positives disappear, while LG's `14`/`1'`/`O1` -- inside the section headed
  `"Installation test (Exhaust check) (cont.)"`, whose own text contains
  `"Possible Causes"`/`"Solutions"` -- still repair correctly. Strong-signal
  tokens (control characters, `&`/`'` adjacency) are still repaired
  regardless of section, since they're independent evidence on their own and
  weren't implicated in this false-positive class.
- **Also implemented (option 3), unconditionally**: `ManualChunk` now carries
  `uncertain_repairs` (original, repaired, confidence) for every token-level
  repair under 0.6 confidence in that chunk, so a downstream consumer can see
  the original text and decide for itself rather than trusting a low-
  confidence repair blindly.
- **Actionable suggestion**: A weak/ambiguous signal that only fires "in the
  company of" a strong one needs a scope for that company -- same line
  turned out to be too wide once real documents mix corrupted narrative text
  with uncorrupted tabular data on adjacent lines within one section. Scoping
  to "sections that look like the kind of content we're actually trying to
  fix" (not just "this line, or a strong-enough neighbor") is the more
  robust rule, and reused an existing heuristic rather than adding a new one.

### 2026-09-23 — two layered blockers kept the Bedrock verification step from running live

- **Tool/SDK**: `boto3`, Amazon Bedrock (`bedrock`, `bedrock-runtime`), AWS STS.
- **Task attempted**: Run `BedrockExtractor` for real against the LG dryer
  manual's chunks and show the raw extracted records, per the step's own
  instructions, before running it against all five manuals.
- **Steps taken**, in order, verifying each layer before moving to the next
  rather than guessing past it:
  1. Checked for AWS credentials before attempting a live call: no
     `~/.aws` directory, no `AWS_*` env vars, `boto3.Session().get_credentials()`
     returned `None`. Stopped and asked the user rather than fabricate a
     result -- this sandbox has no way to authenticate to AWS on its own.
  2. User supplied IAM access keys. Verified them with `sts.get_caller_identity()`
     (confirmed account + IAM user, without ever printing the secret key back)
     before doing anything else with them.
  3. Listed available Bedrock models (`bedrock.list_foundation_models`) to
     confirm the configured default (`anthropic.claude-sonnet-5`) actually
     exists and is `ACTIVE` in this account/region -- it does.
  4. Attempted one minimal real `converse()` call before running the full
     extraction, specifically to catch a permissions/access problem cheaply
     rather than discover it mid-batch.
- **Actual**: Step 4 failed: `AccessDeniedException` -- "Your account is
  currently being verified. Verification normally takes less than 2 hours."
  This is a brand-new AWS account still in Amazon's own fraud/abuse
  verification pipeline, unrelated to IAM permissions or model access
  entitlement (both of which checked out fine in steps 2-3).
- **Severity**: N/A -- an external account-state constraint neither side of
  this conversation can resolve directly, correctly surfaced rather than
  worked around by substituting stub output and presenting it as if it came
  from Bedrock.
- **Workaround**: None available immediately. `BedrockExtractor` itself was
  already fully built and verified end-to-end against a mocked
  `bedrock-runtime` client before any of this (parsing, schema validation,
  and the bounded retry path all covered by `tests/unit/test_extraction.py`,
  19 tests, zero AWS credentials required), so the code is ready the moment
  the account clears verification -- `make extract-codes MANUAL=lg-dlex8000w-dryer`
  with `FIXIT_EXTRACTOR=bedrock` is the command to run then. Proceeding with
  everything else finished and committed now, per the user's choice, rather
  than blocking further work on an AWS-side clock neither of us controls.
- **Actionable suggestion**: For a project meant to run in varied
  environments (a contributor's laptop, CI, a hackathon judge's sandbox), a
  README note on which commands need real AWS credentials+access (`make
  extract-codes` with `FIXIT_EXTRACTOR=bedrock`) versus which don't (every
  other Makefile target, including `FIXIT_EXTRACTOR=stub`) saves this exact
  back-and-forth. Separately: a cheap one-call permission/access smoke test
  (like step 4 above) before a real batch job is worth doing by default, not
  just when troubleshooting -- it turned a potentially confusing failure
  partway through a 5-manual run into a single, clear, upfront answer.

### 2026-09-23 — a working Bedrock call still needed two more account-specific fixes: bare model id, then inference profile

- **Tool/SDK**: `boto3`, Amazon Bedrock, model id `us.anthropic.claude-sonnet-4-5-20250929-v1:0`.
- **Task attempted**: Once the account's initial verification cleared, get a
  real `converse()` call working end to end before trusting a full
  extraction run to it.
- **Steps taken**: `list_foundation_models` had shown the configured default
  (a bare id, `anthropic.claude-sonnet-5`) as `ACTIVE`. A live test call with
  that id nonetheless failed. Tried several other bare ids, all failing
  differently; tried the same ids with a `us.` cross-region-inference-profile
  prefix.
- **Actual**: Two distinct, separately-diagnosed failures before success:
  1. The bare id `anthropic.claude-sonnet-5` (and `claude-fable-5`,
     `claude-fable-5-1`) returned `AccessDeniedException`: "... is not
     available for this account" -- being listed as `ACTIVE` in the region's
     catalog is not the same as this account having entitlement to it.
  2. Dated/legacy-style bare ids (`anthropic.claude-sonnet-4-5-20250929-v1:0`,
     etc.) returned a *different* error: `ValidationException`, "Invocation
     of model ID ... with on-demand throughput isn't supported. Retry your
     request with the ID or ARN of an inference profile." Prefixing the same
     id with `us.` (a cross-region inference profile id) fixed this one
     immediately -- and even then, one specific model (`us.anthropic.claude-sonnet-4-20250514-v1:0`)
     still failed as "marked by provider as Legacy," a third distinct
     failure mode.
  A `us.`-prefixed, non-legacy, dated model
  (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`) finally worked.
- **Severity**: Medium -- three visually-similar-looking model-access errors
  in a row, each requiring a different fix, would be easy to misdiagnose as
  "still broken" rather than "broken for three different reasons in
  sequence" without reading each error message closely.
- **Workaround**: Set the project default to the verified-working
  `us.anthropic.claude-sonnet-4-5-20250929-v1:0` and documented the three
  distinct failure modes directly in `ExtractionSettings.bedrock_model_id`'s
  comment, so the next person who hits one of them recognizes it immediately
  instead of re-diagnosing from scratch.
- **Actionable suggestion**: Bedrock's model-access error messages are
  already fairly clear individually, but there's no single command that
  answers "which model ids can I actually invoke, in what form, right now" --
  `list_foundation_models` shows catalog status, not per-account invoke
  entitlement or the on-demand-vs-inference-profile requirement. A
  `bedrock list-invokable-models` (bare ids and inference-profile ids both
  checked) would have turned three round-trips into one.

### 2026-09-23 — guessed Bedrock pricing understated real cost by ~3x

- **Tool/SDK**: `scripts/extract_codes.py` (this project's own code).
- **Task attempted**: Report real token usage and an accurate estimated cost
  for the LG dryer extraction run, per the task's explicit ask.
- **Steps taken**: The cost estimate constants
  (`ESTIMATED_INPUT_COST_PER_1K`/`ESTIMATED_OUTPUT_COST_PER_1K`) were set from
  memory as "approximate Sonnet-class pricing" ($0.003/$0.015 per 1K) when
  `BedrockExtractor` was first built, before a model was ever actually
  invoked. Looked up real, current Bedrock on-demand pricing for the model
  actually used (`claude-sonnet-4-5`) before reporting a cost figure to the
  user, rather than trusting the unverified guess.
- **Actual**: Real pricing is $9.00 / $45.00 per 1M input/output tokens
  ($0.009 / $0.045 per 1K) -- exactly 3x the guessed figures for both input
  and output. The run's real cost was **$0.1054** (6,581 input + 1,026
  output tokens), not the $0.0351 the unverified constants would have
  reported.
- **Severity**: Medium -- a systematically-wrong cost estimate is worse than
  an obviously-missing one, since it looks trustworthy while quietly being
  wrong every time, and would compound directly with usage across a full
  five-manual run or repeated re-runs.
- **Workaround**: Corrected both constants and cited the source pricing and
  verification date directly in the code comment, so a future model change
  is a visible prompt to re-verify rather than a silent staleness risk.
- **Actionable suggestion**: Never ship a cost estimate based on
  from-memory pricing recall for a fast-moving, frequently-repriced API
  surface -- verify against a current source at the moment the number is
  first going to be shown to someone making a real spending decision, not
  just at implementation time.

### 2026-09-23 — the extraction cache was keyed only by chunk content, not by which extractor produced it

- **Tool/SDK**: `scripts/extract_codes.py` (this project's own code).
- **Task attempted**: Run `BedrockExtractor` on the four manuals that had
  previously only been run through `StubExtractor` (during the earlier
  pipeline smoke test), without re-paying for the LG dryer manual already
  verified.
- **Steps taken**: Noticed before running anything: `chunk_cache_key()`
  hashed only `chunk.text`, with no reference to which extractor (or model)
  produced the cached result.
- **Expected**: N/A -- caught by inspection before it caused a real problem.
- **Actual**: Running `FIXIT_EXTRACTOR=bedrock` without `--force` on the four
  remaining manuals would have silently hit the *stub* extractor's cached
  results for every one of their already-considered chunks (populated during
  the very first `FIXIT_EXTRACTOR=stub` run), since the cache had no way to
  tell "this chunk's result came from a regex match, not a real model call."
  The run would have reported "0 sent, N cache hits" and produced the stub's
  code-only records while claiming to be a Bedrock run -- wrong in a way
  that wouldn't have been obvious from the output alone.
- **Severity**: High if shipped -- a silently-wrong data source is worse
  than an obviously-missing one, and this exact scenario (switching
  extractors on a corpus already processed by the other one) is precisely
  what step 3a's own design -- try stub first, then Bedrock -- guarantees
  will happen on every real use of this tool.
- **Workaround**: Fixed properly rather than patched around with `--force`:
  `chunk_cache_key()` now hashes `extractor_tag + chunk.text` together
  (`extractor_tag()` returns `"stub"` or `f"bedrock:{model_id}"`), so
  switching extractors or models always misses the cache and re-extracts for
  real, while re-running the *same* extractor+model on unchanged text still
  costs nothing. Verified directly: the four-manual Bedrock run reported
  "0 cache hits" for every manual except two chunks with byte-identical text
  processed twice within the same run (legitimate same-run dedup, not stale
  cross-extractor reuse).
- **Actionable suggestion**: Any cache keyed by "content hash" alone is
  implicitly claiming the *function* that produced the cached value is
  fixed. The moment that function becomes configurable (a different
  extractor, a different model, a different prompt version), the function's
  identity has to be part of the key too -- worth a standing checklist item
  for any content-hash cache added to this project going forward (the
  chunk-cache-key pattern also appears in `scripts/fetch_manuals.py` and
  should be checked if that ever becomes configurable).

### 2026-09-23 — chunk overlap produced two records for the same code, one incomplete

- **Tool/SDK**: `fixit_mcp.ingestion.extraction.BedrockExtractor` interacting
  with `fixit_mcp.ingestion.parser`'s chunk-overlap design (step 2b).
- **Task attempted**: Verify every field of the Bosch dishwasher's 13
  extracted records traces to source text, per the user's explicit accuracy
  check.
- **Steps taken**: Compared each record against its `source_chunk_id`'s
  exact text. `E:34-00` appeared as *two* separate records.
- **Actual**: Both are faithful to their own chunk, but incomplete/complete
  differently: `E:34-00`'s entry falls right at the boundary between
  `chunk-0276` and `chunk-0277`. Chunk 276 ends mid-entry (captures only
  "Water is continuously running into the appliance. / 1. Turn off the water
  faucet.", cutting off before step 2), so that record's `repair_steps` has
  only one step (confidence 0.95). Chunk 277 starts with the same entry
  reproduced via chunking's 200-char overlap (which exists precisely so
  context isn't lost at a boundary) and *does* include step 2 ("Call
  customer service"), so that record is complete (confidence 1.0). Neither
  record is wrong -- each is a correct read of what its chunk actually
  contains -- but the same code now has two entries in
  `data/index/error_codes.json`, one strictly worse than the other.
- **Severity**: Medium -- not a fabrication (the explicit thing this step
  was checking for), but a real completeness/dedup gap: a lookup by
  `code_normalized` today would need to pick between two candidates, and
  naively picking the first would sometimes get the incomplete one.
- **Workaround**: None applied this step -- documenting rather than
  reaching for a fix under time pressure, since the right fix depends on
  what a future lookup tool actually needs (merge by normalized code and
  keep the highest-confidence/most-complete record? keep both and let the
  caller decide? re-chunk with code-table rows never split at all?).
- **Actionable suggestion**: A future step should deduplicate
  `data/index/error_codes.json` by `(manual_id, code_normalized)`, preferring
  the record with more populated fields and/or higher
  `extraction_confidence` -- this is exactly the kind of chunk-boundary
  artifact that's invisible until you look at a real multi-page code table
  with overlap enabled, which single-chunk unit tests can't surface.

### 2026-09-23 — the record schema needed by both sides lived on the wrong side of the offline/online boundary

- **Tool/SDK**: `fixit_mcp.ingestion.extraction`, `fixit_mcp.retrieval.codes` (this
  project's own code).
- **Task attempted**: Load `data/index/error_codes.json` into memory at server
  startup (step 3b), which needs to `pydantic.model_validate()` each row back
  into `ErrorCodeRecord`.
- **Steps taken**: Went to import `ErrorCodeRecord`/`normalize_code` for the
  new `fixit_mcp.retrieval.codes` module and found both defined in
  `fixit_mcp.ingestion.extraction` -- which `CLAUDE.md` explicitly documents
  as "offline tooling only, never imported by the running server."
- **Expected**: N/A -- this was step 3a's own design, written before a
  server-side consumer existed, so the conflict wasn't visible until step 3b
  actually tried to be that consumer.
- **Actual**: Importing from `ingestion` would violate the project's own
  standing architecture rule the moment the running server needed the same
  schema `extraction.py` already defined -- two legitimate owners for one
  type, on the wrong side of a boundary that's supposed to be one-directional
  (offline -> committed JSON -> online, never online -> offline module).
- **Severity**: Medium -- caught before writing any server code that would
  have depended on the bad import, not shipped and then found by lint/tests.
- **Workaround**: Moved `ErrorCodeRecord` and `normalize_code` into
  `fixit_mcp.domain.models` (the existing neutral layer already shared by
  both `Appliance`/`ApplianceList`), and had `fixit_mcp.ingestion.extraction`
  re-export both via `__all__` so step 3a's existing tests and call sites
  keep working unchanged. The running server now only ever imports from
  `domain`, never `ingestion`.
- **Actionable suggestion**: When a step defines a schema that a *future*
  step's other side of an architectural boundary will obviously also need
  (here: any record written to a committed JSON artifact will eventually be
  read back by something), put it in the neutral/domain layer from the
  start, even if only one side uses it yet -- moving it later is cheap, but
  only if the conflict is caught before other code (or tests) accumulate on
  the wrong side of it.

### 2026-09-23 — a manual's own generic/range placeholder gets extracted as if it were one real code

- **Tool/SDK**: `fixit_mcp.ingestion.extraction.BedrockExtractor`.
- **Task attempted**: Understand why `ge-jbp26-range` (the GE range, whose
  manual only ever describes error codes generically, see step 2b's
  friction log) went from 0 codes found (stub) to 1 (Bedrock), and whether
  that 1 is real.
- **Actual**: The extracted `error_code` is the literal string `"F— and a
  number or letter"` -- the manual's own placeholder description ("'F— and a
  number or letter' flash in the display... you have a function error
  code"), not an instantiated code like `"F1"`. Bosch's dishwasher manual has
  the same pattern for its catch-all case: `error_code: "E:01-00 to
  E:90-10"`, a *range*, not a single code. Both are faithful, verbatim
  transcriptions of what the manual actually prints as the identifying label
  for that troubleshooting entry -- not fabricated -- but `code_normalized`
  for both is a long, non-lookup-able mangled string
  (`FANDANUMBERORLETTER`, `E0100TOE9010`), so neither is usable the way a
  real `code_normalized` match (`E2060`, `TE1`) is.
- **Severity**: Low -- correctly follows the "preserve the manufacturer's
  exact spelling" instruction to its logical conclusion; the manual itself
  never gives GE range owners a concrete code to look up, so there's no more
  specific truth to extract. Worth knowing about, not a bug to fix.
- **Workaround**: None needed -- flagging for awareness rather than changing
  behavior, since inventing a fake instantiated code family (e.g.
  synthesizing `"F1"`..`"F9"` records) would be exactly the kind of guess
  this project's design explicitly forbids.
- **Actionable suggestion**: A future consumer of `error_codes.json` that
  does exact-match lookup on `code_normalized` should treat a very long
  normalized value (or one containing common English words once stripped of
  punctuation) as a signal that this is a described range/pattern rather
  than a literal code, and fall back to full-text search or a "call service,
  the manual doesn't give a specific code for this" response instead of a
  failed lookup.

### 2026-09-23 — my own illustrative docstring example wasn't real corpus data, and I almost demoed it as if it were

- **Tool/SDK**: N/A (self-caught during manual verification of `diagnose_error`).
- **Task attempted**: Demonstrate the `diagnose_error` tool's normalization +
  Bosch-match behavior using the code `"E24"`, per the step's own requested
  demo list.
- **Steps taken**: Called `diagnose_error(error_code="E24")` against the real
  running server with the real committed index, expecting a Bosch match,
  before reporting results.
- **Expected**: A found result, matching a real Bosch code.
- **Actual**: `not_found`. `"E24"`/`"E:24-00"` was never real data -- it's an
  example I wrote myself in `ErrorCodeRecord`'s docstring back in step 3a/3b
  to illustrate the *format* of a real-looking code, and it doesn't
  correspond to anything actually extracted from a manual. The real Bosch
  codes in the committed index are E:20-60, E:30-00, E:31-00, E:32-00,
  E:34-00, E:61-02, E:61-03, E:90-01, E:92-40. This is correct tool behavior
  (never inventing a match), but reporting it without explanation would have
  looked like the tool failed the requested demo rather than that the demo
  request itself referenced a code that was never real.
- **Severity**: Low -- caught before reporting to the user, by actually
  running the demo rather than assuming a hand-written docstring example was
  interchangeable with real corpus data.
- **Workaround**: Reported the honest `not_found` result for `"E24"` as
  requested, and additionally ran `"e20 60"` (a real Bosch code, in its
  natural-language-ish spoken form) to actually demonstrate normalization +
  a real Bosch match, flagging the discrepancy explicitly rather than
  silently substituting one for the other.
- **Actionable suggestion**: A schema docstring's illustrative example should
  be visibly fake (e.g. `"E:XX-00"` or a clearly-invented brand) rather than
  a plausible-looking real code format, specifically so it can never later
  be mistaken for -- or accidentally used as -- a real test/demo value once
  actual corpus data exists.

### 2026-09-24 — a read-only repository's "safe" default seed became a shared-mutable-state bug the moment writes were added

- **Tool/SDK**: `fixit_mcp.repository.in_memory.InMemoryApplianceRepository`
  (this project's own code, written in step 1, modified in step 3c).
- **Task attempted**: Add `add()`/`remove()` to `InMemoryApplianceRepository`
  for step 3c (household appliances are now mutable, persistent state).
- **Steps taken**: Before writing the new methods, re-read the existing
  `__init__`: `self._data = seed if seed is not None else _SEED_DATA` --
  aliasing the module-level `_SEED_DATA` dict directly (not copying it) when
  no seed is given. This was harmless in steps 1-3b, since every existing
  method only ever read `self._data`. Wrote a test
  (`test_default_seed_is_not_mutated_by_add_on_one_instance`) before trusting
  the new `add()` method, specifically to check this.
- **Expected**: N/A -- written defensively, expecting to catch a real bug.
- **Actual**: Confirmed the bug the test was written to catch: two separate
  `InMemoryApplianceRepository()` instances (e.g., two different tests, or
  two requests in the same process) built with no explicit seed would have
  shared the *same* underlying lists once any instance called `add()` or
  `remove()` -- one test adding an appliance would silently leak it into
  every other test's "fresh" default repository for the rest of the test
  session.
- **Severity**: High if shipped -- a classic mutable-default-object bug that
  is invisible in a read-only repository and only becomes a real, silent
  cross-test/cross-request data leak the moment write methods are added,
  exactly what step 3c does.
- **Workaround**: Fixed at the root: `__init__` now always builds a fresh
  per-instance copy (`{h: list(apps) for h, apps in source.items()}`) from
  whichever source dict is used (custom seed or the module-level default,
  now named `DEFAULT_SEED`), so no two instances -- and no instance and the
  module constant -- ever share a mutable list.
- **Actionable suggestion**: Any class that accepts "a mutable object, or a
  module-level default if none is given" in its constructor should audit
  that default for aliasing the moment the class gains its first mutating
  method -- a pattern that's completely safe in a read-only class becomes a
  shared-state bug retroactively, with no change to the constructor itself
  needed to trigger it.

### 2026-09-24 — the task's own framing of MCP Apps ("returns a resourceUri", "no client-side") doesn't match the current spec

- **Tool/SDK**: `modelcontextprotocol/ext-apps` specification
  (`specification/2026-01-26/apps.mdx`), the current MCP Apps spec.
- **Task attempted**: Add a visual card to `diagnose_error` per the step's
  own description: "when diagnose_error finds a result, it also returns a
  resourceUri... static HTML/SVG templated from DiagnoseErrorResult
  fields... no client-side fetching."
- **Steps taken**: Per the step's own explicit instruction to confirm before
  building, fetched and read the actual current spec (github.com/
  modelcontextprotocol/ext-apps), the hosted API docs
  (apps.extensions.modelcontextprotocol.io), and Alexa+'s own MCP Toolkit
  docs, rather than building from the task's paraphrase of them.
- **Expected**: A tool result can carry its own `resourceUri`, chosen
  per-call, with the resource itself pre-rendered server-side from that
  call's data and no JS involved -- matching the task's plain-English
  description.
- **Actual**: Two mismatches, confirmed directly against spec text: (1)
  `_meta.ui.resourceUri` is defined only on the **Tool definition** (visible
  in `tools/list`, one shared template per tool) -- the spec has no UI
  metadata field on `CallToolResult` at all, so a resource can't be
  attached-or-omitted per individual call the way "only on found" implies.
  (2) The spec's canonical rendering lifecycle requires the UI resource's own
  small JS to act as an MCP client over `postMessage` (`ui/initialize`, then
  react to the host's pushed `ui/notifications/tool-result`) specifically
  *because* the same resource is shared across every call and needs some way
  to learn which call's data to show -- a fully static, zero-JS,
  pre-rendered-per-call resource isn't a documented pattern any current host
  (Claude Desktop, VS Code Copilot, etc.) is built to look for.
- **Severity**: Medium -- would have shipped a card that renders fine in our
  own bespoke test harness but not in any real MCP Apps host, silently
  failing the actual goal (Alexa+/Claude Desktop showing a visual) while
  looking correct in isolation.
- **Workaround**: Stopped and presented both the spec-conformant design and
  the literal-but-non-conformant one to the user via a direct question
  before writing any implementation, per the task's own "tell me before
  building around a guess" instruction. User chose spec-conformant. Built:
  one static `ui://fixit-mcp/diagnose-error-card` resource declared via
  `@mcp.tool(..., meta={"ui": {"resourceUri": ...}})`, containing the spec's
  postMessage handshake plus a pure, DOM-free `buildCardHtml(result)`
  function; "only render on found" is implemented *inside* that function
  (returns `""` for any other status) rather than by conditionally attaching
  metadata to the call result, since the latter isn't how the mechanism
  works.
- **Actionable suggestion**: A fast-moving extension spec (this one changed
  its own dated version, `2025-11-21` draft blog post to a `2026-01-26`
  specification) is exactly the case where a task description's plain-English
  paraphrase of "how it works" is most likely to already be stale or
  simplified -- worth fetching the actual current spec directly before
  writing code every time one of these comes up, even when the paraphrase
  sounds precise and actionable on its own.

### 2026-09-24 — testing a template's JS logic without adding a JS test framework to a Python project

- **Tool/SDK**: `tests/unit/test_diagnose_card.py`, Node.js (already an
  implicit project dependency via `make inspector`'s `npx`).
- **Task attempted**: Unit-test `diagnose_card.html`'s rendering logic
  (which fields show, numbered steps, safety-warning styling, XSS escaping,
  "nothing renders for non-found statuses") without either (a) trusting a
  Python reimplementation of the same logic to stay in sync with the actual
  shipped JS, or (b) pulling in a browser-automation/jsdom dependency for
  one small template.
- **Steps taken**: Designed `buildCardHtml(result)` to be pure and DOM-free
  from the start (no `document`, no `postMessage` inside it -- those live
  only in the surrounding handshake code) specifically so it can run in a
  plain `node -e` subprocess with no browser context at all. Verified `node`
  is already implicitly expected by this repo (the Makefile's `inspector`
  target requires `npx`) before relying on it further.
- **Actual**: Works cleanly -- tests extract just the pure part of the
  `<script>` block via a string split on a marker comment
  (`// MCP Apps handshake`), append a `console.log(buildCardHtml(<fixture>))`
  call, and run it via `subprocess.run([node, "-e", js])`, asserting on
  stdout. This exercises the literal bytes shipped in the resource, not a
  parallel Python copy of the rendering rules.
- **Severity**: Low -- resolved cleanly, logging the pattern rather than a
  real problem.
- **Workaround**: Guarded every such test with
  `@pytest.mark.skipif(shutil.which("node") is None, ...)` so `make test`
  still passes cleanly (skips, doesn't fail) on a machine without Node --
  the static-file/string-content tests in the same file (valid HTML5, `ui://`
  scheme, no `fetch(`) still run unconditionally and don't need it.
- **Actionable suggestion**: When a Python project's server ships a small
  amount of embedded client-side JS (a UI template, a script tag), prefer
  writing that JS's core logic as a pure, dependency-free function and
  testing it by literally executing it in the runtime it's shipped for
  (Node, here) rather than either skipping real coverage of it or
  reimplementing its logic a second time in Python to test in isolation --
  the reimplementation is the more common choice but is exactly the kind of
  thing that silently drifts from the real behavior over time.

### 2026-09-24 — a user assumption about the spec ("cards can't invoke tools") turned out to be wrong, and confirming that reopened a scope question

- **Tool/SDK**: `modelcontextprotocol/ext-apps` specification (same version
  as the prior MCP Apps entry above).
- **Task attempted**: Add non-blank, purely-informational visual states for
  `not_found`/`ambiguous_appliance` to the `diagnose_error` card, per an
  explicit instruction to first confirm whether a card can invoke a tool
  call back through the host before assuming it can't, and to keep the new
  states non-interactive only if that turned out to be unsupported.
- **Steps taken**: Fetched the raw current spec and searched specifically
  for the View -> Host message list, rather than assuming the premise ("MCP
  Apps cards can't trigger tool calls") stated in the request was correct.
- **Expected**: Uncertain going in -- this was the explicit point of
  checking rather than building on the stated assumption.
- **Actual**: The premise was wrong: `tools/call` is explicitly listed among
  the standard MCP messages a view is allowed to send to the host ("Execute
  a tool on the MCP server"), gated only by host discretion ("the Host...
  MAY decide to block some messages or subject them to further user
  approval"). This meant the original conditional instruction ("no click
  handlers unless the spec supports it") no longer had a settled answer --
  it *is* supported, which reopened whether to build it.
- **Severity**: N/A -- not a bug, a case where confirming a stated
  assumption before building surfaced that the assumption itself was false,
  which changed what decision was actually being made.
- **Workaround**: Rather than picking a side of a now-open scope question
  unilaterally, reported the corrected fact and asked directly. User chose
  to keep both new states purely informational. Reasoning offered for that
  default (and accepted): no real host's approval-UX for view-initiated tool
  calls has been verified against this server, view-initiated calls are a
  first-of-its-kind pattern with no other precedent in this codebase, and
  the step's own scope was "minimal, clearly-different states," not
  reactive UI.
- **Actionable suggestion**: When a task frames a build decision as
  conditional on a fact ("do X unless the spec says Y"), verify the fact
  independently before treating the condition as settled -- a user's
  paraphrase of a spec can be wrong in either direction (stricter or looser
  than reality), and discovering it's wrong doesn't resolve the underlying
  decision, it just means the decision still needs to be made with correct
  information instead of skipped.

### 2026-09-24 — AgentCore's recommended deploy path changed since step 1, and its "custom container" guide describes the wrong contract for MCP servers

- **Tool/SDK**: Amazon Bedrock AgentCore Runtime docs
  (docs.aws.amazon.com/bedrock-agentcore: `runtime-mcp.html`,
  `runtime-mcp-protocol-contract.html`, `getting-started-custom.html`),
  `aws/agentcore-cli` (`docs/container-builds.md`).
- **Task attempted**: Before containerizing (step 4a), re-check the AgentCore
  Runtime MCP container contract and the currently recommended deployment
  method against what step 1 recorded (CLAUDE.md rules 5–6).
- **Steps taken**: Read the MCP deploy guide, the MCP protocol contract, the
  session and filesystem docs, the "get started without the CLI" guide, and
  the AgentCore CLI's container-build doc.
- **Expected**: Same contract as step 1. Deployment either through the
  Python starter toolkit (`agentcore configure`/`launch`) or through
  hand-written CDK.
- **Actual**:
  - **Contract: unchanged.** ARM64, `0.0.0.0:8000`, `POST /mcp`, and
    `stateless_http=True` is still the recommended default. The platform
    injects its own `Mcp-Session-Id`, which a stateless server must accept.
    New since step 1: stateful MCP mode is now supported (Mar 2026) but not
    needed here. Once clients move to MCP `2026-07-28`, elicitation and
    sampling use MRTR and don't require stateful mode either.
  - **Tooling: changed.** The AgentCore CLI is now an npm package
    (`npm install -g @aws/agentcore`: `agentcore create`/`add agent
    --protocol MCP`/`deploy`). `deploy` synthesizes **CDK** under the hood
    (`agentcore/cdk/`, driven by `agentcore/agentcore.json`). The default
    build is CodeZip (an S3 upload, no container). A `"build": "Container"`
    agent can use a fully custom Dockerfile, built remotely by CodeBuild. The
    CLI caps images at 1 GB for local packaging and 2 GB for CodeBuild. Its
    generated images run as non-root UID 1000, which this repo's image
    matches.
  - The **"Get started without the AgentCore CLI"** page (the natural
    starting point for bringing your own Dockerfile) documents only the
    *HTTP*-protocol contract: `/invocations` + `/ping` on port **8080**.
    Nothing on the page says this doesn't apply to MCP-protocol runtimes,
    which use `/mcp` on **8000** and need no `/ping`. Following that page
    for an MCP server would produce a container AgentCore can't talk to.
- **Severity**: Medium. Nothing broke, but the "custom container" guide is
  actively misleading for MCP, and "which deploy tool" now has a different
  answer than step 1's research.
- **Workaround**: Built against the MCP protocol contract page only.
  `tests/unit/test_dockerfile.py` pins host/port/path to that contract.
  Step 4b decides between the AgentCore CLI (Container build pointing at
  this Dockerfile) and hand-written CDK.
- **Actionable suggestion**: AWS should add a protocol note to
  `getting-started-custom.html` ("this contract is for `--protocol HTTP`;
  MCP runtimes serve `/mcp` on 8000, see the MCP protocol contract") and
  link each protocol's contract from it.

### 2026-09-24 — arm64 image under QEMU on an x86_64 host: silent emulation gap, then a 10x latency distortion

- **Tool/SDK**: Docker Engine 29.7 (Linux, x86_64 host, no Docker Desktop
  or Finch), buildx, `tonistiigi/binfmt`.
- **Task attempted**: Build and run the `linux/arm64` image locally and
  confirm it passes the same smoke checks as the dev server, including the
  p95 latency budget.
- **Steps taken**: `docker run --platform linux/arm64 alpine uname -m`
  printed `exec format error`: plain Docker Engine on Linux ships no QEMU
  handlers, unlike Docker Desktop. Registered them with
  `docker run --privileged --rm tonistiigi/binfmt --install arm64`, then
  built and ran the image. Ran `scripts/smoke_test.py` against it.
- **Expected**: All checks pass, latency included. The handler itself is a
  ~1ms in-memory lookup.
- **Actual**: Every functional check passed, but `diagnose_error`'s p95
  round trip was **656ms**, over the 500ms Alexa+ budget. The container's own
  structlog line still said `latency_ms: 1.43`, so the time went to the
  emulated SDK/ASGI/pydantic stack around the handler. Building the *same
  Dockerfile* natively for `linux/amd64` gave **58.9ms**, matching the dev
  server's **55.2ms**. That confirms the gap is QEMU, not the image. Cold
  start under emulation was also ~30s.
- **Severity**: Medium. This would have been a false alarm about the 500ms
  budget, or worse, a "fix" to code that wasn't slow.
- **Workaround**: `scripts/smoke_test.py --skip-latency`. `make
  docker-smoke` passes it automatically when `DOCKER_PLATFORM` differs from
  the host arch, and `tests/integration/test_container.py` skips the check
  when the image arch differs from the host arch. Real latency is measured
  natively (dev server, or an amd64 build) and must be re-measured on
  Graviton after deployment (step 4b).
- **Actionable suggestion**: When emulating the target arch, never read
  latency numbers from the emulated run. Compare the handler's own logged
  latency with the round trip first. A large gap means you're measuring the
  emulator.

### 2026-09-24 — data paths resolved via `Path(__file__).parents[N]` only work from an editable install

- **Tool/SDK**: `uv sync` (0.12.18), uv_build, this repo's
  `fixit_mcp.config` / `catalog.manifest` / `retrieval.codes`.
- **Task attempted**: A minimal, dev-dependency-free runtime image.
- **Steps taken**: Before writing the Dockerfile, grepped `src/` for how the
  server finds `data/` at startup.
- **Expected**: Data paths configurable, or package-relative.
- **Actual**: Three modules locate `data/` as
  `Path(__file__).resolve().parents[2 or 3]`, which is the repo root *only*
  when the package runs from `src/`. The usual container idiom (`uv sync
  --no-editable`, then copy just `.venv`) would point them at
  `.venv/lib/python3.12/`. Missing index: `load_index()` raises, which is
  loud and fine. Missing manifest: `load_manual_catalog()` **silently returns
  an empty catalog**, so the container would start cleanly and then have
  `add_appliance` report "no manual on file" for every model.
- **Severity**: Medium. Invisible at startup, wrong at request time.
- **Workaround**: Kept the default editable install and copied `src/`
  alongside `.venv`, so `/app/src/fixit_mcp/...` resolves `data/` to
  `/app/data`, with no code change. Guarded three ways:
  `tests/unit/test_dockerfile.py` asserts every startup data file is COPYed
  in and not `.dockerignore`d, and that `--no-editable` isn't used. The smoke
  script's `add_appliance` check asserts `manual_linked is True`, which is
  exactly what the silent failure would break.
- **Actionable suggestion**: Worth a follow-up: an explicit
  `FIXIT_DATA_DIR` setting, and making `load_manual_catalog()` fail loudly
  at startup on a missing manifest (it's committed, so absence is always a
  packaging bug). Not done here, to keep this step to "containerize without
  changing server behavior."

### 2026-09-24 — OPEN DECISION: the SQLite household store isn't durable, or even shared, on AgentCore Runtime

- **Tool/SDK**: AgentCore Runtime sessions (`runtime-sessions.html`) and
  filesystem configurations (`runtime-filesystem-configurations.html`),
  `fixit_mcp.repository.sqlite`.
- **Task attempted**: Work out what the step-3c SQLite store
  (`data/state/appliances.db`) does inside the container, locally and on
  AgentCore.
- **Steps taken**: Locally, added an appliance, then (a) restarted the
  container, (b) removed it and ran a fresh one from the image, and (c)
  repeated (b) with a named volume at `/app/data/state`. Now pinned by
  `tests/integration/test_container.py`. Read AgentCore's session and
  filesystem docs.
- **Expected**: Some durability gap on AgentCore across restarts.
- **Actual**: Locally: (a) persisted, (b) **lost**, (c) persisted. On
  AgentCore, *every new session* is case (b). Each runtime session gets its
  own dedicated microVM, and local disk is ephemeral: gone after 15 min idle
  (default), 8 h max lifetime, or on redeploy. The problem is worse than
  "not durable across restarts". The store **isn't shared across sessions**
  either, so an appliance a customer adds in one Alexa+ conversation is
  invisible in the next one. Each fresh microVM also re-seeds the demo
  households, which hides the problem in a demo that only uses seed data.
  The storage options AgentCore now offers don't fix this as-is:
  - *Managed session storage* (Preview, `/mnt/<name>`, no VPC) persists
    across stop/resume but is **isolated per session** and **wiped on every
    runtime version update**. That's the same sharing problem, and it
    resets on each deploy.
  - *EFS / S3 Files access points* are shared across sessions but need VPC
    mode, NFS security groups, and mount targets. More importantly, SQLite
    in **WAL mode (which this repo uses) is unsafe over NFS**: WAL relies on
    shared memory on one host, and here multiple microVMs would write
    concurrently.
- **Severity**: High for real deployment. It breaks the "remembers which
  appliances a household owns" feature outright. Harmless for local and
  container testing.
- **Workaround**: None applied. **This is an explicit decision for step 4b,
  not something to patch silently.** Options, roughly in order of fit:
  (1) implement the `ApplianceRepository` interface on **AgentCore Memory**,
  already the stated production target in CLAUDE.md (check its read
  latency against the 500ms budget first);
  (2) DynamoDB behind the same interface (single-digit-ms reads,
  serverless, no VPC);
  (3) ship to AgentCore with the SQLite backend as a knowingly-ephemeral
  demo store, which is acceptable only if the demo never relies on data
  added in an earlier session.
  `FIXIT_SQLITE_PATH` already lets the path move to a mount if (3) is chosen.
- **Actionable suggestion**: For any MCP server bound for AgentCore
  Runtime, treat local disk as per-conversation scratch space from day one,
  since sessions map to microVMs. Anything that must outlive one
  conversation belongs in an external store behind a repository interface.
  The runtime docs could say "per-session" more prominently in the MCP
  guide itself, not only in the sessions page.

### 2026-09-24 — AgentCore Memory is designed around conversations; using it as a household record store means choosing between two imperfect models

- **Tool/SDK**: Amazon Bedrock AgentCore Memory (data plane
  `bedrock-agentcore` 2024-02-28, boto3 1.43.100), docs at
  docs.aws.amazon.com/bedrock-agentcore (memory types, short-term API,
  `CreateMemory`, `BatchCreateMemoryRecords`, `ListMemoryRecords`, quotas).
- **Task attempted**: Replace the per-microVM SQLite store (step 4a's open
  decision) with AgentCore Memory, behind the unchanged
  `ApplianceRepository` interface: exact-key list/add/remove of a
  household's appliances, well inside the 500ms tool budget.
- **Steps taken**: Read the memory type, short-term event, and long-term
  record docs plus the API references and the quotas page. Inspected the
  installed boto3 service model directly to see what the shipping SDK
  actually supports.
- **Expected**: A durable per-user key/value or document store with an
  "agent memory" layer on top.
- **Actual**: Two storage models, each a partial fit:
  - **Short-term events** (`CreateEvent`/`ListEvents`/`DeleteEvent`): exact
    reads by (actorId, sessionId), 200 TPS account quotas for create and
    list, and a structured `json` payload type in current boto3, which the
    devguide doesn't mention. But **every event expires**:
    `eventExpiryDuration` is a *required* field capped at **365 days**, with
    no "never" option. The API reference says the minimum is 3 days; the
    quotas page says 7. Events are also immutable, so there's no update,
    only delete and re-create.
  - **Long-term records** (`BatchCreateMemoryRecords`, written directly
    with no LLM extraction): no documented expiry. But they're designed
    for semantic retrieval. `ListMemoryRecords` filters by namespace
    **prefix** (`households/house-1` also matches `house-10` unless every
    namespace ends in `/`), the list quota is **30 TPS account-wide**, and
    the docs don't say how soon a written record becomes listable.
- **Severity**: Medium. Neither model is wrong, but the obvious "just use
  Memory" leads either to silent data expiry or to a search index used as
  a database.
- **Workaround**: Chose **short-term events**. Deterministic, exact-key,
  higher quotas, and the path where read-after-write can be checked
  directly (the live test does). Mapping: actorId = household_id, one
  fixed registry session, one event per appliance, appliance_id in event
  metadata. `extractionMode="SKIP"` keeps the store free of LLM
  extraction. The memory is created with 365-day expiry and no strategies.
  **The 365-day expiry is accepted and documented, not solved.** An
  appliance registered and never touched again disappears after a year.
  Fine for a hackathon demo, not for production; a production fix is
  either periodic re-writes of old events or DynamoDB behind the same
  interface.
- **Actionable suggestion**: AWS could offer a non-expiring event option
  (or document long-term records as a first-class direct-write store with
  exact-match reads and stated consistency). It should also reconcile the
  3-vs-7-day minimum between the API reference and the quotas page, and
  document the `json` payload type in the devguide, not only the SDK model.

### 2026-09-24 — AgentCore Memory silently ignores a repeated clientToken, which would have made demo resets silently no-op

- **Tool/SDK**: AgentCore Memory `CreateEvent` (`clientToken`).
- **Task attempted**: Make `add()` safe to retry (boto3 retries throttled
  and 5xx calls automatically).
- **Steps taken**: First draft derived the token from the data:
  `clientToken=f"{household_id}:{appliance_id}"`. Then re-read the
  parameter doc: "If this token matches a previous request, AgentCore
  ignores the request, but does not return an error."
- **Expected**: Idempotency tokens scoped to one logical request.
- **Actual**: A data-derived token also dedupes *future, legitimate*
  requests. Remove `app-001` from house-001, then re-add it (exactly what
  `make seed-agentcore RESET=1` does), and the re-add returns success
  while writing nothing. The appliance silently stays gone. No error to
  catch, and a unit test with a naive fake would never see it.
- **Severity**: Medium. Caught before it ever ran, but it's a silent
  data-loss shape.
- **Workaround**: Fresh `uuid4` token per `add()` call. boto3 resends the
  same kwargs on its own retries, so those stay idempotent, while distinct
  calls never collide. `FakeAgentCoreMemoryClient` models the documented
  ignore-repeated-token behavior, and
  `test_re_adding_an_appliance_after_removing_it_is_not_swallowed` pins it.
- **Actionable suggestion**: When an API documents "matching token →
  ignored, no error", make the test fake implement that literally. Never
  derive idempotency tokens from business keys unless dedupe forever is
  genuinely intended.

### 2026-09-24 — Latency: AgentCore Memory publishes no numbers, and the bigger threat to the 500ms budget is Runtime itself

- **Tool/SDK**: AgentCore Memory (data plane), AgentCore Runtime.
- **Task attempted**: Before building, establish whether real read latency
  could break the 500ms Alexa+ budget, the one finding that would force a
  different storage choice.
- **Steps taken**: Searched the devguide, API reference, quotas page, and
  observability docs for latency figures. Searched for third-party
  benchmarks.
- **Expected**: Some published p50/p99, or at least a stated design target.
- **Actual**: **None for Memory.** CloudWatch exposes a per-operation
  `Latency` metric, but nothing documents expected values. The only
  concrete numbers found concern **AgentCore Runtime**, not Memory: a
  re:Post article (HTTP 403 to automated fetch, so seen only via search
  summaries and **unverified at the source**) reports warm-session
  requests at roughly 200ms p50 / under 500ms p99 and new-session starts
  around 2.9s average. AWS's "new AgentCore runtime" blog says container
  deployments keep a warm pool of about 10 VMs with sub-second starts.
  If those hold, Runtime's own invocation overhead takes a large share of
  the 500ms before any tool code runs, and a cold session start blows the
  budget regardless of storage.
- **Severity**: High as a risk, unconfirmed as a fact. Nothing here shows
  Memory is too slow; nothing shows it's fast enough either.
- **Workaround**: Designed to minimize Memory round trips (one call for
  list/add, two for remove). Tight client timeouts, one startup warm-up
  read, and every call's latency logged (`agentcore_memory_call`).
  `tests/integration/test_agentcore_memory_live.py` measures per-op and
  per-tool p50/p95 against a real memory and asserts the 500ms tool
  budget. **Run it before committing to this design for deployment.**
  Measured from a laptop, the numbers include internet RTT to us-east-1,
  so they're pessimistic versus in-region Runtime.
- **Actionable suggestion**: AWS should publish expected Memory data-plane
  latency (even a same-region p50/p99 target) and put the Runtime
  warm/cold latency figures in the Runtime docs rather than a re:Post
  article.

### 2026-09-24 — Seeding: why the AgentCore backend never seeds at runtime

- **Tool/SDK**: `fixit_mcp.repository.agentcore_memory`,
  `scripts/seed_agentcore_memory.py`.
- **Task attempted**: Decide whether the agentcore backend should seed the
  demo households the way `SqliteApplianceRepository` seeds an empty store.
- **Steps taken**: Compared what "empty" means for each backend.
- **Expected**: Carry over SQLite's "seed if empty".
- **Actual**: SQLite's rule is safe because emptiness is a property of one
  local file checked once at startup. With AgentCore Memory:
  - There's no cheap "is the whole store empty" check. The per-household
    version ("seed this household if it has no events") is **wrong**,
    because it can't tell "new demo" from "a customer removed everything",
    so it would resurrect deleted appliances.
  - Every session's fresh microVM would run the check, concurrently, with
    no uniqueness constraint on events.
  - It would add AWS writes to startup or the request path, against the
    latency budget.
- **Severity**: Low. A design decision, recorded so it isn't "fixed" back
  later.
- **Workaround**: Runtime never seeds. `make seed-agentcore` is an explicit,
  offline, idempotent (by appliance_id) step that only touches
  `DEFAULT_SEED`'s household ids. `RESET=1` clears rehearsal data in the
  demo households only, never a real customer's.
- **Actionable suggestion**: For any shared remote store, keep demo/fixture
  seeding out of the serving path entirely. It's an operator action with
  an explicit blast radius, not a startup side effect.

### 2026-09-24 — First live AgentCore Memory run: functionally correct; latency from this laptop is dominated by distance to us-east-1

> **Resolved:** in-region measurements confirm this was network distance only. See [the resolution entry](#2026-09-24--resolution-in-region-agentcore-memory-latency-is-well-under-budget-laptop-failures-were-rtt-only).

- **Tool/SDK**: AgentCore Memory `FixItHouseholds-6DbWhxEuY7` (us-east-1,
  365-day expiry, no strategies), `tests/integration/test_agentcore_memory_live.py`.
- **Task attempted**: First verification of the `agentcore` backend against
  real AgentCore Memory: seed, read-after-write, smoke suite, measured latency.
- **Steps taken**: `make seed-agentcore` (house-001: 3 added, house-002: 2
  added). Ran the live tests. Separately measured raw network cost to
  `bedrock-agentcore.us-east-1.amazonaws.com` with `curl -w` (5 samples).
- **Expected**: Functional pass. Latency unknown, since AWS publishes none.
- **Actual**:
  - **Functional: pass.** Read-after-write with zero delay is consistent,
    and the full smoke suite passes against real Memory.
  - **Latency from this laptop** (p50 / p95, 20 samples):

    | Operation | p50 | p95 |
    |---|---|---|
    | CreateEvent (add) | 372ms | 386ms |
    | ListEvents (list) | 375ms | 408ms |
    | remove (ListEvents + DeleteEvent) | 695ms | 752ms |
    | `diagnose_error` tool with household | — | 412ms |
    | `add_appliance` tool | 400ms | 438ms |
    | `remove_appliance` tool | 699ms | **718ms (over 500ms)** |

  - **Network baseline**: TCP connect alone is 245–408ms (~280ms typical),
    and TLS setup completes at ~570ms, so this machine is roughly 280ms of
    round-trip time from us-east-1. Each warm (keep-alive) call is about
    one RTT plus service time, so **estimated AgentCore service time is
    ~60–120ms per call**. ICMP is blocked, so ping gives nothing.
- **Severity**: Medium. Nothing is wrong with the backend, but the two
  latency assertions fail here for geographic reasons, and `remove`
  (two sequential calls) is the path that would stay tightest even
  in-region.
- **Workaround**: None applied yet. Estimated in-region cost: list/add
  about 60–120ms, remove about 120–240ms. On top of that, add Runtime's
  own overhead (unverified: roughly 200ms p50 warm). list/add look
  comfortably inside 500ms; remove is plausible but tight. The live test's
  500ms assertion is left as-is rather than weakened. A laptop far from
  the region can't pass it, and that's a true statement about that
  vantage point, not a test bug. A real verdict needs an **in-region**
  run (e.g. AWS CloudShell in us-east-1, or from the Runtime itself in
  4c).
- **Actionable suggestion**: When validating a latency budget against a
  managed AWS API, always measure the bare TCP/TLS baseline from the same
  vantage point alongside the API call. Otherwise a geography number reads
  as a service number. If remove proves too slow in-region, it can drop
  to one call by caching appliance_id → eventId from the last list in the
  same process (AgentCore routes a conversation to one sticky microVM),
  falling back to ListEvents on a cache miss.

### 2026-09-24 — Resolution: in-region AgentCore Memory latency is well under budget (laptop failures were RTT only)

- **Resolves**: [First live AgentCore Memory run: …latency from this laptop is dominated by distance to us-east-1](#2026-09-24--first-live-agentcore-memory-run-functionally-correct-latency-from-this-laptop-is-dominated-by-distance-to-us-east-1).
- **Tool/SDK**: Same memory resource (`FixItHouseholds-6DbWhxEuY7`,
  us-east-1), `tests/integration/test_agentcore_memory_live.py`, run from
  **AWS CloudShell in us-east-1**, the same region as the memory.
- **Task attempted**: Get an in-region latency verdict for the `agentcore`
  backend, which the laptop run couldn't give (~280ms of RTT per call).
- **Steps taken**: Ran the same four live tests, unchanged, from
  CloudShell.
- **Expected**: The laptop numbers minus roughly one RTT per AgentCore call.
- **Actual**: **All 4 live tests pass.**

  | Operation | p50 | p95 | Laptop p95 (for comparison) |
  |---|---|---|---|
  | add (CreateEvent) | 86.6ms | 146.2ms | 386ms |
  | list (ListEvents) | 92.2ms | 103.0ms | 408ms |
  | remove (ListEvents + DeleteEvent) | 134.4ms | 144.7ms | 752ms |
  | `diagnose_error` tool (with household) | — | 138.4ms | 412ms |
  | `add_appliance` tool | — | 109.9ms | 438ms |
  | `remove_appliance` tool | — | 119.8ms | 718ms |

  Per-call service time is in line with the laptop-derived estimate
  (60–120ms). Remove, the two-call path, lands at ~145ms p95, well inside
  budget. The laptop failures were entirely RTT to us-east-1, not an
  AgentCore Memory problem.
- **Severity**: Resolved.
- **Workaround**: None needed. The single-call remove optimization
  proposed in the laptop entry (caching appliance_id → eventId) was
  **never built**, and is now explicitly not needed: ~355ms of headroom on
  the slowest tool is enough margin.
- **Still unverified**: This confirms **AgentCore Memory's** contribution
  only, measured from a CloudShell host in-region, not the full
  Alexa+ → AgentCore Runtime → server → Memory path. Runtime's own
  invocation overhead (the unverified ~200ms warm-p50 estimate from the
  earlier latency entry) and cold-session starts still need measuring
  once the server is actually deployed (step 4c). Rough composition,
  assuming ~200ms Runtime overhead: ~340ms p95 for `diagnose_error`,
  ~345ms for `remove_appliance`. That's under 500ms, but not by a wide
  margin, and with no cold-start allowance.
- **Actionable suggestion**: Measure latency budgets from inside the
  target region before optimizing. The laptop numbers alone would have
  justified a caching layer that the real numbers show is unnecessary.


### 2026-09-24 — Step 4c research: the AgentCore CLI can't deploy a prebuilt agent image, and requires an account-wide CDK bootstrap

- **Tool/SDK**: `@aws/agentcore` CLI 0.30.0 (npm, released 2026-09-15;
  repo `aws/agentcore-cli` at `805f342`), its `docs/container-builds.md`,
  `docs/configuration.md`, `docs/commands.md`, `docs/PERMISSIONS.md`.
- **Task attempted**: Re-check step 4a's recommendation (use the CLI:
  `agentcore create` / `add agent --protocol MCP` / `deploy`) against a
  hard requirement for 4c: deploy **exactly the image that was tested**
  (the step-4a/4b container, built from this repo's Dockerfile), not a
  different build.
- **Steps taken**: Cloned the CLI repo and read its changelog, container,
  configuration, command, and permissions docs. Searched the source for
  any prebuilt-image or `containerUri` support.
- **Expected**: `"build": "Container"` plus a way to point the agent at an
  existing ECR image, or at least at our Dockerfile.
- **Actual**:
  - **Still clearly the maintained path.** Releases are frequent (0.27 →
    0.30 in a month), each release bumps the vended CDK automatically, and
    `protocol: "MCP"`, `envVars`, `executionRoleArn` (bring your own
    role), `authorizerType`, and `lifecycleConfiguration` are all
    first-class in `agentcore.json`.
  - **No prebuilt image for agents.** Prebuilt images are supported only
    for the separate "harness" primitive. An agent with
    `build: "Container"` is **always rebuilt from its Dockerfile by
    CodeBuild** on `agentcore deploy`. Our Dockerfile works there
    (`buildContextPath: "."`), but the deployed digest is a CodeBuild
    rebuild, not the image the 4a/4b tests ran against. Our base images
    are tag-pinned (`python:3.12-slim-bookworm`, `uv:0.12.18`), not
    digest-pinned, so a rebuild can legitimately differ.
  - **Account-level setup.** `agentcore deploy` needs the region
    CDK-bootstrapped: a `CDKToolkit` stack with an S3 assets bucket, an
    ECR repo, and five IAM roles. By default the CloudFormation execution
    role gets **`AdministratorAccess`**. The deploying user also needs a
    broad policy (`cloudformation:*`, `iam:CreateRole` on `AgentCore-*`,
    CodeBuild, ECR, S3, Cognito, Secrets Manager).
- **Severity**: Medium. Not a bug, but it means "use the CLI" and "deploy
  exactly what was tested" can't both be satisfied as written.
- **Workaround**: Pending a decision (see 4c summary). The alternative is
  the documented no-CLI path: push the locally tested image to ECR, then
  `bedrock-agentcore-control:CreateAgentRuntime` with that exact
  `containerUri`, a hand-made least-privilege execution role, and no CDK
  bootstrap.
- **Actionable suggestion**: The CLI could accept a prebuilt `imageUri`
  for container agents, as it already does for harnesses. That's the
  standard "build once, test, promote the same digest" workflow.

### 2026-09-24 — AgentCore Runtime has no anonymous inbound auth: a deployed URL isn't reachable by Alexa+ until OAuth exists

- **Tool/SDK**: AgentCore Runtime inbound auth (`runtime-oauth.html`,
  CLI `authorizerType`).
- **Task attempted**: Plan step 4c's "durable HTTPS URL" for Alexa+.
- **Steps taken**: Read the Runtime inbound-auth docs and the CLI config
  schema.
- **Expected**: A public HTTPS endpoint Alexa+ can call, with auth
  (account linking) added in a later step.
- **Actual**: A Runtime accepts **either** IAM SigV4 (the default)
  **or** JWT bearer tokens (`CUSTOM_JWT`): "not both simultaneously", and
  there is no unauthenticated option. The CLI's runtime `authorizerType`
  enum is just `AWS_IAM | CUSTOM_JWT`. Only Gateway has `NONE`, and a
  `NONE` gateway in front of this server would expose every household's
  data (and the write tools) to the internet. Alexa+ can't SigV4-sign, so
  **the deployed URL is usable by our own tooling (SigV4) but not by
  Alexa+** until inbound OAuth exists (CUSTOM_JWT against the IdP Alexa+
  account linking uses). That's already listed as not-built in
  `docs/alexa-plus-requirements.md`.
- **Severity**: High for the Alexa+ milestone; nothing is broken today.
  The invocation URL is derived from the runtime ARN, so it stays stable
  when the authorizer is later switched to JWT (that's an
  `UpdateAgentRuntime`, not a new URL).
- **Workaround**: Planned: deploy with `AWS_IAM` for 4c and verify with
  SigV4-signed smoke checks (`scripts/smoke_test.py --agent-arn …`, added
  this step). Record the "remote HTTPS URL" requirement as "URL exists,
  IAM-only", not "Alexa+-reachable". OAuth becomes its own step.
- **Actionable suggestion**: AgentCore's MCP hosting guide should say up
  front that a hosted MCP server is never anonymously reachable, and
  point to the OAuth path for consumer MCP clients (Alexa+, Claude, etc.)
  that can't sign SigV4.

### 2026-09-24 — "Deploy exactly what was tested" needs a way to check it: the tested image differs from HEAD by two docstrings

- **Tool/SDK**: Docker (containerd image store), `scripts/push_image.py`.
- **Task attempted**: Push the image the 4a/4b container tests ran against
  (`fixit-mcp:latest`, image id `fc68db80…`, built 2026-09-24 17:57 +06:00)
  to ECR without rebuilding, and be able to say precisely how it relates
  to the committed source.
- **Steps taken**: Added a pre-push check to `push_image.py`. It hashes
  every `.py`/`.html` under `/app/src` inside the image and compares them
  with the working tree. Ran it before any AWS step.
- **Expected**: Either an exact match, or a clear list of differences.
- **Actual**: 26 files in the image. Exactly **two differ**:
  `repository/base.py` and `repository/sqlite.py`. Both changed only in
  docstrings, edited in step 4b's docs pass *after* that build. No code
  difference. Without the check, "we deployed what we tested" would have
  been an assumption either way.
- **Severity**: Low. Behaviorally identical, and now visible instead of
  assumed.
- **Workaround**: Push the tested image as-is, per the requirement.
  `push_image.py` prints the drift on every push, so a future
  *behavioral* drift can't slip through silently. `deploy_runtime.py`
  pins the runtime to the pushed **digest** (`repo@sha256:…`), never the
  mutable `latest` tag.
- **Actionable suggestion**: When the policy is "promote the tested
  artifact", record the artifact's content (source hashes, digest) at
  test time and compare at promote time. A build timestamp or tag alone
  says nothing about what's inside.

### 2026-09-24 — ~17ms of every tool call is FixIt's own stateless MCP request stack, not the handler

- **Tool/SDK**: `mcp` 1.30 FastMCP (`stateless_http=True`,
  `json_response=True`), uvicorn, the MCP Python client.
- **Task attempted**: Build `scripts/measure_runtime_latency.py`, which
  splits a deployed call into network RTT, AgentCore Runtime overhead,
  and handler time. Before trusting that split, sanity-checked it
  against the local dev server, where RTT is ~0.
- **Steps taken**: Ran the script locally. Then timed a raw `tools/call`
  with `curl` (fresh connection each time) and with a keep-alive `httpx`
  client, which bypasses the MCP client library.
- **Expected**: Round trip ≈ handler time (~1.4ms, per the server's own
  `tool_call_completed` log line) + a millisecond or two.
- **Actual**: MCP client round trip ~45ms. Raw curl/httpx ~18–21ms. So
  about **17ms per request is server-side stack outside the handler**
  (stateless mode builds a fresh server session per request), and about
  25ms more is the MCP Python client. Not Nagle/delayed-ACK: curl on
  fresh connections shows the same number.
- **Severity**: Low for the 500ms budget. High for interpretation: the
  deployed container pays the same ~17ms (probably different on
  Graviton), so "client − RTT − handler" is **Runtime overhead + ~17ms of
  ours**, not pure Runtime overhead.
- **Workaround**: The latency script labels the remainder as exactly
  that, rather than calling it "Runtime overhead". Not optimized here:
  it's 3–4% of the budget, and the deployed image stays the tested one.
- **Actionable suggestion**: Log whole-request latency at the ASGI layer
  as well as per-tool latency, so server time can be split without
  assumptions. That's a candidate for the next image, not this deploy.

### 2026-09-24 — The deployer policy is too big to be an inline IAM user policy

- **Tool/SDK**: IAM console (inline user policies), `deploy/iam/deployer-policy.json`.
- **Task attempted**: Attach the step-4c deployer permissions to `fixit-dev`
  as an inline policy, following my own console steps.
- **Steps taken**: The user pasted the rendered policy, then tried
  minifying it.
- **Expected**: The policy saves.
- **Actual**: IAM caps inline policies on a **user** at **2,048
  non-whitespace characters in total**, across all of that user's inline
  policies, and `fixit-dev` already has the step-4b Memory policy. The
  deployer policy alone is 2,296 characters. Minifying can't help,
  because whitespace isn't counted. (Role inline policies allow 10,240,
  so the execution-role policy at 1,577 was never at risk.)
- **Severity**: Low. Caught at the console, before anything was created.
  But it was my instruction that was wrong.
- **Workaround**: Made the deployer policy a **customer managed policy**
  (6,144-character limit) attached to `fixit-dev`. Dropped one redundant
  `logs:DescribeLogGroups`, already covered by a `*` statement, bringing
  it to 2,271. Added
  `test_rendered_policies_fit_the_iam_size_limit_where_they_are_attached`,
  which checks each rendered file against the limit for where it's
  attached, so this can't recur silently.
- **Actionable suggestion**: When handing out an IAM policy, state where
  it attaches (user inline, role inline, or managed) and check its
  non-whitespace size against that limit before handing it over.
