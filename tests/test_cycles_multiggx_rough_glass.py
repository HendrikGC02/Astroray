"""Rough glass defaults to Cycles 5.2 MULTI_GGX on CPU and GPU (owner decision
2026-10-06): single-scatter GGX glass with Cycles' albedo-scaling energy compensation
(energy_scale = 1/E from the ggx_glass_E tables, both sub-lobes). Shared evaluator:
include/astroray/ggx_glass_energy.h; notes: .astroray_plan/docs/cycles-multiggx-glass-
research.md. The pkg265 Heitz walk stays reachable on the CPU via `rough_glass_walk`.

White furnace: a clear glass sphere in a uniform white world, linear, 80x80, 256 spp,
depth 64, seed 7 (lane i14's furnace_methods.py scene). The reference is Cycles itself,
rendered in Blender 5.2 by lane i14 (2026-10-06, 128-segment smooth UV sphere, Glass
BSDF, MULTI_GGX): Cycles is NOT exactly 1.0 here (table resolution, grazing 1/E), so
the gate is "matches Cycles", with a floor and a ceiling (AGENTS.md furnace rule).

Before this change: the CPU (Heitz walk) read ~1.000 everywhere (+0.04..0.05 over
Cycles at IOR 1.8, r >= 0.75) and the GPU (transmission-only compensation with the
dielectric Fss) read rim 0.41-0.71 at r >= 0.75. After (CPU, 2026-10-06): within
0.008 of Cycles on every row below.
"""
import math

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

_N = 80
_YY, _XX = np.mgrid[:_N, :_N]
_RR = np.hypot(_YY - 39.5, _XX - 39.5)

# (ior, roughness) -> Cycles 5.2 MULTI_GGX (centre, rim), lane i14 furnace_table.md.
_CYCLES = {
    (1.33, 0.50): (1.000, 0.987),
    (1.50, 0.75): (0.988, 0.975),
    (1.50, 1.00): (0.983, 0.981),
    (1.80, 0.50): (0.993, 0.984),
    (1.80, 0.75): (0.972, 0.960),
    (1.80, 1.00): (0.956, 0.951),
}
_TOL = 0.015  # both legs are 256-spp estimates; measured |diff| <= 0.008


def _furnace(ior, rough, *, use_gpu=False, walk=False, spp=256):
    r = astroray.Renderer()
    if use_gpu:
        r.set_use_gpu(True)
    r.set_background_color([1.0, 1.0, 1.0])
    g = r.create_material("principled", [1.0, 1.0, 1.0],
                          {"transmission_weight": 1.0, "ior": ior, "roughness": rough,
                           "rough_glass_walk": 1.0 if walk else 0.0})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, g)
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)  # pkg237: furnace bands need the full budget
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, _N, _N)
    r.set_seed(7)
    img = np.asarray(r.render(spp, 64, None, False),  # linear (apply_gamma=False)
                     dtype=np.float32).reshape(_N, _N, 3).mean(-1)
    return float(img[28:52, 28:52].mean()), float(img[(_RR > 20) & (_RR < 26)].mean())


def _check(ior, rough, centre, rim):
    cc, cr = _CYCLES[(ior, rough)]
    for name, v, ref in (("centre", centre, cc), ("rim", rim, cr)):
        assert 0.93 <= v <= 1.02, f"furnace {name} {v:.4f} outside [0.93, 1.02] (ior {ior}, r {rough})"
        assert abs(v - ref) <= _TOL, (
            f"furnace {name} {v:.4f} vs Cycles MULTI_GGX {ref:.3f} (ior {ior}, r {rough}): "
            f"rough glass is not Cycles' 1/E albedo-scaled single scatter")


@pytest.mark.parametrize("ior,rough", sorted(_CYCLES))
def test_furnace_matches_cycles_multiggx_cpu(ior, rough):
    _check(ior, rough, *_furnace(ior, rough))


@pytest.mark.gpu
@pytest.mark.skipif(AVAILABLE and not astroray.__features__.get("cuda", False),
                    reason="CUDA feature not in this build")
@pytest.mark.parametrize("ior,rough", sorted(_CYCLES))
def test_furnace_matches_cycles_multiggx_gpu(ior, rough):
    """GPU runs the same shared evaluator. RED before: rim 0.41-0.71 at r >= 0.75."""
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")
    _check(ior, rough, *_furnace(ior, rough, use_gpu=True))


def test_walk_option_still_conserves_cpu():
    """The pkg265 Heitz walk stays reachable (rough_glass_walk) and lossless: at
    IOR 1.8 r 1.0, where MULTI_GGX reads ~0.95 like Cycles, the walk reads ~1.0."""
    centre, rim = _furnace(1.8, 1.0, walk=True)
    assert 0.99 <= centre <= 1.01 and 0.99 <= rim <= 1.01, (centre, rim)
    mg_centre, _ = _furnace(1.8, 1.0)
    assert centre - mg_centre >= 0.02, (
        f"walk {centre:.4f} vs default {mg_centre:.4f}: rough_glass_walk not honoured")


def _fibonacci_sphere(n):
    i = np.arange(n) + 0.5
    z = 1.0 - 2.0 * i / n
    phi = i * math.pi * (3.0 - math.sqrt(5.0))
    s = np.sqrt(1.0 - z * z)
    return np.stack([s * np.cos(phi), z, s * np.sin(phi)], axis=1).astype(np.float32)


@pytest.mark.parametrize("front_face", [True, False], ids=["entry", "exit"])
@pytest.mark.parametrize("rough,mu", [(0.5, 0.6), (1.0, 0.3), (1.0, 0.9)])
def test_pdf_matches_sampler_mass_cpu(rough, mu, front_face):
    """pdf() is the density sample() draws from: its integral over the sphere equals
    the sampler's non-lost fraction (Cycles loses wrong-side directions; 1/E restores
    their energy in eval, never in the pdf). A wrong Jacobian, G1 or pdf_reflect
    breaks this and biases MIS."""
    r = astroray.Renderer()
    mid = r.create_material("principled", [1.0, 1.0, 1.0],
                            {"transmission_weight": 1.0, "roughness": rough, "ior": 1.45})
    wo = [math.sqrt(1.0 - mu * mu), mu, 0.0]
    n_s = 200_000
    _, pdf_s = r.debug_bsdf_sample_batch(
        mid, wo, np.zeros((2, n_s), dtype=np.float32), front_face)
    kept = float(np.mean(np.asarray(pdf_s) > 0.0))
    pts = _fibonacci_sphere(2_000_000)
    pdf_q = np.asarray(r.debug_bsdf_pdf_batch(mid, wo, pts, front_face), dtype=np.float64)
    mass = 4.0 * math.pi * float(pdf_q.mean())
    assert 0.5 < kept <= 1.0
    assert abs(mass - kept) <= 0.02, (
        f"integral of pdf {mass:.4f} != sampler kept fraction {kept:.4f} "
        f"(r {rough}, mu {mu}, {'entry' if front_face else 'exit'})")
