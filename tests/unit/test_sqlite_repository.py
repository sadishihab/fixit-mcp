from datetime import date
from pathlib import Path

from fixit_mcp.domain.models import Appliance
from fixit_mcp.repository.sqlite import SqliteApplianceRepository


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


# --- seeding -------------------------------------------------


def test_seeds_default_data_on_first_run_when_store_is_empty(tmp_path: Path) -> None:
    repo = SqliteApplianceRepository(tmp_path / "state.db")

    appliances = repo.list_by_household("house-001")

    assert len(appliances) == 3
    assert {a.brand for a in appliances} == {"GE", "Bosch"}


def test_does_not_reseed_a_store_that_already_has_data(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    first = SqliteApplianceRepository(db_path)
    first.add("house-001", make_appliance(appliance_id="app-manual"))

    second = SqliteApplianceRepository(db_path)

    # Reseeding would have re-inserted the 3 default house-001 appliances on
    # top of the manually-added one; confirm it did not.
    assert len(second.list_by_household("house-001")) == 4


def test_custom_seed_is_used_instead_of_the_default(tmp_path: Path) -> None:
    custom_seed = {"house-custom": [make_appliance(appliance_id="app-custom")]}

    repo = SqliteApplianceRepository(tmp_path / "state.db", seed=custom_seed)

    assert len(repo.list_by_household("house-custom")) == 1
    assert repo.list_by_household("house-001") == []


# --- add / remove -------------------------------------------------


def test_add_then_list_returns_the_new_appliance(tmp_path: Path) -> None:
    repo = SqliteApplianceRepository(tmp_path / "state.db", seed={})

    repo.add("house-1", make_appliance())

    appliances = repo.list_by_household("house-1")
    assert len(appliances) == 1
    assert appliances[0].brand == "Samsung"


def test_add_then_remove_round_trip(tmp_path: Path) -> None:
    repo = SqliteApplianceRepository(tmp_path / "state.db", seed={})
    repo.add("house-1", make_appliance(appliance_id="app-to-remove"))

    removed = repo.remove("house-1", "app-to-remove")

    assert removed is True
    assert repo.list_by_household("house-1") == []


def test_remove_returns_false_for_unknown_appliance(tmp_path: Path) -> None:
    repo = SqliteApplianceRepository(tmp_path / "state.db", seed={})

    assert repo.remove("house-1", "does-not-exist") is False


def test_remove_returns_false_for_unknown_household(tmp_path: Path) -> None:
    repo = SqliteApplianceRepository(tmp_path / "state.db", seed={})
    repo.add("house-1", make_appliance(appliance_id="app-1"))

    assert repo.remove("house-other", "app-1") is False


def test_add_preserves_optional_none_dates(tmp_path: Path) -> None:
    repo = SqliteApplianceRepository(tmp_path / "state.db", seed={})
    repo.add(
        "house-1",
        make_appliance(appliance_id="app-no-dates", purchase_date=None, warranty_end_date=None),
    )

    appliance = repo.list_by_household("house-1")[0]
    assert appliance.purchase_date is None
    assert appliance.warranty_end_date is None


def test_add_preserves_empty_manual_id_for_unmatched_appliance(tmp_path: Path) -> None:
    repo = SqliteApplianceRepository(tmp_path / "state.db", seed={})
    repo.add("house-1", make_appliance(appliance_id="app-no-manual", manual_id=""))

    appliance = repo.list_by_household("house-1")[0]
    assert appliance.manual_id == ""


# --- persistence across a fresh instance -------------------------------------------------


def test_persists_across_a_fresh_repository_instance_pointed_at_the_same_file(tmp_path: Path) -> None:
    """Regression test for the whole point of this store: a fresh instance
    pointed at the same file (simulating a server restart) sees everything
    a prior instance wrote, without the caller doing anything special."""
    db_path = tmp_path / "state.db"
    first = SqliteApplianceRepository(db_path, seed={})
    first.add("house-1", make_appliance(appliance_id="app-persisted"))

    second = SqliteApplianceRepository(db_path, seed={})

    appliances = second.list_by_household("house-1")
    assert len(appliances) == 1
    assert appliances[0].appliance_id == "app-persisted"


def test_list_by_household_unknown_household_returns_empty_list(tmp_path: Path) -> None:
    repo = SqliteApplianceRepository(tmp_path / "state.db")

    assert repo.list_by_household("does-not-exist") == []


def test_db_path_parent_directory_is_created_if_missing(tmp_path: Path) -> None:
    nested_path = tmp_path / "nested" / "dir" / "state.db"

    SqliteApplianceRepository(nested_path)

    assert nested_path.exists()
