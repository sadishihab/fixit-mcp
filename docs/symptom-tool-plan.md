# Symptom tool: plan and Nova extraction test (step 25a)

Status: **built in step 25b** for the GE refrigerator and washer (not deployed);
sections 1-5 below are the step 25a plan and test, kept as written. What 25b
changed or added relative to the plan:

- `SymptomRecord` also has `symptom_label` (the manual's own first-column header, so
  the Sounds table's rows match on "sound") and `text_incomplete` (the mid-sentence flag).
- The tool also takes an optional `appliance_id`, like `diagnose_error`, and uses the
  appliance type the customer's own words name when no `appliance_type` is passed.
- Thresholds: score >= 0.5 and two matched words, with one query word the manuals do not
  contain at all not counted against the customer (found by dry-checking the eval phrases).
- The audit compares strings case- and quote-sensitively; the reader joins lines broken
  after a real hyphen or en dash. No manifest field was added: the default manuals are a
  constant in `scripts/extract_symptoms.py`.
- Real extraction: 114 rows (42 + 72), every table accepted, about $0.10 in total.

Original 25a status: plan only; the experiment ran in a scratch directory.
Spend then: $0.043 of a $1.00 cap, Nova models only.

## 1. What the three manuals contain

All three have a "Troubleshooting Tips" table with the columns
**Problem / Possible Causes / What To Do**. Counts below come from the table
geometry (PyMuPDF `find_tables()`), except the range, which is a hand count.

| Manual | Pages | Table rows | Distinct symptoms |
|---|---|---|---|
| GE GFE28GYNFS refrigerator | 46-48 | 42 | 30 |
| GE GTW680BSJWS washer | 26-28 | 61 (troubleshooting) + 11 ("Sounds", p.28) | 27 + 10 |
| GE JBP26 range | 22-24 | not machine-countable | ~19 (hand count, one repeated symptom) |

Example rows (the manuals' own short labels):

- Fridge p.46: "Reset Filter is lit"; "Refrigerator beeping" (cause: "This is door alarm");
  "Water in glass is warm*" (three causes, three actions).
- Fridge p.47: "AUTO FILL under fill/no fill*" (cause "Error message" -> "See page 14");
  "Low brewing flow rate".
- Washer p.26: "Too many suds" (three causes); "Water won't drain"; "Low water flow".
- Washer p.28 "Sounds" table: its third column is headed **Reason**, not What To Do.
- Range p.22-24: "Oven will not work"; "Food does not broil properly"; "CLEAN light flashes".

Layout facts that shape the record:

- A symptom often has several cause/action rows; later rows leave the Problem cell blank.
- One cell can hold several separate items (fridge p.46 row 2: three problem
  phrasings, three causes, three actions in one merged row).
- Footnote markers (`*`, `**`) qualify rows ("Select Models Only").
- The range table is unruled: `find_tables()` returns a two-column result with
  causes and actions merged. It needs word-position column bucketing.

## 2. Record shape

A new neutral-layer model, `SymptomRecord` (in `fixit_mcp.domain.models`, next
to `ErrorCodeRecord`), **one record per table row**:

```
manual_id, brand, model, appliance_type      # as ErrorCodeRecord
symptom: list[str]                           # Problem cell phrases, verbatim
symptom_continued: bool                      # Problem cell was blank; `symptom` carried from the row above (set in code)
possible_causes: list[str]                   # verbatim
what_to_do: list[str]                        # verbatim, in order
response_label: str                          # the manual's own column header: "What To Do" or "Reason"
footnotes: list[str]                         # verbatim footnote text for markers in this row
source_page: int
source_section: str | None
```

Deliberately absent: `meaning`, `parts_needed`, `difficulty`, `safety_warnings`,
`extraction_confidence`. Each would be inference, or a model's self-report. Safety
wording stays inside the verbatim `what_to_do` strings. Grounding is checked
mechanically instead (section 4).

Relation to `ErrorCodeRecord`: different key (free text vs a normalized code)
and a different shape (causes pair with actions row by row), so a **separate
model, `data/index/symptoms.json` (committed), and a separate loader**
(`fixit_mcp.retrieval.symptoms`, loaded once in `create_server()`, no I/O in the
request path). Shared: the citation fields and the household -> appliance ->
`manual_id` resolution, which should be extracted from `tools/diagnose.py`
rather than copied. Ingestion gets a `SymptomExtractor` beside the existing
one, a manifest field `symptom_pages` (like `extraction_pages`), and
`make extract-symptoms`.

## 3. The tool: `diagnose_symptom`

Inputs: `household_id`, `symptom` (the customer's own words), optional
`appliance_type` (normalized with `normalize_appliance_type`).

Outputs: `status: Literal["found","not_found","ambiguous_appliance"]` (single
model, as the other tools), plus up to 3 `matches`, each with `appliance`
(brand/model/type), `symptom` (verbatim phrases), `possible_causes`,
`what_to_do`, `response_label`, `footnotes`, and a `citation` (manual id +
page). `ambiguous_appliance` when the household owns more than one matching
appliance and nothing narrows it (same rule as `diagnose_error`).
`not_found` carries the nearest manual symptom phrases verbatim and a fixed
message; if the household has no matching appliance it sets
`suggest_add_appliance`.

Matching (no model call, all in memory):

1. Restrict to the household's appliances' manuals (and `appliance_type`).
2. Tokenize lower-case, drop a small fixed stopword list, light suffix
   stemming (-ing/-ed/-es/-s); a small hand-curated synonym table (leak/drip,
   noisy/noise/sound/loud) added only when a test query needs it.
3. Score each row: IDF-weighted share of the customer's content terms found in
   the row's `symptom` text (weight 1.0), plus the cause text (lower weight).
   Group rows with the same symptom; rank symptoms.
4. Return `found` only above a score threshold **and** at least two matched
   content terms (one if the query has only one, and its IDF is high); otherwise
   `not_found`. Thresholds are tuned on a small labelled set of paraphrases
   plus off-topic queries ("my TV is blurry") that must come back `not_found`;
   they are measured, not guessed.

How it avoids saying anything the manual doesn't:

- Every string in a match is a stored, verbatim manual string; the only
  server-written text is a fixed template ("The manual lists these possible
  causes for a similar symptom").
- Rows are never merged or summarized; a cause is only ever shown with the
  action(s) from its own row.
- `footnotes` travel with the match and the description tells Alexa to relay
  them ("select models only").
- `response_label == "Reason"` marks text that explains a normal behaviour
  (the washer's Sounds table), not an instruction.
- `not_found` never guesses a cause. Like `check_warranty`, no cost or
  coverage claims, and the demo prompt carries the same restriction.

Fit with the Alexa+ guidance (CLAUDE.md: descriptions are written for the LLM
client): say when to call it (the customer describes a problem **without** an
error code; if they read a code off the display, call `diagnose_error`), what
it needs (`household_id`, the customer's own short words, `appliance_type` if
they said "my washer"), and what comes back. `diagnose_error`'s description
gets a matching sentence pointing at the symptom tool, so routing is
unambiguous. Latency: a few hundred in-memory rows; far below the 500 ms budget.
The repo's `docs/alexa-plus-requirements.md` has no description-size or
tool-count guidance, so none is assumed.

## 4. Nova extraction test

Setup (scratch only): PyMuPDF `find_tables()` for row geometry; cell text from
span-level extraction clipped to each cell; the fridge's font corruption
repaired per span with the manual's already-established +29 offset; the page
rendered row by row, each cell as its printed lines; a verbatim-copy symptom
prompt; JSON out. One page of each manual: fridge p.46 (hardest: corrupted
font, multi-item merged rows, footnotes) and washer p.26.

Audit: for every row, the extracted strings **joined must equal the source
cell** after whitespace normalization. That catches an invented word and a
dropped line. Plus row count, footnote linking, and a read of the output.

| Run | Fridge p.46 (17 rows) | Washer p.26 (22 rows) |
|---|---|---|
| Nova Pro, prompt v1 | content faithful; 11 audit flags, all mechanical (see below) | 0 issues |
| Nova Pro, prompt v2 | **0 issues** | **0 issues** |
| Nova 2 Lite, v1 | 0 issues | first run returned `[]` (silent); identical retry: 0 issues |
| Nova Pro, plain parser text, v1 | unusable (see below) | not run |

Nothing was invented in any run. Defects found:

- Pro v1 dropped the `*`/`**` markers from the text (the footnotes were still
  linked to the right rows) and mis-set the "continues previous row" flag on 5
  rows; it also merged three separate problem phrasings into one string. v2
  fixed all three by instruction and by moving the flag into code.
- Nova 2 Lite returned a bare `[]` for a page with 22 rows, once. An extractor
  that treats `[]` as "no symptoms here" would silently lose a page. The table
  geometry knows the expected row count, so a mismatch must trigger a retry.
- Plain parser text (the existing machinery's output) fails: the parser reads
  the fridge's three columns in two-column order, so all causes and all actions
  come out as separate runs, and the model copied the garbled glyphs and
  control characters into its JSON, which then would not parse.
- A verbatim row can be an incomplete sentence: washer p.26 "Switch to High
  Efficiency detergent such as" (a brand logo in the PDF is an image). The
  audit passes it; a review step should flag rows ending mid-sentence.

## 5. Recommendation

Nova Pro is good enough **given structured input and a mechanical audit**:
0 issues on both pages with prompt v2, at about $0.006-0.007 per page.
Nova 2 Lite matched it on the fridge and on a retry of the washer, at about
$0.004-0.006 per page, but its one silent empty answer means it needs the
row-count check and a retry; it is a candidate, not yet a default.

Full extraction estimate (measured tokens x list prices I assumed, $0.80/$3.20
per M for Pro; not checked against a bill): fridge 3 pages + washer 4 table
blocks on 3 pages + range 3 pages, about $0.07-0.10 in one pass (the 27-row washer page costs about twice a
fridge page), under $0.25 with retries and margin. Cost is not the constraint; the input pipeline is.

What the full build needs first:

1. A table-row reader (geometry-based) feeding the extractor: `find_tables()`
   for the fridge and washer, a word-position column reader for the range.
2. Span-level font repair (the `Line` objects merge spans, so the existing
   repair can't do this).
3. The row-count / verbatim-join audit as a gate in the pipeline, plus
   human review of the flagged rows.
4. Mid-sentence-row flagging.
