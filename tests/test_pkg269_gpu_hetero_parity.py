"""pkg269 — GPU wavefront heterogeneous / bounded volume stage: CPU↔GPU parity.

Gates (spec acceptance):
  * PARITY (GPU) — per-channel ROI mean-ratio GPU/CPU within ±5 % (widened to the
    MC-noise band documented per test) on (a) a homogeneous bounded chromatic
    absorption slab (analytic-free Beer–Lambert cross-check), (b) a heterogeneous
    NanoVDB density grid lit by a mesh emitter (in-scatter + medium NEE through
    the deferred shadow stage), (c) a constant-emission slab (pkg270 emission on
    the GPU). Per-channel mean-ratio, NOT SSIM (independent MC streams — memory
    ssim-wrong-gate-for-independent-rng). Linear (`apply_gamma=False`).
  * MEDIA-FREE BYTE-IDENTITY (GPU) — registering then clearing media renders
    bit-identically to never registering (the c_wfGridVolume count==0 path).
  * VISUAL (GPU) — the heterogeneous smoke saved to PNG for inspection.

GPU legs skip when CUDA is absent (CI has no GPU); the RTX sweep runs them.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

SEED = 269269
_OUT = os.path.join(os.path.dirname(__file__), "..", "test_results", "batchK")


def _gpu_available() -> bool:
    return AVAILABLE and astroray.__features__.get("cuda", False) \
        and astroray.Renderer().gpu_available


def _render(r, spp, max_depth, w, h):
    img = np.asarray(r.render(spp, max_depth, None, False), dtype=np.float64)
    if img.ndim == 1:
        img = img.reshape(h, w, 3)
    return img


def _base(use_gpu, w, h, max_depth):
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", max_depth)
    if use_gpu:
        r.set_use_gpu(True)
        r.set_wavelength_range(380.0, 780.0)
        r.set_output_mode("srgb")
    else:
        r.set_use_gpu(False)
    return r


# --------------------------------------------------------------------------- #
# (a) homogeneous chromatic absorption slab in front of an emissive wall
# --------------------------------------------------------------------------- #

def _abs_scene(use_gpu, with_medium, w=32, h=32, dist=6.0, near=-4.0, far=-3.5):
    r = _base(use_gpu, w, h, 2)
    wall = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 1.0})
    r.add_triangle([-20, -20, -dist], [20, -20, -dist], [20, 20, -dist], wall)
    r.add_triangle([-20, -20, -dist], [20, 20, -dist], [-20, 20, -dist], wall)
    if with_medium:
        C = [0.85, 0.25, 0.20]   # the #807 Volume Absorption colour
        r.add_homogeneous_medium([-10.0, -10.0, near], [10.0, 10.0, far],
                                 5.0, [0.0, 0.0, 0.0], [c * c for c in C], 0.0)
    r.setup_camera([0.0, 0.0, 0.001], [0.0, 0.0, -dist], [0.0, 1.0, 0.0],
                   20.0, w / h, 0.0, dist, w, h)
    return r


def _center(img, half=6):
    h, w = img.shape[:2]
    return img[h // 2 - half:h // 2 + half, w // 2 - half:w // 2 + half, :].reshape(-1, 3).mean(axis=0)


def test_gpu_chromatic_absorption_slab_parity():
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    cpu_clear = _center(_render(_abs_scene(False, False), 128, 2, 32, 32))
    gpu_clear = _center(_render(_abs_scene(True, False), 128, 2, 32, 32))
    cpu = _center(_render(_abs_scene(False, True), 1024, 2, 32, 32)) / np.maximum(cpu_clear, 1e-9)
    gpu = _center(_render(_abs_scene(True, True), 1024, 2, 32, 32)) / np.maximum(gpu_clear, 1e-9)
    cycles = np.exp(-(1.0 - np.array([0.85, 0.25, 0.20])) * 5.0 * 0.5)
    ratio = gpu / np.maximum(cpu, 1e-9)
    print(f"\n[pkg269 abs slab] Tr CPU={cpu.round(4)} GPU={gpu.round(4)} GPU/CPU={ratio.round(4)} "
          f"cycles={cycles.round(4)}")
    for c in range(3):
        assert 0.95 <= ratio[c] <= 1.05, (c, ratio, cpu, gpu)
    assert gpu[0] > 2.5 * gpu[2], "GPU extinction not chromatic"


# --------------------------------------------------------------------------- #
# (b) heterogeneous NanoVDB smoke (synthetic density) lit by a mesh emitter
# --------------------------------------------------------------------------- #

def _smoke_density(n=24):
    z, y, x = np.mgrid[0:n, 0:n, 0:n].astype(np.float32)
    c = (n - 1) / 2.0
    r2 = ((x - c) ** 2 + (y - c) ** 2 + (z - c) ** 2) / (c * c)
    dens = np.clip(1.0 - r2, 0.0, 1.0) * (0.6 + 0.4 * np.sin(x * 0.8) * np.cos(y * 0.6))
    return np.ascontiguousarray(dens.astype(np.float32))


def _smoke_scene(use_gpu, with_medium, w=48, h=48):
    r = _base(use_gpu, w, h, 6)
    lamp = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 30.0})
    r.add_sphere([2.5, 3.0, 2.0], 0.6, lamp)
    floor = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
    r.add_triangle([-6, -1.2, -6], [6, -1.2, -6], [6, -1.2, 6], floor)
    r.add_triangle([-6, -1.2, -6], [6, -1.2, 6], [-6, -1.2, 6], floor)
    if with_medium:
        n = 24
        vox = 2.0 / n   # a 2-unit cube centred at the origin
        i2o = [vox, 0, 0, -1.0, 0, vox, 0, -1.0, 0, 0, vox, -1.0, 0, 0, 0, 1]
        o2w = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        r.set_volume_grid("smoke", _smoke_density(n), [0, 0, 0], i2o, o2w,
                          density_scale=6.0, color=[0.9, 0.7, 0.5],
                          absorption_color=[1.0, 1.0, 1.0], anisotropy=0.3)
    r.setup_camera([0.0, 0.6, 5.5], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   32.0, w / h, 0.0, 5.5, w, h)
    return r


def test_gpu_heterogeneous_smoke_parity_and_visual():
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    from base_helpers import save_image
    os.makedirs(_OUT, exist_ok=True)
    w = h = 48
    cpu = _render(_smoke_scene(False, True, w, h), 256, 6, w, h)
    gpu = _render(_smoke_scene(True, True, w, h), 256, 6, w, h)
    save_image(cpu, os.path.join(_OUT, "pkg269_smoke_cpu.png"))
    save_image(gpu, os.path.join(_OUT, "pkg269_smoke_gpu.png"))
    # ROI = the smoke's projected footprint (centre 24x24).
    roi_c = _center(cpu, 12)
    roi_g = _center(gpu, 12)
    ratio = roi_g / np.maximum(roi_c, 1e-9)
    print(f"\n[pkg269 smoke] ROI CPU={roi_c.round(4)} GPU={roi_g.round(4)} GPU/CPU={ratio.round(4)}")
    assert roi_c.max() > 0.01, "CPU smoke is black"
    for c in range(3):
        assert 0.95 <= ratio[c] <= 1.05, (c, ratio, roi_c, roi_g)


# --------------------------------------------------------------------------- #
# (c) constant-emission slab (pkg270 emission on the GPU stage)
# --------------------------------------------------------------------------- #

def _emis_scene(use_gpu, w=24, h=24, dist=6.0, near=-4.0, far=-2.0):
    r = _base(use_gpu, w, h, 2)
    r.add_homogeneous_medium([-10.0, -10.0, near], [10.0, 10.0, far],
                             0.0, [0.0, 0.0, 0.0], [1.0, 1.0, 1.0], 0.0,
                             emission_strength=1.4, emission_color=[1.0, 0.45, 0.10])
    r.setup_camera([0.0, 0.0, 0.001], [0.0, 0.0, -dist], [0.0, 1.0, 0.0],
                   20.0, w / h, 0.0, dist, w, h)
    return r


def test_gpu_constant_emission_slab_parity():
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    cpu = _center(_render(_emis_scene(False), 1024, 2, 24, 24), 3)
    gpu = _center(_render(_emis_scene(True), 1024, 2, 24, 24), 3)
    expected = np.array([1.0, 0.45, 0.10]) * 1.4 * 2.0
    ratio = gpu / np.maximum(cpu, 1e-9)
    print(f"\n[pkg269 emission] CPU={cpu.round(4)} GPU={gpu.round(4)} GPU/CPU={ratio.round(4)} "
          f"expected={expected.round(4)}")
    for c in range(3):
        assert 0.95 <= ratio[c] <= 1.05, (c, ratio)
        assert expected[c] * 0.85 <= gpu[c] <= expected[c] * 1.15, (c, gpu, expected)


# --------------------------------------------------------------------------- #
# media-free byte-identity on the GPU (count==0 path)
# --------------------------------------------------------------------------- #

def test_gpu_media_free_render_is_bit_identical():
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    a = _render(_smoke_scene(True, False), 32, 6, 32, 32)
    r = _smoke_scene(True, False, 32, 32)
    r.add_homogeneous_medium([-1, -1, -1], [1, 1, 1], 2.0, [0.5, 0.5, 0.5], [1, 1, 1], 0.0)
    r.clear_grid_media()
    b = _render(r, 32, 6, 32, 32)
    assert np.array_equal(a, b)
    assert a.max() > 0.0
