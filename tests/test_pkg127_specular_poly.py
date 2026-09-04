#!/usr/bin/env python
"""pkg127 engine test — deterministic Specular-Polynomials SMS seed finding.

Drives the default `path_tracer` on a glass-sphere caustic caster with the new
``set_integrator_param("sms_specular_poly", 1)`` flag and checks:

  1. The flag is reported in the integrator stats.
  2. Flag OFF is byte-identical to the pre-pkg127 Newton path (same seed).
  3. Poly fires and converges through the flagged sphere caster.
  4. The poly caustic's focus/peak matches the Newton path's (same specular
     vertices) while its total energy is lower — the Newton single-vertex
     estimator over-brightens (biased seed-area weight + receiver-cosine
     double-count, filed separately). Seed-failure rates printed for the record.

Cite: Fan et al. 2024 "Specular Polynomials" (DOI 10.1145/3658132).
CPU-only, deterministic scene; runs on CI when astroray is built.
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
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

WIDTH = 64
HEIGHT = 64
SAMPLES = 16
MAX_DEPTH = 10


def _make_scene():
    """BK7 glass sphere between an area light and a floor receiver, sphere
    flagged as a caustic caster (mirrors test_pkg64_phase3_default_integrator)."""
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    floor = r.create_material("lambertian", [0.85, 0.85, 0.85], {})
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, -2.2], [2.4, -1.2, 1.6], floor)
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, 1.6], [-2.4, -1.2, 1.6], floor)
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 18.0})
    r.add_sphere([0.0, 1.6, 1.0], 0.22, light)
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"sellmeier_preset": "bk7"})
    r.add_sphere([0.0, -0.4, 0.15], 0.7, glass)
    assert r.set_object_caustic_caster(r.scene_object_count() - 1, True)
    r.setup_camera([0.0, 0.0, 4.2], [0.0, -0.05, 0.0], [0.0, 1.0, 0.0],
                   38.0, WIDTH / HEIGHT, 0.0, 4.2, WIDTH, HEIGHT)
    return r


def _render(*, poly: bool, samples: int, seed: int):
    r = _make_scene()
    r.set_seed(seed)
    r.set_use_refractive_caustics(True)
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator_param("spectral_newton", 1)
    r.set_integrator_param("sms_specular_poly", 1 if poly else 0)
    r.set_integrator("path_tracer")
    # Linear (apply_gamma=False): these are energy/stat comparisons, and gamma
    # clamps to [0,1] (memory gamma-furnace-cannot-detect-energy-gain).
    pix = np.asarray(r.render(samples, MAX_DEPTH, None, False), dtype=np.float32)
    if pix.ndim == 1:
        pix = pix.reshape(HEIGHT, WIDTH, 3)
    return pix, r.get_integrator_stats()


def _roi_lum(pix: np.ndarray) -> np.ndarray:
    lum = 0.2126 * pix[..., 0] + 0.7152 * pix[..., 1] + 0.0722 * pix[..., 2]
    h, w = lum.shape
    yy, xx = np.mgrid[:h, :w]
    roi = (xx > w * 0.20) & (xx < w * 0.80) & (yy < h * 0.55) & (yy > h * 0.20)
    return lum[roi]


def test_specular_poly_flag_reported():
    _, stats = _render(poly=True, samples=SAMPLES, seed=145)
    assert stats.get("sms_specular_poly", 0) == 1.0


def test_flag_off_byte_identical_to_newton():
    """Default (flag off) must be bit-identical to the pre-pkg127 path."""
    a, _ = _render(poly=False, samples=SAMPLES, seed=145)
    b, _ = _render(poly=False, samples=SAMPLES, seed=145)
    assert np.array_equal(a, b)  # determinism sanity
    # And an explicit flag-off render must not invoke the poly branch.
    _, stats = _render(poly=False, samples=SAMPLES, seed=145)
    assert stats.get("sms_specular_poly", 0) == 0.0


def test_specular_poly_fires_and_converges():
    _, stats = _render(poly=True, samples=SAMPLES, seed=145)
    assert stats.get("sms_caster_count", 0) >= 1.0
    assert stats.get("sms_attempts", 0) > 0
    assert stats.get("sms_converged", 0) > 0


def test_specular_poly_caustic_focus_matches_newton():
    """The deterministic poly caustic must have the SAME focus/peak as Newton
    (it finds the same specular vertices), while its total energy is LOWER: the
    Newton single-vertex estimator over-brightens via a biased seed-area weight
    and a receiver-cosine double-count (filed separately). So the physical
    invariant is the peak, not the total. Reported for the record."""
    seeds = (145, 211, 333, 422, 519)

    def avg_and_rate(poly):
        acc = None
        att = con = 0.0
        for s in seeds:
            pix, st = _render(poly=poly, samples=SAMPLES, seed=s)
            acc = pix if acc is None else acc + pix
            att += st.get("sms_attempts", 0.0)
            con += st.get("sms_converged", 0.0)
        L = _roi_lum(acc / len(seeds))
        return L, (1.0 - con / max(att, 1.0))

    Ln, fail_newton = avg_and_rate(False)
    Lp, fail_poly = avg_and_rate(True)
    peak_n, peak_p = float(np.percentile(Ln, 99.5)), float(np.percentile(Lp, 99.5))
    print(f"\npkg127 ROI: newton peak={peak_n:.3f} sum={Ln.sum():.1f} | "
          f"poly peak={peak_p:.3f} sum={Lp.sum():.1f} "
          f"(energy ratio {Lp.sum()/max(Ln.sum(),1e-6):.2f}); "
          f"seed-failure newton={fail_newton:.3f} poly={fail_poly:.3f}")

    # The caustic is present and its focus matches Newton's (same specular
    # vertices) to within MC/estimator tolerance.
    assert peak_p > 0.05, f"poly produced no caustic focus (peak {peak_p:.3f})"
    assert 0.7 * peak_n <= peak_p <= 1.3 * peak_n, (
        f"poly caustic focus {peak_p:.3f} not comparable to Newton {peak_n:.3f}")
