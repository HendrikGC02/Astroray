"""
Chi-squared sampler validation gates for Astroray BSDFs.

Tests Disney BSDF lobes (diffuse, metallic, dielectric/glass) across a small
grid of roughness and incident angles using Pearson's chi-square goodness-of-fit
test with Šidák correction.

Constants from pbrt-v4 (Apache-2.0, Matt Pharr):
- 10^6 samples, 80×160 (θ,φ) bins, α=0.01, min expected frequency 5, 5 runs.

Mitsuba 3 chi² harness (BSD-3-Clause, Wenzel Jakob), ported to NumPy.
"""

import pytest
import numpy as np
import sys
import os

# Add parent directory to path to import chi2 module
sys.path.insert(0, os.path.dirname(__file__))
from chi2 import ChiSquareTest, SphericalDomain, HemisphericalDomain

try:
    import astroray
except ImportError:
    pytest.skip("astroray module not available", allow_module_level=True)


# pbrt-v4 constants
CHI2_SAMPLE_COUNT = 1_000_000  # 10^6 samples
CHI2_THETA_RES = 80  # Vertical resolution
CHI2_PHI_RES = 160  # Horizontal resolution (2:1 aspect for sphere)
CHI2_SIGNIFICANCE = 0.01  # α = 0.01
CHI2_MIN_FREQ = 5  # Minimum expected frequency for cell pooling
CHI2_RUNS = 5  # Number of independent runs for Šidák correction


def make_disney_material(renderer, **params):
    """Create a Disney BSDF material with given parameters."""
    base_color = params.pop("base_color", [0.8, 0.8, 0.8])
    mat_id = renderer.create_material("disney", base_color, params)
    return mat_id


def spherical_to_cartesian(theta, phi):
    """
    Convert spherical coordinates (theta, phi) to unit Cartesian vector.

    Uses Y-up convention to match makeMaterialTestRecord normal=[0,1,0].
    theta: polar angle from +Y axis [0, π]
    phi: azimuthal angle from +X axis [-π, π]

    Returns: [x, y, z] where y = cos(theta), x = sin(theta)*cos(phi), z = sin(theta)*sin(phi)
    """
    sin_theta = np.sin(theta)
    cos_theta = np.cos(theta)
    sin_phi = np.sin(phi)
    cos_phi = np.cos(phi)
    return np.array([sin_theta * cos_phi, cos_theta, sin_theta * sin_phi])


class BSDFSamplerAdapter:
    """
    Adapter for Astroray BSDF sampling to chi² test interface.

    The chi² harness expects:
    - sample_func(u2_array) -> (samples_3d, weights) or samples_3d
    - pdf_func(samples_3d) -> pdf_values

    Where u2_array is (2, N) uniform random samples in [0, 1]².

    BSDF convention: wo = outgoing to viewer (fixed), wi = incoming from light (sampled).
    """
    def __init__(self, renderer, material_id, wo):
        self.renderer = renderer
        self.material_id = material_id
        self.wo = wo  # Outgoing direction (from surface to viewer, fixed for test)

    def sample_func(self, u2_array):
        """
        Sample the BSDF given (2, N) uniform random samples.

        Returns (samples, weights) where samples is (3, N) directions and weights
        is (N,) indicator (1=valid, 0=dead). Dead samples (pdf=0, e.g. below horizon)
        don't contribute to histogram bins but count in normalization denominator.
        """
        # Force contiguous C-order for binding
        u2_contig = np.ascontiguousarray(u2_array, dtype=np.float32)
        wi_array, pdf_array = self.renderer.debug_bsdf_sample_batch(
            self.material_id, self.wo, u2_contig
        )
        # wi_array is (N, 3), transpose to (3, N) for chi² harness
        wi_array_t = wi_array.T
        weights = (pdf_array > 0).astype(np.float32)
        return (wi_array_t, weights)

    def pdf_func(self, wi_array_3n):
        """
        Evaluate PDF for given (3, N) incident directions.

        wi_array_3n is (3, N) from SphericalDomain.map_forward.
        """
        # Force contiguous C-order for binding
        wi_array = np.ascontiguousarray(wi_array_3n.T, dtype=np.float32)
        pdf_array = self.renderer.debug_bsdf_pdf_batch(
            self.material_id, self.wo, wi_array
        )
        return pdf_array


@pytest.mark.xfail(
    strict=False,
    reason="Disney SPEC-lobe sample/pdf shape mismatch under investigation "
    "(pkg123). Post-harness-validation state 2026-07-20: Lambertian anchor "
    "passes (p=0.23); diffuse-only Disney passes at normal incidence; every "
    "metallic config fails p~=0 with angle dependence -> the mismatch lives "
    "in the specular lobe's pdf vs its sample procedure. Invisible to "
    "furnace/parity gates (unbiased MC absorbs it); real MIS-weight impact "
    "via the one-sided integrator (see pkg120). Do NOT delete or soften: "
    "this gate documents a suspected real defect.")
@pytest.mark.parametrize("theta_deg", [0, 45, 75])
@pytest.mark.parametrize("roughness", [0.1, 0.4, 0.8])
def test_chi2_disney_metallic(theta_deg, roughness):
    """
    Chi² test for Disney BSDF metallic lobe.

    Tests metallic=1.0 at varying roughness and incident angles.
    """
    renderer = astroray.Renderer()

    # Create metallic material
    mat_id = make_disney_material(
        renderer,
        base_color=[0.95, 0.64, 0.54],  # Copper-ish
        metallic=1.0,
        roughness=roughness
    )

    # Outgoing direction (from surface to viewer)
    theta_rad = np.deg2rad(theta_deg)
    phi_rad = 0.0
    wo = spherical_to_cartesian(theta_rad, phi_rad)

    # Create adapter
    adapter = BSDFSamplerAdapter(renderer, mat_id, wo.tolist())

    # Run chi² test (Disney BSDF is reflection-only, so use hemisphere)
    domain = HemisphericalDomain()
    chi2_test = ChiSquareTest(
        domain=domain,
        sample_func=adapter.sample_func,
        pdf_func=adapter.pdf_func,
        sample_dim=2,
        sample_count=CHI2_SAMPLE_COUNT,
        res=CHI2_THETA_RES,
        ires=4,
        seed=42 + theta_deg * 100 + int(roughness * 10)  # Unique seed per config
    )

    result = chi2_test.run(
        significance_level=CHI2_SIGNIFICANCE,
        test_count=CHI2_RUNS,
        quiet=False
    )

    assert result, (
        f"Chi² test FAILED for Disney metallic "
        f"(roughness={roughness}, θ={theta_deg}°). "
        f"p-value={chi2_test.p_value:.6f}. "
        f"This indicates a BSDF sampling/PDF mismatch. "
        f"See chi2_data.py for histogram visualization."
    )


@pytest.mark.xfail(
    strict=False,
    reason="Fails at oblique incidence (theta=45) while normal incidence "
    "passes — consistent with the pkg123 spec-lobe mismatch leaking through "
    "the residual specular mixture weight even at specular=0. See the "
    "metallic gate's xfail note.")
@pytest.mark.parametrize("theta_deg", [45])
@pytest.mark.parametrize("roughness", [1.0])
def test_chi2_disney_diffuse(theta_deg, roughness):
    """
    Chi² test for Disney BSDF diffuse lobe.

    Tests diffuse-dominant material (roughness=1.0, metallic=0.0).
    """
    renderer = astroray.Renderer()

    # Create diffuse material
    mat_id = make_disney_material(
        renderer,
        base_color=[0.8, 0.8, 0.8],
        metallic=0.0,
        roughness=roughness,
        specular=0.0  # Suppress specular lobe for pure diffuse
    )

    # Viewing direction (wo = outgoing from surface to viewer)
    theta_rad = np.deg2rad(theta_deg)
    wo = spherical_to_cartesian(theta_rad, 0.0)

    # Create adapter
    adapter = BSDFSamplerAdapter(renderer, mat_id, wo.tolist())

    # Run chi² test (Disney BSDF is reflection-only, so use hemisphere)
    domain = HemisphericalDomain()
    chi2_test = ChiSquareTest(
        domain=domain,
        sample_func=adapter.sample_func,
        pdf_func=adapter.pdf_func,
        sample_dim=2,
        sample_count=CHI2_SAMPLE_COUNT,
        res=CHI2_THETA_RES,
        ires=4,
        seed=100 + theta_deg
    )

    result = chi2_test.run(
        significance_level=CHI2_SIGNIFICANCE,
        test_count=CHI2_RUNS,
        quiet=False
    )

    assert result, (
        f"Chi² test FAILED for Disney diffuse "
        f"(roughness={roughness}, θ={theta_deg}°). "
        f"p-value={chi2_test.p_value:.6f}"
    )


@pytest.mark.xfail(strict=False, reason="disney transmission needs full-sphere domain + pdf/sample investigation (pkg123)")
@pytest.mark.parametrize("theta_deg", [45])
@pytest.mark.parametrize("roughness", [0.0, 0.3])
def test_chi2_disney_glass(theta_deg, roughness):
    """
    Chi² test for Disney BSDF glass/dielectric lobe.

    Tests transmission=1.0 (glass) at varying roughness.
    """
    renderer = astroray.Renderer()

    # Create glass material
    mat_id = make_disney_material(
        renderer,
        base_color=[1.0, 1.0, 1.0],
        metallic=0.0,
        roughness=roughness,
        transmission=1.0,
        ior=1.5
    )

    # Viewing direction (wo = outgoing from surface to viewer)
    theta_rad = np.deg2rad(theta_deg)
    wo = spherical_to_cartesian(theta_rad, 0.0)

    # Create adapter
    adapter = BSDFSamplerAdapter(renderer, mat_id, wo.tolist())

    # Run chi² test (Disney BSDF is reflection-only, so use hemisphere)
    domain = HemisphericalDomain()
    chi2_test = ChiSquareTest(
        domain=domain,
        sample_func=adapter.sample_func,
        pdf_func=adapter.pdf_func,
        sample_dim=2,
        sample_count=CHI2_SAMPLE_COUNT,
        res=CHI2_THETA_RES,
        ires=4,
        seed=200 + theta_deg * 10 + int(roughness * 10)
    )

    result = chi2_test.run(
        significance_level=CHI2_SIGNIFICANCE,
        test_count=CHI2_RUNS,
        quiet=False
    )

    assert result, (
        f"Chi² test FAILED for Disney glass "
        f"(roughness={roughness}, θ={theta_deg}°). "
        f"p-value={chi2_test.p_value:.6f}"
    )


# Full grid (marked slow) - comprehensive test across parameter space
@pytest.mark.xfail(strict=False, reason="disney pdf/sample mismatch under investigation (pkg123)")
@pytest.mark.slow
@pytest.mark.parametrize("theta_deg", [0, 30, 45, 60, 75])
@pytest.mark.parametrize("roughness", [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
@pytest.mark.parametrize("metallic", [0.0, 0.5, 1.0])
def test_chi2_disney_full_grid(theta_deg, roughness, metallic):
    """
    Comprehensive chi² test across full Disney BSDF parameter grid.

    This is the full dense sweep. Run with: pytest -v -m slow
    """
    renderer = astroray.Renderer()

    mat_id = make_disney_material(
        renderer,
        base_color=[0.8, 0.8, 0.8],
        metallic=metallic,
        roughness=roughness
    )

    theta_rad = np.deg2rad(theta_deg)
    wi = spherical_to_cartesian(theta_rad, 0.0)

    adapter = BSDFSamplerAdapter(renderer, mat_id, wi.tolist())

    domain = SphericalDomain()
    chi2_test = ChiSquareTest(
        domain=domain,
        sample_func=adapter.sample_func,
        pdf_func=adapter.pdf_func,
        sample_dim=2,
        sample_count=CHI2_SAMPLE_COUNT,
        res=CHI2_THETA_RES,
        ires=4,
        seed=1000 + theta_deg * 100 + int(roughness * 10) + int(metallic * 1000)
    )

    result = chi2_test.run(
        significance_level=CHI2_SIGNIFICANCE,
        test_count=CHI2_RUNS,
        quiet=False
    )

    assert result, (
        f"Chi² test FAILED for Disney BSDF "
        f"(metallic={metallic}, roughness={roughness}, θ={theta_deg}°). "
        f"p-value={chi2_test.p_value:.6f}"
    )
