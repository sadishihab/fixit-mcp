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


def make_appliance(appliance_id: str = "app-x", **overrides) -> Appliance:
    defaults = dict(
        appliance_id=appliance_id,
        brand="Samsung",
        model="RF28",
        appliance_type="refrigerator",
        purchase_date=date(2020, 1, 1),
        warranty_end_date=date(2022, 1, 1),
        manual_id="samsung-rf28-refrigerator",
    )
    defaults.update(overrides)
    return Appliance(**defaults)


# --- add / remove -------------------------------------------------


def test_add_appends_to_an_existing_household() -> None:
    repo = InMemoryApplianceRepository()

    repo.add("house-001", make_appliance())

    assert len(repo.list_by_household("house-001")) == 4


def test_add_creates_a_new_household_that_did_not_exist() -> None:
    repo = InMemoryApplianceRepository(seed={})

    repo.add("house-new", make_appliance())

    assert len(repo.list_by_household("house-new")) == 1


def test_remove_returns_true_and_deletes_the_appliance() -> None:
    repo = InMemoryApplianceRepository(seed={})
    repo.add("house-1", make_appliance(appliance_id="app-to-remove"))

    removed = repo.remove("house-1", "app-to-remove")

    assert removed is True
    assert repo.list_by_household("house-1") == []


def test_remove_returns_false_for_unknown_appliance_id() -> None:
    repo = InMemoryApplianceRepository()

    assert repo.remove("house-001", "does-not-exist") is False


def test_remove_returns_false_for_unknown_household() -> None:
    repo = InMemoryApplianceRepository(seed={})

    assert repo.remove("no-such-house", "app-1") is False


def test_default_seed_is_not_mutated_by_add_on_one_instance() -> None:
    """Regression test: two instances built from the default seed must not
    share mutable state -- adding to one must never leak into another."""
    first = InMemoryApplianceRepository()
    first.add("house-001", make_appliance())

    second = InMemoryApplianceRepository()

    assert len(second.list_by_household("house-001")) == 3
