"""Parse appliance manual PDFs into section-aware chunks.

This is offline ingestion tooling (run via scripts/parse_manuals.py), never
imported by the running MCP server -- no LLM calls, no network, no AWS.

Extraction is done with PyMuPDF (`pymupdf`, imported as `fitz`). See
docs/pdf-extraction-library-choice.md for why, based on running pypdf,
pdfplumber, and PyMuPDF against our actual manuals: all three decode text
identically (extraction quality is bottlenecked by the source PDF's own font
encoding, not the library), but PyMuPDF is the only one that exposes per-line
font size/weight and precise bounding boxes -- exactly the layout signals this
module needs for heading detection and column-aware reading order -- and it is
dramatically faster on our largest manual (168 pages).

Heading detection, in priority order (a documented fallback chain, since not
every manual's headings are typographically distinct from body text):
  1. A numbered section prefix at the start of the line, e.g. "17 Troubleshooting"
     or "13.10 Terminating the wash cycle" -- the numbering's dot-depth gives
     us the heading's nesting depth directly.
  2. A line whose font is bold or noticeably larger than the document's body
     text size.
  3. A short, mostly-uppercase line (e.g. "TROUBLESHOOTING TIPS") -- some of
     our manuals use ALL CAPS section titles set in the same font size as
     body text, so size/weight alone would miss them.

Table detection is a best-effort heuristic, not real table-structure
extraction: pdfplumber's geometric table detector was tried on our manuals
and proved unreliable (it mangled a rotated sidebar into a garbage phantom
"table" on one real page, see FRICTION_LOG.md), so instead a section is
flagged as table-like when its text contains both a problem/error-code header
phrase and a solution/action header phrase -- the reading-order plain text
IS the "table" here, which is what error-code content in these manuals
actually looks like once extracted.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from pydantic import BaseModel, Field

# PyMuPDF span flag bit for bold text (see pymupdf docs: TextPage.extractDICT).
_BOLD_FLAG = 1 << 4

# A heading numbered like "17" or "13.10" or "15.2.1" at the start of a short line.
_NUMBERED_HEADING_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\s+([A-Z][^\n]{1,80})$")

# A line that is *only* a page number -- always stripped as a footer/header artifact.
_PAGE_NUMBER_RE = re.compile(r"^\d{1,4}$")

# Section text is considered table-like when it pairs a "problem" phrase with
# a "solution" phrase -- both sides of a troubleshooting/error-code table.
_TABLE_PROBLEM_PATTERNS = (
    re.compile(r"\bpossible causes\b", re.I),
    re.compile(r"\berror codes?\b", re.I),
    re.compile(r"\bfault codes?\b", re.I),
    re.compile(r"\bproblem\b", re.I),
    re.compile(r"\bissue\b", re.I),  # Bosch's manuals use "Issue" as the problem-side column header.
)
_TABLE_SOLUTION_PATTERNS = (
    re.compile(r"\bsolutions?\b", re.I),
    re.compile(r"\bcause and troubleshooting\b", re.I),  # Bosch's combined cause/fix column header.
    re.compile(r"\bwhat to do\b", re.I),
)

MAX_CHUNK_CHARS = 1800
OVERLAP_CHARS = 200
# A normalized line repeated across at least this fraction of a manual's pages
# is treated as running header/footer boilerplate rather than real content.
BOILERPLATE_PAGE_FRACTION = 0.25


class ManualMeta(BaseModel):
    """Metadata for one manifest entry (data/manuals/manifest.yaml), passed
    into parse_manual so its chunks can be tagged with the manual's id."""

    id: str
    brand: str
    model: str
    appliance_type: str


class ManualChunk(BaseModel):
    """One section-bounded, size-limited slice of a parsed manual."""

    manual_id: str
    chunk_id: str
    text: str
    page_start: int = Field(description="1-indexed page the chunk starts on.")
    page_end: int = Field(description="1-indexed page the chunk ends on.")
    section_heading: str | None = Field(description="Heading of the section this chunk belongs to.")
    section_path: list[str] = Field(description="Breadcrumb of nested headings, root first.")
    is_table: bool = Field(
        description="Best-effort flag: does this section read like a code/troubleshooting table?"
    )


@dataclass
class Line:
    """One line of extracted text with the layout signals used for heading detection."""

    page_no: int
    text: str
    font_size: float
    is_bold: bool


@dataclass
class Section:
    """Contiguous manual content between one heading and the next."""

    heading: str | None
    section_path: list[str]
    lines: list[Line] = field(default_factory=list)


def is_allcaps_heading(text: str) -> bool:
    """A short line that's almost entirely uppercase letters, e.g. 'TROUBLESHOOTING TIPS'.

    Some source PDFs in this corpus embed a font whose ToUnicode mapping is
    corrupted for certain text runs, which decodes as garbled strings that are
    often *also* mostly-uppercase (e.g. ")LOWHU FDUWULGJH" for "Filter
    cartridge") and would otherwise be misdetected as headings. Requiring the
    line to start with a letter cheaply rejects most of these -- corrupted
    runs typically start with a stray digit or punctuation glyph standing in
    for the real first letter. This does not fix the underlying corruption
    (see FRICTION_LOG.md); it only stops it from also wrecking chunk boundaries.
    """
    stripped = text.strip()
    if not (3 <= len(stripped) <= 70):
        return False
    if not stripped[0].isalpha():
        return False
    letters = [c for c in stripped if c.isalpha()]
    if not letters:
        return False
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    if upper_ratio < 0.9:
        return False
    return not stripped.endswith((".", ",", ";", ":"))


def heading_info(line: Line, body_font_size: float) -> tuple[bool, int] | None:
    """Return (is_heading, nesting_depth) for this line, or None.

    See the module docstring for the three-signal fallback chain this implements.
    """
    numbered = _NUMBERED_HEADING_RE.match(line.text.strip())
    if numbered:
        depth = numbered.group(1).count(".") + 1
        return True, depth

    size_ratio = (line.font_size / body_font_size) if body_font_size else 1.0
    # Bold *alone* is not trusted: some manuals bold an entire troubleshooting
    # table column (e.g. "Problem"/"Possible Causes") at body text size, which
    # would otherwise shred that table into one false "heading" per row.
    # Weight only counts as a signal alongside a real size increase.
    notably_larger = size_ratio >= 1.3 or (line.is_bold and size_ratio >= 1.2)
    short_enough = len(line.text.strip()) <= 80
    ends_like_a_sentence = line.text.strip().endswith((".", ",", ";"))
    if notably_larger and short_enough and not ends_like_a_sentence:
        return True, 1

    if is_allcaps_heading(line.text):
        return True, 1

    return None


def looks_like_table(text: str) -> bool:
    """Best-effort: does this section's text read like a troubleshooting/error-code table?"""
    has_problem_side = any(p.search(text) for p in _TABLE_PROBLEM_PATTERNS)
    has_solution_side = any(p.search(text) for p in _TABLE_SOLUTION_PATTERNS)
    return has_problem_side and has_solution_side


def find_boilerplate(pages: list[list[Line]]) -> set[str]:
    """Find normalized line text that repeats across many pages -- running
    headers/footers -- so it can be stripped before heading detection and
    chunking (otherwise a repeated sidebar can be mistaken for a heading on
    every page it appears on)."""
    total_pages = len(pages)
    if total_pages == 0:
        return set()

    page_presence: dict[str, set[int]] = {}
    for page_lines in pages:
        seen_on_this_page: set[str] = set()
        for line in page_lines:
            key = line.text.strip().lower()
            if not key or key in seen_on_this_page:
                continue
            seen_on_this_page.add(key)
            page_presence.setdefault(key, set()).add(line.page_no)

    threshold = max(3, int(total_pages * BOILERPLATE_PAGE_FRACTION))
    return {
        key for key, pages_seen in page_presence.items() if len(key) <= 100 and len(pages_seen) >= threshold
    }


def strip_boilerplate(pages: list[list[Line]], boilerplate: set[str]) -> list[list[Line]]:
    """Remove boilerplate lines and bare page-number lines from every page."""
    cleaned: list[list[Line]] = []
    for page_lines in pages:
        kept = [
            line
            for line in page_lines
            if line.text.strip().lower() not in boilerplate and not _PAGE_NUMBER_RE.match(line.text.strip())
        ]
        cleaned.append(kept)
    return cleaned


def build_sections(pages: list[list[Line]]) -> list[Section]:
    """Group lines into sections bounded by detected headings, tracking a
    breadcrumb of ancestor headings (section_path) via a depth stack."""
    all_lines = [line for page_lines in pages for line in page_lines]
    body_font_size = statistics.median(line.font_size for line in all_lines) if all_lines else 10.0

    sections: list[Section] = []
    heading_stack: list[tuple[int, str]] = []
    current = Section(heading=None, section_path=[])

    for line in all_lines:
        info = heading_info(line, body_font_size)
        if info is None:
            current.lines.append(line)
            continue

        _, depth = info
        if current.heading is not None or current.lines:
            sections.append(current)

        while heading_stack and heading_stack[-1][0] >= depth:
            heading_stack.pop()
        heading_text = line.text.strip()
        heading_stack.append((depth, heading_text))

        current = Section(heading=heading_text, section_path=[h for _, h in heading_stack], lines=[line])

    if current.heading is not None or current.lines:
        sections.append(current)

    return sections


def split_section_into_chunks(
    section: Section, manual_id: str, next_chunk_index: list[int]
) -> list[ManualChunk]:
    """Split one section's lines into <=MAX_CHUNK_CHARS chunks with overlap.
    Never crosses a section boundary -- this is only ever called with the
    lines of a single section."""
    lines = section.lines
    if not lines:
        return []

    is_table = looks_like_table("\n".join(line.text for line in lines))
    chunks: list[ManualChunk] = []
    n = len(lines)
    i = 0

    while i < n:
        acc_len = 0
        j = i
        while j < n and (acc_len == 0 or acc_len + len(lines[j].text) + 1 <= MAX_CHUNK_CHARS):
            acc_len += len(lines[j].text) + 1
            j += 1

        chunk_lines = lines[i:j]
        next_chunk_index[0] += 1
        chunks.append(
            ManualChunk(
                manual_id=manual_id,
                chunk_id=f"{manual_id}::chunk-{next_chunk_index[0]:04d}",
                text="\n".join(line.text for line in chunk_lines),
                page_start=chunk_lines[0].page_no,
                page_end=chunk_lines[-1].page_no,
                section_heading=section.heading,
                section_path=section.section_path,
                is_table=is_table,
            )
        )

        if j >= n:
            break

        # Back up from j to build the next chunk's overlap, but never so far
        # that we fail to make forward progress.
        k = j
        overlap_len = 0
        while k > i and overlap_len < OVERLAP_CHARS:
            k -= 1
            overlap_len += len(lines[k].text) + 1
        i = k if k > i else j

    return chunks


def _extract_lines_by_page(doc: pymupdf.Document) -> list[list[Line]]:
    """Extract lines per page in reading order, using each line's dominant
    font size and bold-ness as the layout signals for heading detection.

    Reading order across columns: blocks are sorted by (column, y-position),
    where a block is assigned to column 0 if it starts left of the page's
    horizontal midpoint and column 1 otherwise. This is a documented
    simplification -- it handles the common up-to-two-column layout in these
    manuals but would not generalize to a 3+ column layout.
    """
    pages: list[list[Line]] = []
    for page in doc:
        page_width = page.rect.width
        blocks = [b for b in page.get_text("dict")["blocks"] if b.get("type") == 0]
        blocks.sort(key=lambda b: (0 if b["bbox"][0] < page_width / 2 else 1, b["bbox"][1]))

        lines: list[Line] = []
        for block in blocks:
            for raw_line in block.get("lines", []):
                spans = raw_line.get("spans", [])
                text = "".join(s["text"] for s in spans).strip()
                if not text:
                    continue
                font_size = max(s["size"] for s in spans)
                is_bold = any(s["flags"] & _BOLD_FLAG for s in spans)
                lines.append(Line(page_no=page.number + 1, text=text, font_size=font_size, is_bold=is_bold))
        pages.append(lines)
    return pages


def parse_manual(pdf_path: str | Path, manual_meta: ManualMeta) -> list[ManualChunk]:
    """Parse one manual PDF into section-aware chunks."""
    doc = pymupdf.open(pdf_path)
    try:
        pages = _extract_lines_by_page(doc)
    finally:
        doc.close()

    boilerplate = find_boilerplate(pages)
    pages = strip_boilerplate(pages, boilerplate)
    sections = build_sections(pages)

    chunks: list[ManualChunk] = []
    next_chunk_index = [0]
    for section in sections:
        chunks.extend(split_section_into_chunks(section, manual_meta.id, next_chunk_index))
    return chunks
