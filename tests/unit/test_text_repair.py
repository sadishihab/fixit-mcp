from fixit_mcp.ingestion.text_repair import infer_dominant_offset, repair_line_tokens, repair_run

CLEAN_SENTENCES = [
    "The oven will shut off when the Cook Time has run out.",
    "TROUBLESHOOTING TIPS",
    "Press and hold the START/PAUSE button for three seconds.",
    "system",
    "PERM. PRESS",
]


def corrupt(text: str, offset: int) -> str:
    """Shift every character by -offset, mirroring how the real corruption
    encodes text (repair_run then needs to find +offset to undo it)."""
    return "".join(chr(ord(c) - offset) for c in text)


# --- round-trip repair -------------------------------------------------


def test_repairs_known_ge_fridge_offset() -> None:
    corrupted = ")LOWHU\x03FDUWULGJH\x03QRW\x03SURSHUO\\\x03LQVWDOOHG"

    result = repair_run(corrupted)

    assert result.was_repaired is True
    assert result.offset == 29
    assert result.text == "Filter cartridge not properly installed"
    assert result.confidence > 0.0


def test_repairs_known_lg_dryer_offset() -> None:
    corrupted = "3FNPWF\x01UIF\x01ESZJOH\x01SBDL\x01BOE\x01MJUFSBUVSF"

    result = repair_run(corrupted)

    assert result.was_repaired is True
    assert result.offset == 31
    assert result.text == "Remove the drying rack and literature"


def test_round_trip_repair_recovers_original_for_arbitrary_offset() -> None:
    original = "Turn off the dryer and call for service if the problem repeats."
    corrupted = corrupt(original, offset=17)

    result = repair_run(corrupted)

    assert result.was_repaired is True
    assert result.offset == 17
    assert result.text == original


def test_round_trip_repair_recovers_original_for_negative_offset() -> None:
    original = "Replace filter cartridge or remove filter and install bypass plug."
    corrupted = corrupt(original, offset=-14)

    result = repair_run(corrupted)

    assert result.was_repaired is True
    assert result.offset == -14
    assert result.text == original


# --- clean text is left byte-identical -------------------------------------------------


def test_clean_text_is_returned_byte_identical() -> None:
    for sentence in CLEAN_SENTENCES:
        result = repair_run(sentence)

        assert result.was_repaired is False
        assert result.text == sentence  # byte-identical, not just "close enough"


def test_short_clean_word_is_not_relabeled_by_a_case_toggling_offset() -> None:
    """Regression test: an offset of +/-32 only swaps ASCII letter case, so
    under case-insensitive scoring it can look like a 'winning' candidate
    purely by relabeling already-clean text ('system' -> 'SYSTEM') without
    fixing anything. That must not count as a repair."""
    result = repair_run("system")

    assert result.was_repaired is False
    assert result.text == "system"


# --- ambiguous case: no offset wins clearly -------------------------------------------------


def test_mixed_clean_and_corrupted_text_is_left_untouched() -> None:
    """A run that glues already-clean text directly onto a corrupted tail
    (no separating space) can't be fixed by a single whole-run offset --
    shifting the clean part along with the corrupted part fails the noise
    gate for every candidate offset, so nothing should be "fixed" here."""
    mixed = "AUTO FILL\x03XQGHU\x03ILOO\x12QR\x03ILOO\r"

    result = repair_run(mixed)

    assert result.was_repaired is False
    assert result.text == mixed


def test_short_random_letters_are_not_confidently_repaired() -> None:
    result = repair_run("XZQPLM")

    assert result.was_repaired is False


def test_random_junk_is_not_confidently_repaired() -> None:
    result = repair_run("qzxjkv wprlmn zxcvbn qwzxrq")

    assert result.was_repaired is False


def test_too_short_run_is_never_flagged_suspicious() -> None:
    result = repair_run("ab")

    assert result.was_repaired is False
    assert result.text == "ab"


# --- token-level repair (step 2d) -------------------------------------------------
#
# LG's dryer manual, page 31: "U& or U&" and "14 or 1' or O1" never get
# whole-run repaired by repair_run, because "or" is already clean English and
# shifting the whole line by any offset would corrupt it. But the short
# tokens themselves are corrupted under the document's real +31 offset:
#   "U&"  +31 -> "tE"  (matches its row: "Temperature sensor failure")
#   "1'"  +31 -> "PF"  (real LG power-supply code)
#   "O1"  +31 -> "nP"  (real LG power-supply code)
#   "14"  +31 -> "PS"  (real LG power-supply code)


def test_repair_line_tokens_fixes_ampersand_code() -> None:
    new_text, repairs = repair_line_tokens("U& or U&", dominant_offset=31)

    assert new_text == "tE or tE"
    assert {r.original for r in repairs} == {"U&"}
    assert all(r.repaired == "tE" for r in repairs)


def test_repair_line_tokens_fixes_ampersand_code_with_attached_control_char() -> None:
    """Regression test: the real line in the PDF is "U&\\x12 or U&\\x13" --
    the control-char digit suffix is directly attached with no space, and
    the correct decode ("tE1", "tE2", real LG codes) ends in a digit, not a
    letter. An earlier version only accepted a shift that produced a purely
    alphabetic result and rejected this because "tE1" isn't all-letters."""
    new_text, repairs = repair_line_tokens("U&\x12 or U&\x13", dominant_offset=31)

    assert new_text == "tE1 or tE2"
    assert {(r.original, r.repaired) for r in repairs} == {
        ("U&\x12", "tE1"),
        ("U&\x13", "tE2"),
    }


def test_repair_line_tokens_fixes_the_power_supply_code_line() -> None:
    new_text, repairs = repair_line_tokens("14 or 1' or O1", dominant_offset=31)

    assert new_text == "PS or PF or nP"
    assert {(r.original, r.repaired) for r in repairs} == {
        ("14", "PS"),
        ("1'", "PF"),
        ("O1", "nP"),
    }


def test_repair_line_tokens_leaves_clean_line_with_numbers_untouched() -> None:
    line = "Run water for 5 minutes to remove Air from the System, about 24 hours."

    new_text, repairs = repair_line_tokens(line, dominant_offset=31)

    assert new_text == line
    assert repairs == []


# --- step 2e: restricting weak-signal repair to table-like sections --------
#
# Regression tests for real false positives found in GE's EPA water-quality
# table: a genuinely corrupted chemical name shares a line with ordinary,
# uncorrupted concentration numbers ("86", "24", "3.", "80", "5"). With
# weak-signal repair disabled -- which the parser does for any section that
# doesn't look like error-code/troubleshooting content, see
# parser.apply_token_level_repair -- the strong-signal token (the chemical
# name) is still fixed, but the bare numbers must be left alone rather than
# "repaired" into different, equally plausible-looking wrong numbers.


def test_weak_signal_disabled_leaves_real_false_positive_numbers_untouched() -> None:
    line = "&DUEDPD]HSLQH 86 24 3. 80 5"

    new_text, repairs = repair_line_tokens(line, dominant_offset=29, allow_weak_signal=False)

    assert new_text == "Carbamazepine 86 24 3. 80 5"
    assert {r.original for r in repairs} == {"&DUEDPD]HSLQH"}


def test_weak_signal_enabled_still_repairs_bare_numbers_with_a_sibling() -> None:
    """Sanity check that allow_weak_signal=True (the default, used only
    inside table-like sections) is unaffected by the step 2e change."""
    new_text, repairs = repair_line_tokens("14 or 1' or O1", dominant_offset=31, allow_weak_signal=True)

    assert new_text == "PS or PF or nP"
    assert len(repairs) == 3


def test_repair_line_tokens_does_nothing_without_dominant_offset_context() -> None:
    """repair_line_tokens itself always takes an offset -- this test
    documents the actual no-op boundary: infer_dominant_offset must return
    None first for a caller to correctly skip calling repair_line_tokens at
    all when there isn't enough evidence for one true document offset."""
    assert infer_dominant_offset([]) is None
    assert infer_dominant_offset([31, 31, 31]) is None  # too few repairs
    assert infer_dominant_offset([31] * 5 + [17] * 5) is None  # no clear majority


def test_infer_dominant_offset_detects_a_clear_majority() -> None:
    result = infer_dominant_offset([31] * 20 + [17] * 2)

    assert result is not None
    assert result.offset == 31
    assert result.count == 20
    assert result.total_repaired == 22
    assert result.share > 0.9
