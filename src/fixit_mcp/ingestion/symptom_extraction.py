"""Extract cited symptom rows from troubleshooting tables with Amazon Nova (step 25b).

Offline ingestion tooling only (see scripts/extract_symptoms.py) -- never imported
by the running MCP server, and the only model call in the symptom path. Nova models
only: `assert_nova_model` refuses anything else, because this step's budget is
Nova-only and a Claude model is both billed through Marketplace and denied to the
project's IAM user (FRICTION_LOG.md).

The model is asked to copy each row's text verbatim into a JSON array. Nothing it
returns is trusted until `audit_rows` passes: the table geometry gives the expected
row count, and for every row the extracted strings, joined, must equal the source
cell (whitespace collapsed, nothing else). An empty or short answer, a missing or
added word, or a wrong footnote link triggers a bounded retry; rows that still fail
are never written.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from fixit_mcp.domain.models import SymptomRecord
from fixit_mcp.ingestion.symptom_tables import SymptomTable, TableRow, collapse

PROMPT_VERSION = "v2"
DEFAULT_MODEL_ID = "us.amazon.nova-pro-v1:0"
DEFAULT_REGION = "us-east-1"
DEFAULT_MAX_ATTEMPTS = 3
MAX_OUTPUT_TOKENS = 8000

# Assumed list prices per 1M input/output tokens (not read from a bill; labelled estimates).
PRICES_PER_M: dict[str, tuple[float, float]] = {
    "us.amazon.nova-pro-v1:0": (0.80, 3.20),
    "us.amazon.nova-2-lite-v1:0": (0.30, 2.50),
}
# Calibrated on the step 25a runs: Nova Pro wrote 1,487-2,032 output tokens for 17- and
# 22-row tables, i.e. 80-90 per row.
OUTPUT_TOKENS_PER_ROW = 90
ESTIMATE_MARGIN = 1.25
CHARS_PER_TOKEN = 3.2  # conservative

SYSTEM_PROMPT = """You are extracting troubleshooting-table rows from one page of a home appliance's \
official manual, for a customer-support tool. Be extremely literal and conservative.

The page content is a table with three columns: Problem (the symptom as the customer would describe \
it), Possible Causes, and What To Do. It is given row by row; each cell is shown as the printed \
lines (a "|" prefix per line). One printed line may be a wrapped continuation of the previous line, \
or a separate item: use the wording to decide.

Output one object per ROW, in page order, with exactly these keys:
- "symptom": array of strings, one string per distinct phrase in the Problem cell ([] if the cell is \
blank). A cell can hold several separate phrasings of the problem (e.g. one per line, each a \
complete statement): make each its own string.
- "possible_causes": array of strings, the Possible Causes cell's distinct items.
- "what_to_do": array of strings, the What To Do cell's distinct items, in order.
- "footnotes": array of verbatim footnote texts from PAGE FOOTNOTES whose marker (* or **) appears \
in this row's cells; otherwise [].

Rules:
- Copy the manual's own wording EXACTLY, including any asterisk markers (* or **) where they are \
printed. Join wrapped lines with a single space. Do not paraphrase, shorten, correct, reorder, \
summarize, or add any word. Every word you output must be in that cell.
- Every printed line of every cell must end up in exactly one string. Do not drop or duplicate any.
- Never invent a cause or an action. If a cell is blank, use [].
- Respond with ONLY the JSON array: no markdown fences, no commentary."""

_DANGLING_WORDS = frozenset(
    "as like including the a an to of and or with for by than if such e.g. i.e.".split()
)


class BudgetExceeded(Exception):
    """The next Bedrock call would pass the spending cap."""


def assert_nova_model(model_id: str) -> None:
    lowered = model_id.lower()
    if "nova" not in lowered or "anthropic" in lowered or "claude" in lowered:
        raise ValueError(
            f"{model_id!r} is not an Amazon Nova model. Symptom extraction is Nova-only "
            "(Claude on Bedrock is Marketplace-billed and denied to the project's IAM user)."
        )


# --- prompt, parsing -------------------------------------------------------


def build_user_prompt(brand: str, model: str, appliance_type: str, table: SymptomTable) -> str:
    from fixit_mcp.ingestion.symptom_tables import render_for_model

    footnotes = "\n".join(table.footnotes) if table.footnotes else "(none)"
    return (
        f"Appliance: {brand} {model} ({appliance_type})\n"
        f"Column headers: {' | '.join(table.headers)}\n"
        "Input format: table rows rebuilt from PDF cell geometry\n\n"
        f"PAGE CONTENT:\n{render_for_model(table)}\n\nPAGE FOOTNOTES:\n{footnotes}\n"
    )


class ExtractedRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symptom: list[str]
    possible_causes: list[str] = []
    what_to_do: list[str] = []
    footnotes: list[str] = []


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped)
    return stripped.strip()


def parse_rows(raw_text: str) -> list[ExtractedRow]:
    """Raises ValueError/ValidationError on anything that is not a JSON array of valid rows."""
    data = json.loads(_strip_fence(raw_text))
    if not isinstance(data, list):
        raise ValueError(f"expected a JSON array, got {type(data).__name__}")
    return [ExtractedRow.model_validate(item) for item in data]


# --- audit -------------------------------------------------------------------

_DOUBLE_STAR = re.compile(r"\*\*")
_SINGLE_STAR = re.compile(r"(?<!\*)\*(?!\*)")


def expected_footnotes(row: TableRow, page_footnotes: list[str]) -> list[str]:
    """The page footnotes this row's own text calls for, from its printed markers."""
    text = row.all_text()
    double, single = bool(_DOUBLE_STAR.search(text)), bool(_SINGLE_STAR.search(text))
    return [
        note
        for note in page_footnotes
        if (double and note.startswith("**"))
        or (single and note.startswith("*") and not note.startswith("**"))
    ]


def ends_mid_sentence(text: str) -> bool:
    """True when a string stops on a word that cannot end a sentence ("... detergent such as")."""
    words = re.sub(r"[\s.,:;*]+$", "", text).split()
    return bool(words) and words[-1].lower() in _DANGLING_WORDS


@dataclass
class Problem:
    message: str
    row: int | None = None  # 1-based; None for a table-level problem


def audit_rows(table: SymptomTable, rows: list[ExtractedRow]) -> list[Problem]:
    """Every way the answer departs from the table. An empty list means the answer is accepted."""
    problems: list[Problem] = []
    if not rows:
        return [Problem(f"empty answer for a table with {len(table.rows)} rows")]
    if len(rows) != len(table.rows):
        return [Problem(f"row count: extracted {len(rows)}, the table has {len(table.rows)}")]
    names = ("symptom", "possible_causes", "what_to_do")
    for number, (got, source) in enumerate(zip(rows, table.rows, strict=True), 1):
        answers = (got.symptom, got.possible_causes, got.what_to_do)
        for index, name in enumerate(names):
            items = answers[index]
            if any(not collapse(item) for item in items):
                problems.append(Problem(f"{name} has an empty string", number))
            joined = collapse(" ".join(items))
            want = source.text(index)
            if joined != want:
                problems.append(
                    Problem(f"{name} differs from the cell: got {joined!r}, cell {want!r}", number)
                )
        want_notes = {collapse(n) for n in expected_footnotes(source, table.footnotes)}
        got_notes = {collapse(n) for n in got.footnotes}
        if got_notes != want_notes:
            problems.append(
                Problem(f"footnotes {sorted(got_notes)!r}, expected {sorted(want_notes)!r}", number)
            )
    return problems


# --- cost ---------------------------------------------------------------------


def estimate_call_cost(model_id: str, user_prompt: str, row_count: int) -> float:
    price_in, price_out = PRICES_PER_M[model_id]
    in_tokens = (len(SYSTEM_PROMPT) + len(user_prompt)) / CHARS_PER_TOKEN
    out_tokens = row_count * OUTPUT_TOKENS_PER_ROW
    return ESTIMATE_MARGIN * (in_tokens * price_in + out_tokens * price_out) / 1e6


def actual_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES_PER_M[model_id]
    return (input_tokens * price_in + output_tokens * price_out) / 1e6


@dataclass
class Budget:
    cap_usd: float
    spent_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    def check(self, estimate_usd: float) -> None:
        if self.spent_usd + estimate_usd > self.cap_usd:
            raise BudgetExceeded(
                f"next call is estimated at ${estimate_usd:.4f}; ${self.spent_usd:.4f} already spent "
                f"would pass the ${self.cap_usd:.2f} cap"
            )

    def record(self, cost_usd: float, input_tokens: int, output_tokens: int) -> None:
        self.spent_usd += cost_usd
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.calls += 1


# --- extraction -----------------------------------------------------------------


@dataclass
class TableResult:
    table: SymptomTable
    rows: list[ExtractedRow] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)  # of the last attempt; empty = accepted
    attempt_problems: list[list[Problem]] = field(default_factory=list)  # one entry per rejected attempt
    attempts: int = 0
    cached: bool = False
    cost_usd: float = 0.0

    @property
    def accepted(self) -> bool:
        return not self.problems and bool(self.rows)


def _make_client(region: str) -> Any:
    import boto3

    return boto3.client("bedrock-runtime", region_name=region)


class NovaSymptomExtractor:
    def __init__(
        self,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        region: str = DEFAULT_REGION,
        client: Any | None = None,
        budget: Budget,
        cache_dir: Path | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        force: bool = False,
    ) -> None:
        assert_nova_model(model_id)
        if model_id not in PRICES_PER_M:
            raise ValueError(f"no assumed price for {model_id!r}; add it to PRICES_PER_M")
        self.model_id = model_id
        self.budget = budget
        self.max_attempts = max_attempts
        self.cache_dir = cache_dir
        self.force = force
        self._client = client if client is not None else _make_client(region)

    def _cache_path(self, user_prompt: str) -> Path | None:
        if self.cache_dir is None:
            return None
        key = hashlib.sha256(
            f"{self.model_id}\n{PROMPT_VERSION}\n{SYSTEM_PROMPT}\n{user_prompt}".encode()
        ).hexdigest()[:20]
        return self.cache_dir / f"{key}.json"

    def _invoke(self, user_prompt: str, row_count: int) -> tuple[str, float]:
        self.budget.check(estimate_call_cost(self.model_id, user_prompt, row_count))
        response = self._client.converse(
            modelId=self.model_id,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": user_prompt}]}],
            inferenceConfig={"maxTokens": MAX_OUTPUT_TOKENS, "temperature": 0},
        )
        text = response["output"]["message"]["content"][0]["text"]
        usage = response.get("usage", {})
        in_tokens, out_tokens = usage.get("inputTokens", 0), usage.get("outputTokens", 0)
        cost = actual_cost(self.model_id, in_tokens, out_tokens)
        self.budget.record(cost, in_tokens, out_tokens)
        return text, cost

    def extract_table(self, brand: str, model: str, appliance_type: str, table: SymptomTable) -> TableResult:
        base_prompt = build_user_prompt(brand, model, appliance_type, table)
        result = TableResult(table=table)
        cache_path = self._cache_path(base_prompt)

        if cache_path is not None and not self.force and cache_path.exists():
            try:
                cached = [ExtractedRow.model_validate(r) for r in json.loads(cache_path.read_text())]
            except (ValueError, ValidationError):
                cached = []
            if cached and not audit_rows(table, cached):  # the audit is re-run, never skipped
                result.rows, result.cached = cached, True
                return result

        prompt = base_prompt
        for attempt in range(1, self.max_attempts + 1):
            result.attempts = attempt
            raw, cost = self._invoke(prompt, len(table.rows))
            result.cost_usd += cost
            try:
                rows = parse_rows(raw)
            except (ValueError, ValidationError) as exc:
                result.rows, result.problems = [], [Problem(f"unparseable answer: {str(exc)[:200]}")]
            else:
                result.rows, result.problems = rows, audit_rows(table, rows)
            if result.accepted:
                if cache_path is not None:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(
                        json.dumps([r.model_dump() for r in result.rows], ensure_ascii=False)
                    )
                return result
            result.attempt_problems.append(result.problems)
            hint = "; ".join((f"row {p.row}: " if p.row else "") + p.message for p in result.problems[:5])
            prompt = (
                base_prompt + f"\n\nYour previous answer was rejected: {hint}. The table has exactly "
                f"{len(table.rows)} rows. Respond again with ONLY the JSON array."
            )
        return result


def estimate_tables(model_id: str, tables_with_prompts: list[tuple[SymptomTable, str]]) -> float:
    return sum(estimate_call_cost(model_id, prompt, len(t.rows)) for t, prompt in tables_with_prompts)


# --- records ------------------------------------------------------------------------


def build_records(
    results: list[TableResult], *, brand: str, model: str, appliance_type: str
) -> tuple[list[SymptomRecord], list[str]]:
    """Records for the accepted tables, in page order, plus human-readable notes.

    A row whose Problem cell is blank carries the symptom of the row above (also across a page
    break) and is marked `symptom_continued`; the first row of the first table cannot be blank.
    """
    records: list[SymptomRecord] = []
    notes: list[str] = []
    carried: list[str] = []
    carried_label = ""
    for result in results:
        table = result.table
        for number, (got, source) in enumerate(zip(result.rows, table.rows, strict=True), 1):
            continued = not got.symptom
            if continued:
                if not carried:
                    raise ValueError(
                        f"p.{table.page} row {number}: blank Problem cell with nothing to continue"
                    )
                if number == 1:
                    notes.append(f"p.{table.page} row 1 continues a symptom from the previous table")
                symptom, label = carried, carried_label
            else:
                symptom, label = got.symptom, table.headers[0]
                carried, carried_label = symptom, label
            strings = [*got.symptom, *got.possible_causes, *got.what_to_do]
            dangling = [s for s in strings if ends_mid_sentence(s)]
            incomplete = bool(dangling)
            for s in dangling:
                notes.append(f"p.{table.page} row {number} ends mid-sentence: {s!r}")
            records.append(
                SymptomRecord(
                    manual_id=table.manual_id,
                    brand=brand,
                    model=model,
                    appliance_type=appliance_type,
                    symptom=list(symptom),
                    symptom_label=label,
                    symptom_continued=continued,
                    possible_causes=got.possible_causes,
                    what_to_do=got.what_to_do,
                    response_label=table.headers[2],
                    footnotes=expected_footnotes(source, table.footnotes),
                    text_incomplete=incomplete,
                    source_page=table.page,
                    source_section=table.section,
                )
            )
    return records, notes
