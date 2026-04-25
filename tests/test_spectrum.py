"""Tests for pkg10: Pillar 2 spectral core scaffolding.

Covers the new `include/astroray/spectrum.h` types — arithmetic, the
CIE 1964 10° CMF / D65 SPD tables, `SampledSpectrum.toXYZ`, and the
Jakob-Hanika LUT upsampling. No integration of these types into the
renderer is in scope for pkg10, so this test file drives them via the
Python bindings only.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "build"))

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

REFERENCE_JSON = Path(__file__).parent / "data" / "spectrum_reference.json"


def _reference() -> dict:
    with REFERENCE_JSON.open(encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Module surface smoke.
# ---------------------------------------------------------------------------

def test_spectrum_constants_exposed():
    assert astroray.kSpectrumSamples == 4
    assert astroray.kLambdaMin == pytest.approx(360.0)
    assert astroray.kLambdaMax == pytest.approx(830.0)


def test_spectrum_lut_path_points_at_shipped_file():
    path = astroray.spectrum_lut_path()
    assert path, "spectrum_lut_path() returned empty string"
    assert Path(path).exists(), f"LUT file missing: {path}"
    assert Path(path).name == "rgb_to_spectrum_srgb.coeff"


# ---------------------------------------------------------------------------
# SampledWavelengths.
# ---------------------------------------------------------------------------

def test_sample_uniform_stratifies_and_stays_in_range():
    for u in [0.0, 0.25, 0.5, 0.75, 0.9999]:
        wl = astroray.SampledWavelengths.sample_uniform(u)
        lambdas = wl.lambdas()
        pdfs = wl.pdfs()
        assert len(lambdas) == 4
        assert len(pdfs) == 4
        for lam in lambdas:
            assert astroray.kLambdaMin <= lam <= astroray.kLambdaMax + 1e-3
        # PDFs are uniform over the range.
        span = astroray.kLambdaMax - astroray.kLambdaMin
        for p in pdfs:
            assert p == pytest.approx(1.0 / span, rel=1e-5)


def test_sample_uniform_four_distinct_strata():
    wl = astroray.SampledWavelengths.sample_uniform(0.5)
    lambdas = sorted(wl.lambdas())
    step = (astroray.kLambdaMax - astroray.kLambdaMin) / 4.0
    for i in range(3):
        assert lambdas[i + 1] - lambdas[i] == pytest.approx(step, rel=1e-4)


def test_terminate_secondary_collapses_pdfs():
    wl = astroray.SampledWavelengths.sample_uniform(0.3)
    assert not wl.secondary_terminated()
    wl.terminate_secondary()
    assert wl.secondary_terminated()
    pdfs = wl.pdfs()
    assert pdfs[0] != 0.0
    assert pdfs[1:] == [0.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# SampledSpectrum arithmetic.
# ---------------------------------------------------------------------------

def test_arithmetic_componentwise():
    a = astroray.SampledSpectrum([1.0, 2.0, 3.0, 4.0])
    b = astroray.SampledSpectrum([4.0, 3.0, 2.0, 1.0])

    assert (a + b).values() == [5.0, 5.0, 5.0, 5.0]
    assert (a - b).values() == [-3.0, -1.0, 1.0, 3.0]
    assert (a * b).values() == [4.0, 6.0, 6.0, 4.0]
    assert (a * 2.0).values() == [2.0, 4.0, 6.0, 8.0]
    assert (2.0 * a).values() == [2.0, 4.0, 6.0, 8.0]


def test_reductions():
    a = astroray.SampledSpectrum([1.0, 2.0, 3.0, 4.0])
    assert a.sum() == pytest.approx(10.0)
    assert a.average() == pytest.approx(2.5)
    assert a.max_value() == 4.0
    assert a.min_value() == 1.0
    assert not a.has_nan()
    assert not a.is_zero()
    assert astroray.SampledSpectrum(0.0).is_zero()
    assert astroray.SampledSpectrum([0.0, float("nan"), 0.0, 0.0]).has_nan()


# ---------------------------------------------------------------------------
# D65 → XYZ whitepoint recovery.
# ---------------------------------------------------------------------------

def _d65_xyz_via_ground_truth():
    """Integrate baked D65 SPD against the baked 1964 10° CMF the same way
    the C++ runtime normalizes its SPD: this reproduces the published
    whitepoint for the 10° observer."""
    ref = _reference()
    return ref["d65_xyz_whitepoint"]


def test_d65_xyz_whitepoint_matches_reference_within_one_percent():
    """Build a dense `SampledSpectrum` from sampled D65 and check that the
    Monte Carlo `toXYZ` estimator converges to the reference whitepoint.

    We use uniform stratified hero wavelengths across many seeds and
    average to beat down the 4-sample variance — the whitepoint is what
    we ultimately care about for colour fidelity, so the test is an
    integrated check of `sampleD65`, `cie_cmf_1964_10deg`, and
    `SampledSpectrum.toXYZ` together.
    """
    ref = _d65_xyz_via_ground_truth()

    # Deterministic sweep over u: 512 stratified sets is plenty.
    N = 512
    sumX = sumY = sumZ = 0.0
    for i in range(N):
        u = (i + 0.5) / N
        wl = astroray.SampledWavelengths.sample_uniform(u)
        values = [astroray.sample_d65(wl.lambda_(j)) for j in range(4)]
        s = astroray.SampledSpectrum(values)
        xyz = s.to_xyz(wl)
        sumX += xyz.X
        sumY += xyz.Y
        sumZ += xyz.Z
    X = sumX / N
    Y = sumY / N
    Z = sumZ / N

    assert Y == pytest.approx(ref["Y"], rel=0.01), f"Y={Y}"
    assert X == pytest.approx(ref["X"], rel=0.01), f"X={X}"
    assert Z == pytest.approx(ref["Z"], rel=0.01), f"Z={Z}"

    # Also within 1% of the 1964 10° observer's published tristimulus.
    assert X == pytest.approx(0.9481, rel=0.01)
    assert Y == pytest.approx(1.0, rel=0.01)
    assert Z == pytest.approx(1.0731, rel=0.01)


# ---------------------------------------------------------------------------
# Jakob-Hanika LUT round-trip.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["white", "mid_grey", "red", "green", "blue"])
def test_rgb_to_spectrum_matches_offline_reference(name: str):
    ref = _reference()["jakob_hanika_samples"][name]
    rgb = ref["rgb"]
    lambdas = ref["wavelengths_nm"]
    expected = ref["expected_spectrum"]

    got = astroray.rgb_to_spectrum(rgb, lambdas)
    assert len(got) == len(expected)
    for g, e in zip(got, expected):
        # Coefficient lookup has ~1e-4 numerical tolerance in the C++/Python
        # replay of the same LUT; this is much tighter than the published
        # Jakob-Hanika RMS error of ~3e-3.
        assert g == pytest.approx(e, abs=5e-4), f"{name}: got={got} expected={expected}"


def test_rgb_albedo_spectrum_sample_matches_eval_at():
    rsp = astroray.RGBAlbedoSpectrum([0.8, 0.2, 0.1])
    wl = astroray.SampledWavelengths.sample_uniform(0.4)
    sampled = rsp.sample(wl)
    for i in range(4):
        direct = rsp.eval_at(wl.lambda_(i))
        assert sampled[i] == pytest.approx(direct, abs=1e-6)


def test_rgb_unbounded_spectrum_scales_linearly():
    # HDR input — RGBAlbedoSpectrum would clamp to 1, RGBUnboundedSpectrum
    # pulls the magnitude out as a scale factor.
    rsp = astroray.RGBUnboundedSpectrum([2.0, 0.0, 0.0])
    assert rsp.scale > 0.0
    # At 620 nm, red reflectance for a saturated red should be > 0.5 of scale.
    val = rsp.eval_at(620.0)
    assert val > 0.5, f"unexpected red eval at 620nm: {val}"


def test_rgb_illuminant_spectrum_nonzero_in_visible_range():
    rsp = astroray.RGBIlluminantSpectrum([1.0, 1.0, 1.0])
    # In the eye's peak sensitivity region, white illuminant should yield a
    # clearly positive SPD.
    assert rsp.eval_at(555.0) > 0.0


# ---------------------------------------------------------------------------
# Helper tables.
# ---------------------------------------------------------------------------

def test_cie_cmf_has_expected_peak_at_555nm():
    cmf_555 = astroray.cie_cmf_1964_10deg(555.0)
    cmf_360 = astroray.cie_cmf_1964_10deg(360.0)
    # y_bar peaks near 555 nm for the 10° observer — value ~0.99.
    assert cmf_555.Y > 0.9
    assert cmf_360.Y < 0.01


def test_sample_d65_zero_outside_table_range():
    assert astroray.sample_d65(100.0) == 0.0
    assert astroray.sample_d65(1500.0) == 0.0


# ---------------------------------------------------------------------------
# Regression smoke: existing registries unchanged by pkg10.
# ---------------------------------------------------------------------------

def test_material_registry_untouched():
    names = astroray.material_registry_names()
    assert "lambertian" in names
    assert "metal" in names


def test_pass_registry_untouched():
    names = astroray.pass_registry_names()
    # OIDN denoiser is optional at build time; AOV passes are always present.
    assert "depth_aov" in names
    assert "normal_aov" in names
    assert "albedo_aov" in names
