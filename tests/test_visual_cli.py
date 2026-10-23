"""End-to-end --visual run. Skipped when no Chromium is available."""

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("skimlint.aim")
sync_api = pytest.importorskip("playwright.sync_api")

from skimlint.cli import main  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module", autouse=True)
def chromium_available():
    executable = os.environ.get("SKIMLINT_CHROMIUM")
    try:
        with sync_api.sync_playwright() as p:
            p.chromium.launch(executable_path=executable).close()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no Chromium: {e}")


def test_visual_scores_every_screen_and_fails_above_limit(capsys, tmp_path):
    args = ["--visual", "--metrics", "m4,m8", "--save-screenshots", str(tmp_path), "--format", "json"]

    exit_code = main([*args, "--fail-above", "m8=3.5", str(FIXTURES / "clean.md"), str(FIXTURES / "dense.md")])

    clean, dense = json.loads(capsys.readouterr().out)
    assert clean["visual"]["summary"]["m8"]["first"] < 3.5 < dense["visual"]["summary"]["m8"]["first"]
    assert any(f["rule"] == "visual-m8" for f in dense["findings"])
    assert not any(f["rule"] == "visual-m8" for f in clean["findings"])
    assert exit_code == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["clean-1.png", "dense-1.png"]


def test_fail_above_needs_visual():
    with pytest.raises(SystemExit):
        main(["--fail-above", "m8=1", str(FIXTURES / "clean.md")])
