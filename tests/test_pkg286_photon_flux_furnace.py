#!/usr/bin/env python
"""pkg286 — the photon-caustic pre-pass carries physical flux.

A delta sun shines straight down through a clear glass slab (1.6 x 1.6 m,
normal incidence) onto a white Lambertian floor. The slab blocks the shadow
ray and a delta sun cannot be hit by BSDF rays, so under the slab the floor is
lit by the photon gather alone (caustics-only receiver). A slab only shifts the
beam, so the caustic irradiance there is E_sun * T with T = (1 - F0)^2 = 0.9216
(Schlick at normal incidence, the pre-pass Fresnel model), and the deposited
flux integrates to E_sun * A_slab * T (Jensen 2001 §7.1). Before pkg286 the
caustic was pinned to boost / (pi * peak95) of its own map, so none of these
held. `caustic_boost` 1.0 = the physical caustic.
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
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

W, H = 160, 120
SPP = 16
ALBEDO = 0.8
HALF = 0.8                      # slab half-width (m)
T_SLAB = (1.0 - 0.04) ** 2      # Schlick transmittance, two interfaces at normal incidence
PATCH = (slice(60, 74), slice(62, 98))   # floor pixels well inside the slab's shadow
DIRECT = (slice(90, 110), slice(0, W))   # floor pixels lit directly


def _box(r, lo, hi, m):
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    v = [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
         [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]]
    for a, b, c, d in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                       (3, 7, 6, 2), (0, 4, 7, 3), (1, 2, 6, 5)):
        r.add_triangle(v[a], v[b], v[c], m)
        r.add_triangle(v[a], v[c], v[d], m)


def _scene(gpu: bool, strength: float = 1.0):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})
    i0 = r.scene_object_count()
    _box(r, (-HALF, 2.0, -HALF), (HALF, 2.1, HALF), glass)
    for i in range(i0, r.scene_object_count()):
        r.set_object_caustic_caster(i, True)
    floor = r.create_material("lambertian", [ALBEDO] * 3, {})
    r.add_triangle([-4, 0, -4], [4, 0, 4], [4, 0, -4], floor)
    r.add_triangle([-4, 0, -4], [-4, 0, 4], [4, 0, 4], floor)
    r.add_sun_light_dedicated([0.0, -1.0, 0.0], 0.0,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, strength)
    r.set_use_refractive_caustics(True)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 8)
    r.set_integrator_param_float("caustic_boost", 1.0)
    if gpu:
        r.set_use_gpu(True)
        r.set_use_photon_caustics(True)
    else:
        r.set_integrator_param_str("caustics", "photon_map")
    r.setup_camera([0, 1.4, 3.0], [0, 0, 0], [0, 1, 0], 50.0, W / H, 0.0, 4.0, W, H)
    return r


def _render(r, seed=3):
    r.set_seed(seed)
    img = np.asarray(r.render(SPP, 8, None, False), dtype=np.float32).reshape(H, W, 3)
    return img, 0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]


def test_cpu_caustic_flux_matches_analytic(test_results_dir):
    r = _scene(gpu=False)
    img, lum = _render(r)
    from base_helpers import save_image
    save_image(img, os.path.join(test_results_dir, "pkg286_furnace_cpu.png"))
    stats = r.get_integrator_stats()
    patch, direct = float(lum[PATCH].mean()), float(lum[DIRECT].mean())
    e_y = np.pi * direct / ALBEDO                   # sun irradiance (Y) from direct light
    flux_ref = e_y * (2 * HALF) ** 2 * T_SLAB
    print(f"\n[pkg286 CPU] patch={patch:.4f} direct={direct:.4f} ratio={patch/direct:.4f} "
          f"(T={T_SLAB:.4f}) flux={stats['pm_flux_y']:.4f} ref={flux_ref:.4f}")
    assert abs(patch / direct / T_SLAB - 1.0) <= 0.03
    assert abs(stats["pm_flux_y"] / flux_ref - 1.0) <= 0.03


def test_cpu_caustic_linear_in_sun_strength():
    _, l1 = _render(_scene(gpu=False, strength=1.0))
    _, l2 = _render(_scene(gpu=False, strength=2.0))
    ratio = float(l2[PATCH].mean() / l1[PATCH].mean())
    print(f"\n[pkg286 CPU] 2x sun -> caustic x{ratio:.3f}")
    assert abs(ratio - 2.0) <= 0.05


def _gpu_ok():
    return AVAILABLE and astroray.__features__.get("cuda", False) and astroray.Renderer().gpu_available


@pytest.mark.skipif(not _gpu_ok(), reason="CUDA GPU not available")
def test_gpu_caustic_flux_matches_analytic_and_cpu(test_results_dir):
    gimg, g = _render(_scene(gpu=True))
    _, c = _render(_scene(gpu=False))
    from base_helpers import save_image
    save_image(gimg, os.path.join(test_results_dir, "pkg286_furnace_gpu.png"))
    gp, gd, cp = float(g[PATCH].mean()), float(g[DIRECT].mean()), float(c[PATCH].mean())
    print(f"\n[pkg286 GPU] patch={gp:.4f} direct={gd:.4f} ratio={gp/gd:.4f} "
          f"(T={T_SLAB:.4f}) | CPU patch={cp:.4f} GPU/CPU={gp/cp:.4f}")
    assert abs(gp / gd / T_SLAB - 1.0) <= 0.03
    assert abs(gp / cp - 1.0) <= 0.05
    _, g2 = _render(_scene(gpu=True, strength=2.0))
    assert abs(float(g2[PATCH].mean()) / gp - 2.0) <= 0.05
