"""Command line entry point: `pdf-encoding-repair input.txt`."""

from __future__ import annotations

import argparse
import sys

from .document import DocumentReport, repair_text_with_report


def format_report(report: DocumentReport) -> str:
    out = [
        f"lines: {report.total_lines}, repaired: {report.lines_repaired} "
        f"(whole-line: {report.run_repairs}, tokens: {report.token_repairs})",
    ]
    if report.offsets:
        found = ", ".join(f"{o:+d} x{n}" for o, n in sorted(report.offsets.items()))
        out.append(f"offsets found: {found}")
    if report.dominant is not None:
        d = report.dominant
        out.append(f"dominant offset: {d.offset:+d} ({d.count}/{d.total_repaired} repairs)")
    else:
        out.append("dominant offset: none (token-level pass skipped)")
    if report.low_confidence:
        out.append(f"low-confidence repairs ({len(report.low_confidence)}):")
        for r in report.low_confidence:
            out.append(
                f"  line {r.line_number + 1} [{r.kind}, {r.confidence:.2f}]: {r.original!r} -> {r.repaired!r}"
            )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pdf-encoding-repair",
        description="Repair text extracted from PDFs with a constant character-code offset. "
        "Repaired text goes to stdout, a report to stderr.",
    )
    parser.add_argument("input", help="text file to repair, or - for stdin")
    parser.add_argument(
        "--no-weak-signal",
        action="store_true",
        help="disable token repair of bare short numbers (safer for data tables)",
    )
    args = parser.parse_args(argv)

    if args.input == "-":
        text = sys.stdin.read()
    else:
        with open(args.input, encoding="utf-8", newline="") as f:
            text = f.read()

    repaired, report = repair_text_with_report(text, allow_weak_signal=not args.no_weak_signal)
    sys.stdout.write(repaired)
    print(format_report(report), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
