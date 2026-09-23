from datetime import date

from fixit_mcp.domain.models import Appliance

# Brand/model pairs here match data/manuals/manifest.yaml entries (same
# brand + model), linked via manual_id.
_SEED_DATA: dict[str, list[Appliance]] = {
    "house-001": [
        Appliance(
            appliance_id="app-001",
            brand="GE",
            model="GFE28GYNFS",
            appliance_type="refrigerator",
            purchase_date=date(2021, 6, 12),
            warranty_end_date=date(2023, 6, 12),
            manual_id="ge-gfe28gynfs-refrigerator",
        ),
        Appliance(
            appliance_id="app-002",
            brand="Bosch",
            model="SHE53B75UC",
            appliance_type="dishwasher",
            purchase_date=date(2022, 3, 1),
            warranty_end_date=date(2024, 3, 1),
            manual_id="bosch-she53b75uc-dishwasher",
        ),
        Appliance(
            appliance_id="app-004",
            brand="GE",
            model="JBP26",
            appliance_type="oven",
            purchase_date=date(2020, 11, 5),
            warranty_end_date=date(2022, 11, 5),
            manual_id="ge-jbp26-range",
        ),
    ],
    "house-002": [
        Appliance(
            appliance_id="app-003",
            brand="GE",
            model="GTW680BSJWS",
            appliance_type="washing_machine",
            purchase_date=date(2023, 1, 15),
            warranty_end_date=date(2025, 1, 15),
            manual_id="ge-gtw680bsjws-washer",
        ),
        Appliance(
            appliance_id="app-005",
            brand="LG",
            model="DLEX8000W",
            appliance_type="dryer",
            purchase_date=date(2023, 1, 15),
            warranty_end_date=date(2025, 1, 15),
            manual_id="lg-dlex8000w-dryer",
        ),
    ],
}


class InMemoryApplianceRepository:
    """ApplianceRepository backed by an in-memory seed dict."""

    def __init__(self, seed: dict[str, list[Appliance]] | None = None) -> None:
        self._data = seed if seed is not None else _SEED_DATA

    def list_by_household(self, household_id: str) -> list[Appliance]:
        return list(self._data.get(household_id, []))
