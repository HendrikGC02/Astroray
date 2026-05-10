"""End-to-end gate for pkg74 — engine benchmark + visual showcase.

Spec: .astroray_plan/packages/pkg74-engine-benchmark-showcase.md

This test runs `benchmarks.showcase.runner.run(quick=True)` and asserts
the five Phase 1 artefacts exist, are non-trivial, and round-trip
(PNG re-openable, CSV parseable with > 0 data rows). Anything more
detailed than existence + size belongs to follow-up tests.
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray  # noqa: F401
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")


def _png_is_loadable(path: Path) -> bool:
    from PIL import Image  # noqa: PLC0415 — defer import so the skip is clean
    with Image.open(path) as img:
        img.load()
        return img.size[0] > 0 and img.size[1] > 0


def test_quick_run_produces_all_five_artefacts(tmp_path: Path) -> None:
    # Late import so the astroray-availability skip fires before runner imports.
    from benchmarks.showcase import runner  # noqa: PLC0415

    t0 = time.perf_counter()
    out_dir = runner.run(
        quick=True,
        output_root=tmp_path,
        # Hold these well under defaults so the test is robust on any laptop.
        resolution=48,
        samples=4,
        spp_series=[1, 4, 16],
        max_depth=4,
        seed=0xCAFE,
    )
    elapsed = time.perf_counter() - t0

    assert out_dir.exists(), f"runner did not create {out_dir}"
    assert out_dir.is_dir()

    expected_pngs = [
        "material_zoo_contact_sheet.png",
        "convergence_grid_contact_sheet.png",
        "convergence_curve.png",
    ]
    for name in expected_pngs:
        path = out_dir / name
        assert path.exists(), f"missing artefact: {path}"
        assert path.stat().st_size > 0, f"empty PNG: {path}"
        assert _png_is_loadable(path), f"PNG not loadable: {path}"

    csv_path = out_dir / "stats_summary.csv"
    assert csv_path.exists(), f"missing artefact: {csv_path}"
    assert csv_path.stat().st_size > 0
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) > 0, "stats_summary.csv has no data rows"
    # Required columns from the spec.
    required_cols = {"scene", "integrator", "samples", "render_seconds",
                     "machine_id", "git_sha", "run_date"}
    missing = required_cols - set(rows[0].keys())
    assert not missing, f"stats_summary.csv missing required columns: {missing}"

    html_path = out_dir / "index.html"
    assert html_path.exists(), f"missing artefact: {html_path}"
    assert html_path.stat().st_size > 0
    body = html_path.read_text(encoding="utf-8")
    for name in expected_pngs:
        assert name in body, f"index.html does not link {name}"

    # Soft sanity gate so a runaway test fails loudly rather than CI-timing-out.
    assert elapsed < 120.0, f"--quick run took {elapsed:.1f}s (cap: 120s)"
