"""Whole-document repair: run-level pass, dominant offset, token-level pass."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .repair import DominantOffset, infer_dominant_offset, repair_line_tokens, repair_run

DEFAULT_LOW_CONFIDENCE_THRESHOLD = 0.7


@dataclass
class LineRepair:
    """One repaired line: which line, how, and how sure."""

    line_number: int  # 0-based index into the input lines
    original: str
    repaired: str
    kind: str  # "run" or "token"
    confidence: float
    offset: int | None = None


@dataclass
class DocumentReport:
    """What repair_document did.

    `offsets` maps each offset found by whole-line repair to how many lines
    used it. `dominant` is set only when one offset clearly dominates, which
    is the precondition for the token-level pass. `low_confidence` lists
    repairs whose confidence fell below the threshold -- review these first.
    """

    total_lines: int = 0
    offsets: dict[int, int] = field(default_factory=dict)
    dominant: DominantOffset | None = None
    lines_repaired: int = 0
    run_repairs: int = 0
    token_repairs: int = 0
    repairs: list[LineRepair] = field(default_factory=list)
    low_confidence: list[LineRepair] = field(default_factory=list)


def repair_document(
    lines: list[str],
    *,
    allow_weak_signal: bool = True,
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
) -> tuple[list[str], DocumentReport]:
    """Repair a whole document given its lines (without line terminators).

    Pass 1 runs `repair_run` on every line. Pass 2 runs only if the offsets
    from pass 1 have a clear dominant offset (`infer_dominant_offset`): lines
    pass 1 left alone are then re-scanned token by token against that one
    offset. Without an established document offset, no token-level repair
    is attempted.
    """
    report = DocumentReport(total_lines=len(lines))
    out = list(lines)
    repaired_idx: set[int] = set()

    found_offsets: list[int] = []
    for i, line in enumerate(lines):
        result = repair_run(line)
        if result.was_repaired and result.offset is not None:
            out[i] = result.text
            repaired_idx.add(i)
            found_offsets.append(result.offset)
            report.repairs.append(
                LineRepair(i, line, result.text, "run", result.confidence, offset=result.offset)
            )
            report.run_repairs += 1

    report.offsets = dict(Counter(found_offsets))
    report.dominant = infer_dominant_offset(found_offsets)

    if report.dominant is not None:
        for i, line in enumerate(lines):
            if i in repaired_idx:
                continue
            new_line, token_repairs = repair_line_tokens(
                line, report.dominant.offset, allow_weak_signal=allow_weak_signal
            )
            if not token_repairs:
                continue
            out[i] = new_line
            repaired_idx.add(i)
            report.token_repairs += len(token_repairs)
            report.repairs.append(
                LineRepair(
                    i,
                    line,
                    new_line,
                    "token",
                    min(t.confidence for t in token_repairs),
                    offset=report.dominant.offset,
                )
            )

    report.lines_repaired = len(repaired_idx)
    report.low_confidence = [r for r in report.repairs if r.confidence < low_confidence_threshold]
    return out, report


def repair_text_with_report(text: str, *, allow_weak_signal: bool = True) -> tuple[str, DocumentReport]:
    """Like `repair_text`, but also returns the DocumentReport."""
    raw = text.split("\n")
    cr = [line.endswith("\r") for line in raw]
    lines = [line[:-1] if has_cr else line for line, has_cr in zip(raw, cr, strict=True)]
    repaired, report = repair_document(lines, allow_weak_signal=allow_weak_signal)
    joined = "\n".join(line + ("\r" if has_cr else "") for line, has_cr in zip(repaired, cr, strict=True))
    return joined, report


def repair_text(text: str) -> str:
    """Repair a multi-line string; line endings (LF or CRLF) are preserved."""
    return repair_text_with_report(text)[0]
