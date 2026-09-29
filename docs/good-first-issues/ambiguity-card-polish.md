# Visual card: polish the ambiguous-appliance state

## Description

When a code exists for several of a household's appliances the card lists candidates plainly. Show brand, model and appliance type in a consistent order, make sure long model names wrap on a narrow view, and add a test that HTML in a candidate field is escaped. The card has no click handlers by design; keep it that way.

## Acceptance criteria

- [ ] `buildCardHtml` output for `ambiguous_appliance` lists each candidate as brand model (type).
- [ ] A Node-run test in `tests/unit/test_diagnose_card.py` checks escaping (`<` becomes `&lt;`).
- [ ] The `found` and `not_found` renderings are unchanged.

## Files to touch

- `src/fixit_mcp/apps/diagnose_card.html`
- `tests/unit/test_diagnose_card.py`
