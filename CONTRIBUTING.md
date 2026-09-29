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
3. Content check: the PDF must contain the model number (or its series stem,
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

Then run `make validate-manifest` and `make test`, review the diff, and commit
the manifest and index. **Never commit the PDF.**

The stub extractor only recognises a few known code shapes and fills in no
meaning or steps. For real records use `FIXIT_EXTRACTOR=bedrock` (needs AWS
credentials and Bedrock model access).

A new manual only reaches the deployed server after an image rebuild and a
runtime update (`make docker-build docker-push deploy-runtime`); the index is
baked into the image.

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

## Running the tests

```bash
make test                # everything, including manifest validation
make validate-manifest   # just the manifest checks
make lint && make format
```

The `add_manual` tests use synthetic PDFs generated inside the tests and mocked
HTTP: no real manual, no network, no AWS.

## Reporting a manual that parses badly

Open an issue with: the manual id, its `source_url`, the page(s) where the
error-code table is, what `make parse-manuals` (or the `add-manual` output)
reported, and what came out wrong (missing codes, garbled text, wrong section).
Garbled characters usually mean a broken font encoding; see
`FRICTION_LOG.md` and `fixit_mcp/ingestion/text_repair.py`. Don't attach the PDF
if the manufacturer's terms don't allow redistributing it; the URL is enough.
