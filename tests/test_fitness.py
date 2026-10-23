import math
from types import SimpleNamespace

import pytest

from skimlint import fitness
from skimlint.text import analyze_text


def test_score_is_100_times_the_geometric_mean():
    result = fitness.score({"blocks": 1.0, "sentences": 0.25})

    assert result["score"] == pytest.approx(50.0)
    assert result["version"] == fitness.FITNESS_VERSION


def test_unmeasured_components_are_left_out():
    assert fitness.score({"blocks": 0.81, "visual": None})["score"] == pytest.approx(81.0)
    assert fitness.score({})["score"] is None


def test_zero_component_is_floored_so_other_gains_still_count():
    worse = fitness.score({"blocks": 0.0, "sentences": 0.5})["score"]
    better = fitness.score({"blocks": 0.0, "sentences": 1.0})["score"]

    assert 0 < worse < better
    assert better == pytest.approx(100 * math.sqrt(0.01))


def test_blocks_component_is_the_share_of_words_in_short_blocks():
    report = analyze_text("one two three\n\n" + "word " * 7 + "\n")

    assert fitness.blocks_component(report, max_words=5) == pytest.approx(3 / 10)
    assert fitness.blocks_component(report, max_words=0) is None


def test_sentences_component_weights_by_words():
    language = SimpleNamespace(sentences=[
        SimpleNamespace(words=10, dependency_distance=2.0),
        SimpleNamespace(words=30, dependency_distance=4.0),
    ])

    assert fitness.sentences_component(language) == pytest.approx(10 / 40)


def test_visual_component_maps_first_screen_m8_linearly():
    def visual(m8):
        return {"summary": {"m8": {"first": m8}}}

    assert fitness.visual_component(visual(fitness.M8_GOOD - 1)) == 1.0
    assert fitness.visual_component(visual(fitness.M8_BAD + 1)) == 0.0
    midpoint = (fitness.M8_GOOD + fitness.M8_BAD) / 2
    assert fitness.visual_component(visual(midpoint)) == pytest.approx(0.5)
    assert fitness.visual_component({"summary": {}}) is None
