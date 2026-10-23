"""One fitness score per document, for loops that tune writing rules against it.

Each component is a share in [0, 1], where 1 is best. The score is 100 times
the geometric mean of the components that were measured, so one bad component
pulls the score down and cannot be offset by the others. A component exists
only when its analysis ran: compare scores from runs with the same flags.
"""

from __future__ import annotations

import math
from typing import Dict

FITNESS_VERSION = 1

# A sentence with a mean dependency distance above this is hard to parse.
SENTENCE_DD_LIMIT = 3.0
# Feature congestion (m8) of the first screen: 1 at or below GOOD, 0 at or above BAD.
M8_GOOD = 4.0
M8_BAD = 6.5
# A component of 0 would make the score 0 no matter how the rest improves.
_FLOOR = 0.01


def blocks_component(report, max_words: int) -> float | None:
    """Share of block words that sit in blocks within the word limit."""
    total = sum(p.words for p in report.paragraphs)
    if not total or not max_words:
        return None
    return sum(p.words for p in report.paragraphs if p.words <= max_words) / total


def sentences_component(language) -> float | None:
    """Share of sentence words in sentences within the dependency distance limit."""
    total = sum(s.words for s in language.sentences)
    if not total:
        return None
    return sum(s.words for s in language.sentences if s.dependency_distance <= SENTENCE_DD_LIMIT) / total


def visual_component(visual) -> float | None:
    summary = visual["summary"].get("m8")
    if summary is None:
        return None
    return min(1.0, max(0.0, (M8_BAD - summary["first"]) / (M8_BAD - M8_GOOD)))


def score(components: Dict[str, float | None]) -> dict:
    measured = {k: v for k, v in components.items() if v is not None}
    if not measured:
        return {"version": FITNESS_VERSION, "score": None, "components": measured}
    log_mean = sum(math.log(max(v, _FLOOR)) for v in measured.values()) / len(measured)
    return {"version": FITNESS_VERSION, "score": 100 * math.exp(log_mean), "components": measured}
