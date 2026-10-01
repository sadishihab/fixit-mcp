"""scripts/validate_manifest.py: the real manifest must be valid (this is what
puts `make validate-manifest` inside `make test`), and each rule must fire."""

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import yaml

from fixit_mcp.domain.models import Appliance
from fixit_mcp.repository.in_memory import DEFAULT_SEED

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
spec = importlib.util.spec_from_file_location("fixit_validate_manifest", SCRIPTS / "validate_manifest.py")
vm = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = vm
spec.loader.exec_module(vm)


def entry(**overrides) -> dict:
    base = {
        "id": "a-1",
        "brand": "Acme",
        "model": "X1",
        "appliance_type": "oven",
        "source_url": "https://e.example.com/a.pdf",
        "source_note": "public support page, free",
    }
    base.update(overrides)
    return base


def seed_for(manual_id: str, brand: str = "Acme", model: str = "X1") -> dict:
    appliance = Appliance(
        appliance_id="app-9", brand=brand, model=model, appliance_type="oven",
        purchase_date=date(2024, 1, 1), warranty_end_date=None, manual_id=manual_id,
    )  # fmt: skip
    return {"h": [appliance]}


def test_the_real_manifest_is_valid() -> None:
    entries = yaml.safe_load(vm.MANIFEST_PATH.read_text())
    records = json.loads(vm.INDEX_PATH.read_text())
    symptoms = json.loads(vm.SYMPTOMS_PATH.read_text())
    assert vm.validate(entries, DEFAULT_SEED, records, symptoms) == []


def test_a_symptom_record_for_an_unknown_manual_is_flagged() -> None:
    problems = vm.validate([entry()], {}, [], [{"manual_id": "a-1"}, {"manual_id": "ghost"}])

    assert any("symptoms.json" in p and "ghost" in p for p in problems)
    assert not any("a-1" in p for p in problems)


def test_valid_minimal_manifest_has_no_problems() -> None:
    assert vm.validate([entry()], seed_for("a-1"), [{"manual_id": "a-1"}]) == []


def test_duplicate_id_and_duplicate_brand_model_are_reported() -> None:
    problems = vm.validate([entry(), entry()], {}, [])
    assert any("duplicate id" in p for p in problems)
    assert any("brand+model duplicates" in p for p in problems)


def test_missing_note_and_field_and_bad_url_are_reported() -> None:
    problems = vm.validate([entry(source_note=" "), entry(id="b", model="X2", source_url="ftp://x")], {}, [])
    assert any("source_note" in p for p in problems)
    assert any("http(s)" in p for p in problems)
    assert vm.validate([{"id": "z"}], {}, [])  # other required fields missing


def test_seeded_appliance_must_resolve_and_match() -> None:
    assert any("not in the manifest" in p for p in vm.validate([entry()], seed_for("ghost"), []))
    assert any("does not match" in p for p in vm.validate([entry()], seed_for("a-1", model="ZZ"), []))


def test_index_records_must_point_at_a_manifest_entry() -> None:
    assert any("orphan" in p for p in vm.validate([entry()], {}, [{"manual_id": "orphan"}]))


def test_non_list_manifest_is_reported() -> None:
    assert vm.validate({"a": 1}, {}, [])
