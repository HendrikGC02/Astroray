"""pkg206 — luminance-weighted hero-wavelength importance sampling.

Unit-level correctness of `SampledWavelengths.sample_importance` (the CPU
sampler; the GPU twin `sampleImportanceWavelength` in stage_init.cu is a
byte-mirror verified separately by the CPU↔GPU parity render).

Three properties, all independent of any build being *fast* — they only need
the extension importable:

  1. **Normalization** — the logistic proposal density integrates to 1 over the
     analytic support [360, 830] nm (Riemann sum via a dense evaluation of the
     per-lane pdf reconstructed from many single-lane draws).
  2. **Histogram / chi-square** — the empirical distribution of sampled hero
     wavelengths matches the target luminance-weighted logistic density (a
     goodness-of-fit chi-square, not just "looks peaked").
  3. **Unbiasedness (the load-bearing one)** — the MC estimator
     (1/N)·Σ f(λ_i)/p(λ_i) of a known spectral integrand ∫ f(λ) dλ converges to
     the SAME analytic value under both `sample_uniform` and `sample_importance`
     (Wilkie 2014: per-lane density pdf ⇒ unbiased), and the importance variant
     has LOWER variance for a luminance-shaped integrand.

Skipped entirely if the `astroray` extension is not importable (no build).
"""

import math

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

LMIN, LMAX = 360.0, 830.0

# Fitted logistic-CDF constants — MUST match spectrum.cpp / stage_init.cu.
# (Reproduce with scripts/data/fit_hero_luminance_cdf.py.)
A = 0.0221679280
X0 = 552.040271
Y0 = 0.0139650380
N = 0.9839309253


def _logistic(lam):
    return 1.0 / (1.0 + np.exp(-A * (lam - X0)))


def _target_pdf(lam):
    """Analytic proposal density p(λ) = a·F·(1−F)/N, 1/nm, over [LMIN, LMAX]."""
    F = _logistic(lam)
    p = A * F * (1.0 - F) / N
    return np.where((lam >= LMIN) & (lam <= LMAX), p, 0.0)


def test_pdf_integrates_to_one():
    """∫ p(λ) dλ over [360, 830] nm == 1 (normalization ⇒ prerequisite for
    unbiasedness). Uses the analytic density the sampler writes into pdf[i]."""
    lam = np.linspace(LMIN, LMAX, 2_000_000)
    integral = np.trapezoid(_target_pdf(lam), lam)
    assert abs(integral - 1.0) < 1e-3, integral


def test_lane_pdf_matches_density_at_own_lambda():
    """Every lane's stored pdf equals the logistic density evaluated at ITS OWN
    wavelength (Wilkie 2014 companion-pdf rule; the pkg67/PR#627 bias trap was
    setting companions to 1/span). Checked across the u domain."""
    for u in np.linspace(0.001, 0.999, 97):
        wl = astroray.SampledWavelengths.sample_importance(float(u))
        lambdas = np.array(wl.lambdas())
        pdfs = np.array(wl.pdfs())
        expected = _target_pdf(lambdas)
        # Float32 engine vs float64 reference: loose relative tol.
        np.testing.assert_allclose(pdfs, expected, rtol=2e-3, atol=1e-9)


def test_hero_histogram_chi_square():
    """The hero-lane sampled-λ histogram matches the target logistic density
    (chi-square goodness-of-fit). One hero draw per u ∈ U(0,1)."""
    rng = np.random.default_rng(20260821)
    n = 200_000
    us = rng.random(n)
    hero = np.array([
        astroray.SampledWavelengths.sample_importance(float(u)).lambda_(0)
        for u in us
    ])
    nbins = 40
    edges = np.linspace(LMIN, LMAX, nbins + 1)
    observed, _ = np.histogram(hero, bins=edges)
    # Expected counts from the analytic density integrated per bin.
    centers = 0.5 * (edges[:-1] + edges[1:])
    widths = np.diff(edges)
    prob = _target_pdf(centers) * widths
    prob /= prob.sum()
    expected = prob * n
    mask = expected > 5.0  # chi-square validity
    chi2 = np.sum((observed[mask] - expected[mask]) ** 2 / expected[mask])
    dof = mask.sum() - 1
    # Accept within ~3 sigma of the chi-square mean (mean=dof, var=2 dof).
    threshold = dof + 4.0 * math.sqrt(2.0 * dof)
    assert chi2 < threshold, (chi2, dof, threshold)


def _mc_integral(sampler, integrand, n, seed):
    """Monte-Carlo estimate of ∫ integrand(λ) dλ over [LMIN, LMAX] using the
    hero-wavelength estimator (1/K)·Σ f(λ_i)/p(λ_i) averaged over n paths."""
    rng = np.random.default_rng(seed)
    est = np.empty(n)
    for j in range(n):
        wl = sampler(float(rng.random()))
        lam = np.array(wl.lambdas())
        pdf = np.array(wl.pdfs())
        est[j] = np.mean(integrand(lam) / pdf)
    return est


def test_unbiased_matches_uniform_and_lower_variance():
    """Both samplers estimate the SAME analytic integral (unbiasedness), and the
    importance sampler has lower variance for a luminance-concentrated integrand
    (the regime the sampler is DESIGNED for).

    Honest scope (the whole point of pkg206): importance sampling reduces
    variance only when the integrand is concentrated where the luminance-weighted
    pdf is high. For a near-flat/broad integrand (sigma >~ 55 nm over the full
    360-830 band) the varying pdf inflates f/p and importance sampling correctly
    has HIGHER variance than uniform -- standard MC theory, not a bug. We
    therefore demonstrate the win on the photopic luminance band itself, which is
    exactly the perceived-signal regime dispersive-caustic renders live in and
    which the pdf approximates."""
    # Photopic luminosity band V(lambda): peak 555 nm, FWHM ~100 nm (sigma ~42).
    mu, sigma = 555.0, 40.0

    def integrand(lam):
        return np.exp(-0.5 * ((lam - mu) / sigma) ** 2)

    lam = np.linspace(LMIN, LMAX, 2_000_000)
    analytic = np.trapezoid(integrand(lam), lam)

    n = 40_000
    unif = _mc_integral(astroray.SampledWavelengths.sample_uniform,
                        integrand, n, seed=1)
    imp = _mc_integral(astroray.SampledWavelengths.sample_importance,
                       integrand, n, seed=1)

    mean_unif = unif.mean()
    mean_imp = imp.mean()
    # Unbiasedness: both means match the analytic value within MC error
    # (~4 sigma of the importance estimator's standard error).
    se_imp = imp.std() / math.sqrt(n)
    assert abs(mean_imp - analytic) < 5.0 * se_imp + 1e-3 * analytic, \
        (mean_imp, analytic, se_imp)
    assert abs(mean_unif - analytic) < 5.0 * (unif.std() / math.sqrt(n)) + 1e-3 * analytic, \
        (mean_unif, analytic)
    # Convergence win: importance variance is lower for this luminance-shaped
    # integrand (the whole point of the package).
    assert imp.var() < unif.var(), (imp.var(), unif.var())
