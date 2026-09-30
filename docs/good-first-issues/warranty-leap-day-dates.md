# Warranty: pin down leap-day end dates with tests

## Description

A warranty ending on `2024-02-29` should give exact day counts around the leap day. The logic is plain date subtraction, so this is mostly about adding tests that prove it. Expected results for an end date of `2024-02-29`:

| `as_of` | status | count |
|---|---|---|
| 2024-02-28 | `active` | `days_remaining == 1` |
| 2024-02-29 | `active` | `days_remaining == 0` |
| 2024-03-01 | `expired` | `days_since_expiry == 1` |
| 2025-02-28 | `expired` | `days_since_expiry == 365` |
| 2025-03-01 | `expired` | `days_since_expiry == 366` |

## Acceptance criteria

- [ ] Tests for the five rows above in `tests/unit/test_warranty_tool.py`, using the existing `make_appliance`/`repo_with` helpers.
- [ ] The message text uses the singular "1 day" for the 1-day rows.
- [ ] No production code change unless a test finds a bug.

## Files to touch

- `tests/unit/test_warranty_tool.py`
- `src/fixit_mcp/tools/warranty.py` (only if a test finds a bug)
