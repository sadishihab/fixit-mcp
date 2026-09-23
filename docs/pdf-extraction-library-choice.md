# PDF extraction library choice

Tried three libraries against our actual manuals (`data/manuals/pdf/`) before
writing `src/fixit_mcp/ingestion/parser.py`, specifically checking the
168-page multi-column `ge-gfe28gynfs-refrigerator.pdf` and the pages
containing each manual's fault/error-code table (found by keyword search,
not assumed from a table of contents).

## What was tried

- **`pypdf`** (already a dependency, used by `scripts/fetch_manuals.py`).
- **`pdfplumber`** (built on `pdfminer.six`; exposes character-level font
  metadata and a geometric table-extraction feature).
- **PyMuPDF** (`pymupdf`, imported as `fitz`/`pymupdf`; a compiled MuPDF binding).

## Findings

1. **Plain-text quality is identical across all three where the source PDF's
   own font encoding is intact**, because all three ultimately decode text
   via the PDF's embedded ToUnicode CMap. Where that CMap is broken — two of
   our five manuals (`lg-dlex8000w-dryer.pdf`, `ge-gfe28gynfs-refrigerator.pdf`)
   have text runs that decode as garbled strings, e.g. `)LOWHU FDUWULGJH` for
   "Filter cartridge" — **all three libraries produce the same garbled output**.
   This is a source-document defect, not something a different extraction
   library fixes. See `FRICTION_LOG.md`.

2. **`pdfplumber`'s `extract_tables()` is unreliable on these manuals.** On
   the LG dryer's actual Error Code table page it worked reasonably (correctly
   split `Error Code` / `Possible Causes` / `Solutions` into columns). On the
   GE range's troubleshooting table page it produced garbage: a rotated
   sidebar of chapter names got picked up as a phantom "table" with reversed
   character order (`snoitcurtsnI\nytefaS` for "Safety Instructions"), and the
   real `Problem`/`Possible Causes`/`What To Do` table lost two of its three
   columns entirely. One tool, two very different real outcomes on our actual
   corpus — not something to build a parser around.

3. **Only PyMuPDF exposes the layout signals this task needs.** `pypdf`'s
   `extract_text()` returns a single text stream with no font size, weight, or
   position data at all -- there is no way to do the "layout signals
   (font size/weight...)" heading detection the task asks for using it alone.
   `pdfplumber` does expose character-level `size`/`fontname`, but PyMuPDF's
   `get_text("dict")` gives the same per-span `size`, bold flags (via the
   `flags` bitmask), and bounding boxes more directly and much faster.

4. **Speed matters here**: `ge-gfe28gynfs-refrigerator.pdf` is 168 pages.
   PyMuPDF (compiled C/MuPDF) parses it in a fraction of a second; `pdfplumber`
   (pure-Python `pdfminer.six`) is noticeably slower, especially once
   `extract_tables()` is called per page.

## Decision

**PyMuPDF (`pymupdf`)** is used for all extraction. Its plain-text quality
matches `pypdf` exactly (same CMap-driven decoding, same garbling where the
source PDF is broken), but it's the only one of the three that gives
`src/fixit_mcp/ingestion/parser.py` the per-line font size/weight and
bounding-box data needed for heading detection and column-aware reading
order, and it's dramatically faster on the corpus's largest file.

Neither library's built-in table extraction is used. Given finding 2 above,
`looks_like_table()` in the parser is a lightweight keyword-pairing heuristic
over the plain reading-order text instead (see that function's docstring) --
less structured than a real table extractor when one works, but consistently
usable across all five manuals' actual table styles, which a single
geometric table detector was not.
