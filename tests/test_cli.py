from pathlib import Path

import pytest

from pdf_encoding_repair.cli import main

from .helpers import PLAIN_LINES, corrupt


def test_cli_prints_repaired_text_and_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "in.txt"
    src.write_text("\n".join(corrupt(line, 29) for line in PLAIN_LINES[:6]) + "\n", encoding="utf-8")

    assert main([str(src)]) == 0

    captured = capsys.readouterr()
    assert captured.out == "\n".join(PLAIN_LINES[:6]) + "\n"
    assert "repaired: 6" in captured.err
    assert "+29" in captured.err
