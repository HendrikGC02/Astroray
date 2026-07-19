"""Manual test of Disney diffuse BSDF."""
import pytest
import numpy as np

try:
    import astroray
except ImportError:
    pytest.skip("astroray module not available", allow_module_level=True)


def test_disney_diffuse_manual():
    renderer = astroray.Renderer()

    # Make Disney diffuse material
    params = {
        "type": "disneyBRDF",
        "baseColor": [0.8, 0.8, 0.8],
        "metallic": 0.0,
        "roughness": 1.0,
        "specular": 0.0,
    }
    mat_id = renderer.add_material(params)

    # Viewing direction at 45° from normal
    theta = np.deg2rad(45)
    wo = [np.cos(theta), np.sin(theta), 0.0]

    print(f"\nwo = {wo}")

    # Sample 10 directions
    u2_array = np.random.rand(2, 10).astype(np.float32)
    u2_contig = np.ascontiguousarray(u2_array, dtype=np.float32)
    wi_array, pdf_array = renderer.debug_bsdf_sample_batch(mat_id, wo, u2_contig)

    print(f"\nSampled {len(wi_array)} directions:")
    for i in range(min(5, len(wi_array))):
        wi = wi_array[i]
        pdf = pdf_array[i]
        print(f"  wi[{i}] = ({wi[0]:.3f}, {wi[1]:.3f}, {wi[2]:.3f}), pdf={pdf:.6f}")

    # Check normal direction PDF
    wi_normal = np.ascontiguousarray(np.array([[0.0, 1.0, 0.0]]), dtype=np.float32)
    pdf_normal = renderer.debug_bsdf_pdf_batch(mat_id, wo, wi_normal)
    print(f"\nPDF at normal [0,1,0]: {pdf_normal[0]:.6f}")
    print(f"Expected (Lambertian at normal): {1.0/np.pi:.6f}")
    print(f"But Disney diffuse uses different lobe scaling!")
