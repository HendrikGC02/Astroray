"""pkg55 Phase B' Session 2b — equivalence test for the two reference PTs.

SSIM >= 0.99 at 64 spp between reference_pt_production_render and
reference_pt_wavefront_render. Validates that the per-path RNG scheme is
statistically equivalent to the tile-shared RNG scheme.

The two oracles use different seeding:
- reference_pt_production: mt19937(baseSeed + tileIdx) (tile-shared).
- reference_pt_wavefront: mt19937(hash(pixel_index, sample_index, 0)) (per-path).

RNG draw order within a sample is identical, so statistically they converge
to the same result. SSIM >= 0.99 at 64 spp is the acceptance gate.

Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §"Phase B'".
Design: .astroray_plan/docs/pkg55-B-cpu-reference-design.md §2, §3, §9.
"""

import pytest
import sys
import os
import numpy as np
import astroray

# Add tests/scenes to path so we can import lambertian_cornell.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scenes"))
import lambertian_cornell


def compute_ssim(img1, img2):
    """Compute SSIM between two float RGB images (H, W, 3).

    Simplified SSIM: per-channel mean over all pixels. This is not the full
    Wang et al. 2004 SSIM, but sufficient for the equivalence test (high
    sample count, same underlying physics).
    """
    from skimage.metrics import structural_similarity
    # Compute per-channel SSIM, then average.
    ssim_vals = []
    for c in range(3):
        s = structural_similarity(img1[:,:,c], img2[:,:,c],
                                  data_range=img1[:,:,c].max() - img1[:,:,c].min())
        ssim_vals.append(s)
    return np.mean(ssim_vals)


def test_reference_pt_oracles_equivalent():
    """Equivalence: tile-RNG and per-path-RNG oracles are statistically equivalent."""
    WIDTH, HEIGHT = 64, 64
    SEED = 424242
    SPP = 64
    MAX_DEPTH = 8
    SSIM_THRESHOLD = 0.99

    # Build Lambertian Cornell scene.
    r = astroray.Renderer()
    lambertian_cornell.build_scene(r)
    lambertian_cornell.setup_camera(r, width=WIDTH, height=HEIGHT)
    r.set_seed(SEED)

    # Render with both reference PTs.
    prod_img = astroray.reference_pt_production_render(
        r, samples=SPP, max_depth=MAX_DEPTH, seed=SEED, record_snapshots=False)
    wf_img = astroray.reference_pt_wavefront_render(
        r, samples=SPP, max_depth=MAX_DEPTH, seed=SEED, record_snapshots=False)

    # Both should be (HEIGHT, WIDTH, 3) float32.
    assert prod_img.shape == (HEIGHT, WIDTH, 3)
    assert wf_img.shape == (HEIGHT, WIDTH, 3)

    # Compute SSIM (requires scikit-image).
    try:
        ssim = compute_ssim(prod_img, wf_img)
    except ImportError:
        pytest.skip("scikit-image not installed; cannot compute SSIM")

    # Report statistics.
    diff = np.abs(prod_img - wf_img)
    max_diff = diff.max()
    mean_diff = diff.mean()

    print(f"\n[pkg55-Session2b equivalence test]")
    print(f"  SPP: {SPP}")
    print(f"  Resolution: {WIDTH}x{HEIGHT}")
    print(f"  SSIM: {ssim:.6f} (threshold >= {SSIM_THRESHOLD})")
    print(f"  Max abs diff: {max_diff:.6f}")
    print(f"  Mean abs diff: {mean_diff:.6f}")

    assert ssim >= SSIM_THRESHOLD, \
        f"Equivalence test FAILED: SSIM = {ssim:.6f} < {SSIM_THRESHOLD}. " \
        f"Per-path RNG and tile-shared RNG are not statistically equivalent."

    print(f"[pkg55-Session2b equivalence test] PASS: tile-RNG ≈ per-path-RNG "
          f"(SSIM = {ssim:.6f} >= {SSIM_THRESHOLD})")
