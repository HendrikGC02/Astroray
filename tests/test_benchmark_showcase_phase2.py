"""Phase 2 gate for pkg74 — every stat category must produce at least
one non-empty value on the Cornell scenes, the integrator-comparison
contact sheet must exist, and `qual_convergence_rate_slope` must be
finite + negative (Monte Carlo error decreases with SPP).

Spec: .astroray_plan/packages/pkg74-engine-benchmark-showcase.md
Research catalog: .astroray_plan/docs/engine-benchmark-research.md §2
"""
from __future__ import annotations

import csv
import math
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


# Categories that must have at least one populated cell across all rows.
# `intstat_` is allowed to be empty when the integrator has no debug
# stats (path_tracer + most non-NRC integrators); we don't gate it.
REQUIRED_NONEMPTY_CATEGORY_PREFIXES = ("geom_", "mem_", "time_", "samp_", "qual_", "gpu_")


def _png_loadable(path: Path) -> bool:
    from PIL import Image
    with Image.open(path) as img:
        img.load()
        return img.size[0] > 0 and img.size[1] > 0


def _read_rows(out_dir: Path) -> list[dict[str, str]]:
    csv_path = out_dir / "stats_summary.csv"
    assert csv_path.exists(), f"missing {csv_path}"
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_phase2_categories_populated(tmp_path: Path) -> None:
    from benchmarks.showcase import runner

    out_dir = runner.run(
        quick=True,
        output_root=tmp_path,
        resolution=48,
        samples=4,
        spp_series=[1, 4, 16],
        max_depth=4,
        seed=0xCAFE,
    )

    rows = _read_rows(out_dir)
    assert len(rows) > 0, "stats_summary.csv has no data rows"

    columns = list(rows[0].keys())

    # device column lands on every row.
    assert "device" in columns, "Phase 2 added the device column; missing"
    assert any(r.get("device") for r in rows), "no row carries a device tag"

    # Every required category has at least one non-empty cell across all rows.
    for prefix in REQUIRED_NONEMPTY_CATEGORY_PREFIXES:
        cat_cols = [c for c in columns if c.startswith(prefix)]
        assert cat_cols, f"no columns under category prefix {prefix!r}"
        nonempty = any(r[c] not in ("", None) for r in rows for c in cat_cols)
        assert nonempty, (
            f"category {prefix!r} has columns {cat_cols} but every cell is "
            f"empty across {len(rows)} rows")

    # Geometry counts on the convergence-grid Cornell rows must match
    # the scene builder's accounting (14 triangles + 1 sphere = 15
    # primitives, 4 materials, 1 light).
    cornell = [r for r in rows
               if r.get("scene") == "convergence_grid_cornell"]
    assert cornell, "convergence_grid_cornell rows missing"
    sample = cornell[0]
    assert sample.get("geom_triangles") == "14", sample
    assert sample.get("geom_spheres") == "1", sample
    assert sample.get("geom_primitives") == "15", sample

    # Convergence rate slope: finite, negative, sane bound. A correct
    # MC integrator approaches −0.5; in --quick mode at low SPP it
    # may drift but should still be < 0 and > −2.
    slope_str = next((r.get("qual_convergence_rate_slope") for r in cornell
                      if r.get("qual_convergence_rate_slope")), "")
    assert slope_str, "qual_convergence_rate_slope is empty on every Cornell row"
    slope = float(slope_str)
    assert math.isfinite(slope), f"slope is not finite: {slope}"
    assert slope < 0.0, f"slope is non-negative ({slope}); MC error should drop with SPP"
    assert slope > -2.0, f"slope is implausibly steep ({slope})"

    # Variance columns: present only on the top-SPP Cornell row.
    variance_rows = [r for r in cornell
                     if r.get("qual_variance_mean") not in ("", None)]
    assert len(variance_rows) >= 1, (
        "no Cornell row carries qual_variance_mean — paired-seed render skipped?")
    var_mean = float(variance_rows[0]["qual_variance_mean"])
    assert math.isfinite(var_mean) and var_mean >= 0.0, var_mean

    # Integrator comparison: at least one row exists, and the contact
    # sheet + timing PNG are produced.
    ic_rows = [r for r in rows
               if r.get("scene") == "integrator_compare_cornell_glass"]
    assert ic_rows, "integrator_compare scene produced no rows"
    # path_tracer must be among the integrators that succeeded.
    pt_rows = [r for r in ic_rows
               if r.get("integrator") == "path_tracer"
               and r.get("skip_reason") in ("", None)]
    assert pt_rows, ("integrator_compare must include a successful path_tracer "
                     "row; got rows: " + str([(r.get("integrator"),
                                               r.get("skip_reason"))
                                              for r in ic_rows]))

    for png in ("integrator_compare_contact_sheet.png",
                "integrator_compare_timing.png"):
        path = out_dir / png
        assert path.exists() and path.stat().st_size > 0, f"missing/empty {path}"
        assert _png_loadable(path), f"unloadable PNG {path}"

    # HTML index has the new category sections (visible as <details>
    # elements with summaries).
    html = (out_dir / "index.html").read_text(encoding="utf-8")
    assert "<details" in html, "Phase 2 collapsible category sections missing"
    for label in ("Geometry", "Memory", "Timing", "Quality", "Integrator-specific"):
        assert label in html, f"category section {label!r} missing from index.html"

    # Phase 1 gate must keep passing through Phase 2 — assert the same
    # invariants on the same output here so a Phase 2 regression is
    # caught even if the Phase 1 test is run separately.
    for legacy_col in ("scene", "integrator", "samples", "render_seconds",
                       "machine_id", "git_sha", "run_date",
                       "mean_luminance", "p99_luminance", "max_luminance"):
        assert legacy_col in columns, (
            f"Phase 1 column {legacy_col!r} dropped — back-compat broken")


def test_gpu_flag_runs_without_cuda(tmp_path: Path) -> None:
    """`--gpu` is opt-in. With CUDA absent it must still complete and
    record `device=cpu` with a `gpu unavailable` skip_reason on the
    rows that were asked for GPU."""
    from benchmarks.showcase import runner

    out_dir = runner.run(
        quick=True,
        output_root=tmp_path,
        resolution=32,
        samples=2,
        spp_series=[1, 4],
        max_depth=3,
        seed=0xCAFE,
        gpu=True,
        skip_integrator_compare=True,  # keep this gate fast
    )
    rows = _read_rows(out_dir)
    assert rows
    devices_seen = {r.get("device") for r in rows}
    # Always cpu; gpu only when actually available.
    assert "cpu" in devices_seen, devices_seen
