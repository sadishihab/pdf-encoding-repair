"""Detect and repair PDF-extracted text corrupted by a constant character-code offset."""

from .document import DocumentReport, LineRepair, repair_document, repair_text, repair_text_with_report
from .repair import (
    DominantOffset,
    RepairResult,
    TokenRepair,
    infer_dominant_offset,
    repair_line_tokens,
    repair_run,
)

__version__ = "0.1.0"

__all__ = [
    "DocumentReport",
    "DominantOffset",
    "LineRepair",
    "RepairResult",
    "TokenRepair",
    "infer_dominant_offset",
    "repair_document",
    "repair_line_tokens",
    "repair_run",
    "repair_text",
    "repair_text_with_report",
]
