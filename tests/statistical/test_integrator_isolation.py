"""
Isolate tabulate_pdf integrator bug with closed-form PDF.

Tests if the integration arithmetic is correct independent of engine bindings.
Lambertian PDF in [φ, cosθ] domain: pdf(φ, μ) = μ/π where μ=cosθ ∈ [0,1].
Should integrate to 1.0 over hemisphere: ∫[-π,π] ∫[0,1] (μ/π) dμ dφ = 1.0
"""

import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from chi2 import ChiSquareTest, HemisphericalDomain


def closed_form_lambertian_pdf(wi_directions_3n):
    """
    Closed-form Lambertian PDF: cosθ/π in solid angle measure.

    For HemisphericalDomain (Y-up): cosθ = wi[1] (y-component).
    """
    cos_theta = wi_directions_3n[1]  # Y-up normal
    return np.maximum(0.0, cos_theta / np.pi)


def test_pure_numpy_integration():
    """
    Test tabulate_pdf integration with closed-form Lambertian PDF.

    This bypasses engine bindings entirely - feeds a lambda directly to the integrator.
    If this fails, the bug is in tabulate_pdf arithmetic (cell area, trapezoid weights).
    If this passes, the bug is in how we call the engine PDF (frame mapping).
    """
    domain = HemisphericalDomain()

    # Create a minimal ChiSquareTest instance just to use tabulate_pdf
    class DummySampler:
        pass

    chi2_test = ChiSquareTest(
        domain=domain,
        sample_func=lambda u: np.zeros((3, 1)),  # Dummy, won't be called
        pdf_func=closed_form_lambertian_pdf,
        sample_dim=2,
        sample_count=100000,
        res=40,  # Smaller for quick test
        ires=4,
        seed=42
    )

    # Only run tabulate_pdf (skip histogram)
    chi2_test.tabulate_pdf()

    pdf_sum = float(chi2_test.pdf_sum)

    print(f"Pure NumPy integration test:")
    print(f"  PDF sum = {pdf_sum:.6f} (expected 1.000000)")
    print(f"  Error = {abs(pdf_sum - 1.0):.6f}")

    # Should be within numerical integration tolerance
    assert abs(pdf_sum - 1.0) < 0.01, \
        f"Integrator bug: closed-form Lambertian PDF integrates to {pdf_sum:.6f}, expected 1.0"

    print("PASS: Pure NumPy integration correct - integrator arithmetic is correct")


if __name__ == "__main__":
    test_pure_numpy_integration()
