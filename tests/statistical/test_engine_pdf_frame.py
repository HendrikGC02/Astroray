"""
Test if engine Material::pdf() returns values in the expected frame.

Compares engine Lambertian PDF against closed-form cosθ/π at specific directions.
"""

import numpy as np
import sys
sys.path.insert(0, 'build_cuda/Release')

try:
    import astroray
except ImportError:
    print("Skipping - astroray not available")
    sys.exit(0)


def test_engine_pdf_frame():
    """
    Test engine PDF at known directions to verify frame convention.

    For Y-up normal, Lambertian PDF should be cosθ/π where cosθ = y-component.
    """
    r = astroray.Renderer()
    mat = r.create_material('lambertian', [1.0, 1.0, 1.0], {})

    wo = [0.0, 1.0, 0.0]  # Viewer at normal (Y-up)

    # Test a grid of directions
    test_cases = [
        ([0.0, 1.0, 0.0], 1.0/np.pi, "Normal direction"),
        ([0.0, 0.707, 0.707], 0.707/np.pi, "45deg from normal"),
        ([1.0, 0.0, 0.0], 0.0, "Horizontal (grazing)"),
        ([0.0, -1.0, 0.0], 0.0, "Below horizon"),
    ]

    print("Engine PDF frame test:")
    all_pass = True
    for wi, expected_pdf, label in test_cases:
        wi_array = np.array([wi], dtype=np.float32)
        pdf = r.debug_bsdf_pdf_batch(mat, wo, wi_array)[0]

        error = abs(pdf - expected_pdf)
        status = "PASS" if error < 0.01 else "FAIL"
        if error >= 0.01:
            all_pass = False

        print(f"  {label:25s}: pdf={pdf:.6f}, expected={expected_pdf:.6f}, error={error:.6f} [{status}]")

    if all_pass:
        print("\nPASS: Engine PDF returns expected values - frame convention is correct")
    else:
        print("\nFAIL: Engine PDF doesn't match expected - frame issue")

    return all_pass


if __name__ == "__main__":
    test_engine_pdf_frame()
