"""pkg225 Stage 2 — Principled Hair BSDF (Chiang 2016) unit gates.

Drives the CPU `principled_hair` material's BSDF directly (no render) via the
`eval_hair_material` / `integrate_hair_reflectance` test bindings, which build a
curve-style HitRecord (uvTangent = strand tangent, hair_v set) so the hair
branch activates. See .astroray_plan/docs/pkg225-hair-bsdf-research.md §9.
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from runtime_setup import configure_test_imports
configure_test_imports()

try:
    import astroray
    AVAILABLE = hasattr(astroray.Renderer, "integrate_hair_reflectance")
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray hair bindings not built")

_TANGENT = [1.0, 0.0, 0.0]          # strand along +X
_HAIR_V = 0.62                       # off-centre hit (h = 2v-1 = 0.24)


def _hair_mat(r, **params):
    # Reflectance colour defaults to a mid grey unless overridden.
    color = params.pop("color", [0.5, 0.5, 0.5])
    return r.create_material("principled_hair", color, params)


def _wo(theta_deg=35.0, phi_deg=20.0):
    # A generic outgoing (view) direction, not aligned to the tangent.
    t = math.radians(theta_deg)
    p = math.radians(phi_deg)
    return [math.sin(t), math.cos(t) * math.cos(p), math.cos(t) * math.sin(p)]


@pytest.mark.parametrize("betaM", [0.1, 0.3, 0.6, 1.0])
def test_energy_conservation_white_furnace(betaM):
    """sigma_a = 0 (absorption off): the hemispherical/spherical directional
    reflectance rho = (1/N) sum f/pdf must be <= 1 (energy-conserving). Linear,
    upper-bound assertion (MEMORY gamma-furnace-hides-energy-gain)."""
    r = astroray.Renderer()
    mat = _hair_mat(r, roughness=betaM, radial_roughness=0.3,
                    parametrization="absorption", absorption_coefficient=[0.0, 0.0, 0.0])
    rho = np.asarray(r.integrate_hair_reflectance(mat, _wo(), _TANGENT, _HAIR_V, 20000))
    assert np.all(np.isfinite(rho)), f"rho not finite: {rho}"
    assert np.all(rho <= 1.02), f"energy gain (rho>1) at betaM={betaM}: {rho}"
    assert np.all(rho > 0.2), f"suspiciously dark hair (rho too low) at betaM={betaM}: {rho}"


def test_absorption_darkens():
    """Non-zero absorption must reduce reflectance vs the zero-absorption case."""
    r = astroray.Renderer()
    clear = _hair_mat(r, roughness=0.3, parametrization="absorption",
                      absorption_coefficient=[0.0, 0.0, 0.0])
    absorb = _hair_mat(r, roughness=0.3, parametrization="absorption",
                       absorption_coefficient=[2.0, 2.0, 2.0])
    rho_clear = np.asarray(r.integrate_hair_reflectance(clear, _wo(), _TANGENT, _HAIR_V, 20000))
    rho_abs = np.asarray(r.integrate_hair_reflectance(absorb, _wo(), _TANGENT, _HAIR_V, 20000))
    assert np.mean(rho_abs) < np.mean(rho_clear), \
        f"absorption did not darken: clear={rho_clear} absorb={rho_abs}"


def test_reflectance_color_response():
    """Direct-coloring (reflectance) mode: a red target colour must yield a
    redder reflectance than a blue target (the sigma_a inversion is per-channel)."""
    r = astroray.Renderer()
    red = _hair_mat(r, color=[0.6, 0.05, 0.05], roughness=0.3, parametrization="reflectance")
    blue = _hair_mat(r, color=[0.05, 0.05, 0.6], roughness=0.3, parametrization="reflectance")
    rho_red = np.asarray(r.integrate_hair_reflectance(red, _wo(), _TANGENT, _HAIR_V, 20000))
    rho_blue = np.asarray(r.integrate_hair_reflectance(blue, _wo(), _TANGENT, _HAIR_V, 20000))
    assert rho_red[0] > rho_red[2], f"red hair not red-dominant: {rho_red}"
    assert rho_blue[2] > rho_blue[0], f"blue hair not blue-dominant: {rho_blue}"


def test_eval_finite_and_nonnegative():
    """eval must be finite and >= 0 for a spread of incoming directions."""
    r = astroray.Renderer()
    mat = _hair_mat(r, roughness=0.3, radial_roughness=0.3, parametrization="reflectance",
                    color=[0.4, 0.3, 0.2])
    wo = _wo()
    rng = np.random.default_rng(7)
    saw_positive = False
    for _ in range(200):
        d = rng.normal(size=3); d /= np.linalg.norm(d)
        f = np.asarray(r.eval_hair_material(mat, wo, list(d), _TANGENT, _HAIR_V))
        assert np.all(np.isfinite(f)), f"eval not finite: {f} wi={d}"
        assert np.all(f >= -1e-6), f"eval negative: {f} wi={d}"
        if np.any(f > 1e-4):
            saw_positive = True
    assert saw_positive, "hair BSDF eval was ~zero for every direction"


def test_not_a_curve_hit_returns_zero():
    """hair_v < 0 (non-curve hit) must return zero — the material only activates
    on curve hits, so non-hair scenes are unaffected (regression guard)."""
    r = astroray.Renderer()
    mat = _hair_mat(r, roughness=0.3)
    f = np.asarray(r.eval_hair_material(mat, _wo(), [0.0, 1.0, 0.0], _TANGENT, -1.0))
    assert np.allclose(f, 0.0), f"expected zero for non-curve hit, got {f}"


def test_hair_strand_renders_spectral_path():
    """End-to-end smoke: a curve strand with the principled_hair material, lit by
    a grey environment, must render through the SPECTRAL integrator path
    (evalSpectral/sampleSpectral) to finite, energy-bounded, non-black pixels.
    The RGB unit gates above never touch the spectral path, so this guards it."""
    W = H = 96
    r = astroray.Renderer()
    r.set_background_color([0.5, 0.5, 0.5])            # uniform grey environment
    mat = _hair_mat(r, roughness=0.3, radial_roughness=0.3,
                    color=[0.55, 0.35, 0.18], parametrization="reflectance")
    # A near-horizontal strand across the view, thick enough to cover pixels.
    pts = np.array([[-3.0, 0.0, 0.0], [-1.0, 0.0, 0.0],
                    [1.0, 0.0, 0.0], [3.0, 0.0, 0.0]], dtype=np.float32)
    rad = np.full(4, 0.25, dtype=np.float32)
    r.add_curves_bulk(pts, rad, [4], mat)
    r.set_integrator("path_tracer")
    r.setup_camera([0, 0, 5], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 5.0, W, H)
    r.set_seed(7)
    img = np.asarray(r.render(64, 6, None, True), dtype=np.float32).reshape(H, W, 3)
    assert np.all(np.isfinite(img)), "hair render produced non-finite pixels"
    assert float(img.max()) < 5.0, f"hair render energy runaway: max={img.max()}"
    # The strand crosses the middle row; that band must be lit (non-black).
    band = img[H // 2 - 3:H // 2 + 3, :, :]
    assert float(band.max()) > 1e-3, f"hair strand rendered black (max={band.max()})"
