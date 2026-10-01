# Contributing: adding an appliance manual

FixIt's knowledge base is built from real manufacturer manuals. Adding one is a
single command; you don't need to touch the pipeline internals.

## Add a manual in one command

```bash
make add-manual ID=acme-x100-oven BRAND=Acme MODEL=X100 TYPE=oven \
  URL=https://example.com/x100-owners-manual.pdf \
  NOTE="Linked from Acme's public support page for the X100; no login, free download."
```

Check first, change nothing: add `DRY_RUN=1`. Other switches: `FORCE=1`
(override the content check) and `YES=1` (skip the Bedrock cost prompt). Avoid
double quotes inside `NOTE`.

It runs, and reports, each step:

1. Validates the arguments. Refuses a duplicate `ID` or a duplicate brand+model.
2. Downloads the URL and checks it is a real PDF (magic bytes, page count),
   using the same code as `make fetch-manuals`.
3. Content check: the PDF must contain the model number (exactly, via a wildcard label such as `WM4000H*A`, or its series stem,
   e.g. `GFE28` for `GFE28GYNFS`) and a troubleshooting/error-code keyword.
   This exists because a filename or search title proves nothing: a real,
   valid, model-correct PDF turned out to be a 3-page spec sheet
   (see `FRICTION_LOG.md`). `--dry-run` stops here.
4. Appends the entry to `data/manuals/manifest.yaml` and keeps the PDF in
   `data/manuals/pdf/` (gitignored).
5. Parses it (including the font-encoding repair) into `data/manuals/parsed/`.
6. Extracts records with `FIXIT_EXTRACTOR=stub|bedrock` (default `stub`, no AWS).
   With `bedrock` it first prints the chunks to send and the estimated tokens
   and cost, and needs you to type `yes`.
7. Merges the records into `data/index/error_codes.json`, replacing only this
   manual's records. Re-running the same command is safe and idempotent.

If the automatic chunk filter misses the code table (some PDFs are split into
tiny fragments, so the table's chunks do not look like a table), open the PDF,
note the pages that hold the table, and pass `CODE_PAGES=43-45`. Only those
pages are sent, merged into one window so a row is never split. It is stored in
the manifest as `extraction_pages`, so `make extract-codes` repeats it.

Some PDFs draw display codes in a seven-segment font whose text layer uses
look-alike letters (LG prints `dE2` as `dEz`). If you find one, check the
rendered page and add `code_fixes: {dEz: dE2}` to the manifest entry. Never
guess a correction.

Then run `make validate-manifest` and `make test`, review the diff, and commit
the manifest and index. **Never commit the PDF.**

The stub extractor only recognises a few known code shapes and fills in no
meaning or steps. For real records use `FIXIT_EXTRACTOR=bedrock` (needs AWS
credentials and Bedrock model access).

A new manual only reaches the deployed server after an image rebuild and a
runtime update (`make docker-build docker-push deploy-runtime`); the index is
baked into the image.

## Symptom tables (the GE refrigerator and washer so far)

A manual's "Problem / Possible Causes / What To Do" tables are extracted
separately, into `data/index/symptoms.json`, for the `diagnose_symptom` tool:

```bash
make extract-symptoms DRY_RUN=1      # read the tables, print row counts and the cost estimate, call nothing
make extract-symptoms                # asks before spending; Amazon Nova Pro only, never Claude
make extract-symptoms MANUAL=<id> YES=1 MAX_COST=0.5
```

It reads each table from the PDF geometry and refuses to write a manual's rows unless
every table passes the audit (expected row count; each row's text, joined, equal to its
source cell). Open the rendered pages and spot-check a few rows before committing. Only
manuals whose tables are ruled and have the three columns are supported; the default
manuals are listed in `scripts/extract_symptoms.py`. The index is baked into the image like
the error-code index.

## What makes a good source

- A **freely downloadable, official** PDF from the manufacturer: a public
  support page or their own document CDN, no login.
- It contains an **error-code table** (code, meaning, what to do). A real code
  table beats symptom prose ("if the dishwasher is noisy...") by a wide margin:
  FixIt looks codes up exactly, and prose gives it nothing to key on.
- The full owner's/use-and-care manual, not a spec sheet, install guide, or
  quick-start card.
- Check the URL works from a script, not just a browser. Some CDNs (Whirlpool's,
  for one) answer every non-browser request with a 403.

## Terms of use

Extracted records are committed and shipped in the container image. Before you
add a manual, read the manufacturer's terms and make sure redistributing
extracted facts (codes, meanings, repair steps, cited to the manual) is
acceptable. Say in `NOTE` where the URL came from and why it is freely
downloadable; the tool refuses an empty note. If the terms forbid it, don't add
the manual.

## How we measure grounding

"No invented answers" is measured, not assumed. `evals/cases.yaml` holds about 60
questions: found codes from every manual that has codes, safety questions where the
manual lists no warning, not-found codes (including a real Bosch code our manual
lacks, to catch answers from the model's memory), the ambiguous `PF`, warranty
questions (active, expired, unknown, ambiguous, not registered), add/list/remove
flows, and adversarial follow-ups ("is it safe to keep using it?", "how much will the
repair cost?", "is it covered?", "what's the phone number?").

```bash
make run                       # terminal 1: the local server
make eval                      # terminal 2: all cases once (needs AWS credentials for Bedrock)
make eval REPEAT=3             # final numbers, with run-to-run variance
make eval CASE=adv-repair-cost # one case
uv run --group demo python scripts/run_eval.py --estimate-only   # cost first
```

Each case runs through the real demo orchestrator (the same system prompt and tool
loop) against the local server, in a fresh `house-eval-<random>` household seeded
through `add_appliance` and removed afterwards. The final reply is graded twice:

1. **Deterministic checks:** the expected tool was called, with the right key
   arguments and the case's own household; the reply includes or avoids given
   phrases (for example, warranty replies must say "recorded", cost answers must not
   contain a dollar amount).
2. **A judge:** a second, stronger model (default `us.anthropic.claude-opus-4-6-v1`,
   the strongest this account can invoke; `--probe-models` re-checks, `--judge-model`
   changes it) gets only the tool results and the reply, and lists every factual
   claim the results do not support. A case is grounded when that list is empty.

The run prints an estimate and refuses to start above `--max-cost` (default $10),
and stops if real spend passes it. Results are saved to `evals/results-<time>.json`
(gitignored) and printed as a markdown table, with the reply and the unsupported
claim for every failure. The judge is evaluation tooling only: the server never
imports it.

**What this cannot catch.** The judge is a model and can be wrong in both
directions. It can accept a claim that sounds supported but is not (a paraphrase that
quietly changes meaning, advice such as "contact a service provider" read as implied
by "call for service"), or flag a fair paraphrase. It sees only the tool results and
the final reply, not the question, so it cannot tell whether the reply answered the
question, and earlier replies in a multi-turn case are not graded. It also cannot
check that the tool results themselves are right: that is the extraction audit's
job. A passing eval means "no unsupported claim was found", not "proven grounded".
Read the failures, and spot-check some passes.

## Running the tests

```bash
make test                # everything, including manifest validation
make validate-manifest   # just the manifest checks
make lint && make format
```

The `add_manual` tests use synthetic PDFs generated inside the tests and mocked
HTTP: no real manual, no network, no AWS.

## Issue labels

| Label | Use it for |
|---|---|
| `good first issue` | Small and well-scoped: a newcomer can finish it in an afternoon. See [`docs/good-first-issues/`](docs/good-first-issues/). |
| `help wanted` | A maintainer would welcome a contribution but has no time to do it soon. |
| `new manual` | Adding a manufacturer manual, or requesting one (the "Request a manual" template applies it). |
| `parser` | Manual parsing: headings, tables, text repair, chunking (`fixit_mcp.ingestion`). |
| `docs` | README, CONTRIBUTING, and other documentation. |

## Reporting a manual that parses badly

Open an issue with: the manual id, its `source_url`, the page(s) where the
error-code table is, what `make parse-manuals` (or the `add-manual` output)
reported, and what came out wrong (missing codes, garbled text, wrong section).
Garbled characters usually mean a broken font encoding; see
`FRICTION_LOG.md` and `fixit_mcp/ingestion/text_repair.py`. Don't attach the PDF
if the manufacturer's terms don't allow redistributing it; the URL is enough.
