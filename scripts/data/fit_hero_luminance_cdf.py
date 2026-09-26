#!/usr/bin/env python
"""pkg206 -- fit a logistic (sigmoid) CDF to Astroray's luminance-weighted D65
hero-wavelength target, against the baked observer table (data/spectra/cie_cmf.inc).

The committed kHeroA/kHeroX0 were fitted 2026-08-21 against the then-baked
CIE 1964 10 deg table. #767 moved the table to CIE 1931 2 deg, so re-running
this script now fits 2 deg (kHeroA 0.0223367, kHeroX0 555.72 nm). The old
constants stay an unbiased proposal; the re-fit is variance-only (#848).

`--minimax` (#848 follow-up; the SHIPPED constants since 2026-09-27): the
luminance fit leaves blue under-sampled (grey D65 floor: B normalised variance
~11x R). This mode grid-searches the same logistic family (pbrt-v4
SampleVisibleWavelengths is a member: a=0.0144, x0=538) for the (a, x0) that
minimises the WORST sRGB-channel variance of the 4-lane CDF-stratified hero
estimator on a D65-lit grey surface, subject to luminance variance <= the old
constants'. Result: kHeroA 0.0170, kHeroX0 522.5 nm.

Astroray carries the CIE 1964 10 deg observer + a normalized D65 SPD
(src/spectrum.cpp, data/spectra/*.inc). Blender Cycles' merged dispersion PR
draws the hero wavelength from a luminance-weighted D65 distribution fitted to a
sigmoid CDF (intern/cycles/kernel/util/colorspace.h::sample_wavelength,
intern/cycles/app/cie_d65_luminance_fit.py, Apache-2.0). Cycles fits against the
CIE 1931 2 deg observer; because Astroray's observer differs we RE-FIT here
against Astroray's baked tables rather than reusing Cycles' constants blindly.

Target CDF: cumulative of  (y_bar + BLEND) * D65  over [360, 830] nm.
  * y_bar    = baked luminance CMF (kCieCmfY; CIE 1931 2 deg since #767)
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


def minimax() -> int:
    """Worst-channel variance fit (see module docstring)."""
    xyz = np.vstack([parse_array(CMF_INC, k) for k in ("kCieCmfX", "kCieCmfY", "kCieCmfZ")])
    d65 = parse_array(D65_INC, "kD65Spd")
    lam = np.arange(LMIN, LMAX + 0.5, STEP)
    srgb = np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415],
                     [0.0557, -0.2040, 1.0570]])
    rgb_d65 = (srgb @ xyz) * d65                       # grey surface under D65
    lum_w = np.array([0.2126, 0.7152, 0.0722])
    u = (np.arange(20000) + 0.5) / 20000 / 4           # 4 lanes stratified in CDF space

    def nv(a, x0):
        lo, hi = sigmoid(LMIN, a, x0), sigmoid(LMAX, a, x0)
        est = 0.0
        for i in range(4):
            r = lo + (hi - lo) * (u + i / 4)
            lam_i = x0 - np.log(1 / r - 1) / a
            pdf = a * r * (1 - r) / (hi - lo)
            est = est + np.vstack([np.interp(lam_i, lam, c) for c in rgb_d65]) / pdf
        est /= 4
        y = lum_w @ est
        return est.var(1) / est.mean(1) ** 2, y.var() / y.mean() ** 2

    _, lum0 = nv(0.0221679280, 552.040271)             # pre-minimax constants
    best = None
    for a in np.arange(0.010, 0.02405, 0.0005):
        for x0 in np.arange(500.0, 560.05, 2.5):
            ch, lum = nv(a, x0)
            if lum <= lum0 and (best is None or ch.max() < best[0]):
                best = (ch.max(), a, x0, ch, lum)
    _, a, x0, ch, lum = best
    print(f"kHeroA  = {a:.4f}f;  kHeroX0 = {x0:.1f}f;")
    print(f"# grey-D65 per-sample nv RGB {np.round(ch, 4)}, lum {lum:.5f} (old {lum0:.5f})")
    return 0


def main() -> int:
    if "--minimax" in sys.argv:
        return minimax()
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

    print("# luminance-weighted D65 hero-wavelength fit vs the baked CMF (nm units)")
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
