# Parser: recognise two-column 'code  meaning' lists as tables

## Description

`looks_like_table` decides whether a section is worth sending to extraction. It only fires when the text contains a problem-side word (`problem`, `error code`, `possible causes`, ...) and a solution-side word (`solution`, `what to do`, ...). A list shaped like `E4   Door not closed` (short code, gap, sentence) has neither, so `looks_like_table("E4   Door not closed\nE5   Water supply problem\nE6   Drain problem")` returns `False` today. Add a conservative rule for this shape, and synthetic tests for a positive and a negative case (prose that merely contains short words).

## Acceptance criteria

- [ ] Positive test: a list of at least three `code  meaning` lines is table-like.
- [ ] Negative test: an ordinary paragraph is not.
- [ ] Existing tests still pass, including `tests/unit/test_extract_filter.py` (which proves the chunk filter never drops a chunk that already produced a record).
- [ ] `make test` passes.

## Files to touch

- `src/fixit_mcp/ingestion/parser.py`
- `tests/unit/test_ingestion_parser.py`
