"""Regenerates the test fixtures: first-screen PNGs and the original AIM scores for them.

Usage: python scripts/make_aim_reference.py <path to a clone of github.com/aalto-ui/aim>

The original AIM metrics run unchanged from that clone, so the tests compare
skimlint's port against AIM itself. Needs the `visual` extra, plus `pydantic`
and `python-resize-image`, which the AIM metric modules import.
"""

import base64
import importlib
import io
import json
import math
import sys
from pathlib import Path

from PIL import Image

from skimlint.render import SCREEN_HEIGHT, SCREEN_WIDTH, screenshot

ORIGINAL_MODULES = {
    "m1": "m1_png_file_size",
    "m2": "m2_jpeg_file_size",
    "m3": "m3_distinct_rgb_values",
    "m4": "m4_contour_density",
    "m5": "m5_figure_ground_contrast",
    "m6": "m6_contour_congestion",
    "m7": "m7_subband_entropy",
    "m8": "m8_feature_congestion",
    "m13": "m13_luminance_std",
}

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def main() -> None:
    sys.path.insert(0, str(Path(sys.argv[1]) / "backend"))
    names = ["clean", "dense"]
    screens = screenshot([(FIXTURES / f"{n}.md").read_text() for n in names], 980, 1)
    pngs = {name: doc_screens[0] for name, doc_screens in zip(names, screens)}
    blank = io.BytesIO()
    Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), "white").save(blank, format="PNG")
    pngs["blank"] = blank.getvalue()

    reference = {}
    for name, png in pngs.items():
        (FIXTURES / f"{name}.png").write_bytes(png)
        b64 = base64.b64encode(png).decode()
        scores = {}
        for metric_id, module in ORIGINAL_MODULES.items():
            metric = importlib.import_module(f"aim.metrics.{metric_id}.{module}").Metric
            value = float(next(r for r in metric.execute_metric(b64) if isinstance(r, (int, float))))
            # On a blank screen m5 and m6 divide 0 by 0. AIM catches ZeroDivisionError and
            # returns 0.0, but numpy 2 integers give NaN instead, so store the intended 0.0.
            scores[metric_id] = 0.0 if math.isnan(value) else value
        reference[name] = scores
        print(name, scores)
    (FIXTURES / "aim_reference.json").write_text(json.dumps(reference, indent=2) + "\n")


if __name__ == "__main__":
    main()
