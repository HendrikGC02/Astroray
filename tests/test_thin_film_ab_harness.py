# -*- coding: utf-8 -*-
"""pkg178 thin-film A/B — unit tests for the pure metric/band/sweep layer.

Synthetic arrays only — no Blender, no GPU. The full Cycles-5.2-vs-Astroray run is
the LEAD's on-hardware acceptance gate (needs Blender 5.2 + the addon .pyd + the
RTX box, none present in CI); there is no verdict here by design.

    pytest tests/test_thin_film_ab_harness.py -v
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_TF = REPO_ROOT / "benchmarks" / "cycles-parity" / "thin_film"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_unique(mod_name, path):
    """Load a module from an explicit path under a UNIQUE name (avoids the bare
    `import scenes`/`import harness` sys.modules collision across benchmarks dirs;
    see tests/test_pkg129_metal_ab_harness.py for the same pattern)."""
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


_scenes = _load_unique("tf_scenes", _TF / "scenes.py")
_H = _load_unique("tf_harness", _TF / "harness.py")


# --------------------------------------------------------------------------- #
# Sweep construction
# --------------------------------------------------------------------------- #

def test_sweep_grid_shape():
    sweep = _scenes.thinfilm_sweep()
    assert len(sweep) == 2 * len(_scenes.THICKNESSES_NM) * len(_scenes.FILM_IORS)
    kinds = {c.kind for c in sweep}
    assert kinds == {"dielectric", "conductor"}
    names = {c.name for c in sweep}
    assert len(names) == len(sweep)  # unique names


def test_kind_material_params():
    sweep = {c.kind: c for c in _scenes.thinfilm_sweep()}
    assert sweep["conductor"].metallic == 1.0
    assert sweep["dielectric"].metallic == 0.0
    # dielectric is a near-black body so only the iridescent Fresnel shows.
    assert max(sweep["dielectric"].base_color) < 0.1
    assert min(sweep["conductor"].base_color) > 0.5


def test_config_by_name_roundtrip():
    c = _scenes.thinfilm_sweep()[7]
    assert _scenes.config_by_name(c.name) is not None
    with pytest.raises(ValueError):
        _scenes.config_by_name("tf_nope")


# --------------------------------------------------------------------------- #
# Metric layer
# --------------------------------------------------------------------------- #

def test_per_channel_ratio_identity():
    a = np.full((4, 4, 3), 0.5, np.float32)
    assert _H.per_channel_ratio(a, a) == pytest.approx((1.0, 1.0, 1.0))


def test_per_channel_ratio_values():
    a = np.zeros((2, 2, 3), np.float32)
    b = np.zeros((2, 2, 3), np.float32)
    a[..., 0] = 0.4; b[..., 0] = 0.5   # 0.8
    a[..., 1] = 0.6; b[..., 1] = 0.6   # 1.0
    a[..., 2] = 0.9; b[..., 2] = 0.6   # 1.5
    r = _H.per_channel_ratio(a, b)
    assert r == pytest.approx((0.8, 1.0, 1.5))


def test_in_band_both_bounds():
    band = _H.Band(0.85, 1.15)
    assert _H.in_band((1.0, 1.0, 1.0), band)
    assert not _H.in_band((0.84, 1.0, 1.0), band)   # floor
    assert not _H.in_band((1.0, 1.16, 1.0), band)   # ceiling (energy GAIN fails)
    assert not _H.in_band((float("nan"), 1.0, 1.0), band)  # missing signal


def test_hue_delta_circular_wraparound():
    assert _H._hue_delta_deg(10.0, 350.0) == pytest.approx(20.0)
    assert _H._hue_delta_deg(350.0, 10.0) == pytest.approx(20.0)
    assert _H._hue_delta_deg(0.0, 180.0) == pytest.approx(180.0)
    assert math.isnan(_H._hue_delta_deg(float("nan"), 10.0))


def test_sphere_roi_is_central_subregion():
    img = np.zeros((100, 100, 3), np.float32)
    roi = _H.sphere_roi(img)
    assert roi.shape[0] < 100 and roi.shape[1] < 100
    assert roi.shape[0] > 0 and roi.shape[1] > 0


def test_compare_cell_identical_passes():
    cfg = _scenes.thinfilm_sweep()[0]
    img = np.full((16, 16, 3), 0.4, np.float32)
    img[..., 2] = 0.3  # give it some chroma so hue is defined
    r = _H.compare_cell(cfg, img, img, _H.Band(0.85, 1.15))
    assert r.status == "pass"
    assert r.ratio == pytest.approx((1.0, 1.0, 1.0))
    assert r.hue_delta_deg == pytest.approx(0.0, abs=1e-6)
