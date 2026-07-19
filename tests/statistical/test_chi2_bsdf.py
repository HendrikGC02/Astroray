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
from chi2 import ChiSquareTest, SphericalDomain

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
    """Convert spherical coordinates (theta, phi) to unit Cartesian vector."""
    sin_theta = np.sin(theta)
    cos_theta = np.cos(theta)
    sin_phi = np.sin(phi)
    cos_phi = np.cos(phi)
    return np.array([sin_theta * cos_phi, sin_theta * sin_phi, cos_theta])


class BSDFSamplerAdapter:
    """
    Adapter for Astroray BSDF sampling to chi² test interface.

    The chi² harness expects:
    - sample_func(u2_array) -> (samples_3d, weights) or samples_3d
    - pdf_func(samples_3d) -> pdf_values

    Where u2_array is (2, N) uniform random samples in [0, 1]².
    """
    def __init__(self, renderer, material_id, wi):
        self.renderer = renderer
        self.material_id = material_id
        self.wi = wi  # Incoming direction (from surface to viewer)

    def sample_func(self, u2_array):
        """
        Sample the BSDF given (2, N) uniform random samples.

        Returns (wo_array, pdf_array) where wo_array is (3, N) and pdf_array is (N,).
        The chi² harness expects samples as (3, N) for SphericalDomain.map_backward.
        """
        # Call the batched sampler
        wo_array, pdf_array = self.renderer.debug_bsdf_sample_batch(
            self.material_id, self.wi, u2_array.astype(np.float32)
        )
        # wo_array is (N, 3), transpose to (3, N) for chi² harness
        wo_array_t = wo_array.T
        return (wo_array_t, pdf_array)

    def pdf_func(self, wo_array_3n):
        """
        Evaluate PDF for given (3, N) outgoing directions.

        wo_array_3n is (3, N) from SphericalDomain.map_forward.
        """
        # Transpose to (N, 3) for the binding
        wo_array = wo_array_3n.T.astype(np.float32)
        pdf_array = self.renderer.debug_bsdf_pdf_batch(
            self.material_id, self.wi, wo_array
        )
        return pdf_array


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

    # Incident direction (from surface to viewer)
    theta_rad = np.deg2rad(theta_deg)
    phi_rad = 0.0
    wi = spherical_to_cartesian(theta_rad, phi_rad)

    # Create adapter
    adapter = BSDFSamplerAdapter(renderer, mat_id, wi.tolist())

    # Run chi² test
    domain = SphericalDomain()
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

    # Incident direction
    theta_rad = np.deg2rad(theta_deg)
    wi = spherical_to_cartesian(theta_rad, 0.0)

    # Create adapter
    adapter = BSDFSamplerAdapter(renderer, mat_id, wi.tolist())

    # Run chi² test
    domain = SphericalDomain()
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

    # Incident direction
    theta_rad = np.deg2rad(theta_deg)
    wi = spherical_to_cartesian(theta_rad, 0.0)

    # Create adapter
    adapter = BSDFSamplerAdapter(renderer, mat_id, wi.tolist())

    # Run chi² test
    domain = SphericalDomain()
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
