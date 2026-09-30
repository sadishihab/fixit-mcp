# Parser: do not treat bare 'NOTE' / 'WARNING' / 'CAUTION' callout labels as section headings

## Description

Heading detection in `heading_info` is heuristic. A callout label written without a colon, such as a bold `WARNING` or `NOTE` on its own line, passes `is_allcaps_heading` and becomes a section heading, which can split a troubleshooting table from its real heading (see FRICTION_LOG.md, bold-at-body-size false headings). Today `heading_info` returns `(True, 1)` for `Line(1, "WARNING", 10.0, True)` at a 10.0 body size, whereas `NOTE:` and `CAUTION:` (with a colon) are already rejected.

Tighten the rule so bare callout labels are not headings, and keep genuine all-caps headings such as `TROUBLESHOOTING TIPS`. Prove it with `Line` objects or a PDF generated inside the test, never a real manual.

## Acceptance criteria

- [ ] `heading_info` returns `None` for a bare `WARNING`, `NOTE` and `CAUTION` line, and still returns a heading for `TROUBLESHOOTING TIPS`.
- [ ] A test builds a section list containing a bare `WARNING` line inside a troubleshooting section and asserts one section, not two.
- [ ] Existing parser tests still pass.
- [ ] No real manual is added to the repo.

## Files to touch

- `src/fixit_mcp/ingestion/parser.py`
- `tests/unit/test_ingestion_parser.py`
