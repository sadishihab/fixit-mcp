# Add a second manual for an appliance type that already has one

## Description

Every appliance type has exactly one manual today. Add a second model of one type so diagnosis can be tried against two manuals of the same type, and check that a code shared by both brands still gives an `ambiguous_appliance` answer for a household owning both (or add a unit test that shows it).

## Acceptance criteria

- [ ] A new manual added via `make add-manual` (see CONTRIBUTING.md).
- [ ] A test in `tests/unit/test_diagnose_tool.py` covers the same code appearing in two manuals for one household.
- [ ] `make test` passes.

## Files to touch

- `data/manuals/manifest.yaml`
- `data/index/error_codes.json`
- `tests/unit/test_diagnose_tool.py`
