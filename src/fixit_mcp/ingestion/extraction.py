"""Extract structured, cited error-code records from parsed manual chunks.

Offline ingestion tooling only (see scripts/extract_codes.py) -- never
imported by the running MCP server. No LLM calls happen anywhere in this
project except inside BedrockExtractor.extract() below, which is only ever
invoked by that script, never from a tool handler (see CLAUDE.md's
no-LLM-in-tool-handlers rule).

Two extractors implement the same ErrorCodeExtractor interface:
  - StubExtractor: deterministic, regex-based, no network, no AWS
    credentials required. It only recognizes a handful of known code shapes
    (see _CODE_PATTERNS) and never fills in meaning/causes/steps/parts/
    warnings -- those require actually reading and understanding the
    surrounding prose, which a fixed regex can't honestly claim to do. It
    exists so the pipeline (chunk selection, caching, output format) can be
    exercised and tested without AWS, not for extraction quality.
  - BedrockExtractor: calls Amazon Bedrock (an Anthropic Claude model) via
    boto3, asks for a strict JSON array matching ErrorCodeRecord's semantic
    fields, validates the response with pydantic, and retries a bounded
    number of times on malformed output. Returns an empty list -- never a
    guess -- when a chunk has no real error codes, or when every retry still
    produced unusable output.
"""

from __future__ import annotations

import json
import re
from typing import Literal, Protocol

from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from fixit_mcp.ingestion.parser import ManualChunk


class ErrorCodeRecord(BaseModel):
    """One extracted, cited error-code record.

    Every field beyond error_code/code_normalized/extraction_confidence is
    extracted *only* from what the manual's text actually states -- a
    missing field is an empty list/string, never a guess.
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
    than stripping punctuation and case).
    """
    return re.sub(r"[^A-Za-z0-9]", "", code).upper()


class ErrorCodeExtractor(Protocol):
    """Interface both extractors implement."""

    def extract(self, chunk: ManualChunk) -> list[ErrorCodeRecord]: ...


# --- StubExtractor -----------------------------------------------------

# Known real code shapes seen in this project's manual corpus (see
# FRICTION_LOG.md / data/manuals/parsed/). Deliberately specific rather than
# a broad "any short alnum token" pattern -- a stub that over-matches would
# be worse than one that under-matches, since nothing downstream validates
# its output the way BedrockExtractor's schema validation does.
_CODE_PATTERNS = (
    re.compile(r"\bE:\d{2}-\d{2}\b"),  # Bosch, e.g. E:24-00
    re.compile(r"\b[tT]E\d\b"),  # LG, e.g. tE1
    re.compile(r"\bP[SF]\b"),  # LG, e.g. PS, PF
    re.compile(r"\bnP\b"),  # LG
    re.compile(r"\bHS\b"),  # LG, Humidity Sensor
)

_STUB_CONFIDENCE = 0.3  # Always low: a regex match, not a verified understanding.


class StubExtractor:
    """Deterministic, no-network, no-AWS-credentials-required extractor.

    Finds tokens matching known real code shapes and reports only the code
    itself -- meaning/causes/steps/parts/warnings are left empty, since a
    fixed regex has no basis for filling them in without inventing content.
    """

    def extract(self, chunk: ManualChunk) -> list[ErrorCodeRecord]:
        seen: set[str] = set()
        records: list[ErrorCodeRecord] = []
        for pattern in _CODE_PATTERNS:
            for match in pattern.finditer(chunk.text):
                code = match.group(0)
                if code in seen:
                    continue
                seen.add(code)
                records.append(
                    ErrorCodeRecord(
                        manual_id=chunk.manual_id,
                        brand=chunk.brand,
                        model=chunk.model,
                        appliance_type=chunk.appliance_type,
                        error_code=code,
                        code_normalized=normalize_code(code),
                        source_page=chunk.page_start,
                        source_section=chunk.section_heading,
                        source_chunk_id=chunk.chunk_id,
                        extraction_confidence=_STUB_CONFIDENCE,
                    )
                )
        return records


# --- BedrockExtractor ----------------------------------------------------


class ExtractionSettings(BaseSettings):
    """Config for which extractor to use and how to reach Bedrock.

    Kept separate from fixit_mcp.config.Settings (the running server's
    config) since this only matters to offline ingestion, never to the
    server -- see CLAUDE.md.
    """

    model_config = SettingsConfigDict(env_prefix="FIXIT_", env_file=".env", extra="ignore")

    extractor: Literal["bedrock", "stub"] = "stub"
    bedrock_region: str = "us-east-1"
    # Verified working in this project's dev AWS account (2026-09) via a
    # live converse() call. Model access on Bedrock is per-account/region:
    # a bare id like "anthropic.claude-sonnet-5" can be listed as ACTIVE by
    # list_foundation_models yet still be denied for a given account
    # ("not available for this account"), and a dated/legacy-style id
    # (e.g. "anthropic.claude-sonnet-4-5-20250929-v1:0") is rejected for
    # on-demand throughput and needs a cross-region inference profile
    # ("us."/"eu."/... prefix) instead -- see FRICTION_LOG.md. If this
    # default isn't enabled in your account, run `aws bedrock
    # list-foundation-models` and try candidates with a "us." prefix.
    bedrock_model_id: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    extractor_max_retries: int = 2


_SYSTEM_PROMPT = """You are extracting structured error-code records from one page of a home \
appliance's official manual, for a customer-support tool. Be extremely literal and conservative:

- Extract ONLY error/fault codes that this text actually documents. If the text has no error \
codes, return an empty JSON array: [].
- Never invent a cause, a repair step, a part, or a safety warning that isn't stated in the \
text. If a field isn't stated, leave it an empty list (or empty string for "meaning") -- never \
a guess.
- Preserve the manufacturer's exact spelling and punctuation of each code in "error_code" \
(e.g. "E:24-00", "tE1", "F1").
- "repair_steps" must be in the order the manual gives them.
- "safety_warnings" must carry over what the manual states verbatim in substance (not \
paraphrased away) when it gives one for that code.
- Set "difficulty" only when the text's own guidance clearly implies one: "easy" (a simple \
user action fixes it), "moderate" (some disassembly or tools needed), "call_service" (the \
manual says to call for service or a technician). Use null if genuinely unclear.
- Set "extraction_confidence" (0.0-1.0) to your own honest confidence that this record is \
fully and correctly extracted from the given text.

Some of this text was automatically repaired from a corrupted PDF font encoding. Any token \
listed under "UNCERTAIN REPAIRS" below might be WRONG -- if a repaired token doesn't make sense \
as part of an error code or its description, prefer what the original (pre-repair) text most \
likely means, or omit that detail, rather than trust a nonsensical repair.

Respond with ONLY a JSON array (no markdown fences, no commentary before or after) of objects \
with exactly these keys: error_code, meaning, likely_causes, repair_steps, parts_needed, \
safety_warnings, difficulty, extraction_confidence. Return [] if this text contains no error \
codes."""

_RETRY_HINT = (
    "\n\nYour previous response could not be parsed as a valid JSON array matching the required "
    "schema. Respond again with ONLY a JSON array -- no markdown code fences, no commentary."
)

_RECORD_KEYS = (
    "error_code",
    "meaning",
    "likely_causes",
    "repair_steps",
    "parts_needed",
    "safety_warnings",
    "difficulty",
    "extraction_confidence",
)


def _build_user_prompt(chunk: ManualChunk) -> str:
    lines = [
        f"Appliance: {chunk.brand} {chunk.model} ({chunk.appliance_type})",
        f"Manual section: {chunk.section_heading or '(no heading)'}",
        "",
        "TEXT:",
        chunk.text,
    ]
    if chunk.uncertain_repairs:
        lines.append("")
        lines.append("UNCERTAIN REPAIRS in this text (original -> repaired, confidence):")
        for ur in chunk.uncertain_repairs:
            lines.append(f'  "{ur.original}" -> "{ur.repaired}" (confidence {ur.confidence})')
    return "\n".join(lines)


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped)
    return stripped.strip()


def _parse_records(raw_text: str, chunk: ManualChunk) -> list[ErrorCodeRecord]:
    """Parse and validate a model response. Raises ValueError/ValidationError
    on anything malformed -- the caller decides whether to retry."""
    cleaned = _strip_markdown_fence(raw_text)
    data = json.loads(cleaned)  # raises json.JSONDecodeError
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array, got {type(data).__name__}")

    records: list[ErrorCodeRecord] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError(f"Expected each array element to be an object, got {type(item).__name__}")
        unexpected = set(item) - set(_RECORD_KEYS)
        if unexpected:
            raise ValueError(f"Unexpected keys in model output: {sorted(unexpected)}")
        error_code = item.get("error_code", "")
        record = ErrorCodeRecord(
            manual_id=chunk.manual_id,
            brand=chunk.brand,
            model=chunk.model,
            appliance_type=chunk.appliance_type,
            error_code=error_code,
            code_normalized=normalize_code(error_code) if error_code else "",
            meaning=item.get("meaning", ""),
            likely_causes=item.get("likely_causes", []),
            repair_steps=item.get("repair_steps", []),
            parts_needed=item.get("parts_needed", []),
            safety_warnings=item.get("safety_warnings", []),
            difficulty=item.get("difficulty"),
            source_page=chunk.page_start,
            source_section=chunk.section_heading,
            source_chunk_id=chunk.chunk_id,
            extraction_confidence=item.get("extraction_confidence", 0.0),
        )  # raises pydantic.ValidationError
        records.append(record)
    return records


class BedrockExtractor:
    """Calls Amazon Bedrock (Claude) to extract error-code records.

    Retries a bounded number of times (extractor_max_retries) if the model's
    response doesn't parse as JSON or doesn't validate against
    ErrorCodeRecord's schema, appending a short retry hint each time. Gives
    up and returns [] rather than ever guessing at malformed output.
    """

    def __init__(
        self,
        region: str,
        model_id: str,
        max_retries: int = 2,
        client: object | None = None,
    ) -> None:
        self._model_id = model_id
        self._max_retries = max_retries
        self._client = client if client is not None else _make_bedrock_client(region)
        self.last_usage: dict[str, int] | None = None

    def extract(self, chunk: ManualChunk) -> list[ErrorCodeRecord]:
        user_prompt = _build_user_prompt(chunk)
        self.last_usage = None

        for attempt in range(self._max_retries + 1):
            prompt = user_prompt + (_RETRY_HINT if attempt > 0 else "")
            raw_text, usage = self._invoke(prompt)
            self.last_usage = usage
            try:
                return _parse_records(raw_text, chunk)
            except (json.JSONDecodeError, ValueError, ValidationError):
                continue

        return []

    def _invoke(self, prompt: str) -> tuple[str, dict[str, int]]:
        response = self._client.converse(
            modelId=self._model_id,
            system=[{"text": _SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 4096, "temperature": 0},
        )
        text = response["output"]["message"]["content"][0]["text"]
        usage = {
            "input_tokens": response.get("usage", {}).get("inputTokens", 0),
            "output_tokens": response.get("usage", {}).get("outputTokens", 0),
        }
        return text, usage


def _make_bedrock_client(region: str):
    import boto3

    return boto3.client("bedrock-runtime", region_name=region)


def make_extractor(settings: ExtractionSettings | None = None) -> ErrorCodeExtractor:
    """Build the configured extractor (FIXIT_EXTRACTOR=bedrock|stub)."""
    settings = settings or ExtractionSettings()
    if settings.extractor == "stub":
        return StubExtractor()
    return BedrockExtractor(
        region=settings.bedrock_region,
        model_id=settings.bedrock_model_id,
        max_retries=settings.extractor_max_retries,
    )
