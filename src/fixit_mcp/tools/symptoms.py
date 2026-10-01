"""The diagnose_symptom tool: finds what a customer describes in the troubleshooting tables of
their appliances' manuals and returns the manual's own rows, cited -- see
fixit_mcp.retrieval.symptoms for the index and the matcher.

Pure in-memory lookups, no file I/O, no network, no LLM calls (CLAUDE.md rules 3/4). Everything
in a match is a stored, verbatim manual string; the only text this module writes itself is the
fixed `message` templates below. A customer's words are used to find a row and are never copied
into a result, and nothing is ever merged, summarized or completed.
"""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from fixit_mcp.apps.resources import SYMPTOM_CARD_HTML, SYMPTOM_CARD_RESOURCE_URI
from fixit_mcp.domain.appliance_types import normalize_appliance_type
from fixit_mcp.domain.models import Appliance
from fixit_mcp.logging import log_tool_latency
from fixit_mcp.repository.base import ApplianceRepository
from fixit_mcp.retrieval.symptoms import (
    MAX_MATCHES,
    ScoredGroup,
    SymptomIndex,
    appliance_types_in,
    query_terms,
)
from fixit_mcp.tools.common import ApplianceChoice, resolve_owned_appliances, to_choice
from fixit_mcp.tools.diagnose import Citation

DIAGNOSE_SYMPTOM_DESCRIPTION = (
    "Look up what the appliance manual says about a problem the customer describes in their own "
    "words when there is NO error code: 'it won't drain', 'the fridge keeps beeping', 'too many "
    "suds', 'the washer is making a clicking noise'. Call this whenever the customer describes "
    "something an appliance is doing or not doing and has not read a code off the display (if they "
    "mention a code, call diagnose_error instead). Always pass household_id, and pass symptom as the "
    "customer's own short description -- just the problem, a few words, not the whole sentence. Pass "
    "appliance_type (e.g. 'washer', 'refrigerator') when the customer says which appliance it is, and "
    "appliance_id if you already know it from list_my_appliances. The response lists up to three "
    "matching entries from the manual, each with the problem as the manual words it, the possible "
    "causes, and what the manual says to do, cited to a manual page. Relay only what the entry says, "
    "in the manual's own terms: add no cause, step, safety judgment or reassurance of your own, "
    "never complete a sentence that ends mid-way, and read out an entry's footnotes (such as 'Select "
    "Models Only'), since they limit which models it applies to. An entry whose response_label is "
    "'Reason' explains normal behavior rather than telling the customer to do something. If the "
    "household owns more than one appliance with a matching entry, the response asks which appliance "
    "-- relay that question rather than guessing. If nothing matches, the response says so plainly "
    "and may list the manual's closest phrases; never invent a diagnosis. If appliance_registered is "
    "false, the entry is for an appliance the household hasn't registered: say so, and you may "
    "suggest add_appliance."
)

_NOT_FOUND_ROUTING = (
    " If the customer can read an error code off the appliance's display, use diagnose_error."
)
_NO_TERMS = "The description had no specific words to look up in the manuals."


class SymptomRow(BaseModel):
    """One cause/action row of a matched symptom, as the manual prints it."""

    possible_causes: list[str]
    what_to_do: list[str] = Field(description="The manual's third column; see response_label.")
    response_label: str = Field(
        description=(
            "The manual's own header for what_to_do: 'What To Do' (an action) or 'Reason' (an explanation)."
        )
    )
    footnotes: list[str] = Field(default_factory=list)
    text_incomplete: bool = Field(
        default=False,
        description="A string here ends mid-sentence in the manual text we have; don't finish it.",
    )
    page: int


class SymptomMatch(BaseModel):
    symptom: list[str] = Field(description="The problem as the manual words it.")
    symptom_label: str = Field(description="The manual's header for that column, e.g. 'Problem' or 'Sounds'.")
    rows: list[SymptomRow]
    citation: Citation
    score: float = Field(description="Match strength, 0-1: how much of what was described this entry covers.")


class DiagnoseSymptomResult(BaseModel):
    """Response for diagnose_symptom. Only the fields of the current `status` are populated; the rest
    stay at their empty defaults."""

    status: Literal["found", "ambiguous_appliance", "not_found"]
    message: str = Field(description="Short, human-readable summary of the result.")
    symptom: str = Field(description="The description as given.")

    # Populated when status == "found".
    appliance: ApplianceChoice | None = None
    appliance_registered: bool | None = Field(
        default=None,
        description=(
            "True when the matched manual belongs to one of the household's registered appliances; "
            "False when the entry is documented only for an appliance the household hasn't registered "
            "(appliance then names the documented appliance, with an empty appliance_id, and "
            "suggest_add_appliance is set)."
        ),
    )
    matches: list[SymptomMatch] = Field(default_factory=list)

    # Populated when status == "ambiguous_appliance".
    candidate_appliances: list[ApplianceChoice] = Field(default_factory=list)

    # Populated when status == "not_found".
    nearest_phrases: list[str] = Field(
        default_factory=list, description="The manual's own closest problem phrases, verbatim."
    )
    suggest_add_appliance: bool = Field(
        default=False,
        description="Set when no registered appliance (of the given type) was found; suggest add_appliance.",
    )


def _match_for(scored: ScoredGroup) -> SymptomMatch:
    g = scored.group
    return SymptomMatch(
        symptom=g.phrases,
        symptom_label=g.symptom_label,
        rows=[
            SymptomRow(
                possible_causes=r.possible_causes,
                what_to_do=r.what_to_do,
                response_label=r.response_label,
                footnotes=r.footnotes,
                text_incomplete=r.text_incomplete,
                page=r.source_page,
            )
            for r in g.rows
        ],
        citation=Citation(brand=g.brand, model=g.model, page=g.page, section=g.section),
        score=round(scored.score, 2),
    )


def _found_message(matches: list[SymptomMatch], brand: str, model: str, registered: bool) -> str:
    count = len(matches)
    message = (
        f"Found {count} similar {'entry' if count == 1 else 'entries'} in the manual for the "
        f"{brand} {model}. These are the manual's own words; relay only what they say."
    )
    if not registered:
        message += (
            f" This is documented for {brand} {model}, which isn't registered to this household. "
            "Consider calling add_appliance if this is the customer's appliance."
        )
    if any(row.footnotes for m in matches for row in m.rows):
        message += " Some entries carry a footnote that limits which models they apply to; relay it."
    if any(row.text_incomplete for m in matches for row in m.rows):
        message += " One entry's text ends mid-sentence in our copy of the manual; don't complete it."
    return message


def _documented_choice(group_manual: ScoredGroup) -> ApplianceChoice:
    g = group_manual.group
    return ApplianceChoice(appliance_id="", brand=g.brand, model=g.model, appliance_type=g.appliance_type)


def _top_per_manual(hits: list[ScoredGroup]) -> dict[str, list[ScoredGroup]]:
    by_manual: dict[str, list[ScoredGroup]] = {}
    for hit in hits:
        by_manual.setdefault(hit.group.manual_id, []).append(hit)
    return by_manual


def _owned_of_type(owned: list[Appliance], appliance_type: str | None) -> list[Appliance]:
    if appliance_type is None:
        return owned
    return [a for a in owned if normalize_appliance_type(a.appliance_type) == appliance_type]


def diagnose_symptom(
    index: SymptomIndex,
    repository: ApplianceRepository,
    household_id: str,
    symptom: str,
    appliance_type: str | None = None,
    appliance_id: str | None = None,
) -> DiagnoseSymptomResult:
    """Pure resolution logic, kept apart from the @mcp.tool wrapper so it is unit-testable directly."""
    terms = query_terms(symptom)

    if appliance_type:
        type_filter: str | None = normalize_appliance_type(appliance_type)
    else:
        named = appliance_types_in(symptom)  # the customer's own words, only if they name exactly one type
        type_filter = next(iter(named)) if len(named) == 1 else None

    owned_all = resolve_owned_appliances(repository, household_id, appliance_id, None, None)
    owned = _owned_of_type(owned_all, type_filter)
    owned_manuals = {a.manual_id for a in owned if a.manual_id}

    if terms:
        hits = (
            index.search(terms, manual_ids=owned_manuals, appliance_type=type_filter) if owned_manuals else []
        )
        by_manual = _top_per_manual(hits)
        owned_hits = [(a, hits_for) for a in owned if (hits_for := by_manual.get(a.manual_id))]

        if len(owned_hits) == 1:
            appliance, manual_hits = owned_hits[0]
            matches = [_match_for(h) for h in manual_hits[:MAX_MATCHES]]
            return DiagnoseSymptomResult(
                status="found",
                message=_found_message(matches, appliance.brand, appliance.model, registered=True),
                symptom=symptom,
                appliance=to_choice(appliance),
                appliance_registered=True,
                matches=matches,
            )
        if len(owned_hits) > 1:
            return DiagnoseSymptomResult(
                status="ambiguous_appliance",
                message=(
                    "More than one of this household's appliances has a manual entry for a similar "
                    "problem -- which appliance is it?"
                ),
                symptom=symptom,
                candidate_appliances=[to_choice(a) for a, _ in owned_hits],
            )

        # Nothing in the household's own manuals: look across every manual (restricted to the named
        # appliance type) so an unregistered appliance is reported as such, never attributed to the household.
        global_by_manual = _top_per_manual(index.search(terms, appliance_type=type_filter))
        if len(global_by_manual) == 1:
            (manual_hits,) = global_by_manual.values()
            first = manual_hits[0].group
            matches = [_match_for(h) for h in manual_hits[:MAX_MATCHES]]
            return DiagnoseSymptomResult(
                status="found",
                message=_found_message(matches, first.brand, first.model, registered=False),
                symptom=symptom,
                appliance=_documented_choice(manual_hits[0]),
                appliance_registered=False,
                matches=matches,
                suggest_add_appliance=True,
            )
        if len(global_by_manual) > 1:
            return DiagnoseSymptomResult(
                status="ambiguous_appliance",
                message=(
                    "Similar problems are described in the manuals of more than one appliance -- "
                    "which brand and model is it?"
                ),
                symptom=symptom,
                candidate_appliances=[_documented_choice(hits[0]) for hits in global_by_manual.values()],
            )

    suggest_add_appliance = not owned
    scope = owned_manuals if owned_manuals else None
    message = f"No symptom in our manuals matches {symptom!r}." if terms else _NO_TERMS
    if suggest_add_appliance:
        message += (
            " We don't see a matching appliance registered for this household -- it may not be "
            "registered yet. Consider calling add_appliance."
        )
    message += _NOT_FOUND_ROUTING
    return DiagnoseSymptomResult(
        status="not_found",
        message=message,
        symptom=symptom,
        nearest_phrases=index.nearest_phrases(terms, manual_ids=scope, appliance_type=type_filter),
        suggest_add_appliance=suggest_add_appliance,
    )


def register_symptom_tool(mcp: FastMCP, repository: ApplianceRepository, index: SymptomIndex) -> None:
    """Register diagnose_symptom and its MCP Apps visual card, declared the way diagnose_error declares
    its own: one static ui:// resource, linked from the tool definition's `_meta.ui.resourceUri`. The
    card's script renders every status (found, not_found, ambiguous_appliance) from the result the host
    pushes to it; the tool's plain structured result is unchanged by it."""

    @mcp.resource(
        SYMPTOM_CARD_RESOURCE_URI,
        name="diagnose-symptom-card",
        title="Symptom card",
        description=(
            "Visual card for a diagnose_symptom result: the matched problem as the manual words it, "
            "its possible causes and what the manual says to do, and the citation."
        ),
        mime_type="text/html;profile=mcp-app",
    )
    def diagnose_symptom_card() -> str:
        return SYMPTOM_CARD_HTML

    @mcp.tool(
        name="diagnose_symptom",
        description=DIAGNOSE_SYMPTOM_DESCRIPTION,
        meta={"ui": {"resourceUri": SYMPTOM_CARD_RESOURCE_URI}},
    )
    @log_tool_latency("diagnose_symptom")
    def diagnose_symptom_tool(
        household_id: str,
        symptom: str,
        appliance_type: str | None = None,
        appliance_id: str | None = None,
    ) -> DiagnoseSymptomResult:
        return diagnose_symptom(index, repository, household_id, symptom, appliance_type, appliance_id)
