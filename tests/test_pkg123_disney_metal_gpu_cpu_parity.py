"""pkg123 — CPU<->GPU Disney-metal render parity at the near-delta alpha band.

Regression test for a GPU-only bug found in independent parity review of PR #498
(Opus review vs Walter 2007 / pbrt-v4 / Cycles forms). The pkg123 fix removed
stabilizer epsilons from D_GTR2 and the specular reflection pdf denominators in
both plugins/materials/disney.cpp and include/astroray/gpu_materials.h. Review
found the GPU specular pdf() branch (gpu_disney_pdf, gpu_materials.h ~874) had
NO alpha floor and NO NdotH>0/HdotV>0 guard, unlike:
  - CPU pdf() (disney.cpp:530 alpha floor, :533 guard)
  - GPU sample() (gpu_materials.h:836 alpha floor, :845 guard)

With the epsilons removed, the unguarded/unfloored GPU pdf() could:
  - divide by zero as HdotV -> 0 (no guard) -> +/-inf,
  - evaluate D_GTR2 at NdotH=1 with alpha->0 -> 0/0 = NaN,
  - disagree with the alpha-floored sample() by ~6-7x near roughness=0.05,
    since sample() floors alpha to 0.0064 while pdf() did not.

This is invisible to the CPU-only chi^2 gates (Track A, tests/statistical/) --
those exercise disney.cpp only. Only a CPU<->GPU render comparison at the
near-delta alpha band (roughness in {0.0, 0.03, 0.05, 0.1}, spanning the
alpha=max(roughness^2, 0.0064) floor transition) can see it.

Gate (per coordinator directive -- NOT SSIM, see memory
ssim-wrong-gate-for-independent-rng: independent MC streams don't converge in
SSIM at practical spp, but per-channel means do):
  1. Zero NaN/Inf pixel components in either render (the direct failure mode).
  2. Per-channel mean-ratio GPU/CPU within a generous MC-noise band.
"""

from __future__ import annotations

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip(
        "CUDA feature not in this build -- pkg123 Disney-metal GPU/CPU parity "
        "needs the RTX box.",
        allow_module_level=True,
    )

WIDTH = HEIGHT = 48
SAMPLES = 128
MAX_DEPTH = 4
SEED = 90123

# The near-delta alpha-floor band. alpha = max(roughness^2, 0.0064):
#   roughness=0.00 -> alpha floored to 0.0064 (roughness^2 = 0.0)
#   roughness=0.03 -> alpha floored to 0.0064 (roughness^2 = 0.0009)
#   roughness=0.05 -> alpha floored to 0.0064 (roughness^2 = 0.0025)
#   roughness=0.10 -> alpha = roughness^2 = 0.01 (just above the floor; control)
# This spans the exact transition where GPU sample() floored alpha but GPU
# pdf() (pre-fix) did not -- the reported ~6-7x sample/pdf mismatch.
ROUGHNESS_VALUES = [0.0, 0.03, 0.05, 0.1]

# Ratio bounds (not |ratio-1| tolerance) mirroring the established pkg64
# GPU/CPU energy-ratio gate pattern (tests/test_pkg64_gpu_cpu_parity.py):
# generous enough to absorb independent-RNG MC noise on a narrow near-mirror
# lobe at modest spp, tight enough to catch an order-of-magnitude
# sample/pdf mismatch (the reported ~6-7x).
RATIO_LOW = 0.4
RATIO_HIGH = 2.5


def _alpha(roughness: float) -> float:
    return max(roughness * roughness, 0.0064)


def _make_metal_scene(use_gpu: bool, roughness: float):
    """Floor + area light + Disney metallic sphere. Mirrors the
    tests/test_pkg64_gpu_cpu_parity.py _make_prism_scene shape: same scene
    graph built identically for CPU and GPU, only the backend flag differs.
    """
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])

    floor = r.create_material("lambertian", [0.6, 0.6, 0.6], {})
    r.add_triangle([-3.0, -1.0, -3.0], [3.0, -1.0, -3.0], [3.0, -1.0, 3.0], floor)
    r.add_triangle([-3.0, -1.0, -3.0], [3.0, -1.0, 3.0], [-3.0, -1.0, 3.0], floor)

    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 12.0})
    r.add_sphere([1.2, 2.5, 1.5], 0.3, light)

    metal = r.create_material("disney", [0.9, 0.6, 0.4], {
        "metallic": 1.0,
        "roughness": roughness,
    })
    r.add_sphere([0.0, 0.0, 0.0], 0.9, metal)

    r.setup_camera([0.0, 0.8, 4.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                    35.0, WIDTH / HEIGHT, 0.0, 4.0, WIDTH, HEIGHT)

    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    if use_gpu:
        r.set_use_gpu(True)
    return r


def _render(use_gpu: bool, roughness: float, seed: int) -> np.ndarray:
    r = _make_metal_scene(use_gpu=use_gpu, roughness=roughness)
    r.set_seed(seed)
    pixels = np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float32)
    return pixels


@pytest.mark.parametrize("roughness", ROUGHNESS_VALUES)
def test_disney_metal_gpu_cpu_parity_near_delta(roughness):
    """CPU<->GPU Disney-metal parity at the near-delta alpha-floor band.

    Checks (pkg123 coordinator directive, NOT SSIM):
      1. No NaN/Inf pixel components in either render.
      2. Per-channel mean-ratio GPU/CPU within a generous MC-noise band.
    """
    gpu_pixels = _render(use_gpu=True, roughness=roughness, seed=SEED)
    cpu_pixels = _render(use_gpu=False, roughness=roughness, seed=SEED)

    assert gpu_pixels.shape == (HEIGHT, WIDTH, 3)
    assert cpu_pixels.shape == (HEIGHT, WIDTH, 3)

    alpha = _alpha(roughness)

    # Gate 1 (primary/blocking): no NaN/Inf. This is the direct failure mode
    # of the unguarded/unfloored gpu_disney_pdf specular branch pre-fix
    # (0/0 at NdotH=1 as alpha->0; unguarded division as HdotV->0).
    gpu_bad = int(np.sum(~np.isfinite(gpu_pixels)))
    cpu_bad = int(np.sum(~np.isfinite(cpu_pixels)))
    assert gpu_bad == 0, (
        f"GPU render produced {gpu_bad} NaN/Inf pixel components at "
        f"roughness={roughness} (alpha={alpha:.4f}). This is the "
        f"gpu_disney_pdf missing-alpha-floor/missing-guard failure mode "
        f"(independent review of PR #498)."
    )
    assert cpu_bad == 0, (
        f"CPU render produced {cpu_bad} NaN/Inf pixel components at "
        f"roughness={roughness} (unexpected on CPU -- disney.cpp already had "
        f"the alpha floor and guard; investigate separately if this fires)."
    )

    # Gate 2: per-channel mean-ratio (NOT SSIM -- memory
    # ssim-wrong-gate-for-independent-rng: independent MC streams don't
    # converge in SSIM at practical spp, but per-channel means do, since both
    # estimators target the same expected integral).
    per_channel = []
    for c, ch in enumerate("RGB"):
        gpu_mean = float(gpu_pixels[..., c].mean())
        cpu_mean = float(cpu_pixels[..., c].mean())
        if cpu_mean < 1e-9:
            ratio = float("inf") if abs(gpu_mean) > 1e-9 else 1.0
        else:
            ratio = gpu_mean / cpu_mean
        per_channel.append((ch, cpu_mean, gpu_mean, ratio))

    print(f"\n[pkg123 Disney-metal GPU/CPU parity] roughness={roughness} "
          f"(alpha={alpha:.4f})")
    for ch, cm, gm, ratio in per_channel:
        print(f"  {ch}: cpu_mean={cm:.5f} gpu_mean={gm:.5f} ratio={ratio:.4f}")

    for ch, cm, gm, ratio in per_channel:
        assert RATIO_LOW <= ratio <= RATIO_HIGH, (
            f"pkg123 Disney-metal GPU/CPU parity FAILED at roughness={roughness} "
            f"(alpha={alpha:.4f}): channel {ch} GPU/CPU mean ratio {ratio:.4f} "
            f"outside [{RATIO_LOW}, {RATIO_HIGH}]. GPU and CPU Disney metallic "
            f"pdf/sample diverge in the near-delta alpha band (cpu_mean={cm:.5f}, "
            f"gpu_mean={gm:.5f})."
        )

    print(f"[pkg123 Disney-metal GPU/CPU parity] PASS at roughness={roughness}: "
          f"no NaN/Inf, per-channel mean ratios within [{RATIO_LOW}, {RATIO_HIGH}]")
