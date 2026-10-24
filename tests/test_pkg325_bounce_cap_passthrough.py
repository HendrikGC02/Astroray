"""pkg325: dielectric bounce-cap passthrough (``dielectric_bounce_cap: terminate | passthrough``).

Scene: benchmarks/pkg325 (three glass panes + a solid tumbler + diffuse props, white world). A camera
ray through all three panes crosses 6 glass interfaces; under ``terminate`` (Cycles semantics, the
default) a path-depth cap below 7 leaves that region dark. Dead = ROI luminance < 0.25 of the uncapped
white-world reference (1.0), per pixel. ROIs are rectangles whose every pixel crosses exactly 2 / 4 / 6
interfaces (``test_roi_interface_counts``).
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from benchmarks.pkg325 import scene_geometry as G  # noqa: E402

W, H = 320, 240
DEAD_BELOW = 0.25


def _roi_stats(img, name):
    x0, y0, x1, y1 = G.rois(W, H)[name]
    lum = img[y0:y1, x0:x1].mean(-1)
    return float((lum < DEAD_BELOW).mean()), float(lum.mean())


def _render(backend, cap, spp=32, seed=325, mode=None):
    import runtime_setup
    runtime_setup.configure_test_imports()
    import astroray
    from benchmarks.pkg325 import engine_scene as E
    r = astroray.Renderer()
    if backend == "gpu":
        try:
            r.set_use_gpu(True)
        except Exception as e:  # noqa: BLE001 - CPU-only build
            pytest.skip(f"GPU unavailable: {e}")
        if not getattr(r, "gpu_available", False):
            pytest.skip("gpu_available is False")
    E.build(r, W, H)
    if mode is not None:
        r.set_dielectric_bounce_cap(mode)
    # the addon passes the same cap for total / diffuse / glossy / transmission / transparent
    return E.render(r, backend, spp, cap, seed=seed, diffuse_bounces=cap, glossy_bounces=cap,
                    transmission_bounces=cap, volume_bounces=-1, transparent_bounces=cap)


# --------------------------------------------------------------------------- #
# Scene hygiene (the fails-before test: pkg324's sp07 tumbler had coincident faces, #1160)
# --------------------------------------------------------------------------- #

def test_scene_hygiene():
    h = G.hygiene(G.scene_meshes())
    assert all(v > 0 for v in h["signed_volume"].values()), h["signed_volume"]
    assert h["coincident_pairs"] == []
    assert h["min_gap"] >= G.MIN_GAP - 1e-9


def test_pkg324_sp07_profile_is_the_negative_control():
    """The same hygiene check must flag the pkg324 tumbler: wound inward (signed volume -0.380, as Blender
    left it), base disk coplanar with the plinth top, self-overlapping rim ring."""
    meshes = G.legacy_pkg324_meshes()
    h = G.hygiene(meshes)
    assert h["signed_volume"]["LegacyTumbler"] < 0
    assert len(h["coincident_pairs"]) > 0
    assert h["min_gap"] < G.MIN_GAP


def test_roi_interface_counts():
    meshes = G.scene_meshes()
    for name, expect in (("stack1", 2), ("stack2", 4), ("stack3", 6)):
        x0, y0, x1, y1 = G.rois(W, H)[name]
        xs, ys = np.meshgrid(np.arange(x0, x1), np.arange(y0, y1))
        o, d = G.camera_rays(W, H, xs.ravel(), ys.ravel())
        assert set(G.count_crossings(o, d, meshes).tolist()) == {expect}, name


# --------------------------------------------------------------------------- #
# terminate: the dead region exists at low caps and is gone at 8 / 12 / 64
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_terminate_has_a_dead_region_at_low_caps(backend):
    for cap in (1, 2, 4):
        dead, _ = _roi_stats(_render(backend, cap), "stack3")
        assert dead > 0.95, (backend, cap, dead)
    for cap in (8, 12, 64):
        dead, mean = _roi_stats(_render(backend, cap), "stack3")
        assert dead < 0.005 and mean > 0.85, (backend, cap, dead, mean)
