"""
Isolate adapter direction-construction bug.

Tests if the direction-vector construction/reshape in the adapter chain is correct.
Uses closed-form Lambertian PDF but routes through the SAME reshape path as engine.
"""

import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from chi2 import ChiSquareTest, HemisphericalDomain


class ClosedFormAdapter:
    """
    Adapter using closed-form PDF but SAME direction construction as BSDFSamplerAdapter.

    This exercises the exact reshape/transpose path the engine adapter uses,
    but with a known-correct PDF function. If this integrates wrong, the bug
    is in direction construction, NOT in the engine.
    """
    def __init__(self):
        pass

    def sample_func(self, u2_array):
        # Dummy - just return zeros (won't be used)
        return np.zeros((3, u2_array.shape[1]))

    def pdf_func(self, wi_array_3n):
        """
        Closed-form Lambertian PDF: cosθ/π.

        wi_array_3n is (3, N) from domain.map_forward.
        This mimics BSDFSamplerAdapter's reshape: transpose to (N, 3),
        then extract Y component.
        """
        # SAME transpose as BSDFSamplerAdapter
        wi_array = wi_array_3n.T.astype(np.float32)  # (N, 3)

        # Extract Y component (cosθ for Y-up normal)
        cos_theta = wi_array[:, 1]

        # Closed-form Lambertian PDF
        pdf_array = np.maximum(0.0, cos_theta / np.pi)

        return pdf_array


def test_direction_construction():
    """
    Test if adapter's direction construction/reshape is correct.

    Uses closed-form PDF through the SAME adapter reshape path.
    If this gives 0.74, the bug is in direction construction.
    If this gives 1.0, the bug is in the engine binding.
    """
    domain = HemisphericalDomain()
    adapter = ClosedFormAdapter()

    chi2_test = ChiSquareTest(
        domain=domain,
        sample_func=adapter.sample_func,
        pdf_func=adapter.pdf_func,
        sample_dim=2,
        sample_count=100000,
        res=40,
        ires=4,
        seed=42
    )

    # Only run tabulate_pdf (skip histogram)
    chi2_test.tabulate_pdf()

    pdf_sum = float(chi2_test.pdf_sum)

    print(f"Direction construction test:")
    print(f"  PDF sum = {pdf_sum:.6f} (expected 1.000000)")
    print(f"  Error = {abs(pdf_sum - 1.0):.6f}")

    if abs(pdf_sum - 0.74) < 0.01:
        print("\nFAIL: PDF sum ~0.74 - bug is in DIRECTION CONSTRUCTION/RESHAPE")
        print("      The adapter transpose/reshape path is corrupting directions")
    elif abs(pdf_sum - 1.0) < 0.01:
        print("\nPASS: PDF sum ~1.0 - direction construction is CORRECT")
        print("      Bug must be in engine binding or engine itself")
    else:
        print(f"\nUNEXPECTED: PDF sum = {pdf_sum:.6f} (neither 0.74 nor 1.0)")

    return pdf_sum


if __name__ == "__main__":
    test_direction_construction()
