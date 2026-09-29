"""The check_warranty tool: reports whether a household's registered
appliance is still within its recorded manufacturer warranty, from a
deterministic server-side date comparison only -- no LLM calls (CLAUDE.md
rule 3), no guessed dates. The comparison always happens here, in code,
never left to the model.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from fixit_mcp.domain.models import Appliance
from fixit_mcp.logging import log_tool_latency
from fixit_mcp.repository.base import ApplianceRepository

CHECK_WARRANTY_DESCRIPTION = (
    "Check whether a household's appliance is still covered by its recorded manufacturer "
    "warranty. Call this whenever the customer asks if an appliance is under warranty, how "
    "much longer it's covered, or when it expired -- for example right after diagnosing an "
    "error code that needs service. Requires household_id. Pass appliance_id if you already "
    "know which specific appliance from an earlier list_my_appliances or diagnose_error call; "
    "otherwise pass whatever the customer said to narrow it down -- appliance_type (e.g. "
    "'dryer'), brand, and/or model. If more than one owned appliance matches, the response "
    "asks which one rather than guessing -- relay that question to the customer. This tool "
    "only reports the recorded purchase and warranty-end dates and today's date compared "
    "against them -- it never says what the warranty covers, whether a specific repair would "
    "be covered, or suggests contacting anyone; only relay the date fact it returns."
)


class WarrantyApplianceChoice(BaseModel):
    """One candidate appliance, for an ambiguous_appliance response."""

    appliance_id: str
    brand: str
    model: str
    appliance_type: str


class CheckWarrantyResult(BaseModel):
    """Response for check_warranty. `message` states only the recorded date
    fact -- never a coverage claim -- since the dates come from what the
    customer registered, not a manufacturer lookup."""

    status: Literal["active", "expired", "unknown", "ambiguous_appliance", "not_found"]
    message: str = Field(description="States only the recorded date fact -- never a coverage claim.")
    as_of: date = Field(description="The UTC date this check was run against.")

    # Populated when status is "active", "expired", or "unknown" -- exactly one appliance resolved.
    appliance: WarrantyApplianceChoice | None = None
    purchase_date: date | None = None
    warranty_end_date: date | None = None
    days_remaining: int | None = Field(
        default=None,
        description="Set only when status == 'active'. The warranty's end date counts as a day "
        "of coverage, so this is 0 on the day it ends, not negative.",
    )
    days_since_expiry: int | None = Field(default=None, description="Set only when status == 'expired'.")

    # Populated when status == "ambiguous_appliance".
    candidate_appliances: list[WarrantyApplianceChoice] = Field(default_factory=list)


def _to_choice(appliance: Appliance) -> WarrantyApplianceChoice:
    return WarrantyApplianceChoice(
        appliance_id=appliance.appliance_id,
        brand=appliance.brand,
        model=appliance.model,
        appliance_type=appliance.appliance_type,
    )


def _resolve_appliances(
    repository: ApplianceRepository,
    household_id: str,
    appliance_id: str | None,
    appliance_type: str | None,
    brand: str | None,
    model: str | None,
) -> list[Appliance]:
    """appliance_id wins outright: if given, no other filter is applied --
    it either matches that one appliance or nothing. Otherwise narrow by
    whichever of appliance_type/brand/model was given, so "my dryer" can
    resolve without an id."""
    owned = repository.list_by_household(household_id)
    if appliance_id is not None:
        return [a for a in owned if a.appliance_id == appliance_id]
    matches = owned
    if appliance_type is not None:
        matches = [a for a in matches if a.appliance_type.lower() == appliance_type.lower()]
    if brand is not None:
        matches = [a for a in matches if a.brand.lower() == brand.lower()]
    if model is not None:
        matches = [a for a in matches if a.model.lower() == model.lower()]
    return matches


def _dated_result(appliance: Appliance, as_of: date) -> CheckWarrantyResult:
    end = appliance.warranty_end_date
    choice = _to_choice(appliance)
    label = f"{appliance.brand} {appliance.model}"

    if end is None:
        return CheckWarrantyResult(
            status="unknown",
            message=f"No recorded warranty end date is on file for this {label}.",
            as_of=as_of,
            appliance=choice,
            purchase_date=appliance.purchase_date,
        )

    if end >= as_of:
        # The end date is the last day of coverage, not the first day of
        # expiry: a warranty ending "today" still counts as active. Pinned
        # by test_check_warranty_ends_today_counts_as_active.
        days_remaining = (end - as_of).days
        if days_remaining == 0:
            message = f"The recorded warranty for this {label} ends today, {end.isoformat()}."
        else:
            plural = "s" if days_remaining != 1 else ""
            message = (
                f"The recorded warranty for this {label} is still active, through "
                f"{end.isoformat()} ({days_remaining} day{plural} from now)."
            )
        return CheckWarrantyResult(
            status="active",
            message=message,
            as_of=as_of,
            appliance=choice,
            purchase_date=appliance.purchase_date,
            warranty_end_date=end,
            days_remaining=days_remaining,
        )

    days_since_expiry = (as_of - end).days
    plural = "s" if days_since_expiry != 1 else ""
    return CheckWarrantyResult(
        status="expired",
        message=(
            f"The recorded warranty for this {label} ended on {end.isoformat()}, "
            f"{days_since_expiry} day{plural} ago."
        ),
        as_of=as_of,
        appliance=choice,
        purchase_date=appliance.purchase_date,
        warranty_end_date=end,
        days_since_expiry=days_since_expiry,
    )


def check_warranty(
    repository: ApplianceRepository,
    household_id: str,
    as_of: date,
    appliance_id: str | None = None,
    appliance_type: str | None = None,
    brand: str | None = None,
    model: str | None = None,
) -> CheckWarrantyResult:
    """Pure resolution logic, kept separate from the @mcp.tool wrapper below
    so it's directly unit-testable without spinning up a server. `as_of` is
    always injected by the caller -- the wrapper below is the one place that
    reads the clock (one UTC source) -- so tests stay deterministic."""
    matches = _resolve_appliances(repository, household_id, appliance_id, appliance_type, brand, model)

    if len(matches) == 1:
        return _dated_result(matches[0], as_of)

    if len(matches) > 1:
        return CheckWarrantyResult(
            status="ambiguous_appliance",
            message="More than one of this household's appliances matches -- which appliance do you mean?",
            as_of=as_of,
            candidate_appliances=[_to_choice(a) for a in matches],
        )

    return CheckWarrantyResult(
        status="not_found",
        message="No registered appliance matches that description for this household.",
        as_of=as_of,
    )


def _utc_today() -> date:
    return datetime.now(UTC).date()


def register_warranty_tool(mcp: FastMCP, repository: ApplianceRepository) -> None:
    """Register the check_warranty tool on the given FastMCP server."""

    @mcp.tool(name="check_warranty", description=CHECK_WARRANTY_DESCRIPTION)
    @log_tool_latency("check_warranty")
    def check_warranty_tool(
        household_id: str,
        appliance_id: str | None = None,
        appliance_type: str | None = None,
        brand: str | None = None,
        model: str | None = None,
    ) -> CheckWarrantyResult:
        return check_warranty(
            repository, household_id, _utc_today(), appliance_id, appliance_type, brand, model
        )
