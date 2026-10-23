import numpy as np
import pytest

spacy = pytest.importorskip("spacy")
from spacy.tokens import Doc  # noqa: E402

from skimlint.language import analyze_language, dependency_distance, load_model  # noqa: E402
from skimlint.text import analyze_text  # noqa: E402


def test_dependency_distance_counts_every_token_and_root_as_zero():
    nlp = spacy.blank("en")
    # "The cat sat": The -> cat, cat -> sat, sat is the root.
    doc = Doc(nlp.vocab, words=["The", "cat", "sat"], heads=[1, 2, 2], deps=["det", "nsubj", "ROOT"])

    mean, adjacent = dependency_distance(doc[:])

    assert mean == pytest.approx(2 / 3)
    assert adjacent == pytest.approx(2 / 3)


def test_long_range_dependency_raises_the_distance():
    nlp = spacy.blank("en")
    words = ["Dogs", "that", "bark", "loudly", "sleep"]
    doc = Doc(nlp.vocab, words=words, heads=[4, 2, 0, 2, 4], deps=["nsubj", "nsubj", "relcl", "advmod", "ROOT"])

    mean, _ = dependency_distance(doc[:])

    assert mean == pytest.approx((4 + 1 + 2 + 1 + 0) / 5)


def _vector_nlp():
    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")
    for word, vector in {"red": [1, 0], "apple": [1, 0.1], "blue": [0, 1], "sky": [0.1, 1]}.items():
        nlp.vocab.set_vector(word, np.array(vector, dtype=np.float32))
    return nlp


def test_coherence_pairs_consecutive_sentences_inside_a_block_only():
    report = analyze_text("red apple red. red apple red.\n\nblue sky blue. blue sky blue.\n")

    language = analyze_language(report.paragraphs, _vector_nlp())

    assert len(language.sentences) == 4
    assert language.coherence == pytest.approx([1.0, 1.0])


def test_fragments_are_not_sentences():
    report = analyze_text("red apple. blue sky blue.\n")

    language = analyze_language(report.paragraphs, _vector_nlp())

    assert [s.words for s in language.sentences] == [3]
    assert language.coherence == []


def test_missing_model_names_the_download_command():
    with pytest.raises(RuntimeError, match="python -m spacy download no_such_model"):
        load_model("no_such_model")
