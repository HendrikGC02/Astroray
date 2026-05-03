#!/usr/bin/env python
"""pkg29a — scoped caustic validation diagnostics."""

from __future__ import annotations

import csv
import json
import os
import sys

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

from base_helpers import save_image  # noqa: E402
from scenes.caustic_validation import SCENES, image_metrics, render_scene  # noqa: E402


pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")


def test_caustic_integrator_registered():
    assert "caustic_path_tracer" in astroray.integrator_registry_names()


@pytest.mark.parametrize("scene_name", sorted(SCENES))
def test_caustic_validation_scenes_save_images_and_stats(scene_name, test_results_dir):
    records = [
        render_scene(astroray, scene_name, "path_tracer", samples=8, max_depth=10),
        render_scene(astroray, scene_name, "caustic_path_tracer", samples=8, max_depth=10),
    ]

    rows = []
    for record in records:
        pixels = record.pixels
        assert pixels.shape == (96, 96, 3)
        assert np.isfinite(pixels).all()
        assert float(pixels.mean()) > 0.001

        save_image(
            pixels,
            os.path.join(test_results_dir, f"pkg29a_{scene_name}_{record.integrator}.png"),
        )

        metrics = image_metrics(pixels, scene_name)
        row = {
            "scene": scene_name,
            "integrator": record.integrator,
            "seconds": record.seconds,
            **metrics,
            **record.stats,
        }
        rows.append(row)

    json_path = os.path.join(test_results_dir, f"pkg29a_{scene_name}_stats.json")
    csv_path = os.path.join(test_results_dir, f"pkg29a_{scene_name}_stats.csv")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, sort_keys=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        keys = sorted({key for row in rows for key in row})
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)

    caustic_row = next(row for row in rows if row["integrator"] == "caustic_path_tracer")
    assert "caustic_connections" in caustic_row
    assert "caustic_energy" in caustic_row
    assert caustic_row["max_luminance"] > 0.01
