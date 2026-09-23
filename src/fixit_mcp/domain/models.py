from datetime import date

from pydantic import BaseModel, Field


class Appliance(BaseModel):
    """A household appliance FixIt knows about."""

    appliance_id: str = Field(description="Stable identifier for this appliance.")
    brand: str = Field(description="Manufacturer brand, e.g. 'Whirlpool'.")
    model: str = Field(description="Manufacturer model number, e.g. 'WRF535SWHZ'.")
    appliance_type: str = Field(description="Category of appliance, e.g. 'refrigerator', 'dishwasher'.")
    purchase_date: date = Field(description="Date the appliance was purchased.")
    warranty_end_date: date = Field(description="Date the manufacturer warranty expires.")


class ApplianceList(BaseModel):
    """Appliances owned by a household."""

    household_id: str
    appliances: list[Appliance]
