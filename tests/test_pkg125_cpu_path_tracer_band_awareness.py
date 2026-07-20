"""pkg125: CPU `path_tracer` (SpectralPathTracer) band awareness.

Regression test for the pkg55-C3 side finding: `path_tracer` ignored
`set_wavelength_range` and always sampled the compile-time default band
(`astroray.kLambdaMin`/`kLambdaMax` = 360/830 nm, spectrum.h:26-27), so a
request for an out-of-visible band (e.g. NIR [800, 900]) silently rendered
as a normal visible-RGB image instead of the physically-correct near-black
result.

Fix (Option A-minimal, mirroring multiwavelength_path_tracer.cpp:45-46,
74-75): `SpectralPathTracer` now reads `lambda_min`/`lambda_max` from its
`ParamDict` and threads them into `SampledWavelengths::sampleUniform`. No
new gating logic was added — the "honest black" outcome falls out of the
existing `SampledSpectrum::toXYZ` -> CIE CMF projection: `sampleTable()`
(src/spectrum.cpp:36-39) returns exactly 0 for any wavelength outside
[kLambdaMin, kLambdaMax] = [360, 830], so an NIR-band sample set (mostly
> 830 nm) collapses to near-zero XYZ regardless of the material's own
spectral response.

These tests are CPU-only. Skipped entirely if the `astroray` extension
module is not importable (no build available in this environment).
"""

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


def _build_scene(width=32, height=32, seed=42):
    """Simple lit Lambertian sphere scene (mirrors test_multiwavelength.py::_render)."""
    r = astroray.Renderer()
    r.setup_camera(
        look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=40, aspect_ratio=1.0, aperture=0.0, focus_dist=3.0,
        width=width, height=height,
    )
    # Seed 0 is the std::random_device sentinel (non-deterministic) in this
    # engine (raytracer.h:2803) -- always pin a nonzero seed for determinism.
    r.set_seed(seed)
    r.set_background_color([0.1, 0.1, 0.1])
    mat = r.create_material("lambertian", [0.2, 0.6, 0.2], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 10.0})
    r.add_sphere([0, 2.5, 0], 0.5, light)
    return r


# ---------------------------------------------------------------------------
# 1. NIR band awareness: path_tracer must render near-black, not visible-RGB.
# ---------------------------------------------------------------------------

def test_nir_band_path_tracer_near_black():
    """FAILS on pre-pkg125 main: path_tracer ignores set_wavelength_range and
    renders the NIR request [800, 900] as a normal visible-RGB image (pkg55-C3
    measured mean ~0.1331). PASSES after the fix: NIR mostly falls outside the
    CIE CMF table support (> 830 nm), so the XYZ projection is near-zero,
    matching the GPU path_tracer's measured band-aware NIR result (~1.8e-4)."""
    r = _build_scene(seed=42)
    r.set_wavelength_range(800.0, 900.0)
    r.set_integrator("path_tracer")
    pixels = np.array(
        r.render(samples_per_pixel=16, max_depth=4, apply_gamma=False),
        dtype=np.float32,
    )
    assert np.all(np.isfinite(pixels)), "NIR path_tracer render has non-finite pixels"
    mean = float(pixels.mean())
    assert mean < 0.01, (
        f"NIR path_tracer not near-black: mean={mean:.4f} "
        "(pre-fix bug renders visible-RGB, pkg55-C3 measured ~0.1331)"
    )


def test_nir_band_path_tracer_agrees_with_multiwavelength():
    """Cross-check (spec verification gate): once band-aware, path_tracer (NEE)
    and multiwavelength_path_tracer (naive, already band-aware pre-pkg125)
    must agree that the NIR band is near-black -- they differ only by NEE
    presence, not by which wavelengths get sampled."""
    r_pt = _build_scene(seed=42)
    r_pt.set_wavelength_range(800.0, 900.0)
    r_pt.set_integrator("path_tracer")
    pt_pixels = np.array(
        r_pt.render(samples_per_pixel=16, max_depth=4, apply_gamma=False),
        dtype=np.float32,
    )

    r_mw = _build_scene(seed=42)
    r_mw.set_wavelength_range(800.0, 900.0)
    r_mw.set_integrator("multiwavelength_path_tracer")
    mw_pixels = np.array(
        r_mw.render(samples_per_pixel=16, max_depth=4, apply_gamma=False),
        dtype=np.float32,
    )

    assert np.all(np.isfinite(pt_pixels))
    assert np.all(np.isfinite(mw_pixels))
    pt_mean = float(pt_pixels.mean())
    mw_mean = float(mw_pixels.mean())
    assert pt_mean < 0.01, f"path_tracer NIR mean not near-black: {pt_mean:.4f}"
    assert mw_mean < 0.01, f"multiwavelength_path_tracer NIR mean not near-black: {mw_mean:.4f}"
    # Both near-zero by the same CMF-clamp mechanism -- absolute (not ratio)
    # comparison, per the MC-noise-vs-deterministic memory: a ratio of two
    # near-zero means is dominated by MC noise, not physics.
    assert abs(pt_mean - mw_mean) < 0.01, (
        f"path_tracer vs multiwavelength_path_tracer NIR means diverge: "
        f"{pt_mean:.4f} vs {mw_mean:.4f}"
    )


# ---------------------------------------------------------------------------
# 2. Visible-band no-regression: the default (band unset) path is unchanged.
# ---------------------------------------------------------------------------

def test_visible_band_default_path_unchanged():
    """No-regression gate: SpectralPathTracer's constructor now reads
    lambda_min/lambda_max via ParamDict::getFloat(key, astroray.kLambdaMin /
    kLambdaMax) -- the SAME constants sampleUniform(u) used implicitly
    pre-pkg125 (this integrator previously called
    sampleUniform(dist01(gen)) with no explicit band, relying on
    SampledWavelengths::sampleUniform's own default arguments, spectrum.h:101-103).

    Note: the pkg125 spec prose states the default band is "[380, 780]": the
    actual compile-time constants (spectrum.h:26-27, exposed as
    astroray.kLambdaMin/kLambdaMax) are 360/830, not 380/780. This test pins
    to the REAL constants so it verifies true byte-for-byte no-regression
    against the pre-fix binary rather than the spec's inexact paraphrase.

    Renders with the band never set, and with the band set explicitly to the
    default constants, must be bit-identical for the same seed -- proving the
    fallback wired in by this fix reproduces the pre-fix implicit default."""
    r_default = _build_scene(seed=7)
    r_default.set_integrator("path_tracer")
    default_pixels = np.array(
        r_default.render(samples_per_pixel=8, max_depth=4, apply_gamma=False),
        dtype=np.float32,
    )

    r_explicit = _build_scene(seed=7)
    r_explicit.set_wavelength_range(astroray.kLambdaMin, astroray.kLambdaMax)
    r_explicit.set_integrator("path_tracer")
    explicit_pixels = np.array(
        r_explicit.render(samples_per_pixel=8, max_depth=4, apply_gamma=False),
        dtype=np.float32,
    )

    assert np.array_equal(default_pixels, explicit_pixels), (
        "path_tracer with no wavelength range set must be bit-identical to "
        "an explicit set_wavelength_range(kLambdaMin, kLambdaMax) call"
    )


def test_visible_band_render_still_non_black():
    """Sanity: an ordinary visible-band render (band unset) still produces a
    lit, non-black image -- the fix must not have broken the default path
    into an all-black render."""
    r = _build_scene(seed=42)
    r.set_integrator("path_tracer")
    pixels = np.array(
        r.render(samples_per_pixel=16, max_depth=4, apply_gamma=False),
        dtype=np.float32,
    )
    assert np.all(np.isfinite(pixels))
    assert np.any(pixels > 0.01), "Default visible-band path_tracer render is unexpectedly black"
