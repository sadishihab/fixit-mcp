"""Appliance-type normalization (step 16b): the synonyms customers use must
match what is stored, in check_warranty and in add_appliance."""

from datetime import date

import pytest

from fixit_mcp.catalog.manifest import ManualCatalog
from fixit_mcp.domain.appliance_types import appliance_types_match, normalize_appliance_type
from fixit_mcp.domain.models import Appliance
from fixit_mcp.repository.in_memory import InMemoryApplianceRepository
from fixit_mcp.tools.appliances import add_appliance
from fixit_mcp.tools.warranty import check_warranty

TODAY = date(2026, 9, 30)

SYNONYMS = {
    "washing_machine": [
        "washer",
        "washing machine",
        "washing_machine",
        "clothes washer",
        "Washer",
        "washing-machine",
    ],
    "dryer": ["dryer", "clothes dryer", "Dryer"],
    "refrigerator": ["fridge", "refrigerator", "freezer", "Fridge"],
    "dishwasher": ["dishwasher", "Dishwasher"],
    "range": ["oven", "range", "stove", "Stove"],
}
CASES = [(canonical, word) for canonical, words in SYNONYMS.items() for word in words]


@pytest.mark.parametrize(("canonical", "word"), CASES)
def test_every_synonym_normalizes_to_its_canonical_type(canonical: str, word: str) -> None:
    assert normalize_appliance_type(word) == canonical


def test_unknown_types_pass_through_and_do_not_match_other_types() -> None:
    assert normalize_appliance_type("Wine Cooler") == "wine_cooler"
    assert not appliance_types_match("microwave", "range")
    assert not appliance_types_match("dryer", "washing_machine")


def _appliance(appliance_type: str, appliance_id: str = "app-1") -> Appliance:
    return Appliance(
        appliance_id=appliance_id, brand="LG", model="M", appliance_type=appliance_type,
        purchase_date=date(2025, 1, 1), warranty_end_date=date(2031, 1, 1), manual_id="",
    )  # fmt: skip


@pytest.mark.parametrize(("canonical", "word"), CASES)
def test_check_warranty_finds_the_stored_appliance_by_any_synonym(canonical: str, word: str) -> None:
    repo = InMemoryApplianceRepository(seed={"h": [_appliance(canonical)]})
    result = check_warranty(repo, "h", TODAY, appliance_type=word)
    assert result.status == "active", (canonical, word)


def test_check_warranty_matches_values_stored_before_normalization() -> None:
    # A value stored as the customer typed it (older adds, or other backends) still matches.
    repo = InMemoryApplianceRepository(seed={"h": [_appliance("Washer")]})
    assert check_warranty(repo, "h", TODAY, appliance_type="washing machine").status == "active"


def test_check_warranty_with_an_unknown_type_is_still_not_found() -> None:
    repo = InMemoryApplianceRepository(
        seed={"h": [_appliance("washing_machine"), _appliance("dryer", "app-2")]}
    )
    assert check_warranty(repo, "h", TODAY, appliance_type="microwave").status == "not_found"


def test_the_eval_failure_case_washer_query_against_washing_machine() -> None:
    repo = InMemoryApplianceRepository(seed={"h": [_appliance("washing_machine")]})
    assert check_warranty(repo, "h", TODAY, appliance_type="washer").status == "active"


STORED = [
    ("washer", "washing_machine"),
    ("Fridge", "refrigerator"),
    ("stove", "range"),
    ("Wine Cooler", "wine_cooler"),
]


@pytest.mark.parametrize(("word", "stored"), STORED)
def test_add_appliance_stores_the_normalized_type(word: str, stored: str) -> None:
    repo = InMemoryApplianceRepository(seed={})
    add_appliance(repo, ManualCatalog(entries=[]), "h", "LG", "X1", word)
    assert repo.list_by_household("h")[0].appliance_type == stored
