"""The diagnose_error tool: looks up a manufacturer error code against the
offline-extracted error-code index and, when possible, the household's own
appliances -- see fixit_mcp.retrieval.codes for the index itself.

Pure in-memory dict/string lookups only, no file I/O, no network, no LLM
calls (CLAUDE.md rules 3/4) -- everything expensive already happened offline,
at ingestion time.
"""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from fixit_mcp.domain.models import Appliance, ErrorCodeRecord, normalize_code
from fixit_mcp.logging import log_tool_latency
from fixit_mcp.repository.base import ApplianceRepository
from fixit_mcp.retrieval.codes import ErrorCodeIndex

DIAGNOSE_ERROR_DESCRIPTION = (
    "Look up what an appliance error code means: its meaning, likely causes, "
    "ordered repair steps, parts needed, safety warnings, and how hard the "
    "fix is, cited to the specific manual page. Call this whenever the "
    "customer mentions an error code, a code shown on an appliance's display, "
    "or a blinking-light pattern that corresponds to one. Pass error_code "
    "exactly as the customer said or as it's shown (e.g. 'E24', 'tE1', "
    "'E:24-00') -- normalization is handled internally. Pass household_id "
    "(and appliance_id if you already know which specific appliance from an "
    "earlier list_my_appliances call) so the right manual can be picked "
    "automatically; if you only know the brand/model, pass those instead. "
    "If the household owns more than one appliance whose manual documents "
    "this exact code, the response asks which appliance rather than "
    "guessing -- relay that question to the customer. If the code isn't in "
    "our index, the response says so plainly and never invents a diagnosis; "
    "it may suggest the closest known codes instead."
)


class ApplianceChoice(BaseModel):
    """One candidate appliance, for an ambiguous_appliance response."""

    appliance_id: str = Field(
        description="Empty when resolved by brand/model alone, with no owned appliance."
    )
    brand: str
    model: str
    appliance_type: str


class Citation(BaseModel):
    """Where this diagnosis came from, for transparency and follow-up."""

    brand: str
    model: str
    page: int
    section: str | None


class DiagnoseErrorResult(BaseModel):
    """Response for diagnose_error. Only one of the three `status` shapes is
    ever meaningfully populated at once; the others' fields stay at their
    empty defaults -- never fabricated content to fill a shape that doesn't
    apply."""

    status: Literal["found", "ambiguous_appliance", "not_found"]
    message: str = Field(description="Short, human-readable summary of the result.")
    error_code: str = Field(
        description="As matched (manufacturer's exact spelling) or as given, if unmatched."
    )
    code_normalized: str

    # Populated when status == "found".
    appliance: ApplianceChoice | None = None
    meaning: str = ""
    likely_causes: list[str] = Field(default_factory=list)
    repair_steps: list[str] = Field(default_factory=list)
    parts_needed: list[str] = Field(default_factory=list)
    safety_warnings: list[str] = Field(default_factory=list)
    difficulty: Literal["easy", "moderate", "call_service"] | None = None
    confidence: float | None = None
    citation: Citation | None = None

    # Populated when status == "ambiguous_appliance".
    candidate_appliances: list[ApplianceChoice] = Field(default_factory=list)

    # Populated when status == "not_found".
    nearest_matches: list[str] = Field(default_factory=list)
    family_note: str | None = Field(
        default=None,
        description="Set when the relevant manual describes a general code family, not this exact code.",
    )


def _to_choice(appliance: Appliance) -> ApplianceChoice:
    return ApplianceChoice(
        appliance_id=appliance.appliance_id,
        brand=appliance.brand,
        model=appliance.model,
        appliance_type=appliance.appliance_type,
    )


def _citation_for(record: ErrorCodeRecord) -> Citation:
    return Citation(
        brand=record.brand, model=record.model, page=record.source_page, section=record.source_section
    )


def _found_result(record: ErrorCodeRecord, appliance: ApplianceChoice | None) -> DiagnoseErrorResult:
    return DiagnoseErrorResult(
        status="found",
        message=(
            f"{record.error_code}: {record.meaning}" if record.meaning else f"Found {record.error_code}."
        ),
        error_code=record.error_code,
        code_normalized=record.code_normalized,
        appliance=appliance,
        meaning=record.meaning,
        likely_causes=record.likely_causes,
        repair_steps=record.repair_steps,
        parts_needed=record.parts_needed,
        safety_warnings=record.safety_warnings,
        difficulty=record.difficulty,
        confidence=record.extraction_confidence,
        citation=_citation_for(record),
    )


def _resolve_owned_appliances(
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


def diagnose(
    index: ErrorCodeIndex,
    repository: ApplianceRepository,
    error_code: str,
    household_id: str | None = None,
    appliance_id: str | None = None,
    brand: str | None = None,
    model: str | None = None,
) -> DiagnoseErrorResult:
    """Pure resolution logic, kept separate from the @mcp.tool wrapper below
    so it's directly unit-testable without spinning up a server."""
    code_normalized = normalize_code(error_code)
    candidates = index.by_code(code_normalized)

    owned: list[Appliance] = []
    if household_id is not None:
        owned = _resolve_owned_appliances(repository, household_id, appliance_id, brand, model)

    if candidates:
        if owned:
            matches = [
                (appliance, record)
                for appliance in owned
                for record in candidates
                if record.manual_id == appliance.manual_id
            ]
            if len(matches) == 1:
                appliance, record = matches[0]
                return _found_result(record, _to_choice(appliance))
            if len(matches) > 1:
                return DiagnoseErrorResult(
                    status="ambiguous_appliance",
                    message=(
                        f"More than one of this household's appliances has a manual documenting "
                        f"{error_code} -- which appliance is showing this code?"
                    ),
                    error_code=error_code,
                    code_normalized=code_normalized,
                    candidate_appliances=[_to_choice(a) for a, _ in matches],
                )
            # Household given, but none of its (possibly already-filtered)
            # appliances have a manual with this code -- fall through and
            # resolve by brand/model/global candidates instead.

        filtered = candidates
        if brand is not None:
            filtered = [r for r in filtered if r.brand.lower() == brand.lower()]
        if model is not None:
            filtered = [r for r in filtered if r.model.lower() == model.lower()]

        if len(filtered) == 1:
            return _found_result(filtered[0], appliance=None)
        if len(filtered) > 1:
            return DiagnoseErrorResult(
                status="ambiguous_appliance",
                message=(
                    f"{error_code} means something different on different appliances -- "
                    "which brand and model is showing this code?"
                ),
                error_code=error_code,
                code_normalized=code_normalized,
                candidate_appliances=[
                    ApplianceChoice(
                        appliance_id="", brand=r.brand, model=r.model, appliance_type=r.appliance_type
                    )
                    for r in filtered
                ],
            )
        # filtered is empty: brand/model (or household's appliances) didn't
        # match any manual that has this code, even though it exists
        # elsewhere in the index -- treat as not found below, but still without
        # inventing a match to an unrelated appliance.

    family_note = None
    if len(owned) == 1:
        family_record = index.family_note_for_manual(owned[0].manual_id)
        if family_record is not None:
            family_note = (
                f"The manual for this {owned[0].brand} {owned[0].model} doesn't document {error_code} "
                f'specifically, but describes a general code family: "{family_record.error_code}" -- '
                f"{family_record.meaning}"
            )

    return DiagnoseErrorResult(
        status="not_found",
        message=f"No manual in our index documents an error code matching {error_code!r}.",
        error_code=error_code,
        code_normalized=code_normalized,
        nearest_matches=index.nearest_codes(code_normalized),
        family_note=family_note,
    )


def register_diagnose_tool(mcp: FastMCP, repository: ApplianceRepository, index: ErrorCodeIndex) -> None:
    """Register the diagnose_error tool on the given FastMCP server."""

    @mcp.tool(name="diagnose_error", description=DIAGNOSE_ERROR_DESCRIPTION)
    @log_tool_latency("diagnose_error")
    def diagnose_error(
        error_code: str,
        household_id: str | None = None,
        appliance_id: str | None = None,
        brand: str | None = None,
        model: str | None = None,
    ) -> DiagnoseErrorResult:
        return diagnose(index, repository, error_code, household_id, appliance_id, brand, model)
