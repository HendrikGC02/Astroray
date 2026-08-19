"""pkg206 — luminance-weighted hero-wavelength importance sampling.

Sampler-level gates (fast, driven through the Python bindings):

  1. UNBIASEDNESS — the importance-sampled Monte-Carlo estimator of a known
     spectral integral matches the uniform-sampled estimator (and the analytic
     truth) within MC error. Importance sampling only changes the proposal
     density; dividing the estimator by that density leaves the mean unchanged.

  2. VARIANCE REDUCTION — for an integrand concentrated in the photopic band
     (where the eye sees), the importance estimator has measurably lower
     variance than the uniform one at equal sample count. That is the whole win.

  3. PDF NORMALIZATION — the per-sample pdf is a genuine density in 1/nm:
     E_u[ 1 / (span * pdf_hero) ] == 1 (the pdf integrates to 1 over the range).

These run on the CPU sampler. The render-level A/B convergence gate lives in
test_pkg206_prism_convergence.py; CPU<->GPU parity is covered by the wavefront
parity suites (the GPU sampleImportanceWavelength is a byte-mirror).
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "build"))

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

LMIN, LMAX = 360.0, 830.0
SPAN = LMAX - LMIN


def _hero_arrays(sampler, us):
    """Return (hero lambdas, hero pdfs) for a batch of uniforms."""
    lam = np.empty(us.size)
    pdf = np.empty(us.size)
    for i, u in enumerate(us):
        wl = sampler(float(u))
        lam[i] = wl.lambda_(0)
        pdf[i] = wl.pdf(0)
    return lam, pdf


def _gauss(lam, mu, sigma):
    return np.exp(-0.5 * ((lam - mu) / sigma) ** 2)


def _analytic_integral(mu, sigma):
    """Fine-grid reference for the truncated-Gaussian integral over the band."""
    grid = np.linspace(LMIN, LMAX, 2_000_001)
    return np.trapezoid(_gauss(grid, mu, sigma), grid)


def test_importance_hero_stays_in_range_and_pdf_positive():
    for u in [0.0, 1e-6, 0.25, 0.5, 0.75, 1.0 - 1e-6]:
        wl = astroray.SampledWavelengths.sample_importance(u)
        lambdas = wl.lambdas()
        pdfs = wl.pdfs()
        assert len(lambdas) == 4 and len(pdfs) == 4
        for lam in lambdas:
            assert LMIN - 1e-2 <= lam <= LMAX + 1e-2, lam
        for p in pdfs:
            assert p > 0.0, p


def test_importance_pdf_integrates_to_one():
    # E_u[ 1 / (span * pdf_hero) ] == 1  <=>  integral of pdf over band == 1.
    rng = np.random.default_rng(206)
    us = rng.random(60_000)
    _, pdf = _hero_arrays(astroray.SampledWavelengths.sample_importance, us)
    est = np.mean(1.0 / (SPAN * pdf))
    # The uniform baseline: pdf == 1/span, so 1/(span*pdf) == 1 exactly.
    assert est == pytest.approx(1.0, abs=0.01), est


def test_importance_matches_uniform_mean_unbiased():
    # Estimate integral of a photopic-band Gaussian bump two ways. Both are
    # unbiased estimators of the same integral, so their means agree within MC
    # error and both match the analytic truth.
    mu, sigma = 555.0, 60.0
    truth = _analytic_integral(mu, sigma)

    rng = np.random.default_rng(20206)
    us = rng.random(120_000)

    lam_i, pdf_i = _hero_arrays(astroray.SampledWavelengths.sample_importance, us)
    lam_u, pdf_u = _hero_arrays(astroray.SampledWavelengths.sample_uniform, us)

    est_i = _gauss(lam_i, mu, sigma) / pdf_i
    est_u = _gauss(lam_u, mu, sigma) / pdf_u

    mean_i, mean_u = est_i.mean(), est_u.mean()
    se_i = est_i.std(ddof=1) / np.sqrt(est_i.size)
    se_u = est_u.std(ddof=1) / np.sqrt(est_u.size)

    print(f"\n  analytic integral        = {truth:.4f}")
    print(f"  importance estimate      = {mean_i:.4f} +/- {se_i:.4f}")
    print(f"  uniform    estimate      = {mean_u:.4f} +/- {se_u:.4f}")

    # Each estimator within ~4 SE of the analytic truth (unbiased).
    assert abs(mean_i - truth) < 4.0 * se_i + 1e-3, (mean_i, truth, se_i)
    assert abs(mean_u - truth) < 4.0 * se_u + 1e-3, (mean_u, truth, se_u)
    # And within ~4 combined SE of each other.
    assert abs(mean_i - mean_u) < 4.0 * (se_i + se_u) + 1e-3


def test_importance_reduces_variance_in_photopic_band():
    # Integrand concentrated where luminance is high (green-ish). The importance
    # sampler is fitted to exactly this region, so its estimator variance is
    # measurably lower than uniform's at equal sample count.
    mu, sigma = 545.0, 45.0

    rng = np.random.default_rng(999)
    us = rng.random(120_000)

    lam_i, pdf_i = _hero_arrays(astroray.SampledWavelengths.sample_importance, us)
    lam_u, pdf_u = _hero_arrays(astroray.SampledWavelengths.sample_uniform, us)

    est_i = _gauss(lam_i, mu, sigma) / pdf_i
    est_u = _gauss(lam_u, mu, sigma) / pdf_u

    var_i = est_i.var(ddof=1)
    var_u = est_u.var(ddof=1)
    ratio = var_i / var_u

    print(f"\n  var(importance) = {var_i:.4f}")
    print(f"  var(uniform)    = {var_u:.4f}")
    print(f"  variance ratio  = {ratio:.3f}  (want < 1.0)")

    assert ratio < 0.9, f"importance sampling did not reduce variance: ratio={ratio:.3f}"
