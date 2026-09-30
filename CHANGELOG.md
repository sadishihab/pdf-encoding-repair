# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-01

### Added

- Detection and repair of PDF-extracted text whose font `ToUnicode`/CMap maps glyphs with a constant
  character-code offset. The offset is inferred per run rather than hardcoded. Pure Python, no dependencies,
  operates on plain strings from any extractor.
- Run-level repair: suspicious runs are flagged by raw control characters (or a vowel-ratio check), candidate
  offsets come from those control characters plus a sweep of -40..+40, and a candidate is accepted only if it
  passes a noise gate, a letter-frequency gate and a common-word gate, and strictly beats the unshifted text.
- Document-level repair: a dominant offset is established when at least 5 lines are repaired and one offset
  has an 80% share; only then are the remaining lines rescanned token by token against that offset.
- Public API: `repair_run`, `infer_dominant_offset`, `repair_line_tokens`, `repair_document`, `repair_text`,
  `repair_text_with_report`, and the result types `RepairResult`, `DominantOffset`, `TokenRepair`,
  `DocumentReport`, `LineRepair`.
- `pdf-encoding-repair` command: reads a file or `-` for stdin, writes repaired text to stdout and a report
  (lines repaired, offsets found, dominant offset, low-confidence repairs) to stderr. `--no-weak-signal`
  disables token repair of bare short numbers.
- Inline type hints (`py.typed`).

### Known limitations

- English only; the built-in word list is small and leans toward technical/appliance vocabulary.
- Constant offsets only: substitution ciphers, arbitrary glyph remapping, and offsets that vary within a run
  are out of scope.
- Runs mixing clean text with a corrupted tail are left untouched; only the token pass can help, and only for
  short codes.
- Runs under 6 characters are never flagged.
- Without a space glyph to pin the offset, offset N cannot be told from N-32, so a lowercase run may be
  returned uppercase.
- The offset sweep covers -40..+40.
- It is not an extractor or OCR: characters already dropped or reordered cannot be recovered.
- Heuristic: the weak-signal token path can turn real short numbers into letters; parentheses are not treated
  as a corruption signal. Precision is favoured over recall.

[Unreleased]: https://github.com/sadishihab/pdf-encoding-repair/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/sadishihab/pdf-encoding-repair/releases/tag/v0.1.0
