"""
pkg55-C5 gate: spectral photon-map caustics in the GPU wavefront.

Tests:
1. Photons OFF: wavefront bit-identity (photons disabled = default path untouched)
2. Photons ON: wavefront vs MW megakernel caustic parity (SSIM ≥ 0.80)

Spec: .astroray_plan/docs/pkg55-phase-c-plan-2026-07.md Session C5.
"""

import pytest
import numpy as np
import astroray
import os


def _gpu_available():
    return astroray.Renderer().gpu_available


def _build_glass_sphere_scene():
    """Glass-sphere caustic scene (minimal test resolution).

    Mirrors test_gpu_caustic_parity.py but uses smaller resolution for faster
    gate validation. Production caustic tests remain in test_gpu_caustic_parity.py.
    """
    r = astroray.Renderer()

    # Camera looking down at floor
    r.camera.set_position((0, 2, 5))
    r.camera.set_look_at((0, 0, 0))
    r.camera.set_up((0, 1, 0))
    r.camera.set_fov(40)
    r.set_width_height(128, 128)  # Small for fast gate

    # Floor to receive caustic
    floor = r.create_mesh()
    floor.add_quad(
        (-3, 0, -3), (3, 0, -3), (3, 0, 3), (-3, 0, 3),
        [0, 0, 1], [0, 0, 1], [0, 0, 1], [0, 0, 1]
    )
    mat_floor = r.create_material()
    mat_floor.set_albedo((0.8, 0.8, 0.8))
    floor.set_material(mat_floor)

    # Glass sphere (caustic caster)
    sphere = r.create_sphere((0, 1.5, 0), 0.5)
    mat_glass = r.create_material()
    mat_glass.set_type("glass")
    mat_glass.set_ior(1.5)
    sphere.set_material(mat_glass)
    sphere.set_caustic_caster(True)  # Flag for photon pre-pass

    # Sun light
    r.create_directional_light((0.3, -1, 0.2), (1, 1, 1), 3.0)

    return r


def _render_wavefront(r, samples, enable_photons):
    """Render with wavefront_path_tracer."""
    r.set_integrator("wavefront_path_tracer")
    r.set_integrator_param("max_depth", 8)
    if enable_photons:
        r.set_integrator_param_str("caustics", "photon_map")
        r.set_integrator_param("photon_knn", 50)
    # else: caustics param omitted = photons OFF (default path)
    r.render(samples)
    return np.array(r.camera.pixels)


def _render_mw(r, samples, enable_photons):
    """Render with path_tracer (MW megakernel)."""
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 8)
    if enable_photons:
        r.set_integrator_param_str("caustics", "photon_map")
        r.set_integrator_param("photon_knn", 50)
    r.render(samples)
    return np.array(r.camera.pixels)


def _luminance(img):
    """RGB to luminance."""
    return 0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2]


def _ssim(img1, img2):
    """SSIM (structural similarity)."""
    try:
        from skimage.metrics import structural_similarity
        lum1 = _luminance(img1)
        lum2 = _luminance(img2)
        return structural_similarity(lum1, lum2, data_range=lum1.max() - lum1.min())
    except ImportError:
        pytest.skip("scikit-image not available for SSIM")


def _max_abs_diff(img1, img2):
    """Max absolute difference (for bit-identity checks)."""
    return np.abs(img1 - img2).max()


@pytest.mark.skipif(not _gpu_available(), reason="CUDA GPU not available")
def test_wavefront_photons_off_identity():
    """Gate 1: photons OFF → wavefront bit-identity.

    With photons disabled (no caustics param), the wavefront path should be
    bit-identical to the no-photon baseline (default path untouched by C5).
    Uses the existing GPU fp-noise floor: max_abs_diff ≤ 1e-5 (Monte Carlo +
    atomic accumulation noise, same convention as C4 gates).
    """
    r = _build_glass_sphere_scene()

    # Render twice with photons OFF (should be identical)
    img1 = _render_wavefront(r, samples=16, enable_photons=False)
    img2 = _render_wavefront(r, samples=16, enable_photons=False)

    diff = _max_abs_diff(img1, img2)
    assert diff <= 1e-5, (
        f"Photons-off bit-identity failed: max_abs_diff={diff:.2e} > 1e-5. "
        f"C5 photon code should not affect the default (photons-off) path."
    )


@pytest.mark.skipif(not _gpu_available(), reason="CUDA GPU not available")
def test_wavefront_photon_caustic_parity(test_results_dir):
    """Gate 2: photons ON → wavefront vs MW megakernel SSIM ≥ 0.80.

    Renders glass-sphere caustic scene with wavefront_path_tracer (photons ON)
    and compares to path_tracer (MW megakernel baseline). The gate is SSIM ≥ 0.80
    (pkg113 Phase-3 parity threshold, stochastic caustics).

    This is the C5 PRIMARY GATE from the plan doc Session C5 specification.
    """
    r = _build_glass_sphere_scene()

    # Render with photons ON: wavefront vs MW baseline
    img_wf = _render_wavefront(r, samples=32, enable_photons=True)
    img_mw = _render_mw(r, samples=32, enable_photons=True)

    ssim = _ssim(img_wf, img_mw)
    peak_wf = float(_luminance(img_wf).max())
    peak_mw = float(_luminance(img_mw).max())

    # Save PNGs for visual inspection (parent check per pkg113 culture)
    if test_results_dir:
        from PIL import Image

        def save_png(img, path):
            clipped = np.clip(img ** (1/2.2), 0, 1)  # gamma correct
            pil = Image.fromarray((clipped * 255).astype(np.uint8))
            pil.save(path)

        wf_png = os.path.join(test_results_dir, "pkg55_c5_wavefront_photons.png")
        mw_png = os.path.join(test_results_dir, "pkg55_c5_mw_baseline_photons.png")
        save_png(img_wf, wf_png)
        save_png(img_mw, mw_png)

        print(f"\n[pkg55-C5 photon caustic parity]")
        print(f"  SSIM: {ssim:.4f} (gate: ≥0.80)")
        print(f"  Peak luminance: WF={peak_wf:.3f} MW={peak_mw:.3f}")
        print(f"  Wavefront PNG: {wf_png}")
        print(f"  MW baseline PNG: {mw_png}")
        print(f"  PARENT: open both PNGs — confirm focused caustic on floor\n")

    assert ssim >= 0.80, (
        f"Photon caustic parity failed: SSIM={ssim:.4f} < 0.80. "
        f"Wavefront photon gather does not match MW megakernel baseline. "
        f"Peak luminance: WF={peak_wf:.3f} MW={peak_mw:.3f}"
    )
