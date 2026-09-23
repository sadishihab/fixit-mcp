from datetime import date

from fixit_mcp.domain.models import Appliance

_SEED_DATA: dict[str, list[Appliance]] = {
    "house-001": [
        Appliance(
            appliance_id="app-001",
            brand="Whirlpool",
            model="WRF535SWHZ",
            appliance_type="refrigerator",
            purchase_date=date(2021, 6, 12),
            warranty_end_date=date(2023, 6, 12),
        ),
        Appliance(
            appliance_id="app-002",
            brand="Bosch",
            model="SHXM4AY55N",
            appliance_type="dishwasher",
            purchase_date=date(2022, 3, 1),
            warranty_end_date=date(2024, 3, 1),
        ),
    ],
    "house-002": [
        Appliance(
            appliance_id="app-003",
            brand="LG",
            model="WM3900HWA",
            appliance_type="washing_machine",
            purchase_date=date(2023, 1, 15),
            warranty_end_date=date(2025, 1, 15),
        ),
    ],
}


class InMemoryApplianceRepository:
    """ApplianceRepository backed by an in-memory seed dict."""

    def __init__(self, seed: dict[str, list[Appliance]] | None = None) -> None:
        self._data = seed if seed is not None else _SEED_DATA

    def list_by_household(self, household_id: str) -> list[Appliance]:
        return list(self._data.get(household_id, []))
