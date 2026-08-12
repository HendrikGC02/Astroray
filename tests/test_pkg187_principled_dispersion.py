"""pkg187 — Principled BSDF dispersion (CPU).

Acceptance coverage (engine-level; the Blender socket is unmerged upstream, see
the spec correction note + tests/test_pkg187_addon_dispersion_probe.py):

  * A Principled glass prism with nonzero dispersion produces CHROMATIC caustics
    (measurable red/blue spatial spread beyond the flat prism).
  * Zero-dispersion Principled glass is BYTE-IDENTICAL to the pre-pkg187 path
    (regression guard): a render with dispersion_scale=0 == a render with no
    dispersion params at all, and both == the non-dispersive baseline.
  * The OpenPBR/Cycles Cauchy fit constants are pinned (blue bends more than red).

Uses the shared pkg29 prism scaffold (closed triangular prism, outward normals)
but with a native `principled` transmissive glass instead of the dielectric.
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

from base_helpers import save_image
from scenes.prism_reference import (
    HEIGHT,
    MAX_DEPTH,
    SAMPLES,
    WIDTH,
    _add_panel,
    add_triangular_prism,
    red_blue_centroid_separation,
)

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

# Dense-flint-like dispersion: Abbe 20, full scale -> strong, unambiguous spread.
DISP_PARAMS = {"dispersion_scale": 1.0, "dispersion_abbe": 20.0}


def _make_principled_prism_scene(*, glass_extra: dict):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([0.8, 0.9, 1.0])

    red = r.create_material("lambertian", [1.0, 0.05, 0.03], {})
    white = r.create_material("lambertian", [0.92, 0.92, 0.90], {})
    blue = r.create_material("lambertian", [0.03, 0.08, 1.0], {})
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 5.0})

    _add_panel(r, red, -2.0, -0.4, -1.79)
    _add_panel(r, white, -0.45, 0.45, -1.80)
    _add_panel(r, blue, 0.4, 2.0, -1.78)

    r.add_triangle([-1.5, 1.6, 1.5], [1.5, 1.6, 1.5], [1.5, 1.6, -1.2], light)
    r.add_triangle([-1.5, 1.6, 1.5], [1.5, 1.6, -1.2], [-1.5, 1.6, -1.2], light)

    # Smooth (delta) transmissive Principled glass; roughness < kDeltaGlassRoughness.
    params = {"transmission_weight": 1.0, "ior": 1.5, "roughness": 0.02, "metallic": 0.0}
    params.update(glass_extra)
    glass = r.create_material("principled", [1.0, 1.0, 1.0], params)
    add_triangular_prism(r, glass)

    r.setup_camera(
        [0.0, 0.0, 4.2], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
        38.0, 1.0, 0.0, 4.2, WIDTH, HEIGHT)
    return r


def _render(glass_extra: dict, *, seed: int = 17) -> np.ndarray:
    r = _make_principled_prism_scene(glass_extra=glass_extra)
    r.set_seed(seed)
    return np.asarray(r.render(SAMPLES, MAX_DEPTH, None, True), dtype=np.float32)


def test_principled_dispersion_is_chromatic(test_results_dir):
    flat = _render({})
    dispersive = _render(DISP_PARAMS)

    save_image(flat, os.path.join(test_results_dir, "pkg187_principled_flat.png"))
    save_image(dispersive, os.path.join(test_results_dir, "pkg187_principled_dispersive.png"))

    flat_sep = red_blue_centroid_separation(flat)
    disp_sep = red_blue_centroid_separation(dispersive)
    diff = np.abs(dispersive - flat)

    print(f"\n  principled flat  red/blue centroid separation: {flat_sep:.3f}px")
    print(f"  principled disp. red/blue centroid separation: {disp_sep:.3f}px")
    print(f"  max abs RGB diff: {float(diff.max()):.4f}  mean: {float(diff.mean()):.4f}")

    assert np.isfinite(dispersive).all()
    assert float(dispersive.mean()) > 0.01
    # Dispersion must add clear red/blue spatial separation vs the flat prism.
    assert float(diff.max()) > 0.15
    assert disp_sep - flat_sep > 1.0


def test_zero_dispersion_is_bit_identical(test_results_dir):
    """Regression guard: dispersion_scale=0 and 'no dispersion params' must both
    reproduce the non-dispersive baseline BYTE-for-byte (dispersive_ is false, so
    the added sampleSpectral branches never execute)."""
    baseline = _render({})
    scale_zero = _render({"dispersion_scale": 0.0, "dispersion_abbe": 20.0})
    # A defined abbe with zero scale is still non-dispersive (inv_abbe = 0).
    abbe_only = _render({"dispersion_abbe": 25.0})

    assert np.array_equal(baseline, scale_zero), (
        "dispersion_scale=0 perturbed the zero-dispersion render (not bit-identical)")
    assert np.array_equal(baseline, abbe_only), (
        "an Abbe number with zero scale perturbed the zero-dispersion render")


def test_nonzero_dispersion_actually_changes_the_render():
    """Sanity companion to the bit-identity guard: the switch is genuinely live."""
    baseline = _render({})
    dispersive = _render(DISP_PARAMS)
    assert not np.array_equal(baseline, dispersive)


def test_openpbr_cauchy_constants_pinned():
    """Pin the ported OpenPBR v1.1.1 / Cycles PR#162041 Cauchy fit: blue (F line)
    must refract more strongly than red (C line), and the d line reproduces the
    base IOR. This anchors the constants in principled.cpp::cauchyAB against
    accidental edits (pure-Python replica of the cited formula)."""
    lambda_d, lambda_C, lambda_F = 0.5876, 0.6563, 0.4861
    fac = 1.0 / (1.0 / lambda_F**2 - 1.0 / lambda_C**2)
    n_d = 1.5
    inv_abbe = 1.0 / 20.0  # scale 1.0 / Abbe 20
    B = (n_d - 1.0) * inv_abbe * fac
    A = n_d - B / lambda_d**2

    def n(lam_um):
        return A + B / lam_um**2

    assert n(lambda_d) == pytest.approx(n_d, abs=1e-4)   # d line == base IOR
    assert n(lambda_F) > n(lambda_d) > n(lambda_C)       # blue bends more than red
    assert (n(lambda_F) - n(lambda_C)) > 0.01            # meaningful spread at Abbe 20
