from datetime import date

from fixit_mcp.domain.models import Appliance
from fixit_mcp.repository.in_memory import InMemoryApplianceRepository


def test_list_by_household_returns_seeded_appliances() -> None:
    repo = InMemoryApplianceRepository()

    appliances = repo.list_by_household("house-001")

    assert len(appliances) == 2
    assert {a.brand for a in appliances} == {"Whirlpool", "Bosch"}


def test_list_by_household_unknown_household_returns_empty_list() -> None:
    repo = InMemoryApplianceRepository()

    assert repo.list_by_household("does-not-exist") == []


def test_list_by_household_uses_injected_seed() -> None:
    custom_seed = {
        "house-custom": [
            Appliance(
                appliance_id="app-x",
                brand="Samsung",
                model="RF28",
                appliance_type="refrigerator",
                purchase_date=date(2020, 1, 1),
                warranty_end_date=date(2022, 1, 1),
            )
        ]
    }
    repo = InMemoryApplianceRepository(seed=custom_seed)

    appliances = repo.list_by_household("house-custom")

    assert len(appliances) == 1
    assert appliances[0].brand == "Samsung"


def test_list_by_household_returns_copy_not_internal_list() -> None:
    repo = InMemoryApplianceRepository()

    appliances = repo.list_by_household("house-001")
    appliances.clear()

    assert len(repo.list_by_household("house-001")) == 2
