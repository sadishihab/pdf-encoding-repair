from pdf_encoding_repair import repair_document, repair_text

from .helpers import PLAIN_LINES, corrupt

OFFSET = 29


def _corrupted_lines(n: int, offset: int = OFFSET) -> list[str]:
    return [corrupt(PLAIN_LINES[i % len(PLAIN_LINES)], offset) for i in range(n)]


def test_document_repairs_lines_and_reports_offsets() -> None:
    lines = _corrupted_lines(6) + ["A perfectly clean line of text."]

    repaired, report = repair_document(lines)

    assert repaired[:6] == [PLAIN_LINES[i % len(PLAIN_LINES)] for i in range(6)]
    assert repaired[6] == "A perfectly clean line of text."
    assert report.total_lines == 7
    assert report.offsets == {OFFSET: 6}
    assert report.dominant is not None and report.dominant.offset == OFFSET
    assert report.lines_repaired == 6
    assert report.run_repairs == 6
    assert report.token_repairs == 0


def test_token_pass_runs_once_document_offset_is_established() -> None:
    code_line = " or ".join(corrupt(c, OFFSET) for c in ("tE", "PS"))
    mixed = _corrupted_lines(5) + [f"{code_line}"]
    # A strong-signal token that whole-line repair cannot fix on its own.
    line = f"{corrupt('tE1', OFFSET)} or clean"
    mixed.append(line)

    repaired, report = repair_document(mixed)

    assert report.dominant is not None
    assert repaired[-1] == "tE1 or clean"
    assert report.token_repairs >= 1
    assert any(r.kind == "token" and r.line_number == len(mixed) - 1 for r in report.repairs)


def test_token_pass_is_skipped_without_an_established_offset() -> None:
    """Sub-line repair only runs against an already-established document
    offset: with too few whole-line repairs, the same line is left alone."""
    line = f"{corrupt('tE1', OFFSET)} or clean"
    lines = _corrupted_lines(3) + [line]

    repaired, report = repair_document(lines)

    assert report.dominant is None
    assert repaired[-1] == line
    assert report.token_repairs == 0


def test_token_pass_is_skipped_when_offsets_are_split() -> None:
    line = f"{corrupt('tE1', OFFSET)} or clean"
    lines = _corrupted_lines(5, OFFSET) + _corrupted_lines(5, 17) + [line]

    repaired, report = repair_document(lines)

    assert report.dominant is None
    assert report.offsets == {OFFSET: 5, 17: 5}
    assert repaired[-1] == line


def test_allow_weak_signal_false_is_respected() -> None:
    line = f"{corrupt('Calcium', OFFSET)} 86 24 3. 80 5"
    lines = _corrupted_lines(5) + [line]

    repaired, _ = repair_document(lines, allow_weak_signal=False)

    assert repaired[-1] == "Calcium 86 24 3. 80 5"


def test_low_confidence_repairs_are_reported() -> None:
    line = f"{corrupt('tE1', OFFSET)} or clean"
    lines = _corrupted_lines(5) + [line]

    _, report = repair_document(lines, low_confidence_threshold=0.7)

    assert [r.line_number for r in report.low_confidence] == [5]
    assert report.low_confidence[0].confidence < 0.7


def test_clean_document_is_untouched() -> None:
    lines = ["Nothing is wrong here.", "Press the button, then wait 5 minutes (about 300 s)."]

    repaired, report = repair_document(lines)

    assert repaired == lines
    assert report.lines_repaired == 0
    assert report.offsets == {}
    assert report.dominant is None


def test_repair_text_preserves_line_endings() -> None:
    body = _corrupted_lines(2)
    text = "\r\n".join(body) + "\r\n"

    out = repair_text(text)

    assert out == "\r\n".join(PLAIN_LINES[:2]) + "\r\n"

    assert repair_text("\n".join(body)) == "\n".join(PLAIN_LINES[:2])
