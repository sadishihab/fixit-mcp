# Test: the real `PF` code is ambiguous for a household that owns both LG appliances

## Description

`PF` is documented in two manuals in the committed index: the LG dryer (`lg-dlex8000w-dryer`) and the LG washer (`lg-wm4000hwa-washer`). `diagnose_error` must return `ambiguous_appliance` for a household that owns both, never pick one. Today this is covered only with synthetic records in `tests/unit/test_diagnose_tool.py`; nothing pins it on the real data, so a re-extraction that changed either manual's `PF` record could break it unnoticed.

Add tests that load the real index with `load_index()` (see `fixit_mcp.retrieval.codes`) and call `diagnose` for `PF` against a small in-memory household.

## Acceptance criteria

- [ ] A household owning both LG appliances gets `status == "ambiguous_appliance"`, with both models in `candidate_appliances` and no diagnosis content in the response.
- [ ] A household owning only the LG washer gets `status == "found"` for `PF`, citing the WM4000HWA manual (page 44).
- [ ] No production code change unless a test finds a bug.
- [ ] `make test` passes.

## Files to touch

- `tests/unit/test_diagnose_tool.py` (or a new `tests/unit/test_diagnose_real_index.py`)
