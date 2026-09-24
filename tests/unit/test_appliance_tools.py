from fixit_mcp.catalog.manifest import ManualCatalog, ManualCatalogEntry
from fixit_mcp.repository.in_memory import InMemoryApplianceRepository
from fixit_mcp.tools.appliances import add_appliance, remove_appliance

CATALOG = ManualCatalog(
    entries=[
        ManualCatalogEntry(
            manual_id="bosch-she53b75uc-dishwasher",
            brand="Bosch",
            model="SHE53B75UC",
            appliance_type="dishwasher",
        )
    ]
)

EMPTY_CATALOG = ManualCatalog(entries=[])


# --- add_appliance -------------------------------------------------


def test_add_appliance_links_to_a_matching_manual() -> None:
    repo = InMemoryApplianceRepository(seed={})

    result = add_appliance(repo, CATALOG, "house-1", "Bosch", "SHE53B75UC", "dishwasher")

    assert result.manual_linked is True
    assert result.appliance.manual_id == "bosch-she53b75uc-dishwasher"
    assert result.appliance.appliance_id.startswith("app-")


def test_add_appliance_matches_manual_case_insensitively() -> None:
    repo = InMemoryApplianceRepository(seed={})

    result = add_appliance(repo, CATALOG, "house-1", "bosch", "she53b75uc", "dishwasher")

    assert result.manual_linked is True


def test_add_appliance_saves_even_without_a_matching_manual() -> None:
    repo = InMemoryApplianceRepository(seed={})

    result = add_appliance(repo, EMPTY_CATALOG, "house-1", "Samsung", "RF28", "refrigerator")

    assert result.manual_linked is False
    assert result.appliance.manual_id == ""
    assert "limited" in result.message.lower()
    assert repo.list_by_household("house-1") == [result.appliance]


def test_add_appliance_persists_via_the_repository() -> None:
    repo = InMemoryApplianceRepository(seed={})

    add_appliance(repo, CATALOG, "house-1", "Bosch", "SHE53B75UC", "dishwasher")

    assert len(repo.list_by_household("house-1")) == 1


def test_add_appliance_accepts_optional_dates_as_none() -> None:
    repo = InMemoryApplianceRepository(seed={})

    result = add_appliance(repo, CATALOG, "house-1", "Bosch", "SHE53B75UC", "dishwasher")

    assert result.appliance.purchase_date is None
    assert result.appliance.warranty_end_date is None


# --- remove_appliance -------------------------------------------------


def test_remove_appliance_removes_a_previously_added_one() -> None:
    repo = InMemoryApplianceRepository(seed={})
    added = add_appliance(repo, CATALOG, "house-1", "Bosch", "SHE53B75UC", "dishwasher")

    result = remove_appliance(repo, "house-1", added.appliance.appliance_id)

    assert result.removed is True
    assert repo.list_by_household("house-1") == []


def test_remove_appliance_reports_not_found_without_guessing() -> None:
    repo = InMemoryApplianceRepository(seed={})

    result = remove_appliance(repo, "house-1", "app-does-not-exist")

    assert result.removed is False
    assert "app-does-not-exist" in result.message
