# Warranty: pin down leap-day end dates with tests

## Description

A warranty ending on `2024-02-29` and checked on `2025-02-28` / `2025-03-01` should report exact day counts. The logic is plain date subtraction, so this is mostly about adding tests that prove it.

## Acceptance criteria

- [ ] Tests for as_of dates just before and after a leap-day end date, asserting `status` and `days_remaining` / days-since values.
- [ ] No production code change unless a test finds a bug.

## Files to touch

- `tests/unit/test_warranty_tool.py`
- `src/fixit_mcp/tools/warranty.py`
