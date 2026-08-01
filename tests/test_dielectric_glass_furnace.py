"""Smooth dielectric glass must conserve energy (white-furnace), CPU and GPU.

A clear glass sphere in a uniform white environment must render ~1.0: radiance is
invariant along a ray however it bends, so clear glass is invisible in a uniform
field. Any deficit = lost energy.

Root cause fixed 2026-05-30 (GPU only): a plain `dielectric` material lowers to
GMAT_CLOSURE_GRAPH on the GPU, and its delta refraction f = baseColor*eta^2 was
routed through gpu_rgbToSampledSpectrum in GSPEC_RGB_ALBEDO mode, whose JH
upsampler CLAMPS rgb to [0,1]. The exit eta^2 (2.25 @ ior 1.5, 4.0 @ ior 2.0) was
clipped to 1.0, so the enter (0.44) and exit (2.25) radiance-transport factors no
longer cancelled — the GPU furnace lost energy SCALING WITH IOR (0.705 @ ior 1.5,
0.604 @ ior 2.0) while the CPU stayed ~0.985. Fixed in gpu_material_sample_spectral
by factoring any >1 delta-lobe magnitude out as a flat spectral scalar and
upsampling only the normalized tint (mirrors CPU dielectric.cpp:72, tintSpec*eta^2).
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

# eta^2 grows with IOR (2.25 @ 1.5, 4.0 @ 2.0) — the clamp bug got worse with IOR,
# so the sweep deliberately spans low to high IOR.
_IORS = [1.0, 1.1, 1.5, 2.0]


def _furnace(ior: float, *, use_gpu: bool = False, spp: int = 64, depth: int = 32) -> float:
    r = astroray.Renderer()
    r.set_background_color([1.0, 1.0, 1.0])           # uniform white environment
    g = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": ior})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, g)
    r.set_integrator("path_tracer")
    if use_gpu:
        r.set_use_gpu(True)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 80, 80)
    r.set_seed(7)
    # pkg166: render LINEAR (4th arg apply_gamma=False). A gamma furnace clamps
    # to [0,1] and can only ever detect energy LOSS, never GAIN. At albedo 1 in
    # a radiance-1 field the target is 1.0, where gamma is a no-op, so the bands
    # below are unchanged from the gamma pins — but the suite is no longer blind
    # to an IOR-dependent energy GAIN above 1.0.
    img = np.asarray(r.render(spp, depth, None, False), dtype=np.float32).reshape(80, 80, 3)
    return float(img[28:52, 28:52].mean())          # sphere-centre patch


def test_dielectric_glass_furnace_cpu():
    vals = {ior: _furnace(ior) for ior in _IORS}
    bad = {ior: v for ior, v in vals.items() if not (0.95 <= v <= 1.05)}
    assert not bad, f"clear glass furnace not energy-conserving at ior {bad}; all={vals}"


@pytest.mark.skipif(
    AVAILABLE and not astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build")
def test_dielectric_glass_furnace_gpu():
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")
    vals = {ior: _furnace(ior, use_gpu=True) for ior in _IORS}
    # The IOR-scaling deficit (0.705 @ 1.5, 0.604 @ 2.0) must be gone: every value
    # energy-conserving, and crucially NOT decreasing as IOR climbs.
    bad = {ior: v for ior, v in vals.items() if not (0.95 <= v <= 1.05)}
    assert not bad, f"GPU clear glass furnace not energy-conserving at ior {bad}; all={vals}"
    assert vals[2.0] >= 0.95, f"GPU furnace still loses energy at high IOR: {vals}"
