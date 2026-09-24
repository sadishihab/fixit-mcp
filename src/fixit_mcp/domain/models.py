import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class Appliance(BaseModel):
    """A household appliance FixIt knows about."""

    appliance_id: str = Field(description="Stable identifier for this appliance.")
    brand: str = Field(description="Manufacturer brand, e.g. 'GE'.")
    model: str = Field(description="Manufacturer model number, e.g. 'GFE28GYNFS'.")
    appliance_type: str = Field(description="Category of appliance, e.g. 'refrigerator', 'dishwasher'.")
    purchase_date: date | None = Field(
        default=None, description="Date the appliance was purchased, if known."
    )
    warranty_end_date: date | None = Field(
        default=None, description="Date the manufacturer warranty expires, if known."
    )
    manual_id: str = Field(
        default="",
        description=(
            "Id of the manual entry (data/manuals/manifest.yaml) for this appliance. Empty "
            "string if no manual matches this brand/model yet -- diagnose_error can't cite a "
            "manual for it until one is added to the manifest."
        ),
    )


class ApplianceList(BaseModel):
    """Appliances owned by a household."""

    household_id: str
    appliances: list[Appliance]


class ErrorCodeRecord(BaseModel):
    """One extracted, cited error-code record.

    Every field beyond error_code/code_normalized/extraction_confidence is
    extracted *only* from what the manual's text actually states -- a
    missing field is an empty list/string, never a guess. Written offline by
    `fixit_mcp.ingestion.extraction` into `data/index/error_codes.json`, and
    read at server startup by `fixit_mcp.retrieval.codes` -- this model lives
    here in the neutral domain layer, not in `ingestion`, specifically so the
    running server never has to import ingestion code (which is offline
    tooling only, see CLAUDE.md) just to know this schema.
    """

    manual_id: str
    brand: str
    model: str
    appliance_type: str
    error_code: str = Field(description="The manufacturer's exact spelling, e.g. 'E:24-00' or 'tE1'.")
    code_normalized: str = Field(description="Uppercased, separator-stripped error_code, for lookup.")
    meaning: str = Field(default="", description="What the code means, per the manual. Empty if not stated.")
    likely_causes: list[str] = Field(default_factory=list)
    repair_steps: list[str] = Field(default_factory=list, description="In the order the manual gives them.")
    parts_needed: list[str] = Field(default_factory=list)
    safety_warnings: list[str] = Field(
        default_factory=list, description="Carried over verbatim in substance."
    )
    difficulty: Literal["easy", "moderate", "call_service"] | None = Field(
        default=None, description="Only set when the manual's own guidance clearly implies one."
    )
    source_page: int
    source_section: str | None
    source_chunk_id: str
    extraction_confidence: float = Field(ge=0.0, le=1.0)


def normalize_code(code: str) -> str:
    """Uppercased, separator-stripped form of a manufacturer error code.

    "E:24-00" -> "E2400", "tE1" -> "TE1", "E24" -> "E24" -- lets a lookup key
    on a consistent form without claiming that differently-formatted codes
    for the same fault are the same string (they aren't collapsed further
    than stripping punctuation and case). Shared by both the offline
    extractor (writing error_code/code_normalized) and the runtime retrieval
    layer (normalizing a customer's spoken/typed code before looking it up).
    """
    return re.sub(r"[^A-Za-z0-9]", "", code).upper()
