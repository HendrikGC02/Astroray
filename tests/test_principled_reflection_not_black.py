"""Principled metallic + dielectric-specular REFLECTION must not render black at
LOW roughness, CPU and GPU.

Regression guard for the eval-D vs pdf-D regularizer mismatch (fixed pkg182): the
Principled reflect lobes (ggxReflectRGB/Spectral + gpu_pr_ggxReflect*) evaluated D
as `a2/(π·denom²+1e-4)` while the NDF-sampling pdf (pdfLobe) used the unregularized
`D_GTR2`. At roughness ≲ 0.2 the `+1e-4` term dominates the eval denominator and
collapses the eval D ~1e4× below the pdf D at the specular peak (measured ~19000×
at r=0.02), so f/pdf → 0 and the metallic / specular lobe rendered NEAR-BLACK. The
fix uses D_GTR2 in BOTH eval and pdf (the discipline the Transmission / thin-glass
`ggxReflectConsistent` lobes already followed).

A Principled metallic (or dielectric-specular) sphere in a uniform grey [0.5]
environment must reflect that environment — its centre luminance must be a
substantial fraction of what the plain `metal` material produces at the same
roughness, and must NOT be ~0. The plain `metal` material uses a self-consistent
eval/pdf D (both `+0.001f`), so it reflects correctly at low roughness and is a
valid reference. The white-furnace glass gate does NOT catch this (it exercises
the transmission path, not reflection) — pkg PR-named-tests-insufficient.
"""

from __future__ import annotations

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

_ROUGHNESS = [0.02, 0.05, 0.1]
_GOLD = [0.9, 0.68, 0.25]


def _centre_lum(mat_type: str, base, params: dict, *, use_gpu: bool = False) -> float:
    r = astroray.Renderer()
    r.set_background_color([0.5, 0.5, 0.5])           # uniform grey environment
    m = r.create_material(mat_type, list(base), dict(params))
    r.add_sphere([0.0, 0.0, 0.0], 1.0, m)
    r.set_integrator("path_tracer")
    if use_gpu:
        r.set_use_gpu(True)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 96, 96)
    r.set_seed(7)
    img = np.asarray(r.render(64, 8, None, True), dtype=np.float32).reshape(96, 96, 3)
    lum = 0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2]
    return float(lum[36:60, 36:60].mean())


def _check_metallic(use_gpu: bool):
    """Full metallic mirror: reflects ~all of the grey env. Compared to the plain
    `metal` material (self-consistent eval/pdf D → correct at low roughness).
    Pre-fix (measured, CPU): 0.067/0.067/0.112 at r=0.02/0.05/0.10 vs metal ~0.60."""
    bad = {}
    for R in _ROUGHNESS:
        pr = _centre_lum("principled", _GOLD, {"metallic": 1.0, "roughness": R}, use_gpu=use_gpu)
        metal = _centre_lum("metal", _GOLD, {"roughness": R}, use_gpu=use_gpu)
        # F82 vs GGX + energy comp differ slightly; require it be REFLECTING, i.e.
        # a substantial fraction of the metal material (not the ~0.1x collapse).
        if pr < 0.30 or pr < 0.5 * metal:
            bad[R] = (round(pr, 4), round(metal, 4))
    assert not bad, (
        f"Principled metallic reflection too dark vs metal material at low "
        f"roughness {{R:(principled,metal)}}={bad}")


def _check_specular(use_gpu: bool):
    """Isolate the dielectric-specular reflect lobe: BLACK base color kills the
    diffuse lobe (which would otherwise mask the specular collapse), metallic=0,
    no transmission. Only the specular GGX reflection of the grey env remains.
    Pre-fix (measured, CPU): 0.025/0.025/0.042; post-fix flat ~0.231. A flat,
    clearly-positive value across roughness is the smoking gun that the eval/pdf-D
    mismatch (which grew as roughness→0) is gone."""
    bad = {}
    for R in _ROUGHNESS:
        pr = _centre_lum("principled", [0.0, 0.0, 0.0],
                         {"metallic": 0.0, "roughness": R, "specular_ior_level": 1.0},
                         use_gpu=use_gpu)
        # Post-fix ~0.23; pre-fix max 0.042. 0.12 cleanly separates (~3x margin).
        if pr < 0.12:
            bad[R] = round(pr, 4)
    assert not bad, (
        f"Principled dielectric-specular reflection collapsed at low roughness "
        f"(black-base isolation) {{R:centre_lum}}={bad}; expected ~0.23")


def test_principled_metallic_reflection_not_black_low_roughness_cpu():
    _check_metallic(use_gpu=False)


def test_principled_specular_reflection_not_black_low_roughness_cpu():
    _check_specular(use_gpu=False)


@pytest.mark.skipif(
    AVAILABLE and not astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build")
def test_principled_metallic_reflection_not_black_low_roughness_gpu():
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")
    _check_metallic(use_gpu=True)


@pytest.mark.skipif(
    AVAILABLE and not astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build")
def test_principled_specular_reflection_not_black_low_roughness_gpu():
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")
    _check_specular(use_gpu=True)
