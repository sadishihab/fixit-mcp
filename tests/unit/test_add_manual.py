"""scripts/add_manual.py end to end, with synthetic PDFs generated here and
all HTTP mocked -- no real manual, no network, no AWS."""

import argparse
import functools
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pymupdf
import pytest
import yaml

from fixit_mcp.ingestion.extraction import BedrockExtractor

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"fixit_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


add_manual = _load("add_manual")

URL = "https://docs.example.com/x100.pdf"
NOTE = "Linked from Acme's public support page; no login, freely downloadable."
MANIFEST_HEADER = "# test manifest header comment\n\n"

OTHER_RECORD = {
    "manual_id": "other-manual",
    "brand": "Other",
    "model": "O1",
    "appliance_type": "washer",
    "error_code": "F9",
    "code_normalized": "F9",
    "meaning": "kept exactly",
    "likely_causes": ["a", "b"],
    "extra_future_field": {"nested": [1, 2, 3]},
}


@functools.cache  # PyMuPDF stamps a random file id, so rebuilding would change the bytes
def make_pdf(kind: str = "manual", model: str = "X100") -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72.0
    page.insert_text((72, y), f"Acme {model} Oven Owner's Manual", fontsize=20, fontname="hebo")
    y += 40
    page.insert_text((72, y), "1 Safety", fontsize=16, fontname="hebo")
    y += 24
    for _ in range(3):
        page.insert_text((72, y), "Read all instructions before using the oven.", fontsize=10)
        y += 14
    y += 20
    if kind == "manual":
        page.insert_text((72, y), "2 Troubleshooting", fontsize=16, fontname="hebo")
        y += 24
        for line in [
            "Error codes",
            "E:24-00  Drain pump fault.",
            "E:34-00  Water inlet fault.",
            "tE1  Open circuit.",
        ]:
            page.insert_text((72, y), line, fontsize=10)
            y += 14
    elif kind == "spec_sheet":
        page.insert_text((72, y), "2 Specifications", fontsize=16, fontname="hebo")
        y += 24
        page.insert_text((72, y), "Width 30 in. Wattage 2400 W.", fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


def transport(routes: dict[str, tuple[int, bytes, str]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        status, body, ctype = routes.get(str(request.url), (404, b"nope", "text/html"))
        return httpx.Response(status, content=body, headers={"content-type": ctype})

    return httpx.MockTransport(handler)


def pdf_route(kind: str = "manual", model: str = "X100") -> httpx.MockTransport:
    return transport({URL: (200, make_pdf(kind, model), "application/pdf")})


@pytest.fixture
def paths(tmp_path: Path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        MANIFEST_HEADER
        + yaml.safe_dump(
            [
                {
                    "id": "other-manual",
                    "brand": "Other",
                    "model": "O1",
                    "appliance_type": "washer",
                    "source_url": "https://o.example.com/o1.pdf",
                    "source_note": "an existing entry with a long enough note",
                }
            ],
            sort_keys=False,
        )
    )
    index = tmp_path / "index" / "error_codes.json"
    index.parent.mkdir()
    index.write_text(json.dumps([OTHER_RECORD], indent=2))
    return add_manual.Paths(
        manifest=manifest,
        pdf_dir=tmp_path / "pdf",
        parsed_dir=tmp_path / "parsed",
        index=index,
        cache_dir=tmp_path / "index" / ".cache",
    )


def make_args(**overrides) -> argparse.Namespace:
    values = {
        "id": "acme-x100-oven",
        "brand": "Acme",
        "model": "X100",
        "type": "oven",
        "url": URL,
        "note": NOTE,
        "dry_run": False,
        "force": False,
        "yes": False,
        "allow_downgrade": False,
        "code_pages": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def run(
    paths, capsys=None, *, tr=None, extractor=None, input_fn=None, **arg_overrides
) -> tuple[int, list[str]]:
    lines: list[str] = []
    code = add_manual.run(
        make_args(**arg_overrides),
        paths,
        transport=tr or pdf_route(),
        extractor=extractor or add_manual.StubExtractor(),
        input_fn=input_fn or (lambda _: pytest.fail("unexpected prompt")),
        say=lines.append,
    )
    return code, lines


def snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# --- rejection ---------------------------------------------------------------


def test_duplicate_id_with_different_fields_is_rejected(paths) -> None:
    before = snapshot(paths.manifest.parent)
    code, lines = run(paths, id="other-manual")
    assert code == 1
    assert "already exists" in "\n".join(lines)
    assert snapshot(paths.manifest.parent) == before


def test_duplicate_brand_and_model_under_a_new_id_is_rejected(paths) -> None:
    before = snapshot(paths.manifest.parent)
    code, lines = run(paths, brand="other", model="o1")
    assert code == 1
    assert "already in the manifest as 'other-manual'" in "\n".join(lines)
    assert snapshot(paths.manifest.parent) == before


@pytest.mark.parametrize("note", ["", "   ", "free"])
def test_missing_or_trivial_note_is_rejected(paths, note) -> None:
    code, lines = run(paths, note=note)
    assert code == 1
    assert "--note is required" in "\n".join(lines)


def test_bad_id_and_non_http_url_are_rejected(paths) -> None:
    assert run(paths, id="Bad Id!")[0] == 1
    assert run(paths, url="file:///etc/passwd")[0] == 1


def test_a_403_and_a_non_pdf_body_are_rejected(paths) -> None:
    code, lines = run(paths, tr=transport({URL: (403, b"denied", "text/html")}))
    assert code == 1 and "download failed" in "\n".join(lines)
    code, lines = run(paths, tr=transport({URL: (200, b"<html>login</html>", "text/html")}))
    assert code == 1 and "not a PDF" in "\n".join(lines)


def test_spec_sheet_without_troubleshooting_content_is_rejected(paths) -> None:
    before = snapshot(paths.manifest.parent)
    code, lines = run(paths, tr=pdf_route("spec_sheet"))
    assert code == 1
    assert "no troubleshooting or error-code keyword" in "\n".join(lines)
    assert snapshot(paths.manifest.parent) == before


def test_pdf_for_the_wrong_model_is_rejected(paths) -> None:
    code, lines = run(paths, tr=pdf_route("manual", model="Z999"))
    assert code == 1
    assert "'X100' never appears" in "\n".join(lines)


def test_force_overrides_the_content_check(paths) -> None:
    code, _ = run(paths, tr=pdf_route("spec_sheet"), force=True)
    assert code == 0
    assert any(e["id"] == "acme-x100-oven" for e in yaml.safe_load(paths.manifest.read_text()))


def test_series_stem_counts_as_a_model_match(paths) -> None:
    code, lines = run(paths, model="X100ABC", tr=pdf_route("manual", model="X100"))
    assert code == 0
    assert "series" in "\n".join(lines)


@pytest.mark.parametrize(
    ("model", "text"),
    [
        ("DVE45T6000W", "User manual\nDVE(G)45T6005*/DVE(G)45T6000*\nContents"),
        ("WM4000HWA", "ENGLISH WM4000H*A / WM4080H*A MFL00000000"),
    ],
)
def test_wildcard_labels_match_the_model(model, text) -> None:
    assert add_manual.match_model(model, text) == "wildcard"


@pytest.mark.parametrize(
    ("model", "text"),
    [
        ("DVE45T7000W", "DVE(G)45T6005*/DVE(G)45T6000*"),  # different series digit
        ("WM4100HWA", "WM4000H*A / WM4080H*A"),
        ("ABCDEFGH1", "* / W*A"),  # too few literal characters to trust
    ],
)
def test_wildcard_labels_do_not_match_other_models(model, text) -> None:
    assert add_manual.match_model(model, text) is None


def test_a_model_the_wildcard_excludes_falls_back_to_series_only() -> None:
    # WM4000HWB is not covered by "WM4000H*A" (fixed final A), but the series
    # stem WM4000 is printed, so it is reported as the weaker "series" match.
    assert add_manual.match_model("WM4000HWB", "WM4000H*A") == "series"


def test_exact_and_series_matches_are_still_reported() -> None:
    assert add_manual.match_model("X100", "the X100 oven") == "exact"
    assert add_manual.match_model("GFE28GYNFS", "models GFE28 and GFE26") == "series"


# --- dry run -------------------------------------------------------------------


def test_dry_run_changes_nothing(paths) -> None:
    before = snapshot(paths.manifest.parent)
    code, lines = run(paths, dry_run=True)
    assert code == 0
    assert "Dry run" in "\n".join(lines)
    assert snapshot(paths.manifest.parent) == before
    assert not paths.pdf_dir.exists() and not paths.parsed_dir.exists()


def test_dry_run_still_fails_on_wrong_content(paths) -> None:
    assert run(paths, tr=pdf_route("spec_sheet"), dry_run=True)[0] == 1


# --- real run, merge, idempotence -------------------------------------------------


def test_run_adds_manifest_entry_pdf_parsed_chunks_and_records(paths) -> None:
    code, lines = run(paths)
    assert code == 0, lines

    text = paths.manifest.read_text()
    assert text.startswith(MANIFEST_HEADER)  # header comment untouched
    entries = yaml.safe_load(text)
    new = next(e for e in entries if e["id"] == "acme-x100-oven")
    assert new["source_note"] == NOTE and new["source_url"] == URL
    assert (paths.pdf_dir / "acme-x100-oven.pdf").read_bytes().startswith(b"%PDF-")
    assert (paths.parsed_dir / "acme-x100-oven.json").exists()

    records = json.loads(paths.index.read_text())
    mine = [r for r in records if r["manual_id"] == "acme-x100-oven"]
    assert {r["code_normalized"] for r in mine} == {"E2400", "E3400", "TE1"}
    joined = "\n".join(lines)
    assert "manufacturer's terms" in joined
    assert "codes found: 3" in joined
    assert "image rebuild" in joined


def test_merge_leaves_other_manuals_records_untouched(paths) -> None:
    assert run(paths)[0] == 0
    records = json.loads(paths.index.read_text())
    assert records[0] == OTHER_RECORD  # same position, same content, unknown fields kept


def test_rerun_is_idempotent(paths) -> None:
    assert run(paths)[0] == 0
    first = snapshot(paths.manifest.parent)
    code, lines = run(paths)
    assert code == 0
    assert "re-run" in "\n".join(lines)
    assert snapshot(paths.manifest.parent) == first
    entries = yaml.safe_load(paths.manifest.read_text())
    assert [e["id"] for e in entries].count("acme-x100-oven") == 1


def test_stub_will_not_silently_replace_fully_extracted_records(paths) -> None:
    rich = dict(OTHER_RECORD, manual_id="acme-x100-oven", meaning="a real meaning")
    paths.index.write_text(json.dumps([OTHER_RECORD, rich], indent=2))
    before = snapshot(paths.manifest.parent)
    code, lines = run(paths)
    assert code == 1 and "--allow-downgrade" in "\n".join(lines)
    assert snapshot(paths.manifest.parent) == before
    assert run(paths, allow_downgrade=True)[0] == 0


# --- bedrock confirmation ----------------------------------------------------------


class FakeConverse:
    def __init__(self) -> None:
        self.calls = 0

    def converse(self, **kwargs):
        self.calls += 1
        body = [{"error_code": "E:24-00", "meaning": "Drain pump fault.", "extraction_confidence": 0.9}]
        return {
            "output": {"message": {"content": [{"text": json.dumps(body)}]}},
            "usage": {"inputTokens": 500, "outputTokens": 100},
        }


def bedrock(client: FakeConverse):
    return BedrockExtractor(region="us-east-1", model_id="fake-model", client=client)


def test_bedrock_prints_estimate_and_needs_yes(paths) -> None:
    client = FakeConverse()
    code, lines = run(paths, extractor=bedrock(client), input_fn=lambda _: "no")
    assert code == 1 and client.calls == 0
    joined = "\n".join(lines)
    assert "About to send 1 chunks to Amazon Bedrock" in joined
    assert "Estimated cost" in joined and "Estimated tokens" in joined
    assert "re-run the same command" in joined


def test_bedrock_proceeds_on_yes_and_reports_cost(paths) -> None:
    client = FakeConverse()
    code, lines = run(paths, extractor=bedrock(client), input_fn=lambda _: "yes")
    assert code == 0 and client.calls == 1
    assert "cost: $0.0" in "\n".join(lines)
    mine = [r for r in json.loads(paths.index.read_text()) if r["manual_id"] == "acme-x100-oven"]
    assert mine[0]["meaning"] == "Drain pump fault."


def test_bedrock_yes_flag_skips_the_prompt(paths) -> None:
    client = FakeConverse()
    assert run(paths, extractor=bedrock(client), yes=True)[0] == 0 and client.calls == 1


def test_bedrock_rerun_uses_cache_and_sends_nothing(paths) -> None:
    client = FakeConverse()
    assert run(paths, extractor=bedrock(client), yes=True)[0] == 0
    first = paths.index.read_text()
    assert run(paths, extractor=bedrock(client), yes=True)[0] == 0
    assert client.calls == 1
    assert paths.index.read_text() == first


# --- --code-pages ------------------------------------------------------------------


def test_code_pages_are_recorded_in_the_manifest_and_limit_extraction(paths) -> None:
    code, lines = run(paths, code_pages="1")
    assert code == 0, lines
    entry = next(e for e in yaml.safe_load(paths.manifest.read_text()) if e["id"] == "acme-x100-oven")
    assert str(entry["extraction_pages"]) == "1"
    records = json.loads(paths.index.read_text())
    mine = {r["code_normalized"] for r in records if r["manual_id"] == "acme-x100-oven"}
    assert mine == {"E2400", "E3400", "TE1"}


def test_code_pages_on_a_page_without_codes_finds_nothing(paths) -> None:
    code, lines = run(paths, code_pages="9")
    assert code == 0
    assert "codes found: 0" in "\n".join(lines)


def test_bad_code_pages_is_rejected(paths) -> None:
    assert run(paths, code_pages="abc")[0] == 1


def test_rerun_with_different_code_pages_is_not_treated_as_a_rerun(paths) -> None:
    assert run(paths, code_pages="1")[0] == 0
    code, lines = run(paths, code_pages="2")
    assert code == 1 and "already exists" in "\n".join(lines)
