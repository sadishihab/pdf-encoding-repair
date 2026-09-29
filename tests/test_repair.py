import pytest

from pdf_encoding_repair import infer_dominant_offset, repair_line_tokens, repair_run
from pdf_encoding_repair.repair import (
    _MIN_LETTER_FREQ_SCORE,
    _letter_freq_score,
    _noise_ratio,
    _passes_gates,
    is_suspicious_run,
)

from .helpers import CLEAN_SENTENCES, corrupt

# --- round-trip repair -------------------------------------------------


def test_repairs_readme_example_offset() -> None:
    original = "Filter cartridge not properly installed"
    corrupted = corrupt(original, 29)
    assert corrupted.startswith(")LOWHU\x03FDUWULGJH")

    result = repair_run(corrupted)

    assert result.was_repaired is True
    assert result.offset == 29
    assert result.text == original
    assert result.confidence > 0.0


def test_repairs_a_different_offset_without_hardcoding() -> None:
    original = "Remove the drying rack and literature"
    result = repair_run(corrupt(original, 31))

    assert result.was_repaired is True
    assert result.offset == 31
    assert result.text == original


def test_round_trip_repair_recovers_original_for_arbitrary_offset() -> None:
    original = "Turn off the dryer and call for service if the problem repeats."
    result = repair_run(corrupt(original, offset=17))

    assert result.was_repaired is True
    assert result.offset == 17
    assert result.text == original


def test_round_trip_repair_recovers_original_for_negative_offset() -> None:
    original = "Replace filter cartridge or remove filter and install bypass plug."
    result = repair_run(corrupt(original, offset=-14))

    assert result.was_repaired is True
    assert result.offset == -14
    assert result.text == original


def test_run_without_a_space_glyph_is_repaired_by_sweep() -> None:
    """No control character to hint the offset: the brute-force sweep and
    the substring word match must carry it. Scoring is case-insensitive, so
    the sweep cannot tell offset N from N-32: the letters are recovered but
    their case may not be (documented limit)."""
    original = "pressstartbutton"
    result = repair_run(corrupt(original, 7))

    assert result.was_repaired is True
    assert result.text.lower() == original
    assert (result.offset - 7) % 32 == 0


# --- clean text is left byte-identical -------------------------------------------------


@pytest.mark.parametrize("sentence", CLEAN_SENTENCES)
def test_clean_text_is_returned_byte_identical(sentence: str) -> None:
    result = repair_run(sentence)

    assert result.was_repaired is False
    assert result.text == sentence


def test_short_clean_word_is_not_relabeled_by_a_case_toggling_offset() -> None:
    """Case-flip guard. An offset of +/-32 only swaps ASCII letter case, so
    under case-insensitive scoring it can look like a 'winning' candidate
    purely by relabeling already-clean text ('system' -> 'SYSTEM') without
    fixing anything. A candidate must strictly beat the unshifted baseline."""
    result = repair_run("system")

    assert result.was_repaired is False
    assert result.text == "system"


def test_case_flip_is_not_a_repair_even_in_a_longer_suspicious_line() -> None:
    # Lowercase-only text with no vowels-ratio problem: an offset of -32
    # would only uppercase it. It must never be reported as a repair.
    text = "check the system status before service"
    result = repair_run(text)

    assert result.was_repaired is False
    assert result.text == text


# --- the three gates, individually -------------------------------------------------


def test_noise_gate_rejects_symbol_heavy_text() -> None:
    assert _noise_ratio("Turn off the power") == 0.0
    noisy = "Turn off the power\x03\x03\x03\x03\x03\x03"
    assert _noise_ratio(noisy) > 0.10
    assert _passes_gates(noisy) is False


def test_letter_frequency_gate_rejects_implausible_letters() -> None:
    # Contains the exact word "that" (enough for the word gate, too short to
    # trigger the exact-match bypass) but is dominated by rare letters.
    text = "that zqxjkvzqxjkvzqxjkvzqxjkv"
    assert _letter_freq_score(text) < _MIN_LETTER_FREQ_SCORE
    assert _passes_gates(text) is False


def test_common_word_gate_rejects_plausible_letters_without_words() -> None:
    # Letter frequencies are English-like, but there are no recognizable words.
    text = "eetta oinsr hdlee tanoi"
    assert _noise_ratio(text) == 0.0
    assert _letter_freq_score(text) >= _MIN_LETTER_FREQ_SCORE
    assert _passes_gates(text) is False


def test_a_short_correct_run_can_bypass_the_letter_frequency_gate() -> None:
    assert _letter_freq_score("Problem") < _MIN_LETTER_FREQ_SCORE
    assert _passes_gates("Problem") is True


# --- ambiguous / hopeless input -------------------------------------------------


def test_mixed_clean_and_corrupted_text_is_left_untouched() -> None:
    """A clean prefix glued directly onto a corrupted tail (no separating
    space) can't be fixed by one whole-run offset: shifting the clean part
    along with the corrupted part fails the noise gate for every candidate,
    so nothing should be "fixed" here."""
    mixed = "COLD START" + corrupt(" under high load", 29)
    assert is_suspicious_run(mixed)

    result = repair_run(mixed)

    assert result.was_repaired is False
    assert result.text == mixed


def test_short_random_letters_are_not_confidently_repaired() -> None:
    assert repair_run("XZQPLM").was_repaired is False


def test_random_junk_is_not_confidently_repaired() -> None:
    assert repair_run("qzxjkv wprlmn zxcvbn qwzxrq").was_repaired is False


def test_too_short_run_is_never_flagged_suspicious() -> None:
    result = repair_run("ab")

    assert result.was_repaired is False
    assert result.text == "ab"


# --- token-level repair -------------------------------------------------
#
# Short codes are built by corrupting known text at a known offset, e.g.
# corrupt("tE", 31) == "U&" and corrupt("PS", 31) == "14".


def test_synthetic_token_fixtures_are_what_the_tests_claim() -> None:
    assert corrupt("tE", 31) == "U&"
    assert corrupt("PF", 31) == "1'"
    assert corrupt("nP", 31) == "O1"
    assert corrupt("PS", 31) == "14"


def test_repair_line_tokens_fixes_ampersand_code() -> None:
    line = f"{corrupt('tE', 31)} or {corrupt('tE', 31)}"

    new_text, repairs = repair_line_tokens(line, dominant_offset=31)

    assert new_text == "tE or tE"
    assert {r.original for r in repairs} == {"U&"}
    assert all(r.repaired == "tE" for r in repairs)


def test_repair_line_tokens_fixes_code_with_attached_control_char() -> None:
    """The corrupted digit suffix is a control character attached with no
    space, and the correct decode ("tE1") ends in a digit, not a letter --
    so the accepted result must be alphanumeric, not purely alphabetic."""
    a, b = corrupt("tE1", 31), corrupt("tE2", 31)
    assert a == "U&\x12"

    new_text, repairs = repair_line_tokens(f"{a} or {b}", dominant_offset=31)

    assert new_text == "tE1 or tE2"
    assert {(r.original, r.repaired) for r in repairs} == {(a, "tE1"), (b, "tE2")}


def test_repair_line_tokens_fixes_a_line_of_short_codes() -> None:
    line = " or ".join(corrupt(code, 31) for code in ("PS", "PF", "nP"))
    assert line == "14 or 1' or O1"

    new_text, repairs = repair_line_tokens(line, dominant_offset=31)

    assert new_text == "PS or PF or nP"
    assert {(r.original, r.repaired) for r in repairs} == {("14", "PS"), ("1'", "PF"), ("O1", "nP")}


def test_repair_line_tokens_leaves_clean_line_with_numbers_untouched() -> None:
    line = "Run water for 5 minutes to remove air from the system, about 24 hours."

    new_text, repairs = repair_line_tokens(line, dominant_offset=31)

    assert new_text == line
    assert repairs == []


def test_parenthesis_adjacency_is_not_a_corruption_signal() -> None:
    """False-positive lesson: '(' and ')' sit next to digits and letters in
    ordinary text (unit conversions, list markers, abbreviations). They must
    never count as strong evidence, or ordinary numbers get 'repaired'."""
    for line in ("Length: 14 in. (35.6 cm) or 2 ft", "Options (1) or (2) or (SD) 24", "see step 3) then 5"):
        new_text, repairs = repair_line_tokens(line, dominant_offset=31)
        assert new_text == line
        assert repairs == []


def test_contractions_are_not_a_corruption_signal() -> None:
    line = "Don't open it, it's hot and you'll 14 see"
    new_text, repairs = repair_line_tokens(line, dominant_offset=31)

    assert new_text == line
    assert repairs == []


def test_weak_signal_disabled_leaves_bare_numbers_untouched() -> None:
    """A corrupted name shares a row with ordinary measurements. With weak
    signal off, the strong-signal token is fixed but the numbers stay."""
    name = corrupt("Calcium", 29)
    assert name == "&DOFLXP"

    new_text, repairs = repair_line_tokens(
        f"{name} 86 24 3. 80 5", dominant_offset=29, allow_weak_signal=False
    )

    assert new_text == "Calcium 86 24 3. 80 5"
    assert {r.original for r in repairs} == {name}


def test_weak_signal_enabled_repairs_bare_numbers_with_a_strong_sibling() -> None:
    new_text, repairs = repair_line_tokens("14 or 1' or O1", dominant_offset=31, allow_weak_signal=True)

    assert new_text == "PS or PF or nP"
    assert len(repairs) == 3


def test_weak_signal_alone_never_triggers_a_repair() -> None:
    line = "14 or 24 or 5"
    new_text, repairs = repair_line_tokens(line, dominant_offset=31)

    assert new_text == line
    assert repairs == []


# --- dominant offset -------------------------------------------------


def test_no_dominant_offset_without_enough_evidence() -> None:
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
