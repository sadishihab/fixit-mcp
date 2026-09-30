# Warranty: handle a purchase date later than the warranty end date

## Description

`check_warranty` compares dates only. If a household registered a `purchase_date` after `warranty_end_date` (a typo), the answer looks confident (`active` or `expired` from the end date alone) but the recorded data is inconsistent. Propose in the issue thread what the response should be (likely `status="unknown"` with a message saying the recorded dates conflict), then implement it. Keep the rule that the message states only recorded facts, says "recorded", and makes no coverage claim.

## Acceptance criteria

- [ ] Agreed behaviour written in the issue.
- [ ] A test in `tests/unit/test_warranty_tool.py` covers the conflicting-dates case.
- [ ] The boundary test (end date equals today is still `active`) still passes.
- [ ] `make test` passes.

## Files to touch

- `src/fixit_mcp/tools/warranty.py`
- `tests/unit/test_warranty_tool.py`
