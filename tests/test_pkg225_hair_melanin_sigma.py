"""Deterministic check of the spectral hair melanin sigma_a(lambda) seam.

Replaces the render-level spectral-vs-RGB R/B comparison in
test_pkg225_spectral_hair.py (physically <=0.4%, cannot detect a silent
fallback). Binding: astroray_test_helpers.hair_melanin_sigma_at_lambda.
"""
from __future__ import annotations

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()
helpers = pytest.importorskip("astroray_test_helpers")
if not hasattr(helpers, "hair_melanin_sigma_at_lambda"):
    pytest.skip("astroray_test_helpers lacks hair_melanin_sigma_at_lambda; rebuild",
                allow_module_level=True)

sigma = helpers.hair_melanin_sigma_at_lambda
LAMBDAS = [400.0, 450.0, 500.0, 550.0, 600.0, 650.0, 700.0]
# Cycles RGB melanin coefficients (include/astroray/hair_bsdf.h melaninCoeffs).
CE = np.array([0.506, 0.841, 1.653])
CP = np.array([0.343, 0.733, 1.924])


def _rgb_fallback(eu, ph, lam):
    """The direct-absorption fallback in principled_hair.cpp sigmaAAtLambda: piecewise-
    linear upsample of the RGB triple (B<=450, G=550, R>=600)."""
    r, g, b = CE * eu + CP * ph
    if lam <= 450.0:
        return b
    if lam >= 600.0:
        return r
    if lam < 550.0:
        t = (lam - 450.0) / 100.0
        return b * (1 - t) + g * t
    t = (lam - 550.0) / 50.0
    return g * (1 - t) + r * t


@pytest.mark.parametrize("lam", LAMBDAS)
def test_pure_eumelanin_power_law(lam):
    want = 0.841 * (lam / 550.0) ** -3.33  # Jacques 2013
    assert sigma(1.0, 0.0, lam) == pytest.approx(want, rel=1e-5)


@pytest.mark.parametrize("lam", LAMBDAS)
def test_pure_pheomelanin_power_law(lam):
    want = 0.733 * (lam / 550.0) ** -4.75
    assert sigma(0.0, 1.0, lam) == pytest.approx(want, rel=1e-5)


def test_linear_in_concentration():
    for lam in (450.0, 650.0):
        assert sigma(0.7, 0.4, lam) == pytest.approx(
            0.7 * sigma(1.0, 0.0, lam) + 0.4 * sigma(0.0, 1.0, lam), rel=1e-5)


def test_differs_from_rgb_fallback_at_spectral_extremes():
    # A silent fallback to the RGB upsample would make these equal. The power
    # law diverges from the clamped piecewise upsample toward the extremes.
    for eu, ph in [(1.0, 0.0), (0.0, 1.0), (0.5, 0.5)]:
        gaps = [abs(sigma(eu, ph, lam) - _rgb_fallback(eu, ph, lam))
                / _rgb_fallback(eu, ph, lam) for lam in (400.0, 700.0)]
        print(f"  eu={eu} ph={ph} rel gap at 400/700 nm: {gaps}")
        assert max(gaps) > 0.10, f"sigma_a(lambda) tracks RGB fallback for eu={eu} ph={ph}"
    # ...but is anchored to the green coefficient at 550 nm.
    assert sigma(1.0, 0.0, 550.0) == pytest.approx(_rgb_fallback(1.0, 0.0, 550.0), rel=1e-5)
