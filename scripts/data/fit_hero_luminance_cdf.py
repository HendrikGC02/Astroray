#!/usr/bin/env python
"""pkg206 -- fit a logistic (sigmoid) CDF to Astroray's luminance-weighted D65
hero-wavelength target, against Astroray's OWN CIE 1964 10-degree observer.

Astroray carries the CIE 1964 10 deg observer + a normalized D65 SPD
(src/spectrum.cpp, data/spectra/*.inc). Blender Cycles' merged dispersion PR
draws the hero wavelength from a luminance-weighted D65 distribution fitted to a
sigmoid CDF (intern/cycles/kernel/util/colorspace.h::sample_wavelength,
intern/cycles/app/cie_d65_luminance_fit.py, Apache-2.0). Cycles fits against the
CIE 1931 2 deg observer; because Astroray's observer differs we RE-FIT here
against Astroray's baked tables rather than reusing Cycles' constants blindly.

Target CDF: cumulative of  (y_bar + BLEND) * D65  over [360, 830] nm.
  * y_bar    = CIE 1964 10 deg luminance CMF (kCieCmfY)
  * D65      = normalized D65 SPD (kD65Spd)
  * BLEND    = additive constant on the luminance CMF ("a bit of all
               wavelengths" -- Cycles' trick; blends luminance vs uniform).

Model:  F(lambda; a, x0) = 1 / (1 + exp(-a*(lambda - x0)))   [lambda in nm]
        y0 = F(lmin),  N = F(lmax) - y0   (CDF-space truncation to the range)

Emits the a / x0 / y0 / N constants (nm units) for the CPU + GPU sampler and a
fit-quality error bound. Derivation + observer-mismatch decision:
.astroray_plan/docs/pkg206-hero-luminance-fit.md

Registered in scripts/README.md (Spectral data/profile generation row).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import curve_fit

ROOT = Path(__file__).resolve().parents[2]
CMF_INC = ROOT / "data" / "spectra" / "cie_cmf.inc"
D65_INC = ROOT / "data" / "spectra" / "illuminant_d65.inc"

LMIN, LMAX = 360.0, 830.0
STEP = 1.0
BLEND = 0.25  # additive constant on the luminance CMF (Cycles' blend trick).


def parse_array(path: Path, name: str) -> np.ndarray:
    text = path.read_text()
    m = re.search(name + r"\[\d+\]\s*=\s*\{(.*?)\}", text, re.DOTALL)
    if not m:
        raise RuntimeError(f"array {name} not found in {path}")
    nums = re.findall(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?f?", m.group(1))
    return np.array([float(x.rstrip("f")) for x in nums], dtype=np.float64)


def sigmoid(x, a, x0):
    return 1.0 / (1.0 + np.exp(-a * (x - x0)))


def main() -> int:
    ybar = parse_array(CMF_INC, "kCieCmfY")
    d65 = parse_array(D65_INC, "kD65Spd")
    assert ybar.size == d65.size == 471, (ybar.size, d65.size)

    lam = np.arange(LMIN, LMAX + 0.5, STEP)
    assert lam.size == ybar.size

    weight = (ybar + BLEND) * d65
    cdf = np.cumsum(weight)
    cdf /= cdf[-1]

    # Initial guess: steep sigmoid centred on the luminance peak (~555 nm).
    p0 = (0.02, 555.0)
    popt, _ = curve_fit(sigmoid, lam, cdf, p0=p0, maxfev=100000)
    a, x0 = float(popt[0]), float(popt[1])

    y0 = float(sigmoid(LMIN, a, x0))
    span = float(sigmoid(LMAX, a, x0)) - y0

    # Fit quality: max abs error of the fitted CDF vs empirical.
    err = float(np.max(np.abs(sigmoid(lam, a, x0) - cdf)))

    print("# CIE-1964 10deg luminance-weighted D65 hero-wavelength fit (nm units)")
    print(f"# range [{LMIN}, {LMAX}] nm, blend +{BLEND}")
    print(f"kHeroA  = {a:.10f}f;   // 1/nm")
    print(f"kHeroX0 = {x0:.6f}f;    // nm")
    print(f"kHeroY0 = {y0:.10f}f;")
    print(f"kHeroN  = {span:.10f}f;")
    print(f"# max |F_fit - F_emp| = {err:.5e}")

    # Cross-check: verify the sampler round-trips over the truncated CDF window
    # and that the density integrates to 1 over the analytic support.
    u = (np.arange(0.5, 1_000_000) / 1_000_000)
    rand = span * u + y0
    lam_s = -np.log(1.0 / rand - 1.0) / a + x0
    print(f"# sampled lambda in [{lam_s.min():.3f}, {lam_s.max():.3f}] nm")
    lam_grid = np.linspace(lam_s.min(), lam_s.max(), 2_000_000)
    F = sigmoid(lam_grid, a, x0)
    pdf_grid = a * F * (1.0 - F) / span
    integral = np.trapezoid(pdf_grid, lam_grid)
    print(f"# integral(pdf dlambda) over support = {integral:.6f}  (target 1.0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
