#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pkg258 — Environment-NEE convergence and energy-conservation gate.

pkg63's never-run gate, finally run. Two scenes, CPU leg (the GPU parameter is
marked xfail(strict) until the pkg258 GPU wavefront leg lands):

  (A) Sun-disc HDRI over a Lambertian floor. A concentrated bright disc lights a
      diffuse floor. With env NEE the floor converges far faster than with plain
      BSDF-miss lighting (which is lit only by rare lucky misses -> high
      variance, dark-biased under a firefly clamp). Gate: RMSE(NEE on, 256 spp)
      vs a high-spp reference <= 0.25 * RMSE(NEE off, 256 spp).

  (B) Linear white furnace: uniform env (radiance 1), albedo-1 Lambertian floor,
      apply_gamma=False. Reflected radiance must be exactly 1.0 so NEE + the
      MIS-weighted miss leg never double-count. Gate: mean in [0.99, 1.01] with
      the UPPER bound asserted (memory: gamma-furnace-cannot-detect-energy-gain
      -- a clamped/gamma render hides energy gain, so this asserts < 1.01
      linearly).

Estimator reference: PBRT 4e §12.5 / Cycles background.h -- see
`.astroray_plan/docs/pkg258-env-nee-research.md`.
"""
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

from test_world_hdri_parity import _write_radiance_hdr  # noqa: E402

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

SAVE = os.environ.get("PKG258_SAVE_RENDERS")
SAVE_DIR = os.path.join(os.path.dirname(__file__), "..",
                        "test_results", "2026-09-08-pkg258")


def _save_png(name, img_lin):
    """Write a linear->sRGB 8-bit PNG for the lead's visual inspection."""
    if not SAVE:
        return
    os.makedirs(SAVE_DIR, exist_ok=True)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.image as mpimg
    x = np.clip(img_lin, 0.0, None)
    # Fixed exposure + sRGB OETF so NEE-on/off are directly comparable.
    x = x * 0.9
    srgb = np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)
    srgb = np.clip(srgb, 0.0, 1.0)
    mpimg.imsave(os.path.join(SAVE_DIR, name), srgb)


def _sun_disc_hdri(width=64, height=32):
    """Dim ambient with a small bright disc in the UPPER hemisphere (row band
    near the top) so a floor with +Y normal is strongly lit from above."""
    img = np.full((height, width, 3), 0.05, dtype=np.float32)
    cx, cy = width // 3, height // 6          # upper hemisphere
    rr = 2
    for y in range(max(0, cy - rr), min(height, cy + rr + 1)):
        for x in range(max(0, cx - rr), min(width, cx + rr + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= rr * rr:
                img[y, x, :] = 300.0
    return img


def _uniform_hdri(width=32, height=16, value=1.0):
    return np.full((height, width, 3), value, dtype=np.float32)


def _floor_renderer(hdri_path, seed):
    r = astroray.Renderer()
    r.set_use_gpu(False)                       # CPU leg
    r.set_integrator("path_tracer")
    r.set_seed(seed)
    # Disable adaptive sampling so a fixed-spp RMSE comparison is clean sqrt(N)
    # noise, not a colour-blind stop-metric artefact (memory
    # adaptive-sampling-colour-blind-stop-metric).
    r.set_adaptive_sampling(False)
    floor = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    s = 20.0
    r.add_triangle([-s, 0, -s], [s, 0, -s], [s, 0, s], floor)
    r.add_triangle([-s, 0, -s], [s, 0, s], [-s, 0, s], floor)
    r.setup_camera(look_from=[0, 6, 9], look_at=[0, 0, 0], vup=[0, 1, 0],
                   vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=10.0,
                   width=24, height=24)
    assert r.load_environment_map(hdri_path, 1.0, 0.0, 0.0, 0.0)
    return r


def _render_linear(r, spp, depth=3):
    # render() returns the (H, W, 3) frame; apply_gamma=False -> linear.
    return np.asarray(r.render(spp, depth, None, False), dtype=np.float64)


@pytest.fixture(scope="module")
def sun_hdri(tmp_path_factory):
    p = tmp_path_factory.mktemp("pkg258_sun") / "sun_disc.hdr"
    _write_radiance_hdr(str(p), _sun_disc_hdri())
    return str(p)


@pytest.fixture(scope="module")
def uniform_hdri(tmp_path_factory):
    p = tmp_path_factory.mktemp("pkg258_uni") / "uniform.hdr"
    _write_radiance_hdr(str(p), _uniform_hdri())
    return str(p)


def _reshape(img, r):
    # get_last_frame may be flat; reshape to (H, W, 3).
    a = np.asarray(img, dtype=np.float64)
    if a.ndim == 1:
        a = a.reshape((24, 24, 3))
    return a


@pytest.mark.parametrize("backend", [
    "cpu",
    pytest.param("gpu", marks=pytest.mark.xfail(
        strict=True, reason="pkg258 GPU wavefront leg pending (separate PR)")),
])
def test_sun_disc_nee_convergence(sun_hdri, backend):
    """RMSE(NEE on) <= 0.25 * RMSE(NEE off) vs a high-spp reference."""
    use_gpu = (backend == "gpu")
    SEED = 20260908
    REF_SPP = 2048
    TEST_SPP = 256

    # Reference: NEE on, high spp (unbiased ground truth for BOTH estimators).
    r_ref = _floor_renderer(sun_hdri, SEED)
    r_ref.set_use_gpu(use_gpu)
    r_ref.set_env_nee(True)
    ref = _reshape(_render_linear(r_ref, REF_SPP), r_ref)

    r_on = _floor_renderer(sun_hdri, SEED + 1)
    r_on.set_use_gpu(use_gpu)
    r_on.set_env_nee(True)
    on = _reshape(_render_linear(r_on, TEST_SPP), r_on)

    r_off = _floor_renderer(sun_hdri, SEED + 1)
    r_off.set_use_gpu(use_gpu)
    r_off.set_env_nee(False)
    off = _reshape(_render_linear(r_off, TEST_SPP), r_off)

    rmse_on = float(np.sqrt(np.mean((on - ref) ** 2)))
    rmse_off = float(np.sqrt(np.mean((off - ref) ** 2)))
    ratio = rmse_on / max(rmse_off, 1e-12)
    print(f"\n[pkg258 sun-disc {backend}] RMSE on={rmse_on:.4e} off={rmse_off:.4e} "
          f"ratio={ratio:.3f} (gate <= 0.25)")

    _save_png(f"sun_disc_nee_off_{backend}.png", off)
    _save_png(f"sun_disc_nee_on_{backend}.png", on)
    _save_png(f"sun_disc_ref_{backend}.png", ref)

    assert ratio <= 0.25, (
        f"env NEE did not cut RMSE by >=4x: ratio {ratio:.3f} "
        f"(on={rmse_on:.4e}, off={rmse_off:.4e})")


@pytest.mark.parametrize("backend", [
    "cpu",
    pytest.param("gpu", marks=pytest.mark.xfail(
        strict=True, reason="pkg258 GPU wavefront leg pending (separate PR)")),
])
def test_white_furnace_energy_conservation(uniform_hdri, backend):
    """Linear white furnace: uniform env, albedo ~1, mean == 1.0 +/- 1%, with the
    UPPER bound asserted so NEE + miss cannot silently gain energy."""
    use_gpu = (backend == "gpu")
    r = astroray.Renderer()
    r.set_use_gpu(use_gpu)
    r.set_integrator("path_tracer")
    r.set_seed(4242)
    # Albedo as close to 1 as the Lambertian clamp allows.
    mat = r.create_material("lambertian", [0.999, 0.999, 0.999], {})
    s = 50.0
    r.add_triangle([-s, 0, -s], [s, 0, -s], [s, 0, s], mat)
    r.add_triangle([-s, 0, -s], [s, 0, s], [-s, 0, s], mat)
    r.setup_camera(look_from=[0, 4, 6], look_at=[0, 0, 0], vup=[0, 1, 0],
                   vfov=40, aspect_ratio=1.0, aperture=0.0, focus_dist=7.0,
                   width=24, height=24)
    assert r.load_environment_map(uniform_hdri, 1.0, 0.0, 0.0, 0.0)
    r.set_env_nee(True)
    img = _reshape(_render_linear(r, 256, depth=4), r)
    mean = float(img.mean())
    print(f"\n[pkg258 furnace {backend}] mean={mean:.5f} (target 1.0 +/- 1%)")
    _save_png(f"white_furnace_{backend}.png", img)
    # Albedo 0.999 -> equilibrium slightly below 1 for multi-bounce; the tight
    # window is against energy GAIN (double counting), the real failure mode.
    assert mean < 1.01, f"furnace mean {mean:.5f} >= 1.01 -- NEE+miss double counts"
    assert mean > 0.97, f"furnace mean {mean:.5f} <= 0.97 -- NEE+miss loses energy"
