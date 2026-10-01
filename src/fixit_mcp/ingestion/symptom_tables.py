"""Read a manual's "Problem / Possible Causes / What To Do" tables as rows (step 25b).

Offline ingestion tooling only -- never imported by the running server.

The parser in `fixit_mcp.ingestion.parser` reads text in reading order and
handles at most two columns, so a three-column table comes out as a run of
problems, then a run of causes, then a run of actions, with the row alignment
lost (FRICTION_LOG.md, step 25a). This module takes the table's *geometry* from
PyMuPDF `find_tables()` and the *text* from span-level extraction clipped to each
cell, so every cell keeps the printed lines it had on the page.

Font repair is done per span, not per line (the parser's `Line` merges spans):
in the GE refrigerator PDF the corrupted text is a separate span from the clean
text, and a corrupted span always contains the encoded space (`\\x03` for the
+29 offset) or another C0 control character, which clean text never has. The
shift is only ever applied with the document's offset as already established by
the parser's whole-line repair (`dominant_offset_for_pages`); it is never
searched for here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from fixit_mcp.ingestion.parser import dominant_offset_for_pages, extract_lines

# The refrigerator's font prints the curly quotes as U+00B3 / U+00B4 in a
# corrupted span. Hand-checked against the rendered page (step 25a); a corrupted
# span in another manual is left as-is for those characters rather than guessed.
_CORRUPTED_SPAN_QUOTES = {"³": "“", "´": "”"}

_COLUMN_1 = {"problem", "sounds"}
_COLUMN_2 = {"possible causes"}
_COLUMN_3 = {"what to do", "reason"}
_SECTION_RE = re.compile(r"troubleshooting tips", re.I)


class TableReadError(Exception):
    """A table could not be read faithfully (e.g. unrepaired font corruption)."""


def collapse(text: str) -> str:
    """Whitespace collapsed to single spaces -- the only normalization the audit allows."""
    return " ".join(text.split())


def join_lines(lines: list[str]) -> str:
    """Join printed lines with a space, except where a line breaks right after a hyphen in front of a
    lowercase continuation ("non-" + "stick" -> "non-stick") or after an en dash inside a range in
    front of an alphanumeric ("48°C–" + "60°C" -> "48°C–60°C"): the manuals break lines at the real
    punctuation, so the space is a typesetting artifact, not part of the wording."""
    out = ""
    for line in lines:
        line = collapse(line)
        if not line:
            continue
        glued_hyphen = out.endswith("-") and len(out) > 1 and out[-2].isalpha() and line[0].islower()
        glued_range = out.endswith("\u2013") and len(out) > 1 and not out[-2].isspace() and line[0].isalnum()
        if out and (glued_hyphen or glued_range):
            out += line
        else:
            out = f"{out} {line}" if out else line
    return out


def has_control_chars(text: str) -> bool:
    return any(ord(ch) < 32 and ch != "\n" for ch in text)


def repair_span(text: str, offset: int | None) -> str:
    """Shift one corrupted span by the document's established offset; leave a clean span alone."""
    if offset is None or not has_control_chars(text):
        return text
    out: list[str] = []
    for ch in text:
        if ch in _CORRUPTED_SPAN_QUOTES:
            out.append(_CORRUPTED_SPAN_QUOTES[ch])
        elif ord(ch) < 128:
            out.append(chr(ord(ch) + offset))
        else:
            out.append(ch)
    return "".join(out)


def document_offset(pdf_path: str | Path) -> int | None:
    """The offset the parser's whole-line repair established for this PDF, or None if it is clean."""
    dominant = dominant_offset_for_pages(extract_lines(pdf_path))
    return dominant.offset if dominant else None


def _span_lines(page: pymupdf.Page, clip: pymupdf.Rect | None, offset: int | None) -> list[tuple[float, str]]:
    """(top y, text) of every line in the clip, span-repaired, in page order."""
    data = page.get_text("dict", clip=clip) if clip is not None else page.get_text("dict")
    lines: list[tuple[float, str]] = []
    for block in data["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            text = "".join(repair_span(span["text"], offset) for span in line["spans"])
            if text.strip():
                lines.append((line["bbox"][1], text))
    return lines


def _apply_fixes(text: str, fixes: dict[str, str] | None) -> str:
    for wrong, right in (fixes or {}).items():
        text = text.replace(wrong, right)
    return text


def _cell_items(
    page: pymupdf.Page, bbox: tuple | None, offset: int | None, fixes: dict[str, str] | None = None
) -> list[str]:
    if bbox is None:
        return []
    items = [_apply_fixes(collapse(text), fixes) for _, text in _span_lines(page, pymupdf.Rect(bbox), offset)]
    items = [item for item in items if item]
    if any(has_control_chars(item) for item in items):
        raise TableReadError(f"unrepaired control characters in a cell: {items!r}")
    return items


@dataclass
class TableRow:
    """One table row: the printed lines of its three cells."""

    problem: list[str]
    causes: list[str]
    actions: list[str]

    def cell(self, index: int) -> list[str]:
        return (self.problem, self.causes, self.actions)[index]

    def text(self, index: int) -> str:
        return join_lines(self.cell(index))

    def all_text(self) -> str:
        return " ".join(self.text(i) for i in range(3))


@dataclass
class SymptomTable:
    manual_id: str
    page: int
    table_index: int
    headers: tuple[str, str, str]
    rows: list[TableRow]
    footnotes: list[str] = field(default_factory=list)
    section: str | None = None


def _header_matches(headers: list[str]) -> bool:
    h = [collapse(x).lower() for x in headers[:3]]
    return len(h) == 3 and h[0] in _COLUMN_1 and h[1] in _COLUMN_2 and h[2] in _COLUMN_3


def _page_footnotes(page: pymupdf.Page, below_y: float, offset: int | None) -> list[str]:
    """Lines under the table that start with an asterisk marker, span-repaired and whole."""
    notes = []
    for y, text in _span_lines(page, None, offset):
        text = collapse(text)
        if y >= below_y - 1 and text.startswith("*"):
            notes.append(text)
    return notes


def read_symptom_tables(
    pdf_path: str | Path, manual_id: str, offset: int | None, text_fixes: dict[str, str] | None = None
) -> list[SymptomTable]:
    """Every troubleshooting table in the PDF whose header row is Problem|Sounds / Possible Causes /
    What To Do|Reason, as rows. A table that does not have those three columns (the unruled GE range
    table, which `find_tables()` reads as two merged columns) is not returned.

    `text_fixes` is {wrong: right} for reviewed corrections span-level repair cannot make (a corrupted
    one-character span with no control character); only ever set after checking the rendered page."""
    tables: list[SymptomTable] = []
    doc = pymupdf.open(str(pdf_path))
    try:
        for page in doc:
            if "possible causes" not in page.get_text().lower():
                continue
            found = page.find_tables().tables
            for table_index, table in enumerate(found):
                rows = table.rows
                if not rows:
                    continue
                header_cells = list(rows[0].cells)[:3]
                if len(header_cells) < 3 or any(c is None for c in header_cells):
                    continue
                headers = [" ".join(_cell_items(page, c, offset)) for c in header_cells]
                if not _header_matches(headers):
                    continue
                body: list[TableRow] = []
                for row in rows[1:]:
                    cells = (list(row.cells) + [None, None, None])[:3]
                    body.append(TableRow(*(_cell_items(page, c, offset, text_fixes) for c in cells)))
                page_text = page.get_text()
                tables.append(
                    SymptomTable(
                        manual_id=manual_id,
                        page=page.number + 1,
                        table_index=table_index,
                        headers=(headers[0], headers[1], headers[2]),
                        rows=body,
                        footnotes=_page_footnotes(page, table.bbox[3], offset),
                        section="Troubleshooting Tips" if _SECTION_RE.search(page_text) else None,
                    )
                )
    finally:
        doc.close()
    return tables


def render_for_model(table: SymptomTable) -> str:
    """The table row by row, each cell as its printed lines (a "|" per line)."""
    out: list[str] = []
    names = table.headers
    for number, row in enumerate(table.rows, 1):
        out.append(f"ROW {number}")
        for index, name in enumerate(names):
            lines = row.cell(index)
            if not lines:
                out.append(f"  {name}: (blank)")
            else:
                out.append(f"  {name}:")
                out.extend(f"    | {line}" for line in lines)
    return "\n".join(out)
