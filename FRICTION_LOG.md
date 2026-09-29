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

- **Tool/SDK**: AgentCore Memory `FixItHouseholds-<memory-id>` (us-east-1,
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
- **Tool/SDK**: Same memory resource (`FixItHouseholds-<memory-id>`,
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

### 2026-09-24 — First real CreateAgentRuntime: AccessDenied on an action the call never names (CreateAgentRuntimeEndpoint)

- **Tool/SDK**: `bedrock-agentcore-control:CreateAgentRuntime` (boto3
  1.43.100), IAM, `scripts/deploy_runtime.py`.
- **Task attempted**: First real deploy (`make deploy-runtime`) after
  `make docker-push` succeeded. That push created ECR repo `fixit-mcp`;
  the image digest `sha256:fc68db80…` equals the tested local image's id.
- **Steps taken**: Ran the deploy with the `FixItRuntimeDeployer` managed
  policy attached to `fixit-dev`.
- **Expected**: `CreateAgentRuntime` authorized by the statement granting
  `bedrock-agentcore:CreateAgentRuntime` on `*`.
- **Actual**: `AccessDeniedException: User:
  arn:aws:iam::<account>:user/fixit-dev is not authorized to perform:
  bedrock-agentcore:CreateAgentRuntimeEndpoint on resource:
  arn:aws:bedrock-agentcore:us-east-1:<account>:runtime/* because no
  identity-based policy allows the bedrock-agentcore:CreateAgentRuntimeEndpoint
  action`. `CreateAgentRuntime` implicitly creates the DEFAULT endpoint,
  and IAM authorizes that as a **second action**, against the literal
  wildcard ARN `runtime/*`, so a name-scoped `runtime/fixit_mcp-*` grant
  can never match it. `ListAgentRuntimes` afterwards showed **no runtime
  created**: the check fails before anything is provisioned.
- **Severity**: Low (nothing half-created). Not documented on the
  CreateAgentRuntime API page, nor in AWS's runtime-permissions page.
- **Workaround**: Added `CreateAgentRuntimeEndpoint` to the `*` statement.
  Also added `UpdateAgentRuntimeEndpoint` and `DeleteAgentRuntimeEndpoint`
  to the runtime-scoped statement. Those two are **anticipated, not
  observed**: update repoints DEFAULT at the new version, and delete
  removes it, the same implicit-endpoint pattern. One policy revision
  instead of three failed runs. Pinned by
  `test_deployer_can_create_the_implicit_default_endpoint`.
- **Actionable suggestion**: AWS should list implicitly authorized
  sub-actions (like endpoint creation) on the CreateAgentRuntime API
  reference page. Scoping a create to a resource-name pattern fails in a
  confusing way when the service authorizes a sibling action against a
  wildcard ARN.
- **Follow-up, second attempt (same day)**: With the endpoint action
  granted, the create failed on the *next* implicit sub-action:
  `AccessDeniedException: ... not authorized to perform:
  bedrock-agentcore:CreateWorkloadIdentity on resource:
  arn:aws:bedrock-agentcore:us-east-1:<account>:workload-identity-directory/default/workload-identity/*`
  (request id `b20cfe3d-0a8c-4a93-ad57-ed9fc248b896`). Again, **no runtime
  was created**. AWS's runtime docs do say a workload identity is created
  automatically with every runtime, so this one was foreseeable. Rather
  than find the rest one console round trip at a time, took the
  **complete** runtime-lifecycle action set from the AgentCore CLI's own
  shipped `docs/policies/iam-policy-user.json`: CreateAgentRuntime,
  Update/Delete/ListAgentRuntimes, CreateAgentRuntimeEndpoint,
  CreateWorkloadIdentity, DeleteWorkloadIdentity. Added
  `CreateWorkloadIdentity` on `*`, and `DeleteWorkloadIdentity` scoped to
  `workload-identity/fixit_mcp-*` (scoping is my inference; the CLI uses
  `*`).
- **Lesson**: For a service whose create call fans out into several
  implicitly authorized sub-resources, start from the vendor tool's
  shipped policy, which encodes that fan-out, and scope *down* from it.
  Building up from the API reference page means discovering the fan-out
  one AccessDenied at a time.


### 2026-09-24 — First AgentCore Runtime deploy: what got created, and the measured latency (warm is fine; cold sessions are the real risk)

- **Tool/SDK**: `bedrock-agentcore-control` (CreateAgentRuntime),
  AgentCore Runtime data plane (SigV4), CloudWatch Logs,
  `scripts/{push_image,deploy_runtime,measure_runtime_latency,smoke_test}.py`.
- **Task attempted**: Deploy the tested image, verify it end to end, and
  finally measure AgentCore Runtime's own overhead: the unverified
  "~200ms warm p50" from step 4b.
- **Steps taken**: `make docker-push`, then `make deploy-runtime` (third
  attempt, after the two AccessDenied entries above). Inventoried the
  result. Ran `measure_runtime_latency.py` **before** the smoke test, so
  the very first sessions after creation were genuinely cold. Read the
  container's CloudWatch log streams per session. Re-measured once the
  warm pool existed. Ran `make runtime-smoke`. Re-ran `make deploy-runtime`
  to check idempotency against the real API.
- **What exists now (all us-east-1)**:
  - ECR repo `fixit-mcp`, holding an OCI image index: linux/arm64 plus a
    buildx provenance attestation. Its digest `sha256:fc68db80…` **equals
    the tested local image id**, so it's byte-identical. AgentCore
    accepted the index as-is.
  - Runtime `fixit_mcp-<id>` v1, READY in ~10s. MCP, PUBLIC, no
    authorizer (IAM SigV4), idle timeout 300s, role
    `FixItAgentCoreRuntimeRole`, 4 env vars (agentcore backend).
  - Endpoint `DEFAULT` → v1. Workload identity `fixit_mcp-<id>`
    (automatic). Log group `/aws/bedrock-agentcore/runtimes/fixit_mcp-<id>-DEFAULT`.
- **Expected**: Warm overhead of about 200ms. Cold start of a few
  hundred ms, given the documented warm pool.
- **Actual**:
  - **Warm (same session), two runs of 30 and 60 calls:** client p50
    532 / 516ms, p95 637 / 614ms. RTT (TCP connect) 308 / 321ms. Handler
    p50 53 / 52ms, from our own `tool_call_completed` lines.
    **Remainder: 171 / 143ms**, which includes ~17ms of our own stack
    (entry above). **AgentCore Runtime overhead is roughly 125–155ms
    p50**, better than the 200ms estimate. Implied in-region warm p50:
    about 200–250ms. Well inside budget.
  - **Cold, before the warm pool existed** (first traffic, 40s after
    create): 5 new sessions. `initialize` took **6.3–8.4s**; the first
    tool call another ~2s. CloudWatch shows our own process ready ~0.2s
    after its first log line (warm-up Memory read 70–85ms), so the 6–8s
    is microVM provisioning, image pull, and interpreter start: platform
    time, not ours.
  - **The warm pool appeared only *after* first use**: 10 extra microVMs
    started 15:17:49–15:18:12, about 2 minutes after the runtime was
    created (15:15:43) and after the first sessions. Each got one
    platform ping and no traffic.
  - **Cold, with the pool warm:** 8 new sessions. `initialize` took
    **1.3–2.1s (p50 1.57s)**. Each opens a fresh TLS connection, about 3
    RTTs (~1s) from this laptop. But the **first tool call in every new
    session is ~2s regardless** (1.94–2.15s), versus ~0.5s warm. The
    container logs show the platform holding that request about 1s
    before forwarding it, with its own MCP ping arriving in between.
    Cause unknown.
  - **Platform health checks:** besides MCP `ping` every 2s on a separate
    connection, the platform also probes **`GET /ping`, which returns
    404** (FastMCP has no such route). Harmless so far: sessions work
    and nothing restarts.
  - **One intermittent `504 Gateway Time-out`** from the AgentCore front
    door in one warm session: 1 of about 110 warm calls. The container
    log shows the request **never arrived**; only healthy platform pings
    continued. Not reproduced in the next 60-call run.
  - **Smoke test:** 8/8 functional checks pass, SigV4-signed. The
    latency check fails at 641.5ms p95, because RTT is ~320ms of that
    from here.
  - **Idempotency:** a second `make deploy-runtime` reports `unchanged
    (version 1)`, so `config_matches` holds against the real
    `GetAgentRuntime` shape.
- **Severity**: **High, for cold sessions.** If Alexa+ opens a new MCP
  session per conversation, the first call of every conversation costs
  roughly 1.5s (initialize) + 2s (first tool call) from here, and seconds
  even in-region: far over 500ms. Warm calls are fine. Low for the 504
  and the `/ping` 404, but worth tracking.
- **Workaround**: None yet, deliberately. The next measurements before
  choosing a fix:
  1. Rerun `measure_runtime_latency.py --cold 8` from CloudShell
     (us-east-1), to separate the ~1s of laptop TLS setup from real
     platform cold cost.
  2. Find out whether Alexa+ reuses `Mcp-Session-Id` across turns or
     conversations.
  Candidate fixes to weigh later: a `/ping` route (cheap, needs a new
  image), keeping sessions alive, and asking AWS about warm-pool sizing
  and the first-call delay.
- **Actionable suggestion**: AgentCore should document (a) that the
  container warm pool fills only after first traffic, (b) the extra
  first-request latency in a new session, and (c) that MCP-protocol
  runtimes are also probed on `GET /ping`.

### 2026-09-25 — I committed the real AWS account id in a test; caught before any push and scrubbed from local history

- **Tool/SDK**: git, `tests/unit/test_deploy_scripts.py`.
- **Task attempted**: Keep the account id out of the public repo (an
  explicit requirement for step 4c), while testing the IAM policy size
  limits with a realistic-length id.
- **Steps taken**: Before the final step-4c commit, ran
  `git grep` for the account id and runtime id over the staged tree.
- **Expected**: Clean.
- **Actual**: The real account id was hardcoded in
  `test_rendered_policies_fit_the_iam_size_limit_where_they_are_attached`,
  introduced in the "customer managed policy" commit. My command chained
  the grep with `||` and `&&`, so **the commit still went through** despite
  the grep finding it. `origin/main` was clean: all six step-4c commits
  were still unpushed.
- **Severity**: Medium. An account id isn't a credential, but the user
  explicitly asked for it to stay out of the public repo, and a pushed
  commit can't really be un-published.
- **Workaround**: Created `backup/pre-account-id-scrub`. Replaced the id
  with a same-length dummy (`999999999999`, so the size test measures the
  same thing), then folded that into the offending commit with a
  `fixup!` + `git rebase --autosquash origin/main`, rewriting local
  unpushed commits only. Verified 0 occurrences in unpushed patches,
  commit messages, and the tree. Added
  `tests/unit/test_no_account_ids.py`, which scans every tracked file for
  12-digit account ids in ARNs, ECR URIs, and `AWS_ACCOUNT_ID` /
  `aws:SourceAccount` values, allowing only AWS's documentation examples
  and the dummy. It would have caught this leak.
- **Actionable suggestion**: A secret or identifier check has to *gate*
  the commit (fail and stop), not just print before it. Better still, it
  belongs in the test suite, where every commit already runs it.

### 2026-09-28 — Step 5a research: Alexa+'s MCP session model is undocumented where it matters most; our own deploy script silently opted out of the cold-start fix

- **Tool/SDK**: Alexa+ MCP Toolkit docs (`mcp-toolkit-client-lifecycle.html`,
  `mcp-toolkit-overview.html`, `mcp-toolkit-quickstart.html`), AWS AgentCore
  Runtime docs (`runtime-lifecycle-settings.html`, `agent-runtime-versioning.html`,
  the AGENTCOST06-BP03 / AGENTPERF02-BP03 Well-Architected agentic-ai-lens
  pages), the "new AgentCore Runtime" GA blog post and what's-new post
  (2026-09-18), `scripts/deploy_runtime.py`.
- **Task attempted**: Research only (no code/AWS changes) — find out how
  often a real Alexa+ conversation will hit a cold AgentCore Runtime
  session, per the user's step-5a research request.
- **Steps taken**: Read all three Alexa+ MCP Toolkit doc pages and the
  AWS AgentCore Runtime lifecycle/versioning docs and two Well-Architected
  agentic-ai-lens best-practice pages. Cross-checked `deploy_runtime.py`'s
  `create_agent_runtime`/`update_agent_runtime` call against what the docs
  say controls cold-start latency.
- **Expected**: Alexa+ docs would state whether `Mcp-Session-Id` is reused
  across conversation turns/conversations, and whether `initialize` runs
  once at deploy time or on every customer turn — the fact that determines
  whether cold start is a rare edge case or a per-turn tax.
- **Actual**:
  - **Undocumented, load-bearing gap**: `mcp-toolkit-client-lifecycle.html`
    says only "the session is based on the customer's previous conversations
    with Alexa+ rather than an explicit identifier for a session with your
    MCP App" — it never says whether that maps to one `Mcp-Session-Id` per
    conversation, one per turn, or something else, and never states whether
    `initialize`/`tools/list` run once at add-on deployment (the overview
    page's registration language implies this) or are replayed per
    session. Nothing in any of the three pages mentions timeouts or retries
    for a slow/cold tool call beyond the flat 500ms latency requirement.
  - **Unexpected, concrete finding**: AgentCore Runtime shipped a new
    execution platform (`platformVersion: "V2"`, GA 2026-09-18, us-east-1
    included) that replaces the boot-and-initialize cold path with a
    snapshot-restore, giving a documented P75 cold start of ~2s regardless
    of image size, versus **5.4–30s on V1** — squarely explaining our
    measured 1.3–8.4s cold `initialize` times. `platformVersion` defaults
    to `V1` when omitted on `CreateAgentRuntime`/`UpdateAgentRuntime`, and
    `deploy_runtime.py`'s `desired` payload (around line 90) never sets it
    — so step 4c's runtime has been on the slow platform the whole time,
    not because V2 didn't exist, but because it launched *nine days before*
    our step-4c deploy and nothing here checked for it.
  - Also confirmed (documented, not inferred): the observed "10 microVMs
    appeared ~2 minutes after first traffic" behavior in the step-4c entry
    matches AWS's stated container warm-pool size (10 pre-warmed VMs; the
    11th+ concurrent new session pays full cold cost). Idle timeout
    (`deploy_runtime.py`'s 300s) resets on every invocation to the same
    `runtimeSessionId` and is independent of `maxLifetime` (8h default) —
    so a conversation with >5 minutes between turns will cold-start its
    *own* session even if the runtime overall stays warm for other traffic.
- **Severity**: High. Two compounding unknowns — how Alexa+ maps
  conversations to sessions (undocumented) and which Runtime platform we
  deployed on (documented, but silently wrong in our own script) — made the
  cold-start risk look worse and less actionable than it actually is.
- **Workaround**: None yet — this is the research step; the report handed
  to the user ranks `platformVersion: "V2"` as the first thing to try,
  since it's a config change to an existing script, not a new mitigation to
  build, and costs no new code path.
- **Actionable suggestion**: Alexa+'s MCP Toolkit docs should state the
  `Mcp-Session-Id` reuse policy explicitly — it's the one fact that decides
  whether a builder needs to care about cold starts at all. Separately,
  `deploy_runtime.py` should assert or default `platformVersion` explicitly
  rather than silently inheriting whatever AWS's API default is, so a
  future platform-default change can't silently change our latency profile
  again.

### 2026-09-28 — Step 5b: `platformVersion` is a free-text field with no documented default value in the API reference itself

- **Tool/SDK**: boto3 1.43.100 (`bedrock-agentcore-control` service model),
  the `CreateAgentRuntime`/`UpdateAgentRuntime`/`GetAgentRuntime` API
  reference pages, `scripts/deploy_runtime.py`.
- **Task attempted**: Make `platformVersion` explicit in
  `deploy_runtime.py` (default `"V2"`, overridable via
  `--platform-version`/`FIXIT_AGENTCORE_PLATFORM_VERSION`), per step 5a's
  finding that the script was silently deploying on the slower V1
  platform.
- **Steps taken**: Inspected the installed boto3 service model directly
  (`client.meta.service_model.operation_model(...)`) before changing any
  code, rather than trusting the step-5a research secondhand. Confirmed
  `platformVersion` is a real input member on both `CreateAgentRuntime` and
  `UpdateAgentRuntime`, and an output member on `GetAgentRuntime`, in the
  installed SDK (uploaded 2026-09-22, four days after V2 GA'd). Then read
  the three API reference pages directly (not secondhand from search
  results) for the field's documented behavior.
- **Expected**: The API reference would state a default (e.g. "V1 if
  omitted") the way the marketing blog post and secondary sources
  (forkast.news, unite.ai) claimed.
- **Actual**: `platformVersion` is modeled as a **plain string** (pattern
  `[^\s]+`, 1-128 chars, **no enum constraint** in the SDK) on all three
  operations. Its prose description is one line ("The version of the
  runtime platform...") with no stated default and no enum of valid values
  anywhere in the API reference itself -- "V1 is the default" is real (per
  the GA announcement and secondary coverage) but isn't asserted by the
  `CreateAgentRuntime`/`GetAgentRuntime` reference pages a caller would
  actually consult. Whether a runtime created before this field existed
  reports back `"V1"` explicitly or omits the key from `GetAgentRuntime`
  is therefore still unconfirmed against a real runtime.
- **Severity**: Low. `config_matches()` (`deploy_runtime.py`) already
  compares every `desired` key against `current.get(key)` generically --
  `current.get("platformVersion")` being `"V1"` or `None` both fail to
  equal our desired `"V2"`, so the idempotency check triggers an update
  either way without needing to know which case is real. Confirmed with a
  fake-runtime test (`test_a_v1_runtime_is_detected_as_needing_an_update`)
  using an explicit `"V1"` current value, since that's the only case a
  fake can assert without live AWS.
- **Workaround**: None needed -- the existing generic comparison already
  handles both possibilities correctly.
- **Actionable suggestion**: The `CreateAgentRuntime`/`GetAgentRuntime` API
  reference should state `platformVersion`'s default and valid values
  (`V1`/`V2`) directly, not require cross-referencing a blog post and a
  service model with no enum to find them.

### 2026-09-28 — Step 5b live measurement: V2 beats V1's cold-start-from-scratch case, but the ~2s first-tool-call tax survives the platform switch unchanged

- **Tool/SDK**: The live `fixit_mcp` AgentCore Runtime, `scripts/deploy_runtime.py`,
  `scripts/smoke_test.py`, `scripts/measure_runtime_latency.py`.
- **Task attempted**: Deploy `platformVersion: "V2"` to the real runtime
  (step 5b), confirm it took effect and functional checks still pass, and
  measure cold/warm latency against step 4c's V1 numbers.
- **Steps taken**: `make deploy-runtime` with `FIXIT_AGENTCORE_MEMORY_ID`
  set. Confirmed via `GetAgentRuntime` on both versions:
  `agentRuntimeVersion` 1 reports `platformVersion: "V1"` explicitly (not
  omitted -- resolves the "unconfirmed" question in the entry above) and
  version 2 reports `"V2"`. Same `agentRuntimeId`/ARN throughout -- an
  in-place `UpdateAgentRuntime` (not a recreate), and it wasn't denied.
  `make runtime-smoke`: 8/8 functional checks pass; the pre-existing
  latency check still fails from here (as in step 4c -- RTT-dominated, not
  a regression). `measure_runtime_latency.py --agent-arn ...` (defaults:
  5 cold sessions, 30 warm calls), run from Dhaka: TCP-connect RTT p50
  316.6ms / p95 327.1ms, essentially identical to step 4c's laptop numbers,
  so the two runs are comparable.
- **Expected**: Cold `initialize` around AWS's documented ~2s P75 for V2,
  and some improvement to the first-tool-call cost too.
- **Actual**:
  - **Cold `initialize`** (n=5): 2880.2, 3093.5, 2866.7, 2931.9, 2780.3ms
    -- p50 2880.2ms, p95 3093.5ms, min 2780.3ms, max 3093.5ms.
  - **Cold first `diagnose_error` in the new session** (n=5): 2254.9,
    2187.3, 2337.6, 2113.9, 2040.9ms -- p50 2187.3ms, p95 2337.6ms.
  - **Warm `diagnose_error`** (n=30, same session): p50 571.8ms, p95
    645.2ms, min 505.8ms, max 835.0ms. Server-side handler (CloudWatch):
    p50 53.5ms, p95 105.2ms. Client p50 − RTT p50 − handler p50 = 201.7ms.
  - **These 5 cold samples were taken right after the update**, before any
    V2-specific warm pool had a chance to exist (step 4c found AWS's
    10-VM pool fills only ~2 minutes *after* first traffic on a version).
    So the fair V1 comparison is the *"before the warm pool existed"* row
    (6.3-8.4s), not the *"with pool warm"* row (1.3-2.1s, p50 1.57s) -- and
    against that, V2 is clearly faster (2.78-3.09s, roughly 2-3x). Against
    the warm-pool V1 row, though, V2's raw numbers are **higher**, not
    lower. Subtracting the ~1s of TLS-handshake RTT (3 round trips from
    here, per step 4c) that AWS's own EC2-to-EC2 benchmark environment
    wouldn't have paid gives a platform-side estimate of roughly 1.8-2.1s
    -- in the neighborhood of the documented ~2s P75, but that's an
    inference from subtraction, not a direct platform-only measurement, so
    **I'm not calling this a confirmed hit on the P75 claim, just
    plausible.**
  - **The first-tool-call tax is unchanged.** Step 4c (V1): first tool
    call in a new session was ~1.94-2.15s *regardless of warm-pool state*,
    with "the platform holding that request about 1s before forwarding
    it, with its own MCP ping arriving in between. Cause unknown." This
    run (V2): 2.04-2.34s -- statistically the same. Switching platform
    version did nothing to this component, whatever it is.
  - **The warm path got slightly worse, not better, in this one run**: p50
    571.8ms vs V1's 516-532ms, and the derived Runtime-overhead figure
    rose to ~202ms vs V1's ~125-155ms p50. One run of 30 calls; step 4c
    ran two independent rounds (30 and 60 calls) before trusting its V1
    number, so this isn't yet distinguishable from noise.
- **Severity**: Medium. Real improvement over an unwarmed pool, but not a
  clean "problem solved": total cold-session cost (init + first tool call)
  is still roughly 5s from here, still far over the 500ms budget for a
  conversation's first turn, and the one component step 4c couldn't
  explain (the ~2s first-tool-call hold) is now confirmed to be
  independent of platform version.
- **Workaround**: None decided yet. Worth remeasuring cold numbers again
  once natural traffic (or a deliberate second cold burst) has had time to
  fill a V2 warm pool, the way step 4c did for V1, before concluding V2's
  warm-pool cold-start number is actually worse than V1's -- this run
  never got that chance.
- **Actionable suggestion**: The first-request-in-new-session ~1s hold is
  now reproduced identically across two platform versions, which rules out
  a V1-specific bug as the cause and makes it the single highest-value
  remaining mystery in the cold-start budget. AWS should document what
  that hold is.

### 2026-09-28 — Step 5d: tested and ruled out the `GET /ping` hypothesis for the ~1s first-tool-call hold

- **Tool/SDK**: AgentCore Runtime docs (`runtime-service-contract.md`,
  `runtime-http-protocol-contract.md`, `runtime-mcp-protocol-contract.md`,
  `runtime-troubleshooting.md`), CloudWatch Logs on the live `fixit_mcp`
  runtime (`GetLogEvents`, container access-log stream).
- **Task attempted**: Test the hypothesis that the platform waits on a
  `GET /ping` health check (which 404s on our server -- FastMCP has no
  such route) before forwarding the first real request in a new session,
  and that wait is the ~1s hold noted in step 4c and reproduced identically
  under V2 in step 5b. Investigate only; no code change unless the
  evidence supported it.
- **Steps taken**:
  1. Read the AgentCore Runtime service-contract docs directly (not
     secondhand). Finding: `GET /ping` is documented **only** under the
     HTTP protocol contract (port 8080, alongside `/invocations`) as a
     liveness/idle-timeout signal ("Verifies that your agent is
     operational and ready to handle requests" / drives the 15-minute
     idle-session timeout via `Healthy`/`HealthyBusy`). The **MCP protocol
     contract**'s "Path requirements" section lists exactly one path --
     `POST /mcp` -- and never mentions `/ping` at all. Nothing in any of
     the four contract pages describes `/ping` as gating or delaying
     forwarding of a session's first request; every documented use is
     liveness/idle-timeout, not readiness-gating.
  2. Generated one fresh cold session
     (`measure_runtime_latency.py --agent-arn ... --cold 1 --warm 0`) and
     pulled the exact CloudWatch container log lines for that session
     immediately after (`GetLogEvents` on the current `runtime-logs-*`
     stream, millisecond timestamps from our own uvicorn access log --
     `127.0.0.1` addresses, so no network/TLS time is mixed in).
- **Expected**: A `GET /ping` (or the periodic MCP `PingRequest` keepalive)
  landing inside the gap between the client's `initialize` completing and
  the server starting to process the first tool call.
- **Actual**: The real timeline for that session:
  ```
  13:18:58.898  POST /mcp  200 OK        <- initialize response
  13:18:59.384  POST /mcp  202 Accepted  <- notifications/initialized
                ---- 1037ms gap, nothing logged ----
  13:19:00.421  "Processing request of type CallToolRequest"  <- diagnose_error begins
  13:19:00.540  tool_call_completed (118ms handler)
  13:19:00.557  POST /mcp  200 OK        <- tool call response
  13:19:00.821  GET /ping  404 Not Found <- the only GET /ping in the window,
                                             ~400ms AFTER the tool call already finished
  ```
  The periodic MCP `PingRequest` keepalive (separate connection, steady
  ~2005ms cadence: `13:18:58.819`, `13:19:00.824`, `13:19:02.829`, ...)
  doesn't land inside the 1037ms gap either -- the nearest one is *after*
  the gap closes. **Neither `GET /ping` nor an MCP `PingRequest` occurs
  anywhere in the hold.** This also refines step 4c's original qualitative
  note ("the platform holding that request... with its own MCP ping
  arriving in between") -- with precise timestamps, the ping doesn't
  actually arrive inside the gap; that was an imprecise read of noisier
  logs at the time.
- **Severity**: N/A -- this is a negative result, which is the point of
  testing a hypothesis before building on it.
- **Workaround**: None -- per instructions, stopped here and did not add a
  `/ping` route or touch any code. The ~1s hold is confirmed real (all
  timestamps are internal, not RTT) and confirmed platform-version-
  independent (step 5b), but its cause is still unknown. `/ping` and the
  MCP keepalive are both ruled out.
- **Actionable suggestion**: Unchanged from step 4c/5b -- AWS should
  document what happens internally between a session's `initialize`
  completing and its first tool call being dispatched. The docs gap here
  isn't that `/ping`'s role for MCP is unclear (it's fairly clear: HTTP-
  protocol-only, liveness/idle-timeout) -- it's that nothing documents
  *this specific* internal gap at all.

### Cold-start latency: known limitation

Consolidates steps 4c, 5a, 5b, and 5d. This is the closing summary for the
cold-start investigation, not a new finding -- see those entries for the
full detail behind each number.

- **Measured numbers** (all from Dhaka, ~320ms RTT to us-east-1;
  `scripts/measure_runtime_latency.py`):
  - **V1** (`platformVersion` unset, step 4c): cold `initialize`
    6.3-8.4s before the runtime's warm pool existed, 1.3-2.1s (p50 1.57s)
    once it did.
  - **V2** (`platformVersion: "V2"`, step 5b): cold `initialize`
    2.8-3.1s (p50 2.88s), measured immediately after the platform
    update, before any V2-specific warm pool had a chance to fill --
    the fair comparison is V1's unwarmed number, against which V2 is
    2-3x faster; against V1's warm-pool number, V2's raw figure is
    higher (though ~1s of that gap is Dhaka's TLS RTT that AWS's own
    EC2-to-EC2 P75 benchmark wouldn't pay).
  - **First tool call in a new session: ~2s on both platform versions**
    (V1 1.94-2.15s, V2 2.04-2.34s) -- statistically the same, including a
    **~1.0s internal platform hold** between `initialize` completing and
    the server starting to process the first tool call. Step 5d confirmed
    with real CloudWatch timestamps that neither `GET /ping` nor the
    periodic MCP `PingRequest` keepalive occurs inside that hold, so
    neither explains it. Cause still unknown.
  - **Total cold session cost (init + first tool call): ~5s**, on both
    platform versions, from here.
  - **Warm path**: fits the 500ms budget once RTT is discounted to an
    in-region customer (~200-250ms p50 estimated in-region, vs. the
    ~572-645ms client-side measured from Dhaka).
- **Documented vs. inferred**:
  - **Undocumented**: whether Alexa+'s `Mcp-Session-Id` maps to one
    session per conversation, one per turn, or something else (step 5a --
    the single fact that would tell us how often a real Alexa+
    conversation pays the cold-start cost above). Also undocumented: what
    happens internally between a session's `initialize` completing and
    its first tool call being dispatched (the ~1.0s hold, step 5d).
  - **Documented**: AgentCore's 10-VM warm pool and per-session microVM
    model (step 4c); `platformVersion` V1 vs. V2 and V2's ~2s P75 cold
    start claim (step 5a/5b); `/ping`'s role as an HTTP-protocol-only
    liveness/idle-timeout signal, not part of the MCP contract and not
    documented as gating traffic (step 5d).
- **What we did**: set `platformVersion: "V2"` explicitly instead of
  silently inheriting AWS's V1 default (step 5b) -- a real, low-cost,
  low-risk win for the unwarmed-pool case, already deployed.
- **What we did not do**: any application-level mitigation. Specifically
  not attempted: keep-alive pings to hold a session's own microVM warm
  between customer turns (per-session isolation means this only helps if
  Alexa+ actually reuses the same `Mcp-Session-Id`, which is unknown);
  measuring from AWS CloudShell in-region to separate real platform cold
  cost from Dhaka's RTT cleanly; provisioned/reserved capacity (Instances
  compute type, `capacityProviderConfiguration`) to eliminate microVM
  cold starts entirely, unevaluated for cost or fit against our stateless,
  bursty workload.
- **The bottom line**: warm calls comfortably fit the 500ms Alexa+ budget.
  Cold sessions do not, by roughly an order of magnitude, on either
  platform version, and that is a known, currently unmitigated limitation
  of this deployment -- not a solved problem. Whether that limitation
  matters in practice for a real Alexa+ conversation depends entirely on
  the undocumented `Mcp-Session-Id` reuse policy above, which can only be
  learned by testing against a real Alexa+ client, not by further
  measurement of our own runtime.
- **Suggestions for AWS/Amazon**:
  1. Document whether/how Alexa+'s MCP client reuses `Mcp-Session-Id`
     across conversation turns and across separate conversations --
     `mcp-toolkit-client-lifecycle.html` currently says only that "the
     session is based on the customer's previous conversations," which
     doesn't answer this.
  2. Document what happens internally between a session's `initialize`
     completing and its first tool call being dispatched, and why it
     costs ~1s independent of platform version or warm-pool state.

### 2026-09-28 — Step 6a: a fake that captures a mutable list by reference showed every recorded Bedrock call the loop's *final* message history, not what that call actually saw

- **Tool/SDK**: `tests/unit/test_demo_orchestrator.py`'s `FakeConverse`,
  Python's mutable-default-argument-adjacent footgun (a shared mutable
  object captured by reference, not value).
- **Task attempted**: Assert that the `toolResult` sent back to Bedrock on
  the *second* Converse call (after a tool call) carries the tool's
  structured content and the right `toolUseId`.
- **Steps taken**: `run_turn` (`demo/orchestrator.py`) mutates one shared
  `messages` list in place across every round of its loop (appending the
  assistant's response, then the tool result, then looping). `FakeConverse`
  recorded `kwargs` -- including `kwargs["messages"]` -- as-is in a list of
  calls, then the test inspected `converse.calls[1]["messages"][-1]` after
  `run_turn` had already returned.
- **Expected**: `calls[1]["messages"]` frozen at 3 items (user, assistant
  tool-use, user tool-result) -- the state at the moment of the *second*
  `converse()` call.
- **Actual**: `KeyError: 'toolResult'` -- `calls[1]["messages"][-1]` was
  actually the assistant's *final* text message (4th item), because
  `calls[0]["messages"]` and `calls[1]["messages"]` were never two lists;
  they were two dict entries both pointing at the same list object, which
  kept growing after each was "recorded." Inspecting either one after the
  loop finished showed the loop's ending state, not either call's.
- **Severity**: Low -- caught immediately by the test itself failing, never
  reached committed code; the bug was in the test double, not in
  `run_turn`, which was correct throughout.
- **Workaround**: `FakeConverse.__call__` now stores
  `{**kwargs, "messages": list(kwargs["messages"])}` -- a shallow copy at
  call time -- so each recorded call is a snapshot, not a live view into a
  list the code under test keeps mutating.
- **Actionable suggestion**: Any fake that records `**kwargs` verbatim from
  a caller that's known to mutate a passed-in list/dict afterward needs an
  explicit snapshot, not just `kwargs.copy()`/`{**kwargs}` -- a shallow
  copy of the outer dict still shares the same inner mutable list.

### 2026-09-28 — Step 6a: a new uv dependency group needs `make test` updated too, or its tests silently never run

- **Tool/SDK**: `uv` dependency groups (PEP 735), `pyproject.toml`,
  Makefile.
- **Task attempted**: Add FastAPI (and transitively uvicorn) for `demo/`
  without adding them to the image the Dockerfile builds -- the demo is a
  separate client application, never deployed, and `CLAUDE.md`/step 4a's
  `uv sync --frozen --no-dev` in the Dockerfile already excludes every
  non-default group.
- **Steps taken**: `uv add --group demo fastapi`, which created a new
  `[dependency-groups] demo = [...]` section, separate from `dev`. Ran
  `make test` (`uv run pytest -v`, unchanged) to check the new demo tests
  collected.
- **Expected**: The new `tests/integration/test_demo_live.py` (which
  imports `demo.app`, and therefore `fastapi`) either runs or is skipped
  by its own `FIXIT_DEMO_TESTS` gate.
- **Actual**: `uv run pytest` only installs the default group (`dev`) plus
  the project itself -- a non-default group like `demo` is never installed
  unless explicitly requested with `--group demo`. Without it, collecting
  `test_demo_live.py` would fail at import time with `ModuleNotFoundError:
  fastapi` for anyone who hasn't manually run `uv sync --group demo`
  first -- not a skip, a collection error that would have broken `make
  test` for every contributor except whoever happened to have the group
  already installed locally.
- **Severity**: Medium -- would have silently broken the single command
  (`make test`) this project's own testing conventions say to run before
  considering work done, for anyone starting from a clean checkout.
- **Workaround**: Changed the Makefile's `test` target to
  `uv run --group demo pytest -v` (this also installs the default `dev`
  group, per uv's semantics -- `--group` adds to the defaults, it doesn't
  replace them). The Dockerfile's `uv sync --frozen --no-dev` is
  unaffected either way, since it never passes `--group demo`.
- **Actionable suggestion**: Adding a new named dependency group is only
  half the change -- grep for every place a plain `uv run`/`uv sync`
  already exists (Makefile targets, CI, Dockerfiles) and decide explicitly
  whether each one needs the new group, rather than assuming the default
  group covers it.

### 2026-09-28 — Step 6b: SessionManager crashed on shutdown -- a session opened in one asyncio task can't be closed from another

- **Tool/SDK**: `demo/mcp_session.py`'s `SessionManager`, anyio task
  groups (used internally by `mcp.client.streamable_http.streamable_http_client`),
  a real deployed AgentCore Runtime (SigV4-signed) via `make demo AGENT_ARN=...`.
- **Task attempted**: Verify the demo backend end to end for real -- three
  chat turns against a real deployed runtime, then a clean shutdown.
- **Steps taken**: Started the demo, ran the three-turn conversation
  (worked correctly), then sent SIGTERM for a normal shutdown.
- **Expected**: Clean shutdown -- `SessionManager.aclose()` tears down
  every open MCP session.
- **Actual**: `RuntimeError: Attempted to exit cancel scope in a different
  task than it was entered in`, crashing the shutdown with a full
  traceback (`ERROR: Application shutdown failed. Exiting.`). Root cause:
  the original `SessionManager.get()` entered the session's
  `streamable_http_client`/`ClientSession` context via an `AsyncExitStack`
  from inside whichever `/chat` request's own asyncio task called it
  first. `aclose()` then ran from FastAPI's lifespan shutdown, which is a
  *different* task. anyio's cancel scopes (used internally by
  `streamable_http_client`'s task group) are tied to the task that entered
  them, so exiting from another task fails. Actually calling the session's
  own methods (`call_tool`, `read_resource`, ...) from other tasks was
  never the problem -- all three real chat turns worked correctly across
  three separate request tasks reusing the one session; only
  entering/exiting its context is task-affine.
- **Severity**: Medium. Didn't affect any real request/response during
  actual use -- only shutdown -- but a demo backend that can't restart
  cleanly (e.g. under `make demo` iteration, or a supervisor restart) is a
  real reliability problem, and the traceback would have been alarming to
  anyone running this for the first time.
- **Workaround**: Rewrote `SessionManager` so each session's *entire*
  `async with` lifetime (open through close) runs inside one dedicated
  `asyncio.create_task` (`_SessionOwner`), coordinated with the request
  tasks via `asyncio.Event`s rather than by sharing the context-manager
  stack across tasks. Regression test added against the real local dev
  server (`tests/integration/test_demo_mcp_session.py`) -- deliberately
  *not* a fake, since a fake session object wouldn't exercise anyio's real
  task-affine cancel scopes at all and would pass either way.
- **Actionable suggestion**: Any async resource whose teardown must happen
  in the same task that created it should say so loudly in its docs --
  "AsyncExitStack-friendly" isn't a safe default assumption for something
  built on anyio task groups. Caught here only because this step insisted
  on actually starting, using, and cleanly stopping the real process
  end to end, rather than trusting that passing unit tests (which never
  opened a real session in one task and closed it in another) meant it
  worked.

### 2026-09-28 — Step 6b: live verification caught the model treating an empty safety_warnings list as "confirmed safe"

- **Tool/SDK**: `demo/orchestrator.py`'s system prompt, Amazon Bedrock
  Converse (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`), a real
  deployed AgentCore Runtime.
- **Task attempted**: Three real chat turns against the deployed runtime
  -- (a) "My dryer is showing tE1, what should I do?", (b) "Is that
  dangerous?", (c) "What appliances do I have registered?" -- judged
  strictly against the tool's actual data, per this step's explicit
  instruction to flag anything said that wasn't in a tool result.
- **Steps taken**: Ran the three turns twice: once against the original
  step 6a system prompt, and again (after the fix below) against the
  corrected one, both times with `session_setup_ms`/`turn_ms`/tool-call
  logging added this step so the two runs could be compared precisely.
- **Expected**: Turn (b) should say the manual lists no specific safety
  warning for tE1 (the real record's `safety_warnings` is `[]`) and stop
  there.
- **Actual (before the fix)**: "No, there are no specific safety warnings
  listed for this error code. The main concern is that the dryer won't
  operate properly with a failed temperature sensor, which is why it
  needs professional service. **It's safe to turn it off and wait for a
  technician to repair it.**" The first sentence is correct. The rest is
  not grounded in the tool result: "won't operate properly" is an invented
  consequence the record never stated, and "it's safe" is an affirmative
  safety judgment the record never made -- `safety_warnings: []` means no
  warning was *extracted*, not that the code was confirmed safe. The
  original system prompt only told the model not to invent a warning that
  doesn't exist; it said nothing about not inventing an *absence* of
  danger, or about not adding explanatory claims beyond what a tool
  actually said. Turns (a) and (c) were faithful to their tool results in
  every run.
- **Severity**: High for what this demo exists to prove out -- an
  appliance-repair assistant asserting something is safe, unprompted by
  its own data, is exactly the class of mistake `CLAUDE.md` rule 3 (tools
  never fabricate) is meant to prevent from reaching the customer, and the
  LLM layer is precisely where that guarantee can quietly leak back in.
- **Workaround**: Added two sentences to `SYSTEM_PROMPT_TEMPLATE`: one
  forbidding any explanation/consequence/reasoning a tool result didn't
  state, and one specifically on danger/safety questions -- answer only
  from `safety_warnings`, and an empty list means "no warning found," not
  "confirmed safe." Re-ran the identical three turns after the fix: turn
  (b) became "The manual doesn't list a specific safety warning for this
  code." and stopped there -- correct, and nothing else. Turns (a) and (c)
  were unaffected. Added a regression test
  (`test_system_prompt_forbids_treating_an_empty_warning_list_as_confirmed_safe`)
  and left the fully-quoted before/after live responses in this entry
  since they're the actual evidence, not a paraphrase.
- **Actionable suggestion**: "Never invent an X" isn't the same instruction
  as "never invent the *absence* of an X," and a tool schema using an
  empty list/None to mean "nothing found" needs the system prompt to say
  that explicitly -- an LLM will otherwise read silence as reassurance.
  This class of bug is very unlikely to be caught by fake-based unit tests
  (which supply exactly the tool result the test wrote, and never let a
  real model free-associate around it) -- it only shows up by actually
  running the real conversation and reading the real words, which is why
  this step asked for that specifically instead of trusting the units.

### 2026-09-28 — Step 6b: in a real conversation, Amazon Bedrock -- not the AgentCore cold start -- is where most of the wall-clock time goes

- **Tool/SDK**: `demo/app.py`'s new per-turn timing log
  (`session_setup_ms`/`tool_call_ms`/`turn_ms`), a real deployed AgentCore
  Runtime, real Amazon Bedrock Converse calls, measured from Dhaka.
- **Task attempted**: Break down each of the three verification turns'
  wall-clock time into cold-session setup, the MCP tool call, and
  everything else (Bedrock), per this step's explicit request.
- **Steps taken**: Instrumented `SessionManager.is_open()` +
  `/chat`'s handler to time session setup separately from `run_turn`, and
  `run_turn` to sum `usage.inputTokens`/`outputTokens` across every
  Converse call in a turn. Ran the three turns back to back (no idle gaps)
  against the real deployed runtime and read the numbers straight from the
  structured log lines, not estimated.
- **Actual** (turn a / b / c; `session_was_cold` only on turn a):
  cold session setup 2512.5 / 0 / 0 ms; MCP tool call 1746.9 / 0 / 1106.8
  ms; everything else (Bedrock Converse calls, plus one `resources/read`
  card fetch on turn a) 5982.3 / 1916.8 / 4835.5 ms; totals 10241.7 /
  1916.9 / 5942.3 ms. Summed across all three turns: **70.3% of total
  wall-clock time was Bedrock** (two Converse calls per tool-using turn,
  one per plain-reply turn), 15.8% was the MCP tool call round trip, and
  only 13.9% was the AgentCore cold session start that steps 4c-5e spent
  so much effort measuring and mitigating.
- **Severity**: Low as a "problem" (nothing is broken; the 500ms Alexa+
  budget doesn't apply to this demo, which is deliberately not the real
  Alexa+ integration path). Informational: it reframes where the next
  latency-optimization effort would actually pay off in a real multi-turn
  tool-use conversation like this one, as opposed to where step 4c-5e's
  effort went.
- **Workaround**: None -- not a bug, a measurement. Not investigated
  further here (system-prompt length, `MAX_REPLY_TOKENS=1024`, and
  growing conversation history are all plausible contributors, unverified).
- **Actionable suggestion**: Before optimizing AgentCore cold starts
  further for a conversational (not single-tool-call) workload, measure
  where a real turn's time actually goes first -- it may not be where the
  infrastructure-level investigation was looking.

### 2026-09-28 — Step 6c: the deployed MCP Apps card doesn't implement the spec's own View-side lifecycle notification

- **Tool/SDK**: MCP Apps spec (`modelcontextprotocol/ext-apps`,
  `specification/2026-01-26/apps.mdx`, fetched directly via `gh api` for
  this step, not assumed), `src/fixit_mcp/apps/diagnose_card.html`'s
  actual `<script>`.
- **Task attempted**: Build `demo/static/index.html` as an MCP Apps host
  for the existing `diagnose_error` card, per this step's explicit
  instruction to confirm the host-side handshake from the spec and from
  what the card's own JS expects, not guess.
- **Steps taken**: Read the spec's Lifecycle section (`UI Initialization`
  sequence diagram) and Sandbox Proxy section, then read
  `diagnose_card.html`'s handshake IIFE line by line.
- **Expected** (per the spec's own sequence diagram, which applies to both
  the Desktop/Native and Web host branches): after the Host responds to
  the View's `ui/initialize` request, the View sends a
  `ui/notifications/initialized` notification, and only after *that* does
  the Host send `ui/notifications/tool-input`/`tool-result`.
  `apps.mdx`'s Sandbox Proxy section states this explicitly as a hard
  requirement for that path ("The Host MUST NOT send any request or
  notification to the View before it receives an `initialized`
  notification").
- **Actual**: `diagnose_card.html`'s handshake code sends the
  `ui/initialize` request and, in its `.catch()`, only handles the host
  not supporting MCP Apps at all. There's no `.then()` that sends
  `ui/notifications/initialized`, and no code path that ever sends it.
  Waiting for it before pushing `tool-input`/`tool-result` would leave the
  card permanently blank.
- **Severity**: Medium -- not a bug in the card (it was written and
  tested, step 3d, before this SEP's `initialized` notification existed in
  its current form, or simply predates strict adherence to it), but a real
  trap for anyone implementing a host from the spec text alone: the spec
  reads as if waiting for `initialized` is universal lifecycle behavior,
  not merely the Sandbox-Proxy-specific requirement its exact wording is
  scoped to.
- **Workaround**: The host (`demo/static/index.html`) responds to
  `ui/initialize` and immediately pushes `ui/notifications/tool-input`
  then `ui/notifications/tool-result`, without waiting for
  `initialized`. Verified against a real `tE1` turn (found state renders)
  and a real `not_found`/`ambiguous_appliance` turn (muted states render)
  through `make run` + `make demo`.
- **Actionable suggestion**: When building an MCP Apps host against a
  real, already-shipped card/View, verify the View's actual handshake
  behavior by reading its code before trusting the spec's lifecycle
  diagram to describe it exactly -- an SEP evolving after a View was
  written is exactly the kind of drift that silently breaks a
  spec-literal host implementation.

### 2026-09-28 — Step 6c: a sandboxed card iframe with no `allow-same-origin` can't be measured from the host, so it can't just self-report either (it has no SDK)

- **Tool/SDK**: Browser iframe sandboxing (`sandbox="allow-scripts"`,
  deliberately without `allow-same-origin` per this step's own security
  requirement), `demo/static/index.html`.
- **Task attempted**: Size the card iframe to its content so it never
  shows a scrollbar or a large blank area, per this step's two suggested
  options: have the card send a size notification, or have the host
  measure it directly.
- **Steps taken**: Checked whether the host could read
  `iframe.contentDocument`/`scrollHeight` directly for a "measure it"
  approach.
- **Expected**: One of the two suggested options would apply cleanly:
  either the card already reports its size, or the host can just read it.
- **Actual**: Neither applies as-is. `diagnose_card.html` has no SDK and
  never sends `ui/notifications/size-changed` (see the spec's own note
  that auto-resize is a behavior of the View's *SDK*, which this
  hand-written card doesn't use). And a `sandbox="allow-scripts"` iframe
  with no `allow-same-origin` gets a unique opaque origin distinct from
  the host, so `iframe.contentDocument`/`contentWindow.document` throw a
  cross-origin `SecurityError` -- the host genuinely cannot measure it
  directly without granting `allow-same-origin`, which this step's own
  security requirement forbids pairing with `allow-scripts`.
- **Severity**: Low -- resolvable without weakening the sandbox.
- **Workaround**: A third option between the two offered: the host
  appends a small inline `ResizeObserver`-based reporter script to the
  HTML string *it* assigns to `iframe.srcdoc` (`withSizeReporter()` in
  `demo/static/index.html`), making the card behave, for sizing purposes
  only, as if its own SDK reported size -- without editing the file the
  MCP server actually serves via `resources/read`
  (`src/fixit_mcp/apps/diagnose_card.html` on disk, and what
  `tests/unit/test_diagnose_card.py` tests, are both untouched).
- **Actionable suggestion**: "Have the host measure a sandboxed
  cross-origin iframe" isn't achievable at all without `allow-same-origin`
  -- for a card with no self-reporting SDK, a host-side srcdoc-injected
  reporter is the option actually available; worth stating explicitly next
  time this class of requirement comes up in this project's docs.

### 2026-09-28 — Step 6e: two more unstated-content leaks, caught only by reading a real conversation

- **Tool/SDK**: `demo/orchestrator.py`'s `SYSTEM_PROMPT_TEMPLATE`, a real
  deployed local FixIt MCP server, real Amazon Bedrock Converse calls
  (`demo/static/index.html`'s `/chat` path), driven manually.
- **Task attempted**: Exercise a live multi-turn conversation (tE1, a
  safety follow-up, then a not_found code) and read the actual model
  output, the same verification method step 6b's safety-prompt fix used.
- **Steps taken**: Ran the same three-turn conversation twice against the
  identical live server/tool data, once with the pre-6e system prompt and
  once with the 6e prompt, and compared the real replies word for word.
- **Expected**: A `found` reply states each fact once; a `not_found`
  reply states only what the tool result actually supports (the code
  isn't in the index, `nearest_matches` if any, a suggestion to add the
  appliance if the result says to) and nothing else.
- **Actual (before)**:
  - tE1: *"The tE1 code on your LG dryer means temperature sensor
    failure. The likely cause is temperature sensor failure. To fix this,
    turn off the dryer and call for service. This is a call for service
    repair, so you'll need a technician to handle it."* -- `meaning` and
    the sole `likely_causes` entry are the same fact, stated twice, plus
    a fourth sentence restating `difficulty` as unstated advice ("you'll
    need a technician").
  - ZZ99 (`not_found`, `nearest_matches: []`, `suggest_add_appliance:
    false`): *"I don't have any manual in my index that documents an
    error code matching ZZ99. You might want to check your fridge's user
    manual directly or contact the manufacturer for help with that
    code."* -- the second sentence is pure invention; nothing in a
    `not_found` result suggests contacting a manufacturer, and the reply
    named an appliance ("your fridge") the search never actually
    confirmed (the code wasn't found anywhere in the index, not
    specifically ruled out for one appliance).
  - The safety follow-up ("Is that dangerous?") was already correct
    before this step, unaffected either way: *"The manual doesn't list a
    specific safety warning for this code."*
- **Actual (after)**: tE1: *"Code tE1 on your LG dryer means temperature
  sensor failure, and the manual says to turn off the dryer and call for
  service."* -- one sentence, each fact once. ZZ99: *"Code ZZ99 isn't in
  the manuals we have."* -- states only what the result supports, and
  correctly says nothing else since `nearest_matches` was empty and
  `suggest_add_appliance` was false on this real record. Safety follow-up
  unchanged.
- **Severity**: Medium -- same class as step 6b's finding (rule 3's
  "tools never fabricate" guarantee leaking back in at the LLM layer),
  caught the same way: fake-based unit tests supply exactly the tool
  result the test wrote and never let a real model free-associate a
  restatement or an invented next step around it.
- **Workaround**: Added three instructions to `SYSTEM_PROMPT_TEMPLATE`: a
  two-sentence-unless-asked-for-steps length cap, a "don't restate the
  same fact twice" rule (`meaning` vs `likely_causes` specifically), and
  a `not_found`-specific rule naming exactly what that status supports
  (no brand/appliance name, `nearest_matches` if non-empty, a
  suggest_add_appliance-based suggestion if true, nothing else).
  Regression tests assert each new instruction's presence in the prompt,
  same style as the existing safety-prompt test.
- **Actionable suggestion**: A `not_found` result's blank fields
  (`appliance: null`, no brand anywhere in the JSON) are easy for a model
  to read as "search this specific appliance and came up empty" rather
  than "searched the whole index and never narrowed to an appliance at
  all" -- when a schema's absence of a field is meant to convey a scope
  boundary, not just missing data, the system prompt needs to say so
  explicitly, the same lesson as step 6b's empty-`safety_warnings` case.

### 2026-09-29 — Steps 8d/8e: an intermittent demo /chat failure investigated and partially fixed, but not root-caused

- **Tool/SDK**: `demo/app.py`, `demo/orchestrator.py`, `demo/mcp_session.py`,
  the deployed AgentCore Runtime (`fixit_mcp`, v3), CloudWatch Logs, `mcp`
  1.30's `streamable_http_client`.
- **Task attempted**: Diagnose a live browser incident against the deployed
  runtime: turn 1 ("my dryer is showing tE1") succeeded (`diagnose_error`,
  2083ms, cold session); turn 2 on the *same* session ("is it still under
  warranty?") showed the frontend's generic "Sorry, something went wrong
  reaching FixIt"; the identical message, resent on the same session with
  no "new conversation" click, succeeded immediately.
- **Steps taken**: Read the frontend's fetch/catch logic (any non-2xx
  response or network-level exception collapses into that one generic
  message, with no distinguishing detail). Read `demo/app.py`'s `/chat`
  handler and found it had **no try/except and no failure-path logging at
  all** -- a failing turn produced zero application-level signal, only
  whatever uvicorn printed to a terminal nobody captured. Pulled CloudWatch
  container logs for the deployed runtime's log group
  (`/aws/bedrock-agentcore/runtimes/fixit_mcp-<runtime-id>-DEFAULT`) across
  and beyond the incident's plausible time window. Reproduced the two-turn
  pattern directly at the MCP transport layer (no Bedrock, to isolate
  transport behavior) against the live deployed runtime, 5 times with fresh
  sessions, varying the gap between the two tool calls (1/3/5/8/12s) to
  bracket a possible stale-pooled-connection window.
- **What we know (documented)**: CloudWatch showed **no trace of the actual
  failed browser request anywhere** -- only our own scripted
  smoke-test/verification traffic in the same window. **All 5 reproduction
  attempts succeeded** on the first try; turn-2 latency rose somewhat with a
  longer gap (540ms to 1450ms) but nothing ever errored.
- **What we don't know (root cause, not established)**: What specifically
  happened during the actual browser incident is **unconfirmed**. A prior
  entry in this log (step 4c) documented one intermittent 504 Gateway
  Time-out on an otherwise-healthy warm AgentCore Runtime session (about 1
  in 110 calls, the container log showing the request never arrived) with
  the same *character* as this incident -- a single dropped call, immediate
  success on retry, nothing surfaced at the application layer -- but this
  stays a **hypothesis**, not a proven cause. The 0/5 reproduction result
  neither confirms nor rules it out; it only shows the failure isn't
  trivially reproducible on demand.
- **A real bug found and fixed along the way**: while building an automatic
  retry for this class of failure, reading `mcp.client.streamable_http` --
  and proving it with a fake-transport test,
  `tests/unit/test_demo_session_recovery.py` -- showed that after a 404
  (`McpError(code=32600, message="Session terminated")`), the client
  **never clears its stored `Mcp-Session-Id`**: a retry on the same
  `ClientSession` resends the identical stale id and fails identically,
  forever. The first version of this fix (retry blindly on the same
  session) would never have worked for that specific failure mode -- caught
  by re-reading the SDK before committing, not by a production failure.
- **Severity**: Medium. The original browser incident is unconfirmed and
  not reproduced on demand; the session-terminated retry bug was real but
  narrow in scope, and was caught before being committed to `main`.
- **What the fix does and doesn't prove**: `SessionManager.evict()` plus a
  `refresh_session` callback (threaded through `orchestrator.run_turn` /
  `_dispatch_tool_call` / `_call_tool_with_retry`) now open a genuinely
  fresh MCP session (a fresh `initialize()`, a fresh session id) before
  retrying a "session terminated" failure, and `demo/app.py`'s `/chat`
  handler now logs every failure (`demo_chat_turn_failed`, with the
  operation, exception type, and whether it's classified retryable) before
  responding. This **does** prove: (a) a same-session retry for a stale or
  misrouted session id can never work (proven directly against the real SDK,
  not inferred); (b) evicting and reopening before retrying does work, end
  to end, against a real local server
  (`tests/integration/test_demo_chat_reliability.py::test_chat_recovers_through_evict_then_get_after_session_terminated`);
  (c) any future transient-transport-classified failure will now be logged,
  instead of leaving zero trace the way this one did. It does **not** prove
  that a "session terminated" error -- or any AgentCore-side hiccup at all
  -- actually caused the original browser incident; that remains
  unconfirmed, and the fix targets the *class* of failure the investigation
  could support, not a diagnosed root cause.
- **Actionable suggestion**: When a backend proxies a stateful protocol like
  MCP, log the failure path from day one, not just the success path -- the
  single biggest reason this incident couldn't be root-caused after the
  fact was that nothing recorded it happened at all.

### 2026-09-30 — the "PDF must contain the model number" check failed 2 of our 5 real manuals

- **Tool/SDK**: `scripts/add_manual.py` content check (step 11a).
- **Task attempted**: Add the automated version of the Bosch spec-sheet lesson:
  require the model number in the PDF text.
- **Steps taken**: Before trusting the rule, ran it read-only over the five
  already-downloaded, known-good manuals.
- **Expected**: All five pass.
- **Actual**: The GE fridge (`GFE28GYNFS`) and GE washer (`GTW680BSJWS`) failed:
  they are series manuals that only print `GFE28` / `GTW680`, never the full
  model. Both fine, real manuals.
- **Severity**: Medium: a strict rule would have made `add-manual` reject the
  very manuals the corpus is made of.
- **Workaround**: Fall back to the series stem (model minus its trailing letter
  run, at least 4 chars including a digit) and report it as "series", not
  "exact". `--force` remains for anything else.
- **Actionable suggestion**: Validate any new automated gate against the
  existing known-good corpus before shipping it.

### 2026-09-30 — PyMuPDF stamps a random file id, so the "idempotent re-run" test flapped

- **Tool/SDK**: PyMuPDF `Document.tobytes()` (synthetic test PDFs).
- **Actual**: Two builds of the "same" synthetic PDF differ byte for byte, so a
  hash-snapshot idempotence test failed on the re-downloaded PDF, not on any
  pipeline output.
- **Severity**: Low. **Workaround**: build the synthetic PDF once
  (`functools.cache`) so every mocked download serves identical bytes.


### 2026-09-30 — sourcing round 2: manufacturer pages hide their PDF hrefs, and the model check stumbles on wildcard model labels

- **Tool/SDK**: manufacturer support pages (LG, Samsung), `scripts/add_manual.py --dry-run`.
- **Task attempted**: Find 5 candidate manuals (LG washer, Bosch washer/oven, GE dryer, Samsung) from official domains and dry-run them (step 11b phase 1).
- **Actual**:
  - LG's and Samsung's support pages render their manual links with JavaScript, so the PDF href is not in the fetched HTML (LG's page also answered a curl with a 403). The working URLs (`media.us.lg.com/...`, `downloadcenter.samsung.com/...`) came from search results on those official domains, not from following a link on the page.
  - Bosch's oven page lists the real Use and Care manual on `media3.bsh-group.com`; the first `MCDOC...` oven URL a search returned was, again, a 3-page spec sheet.
  - The Samsung dryer manual prints its model as `DVE(G)45T6005*/DVE(G)45T6000*`, and the LG washer manual as `WM4000H*A`. The add-manual content check collapses to alphanumerics, so `DVEG45T6000` does not contain the series stem `DVE45T6000`: the Samsung dry-run reported NOT FOUND for a correct manual, and LG only passed as "series".
- **Severity**: Low to medium: nothing shipped wrongly, but a correct manual is rejected without `--force`.
- **Not fixed here** (phase 1 is research only). Idea: treat `(X)` and `*` in the manual's model label as wildcards when matching.

### 2026-09-30 — adding the LG washer and Samsung dryer: the chunk filter missed both code tables, and the PDFs' seven-segment font mangled three codes

- **Tool/SDK**: `scripts/extract_codes.py` chunk filter, the parser, LG's `WM4080_2023_Owners-Manual_Washer_Eng.pdf`, Bedrock.
- **What fought**:
  - The estimate looked over the cap ($1.12) because of a flat 1,000 output tokens per chunk, but the deeper problem was that the filter would have sent the *wrong* chunks. LG's washer table is shattered by the parser into ~25 fragments (each bold code label such as `INLET ERROR` became a false heading), and Samsung's `Information codes` section has a heading and a table the filter never matched. Tightening the filter alone would have paid to extract nothing useful.
  - Fix: a page-mode window (`extraction_pages`, a human names the pages; fragments merged into one window). Two real mistakes on the way: my first version dropped 12-char fragments like `WATER OUTLET` (half a code name, so `OE`'s meaning came out as `ERROR - ...`), and a 3,000-char window cap split UE's row across two windows. Each cost a re-extraction (~$0.13).
  - LG draws display codes in a seven-segment font; the text layer has look-alike letters: `dE2` reads `dEz`, `Sud` reads `svd`, `uS` reads `vs`. Confirmed only by rendering the page. Fixed with a manifest `code_fixes` map, not guessed.
  - The first Samsung prompt run inferred causes from repair steps ("check for a clogged lint screen" became a cause) and turned an instruction into a safety warning. Prompt tightened; but the extraction cache is keyed by chunk text, not the prompt, so it needed `--force` to take effect.
  - The calibrated per-chunk output estimate (81) undershot dense code windows by ~4x ($0.04 estimated vs $0.144 real); added a separate per-window figure.
- **Total Bedrock spend**: about $0.59 across six runs (two were re-runs caused by the mistakes above).
- **Still open**: a chunk that spans two pages cites its first page (`uS` is on p45, cited p44).

### 2026-09-30 — citations used a chunk's first page; also, the LG dryer's cache predates the cache-key fix

- **Tool/SDK**: `refine_citations`, `ManualChunk.page_start`, the extraction cache.
- **Actual**: A chunk or merged window cited its first page even when the code sat on a later one: LG `uS` (p45, cited 44) and four Bosch records (`E:34-00`, `E:90-01`, `E:92-40`, the range row: cited one page early). Chunks did not record which page each line came from, so the fix needed a new `line_pages` field on `ManualChunk`.
- **Also found**: the LG dryer's six chunks are *uncached* under the current key, because they were extracted before the cache-key fix (which added the extractor tag). Re-running `extract_codes.py` for it would silently spend ~$0.1 and rewrite its records, so its citations were checked by hand instead (all p31, one chunk spanning only p31).

### 2026-09-30 — demo: one hung turn poisoned the session, because nothing had a timeout and nothing rolled history back

- **Tool/SDK**: `demo/orchestrator.py` (`run_turn`), `demo/app.py` (`/chat`), the page's send handler.
- **What happened (live run)**: turn 1 (`add_appliance`) worked. Turn 2 ("It's showing uS...") never logged `demo_chat_turn` or `demo_chat_turn_failed` and the page showed dots forever. Turn 3 then failed with a Bedrock `ValidationException`: `tool_use ids were found without tool_result blocks`. `messages.6` was turn 3's user message and `messages.5` was turn 2's dangling assistant `toolUse`.
- **Root cause of the poisoned session (documented, from the code)**: `run_turn` appends the model's `toolUse` message to the shared history, *then* awaits the tool call and the card fetch, and only after that appends the `toolResult`. Nothing bounded those awaits, nothing restored the history if they failed or were cancelled, the input stayed enabled, and two turns could run on one `session_id` at once. So any step that never answered left a `toolUse` with no `toolResult` for every later turn.
- **Why turn 2 stalled (NOT reproduced, so inferred)**: I ran the exact sequence against the deployed runtime with throwaway households `house-repro-<random>`: fresh session, `add_appliance` (LG WM4000HWA), `diagnose_error uS` for that household, the card `read_resource`, then `remove_appliance`; five times, plus two runs where the household owns only the dryer. No hang, ever (`diagnose_error uS` 507-575 ms, the card fetch 412-497 ms, `add_appliance` 2.1-2.4 s because it is the first tool call on a new session). A household that does *not* own the washer is not slower (481-485 ms): `diagnose_error` lists the household's appliances for every call that names a household, so `tE1` and `uS` take the same path. One more run idled a session 330 s (past AgentCore's documented 300 s idle timeout) and then called `diagnose_error`: it took 8.7 s (a cold replacement microVM) and succeeded. So the likeliest story is that one request to the runtime, or the card fetch, never got its response, and with no timeout the turn waited forever; but I could not make that happen on demand. Every repro appliance was removed and each household listed empty afterwards.
- **What changed**: history snapshot restored on every failure path (exception, timeout, `CancelledError`, and the `max_rounds` fallback, which used to leave the history ending on tool results, so the next message was a second consecutive user turn); `repair_history` drops a dangling `toolUse` (and orphan results, and merges the resulting adjacent user messages) and logs `demo_history_repaired`; per-step time budgets (tool/card 15 s, Converse 30 s, whole turn 90 s, in `DemoSettings`) that end as a logged `demo_chat_turn_failed` naming the operation and `timeout_s` plus a 504; a per-session lock with a 409 `turn_in_progress`; the page disables input, send, mic and "New conversation" while a turn is pending and aborts a request after 120 s. Repair itself had a bug the first test caught: after dropping the dangling message the new user message was a second consecutive user turn, so it is now merged into the last one, which is why the rollback snapshot is a deep copy.
- **Still open**: an abandoned `asyncio.to_thread` Converse call cannot be cancelled, so a timed-out Bedrock call keeps its thread until the boto3 read timeout ends it (set to the budget + 5 s).
