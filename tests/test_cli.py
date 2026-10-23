import io
import json
import sys
from pathlib import Path

from skimlint.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_clean_file_passes(capsys):
    assert main([str(FIXTURES / "clean.md")]) == 0
    assert "0 of 1 file failed" in capsys.readouterr().out


def test_long_paragraph_fails_with_line_number(capsys):
    assert main([str(FIXTURES / "dense.md")]) == 1
    out = capsys.readouterr().out
    assert "3:" in out
    assert "[long-paragraph]" in out


def test_limit_is_configurable_and_zero_turns_it_off():
    assert main(["--max-paragraph-words", "200", str(FIXTURES / "dense.md")]) == 0
    assert main(["--max-paragraph-words", "0", str(FIXTURES / "dense.md")]) == 0


def test_dense_inline_code_is_off_by_default_and_fails_when_set(capsys):
    args = ["--max-paragraph-words", "0", str(FIXTURES / "dense.md")]
    assert main(args) == 0
    assert main(["--max-code-spans", "4", *args]) == 1
    assert "[dense-inline-code]" in capsys.readouterr().out


def test_directory_input_finds_markdown_files(capsys):
    main(["--format", "json", str(FIXTURES)])
    paths = [r["path"] for r in json.loads(capsys.readouterr().out)]
    assert [Path(p).name for p in paths] == ["clean.md", "dense.md"]


def test_stdin(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("word " * 60))
    assert main(["-"]) == 1
    assert "<stdin>" in capsys.readouterr().out


def test_missing_file_exits_2(capsys):
    assert main(["no-such-file.md"]) == 2
    assert "no-such-file.md" in capsys.readouterr().err
