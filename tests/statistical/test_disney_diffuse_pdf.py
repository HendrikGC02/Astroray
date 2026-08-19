"""Manual Disney diffuse PDF test."""
import pytest
import numpy as np

try:
    import astroray
except ImportError:
    pytest.skip("astroray module not available", allow_module_level=True)


def test_disney_diffuse_pdf_vs_lambertian():
    """Compare Disney diffuse PDF to Lambertian."""
    renderer = astroray.Renderer()

    # Lambertian
    lamb_id = renderer.create_material("lambertian", [0.8, 0.8, 0.8], {})

    # Disney diffuse (should be similar to Lambertian)
    disney_id = renderer.create_material("disney", [0.8, 0.8, 0.8], {
        "metallic": 0.0,
        "roughness": 1.0,
        "specular": 0.0,
    })

    # Test at normal direction
    wo = [0.0, 1.0, 0.0]  # View from normal
    wi_normal = np.ascontiguousarray(np.array([[0.0, 1.0, 0.0]]), dtype=np.float32)

    pdf_lamb = renderer.debug_bsdf_pdf_batch(lamb_id, wo, wi_normal)[0]
    pdf_disney = renderer.debug_bsdf_pdf_batch(disney_id, wo, wi_normal)[0]

    print(f"\nPDF at normal [0,1,0]:")
    print(f"  Lambertian: {pdf_lamb:.6f}")
    print(f"  Disney diffuse: {pdf_disney:.6f}")
    print(f"  Expected (1/pi): {1.0/np.pi:.6f}")
    print(f"  Disney/Lambertian ratio: {pdf_disney/pdf_lamb:.6f}")

    # Test at 45° from normal
    theta = np.deg2rad(45)
    cos_theta = np.cos(theta)
    wi_45 = np.ascontiguousarray(np.array([[np.sin(theta), cos_theta, 0.0]]), dtype=np.float32)

    pdf_lamb_45 = renderer.debug_bsdf_pdf_batch(lamb_id, wo, wi_45)[0]
    pdf_disney_45 = renderer.debug_bsdf_pdf_batch(disney_id, wo, wi_45)[0]

    print(f"\nPDF at 45 deg from normal:")
    print(f"  Lambertian: {pdf_lamb_45:.6f}")
    print(f"  Disney diffuse: {pdf_disney_45:.6f}")
    print(f"  Expected (cos45deg/pi): {cos_theta/np.pi:.6f}")
    print(f"  Disney/Lambertian ratio: {pdf_disney_45/pdf_lamb_45:.6f}")
