from fixit_mcp.ingestion.text_repair import repair_run

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
