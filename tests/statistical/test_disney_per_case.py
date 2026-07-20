"""Per-case Disney BSDF chi² breakdown."""
import pytest
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from chi2 import ChiSquareTest, HemisphericalDomain

try:
    import astroray
except ImportError:
    pytest.skip("astroray module not available", allow_module_level=True)


CHI2_SAMPLE_COUNT = 1_000_000
CHI2_THETA_RES = 80
CHI2_SIGNIFICANCE = 0.01
CHI2_RUNS = 1  # Single run for per-case diagnostics


def spherical_to_cartesian(theta, phi):
    """Y-up convention."""
    sin_theta = np.sin(theta)
    cos_theta = np.cos(theta)
    sin_phi = np.sin(phi)
    cos_phi = np.cos(phi)
    return np.array([sin_theta * cos_phi, cos_theta, sin_theta * sin_phi])


class BSDFAdapter:
    def __init__(self, renderer, material_id, wo):
        self.renderer = renderer
        self.material_id = material_id
        self.wo = wo

    def sample_func(self, u2_array):
        u2_contig = np.ascontiguousarray(u2_array, dtype=np.float32)
        wi_array, pdf_array = self.renderer.debug_bsdf_sample_batch(
            self.material_id, self.wo, u2_contig
        )
        return wi_array.T

    def pdf_func(self, wi_array_3n):
        wi_array = np.ascontiguousarray(wi_array_3n.T, dtype=np.float32)
        pdf_array = self.renderer.debug_bsdf_pdf_batch(
            self.material_id, self.wo, wi_array
        )
        return pdf_array


@pytest.mark.parametrize("config", [
    # Pure diffuse (should behave like Lambertian)
    ("diffuse_rough", {"metallic": 0.0, "roughness": 1.0, "specular": 0.0}),

    # Metallic (reflection only)
    ("metal_low_rough", {"metallic": 1.0, "roughness": 0.1}),
    ("metal_mid_rough", {"metallic": 1.0, "roughness": 0.4}),
    ("metal_high_rough", {"metallic": 1.0, "roughness": 0.8}),

    # Glass (transmission - NEEDS FULL SPHERE)
    ("glass_rough0.0", {"transmission": 1.0, "roughness": 0.0, "ior": 1.5}),
    ("glass_rough0.3", {"transmission": 1.0, "roughness": 0.3, "ior": 1.5}),
])
def test_disney_per_case(config):
    """Per-case Disney BSDF chi² test."""
    name, params = config
    renderer = astroray.Renderer()

    mat_id = renderer.create_material("disney", [0.8, 0.8, 0.8], params)

    # Viewing direction at 45° from normal
    theta = np.deg2rad(45)
    wo = spherical_to_cartesian(theta, 0.0).tolist()

    adapter = BSDFAdapter(renderer, mat_id, wo)
    domain = HemisphericalDomain()

    chi2_test = ChiSquareTest(
        domain=domain,
        sample_func=adapter.sample_func,
        pdf_func=adapter.pdf_func,
        sample_dim=2,
        sample_count=CHI2_SAMPLE_COUNT,
        res=CHI2_THETA_RES,
        ires=4,
        seed=42
    )

    result = chi2_test.run(
        significance_level=CHI2_SIGNIFICANCE,
        test_count=CHI2_RUNS,
        quiet=False
    )

    # Extract results
    hist_sum = chi2_test.histogram_sum if hasattr(chi2_test, 'histogram_sum') else 0
    pdf_sum = chi2_test.pdf_sum if hasattr(chi2_test, 'pdf_sum') else 0
    p_value = chi2_test.p_value

    print(f"\n{name}: hist={hist_sum:.6f}, pdf={pdf_sum:.6f}, p={p_value:.6f}, {'PASS' if result else 'FAIL'}")

    # Don't assert - just collect data
