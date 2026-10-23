"""The port must match the original AIM implementation.

`fixtures/aim_reference.json` holds the scores of the original AIM code for the
fixture screenshots; `scripts/make_aim_reference.py` regenerates it.
"""

import json
from pathlib import Path

import pytest

aim = pytest.importorskip("skimlint.aim")

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = json.loads((FIXTURES / "aim_reference.json").read_text())


@pytest.mark.parametrize("screen", sorted(REFERENCE))
def test_scores_match_original_aim(screen):
    png = (FIXTURES / f"{screen}.png").read_bytes()

    scores = aim.run_metrics(png, list(aim.METRICS))

    for metric_id, expected in REFERENCE[screen].items():
        assert scores[metric_id] == pytest.approx(expected, rel=1e-6, abs=1e-12), metric_id


def test_dense_text_scores_higher_clutter_than_clean_text():
    clean = aim.run_metrics((FIXTURES / "clean.png").read_bytes(), ["m4", "m6", "m7", "m8"])
    dense = aim.run_metrics((FIXTURES / "dense.png").read_bytes(), ["m4", "m6", "m7", "m8"])

    for metric_id in clean:
        assert dense[metric_id] > clean[metric_id], metric_id
