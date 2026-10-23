"""End-to-end --language run. Skipped when the spaCy model is not installed."""

import json
from pathlib import Path

import pytest

spacy = pytest.importorskip("spacy")
from skimlint.cli import main  # noqa: E402
from skimlint.language import DEFAULT_MODEL  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

if not spacy.util.is_package(DEFAULT_MODEL):
    pytest.skip(f"spaCy model {DEFAULT_MODEL} is not installed", allow_module_level=True)


def test_dense_document_has_harder_sentences_and_lower_fitness(capsys):
    main(["--language", "--max-paragraph-words", "0", "--format", "json",
          str(FIXTURES / "clean.md"), str(FIXTURES / "dense.md")])

    clean, dense = json.loads(capsys.readouterr().out)
    assert dense["language"]["dependency_distance_mean"] > clean["language"]["dependency_distance_mean"]
    assert dense["fitness"]["components"]["sentences"] < clean["fitness"]["components"]["sentences"]
    assert dense["fitness"]["score"] < clean["fitness"]["score"]


def test_hard_sentence_rule_reports_the_block_line(capsys):
    exit_code = main(["--language", "--max-paragraph-words", "0", "--max-dependency-distance", "3",
                      str(FIXTURES / "dense.md")])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "[hard-sentence]" in out
    assert "3:" in out
