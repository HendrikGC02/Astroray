"""Test if Disney PDF integrates to 1.0."""
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


def test_disney_diffuse_pdf_normalization():
    """Check if Disney diffuse PDF integrates to 1.0."""
    renderer = astroray.Renderer()

    # Pure Disney diffuse
    mat_id = renderer.create_material("disney", [1.0, 1.0, 1.0], {
        "metallic": 0.0,
        "roughness": 1.0,
        "specular": 0.0,
    })

    wo = [0.0, 1.0, 0.0]  # View from normal

    def pdf_func(wi_array_3n):
        wi_array = np.ascontiguousarray(wi_array_3n.T, dtype=np.float32)
        return renderer.debug_bsdf_pdf_batch(mat_id, wo, wi_array)

    # Just integrate the PDF (no sampling)
    domain = HemisphericalDomain()
    chi2_test = ChiSquareTest(
        domain=domain,
        sample_func=lambda u: np.zeros((3, len(u[0]))),  # Dummy
        pdf_func=pdf_func,
        sample_dim=2,
        sample_count=1000,  # Doesn't matter for PDF-only
        res=80,
        ires=4,
        seed=42
    )

    # Manually run just the PDF tabulation
    chi2_test.tabulate_pdf()

    print(f"\nDisney diffuse PDF integral: {chi2_test.pdf_sum:.6f}")
    print(f"Expected: 1.000000")
    print(f"Ratio: {chi2_test.pdf_sum:.6f}")

    # If this is ~0.75, Disney's pdf() is under-normalized
    # If this is ~1.0, the problem is elsewhere

    assert abs(chi2_test.pdf_sum - 1.0) < 0.01, \
        f"Disney PDF integrates to {chi2_test.pdf_sum}, not 1.0 (PDF normalization bug)"
