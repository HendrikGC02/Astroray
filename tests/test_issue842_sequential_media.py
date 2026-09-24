"""#842 — a ray segment must see EVERY bounded medium on it, not only the nearest.

Fixture: an emissive "fire" box behind a "smoke" box on the camera axis (black
background, no surfaces). Gates (batchU-readiness U2 / #842), CPU and GPU:
  1. the rear fire is visible through the smoke in beauty AND the Emission pass,
     for five fixed nonzero seeds (on main the smoke's AABB hid it: 0);
  2. a ZERO-density front box leaves the rear ROI equal to the no-front
     reference within ±5 % (analytic: a void medium transmits everything);
  3. overlapping media add: two overlapping emissive/absorbing boxes == one box
     with the summed emission and absorption, ±5 % (Cycles volume stack);
  4. CPU/GPU per-channel ROI means of the fire-behind-smoke scene within ±5 %.
Linear renders, per-channel ROI means.
"""

from __future__ import annotations

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

BACKENDS = ["cpu", "gpu"]
SEEDS = (842, 8420, 84201, 842011, 8420111)
W = H = 40
FIRE = dict(aabb_min=[-0.5, -0.5, -2.0], aabb_max=[0.5, 0.5, -1.0])
SMOKE = dict(aabb_min=[-1.2, -1.2, 0.0], aabb_max=[1.2, 1.2, 0.6])


def _gpu_available() -> bool:
    return AVAILABLE and astroray.__features__.get("cuda", False) \
        and astroray.Renderer().gpu_available


def _skip_backend(backend):
    if backend == "gpu" and not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")


def _base(backend, seed):
    r = astroray.Renderer()
    r.set_seed(seed)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_integrator("path_tracer")
    if backend == "gpu":
        r.set_use_gpu(True)
        r.set_gpu_light_path_passes(True)
        r.set_wavelength_range(380.0, 780.0)
        r.set_output_mode("srgb")
    else:
        r.set_use_gpu(False)
    r.setup_camera([0.0, 0.0, 5.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   30.0, W / H, 0.0, 5.0, W, H)
    return r


def _add_fire(r, strength=3.0, density=1.0):
    # Emissive + absorbing (colour 0 => sigma_s = 0; sigma_a = D*(1-sqrt(0.25)) = 0.5 D).
    r.add_homogeneous_medium(**FIRE, density_scale=density, color=[0.0, 0.0, 0.0],
                             absorption_color=[0.25, 0.25, 0.25], emission_strength=strength,
                             emission_color=[1.0, 0.45, 0.1])


def _add_smoke(r, density):
    lamp = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 30.0})
    r.add_sphere([3.0, 3.0, 1.5], 0.5, lamp)          # out of frame
    r.add_homogeneous_medium(**SMOKE, density_scale=density, color=[0.9, 0.9, 0.9],
                             absorption_color=[1.0, 1.0, 1.0], anisotropy=0.2)


def _render(r, spp=64, depth=8):
    img = np.asarray(r.render(spp, depth, None, False, -1, -1, -1, -1, -1), dtype=np.float64)
    return img.reshape(H, W, 3) if img.ndim == 1 else img


def _roi(a):
    # Centre 8x8: the fire box projects to ~±6 px around the centre.
    c = W // 2
    return a[c - 4:c + 4, c - 4:c + 4].reshape(-1, 3).mean(axis=0)


def _pass(r, name):
    return np.asarray(r.get_render_pass_buffer(name), dtype=np.float64).reshape(H, W, 3)


@pytest.mark.parametrize("backend", BACKENDS)
def test_rear_fire_visible_through_smoke(backend):
    _skip_backend(backend)
    for seed in SEEDS:
        r = _base(backend, seed)
        _add_fire(r)
        _add_smoke(r, 0.8)
        beauty = _roi(_render(r, 32))
        emis = _roi(_pass(r, "emission"))
        print(f"\n[#842 fire-through-smoke {backend} seed={seed}] beauty={beauty.round(5)} "
              f"emission_pass={emis.round(5)}")
        # The fire is orange: R carries it. Smoke alone (lit from the side) is grey.
        assert emis[0] > 1e-2, f"rear fire missing from the Emission pass ({backend}, {seed})"
        assert beauty[0] > beauty[2] * 1.2, f"rear fire not visible in beauty: {beauty}"


@pytest.mark.parametrize("backend", BACKENDS)
def test_zero_density_front_volume_is_transparent(backend):
    _skip_backend(backend)
    ref = _base(backend, SEEDS[0])
    _add_fire(ref)
    a = _roi(_render(ref, 128))
    ctl = _base(backend, SEEDS[0])
    _add_fire(ctl)
    ctl.add_homogeneous_medium(**SMOKE, density_scale=0.0)
    b = _roi(_render(ctl, 128))
    ratio = b / np.maximum(a, 1e-9)
    print(f"\n[#842 zero-density front {backend}] no-front={a.round(5)} "
          f"zero-front={b.round(5)} ratio={ratio.round(4)}")
    assert a[0] > 0.05, f"fire fixture renders black: {a}"
    for c in range(3):
        if a[c] > 1e-3:
            assert 0.95 <= ratio[c] <= 1.05, (c, ratio, a, b)


@pytest.mark.parametrize("backend", BACKENDS)
def test_overlapping_media_add(backend):
    _skip_backend(backend)
    merged = _base(backend, SEEDS[1])
    # sigma_a = 0.5 (0.25 -> sqrt 0.5), emission 3.0
    merged.add_homogeneous_medium(**FIRE, density_scale=1.0, color=[0.0, 0.0, 0.0],
                                  absorption_color=[0.25, 0.25, 0.25], emission_strength=3.0,
                                  emission_color=[1.0, 0.45, 0.1])
    a = _roi(_render(merged, 128))
    split = _base(backend, SEEDS[1])
    # 0.3 + 0.2 absorption (sqrt(ac) = 0.7 / 0.8), 1.0 + 2.0 emission, same box.
    split.add_homogeneous_medium(**FIRE, density_scale=1.0, color=[0.0, 0.0, 0.0],
                                 absorption_color=[0.49, 0.49, 0.49], emission_strength=1.0,
                                 emission_color=[1.0, 0.45, 0.1])
    split.add_homogeneous_medium(**FIRE, density_scale=1.0, color=[0.0, 0.0, 0.0],
                                 absorption_color=[0.64, 0.64, 0.64], emission_strength=2.0,
                                 emission_color=[1.0, 0.45, 0.1])
    b = _roi(_render(split, 128))
    ratio = b / np.maximum(a, 1e-9)
    print(f"\n[#842 overlap {backend}] merged={a.round(5)} split={b.round(5)} "
          f"ratio={ratio.round(4)}")
    for c in range(3):
        if a[c] > 1e-3:
            assert 0.95 <= ratio[c] <= 1.05, (c, ratio, a, b)


def test_gpu_cpu_parity_fire_behind_smoke():
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    out = {}
    for backend in BACKENDS:
        acc = np.zeros(3)
        for seed in SEEDS:
            r = _base(backend, seed)
            _add_fire(r)
            _add_smoke(r, 0.8)
            acc += _roi(_render(r, 128))
        out[backend] = acc / len(SEEDS)
    ratio = out["gpu"] / np.maximum(out["cpu"], 1e-9)
    print(f"\n[#842 parity] CPU={out['cpu'].round(5)} GPU={out['gpu'].round(5)} "
          f"GPU/CPU={ratio.round(4)}")
    for c in range(3):
        assert 0.95 <= ratio[c] <= 1.05, (c, ratio, out)
