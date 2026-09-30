# Visual card: let long model names wrap on a narrow view

## Description

The `ambiguous_appliance` card already lists each candidate as `brand model (type)` and escapes HTML in candidate fields (both tested in `tests/unit/test_diagnose_card.py`). What is missing is layout: model numbers such as `WM4000H*A / WM4080H*A` or a long unbroken string can push the `.suggestions` lists (used by the ambiguous and not-found states) wider than a phone-width host view. Add a CSS rule so those items wrap, and check the result in a ~320px-wide viewport.

The card has no click handlers by design; keep it that way.

## Acceptance criteria

- [ ] `.suggestions li` wraps long unbroken text (for example `overflow-wrap: anywhere`), checked by eye in a ~320px viewport; say how you checked in the PR.
- [ ] A test in `tests/unit/test_diagnose_card.py` asserts the rule is present in the template.
- [ ] `buildCardHtml` output for all three statuses is unchanged.
- [ ] `make test` passes.

## Files to touch

- `src/fixit_mcp/apps/diagnose_card.html`
- `tests/unit/test_diagnose_card.py`
