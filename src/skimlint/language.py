"""Sentence metrics on spaCy parses: dependency distance and coherence.

The formulas follow TextDescriptives (https://github.com/hlasse/textdescriptives,
Apache License 2.0). It is not a dependency because it pins numpy below 2, which
the visual metrics need.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from typing import List

from .text import Paragraph

DEFAULT_MODEL = "en_core_web_md"

# Sentences with fewer words are fragments ("Unit tests."): they parse into
# trivially short dependencies and would reward chopping text into pieces.
MIN_SENTENCE_WORDS = 3


@dataclass
class Sentence:
    line: int
    words: int
    dependency_distance: float
    adjacent_share: float
    text: str

    @property
    def preview(self) -> str:
        return " ".join(self.text.split()[:8])


@dataclass
class LanguageReport:
    sentences: List[Sentence] = field(default_factory=list)
    # Similarity of each pair of consecutive sentences inside one block.
    coherence: List[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        dds = sorted(s.dependency_distance for s in self.sentences)
        return {
            "sentences": len(self.sentences),
            "dependency_distance_mean": statistics.fmean(dds) if dds else None,
            "dependency_distance_p90": dds[int(0.9 * (len(dds) - 1))] if dds else None,
            "coherence_mean": statistics.fmean(self.coherence) if self.coherence else None,
            "sentence_details": [
                {k: v for k, v in asdict(s).items() if k != "text"} | {"preview": s.preview}
                for s in self.sentences
            ],
        }


def load_model(name: str):
    import spacy

    try:
        return spacy.load(name)
    except OSError as e:
        raise RuntimeError(f"spaCy model {name!r} is not installed; run: python -m spacy download {name}") from e


def dependency_distance(span) -> tuple[float, float]:
    """Mean distance from each token to its head, and the share of adjacent heads.

    As in TextDescriptives, every token counts, and the root has distance 0.
    """
    distances = [abs(t.head.i - t.i) if t.dep_ != "ROOT" else 0 for t in span]
    adjacent = [d == 1 for d in distances]
    return statistics.fmean(distances), statistics.fmean(adjacent)


def _words(span) -> int:
    return sum(1 for t in span if not (t.is_punct or t.is_space))


def analyze_language(paragraphs: List[Paragraph], nlp) -> LanguageReport:
    report = LanguageReport()
    has_vectors = nlp.vocab.vectors.shape[0] > 0
    for paragraph, doc in zip(paragraphs, nlp.pipe(p.text for p in paragraphs)):
        sentences = [s for s in doc.sents if _words(s) >= MIN_SENTENCE_WORDS]
        for span in sentences:
            dd, adjacent = dependency_distance(span)
            report.sentences.append(Sentence(paragraph.line, _words(span), dd, adjacent, span.text))
        if has_vectors:
            report.coherence.extend(
                float(a.similarity(b)) for a, b in zip(sentences, sentences[1:]) if a.vector_norm and b.vector_norm
            )
    return report
