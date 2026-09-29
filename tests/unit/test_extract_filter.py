"""The chunk filter in scripts/extract_codes.py: synthetic cases for each rule,
plus a guard over the real parsed manuals (skipped when data/manuals/parsed is
absent, e.g. in CI: those files are gitignored derived data) proving the
tightened filter never drops a chunk that produced a record."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from fixit_mcp.ingestion.parser import ManualChunk, looks_like_table

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
REPO_ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("fixit_extract_codes", SCRIPTS / "extract_codes.py")
ec = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ec
spec.loader.exec_module(ec)


def chunk(
    text: str, heading: str | None = "Troubleshooting", *, table: bool = False, page: int = 1, n: int = 0
):
    return ManualChunk(
        manual_id="m", brand="B", model="M1", appliance_type="oven", chunk_id=f"m::chunk-{n:04d}",
        text=text, page_start=page, page_end=page, section_heading=heading, section_path=[], is_table=table,
    )  # fmt: skip


def test_bare_heading_stub_is_dropped() -> None:
    assert not ec.is_worth_extracting_from(chunk("TROUBLESHOOTING"))
    assert not ec.is_worth_extracting_from(chunk("Troubleshooting Tips... Before you call ", table=True))


def test_toc_entry_is_dropped() -> None:
    toc = "Troubleshooting Tips . . . 22-24\nCare and Cleaning . . . . 18"
    assert ec.is_toc_entry(toc)
    assert not ec.is_worth_extracting_from(chunk(toc + " " * 5, table=True))


def test_real_table_chunk_and_long_troubleshooting_prose_still_pass() -> None:
    table = "Code Meaning\nE1  Door open. Close the door.\nE2  Sensor fault. Call service.\n" * 3
    assert ec.is_worth_extracting_from(chunk(table, "Errors", table=True))
    assert ec.is_worth_extracting_from(chunk("If the unit will not start, check the plug. " * 4))


def test_ordinary_prose_still_does_not_pass() -> None:
    assert not ec.is_worth_extracting_from(chunk("Wash the filter monthly. " * 10, "Care"))


def test_calibrated_output_estimate_is_the_documented_ratio() -> None:
    assert ec.CALIBRATED_OUTPUT_TOKENS_PER_CHUNK == round(3311 / 41)


def test_page_spec_parsing() -> None:
    assert ec.parse_page_spec("43-45,48") == {43, 44, 45, 48}
    assert ec.parse_page_spec("7") == {7}
    with pytest.raises(ValueError):
        ec.parse_page_spec("x")


def test_named_pages_are_sent_alone_and_merged_into_windows() -> None:
    chunks = [
        chunk("Special features table text. " * 5, table=True, page=42, n=1),
        chunk("Code table part one, long enough to keep as a real chunk of text.", "Codes", page=48, n=2),
        chunk("WATER OUTLET", "ERROR", page=48, n=3),  # half a code name: kept in page mode
        chunk("Part two of the same table, also long enough to be kept as a chunk.", "More", page=48, n=4),
        chunk("Fabric care chart text that is not a code table.", "Specs", page=49, n=5),
    ]
    windows = ec.select_candidates(chunks, {48})
    assert len(windows) == 1
    assert windows[0].chunk_id == "m::chunk-0002"  # traceable to the first merged chunk
    assert "part one" in windows[0].text and "Part two" in windows[0].text
    assert "WATER OUTLET" in windows[0].text
    assert ec.select_candidates(chunks, None) != windows  # no pages: heuristic filter


def test_windows_respect_the_size_cap() -> None:
    chunks = [chunk("x" * 5000, "H", page=3, n=i) for i in range(3)]
    windows = ec.select_candidates(chunks, {3})
    assert len(windows) == 3 and all(len(w.text) <= ec.WINDOW_MAX_CHARS for w in windows)


PARSED = REPO_ROOT / "data" / "manuals" / "parsed"
INDEX = REPO_ROOT / "data" / "index" / "error_codes.json"
EXISTING_FIVE = [
    "bosch-she53b75uc-dishwasher",
    "ge-gfe28gynfs-refrigerator",
    "ge-gtw680bsjws-washer",
    "ge-jbp26-range",
    "lg-dlex8000w-dryer",
]


def _old_filter(c: ManualChunk) -> bool:
    return (
        c.is_table
        or looks_like_table(c.text)
        or bool(ec._TROUBLESHOOTING_HEADING_RE.search(c.section_heading or ""))
    )


@pytest.mark.skipif(
    not all((PARSED / f"{m}.json").exists() for m in EXISTING_FIVE) or not INDEX.exists(),
    reason="parsed manuals are gitignored derived data (run make parse-manuals)",
)
@pytest.mark.parametrize("manual_id", EXISTING_FIVE)
def test_tightened_filter_keeps_every_chunk_that_produced_a_record(manual_id) -> None:
    chunks = [ManualChunk.model_validate(c) for c in json.loads((PARSED / f"{manual_id}.json").read_text())]
    producers = {r["source_chunk_id"] for r in json.loads(INDEX.read_text()) if r["manual_id"] == manual_id}
    new = {c.chunk_id for c in chunks if ec.is_worth_extracting_from(c)}
    old = {c.chunk_id for c in chunks if _old_filter(c)}
    assert producers <= new, f"dropped a record-producing chunk: {sorted(producers - new)}"
    assert new <= old, "the new filter must only ever send fewer chunks than the old one"


def test_window_records_cite_the_page_where_the_code_actually_appears() -> None:
    chunks = [
        chunk("Intro text for the table, long enough to be a chunk.", "Codes", page=43, n=1),
        chunk("dE, dE1  The door is not secured. Close it and restart.", "More", page=44, n=2),
    ]
    window = ec.select_candidates(chunks, {43, 44})[0]
    assert window.page_start == 43

    def record(code: str):
        return ec.ErrorCodeRecord(
            manual_id="m", brand="B", model="M1", appliance_type="oven", error_code=code,
            code_normalized=code.upper(), source_page=window.page_start, source_section="Codes",
            source_chunk_id=window.chunk_id, extraction_confidence=0.9,
        )  # fmt: skip

    refined = ec.refine_citations([record("dE1"), record("zz9")], chunks, {43, 44})
    assert (refined[0].source_page, refined[0].source_chunk_id) == (44, "m::chunk-0002")
    assert refined[1].source_page == 43  # not found anywhere: keeps the window's citation
    assert not ec.refine_citations([record("E")], chunks, {43, 44})[0].source_page == 0


def test_code_fixes_replace_the_code_and_renormalize_it() -> None:
    def record(code: str):
        return ec.ErrorCodeRecord(
            manual_id="m", brand="B", model="M1", appliance_type="oven", error_code=code,
            code_normalized=code.upper(), source_page=1, source_section=None,
            source_chunk_id="m::chunk-0001", extraction_confidence=0.9,
        )  # fmt: skip

    fixed = ec.apply_code_fixes([record("dEz"), record("dE1")], {"dEz": "dE2"})
    assert [(r.error_code, r.code_normalized) for r in fixed] == [("dE2", "DE2"), ("dE1", "DE1")]


def test_manifest_extras_read_pages_and_code_fixes(tmp_path) -> None:
    manifest = tmp_path / "m.yaml"
    manifest.write_text("- id: a\n  extraction_pages: 43-45\n  code_fixes:\n    x: y\n- id: b\n")
    extras = ec.load_manifest_extras(manifest)
    assert extras["a"] == {"pages": {43, 44, 45}, "code_fixes": {"x": "y"}}
    assert extras["b"] == {"pages": None, "code_fixes": {}}
