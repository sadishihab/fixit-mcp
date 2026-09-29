# Parser: do not treat bold 'NOTE:' or 'WARNING' labels as section headings

## Description

Heading detection is heuristic. A bold label at body size such as `NOTE:` can start a bogus section and split a table from its heading (see FRICTION_LOG.md, bold-at-body-size false headings). Tighten `heading_info` so short bold callout labels are not headings, proven with a synthetic PDF or `Line` objects (never a real manual).

## Acceptance criteria

- [ ] A new test builds `Line` objects (or a PDF generated in the test) with a bold `NOTE:` line inside a troubleshooting section and asserts one section, not two.
- [ ] Existing parser tests still pass.
- [ ] No real manual is added to the repo.

## Files to touch

- `src/fixit_mcp/ingestion/parser.py`
- `tests/unit/test_ingestion_parser.py`
