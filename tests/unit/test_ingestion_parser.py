from fixit_mcp.ingestion.parser import (
    Line,
    Section,
    apply_token_level_repair,
    build_sections,
    dominant_offset_for_pages,
    find_boilerplate,
    heading_info,
    is_allcaps_heading,
    looks_like_table,
    split_section_into_chunks,
    strip_boilerplate,
)

BODY_SIZE = 10.0


def make_line(text: str, font_size: float = BODY_SIZE, is_bold: bool = False, page_no: int = 1) -> Line:
    return Line(page_no=page_no, text=text, font_size=font_size, is_bold=is_bold)


def make_repaired_line(text: str, offset: int, page_no: int = 1) -> Line:
    return Line(
        page_no=page_no,
        text=text,
        font_size=BODY_SIZE,
        is_bold=False,
        repair_confidence=0.8,
        repair_offset=offset,
    )


# --- heading detection ---------------------------------------------------


def test_heading_info_detects_numbered_heading_and_its_depth() -> None:
    top_level = make_line("17 Troubleshooting")
    nested = make_line("13.10 Terminating the wash cycle")

    assert heading_info(top_level, BODY_SIZE) == (True, 1)
    assert heading_info(nested, BODY_SIZE) == (True, 2)


def test_heading_info_detects_notably_larger_font() -> None:
    heading = make_line("Before You Call For Service", font_size=19.0)

    result = heading_info(heading, BODY_SIZE)

    assert result is not None
    assert result[0] is True


def test_heading_info_ignores_bold_at_body_size() -> None:
    """A bold line at ordinary body-text size must NOT be treated as a heading --
    real manuals bold entire troubleshooting-table columns at body size, and
    doing so would shred the table into one false heading per row."""
    bold_body_line = make_line("Oven controls not properly set", font_size=BODY_SIZE, is_bold=True)

    assert heading_info(bold_body_line, BODY_SIZE) is None


def test_heading_info_accepts_bold_with_moderate_size_bump() -> None:
    bold_and_bigger = make_line("Safety Information", font_size=12.5, is_bold=True)

    result = heading_info(bold_and_bigger, BODY_SIZE)

    assert result is not None


def test_heading_info_rejects_a_normal_sentence() -> None:
    sentence = make_line("The oven will shut off when the Cook Time has run out.")

    assert heading_info(sentence, BODY_SIZE) is None


def test_is_allcaps_heading_accepts_short_uppercase_title() -> None:
    assert is_allcaps_heading("TROUBLESHOOTING TIPS") is True


def test_is_allcaps_heading_rejects_line_not_starting_with_a_letter() -> None:
    """Regression test: some source PDFs have a corrupted font encoding whose
    garbled output happens to be mostly uppercase letters, but starts with a
    stray digit/punctuation glyph standing in for the real first letter
    (e.g. ")LOWHU FDUWULGJH" for "Filter cartridge"). These must not be
    misdetected as section headings."""
    assert is_allcaps_heading(")LOWHU FDUWULGJH QRW SURSHUOB LQVWDOOHG") is False
    assert is_allcaps_heading("6RPH PRGHOV GR QRW") is False


def test_is_allcaps_heading_rejects_long_or_lowercase_text() -> None:
    assert is_allcaps_heading("This is a normal sentence, not a heading.") is False
    assert is_allcaps_heading("A" * 100) is False


# --- boilerplate stripping -------------------------------------------------


def test_find_boilerplate_detects_line_repeated_across_many_pages() -> None:
    pages = [
        [make_line("Customer Service", page_no=i), make_line(f"Real content on page {i}", page_no=i)]
        for i in range(1, 9)
    ]

    boilerplate = find_boilerplate(pages)

    assert "customer service" in boilerplate
    assert not any(f"real content on page {i}" in boilerplate for i in range(1, 9))


def test_find_boilerplate_ignores_lines_seen_on_few_pages() -> None:
    pages = [[make_line("Only on page one", page_no=1)]] + [
        [make_line(f"Unique to page {i}", page_no=i)] for i in range(2, 9)
    ]

    boilerplate = find_boilerplate(pages)

    assert "only on page one" not in boilerplate


def test_strip_boilerplate_removes_repeated_lines_and_bare_page_numbers() -> None:
    pages = [
        [make_line("47", page_no=47), make_line("Real content", page_no=47)],
    ]
    boilerplate = {"running header"}
    pages_with_header = [[make_line("Running Header", page_no=47), *pages[0]]]

    cleaned = strip_boilerplate(pages_with_header, boilerplate)

    texts = [line.text for line in cleaned[0]]
    assert "Running Header" not in texts
    assert "47" not in texts
    assert "Real content" in texts


# --- section building -------------------------------------------------


def test_build_sections_creates_nested_section_path() -> None:
    lines = [
        make_line("17 Troubleshooting"),
        make_line("General notes before troubleshooting."),
        make_line("17.1 Error codes"),
        make_line("Error code content here."),
    ]

    sections = build_sections([lines])

    assert [s.heading for s in sections] == ["17 Troubleshooting", "17.1 Error codes"]
    assert sections[0].section_path == ["17 Troubleshooting"]
    assert sections[1].section_path == ["17 Troubleshooting", "17.1 Error codes"]


def test_build_sections_pops_stack_back_to_sibling_depth() -> None:
    lines = [
        make_line("1 Chapter One"),
        make_line("1.1 Sub one"),
        make_line("body a"),
        make_line("2 Chapter Two"),
        make_line("body b"),
    ]

    sections = build_sections([lines])

    assert sections[-1].heading == "2 Chapter Two"
    assert sections[-1].section_path == ["2 Chapter Two"]


def test_build_sections_keeps_front_matter_before_first_heading() -> None:
    lines = [make_line("Some front matter with no heading yet."), make_line("1 First Real Heading")]

    sections = build_sections([lines])

    assert sections[0].heading is None
    assert sections[1].heading == "1 First Real Heading"


# --- chunk splitting -------------------------------------------------


def test_split_section_into_chunks_respects_max_size() -> None:
    long_lines = [make_line(f"line number {i} with some filler text to add length") for i in range(200)]
    section = Section(heading="Big Section", section_path=["Big Section"], lines=long_lines)

    chunks = split_section_into_chunks(section, "manual-x", [0])

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text) <= 1800 + 100  # a little slack for the boundary line


def test_split_section_into_chunks_overlaps_consecutive_chunks() -> None:
    long_lines = [make_line(f"unique line {i:04d} padding padding padding") for i in range(150)]
    section = Section(heading="Big Section", section_path=["Big Section"], lines=long_lines)

    chunks = split_section_into_chunks(section, "manual-x", [0])

    assert len(chunks) >= 2
    first_lines = set(chunks[0].text.splitlines())
    second_lines = set(chunks[1].text.splitlines())
    assert first_lines & second_lines  # some lines repeated across the boundary


def test_split_section_into_chunks_never_merges_two_sections() -> None:
    section_a = Section(heading="A", section_path=["A"], lines=[make_line("short a")])
    section_b = Section(heading="B", section_path=["B"], lines=[make_line("short b")])

    counter = [0]
    chunks_a = split_section_into_chunks(section_a, "manual-x", counter)
    chunks_b = split_section_into_chunks(section_b, "manual-x", counter)

    assert len(chunks_a) == 1
    assert len(chunks_b) == 1
    assert chunks_a[0].text == "short a"
    assert chunks_b[0].text == "short b"
    assert chunks_a[0].section_heading == "A"
    assert chunks_b[0].section_heading == "B"


def test_split_section_assigns_page_start_and_end_from_its_lines() -> None:
    lines = [make_line("first", page_no=5), make_line("second", page_no=6), make_line("third", page_no=7)]
    section = Section(heading="S", section_path=["S"], lines=lines)

    chunks = split_section_into_chunks(section, "manual-x", [0])

    assert chunks[0].page_start == 5
    assert chunks[0].page_end == 7


def test_split_section_on_empty_lines_returns_no_chunks() -> None:
    section = Section(heading="Empty", section_path=["Empty"], lines=[])

    assert split_section_into_chunks(section, "manual-x", [0]) == []


# --- table detection -------------------------------------------------


def test_looks_like_table_detects_problem_and_solution_pairing() -> None:
    text = "Problem\nPossible Causes\nWhat To Do\nCLEAN light flashes\nOven controls not set."

    assert looks_like_table(text) is True


def test_looks_like_table_detects_bosch_style_wording() -> None:
    text = "Issue\nCause and troubleshooting\nE:20-60 lights up alternately."

    assert looks_like_table(text) is True


def test_looks_like_table_rejects_ordinary_prose() -> None:
    text = "This appliance must be grounded for safe operation in all households."

    assert looks_like_table(text) is False


# --- document-level dominant offset + token-level repair wiring (step 2d) ---


def test_dominant_offset_for_pages_none_without_enough_repaired_lines() -> None:
    pages = [[make_line("Some ordinary line."), make_line("Another ordinary line.")]]

    assert dominant_offset_for_pages(pages) is None


def test_apply_token_level_repair_is_a_noop_without_a_dominant_offset() -> None:
    """No lines in these pages were ever whole-run repaired (repair_offset is
    None everywhere), so there's no document-wide offset to trust -- the
    token pass must not guess one from a single suspicious-looking line."""
    target = make_line("14 or 1' or O1")
    pages = [[target]]

    repairs = apply_token_level_repair(pages)

    assert repairs == []
    assert target.text == "14 or 1' or O1"
    assert target.token_repairs == []


def test_apply_token_level_repair_fixes_tokens_once_offset_is_established() -> None:
    established = [make_repaired_line(f"Genuinely repaired line number {i}.", offset=31) for i in range(6)]
    target = make_line("14 or 1' or O1")
    pages = [[*established, target]]

    repairs = apply_token_level_repair(pages)

    assert target.text == "PS or PF or nP"
    assert len(repairs) == 3
    assert target.token_repairs == repairs
