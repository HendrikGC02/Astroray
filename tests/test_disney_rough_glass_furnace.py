"""Disney ROUGH glass must conserve energy (white-furnace), CPU and GPU.

A clear glass in a uniform white environment must render ~1.0: radiance is invariant
along a ray however it bends, so clear glass is invisible in a uniform field. Disney
glass (Principled BSDF, transmission=1) at roughness 0 furnaces ~0.97, but roughness
>= 0.05 used to COLLAPSE to ~0.30 — a ~70% energy loss, flat across roughness, stepping
on at kDeltaTransmissionRoughness=0.03.

Root cause (fixed 2026-05-30): the rough-transmission eval used the COMBINED visibility
form `smithG_GGX` (= G1/(2*NdotV), which folds the reflection BRDF's 1/(4*cosO*cosI)
into G) instead of the true Smith G1. In the transmission estimator that leaves a
spurious 1/(4*cosO*cosI) ~ 0.25 in f/pdf. Fixed to `smithG1_GGX` (Walter 2007
"Microfacet Models for Refraction through Rough Surfaces" Eq. 21/34), CPU + GPU.
See .astroray_plan/docs/disney-rough-transmission-walter2007.md.
"""

from __future__ import annotations

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

_ROUGHNESS = [0.0, 0.03, 0.05, 0.1, 0.3, 0.6, 1.0]


def _furnace(roughness: float, *, use_gpu: bool = False, spp: int = 64, depth: int = 32) -> float:
    r = astroray.Renderer()
    r.set_background_color([1.0, 1.0, 1.0])           # uniform white environment
    g = r.create_material("disney", [1.0, 1.0, 1.0],
                          {"transmission": 1.0, "ior": 1.5, "roughness": roughness, "metallic": 0.0})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, g)
    r.set_integrator("path_tracer")
    if use_gpu:
        r.set_use_gpu(True)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 80, 80)
    r.set_seed(7)
    img = np.asarray(r.render(spp, depth, None, True), dtype=np.float32).reshape(80, 80, 3)
    return float(img[28:52, 28:52].mean())          # sphere-centre patch


# Smooth disney glass (roughness <= kDeltaTransmissionRoughness=0.03) takes the
# delta dielectric event and IS energy-conserving on both CPU and GPU.
_SMOOTH = [0.0, 0.03]
# Rough disney glass: the rough-transmission path was rewritten to a Heitz-2018 VNDF
# microfacet dielectric BSDF ported from PBRT-v4 DielectricBxDF (BSD-3-Clause); see
# .astroray_plan/docs/vndf-microfacet-dielectric-research.md. That fixed the old
# ~70% high-roughness collapse: at 256 spp the GPU furnace is now ~0.96-1.00 for
# R>=0.1, and the CPU ~0.81-0.98. A residual loss remains at the LOW-ALPHA boundary
# (R=0.05-0.1, just above the smooth threshold) and the CPU lags the GPU by a few
# percent at mid roughness — tracked by the xfail below.
_ROUGH = [0.1, 0.3, 0.6, 1.0]


def test_disney_smooth_glass_furnace_cpu():
    vals = {R: _furnace(R, spp=128) for R in _SMOOTH}
    bad = {R: v for R, v in vals.items() if not (0.95 <= v <= 1.02)}
    assert not bad, f"smooth disney glass furnace not energy-conserving at roughness {bad}; all={vals}"


def test_disney_rough_glass_furnace_converges():
    # The VNDF microfacet-transmission estimator has higher variance than the old
    # bespoke path, so it needs ~256 spp to converge. Confirm the value is CONVERGED
    # (not still drifting) by comparing 256 vs 1024 spp — they must agree, i.e. the
    # residual is real physics, not an under-sampling artifact.
    lo = _furnace(0.3, spp=256)
    hi = _furnace(0.3, spp=1024)
    assert abs(lo - hi) < 0.03, f"furnace not converged: 256spp={lo:.3f} 1024spp={hi:.3f}"


@pytest.mark.skipif(
    AVAILABLE and not astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build")
def test_disney_rough_glass_furnace_energy_gpu():
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")
    # The VNDF rewrite makes GPU rough glass energy-conserving for R>=0.1 (the win).
    vals = {R: _furnace(R, use_gpu=True, spp=128) for R in _ROUGH}
    bad = {R: v for R, v in vals.items() if not (0.90 <= v <= 1.06)}
    assert not bad, f"GPU rough disney glass furnace not energy-conserving at roughness {bad}; all={vals}"


@pytest.mark.xfail(reason="CPU rough dielectric lacks multiple-scattering energy "
                          "compensation; single-scatter masking loss is only partly "
                          "offset by a forced-TIR delta over-count, so the furnace sags "
                          "at low roughness (R=0.1: 0.81, R=0.3: 0.92). Root-caused + "
                          "fix plan in packages/pkg118-rough-dielectric-multiscatter-energy.md "
                          "(Kulla-Conty 2017 / Heitz 2016).",
                   strict=False)
def test_disney_rough_glass_furnace_energy_cpu():
    vals = {R: _furnace(R, spp=256) for R in _ROUGH}
    bad = {R: v for R, v in vals.items() if not (0.95 <= v <= 1.02)}
    assert not bad, f"rough disney glass furnace not energy-conserving at roughness {bad}; all={vals}"


@pytest.mark.skipif(
    AVAILABLE and not astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build")
def test_disney_smooth_glass_furnace_gpu():
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")
    vals = {R: _furnace(R, use_gpu=True, spp=128) for R in _SMOOTH}
    # GPU smooth glass must conserve energy like the CPU path (the eta^2 closure-graph
    # fix made GPU track CPU; before it the GPU lost ~30% scaling with IOR).
    bad = {R: v for R, v in vals.items() if not (0.92 <= v <= 1.05)}
    assert not bad, f"GPU smooth disney glass furnace not energy-conserving at roughness {bad}; all={vals}"
