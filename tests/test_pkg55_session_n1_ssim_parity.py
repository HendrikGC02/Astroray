"""pkg55 Phase B' Session N+1 — SSIM parity gate vs production path_tracer.

Session N+1 completes the CPU wavefront pipeline. This test validates that
the cpu_wavefront produces a complete, correct image that achieves SSIM ≥ 0.985
vs the production CPU path_tracer on the pkg54 visible-band parity scene at
64 spp.

This is the real Session N+1 close gate — the bit-identity test proves the
wavefront matches the reference oracle by construction, but this SSIM test
proves the entire pipeline (init, advance, accumulate, post-processing)
produces production-quality renders.

Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §"Session N+1".
Design: Session N+1 acceptance criteria — SSIM ≥ 0.985 at 64 spp.
"""

import sys
import os
import numpy as np
import astroray

# Add tests/scenes to path.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scenes"))
import multiwavelength_parity


def _build_renderer(width, height, seed, max_depth):
    """Build renderer with pkg54 multiwavelength_parity scene."""
    r = astroray.Renderer()
    multiwavelength_parity.build_scene(r, attach_profiles=False)
    multiwavelength_parity.setup_camera(r, width=width, height=height)
    r.set_seed(seed)
    r.set_integrator_param("max_depth", max_depth)
    r.set_integrator("path_tracer")
    # Warmup render to build BVH.
    _ = r.render(1, 1, None, False)
    return r


def _compute_ssim(img1, img2):
    """Compute SSIM between two images (H×W×3 float arrays).

    Uses scikit-image when available; falls back to a global numpy SSIM
    estimate (same pattern as test_gpu_multiwavelength.py) so the gate runs
    in CI where skimage is absent from requirements.txt.
    """
    try:
        from skimage.metrics import structural_similarity
        ssim_r = structural_similarity(img1[:, :, 0], img2[:, :, 0], data_range=1.0)
        ssim_g = structural_similarity(img1[:, :, 1], img2[:, :, 1], data_range=1.0)
        ssim_b = structural_similarity(img1[:, :, 2], img2[:, :, 2], data_range=1.0)
        return (ssim_r + ssim_g + ssim_b) / 3.0
    except ImportError:
        a = img1.astype(np.float64)
        b = img2.astype(np.float64)
        c1 = 0.01 ** 2
        c2 = 0.03 ** 2
        mu_a = np.mean(a)
        mu_b = np.mean(b)
        var_a = np.var(a)
        var_b = np.var(b)
        cov = np.mean((a - mu_a) * (b - mu_b))
        return float(((2 * mu_a * mu_b + c1) * (2 * cov + c2))
                     / ((mu_a * mu_a + mu_b * mu_b + c1) * (var_a + var_b + c2)))


def test_cpu_wavefront_ssim_parity():
    """Session N+1 SSIM gate: cpu_wavefront vs production path_tracer ≥ 0.985."""
    WIDTH, HEIGHT = 64, 64
    SEED = 424242
    SPP = 64
    MAX_DEPTH = 8
    SSIM_THRESHOLD = 0.985

    r = _build_renderer(WIDTH, HEIGHT, SEED, MAX_DEPTH)

    # Production path_tracer render (CPU reference).
    print(f"\n[Session N+1 SSIM gate] Rendering production path_tracer "
          f"({WIDTH}×{HEIGHT} @ {SPP} spp)...")
    r.set_integrator("path_tracer")
    ref_rgb = r.render(SPP, MAX_DEPTH, None, apply_gamma=False)
    ref_img = np.array(ref_rgb).reshape(HEIGHT, WIDTH, 3)

    # CPU wavefront render (via the cpu_wavefront_render entry point).
    print(f"[Session N+1 SSIM gate] Rendering cpu_wavefront "
          f"({WIDTH}×{HEIGHT} @ {SPP} spp)...")
    wf_rgb = astroray.cpu_wavefront_render(r, samples=SPP, max_depth=MAX_DEPTH,
                                            seed=SEED)
    wf_img = np.array(wf_rgb).reshape(HEIGHT, WIDTH, 3)

    # Compute SSIM.
    ssim = _compute_ssim(ref_img, wf_img)

    # Diagnostics.
    img_diff = np.abs(ref_img - wf_img)
    print(f"\n[Session N+1 SSIM gate] Results:")
    print(f"  SSIM: {ssim:.4f} (threshold: {SSIM_THRESHOLD:.3f})")
    print(f"  Max abs diff: {float(img_diff.max()):.4f}")
    print(f"  Mean abs diff: {float(img_diff.mean()):.6f}")
    print(f"  Ref mean RGB: [{ref_img[:,:,0].mean():.4f}, "
          f"{ref_img[:,:,1].mean():.4f}, {ref_img[:,:,2].mean():.4f}]")
    print(f"  WF mean RGB:  [{wf_img[:,:,0].mean():.4f}, "
          f"{wf_img[:,:,1].mean():.4f}, {wf_img[:,:,2].mean():.4f}]")

    # Session N+1 acceptance gate.
    assert ssim >= SSIM_THRESHOLD, (
        f"Session N+1 SSIM gate FAILED: SSIM = {ssim:.4f}, "
        f"threshold = {SSIM_THRESHOLD:.3f}. The CPU wavefront must produce "
        f"a complete, correct image that is structurally similar to the "
        f"production path_tracer at 64 spp.")

    print(f"\n[pkg55-SessionN+1 SSIM gate] PASS: SSIM = {ssim:.4f} ≥ "
          f"{SSIM_THRESHOLD:.3f}. The CPU wavefront produces a complete, "
          f"correct image.")


def test_cpu_wavefront_nonzero_output():
    """Sanity check: cpu_wavefront produces non-trivial pixel output.

    Before running the expensive 64-spp SSIM test, verify the wavefront
    produces non-black / non-zero output at low spp.
    """
    WIDTH, HEIGHT = 16, 16
    SEED = 424242
    SPP = 4
    MAX_DEPTH = 8

    r = _build_renderer(WIDTH, HEIGHT, SEED, MAX_DEPTH)

    wf_rgb = astroray.cpu_wavefront_render(r, samples=SPP, max_depth=MAX_DEPTH,
                                            seed=SEED)
    wf_img = np.array(wf_rgb).reshape(HEIGHT, WIDTH, 3)

    mean_val = wf_img.mean()
    max_val = wf_img.max()
    nonzero_count = np.count_nonzero(wf_img)

    print(f"\n[Session N+1 sanity check] cpu_wavefront output "
          f"({WIDTH}×{HEIGHT} @ {SPP} spp):")
    print(f"  Mean: {mean_val:.4f}, Max: {max_val:.4f}, "
          f"Nonzero pixels: {nonzero_count} / {HEIGHT * WIDTH * 3}")

    assert mean_val > 0.0, (
        f"Sanity check FAILED: cpu_wavefront produced all-zero output "
        f"(mean = {mean_val:.4f}). The pipeline is not accumulating radiance.")
    assert max_val > 0.01, (
        f"Sanity check FAILED: cpu_wavefront max pixel = {max_val:.4f}, "
        f"expected > 0.01. The output is too dim to be correct.")
    assert nonzero_count > HEIGHT * WIDTH, (
        f"Sanity check FAILED: only {nonzero_count} / {HEIGHT * WIDTH * 3} "
        f"pixels are nonzero. Expected most pixels to have nonzero values "
        f"given the scene has an area light and env background.")

    print(f"[pkg55-SessionN+1 sanity check] PASS: cpu_wavefront produces "
          f"non-trivial output.")
