#!/usr/bin/env python3
"""
pkg55-C5 manual test: glass-sphere caustic parity on wavefront_path_tracer.

Renders the pkg113 glass-sphere scene with wavefront_path_tracer and compares
to path_tracer (MW megakernel baseline). If SSIM ≥ 0.80, C5 gate passes.
"""

import astroray
import numpy as np
import os


def build_glass_sphere_scene():
    """Minimal glass sphere scene for caustic test."""
    import math
    r = astroray.Renderer()

    # Camera looking down at floor
    r.camera.set_position((0, 2, 5))
    r.camera.set_look_at((0, 0, 0))
    r.camera.set_up((0, 1, 0))
    r.camera.set_fov(40)
    r.set_width_height(256, 256)

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
    light = r.create_directional_light((0.3, -1, 0.2), (1, 1, 1), 3.0)

    return r


def render_wavefront(r, samples=64):
    """Render with wavefront_path_tracer."""
    r.set_integrator("wavefront_path_tracer")
    r.set_integrator_param("max_depth", 8)
    r.set_integrator_param_str("caustics", "photon_map")  # Enable photon caustics
    r.set_integrator_param("photon_knn", 50)
    r.render(samples)
    return np.array(r.camera.pixels)


def render_mw(r, samples=64):
    """Render with path_tracer (MW megakernel baseline)."""
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 8)
    r.set_integrator_param_str("caustics", "photon_map")
    r.set_integrator_param("photon_knn", 50)
    r.render(samples)
    return np.array(r.camera.pixels)


def luminance(img):
    """RGB to luminance."""
    return 0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2]


def ssim(img1, img2):
    """Simplified SSIM (structural similarity)."""
    from skimage.metrics import structural_similarity
    lum1 = luminance(img1)
    lum2 = luminance(img2)
    return structural_similarity(lum1, lum2, data_range=lum1.max() - lum1.min())


def caustic_roi_energy(img):
    """Energy in bottom-center ROI (where caustic lands)."""
    h, w = img.shape[:2]
    roi = img[int(h * 0.6):, int(w * 0.3):int(w * 0.7), :]
    return float(luminance(roi).sum())


def save_png(img, path):
    """Save as PNG."""
    from PIL import Image
    clipped = np.clip(img ** (1/2.2), 0, 1)  # gamma correct
    pil = Image.fromarray((clipped * 255).astype(np.uint8))
    pil.save(path)
    print(f"  Saved: {path}")


def main():
    print("[pkg55-C5 photon wavefront test]")

    if not astroray.Renderer().gpu_available:
        print("SKIP: CUDA GPU not available")
        return

    r = build_glass_sphere_scene()

    print("Rendering with wavefront_path_tracer...")
    img_wf = render_wavefront(r, samples=64)

    print("Rendering with path_tracer (MW baseline)...")
    img_mw = render_mw(r, samples=64)

    # Metrics
    e_wf = caustic_roi_energy(img_wf)
    e_mw = caustic_roi_energy(img_mw)
    ratio = e_wf / max(e_mw, 1e-6)
    sim = ssim(img_wf, img_mw)
    peak_wf = float(luminance(img_wf).max())

    # Save images
    os.makedirs("test_output", exist_ok=True)
    save_png(img_wf, "test_output/c5_wavefront.png")
    save_png(img_mw, "test_output/c5_mw_baseline.png")

    print(f"\nResults:")
    print(f"  Caustic ROI energy: WF={e_wf:.4f} MW={e_mw:.4f} ratio={ratio:.3f}x")
    print(f"  SSIM: {sim:.4f} (gate: ≥0.80)")
    print(f"  Peak luminance (WF): {peak_wf:.3f}")
    print(f"\n  {'PASS' if sim >= 0.80 else 'FAIL'}")

    if sim < 0.80:
        print(f"  Gate miss: SSIM {sim:.4f} < 0.80")
        print("  Visually inspect test_output/c5_*.png for caustic focus")


if __name__ == "__main__":
    main()
