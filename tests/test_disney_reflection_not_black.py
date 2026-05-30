"""Disney specular/metallic REFLECTION must not render black, CPU and GPU.

Regression guard for the VNDF-rewrite bug (fixed 2026-05-30): the CPU disney
specular reflection lobe in sample() was switched to VNDF micronormal sampling while
its pdf() still returned the NDF spec density. The VNDF normal produced below-surface
reflection directions (NdotL<=0), so f/pdf stayed 0 and the path terminated — disney
metal/plastic rendered PURE BLACK on CPU (centre luminance 0.000 in a uniform grey
field) while the plain `metal` material reflected normally (~0.6-0.72). The glass
white-furnace did NOT catch it (it exercises the transmission path, not reflection).

A metallic sphere in a uniform grey [0.5] environment must reflect that environment —
its centre luminance must be a substantial fraction of what the plain `metal` material
produces at the same roughness/colour, and must NOT be ~0.
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

_ROUGHNESS = [0.05, 0.22, 0.45]
_GOLD = [0.9, 0.68, 0.25]


def _centre_lum(mat_type: str, params: dict, *, use_gpu: bool = False) -> float:
    r = astroray.Renderer()
    r.set_background_color([0.5, 0.5, 0.5])           # uniform grey environment
    m = r.create_material(mat_type, _GOLD, dict(params))
    r.add_sphere([0.0, 0.0, 0.0], 1.0, m)
    r.set_integrator("path_tracer")
    if use_gpu:
        r.set_use_gpu(True)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 96, 96)
    r.set_seed(7)
    img = np.asarray(r.render(64, 8, None, True), dtype=np.float32).reshape(96, 96, 3)
    lum = 0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2]
    return float(lum[36:60, 36:60].mean())


def _check(use_gpu: bool):
    bad = {}
    for R in _ROUGHNESS:
        disney = _centre_lum("disney", {"metallic": 1.0, "roughness": R}, use_gpu=use_gpu)
        metal = _centre_lum("metal", {"roughness": R}, use_gpu=use_gpu)
        # Disney's Schlick-Fresnel + combined-G spec differs slightly from the metal
        # material's GGX, so allow a margin — but it must be reflecting, not ~black.
        if disney < 0.30 or disney < 0.5 * metal:
            bad[R] = (round(disney, 3), round(metal, 3))
    assert not bad, f"disney metal reflection too dark vs metal material {{R:(disney,metal)}}={bad}"


def test_disney_metal_reflection_not_black_cpu():
    _check(use_gpu=False)


@pytest.mark.skipif(
    AVAILABLE and not astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build")
def test_disney_metal_reflection_not_black_gpu():
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")
    _check(use_gpu=True)
