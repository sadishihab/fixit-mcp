"""Household-to-manual resolution shared by the tools that look a customer's problem up in the
manual-derived indexes (`diagnose_error`, `diagnose_symptom`).

Pure in-memory logic, no I/O (CLAUDE.md rules 3/4). Extracted from `tools/diagnose.py` in step 25b
without changing `diagnose_error`'s behavior.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, Field

from fixit_mcp.domain.models import Appliance
from fixit_mcp.repository.base import ApplianceRepository


class ApplianceChoice(BaseModel):
    """One candidate appliance, for an ambiguous_appliance response."""

    appliance_id: str = Field(
        description="Empty when resolved by brand/model alone, with no owned appliance."
    )
    brand: str
    model: str
    appliance_type: str


def to_choice(appliance: Appliance) -> ApplianceChoice:
    return ApplianceChoice(
        appliance_id=appliance.appliance_id,
        brand=appliance.brand,
        model=appliance.model,
        appliance_type=appliance.appliance_type,
    )


def resolve_owned_appliances(
    repository: ApplianceRepository,
    household_id: str,
    appliance_id: str | None,
    brand: str | None,
    model: str | None,
) -> list[Appliance]:
    owned = repository.list_by_household(household_id)
    if appliance_id is not None:
        owned = [a for a in owned if a.appliance_id == appliance_id]
    if brand is not None:
        owned = [a for a in owned if a.brand.lower() == brand.lower()]
    if model is not None:
        owned = [a for a in owned if a.model.lower() == model.lower()]
    return owned


class _HasManual(Protocol):
    manual_id: str


def pair_owned_with_records[R: _HasManual](
    owned: Sequence[Appliance], records: Sequence[R]
) -> list[tuple[Appliance, R]]:
    """Every (owned appliance, record) pair whose record comes from that appliance's own manual."""
    return [
        (appliance, record)
        for appliance in owned
        for record in records
        if record.manual_id == appliance.manual_id
    ]
