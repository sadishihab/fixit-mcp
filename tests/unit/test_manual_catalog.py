from pathlib import Path

from fixit_mcp.catalog.manifest import ManualCatalogEntry, load_manual_catalog


def _write_manifest(tmp_path: Path, entries: list[dict]) -> Path:
    import yaml

    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(entries))
    return path


def test_find_matches_brand_and_model_case_insensitively(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path,
        [
            {
                "id": "bosch-she53b75uc-dishwasher",
                "brand": "Bosch",
                "model": "SHE53B75UC",
                "appliance_type": "dishwasher",
            }
        ],
    )
    catalog = load_manual_catalog(path)

    assert catalog.find("bosch", "she53b75uc") == ManualCatalogEntry(
        manual_id="bosch-she53b75uc-dishwasher",
        brand="Bosch",
        model="SHE53B75UC",
        appliance_type="dishwasher",
    )


def test_find_returns_none_for_no_match(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path,
        [
            {
                "id": "bosch-she53b75uc-dishwasher",
                "brand": "Bosch",
                "model": "SHE53B75UC",
                "appliance_type": "dishwasher",
            }
        ],
    )
    catalog = load_manual_catalog(path)

    assert catalog.find("Samsung", "RF28") is None


def test_load_manual_catalog_against_the_real_committed_manifest() -> None:
    catalog = load_manual_catalog()

    entry = catalog.find("Bosch", "SHE53B75UC")
    assert entry is not None
    assert entry.manual_id == "bosch-she53b75uc-dishwasher"


def test_missing_manifest_file_returns_an_empty_catalog(tmp_path: Path) -> None:
    catalog = load_manual_catalog(tmp_path / "does-not-exist.yaml")

    assert catalog.find("Bosch", "SHE53B75UC") is None
