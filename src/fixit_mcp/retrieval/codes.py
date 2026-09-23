"""In-memory error-code index, built once at server startup from the
committed data/index/error_codes.json artifact.

No file I/O and no network in the request path (CLAUDE.md rules 3/4) --
load_index() does all of that once, at startup; the resulting ErrorCodeIndex
is pure in-memory dict lookups from then on, well under the 500ms budget.

Two things from step 3a's own friction log are fixed here, at load time,
rather than by editing the committed artifact -- so re-running extraction
stays idempotent and this logic stays testable against the real data:

  1. Dedup by (manual_id, code_normalized): the same code can appear twice
     when its manual entry falls across a chunk-overlap boundary (e.g.
     Bosch's E:34-00), producing one complete and one truncated record for
     the same code. Keep whichever has more populated content fields, then
     higher extraction_confidence.
  2. Flag non-lookupable records: a manual sometimes describes a *range* or
     a *placeholder* rather than one concrete code (Bosch's "E:01-00 to
     E:90-10", GE's "F-- and a number or letter"). These are never added to
     the exact-match index -- a customer typing "E24" must never accidentally
     match a range description -- but are kept separately so a not-found
     response for that manual can still say "this manual describes a general
     code family here" instead of a flat failure.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from fixit_mcp.domain.models import ErrorCodeRecord

DEFAULT_INDEX_PATH = Path(__file__).resolve().parents[3] / "data" / "index" / "error_codes.json"

_CONTENT_FIELDS = ("meaning", "likely_causes", "repair_steps", "parts_needed", "safety_warnings")

# A real code in this corpus normalizes to at most ~6-8 characters (e.g.
# "E2400" for "E:24-00", "TE1" for "tE1"). A manual's own generic placeholder
# or range description swallows whole descriptive words once normalize_code()
# strips their spaces, producing a much longer normalized string -- checked
# here alongside actual English words in the *original*, still-spaced
# error_code text (word boundaries are meaningless after normalization).
MAX_LOOKUPABLE_NORMALIZED_LEN = 10
_PLACEHOLDER_WORD_RE = re.compile(r"\b(AND|FOR|WITH|LETTER|NUMBER|APPEARS|DIFFERENT|FLASH)\b", re.I)


def is_lookupable(record: ErrorCodeRecord) -> bool:
    """Best-effort: does this record identify one concrete, matchable code,
    or is it the manual's own generic placeholder/range description? See
    FRICTION_LOG.md (step 3a) for the two real examples this exists for.
    """
    if len(record.code_normalized) > MAX_LOOKUPABLE_NORMALIZED_LEN:
        return False
    return not _PLACEHOLDER_WORD_RE.search(record.error_code)


def _populated_field_count(record: ErrorCodeRecord) -> int:
    return sum(1 for name in _CONTENT_FIELDS if getattr(record, name))


def _better_of(a: ErrorCodeRecord, b: ErrorCodeRecord) -> ErrorCodeRecord:
    """Dedup tiebreak for two records sharing (manual_id, code_normalized):
    prefer more populated content fields, then higher extraction_confidence."""
    a_key = (_populated_field_count(a), a.extraction_confidence)
    b_key = (_populated_field_count(b), b.extraction_confidence)
    return a if a_key >= b_key else b


@dataclass
class ErrorCodeIndex:
    """Deduplicated, in-memory error-code lookup, built once by load_index().

    by_manual_and_code holds every deduplicated record (lookupable or not),
    keyed for exact per-manual lookup. lookupable_by_code and
    family_by_manual are the two views diagnose_error actually queries.
    """

    by_manual_and_code: dict[tuple[str, str], ErrorCodeRecord]
    lookupable_by_code: dict[str, list[ErrorCodeRecord]] = field(default_factory=dict)
    family_by_manual: dict[str, list[ErrorCodeRecord]] = field(default_factory=dict)

    def by_code(self, code_normalized: str) -> list[ErrorCodeRecord]:
        """Every lookupable record (across all manuals) matching this
        normalized code -- empty if none."""
        return self.lookupable_by_code.get(code_normalized, [])

    def family_note_for_manual(self, manual_id: str) -> ErrorCodeRecord | None:
        """The manual's own generic code-family description, if it has one
        (e.g. GE's "F-- and a number or letter") -- for a not-found response
        to fall back on instead of a flat failure."""
        records = self.family_by_manual.get(manual_id)
        return records[0] if records else None

    def nearest_codes(self, code_normalized: str, limit: int = 3) -> list[str]:
        """Cheap, deterministic "did you mean" suggestions -- no LLM, just
        stdlib string similarity over the known lookupable codes."""
        return difflib.get_close_matches(
            code_normalized, sorted(self.lookupable_by_code), n=limit, cutoff=0.5
        )


def load_index(path: Path | None = None) -> ErrorCodeIndex:
    """Load, deduplicate, and index data/index/error_codes.json. Call once
    at server startup -- never per-request (rule 4, the <500ms budget)."""
    path = path or DEFAULT_INDEX_PATH
    raw = json.loads(path.read_text())
    records = [ErrorCodeRecord.model_validate(item) for item in raw]

    deduped: dict[tuple[str, str], ErrorCodeRecord] = {}
    for record in records:
        key = (record.manual_id, record.code_normalized)
        deduped[key] = _better_of(deduped[key], record) if key in deduped else record

    lookupable_by_code: dict[str, list[ErrorCodeRecord]] = {}
    family_by_manual: dict[str, list[ErrorCodeRecord]] = {}
    for record in deduped.values():
        if is_lookupable(record):
            lookupable_by_code.setdefault(record.code_normalized, []).append(record)
        else:
            family_by_manual.setdefault(record.manual_id, []).append(record)

    return ErrorCodeIndex(
        by_manual_and_code=deduped,
        lookupable_by_code=lookupable_by_code,
        family_by_manual=family_by_manual,
    )
