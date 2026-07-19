"""
Lambertian anchor test for chi² harness validation.

Tests that pure Lambertian BSDF passes chi² (pdf = cos(θ)/π analytic).
This proves the harness conventions are correct before testing Disney.
"""

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


CHI2_SAMPLE_COUNT = 100_000  # Smaller for quick anchor test
CHI2_THETA_RES = 40
CHI2_SIGNIFICANCE = 0.01


class BSDFSamplerAdapter:
    def __init__(self, renderer, material_id, wo):
        self.renderer = renderer
        self.material_id = material_id
        self.wo = wo

    def sample_func(self, u2_array):
        wi_array, pdf_array = self.renderer.debug_bsdf_sample_batch(
            self.material_id, self.wo, u2_array.astype(np.float32)
        )
        # Return sampled directions WITHOUT weights — Material::sample() already
        # generates from the target distribution p(wi), so samples are unweighted
        return wi_array.T  # Just the directions, no weights

    def pdf_func(self, wi_array_3n):
        wi_array = wi_array_3n.T.astype(np.float32)
        pdf_array = self.renderer.debug_bsdf_pdf_batch(
            self.material_id, self.wo, wi_array
        )

        # Debug: check if PDFs match closed-form
        if not hasattr(self, '_debug_logged'):
            print(f"\nDEBUG pdf_func: first 5 calls")
            for i in range(min(5, len(pdf_array))):
                cost = wi_array[i, 1]  # Y-component
                expected = max(0.0, cost / np.pi)
                print(f"  wi=({wi_array[i,0]:.3f},{wi_array[i,1]:.3f},{wi_array[i,2]:.3f}), cost={cost:.3f}, pdf={pdf_array[i]:.6f}, expect={expected:.6f}")
            self._debug_logged = True

        return pdf_array


def test_lambertian_pdf_manual():
    """Manual sanity check: Lambertian PDF should be cos(θ)/π."""
    r = astroray.Renderer()
    # Note: create_material doesn't expose normal parameter; makeMaterialTestRecord
    # uses default normal=[0,1,0]. For hemisphere testing, we need Z-up.
    # The PDF test here uses Y-up which is fine for manual verification.
    mat = r.create_material('lambertian', [0.8, 0.8, 0.8], {})

    wo = [0.0, 1.0, 0.0]  # Viewer direction (Y-up normal in makeMaterialTestRecord)

    # Test PDF at normal direction
    wi_test = np.array([[0.0, 1.0, 0.0]], dtype=np.float32)
    pdf_test = r.debug_bsdf_pdf_batch(mat, wo, wi_test)
    expected_pdf_at_normal = 1.0 / np.pi

    print(f"Lambertian PDF at normal: {pdf_test[0]:.6f}, expected: {expected_pdf_at_normal:.6f}")

    # Test PDF below horizon (should be 0)
    wi_below = np.array([[0.0, -1.0, 0.0]], dtype=np.float32)
    pdf_below = r.debug_bsdf_pdf_batch(mat, wo, wi_below)

    print(f"Lambertian PDF below horizon: {pdf_below[0]:.6f}, expected: 0.0")

    assert pdf_test[0] > 0, f"PDF at normal should be positive, got {pdf_test[0]}"
    assert abs(pdf_test[0] - expected_pdf_at_normal) < 0.01, \
        f"PDF at normal should be ~{expected_pdf_at_normal:.6f}, got {pdf_test[0]:.6f}"
    assert pdf_below[0] == 0.0, f"PDF below horizon should be 0, got {pdf_below[0]}"


def test_chi2_lambertian_anchor():
    """
    Chi² test for pure Lambertian — harness validation anchor.

    If this passes, harness conventions are correct.
    If this fails, the harness has a bug, not the BSDF.
    """
    r = astroray.Renderer()
    mat = r.create_material('lambertian', [1.0, 1.0, 1.0], {})

    # Viewer at normal incidence
    wo = [0.0, 1.0, 0.0]

    adapter = BSDFSamplerAdapter(r, mat, wo)

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
        test_count=1,
        quiet=False
    )

    assert result, (
        f"Chi² FAILED for Lambertian anchor. "
        f"p-value={chi2_test.p_value:.6f}. "
        f"This indicates a HARNESS BUG, not a BSDF bug. "
        f"Histogram sum={chi2_test.histogram_sum:.6f}, "
        f"PDF sum={chi2_test.pdf_sum:.6f}"
    )
