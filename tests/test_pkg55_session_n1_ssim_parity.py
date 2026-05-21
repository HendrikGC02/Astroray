"""pkg55 Phase B' Session N+1 — per-channel mean-ratio parity gate vs production path_tracer.

Session N+1 completes the CPU wavefront pipeline (env-map miss + complete
pipeline). This test validates that the cpu_wavefront produces a complete,
correct image that matches the production CPU path_tracer per-channel means
on the pkg54 visible-band parity scene at 64 spp.

Why mean-ratio, not SSIM: SSIM ≥ 0.985 is architecturally unreachable for two
independent MC RNG streams (production mt19937 seeded via set_seed vs the
wavefront PCG32 keyed by (pixel, sample, seed)) at modest spp — measured
0.7861 in the PR #327 / pkg55-B' Session N+1 architect verification round.
The noise patterns of two independent MC estimators are uncorrelated, so
windowed SSIM reduces to a noise-floor function of sample count and scene
brightness, not a structural-drift signal. Per-channel means, by contrast,
converge fast because both estimators target the same integral, and a 5%
tolerance catches real semantic drift (a missing xyz→sRGB matrix multiply
or a radiance-sign flip shifts means by ≥ 10%). Kernel correctness is already
proven by the bit-identity gate (test_cpu_wavefront_session_n1_bit_identity.py,
max diff = 0.0) and the <0.3% measured mean-ratio in the verification round.

Precedent: tests/test_pkg55_reference_pt_oracles_equivalent.py made the same
SSIM→mean-ratio swap for the same reason (independent-RNG MC noise).

Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §"Session N+1".
PR: #327 / pkg55-B' Session N+1 verification.
"""

import sys
import os
import numpy as np
import astroray

# Add tests/scenes to path.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scenes"))
import multiwavelength_parity

# Optional skimage for informational SSIM logging only (not gated).
_SKIMAGE_AVAILABLE = False
try:
    from skimage.metrics import structural_similarity as _sk_ssim
    _SKIMAGE_AVAILABLE = True
except ImportError:
    pass


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


def _informational_ssim(img1, img2):
    """Compute SSIM for logging only — not a gate. See module docstring."""
    if _SKIMAGE_AVAILABLE:
        ssim_r = _sk_ssim(img1[:, :, 0], img2[:, :, 0], data_range=1.0)
        ssim_g = _sk_ssim(img1[:, :, 1], img2[:, :, 1], data_range=1.0)
        ssim_b = _sk_ssim(img1[:, :, 2], img2[:, :, 2], data_range=1.0)
        return (ssim_r + ssim_g + ssim_b) / 3.0
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
    """Session N+1 parity gate: cpu_wavefront vs production path_tracer.

    Gate: per-channel mean-ratio |WF/Ref − 1| ≤ 0.05 at 64 spp.

    See module docstring for why SSIM is not the gate. Both estimators target
    the same integral, so per-channel means converge fast (~3% MC noise at
    64 spp on this scene); 5% accommodates noise while still catching real
    semantic drift (any structural bug shifts means by ≥ 10% — e.g., the
    missing xyz→sRGB matrix multiply surfaced at pkg55 Phase B' shifted R
    by 10%, B by 8%).
    """
    WIDTH, HEIGHT = 64, 64
    SEED = 424242
    SPP = 64
    MAX_DEPTH = 8
    MEAN_RATIO_TOLERANCE = 0.05

    r = _build_renderer(WIDTH, HEIGHT, SEED, MAX_DEPTH)

    # Production path_tracer render (CPU reference).
    print(f"\n[Session N+1 parity gate] Rendering production path_tracer "
          f"({WIDTH}x{HEIGHT} @ {SPP} spp)...")
    r.set_integrator("path_tracer")
    ref_rgb = r.render(SPP, MAX_DEPTH, None, apply_gamma=False)
    ref_img = np.array(ref_rgb).reshape(HEIGHT, WIDTH, 3)

    # CPU wavefront render (via the cpu_wavefront_render entry point).
    print(f"[Session N+1 parity gate] Rendering cpu_wavefront "
          f"({WIDTH}x{HEIGHT} @ {SPP} spp)...")
    wf_rgb = astroray.cpu_wavefront_render(r, samples=SPP, max_depth=MAX_DEPTH,
                                            seed=SEED)
    wf_img = np.array(wf_rgb).reshape(HEIGHT, WIDTH, 3)

    # Per-channel mean-ratio gate (primary).
    per_channel = []
    for c, ch in enumerate("RGB"):
        ref_mean = float(ref_img[..., c].mean())
        wf_mean = float(wf_img[..., c].mean())
        if ref_mean < 1e-9:
            ratio = float('inf') if abs(wf_mean) > 1e-9 else 1.0
        else:
            ratio = wf_mean / ref_mean
        deviation = abs(ratio - 1.0)
        per_channel.append((ch, ref_mean, wf_mean, ratio, deviation))

    diff = np.abs(ref_img - wf_img)
    max_diff = float(diff.max())
    mean_diff = float(diff.mean())

    print(f"\n[Session N+1 parity gate] Results:")
    print(f"  SPP: {SPP}, resolution: {WIDTH}x{HEIGHT}")
    print(f"  Max abs diff: {max_diff:.6f}, mean abs diff: {mean_diff:.6f}")
    for ch, rm, wm, ratio, dev in per_channel:
        print(f"  {ch}: ref_mean={rm:.5f} wf_mean={wm:.5f} "
              f"ratio={ratio:.4f} |ratio-1|={dev:.4f}")

    # Informational SSIM (not the gate — see module docstring for why).
    try:
        ssim = _informational_ssim(ref_img, wf_img)
        print(f"  Informational SSIM: {ssim:.4f} "
              f"(skimage={'yes' if _SKIMAGE_AVAILABLE else 'no (numpy fallback)'})")
    except Exception:
        pass

    for ch, _, _, _, dev in per_channel:
        assert dev <= MEAN_RATIO_TOLERANCE, (
            f"Session N+1 parity gate FAILED: channel {ch} mean ratio "
            f"deviates {dev:.4f} > {MEAN_RATIO_TOLERANCE} tolerance. "
            f"Per-channel means of cpu_wavefront and production path_tracer "
            f"converge to different expected values — structural drift in "
            f"the wavefront pipeline.")

    print(f"\n[pkg55-SessionN+1 parity gate] PASS: per-channel mean ratios "
          f"within {MEAN_RATIO_TOLERANCE:.0%}")


def test_cpu_wavefront_nonzero_output():
    """Sanity check: cpu_wavefront produces non-trivial pixel output.

    Before running the expensive 64-spp parity test, verify the wavefront
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
          f"({WIDTH}x{HEIGHT} @ {SPP} spp):")
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
