"""pkg289 (#913): spot-light shaft variance in a homogeneous fog box.

Fixture: 64x64 camera view of a spot (color 0.6/0.75/1.0, 12 kW) shining down
through a bounded homogeneous Principled fog (grey 0.5, black absorption,
density 0.08, g 0.5) onto a dark floor. The box extends below the floor (a
coplanar box/floor face is a separate edge case). Cycles twin: Blender 5.2,
12 seeds x 64 spp, script astra_run/batchU/ae2/cycles_shaft.py; its numbers are
committed below. Ladder + verdict: .astroray_plan/docs/pkg289-medium-chromatic-noise-ladder.md.

Metric: per-pixel normalized variance var/mean^2 over K seeds, averaged over a
fixed in-cone ROI, per channel.
"""
import math

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

astroray = pytest.importorskip("astroray")

_RES = 64
_ROI = (slice(16, 40), slice(37, 44))
_K = 12
# Cycles 5.2 twin, 64 spp, same ROI (R, G, B).
_CYCLES_NV64 = np.array([0.00516, 0.00500, 0.00485])
_CYCLES_ROI_MEAN = np.array([0.0474, 0.0590, 0.0784])
_NV_FACTOR = 4.0


def _render(gpu, spp, seed):
    r = astroray.Renderer()
    if gpu:
        try:
            r.set_use_gpu(True)
        except Exception as e:  # noqa: BLE001 - CPU-only build
            pytest.skip("GPU unavailable: %s" % e)
        if not getattr(r, "gpu_available", False):
            pytest.skip("gpu_available is False")
    elif hasattr(r, "set_use_gpu"):
        r.set_use_gpu(False)
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)
    r.set_background_color([0.0, 0.0, 0.0])
    g = r.create_material("lambertian", [0.12, 0.11, 0.10], {})
    r.add_triangle([-20, -20, 0], [20, -20, 0], [20, 20, 0], g)
    r.add_triangle([-20, -20, 0], [20, 20, 0], [-20, 20, 0], g)
    r.add_homogeneous_medium([-4, -4, -1], [4, 4, 5], 0.08, [0.5, 0.5, 0.5],
                             [0.0, 0.0, 0.0], 0.5)
    r.add_spot_light_dedicated([1.0, 1.0, 7.5], [0, 0, -1], 0.15, 0.19,
                               {"mode": "rgb", "color": [0.6, 0.75, 1.0]}, 12000.0, 0.0)
    r.setup_camera([0, -10, 2.0], [0, 0, 2.0], [0, 0, 1], 40.0, 1.0, 0.0, 10.0,
                   _RES, _RES)
    r.set_seed(seed)
    img = np.asarray(r.render(spp, 8, None, False), dtype=np.float64)
    return img.reshape(_RES, _RES, 3)


def _roi_stats(gpu, spp):
    px = np.stack([_render(gpu, spp, 1000 + s)[_ROI] for s in range(_K)])
    px = px.reshape(_K, -1, 3)
    mu = px.mean(0)
    nv = (px.var(0, ddof=1) / np.maximum(mu, 1e-12) ** 2).mean(0)
    return nv, px.mean((0, 1))


def _assert_converges(gpu):
    nvs = {spp: _roi_stats(gpu, spp) for spp in (16, 64, 256)}
    for c in range(3):
        slope = math.log(nvs[256][0][c] / nvs[16][0][c]) / math.log(256 / 16)
        assert abs(slope + 1.0) <= 0.15, (c, slope, nvs)
    # Unbiased vs the Cycles twin (256 spp x 12 seeds).
    np.testing.assert_allclose(nvs[256][1], _CYCLES_ROI_MEAN, rtol=0.06)


def _assert_variance_vs_cycles(gpu):
    nv, _ = _roi_stats(gpu, 64)
    assert np.all(nv <= _NV_FACTOR * _CYCLES_NV64), (
        f"shaft normalized variance {nv} vs Cycles {_CYCLES_NV64} "
        f"(ratio {nv / _CYCLES_NV64})")


@pytest.mark.cpu
def test_913_shaft_variance_converges_cpu():
    _assert_converges(False)


@pytest.mark.gpu
def test_913_shaft_variance_converges_gpu():
    _assert_converges(True)


_XFAIL = pytest.mark.xfail(
    strict=True,
    reason="#913: medium direct light is sampled only at analog scatter vertices "
           "(~100-500x Cycles' variance); needs per-segment equiangular+distance "
           "NEE (Kulla & Fajardo 2012, Cycles shade_volume.h). Tracked in #925; fix PR un-xfails.")


@pytest.mark.cpu
@_XFAIL
def test_913_shaft_variance_vs_cycles_cpu():
    _assert_variance_vs_cycles(False)


@pytest.mark.gpu
@_XFAIL
def test_913_shaft_variance_vs_cycles_gpu():
    _assert_variance_vs_cycles(True)
