# pdf-encoding-repair

Detect and repair text extracted from PDFs whose font `ToUnicode`/CMap maps glyphs with a **constant
character-code offset**. Pure Python, no dependencies, works on plain strings so any extractor can feed it.

## The problem

Some PDFs embed a font whose character map is shifted by a fixed amount. The PDF looks fine on screen, but
every extractor returns garbage, and the garbage is *consistent*:

```
before:  )LOWHU FDUWULGJH QRW SURSHUO\ LQVWDOOHG      (spaces are really \x03 control characters)
after:   Filter cartridge not properly installed
```

Every character is off by the same amount (here 29: `F` is 70, `)` is 41). Different documents use different
offsets, so this library **infers the offset per run** instead of hardcoding it.

## 60-second quickstart

```bash
pip install pdf-encoding-repair        # or: uv add pdf-encoding-repair
```

```python
from pdf_encoding_repair import repair_run, repair_document, repair_text

result = repair_run(")LOWHU\x03FDUWULGJH")
result.text  # 'Filter cartridge'
result.offset  # 29
result.confidence  # 0.0-1.0; only meaningful when result.was_repaired

# A whole document: a list of lines from any extractor.
lines, report = repair_document(extracted_lines)
report.offsets  # {29: 412}   offsets found -> lines that used them
report.dominant  # DominantOffset(offset=29, ...) or None
report.lines_repaired  # 415
report.low_confidence  # repairs worth a human look

# Or just a string:
clean = repair_text(extracted_text)
```

Command line: repaired text on stdout, report on stderr.

```bash
pdf-encoding-repair extracted.txt > repaired.txt
# lines: 7, repaired: 6 (whole-line: 5, tokens: 1)
# offsets found: +29 x5
# dominant offset: +29 (5/5 repairs)
```

Use `-` to read stdin, and `--no-weak-signal` to turn off bare-number repair (see below).

### Public API

| Function | Purpose |
| --- | --- |
| `repair_run(text)` | Repair one run. Returns `RepairResult(text, was_repaired, offset, confidence)`. |
| `infer_dominant_offset(offsets)` | Given per-line offsets, return the one that clearly dominates, or `None`. |
| `repair_line_tokens(text, offset, *, allow_weak_signal=True)` | Token-level pass for short corrupted tokens inside otherwise clean lines. |
| `repair_document(lines, ...)` | Both passes over a list of lines. Returns `(repaired_lines, DocumentReport)`. |
| `repair_text(text)` | Convenience wrapper over a multi-line string (LF/CRLF preserved). |

## How detection works

1. **Flag suspicious runs.** Real text has no raw control characters (codepoints < 32, except tab/CR/LF). A
   shifted space usually lands in that range, which both flags the run and *is* a near-exact clue to the
   offset (`32 - ord(char)`). Runs with no control character fall back to a vowel-ratio check.
2. **Infer the offset.** Candidates come from the control characters plus a sweep of -40..+40.
3. **Three gates.** A shifted candidate is accepted only if it (a) is at most 10% non-letter/non-space,
   (b) has a plausible English letter-frequency profile, and (c) contains real common words. All three are
   required, not a blended score.
4. **Beat the baseline.** A candidate must strictly beat the unshifted text. An offset of exactly ±32 only flips
   ASCII case, and scoring is case-insensitive, so without this guard `system` would "repair" to `SYSTEM`.
5. **Document offset.** `infer_dominant_offset` needs at least 5 repaired lines and an 80% share for one offset.
6. **Token pass.** Only with an established document offset, lines whole-run repair skipped (e.g. clean words
   mixed with corrupted codes) are rescanned token by token. A token needs a strong signal (a control character,
   or a letter/digit adjacent to `&` or `'`). A weak signal (a short number like `14`) counts only when the same
   line has a strong-signal sibling.

## Limits: what it will not fix

- **English only.** The letter-frequency and word gates assume English. The built-in word list is small and
  leans toward technical/appliance vocabulary; text with none of those words may not clear the word gate.
- **Constant offsets only.** Substitution ciphers, per-font arbitrary glyph remapping, or offsets that vary
  within a run are out of scope.
- **Mixed runs are left alone.** A run with clean text glued directly onto a corrupted tail fails the noise gate
  for every offset and is deliberately untouched. Only the token pass can help, and only for short codes.
- **Short text is hard.** Runs under 6 characters are never flagged; very short corrupted runs are not judged.
- **Case can be ambiguous.** Without a space glyph to pin the offset, the sweep cannot tell offset N from N-32:
  the letters come back, but a lowercase run may be returned uppercase.
- **Offsets are limited to ±40.** Offsets implied by control characters can be outside that range.
- **It is not an extractor or OCR.** If the extractor already dropped or reordered characters, nothing can be
  recovered.

## False positives, honestly

The design goal is "leave it alone unless sure", but it is heuristic, so it can be wrong.

- **Wrong-but-plausible numbers.** The weak-signal token path turns short digit tokens into letters
  (`14` -> `PS`). On a line that shares a corrupted word with real measurements, that would corrupt real numbers.
  Pass `allow_weak_signal=False` (`--no-weak-signal`) for prose and data tables. Strong-signal tokens are still
  repaired.
- **Parentheses are not evidence.** `(`/`)` next to digits and letters is everywhere in ordinary text
  (`14 in. (35.6 cm)`, `(1)`, `(SD)`). Treating it as a corruption signal produced many false positives, so it is
  ignored on purpose. The cost: a corrupted token that only differs by parentheses is not repaired.
- **Short tokens.** Token repair works from one trusted document offset, never from the token itself, so a token is
  only as trustworthy as that offset. Repaired tokens carry a confidence of 0.5-0.8; look at
  `report.low_confidence`.
- **Precision over recall.** Expect some corrupted lines to be left as they are. Review the report on documents
  that matter.

## Origin

Extracted from a hackathon project's PDF ingestion pipeline, where several source PDFs had this exact
corruption and retrieval quality suffered until it was repaired.

## Development

```bash
uv sync
uv run ruff check . && uv run pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md). MIT licensed.
