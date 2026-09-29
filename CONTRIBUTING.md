# Contributing

```bash
uv sync
uv run ruff check .
uv run ruff format .
uv run pytest
```

## How to add a test case

All test strings must be **synthetic**: made in the test by encoding known English text with a known offset,
then repairing. No real documents, no text copied from PDFs, no company or product names, no logos.

1. Pick plain English text you wrote yourself and an offset.
2. Build the corrupted input with `corrupt` from `tests/helpers.py` (it shifts every character by `-offset`,
   so the repair must find `+offset`):

   ```python
   from tests.helpers import corrupt


   def test_my_case() -> None:
       original = "Check the filter before you start the service."
       result = repair_run(corrupt(original, 23))
       assert result.was_repaired is True
       assert result.offset == 23
       assert result.text == original
   ```
3. For a **false positive** report, add the *clean* string that was wrongly changed and assert it comes back
   byte-identical (`was_repaired is False`, or `repair_line_tokens` returns no repairs). Write your own clean
   equivalent rather than pasting the original.
4. Put run-level tests in `tests/test_repair.py`, whole-document tests in `tests/test_document.py`.
5. `corrupt` fails if a shifted code goes negative: a `\n` (10) with offset 29 raises. Leave line breaks out
   of the text you corrupt.

Guards (noise/letter-frequency/word gates, the baseline check, the parenthesis rule, and the
established-offset rule for token repair) have regression tests. Change one of them only together with its test.
