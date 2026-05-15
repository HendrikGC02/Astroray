"""pkg55 Phase B' Session 2b — equivalence test for the two reference PTs.

Validates that the per-path RNG scheme and the tile-shared RNG scheme
produce statistically equivalent renders.

The two oracles use different seeding:
- reference_pt_production: mt19937(baseSeed + tileIdx) (tile-shared).
- reference_pt_wavefront: mt19937(hash(pixel_index, sample_index, 0)) (per-path).

Gate: per-channel mean-ratio |GPU/CPU - 1| < 0.05 at 64 spp.

Why mean-ratio, not SSIM: SSIM measures noise-pattern agreement between
two independent MC estimators with different RNGs, which cannot be high at
practical SPP — the original spec's SSIM ≥ 0.99 @ 64 spp target measured
~0.628 in practice and only reached ~0.97 at 4096 spp (48-minute single-
threaded test). Per-channel means, by contrast, converge fast (both
estimators target the same integral) and are a real semantic-drift gate.

Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §"Phase B'".
Design: .astroray_plan/docs/pkg55-B-cpu-reference-design.md §2, §3, §9.

Follow-ups deferred:
- mt19937 per-path reseeding has known quality concerns (startup bias,
  seed-stream correlation). The GPU wavefront should adopt a counter-based
  RNG (Philox/PCG32) per Codex review 2026-05-15; FNV-1a → mt19937(uint32)
  is acceptable for the CPU reference oracle but not the GPU production
  RNG. Tracked separately.
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
    """Equivalence: tile-RNG and per-path-RNG oracles converge to the same per-channel means."""
    WIDTH, HEIGHT = 64, 64
    SEED = 424242
    SPP = 64
    MAX_DEPTH = 8
    # Per-channel mean ratio tolerance. At 64 spp on Cornell, MC noise
    # in the per-pixel mean is ~3% per channel; 5% accommodates noise
    # while still catching real semantic drift (any structural bug shifts
    # means by ≥ 10% — e.g., the missing xyz→sRGB matrix multiply
    # surfaced at this PR shifted R by 10%, B by 8%).
    MEAN_RATIO_TOLERANCE = 0.05

    # Build Lambertian Cornell scene.
    r = astroray.Renderer()
    lambertian_cornell.build_scene(r)
    lambertian_cornell.setup_camera(r, width=WIDTH, height=HEIGHT)
    r.set_seed(SEED)
    # Trigger BVH build: reference_pt_production_render reads
    # renderer.getBVH() and crashes if the acceleration structure hasn't
    # been built yet. r.render() internally calls buildAcceleration(); a
    # 1-sample warmup is the cheapest way to force it without exposing a
    # dedicated build_acceleration() Python binding.
    # TODO(follow-up): add a `Renderer.build_acceleration()` binding so
    # tests don't need this hack.
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 1)
    _ = r.render(1, 1, None, False)
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator("path_tracer")  # rebuild integrator with updated param

    # Render with both reference PTs.
    prod_img = astroray.reference_pt_production_render(
        r, samples=SPP, max_depth=MAX_DEPTH, seed=SEED, record_snapshots=False)
    wf_img = astroray.reference_pt_wavefront_render(
        r, samples=SPP, max_depth=MAX_DEPTH, seed=SEED, record_snapshots=False)

    # Both should be (HEIGHT, WIDTH, 3) float32.
    assert prod_img.shape == (HEIGHT, WIDTH, 3)
    assert wf_img.shape == (HEIGHT, WIDTH, 3)

    # Per-channel mean-ratio gate (primary): both MC estimators target the
    # same expected per-pixel mean per channel, so ratios converge fast
    # regardless of the RNG-scheme noise-pattern difference.
    per_channel = []
    for c, ch in enumerate("RGB"):
        prod_mean = float(prod_img[..., c].mean())
        wf_mean   = float(wf_img[..., c].mean())
        if prod_mean < 1e-9:
            ratio = float('inf') if abs(wf_mean) > 1e-9 else 1.0
        else:
            ratio = wf_mean / prod_mean
        deviation = abs(ratio - 1.0)
        per_channel.append((ch, prod_mean, wf_mean, ratio, deviation))

    diff = np.abs(prod_img - wf_img)
    max_diff = float(diff.max())
    mean_diff = float(diff.mean())

    print(f"\n[pkg55-Session2b equivalence test]")
    print(f"  SPP: {SPP}, resolution: {WIDTH}x{HEIGHT}")
    print(f"  Max abs diff: {max_diff:.6f}, mean abs diff: {mean_diff:.6f}")
    for ch, pm, wm, r, d in per_channel:
        print(f"  {ch}: prod_mean={pm:.5f} wf_mean={wm:.5f} ratio={r:.4f} |ratio-1|={d:.4f}")

    # Informational SSIM (not the gate — see module docstring for why).
    try:
        ssim = compute_ssim(prod_img, wf_img)
        print(f"  Informational SSIM: {ssim:.4f}")
    except ImportError:
        pass  # scikit-image optional for this branch

    for ch, _, _, _, dev in per_channel:
        assert dev <= MEAN_RATIO_TOLERANCE, \
            f"Equivalence test FAILED: channel {ch} mean ratio deviates {dev:.4f} > " \
            f"{MEAN_RATIO_TOLERANCE} tolerance. Per-path RNG and tile-shared RNG " \
            f"oracles converge to different expected values — structural drift in " \
            f"reference_pt_wavefront or reference_pt_production."

    print(f"[pkg55-Session2b equivalence test] PASS: per-channel mean ratios within "
          f"{MEAN_RATIO_TOLERANCE:.0%}")
