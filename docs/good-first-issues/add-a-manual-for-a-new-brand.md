# Add a manual for a brand not yet in the knowledge base

## Description

The manifest covers GE, Bosch and LG. Pick a brand that is missing (for example Samsung, Frigidaire, Miele, Electrolux) and add one of its appliance manuals with `make add-manual`. Avoid brands whose CDN blocks scripts (Whirlpool answers every non-browser request with a 403; see FRICTION_LOG.md).

## Acceptance criteria

- [ ] The PDF is a free, official, full owner's manual with an error-code table, and you read the manufacturer's terms.
- [ ] `make add-manual ... DRY_RUN=1` passes the content check without `FORCE=1`.
- [ ] The manifest entry has a `source_note` saying where the URL came from and why it is free.
- [ ] `data/index/error_codes.json` gains records for the new manual and existing records are unchanged in the diff.
- [ ] `make validate-manifest` and `make test` pass; no PDF is committed.

## Files to touch

- `data/manuals/manifest.yaml`
- `data/index/error_codes.json`
