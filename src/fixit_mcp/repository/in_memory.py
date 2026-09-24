from datetime import date

from fixit_mcp.domain.models import Appliance

# Brand/model pairs here match data/manuals/manifest.yaml entries (same
# brand + model), linked via manual_id. Shared with SqliteApplianceRepository
# as the data it seeds a fresh, empty store with (see repository/sqlite.py).
DEFAULT_SEED: dict[str, list[Appliance]] = {
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
    """ApplianceRepository backed by a plain in-memory dict. Used by tests
    (deterministic, no filesystem) and available as the "memory" backend for
    local runs where persistence across restarts isn't wanted.

    Deep-copies its seed on init (rather than aliasing the module-level
    DEFAULT_SEED directly) so that `add`/`remove` on one instance -- or
    across repeated test runs using the default seed -- never mutate shared
    state another instance or test would also see.
    """

    def __init__(self, seed: dict[str, list[Appliance]] | None = None) -> None:
        source = seed if seed is not None else DEFAULT_SEED
        self._data: dict[str, list[Appliance]] = {
            household_id: list(appliances) for household_id, appliances in source.items()
        }

    def list_by_household(self, household_id: str) -> list[Appliance]:
        return list(self._data.get(household_id, []))

    def add(self, household_id: str, appliance: Appliance) -> None:
        self._data.setdefault(household_id, []).append(appliance)

    def remove(self, household_id: str, appliance_id: str) -> bool:
        appliances = self._data.get(household_id)
        if not appliances:
            return False
        for index, appliance in enumerate(appliances):
            if appliance.appliance_id == appliance_id:
                del appliances[index]
                return True
        return False
