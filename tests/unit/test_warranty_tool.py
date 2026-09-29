from datetime import date

from fixit_mcp.domain.models import Appliance
from fixit_mcp.repository.in_memory import InMemoryApplianceRepository
from fixit_mcp.tools.warranty import check_warranty

TODAY = date(2026, 9, 29)


def make_appliance(
    appliance_id: str = "app-1",
    brand: str = "GE",
    model: str = "GFE28GYNFS",
    appliance_type: str = "refrigerator",
    purchase_date: date | None = date(2023, 1, 1),
    warranty_end_date: date | None = date(2025, 1, 1),
) -> Appliance:
    return Appliance(
        appliance_id=appliance_id,
        brand=brand,
        model=model,
        appliance_type=appliance_type,
        purchase_date=purchase_date,
        warranty_end_date=warranty_end_date,
        manual_id="",
    )


def repo_with(*appliances: Appliance) -> InMemoryApplianceRepository:
    return InMemoryApplianceRepository(seed={"house-1": list(appliances)})


# --- single-appliance date outcomes -------------------------------------------------


def test_check_warranty_active() -> None:
    appliance = make_appliance(warranty_end_date=date(2026, 12, 31))
    repo = repo_with(appliance)

    result = check_warranty(repo, "house-1", TODAY)

    assert result.status == "active"
    assert result.days_remaining == (date(2026, 12, 31) - TODAY).days
    assert result.days_since_expiry is None
    assert result.warranty_end_date == date(2026, 12, 31)
    assert "recorded" in result.message
    assert result.appliance is not None
    assert result.appliance.brand == "GE"


def test_check_warranty_expired() -> None:
    appliance = make_appliance(warranty_end_date=date(2025, 1, 15))
    repo = repo_with(appliance)

    result = check_warranty(repo, "house-1", TODAY)

    assert result.status == "expired"
    assert result.days_since_expiry == (TODAY - date(2025, 1, 15)).days
    assert result.days_remaining is None
    assert "recorded" in result.message
    assert "ago" in result.message


def test_check_warranty_ends_today_counts_as_active() -> None:
    """Pins the boundary decision: the recorded end date is the last day of
    coverage, not the first day of expiry, so it still reads as active."""
    appliance = make_appliance(warranty_end_date=TODAY)
    repo = repo_with(appliance)

    result = check_warranty(repo, "house-1", TODAY)

    assert result.status == "active"
    assert result.days_remaining == 0
    assert result.days_since_expiry is None


def test_check_warranty_unknown_when_no_end_date() -> None:
    appliance = make_appliance(warranty_end_date=None)
    repo = repo_with(appliance)

    result = check_warranty(repo, "house-1", TODAY)

    assert result.status == "unknown"
    assert result.days_remaining is None
    assert result.days_since_expiry is None
    assert result.warranty_end_date is None


# --- resolution ---------------------------------------------------------------------


def test_check_warranty_ambiguous_when_multiple_match() -> None:
    a = make_appliance(appliance_id="app-1", appliance_type="dryer", brand="LG")
    b = make_appliance(appliance_id="app-2", appliance_type="dryer", brand="Samsung")
    repo = repo_with(a, b)

    result = check_warranty(repo, "house-1", TODAY, appliance_type="dryer")

    assert result.status == "ambiguous_appliance"
    assert {c.appliance_id for c in result.candidate_appliances} == {"app-1", "app-2"}
    assert result.appliance is None


def test_check_warranty_not_found_when_no_appliance_matches() -> None:
    repo = repo_with(make_appliance(appliance_type="refrigerator"))

    result = check_warranty(repo, "house-1", TODAY, appliance_type="dryer")

    assert result.status == "not_found"
    assert result.appliance is None


def test_check_warranty_not_found_for_unknown_household() -> None:
    repo = repo_with(make_appliance())

    result = check_warranty(repo, "no-such-household", TODAY)

    assert result.status == "not_found"


def test_check_warranty_resolves_by_appliance_type() -> None:
    fridge = make_appliance(appliance_id="app-1", appliance_type="refrigerator")
    dryer = make_appliance(appliance_id="app-2", appliance_type="dryer", brand="LG")
    repo = repo_with(fridge, dryer)

    result = check_warranty(repo, "house-1", TODAY, appliance_type="dryer")

    assert result.appliance is not None
    assert result.appliance.appliance_id == "app-2"


def test_check_warranty_appliance_id_takes_precedence_over_other_filters() -> None:
    """appliance_id wins outright -- a conflicting brand/appliance_type
    passed alongside it is ignored, not used to further narrow or reject."""
    fridge = make_appliance(appliance_id="app-1", appliance_type="refrigerator", brand="GE")
    repo = repo_with(fridge)

    result = check_warranty(repo, "house-1", TODAY, appliance_id="app-1", appliance_type="dryer", brand="LG")

    assert result.appliance is not None
    assert result.appliance.appliance_id == "app-1"


def test_check_warranty_appliance_id_with_no_match_is_not_found_even_if_other_appliances_exist() -> None:
    repo = repo_with(make_appliance(appliance_id="app-1"))

    result = check_warranty(repo, "house-1", TODAY, appliance_id="app-does-not-exist")

    assert result.status == "not_found"
