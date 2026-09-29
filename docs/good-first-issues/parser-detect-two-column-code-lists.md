# Parser: recognise two-column 'code  meaning' lists as tables

## Description

`looks_like_table` decides whether a chunk is worth sending to extraction. Lists shaped like `E4   Door not closed` (short code, gap, sentence) may be missed. Add a conservative rule, and a synthetic test for both a positive and a negative case (prose that merely contains short words).

## Acceptance criteria

- [ ] Positive test: a two-column code list is table-like.
- [ ] Negative test: an ordinary paragraph is not.
- [ ] `make test` passes.

## Files to touch

- `src/fixit_mcp/ingestion/parser.py`
- `tests/unit/test_ingestion_parser.py`
