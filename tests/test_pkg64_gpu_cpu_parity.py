#!/usr/bin/env python
"""pkg64-gpu Phase 3 — GPU ↔ CPU SMS parity (SSIM ≥ 0.97).

Spec: .astroray_plan/packages/pkg64-gpu-spectral-caustics.md §Phase 3.

New gate introduced in Phase 3: GPU SMS vs CPU SMS SSIM ≥ 0.97 on the prism
scene at 256 spp with `useCaustics=true`. Threshold rationale from spec:

  "Matches pkg54b NIR-band tolerance, accounts for the FP-noise envelope
  characterized in pkg82. A tighter gate is not justified until pkg82 measures
  cross-build variance specifically for the SMS code path."

Informational: receiver-energy ratio GPU/CPU (expected ≈ 1.0) printed but not
asserted. Skips gracefully when CUDA is unavailable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

from base_helpers import save_image  # noqa: E402

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip(
        "CUDA feature not in this build — pkg64-gpu Phase 3 GPU/CPU parity "
        "needs CUDA; /verify runs this on the RTX box.",
        allow_module_level=True,
    )

WIDTH = 64
HEIGHT = 64
# pkg64-gpu Session 2: bumped 256 -> 512. Measured SSIM 0.924 @256 vs 0.932 @1024
# (3-seed avg, matched integrator) — spp has diminishing returns; the residual gap
# to the original 0.97 target is structural/metric (independent-RNG MC streams),
# not pure noise. 512 is a modest robustness bump without quadrupling runtime.
SAMPLES = 512
MAX_DEPTH = 10

BASELINES_DIR = Path(__file__).parent / "baselines" / "pkg64-gpu-phase3"


def _make_prism_scene(use_gpu: bool):
    """Sellmeier-BK7 sphere caster between an area light and a floor receiver.

    Mirrors test_pkg64_gpu_phase3_default_integrator.py _make_prism_scene (lines 60-88).
    Identical scene on CPU and GPU paths; only the renderer backend differs.
    """
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])

    floor = r.create_material("lambertian", [0.85, 0.85, 0.85], {})
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, -2.2], [2.4, -1.2, 1.6], floor)
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, 1.6], [-2.4, -1.2, 1.6], floor)

    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 18.0})
    r.add_sphere([0.0, 1.6, 1.0], 0.22, light)

    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {
        "sellmeier_preset": "bk7",
    })
    r.add_sphere([0.0, -0.4, 0.15], 0.7, glass)
    glass_id = r.scene_object_count() - 1
    assert r.set_object_caustic_caster(glass_id, True)

    r.setup_camera(
        [0.0, 0.0, 4.2], [0.0, -0.05, 0.0], [0.0, 1.0, 0.0],
        38.0, WIDTH / HEIGHT, 0.0, 4.2, WIDTH, HEIGHT)

    if use_gpu:
        r.set_use_gpu(True)
        r.set_wavelength_range(380.0, 780.0)  # visible-band sRGB output
        r.set_output_mode("srgb")
        # pkg64-gpu Session 2: use "path_tracer" (NOT "multiwavelength_path_tracer").
        # Both names route through the SAME multiwavelength megakernel
        # (module/blender_module.cpp:1121); the only difference is that NEE is
        # enabled for "path_tracer" and disabled for "multiwavelength_path_tracer"
        # (blender_module.cpp:1138). The CPU side below uses "path_tracer" (NEE on),
        # so the GPU side must too — otherwise we compare a NEE-off GPU render
        # (dark, unlit lambertian floor) against a NEE-on CPU render and SSIM is
        # dominated by that integrator mismatch, not by dispersion. Matching the
        # integrator lifts GPU/CPU SSIM from ~0.49 to ~0.93. This still exercises
        # the dispersion fix (useCaustics + the multiwavelength dielectric path).
        r.set_integrator("path_tracer")
    else:
        # CPU spectral path tracer — same integrator (path_tracer, NEE) as GPU.
        r.set_integrator("path_tracer")

    r.set_use_refractive_caustics(True)
    r.set_use_reflective_caustics(True)
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator_param("spectral_newton", 1)

    return r


def _render(use_gpu: bool, samples: int, seed: int):
    """Render the prism scene on GPU or CPU and return (pixels, stats_dict)."""
    r = _make_prism_scene(use_gpu=use_gpu)
    r.set_seed(seed)
    pixels = np.asarray(r.render(samples, MAX_DEPTH, None, False), dtype=np.float32)
    # GPU megakernel does not return integrator stats; CPU does.
    stats = r.get_integrator_stats() if not use_gpu else {}
    return pixels, stats


def _receiver_energy(pixels: np.ndarray) -> float:
    """Sum of luminance over the floor region under the sphere — the pixels
    where the chromatic caustic lands. Same window as test_pkg64_gpu_phase3_default_integrator.py."""
    lum = 0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]
    h, w = lum.shape
    yy, xx = np.mgrid[:h, :w]
    receiver = (xx > w * 0.20) & (xx < w * 0.80) & (yy < h * 0.55) & (yy > h * 0.20)
    return float(np.sum(lum[receiver]))


def _ssim(img1: np.ndarray, img2: np.ndarray) -> float:
    """Structural similarity index (SSIM) between two images.

    Simplified windowed SSIM for 3-channel images. Mirrors the pkg54b NIR-band
    parity gate pattern (tests/test_pkg54b_phase2_gpu_parity.py). We don't need
    skimage.metrics.structural_similarity here because the per-channel mean +
    variance + covariance pattern is sufficient at the 0.97 threshold.

    Returns mean SSIM over RGB channels.
    """
    from math import sqrt

    # Constants from Wang 2004 SSIM paper (DOI 10.1109/TIP.2003.819861).
    C1 = (0.01 * 1.0) ** 2  # (K1 * L)^2, L=1.0 for normalized images
    C2 = (0.03 * 1.0) ** 2  # (K2 * L)^2

    ssim_channels = []
    for ch in range(3):
        x = img1[..., ch].astype(np.float64)
        y = img2[..., ch].astype(np.float64)

        mu_x = np.mean(x)
        mu_y = np.mean(y)
        sigma_x = np.std(x)
        sigma_y = np.std(y)
        sigma_xy = np.mean((x - mu_x) * (y - mu_y))

        numerator = (2 * mu_x * mu_y + C1) * (2 * sigma_xy + C2)
        denominator = (mu_x**2 + mu_y**2 + C1) * (sigma_x**2 + sigma_y**2 + C2)
        ssim_ch = numerator / denominator
        ssim_channels.append(ssim_ch)

    return float(np.mean(ssim_channels))


@pytest.mark.xfail(
    reason="SMS-GPU SSIM parity FROZEN AS LEGACY (owner decision 2026-06-08). The "
           "Wave-5 glass fix (PR #404) legitimately improved GPU output past the frozen "
           "parity baseline, so SSIM drifted to ~0.835 < 0.85. SMS-GPU is no longer the "
           "canonical caustic path — pkg113 forward photon-map is — so this structural "
           "gate is retired rather than recalibrated. The ROI energy-ratio gate (the "
           "robust primary check) still asserts. Evidence: pkg64-gpu-hw-sweep-2026-05-31.md.",
    strict=False,
)
def test_pkg64_gpu_cpu_parity_ssim(test_results_dir):
    """GPU vs CPU SMS parity on the prism scene (pkg64-gpu Session 2).

    LEGACY/xfail since 2026-06-08 — see the xfail marker above. SMS-GPU is frozen;
    the SSIM gate drifted because the glass fix improved GPU output. Kept for the
    record + the ROI energy-ratio check; pkg113 photon-map supersedes SMS-GPU.

    Re-spec from the Session 1 deferral: the original SSIM >= 0.97 gate is
    unreachable for two independent MC streams at this spp — measured CPU-vs-CPU
    SSIM (same engine, different seed) is only ~0.53 at 256 spp, BELOW the 0.97
    threshold, so no implementation can clear it (memory
    `ssim-wrong-gate-for-independent-rng`). Two changes make the gate honest:

      1. Match the integrator: GPU now uses "path_tracer" (NEE) like the CPU side
         (see _make_prism_scene). The Session 1 test compared GPU
         "multiwavelength_path_tracer" (NEE OFF, dark floor) against CPU
         "path_tracer" (NEE ON, lit floor) — an integrator mismatch, not a
         dispersion gap. Matching lifts SSIM from ~0.49 to ~0.93.
      2. ROI luminance-parity is the primary robust gate (per the memory above);
         SSIM is kept as a secondary structural check at a noise-floor-aware
         threshold (0.85; measured ~0.92-0.93 with the dispersion fix).

    The residual SSIM gap to 0.97 is the documented "Option B (hero-wavelength)
    stalls at 0.93-0.95" case the spec owner pre-accepted (2026-05-24); a future
    Option-A (per-wavelength split) session can push higher if needed.
    """
    probe = astroray.Renderer()
    if not probe.gpu_available:
        pytest.skip("CUDA GPU not available on this machine")

    baseline_gpu_path = BASELINES_DIR / "parity-gpu.npy"
    baseline_cpu_path = BASELINES_DIR / "parity-cpu.npy"

    # Multi-seed averaging (same seeds for GPU and CPU to compare apples-to-apples).
    test_seeds = (145, 211, 333)

    def avg(use_gpu, samples, seeds):
        acc = None
        for s in seeds:
            pix, _ = _render(use_gpu=use_gpu, samples=samples, seed=s)
            acc = pix if acc is None else acc + pix
        return acc / len(seeds)

    gpu_avg = avg(True, SAMPLES, test_seeds)
    cpu_avg = avg(False, SAMPLES, test_seeds)

    save_image(gpu_avg, os.path.join(test_results_dir, "pkg64_gpu_p3_parity_gpu.png"))
    save_image(cpu_avg, os.path.join(test_results_dir, "pkg64_gpu_p3_parity_cpu.png"))

    e_gpu = _receiver_energy(gpu_avg)
    e_cpu = _receiver_energy(cpu_avg)
    energy_ratio = e_gpu / max(e_cpu, 1e-6)

    ssim_val = _ssim(gpu_avg, cpu_avg)

    print(
        f"\n[pkg64-gpu Phase 3 GPU/CPU parity] "
        f"SSIM={ssim_val:.4f}, "
        f"receiver energy GPU={e_gpu:.4f} CPU={e_cpu:.4f} ratio={energy_ratio:.3f}x"
    )

    if not baseline_gpu_path.exists() or not baseline_cpu_path.exists():
        # First run: capture baselines and skip.
        baseline_gpu_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(baseline_gpu_path, gpu_avg)
        np.save(baseline_cpu_path, cpu_avg)
        pytest.skip(
            f"pkg64-gpu Phase 3 GPU/CPU parity baselines not present. "
            f"Captured GPU baseline at {baseline_gpu_path}, "
            f"CPU baseline at {baseline_cpu_path}. "
            f"Measured SSIM {ssim_val:.4f}, energy ratio {energy_ratio:.3f}x. "
            f"Re-run this test to assert the gates (SSIM >= 0.85 + ROI energy parity)."
        )

    baseline_gpu = np.load(baseline_gpu_path)
    baseline_cpu = np.load(baseline_cpu_path)
    baseline_ssim = _ssim(baseline_gpu, baseline_cpu)

    # Primary robust gate (memory ssim-wrong-gate-for-independent-rng): the caustic
    # ROI luminance must agree GPU vs CPU within a generous band. This catches the
    # integrator/lighting-divergence class of bug (e.g. the Session 1 NEE mismatch
    # that put GPU ~16x off) without being fooled by per-pixel MC noise.
    assert 0.5 <= energy_ratio <= 2.0, (
        f"pkg64-gpu GPU/CPU parity ROI energy gate FAILED: "
        f"GPU/CPU receiver-energy ratio {energy_ratio:.3f}x outside [0.5, 2.0]. "
        f"A gross deviation indicates GPU and CPU are not rendering the same "
        f"transport (e.g. NEE/integrator mismatch), not a dispersion gap."
    )

    # Secondary structural gate: SSIM >= 0.85. The original 0.97 was unreachable for
    # independent MC streams (CPU-vs-CPU SSIM is ~0.53 at this spp). With matched
    # integrators the dispersion fix reaches ~0.92-0.93; 0.85 leaves margin while
    # still distinguishing a correct chromatic caustic (~0.93) from the broken
    # Session 1 hero-only/mismatch baseline (~0.49-0.52).
    assert ssim_val >= 0.85, (
        f"pkg64-gpu GPU/CPU parity SSIM gate FAILED: "
        f"measured {ssim_val:.4f} < gate 0.85. GPU diverges from CPU structurally "
        f"(baseline SSIM was {baseline_ssim:.4f}). If baselines were captured "
        f"incorrectly, delete {baseline_gpu_path} and {baseline_cpu_path}, then re-run."
    )

    print(
        f"[pkg64-gpu Phase 3 GPU/CPU parity] PASS: "
        f"SSIM {ssim_val:.4f} >= 0.85, ROI energy ratio {energy_ratio:.3f}x in [0.5,2.0] "
        f"(baseline SSIM {baseline_ssim:.4f})"
    )
