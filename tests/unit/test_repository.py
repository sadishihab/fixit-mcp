from datetime import date

from fixit_mcp.domain.models import Appliance
from fixit_mcp.repository.in_memory import InMemoryApplianceRepository


def test_list_by_household_returns_seeded_appliances() -> None:
    repo = InMemoryApplianceRepository()

    appliances = repo.list_by_household("house-001")

    assert len(appliances) == 3
    assert {a.brand for a in appliances} == {"GE", "Bosch"}
    assert {a.appliance_type for a in appliances} == {"refrigerator", "dishwasher", "oven"}


def test_list_by_household_appliances_link_to_a_manual_id() -> None:
    repo = InMemoryApplianceRepository()

    appliances = repo.list_by_household("house-001") + repo.list_by_household("house-002")

    assert all(a.manual_id for a in appliances)
    assert {a.manual_id for a in appliances} == {
        "ge-gfe28gynfs-refrigerator",
        "bosch-she53b75uc-dishwasher",
        "ge-jbp26-range",
        "ge-gtw680bsjws-washer",
        "lg-dlex8000w-dryer",
    }


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
                manual_id="samsung-rf28-refrigerator",
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

    assert len(repo.list_by_household("house-001")) == 3
