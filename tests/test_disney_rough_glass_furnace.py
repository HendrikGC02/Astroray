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


def test_disney_rough_glass_furnace_cpu():
    vals = {R: _furnace(R) for R in _ROUGHNESS}
    bad = {R: v for R, v in vals.items() if not (0.95 <= v <= 1.02)}
    assert not bad, f"disney glass furnace not energy-conserving at roughness {bad}; all={vals}"


def test_disney_rough_glass_furnace_deterministic():
    # The fixed value must be deterministic (an MC-noise artifact would change with spp).
    # Per mc-noise-vs-deterministic: compare two spp an order apart at a rough value.
    lo = _furnace(0.3, spp=32)
    hi = _furnace(0.3, spp=256)
    assert abs(lo - hi) < 0.03, f"furnace not converged/deterministic: 32spp={lo:.3f} 256spp={hi:.3f}"


@pytest.mark.skipif(
    AVAILABLE and not astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build")
def test_disney_rough_glass_furnace_gpu():
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")
    vals = {R: _furnace(R, use_gpu=True) for R in [0.0, 0.05, 0.3, 0.6]}
    # GPU vs CPU parity is looser (independent RNG + FMA drift), but it must NOT lose
    # ~70% — every value must be energy-conserving like the CPU path.
    bad = {R: v for R, v in vals.items() if not (0.92 <= v <= 1.05)}
    assert not bad, f"GPU disney glass furnace not energy-conserving at roughness {bad}; all={vals}"
