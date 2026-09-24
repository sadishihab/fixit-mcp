"""Appliance-registry tools: list, add, remove. Pure in-memory/DB lookups and
writes through ApplianceRepository, no LLM calls (CLAUDE.md rule 3)."""

from __future__ import annotations

import uuid
from datetime import date

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from fixit_mcp.catalog.manifest import ManualCatalog
from fixit_mcp.domain.models import Appliance, ApplianceList
from fixit_mcp.logging import log_tool_latency
from fixit_mcp.repository.base import ApplianceRepository

LIST_MY_APPLIANCES_DESCRIPTION = (
    "List the appliances a household owns, including brand, model, appliance "
    "type, purchase date, and warranty end date. Call this whenever the "
    "customer asks what appliances they have, refers to an appliance by brand "
    "or type without more detail, or before diagnosing an error code so you "
    "know exactly which appliance it applies to. Requires the household_id "
    "for the customer's account; returns an empty list if the household has "
    "no registered appliances."
)

ADD_APPLIANCE_DESCRIPTION = (
    "Register a new appliance for a household, so it can be listed and its error codes "
    "diagnosed in future calls. Call this when the customer mentions an appliance that "
    "list_my_appliances doesn't already show -- for example right after a purchase, or the "
    "first time they bring one up. Requires household_id, brand, model, and appliance_type "
    "(e.g. 'refrigerator', 'dryer'); purchase_date and warranty_end_date are optional -- pass "
    "them only if the customer states them. If we have a manual on file for that exact "
    "brand/model, the appliance is linked to it automatically and diagnose_error will work "
    "right away; if not, the appliance is still saved, but tell the customer that error-code "
    "diagnosis will be limited for it until a manual is available."
)

REMOVE_APPLIANCE_DESCRIPTION = (
    "Remove an appliance from a household's registry -- for example if the customer says "
    "they got rid of it, replaced it, or registered it by mistake. Requires household_id and "
    "the appliance_id (from a prior list_my_appliances or add_appliance call). Tell the "
    "customer plainly if no matching appliance was found; nothing is guessed or assumed."
)


class AddApplianceResult(BaseModel):
    appliance: Appliance
    manual_linked: bool = Field(description="Whether a manual on file was linked to this appliance.")
    message: str = Field(description="Human-readable summary, including any diagnosis-coverage caveat.")


class RemoveApplianceResult(BaseModel):
    removed: bool
    appliance_id: str
    message: str


def add_appliance(
    repository: ApplianceRepository,
    catalog: ManualCatalog,
    household_id: str,
    brand: str,
    model: str,
    appliance_type: str,
    purchase_date: date | None = None,
    warranty_end_date: date | None = None,
) -> AddApplianceResult:
    """Pure resolution logic, kept separate from the @mcp.tool wrapper below
    so it's directly unit-testable without spinning up a server."""
    manual_entry = catalog.find(brand, model)
    appliance = Appliance(
        appliance_id=f"app-{uuid.uuid4().hex[:12]}",
        brand=brand,
        model=model,
        appliance_type=appliance_type,
        purchase_date=purchase_date,
        warranty_end_date=warranty_end_date,
        manual_id=manual_entry.manual_id if manual_entry else "",
    )
    repository.add(household_id, appliance)

    if manual_entry is not None:
        message = f"Added {brand} {model} and linked it to its manual -- diagnose_error will work for it."
    else:
        message = (
            f"Added {brand} {model}, but we don't have a manual on file for this exact model yet -- "
            "error-code diagnosis will be limited until one is added."
        )
    return AddApplianceResult(appliance=appliance, manual_linked=manual_entry is not None, message=message)


def remove_appliance(
    repository: ApplianceRepository, household_id: str, appliance_id: str
) -> RemoveApplianceResult:
    """Pure resolution logic, kept separate from the @mcp.tool wrapper below."""
    removed = repository.remove(household_id, appliance_id)
    message = (
        f"Removed appliance {appliance_id}."
        if removed
        else f"No appliance {appliance_id!r} found for this household -- nothing removed."
    )
    return RemoveApplianceResult(removed=removed, appliance_id=appliance_id, message=message)


def register_appliance_tools(mcp: FastMCP, repository: ApplianceRepository, catalog: ManualCatalog) -> None:
    """Register appliance-related tools on the given FastMCP server."""

    @mcp.tool(name="list_my_appliances", description=LIST_MY_APPLIANCES_DESCRIPTION)
    @log_tool_latency("list_my_appliances")
    def list_my_appliances(household_id: str) -> ApplianceList:
        appliances = repository.list_by_household(household_id)
        return ApplianceList(household_id=household_id, appliances=appliances)

    @mcp.tool(name="add_appliance", description=ADD_APPLIANCE_DESCRIPTION)
    @log_tool_latency("add_appliance")
    def add_appliance_tool(
        household_id: str,
        brand: str,
        model: str,
        appliance_type: str,
        purchase_date: date | None = None,
        warranty_end_date: date | None = None,
    ) -> AddApplianceResult:
        return add_appliance(
            repository, catalog, household_id, brand, model, appliance_type, purchase_date, warranty_end_date
        )

    @mcp.tool(name="remove_appliance", description=REMOVE_APPLIANCE_DESCRIPTION)
    @log_tool_latency("remove_appliance")
    def remove_appliance_tool(household_id: str, appliance_id: str) -> RemoveApplianceResult:
        return remove_appliance(repository, household_id, appliance_id)
