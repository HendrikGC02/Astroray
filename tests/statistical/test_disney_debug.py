"""Debug Disney BSDF sampling."""
import pytest
import numpy as np

try:
    import astroray
except ImportError:
    pytest.skip("astroray module not available", allow_module_level=True)


def test_disney_sample_direction_check():
    """Check if Disney BSDF samples are in upper hemisphere."""
    renderer = astroray.Renderer()

    params = {
        "type": "disneyBRDF",
        "baseColor": [0.8, 0.8, 0.8],
        "metallic": 0.0,
        "roughness": 1.0,
        "specular": 0.0,
    }
    mat_id = renderer.create_material("disney", [0.8, 0.8, 0.8], {
        "metallic": 0.0,
        "roughness": 1.0,
        "specular": 0.0,
    })

    # Viewing direction at 45° from normal (Y-up)
    theta = np.deg2rad(45)
    wo = [np.sin(theta), np.cos(theta), 0.0]  # Y-up: [sin, cos, 0]

    print(f"\nwo (viewing) = [{wo[0]:.3f}, {wo[1]:.3f}, {wo[2]:.3f}]")

    # Sample 100 directions
    N = 100
    u2_array = np.random.rand(2, N).astype(np.float32)
    u2_contig = np.ascontiguousarray(u2_array, dtype=np.float32)
    wi_array, pdf_array = renderer.debug_bsdf_sample_batch(mat_id, wo, u2_contig)

    print(f"\nSampled {len(wi_array)} directions:")

    # Check hemisphere constraint (Y > 0)
    above_horizon = np.sum(wi_array[:, 1] > 0)
    below_horizon = np.sum(wi_array[:, 1] < 0)
    at_horizon = np.sum(np.abs(wi_array[:, 1]) < 1e-6)

    print(f"  Above horizon (Y>0): {above_horizon}")
    print(f"  Below horizon (Y<0): {below_horizon}")
    print(f"  At horizon (Y~0): {at_horizon}")

    # Show first 10 samples
    print(f"\nFirst 10 samples:")
    for i in range(min(10, len(wi_array))):
        wi = wi_array[i]
        pdf = pdf_array[i]
        print(f"  [{i}] wi=({wi[0]:+.3f},{wi[1]:+.3f},{wi[2]:+.3f}), pdf={pdf:.6f}")

    # Check PDF statistics
    print(f"\nPDF statistics:")
    print(f"  min={np.min(pdf_array):.6f}, max={np.max(pdf_array):.6f}")
    print(f"  mean={np.mean(pdf_array):.6f}, median={np.median(pdf_array):.6f}")
    print(f"  Zero PDFs: {np.sum(pdf_array == 0)}")

    assert above_horizon > 0, "No samples above horizon!"
    assert below_horizon == 0, f"{below_horizon} samples below horizon (should be 0 for reflection BSDF)"
