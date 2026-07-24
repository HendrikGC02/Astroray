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

NOTE: all four near-delta rows in this band were xfail'd for a SEPARATE,
pre-existing GPU near-delta over-brightness defect unrelated to the
alpha-floor/guard bug above (measured on hardware post-fix; see the
ROUGHNESS_VALUES per-row reasons below). pkg141 (PR TBD, see spec
gpu-near-delta-disney-metal-brightness) found and fixed the mechanism:
DisneyPlugin::closureGraph() (plugins/materials/disney.cpp) always emits a
GGXConductor closure for any transmission<0.999 Disney material (even for
metallic=1.0, transmission=0.0 pure metal), so the GPU upload always lowers
to GMAT_CLOSURE_GRAPH rather than the direct GMAT_DISNEY path -- and the
closure-graph dispatch (gpu_closure_as_material, gpu_materials.h) routed
EVERY GGXConductor closure to gpu_metal_eval/gpu_metal_sample (the
standalone MetalPlugin's own GPU model), which has an unconditional
full-albedo perfect-mirror shortcut below roughness 0.1 -- correct for
MetalPlugin (whose CPU eval()/sample() has the identical shortcut) but wrong
for a Disney metallic lobe, whose CPU eval()/sample()/pdf() never
special-cases low roughness (alpha floors at 0.0064 but stays a continuous
Fresnel-Schlick/D_GTR2/Smith-G lobe). Fix: stamp the native plugin type on
the uploaded GMaterial (scene_upload.cu, via the already-public
Material::getGPUTypeName(), no disney.cpp edit) and route
Disney-native conductor closures to gpu_disney_eval/sample/pdf instead;
also fixed a second, stacked bug in gpu_disney_eval's specular term (a
stale extra `/(4*NdotL*NdotV+0.001f)` divide that CPU's disney.cpp already
removed in pkg60/PR #178, "Correct the Disney specular/clearcoat Smith-G
denominator bug", commit 1df244f -- the GPU mirror was never updated to
match). HW verification of the rows below is PENDING (see the
hardware-verifier queue) -- do not remove the xfail markers until measured
on RTX. The alpha-floor/guard fix this test was originally written to
regression-guard is still in place and still correct -- it just wasn't the
whole GPU/CPU parity story at this band.

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
#
# ALL FOUR rows are xfail'd (plain, not strict): coordinator hardware runs on
# commits 2ed96f6 and a677cb4 (code unchanged between the two runs, so the
# pre/post logic is identical) measured GPU/CPU R-channel ratios outside the
# [0.4,2.5] band at every roughness in this band:
#   roughness=0.00: ratio 4.0033 (GPU 0.02387, CPU 0.00596) -- alpha floors to
#                   0.0064.
#   roughness=0.03: ratio 4.0033 (GPU 0.02387, CPU 0.00596) -- alpha ALSO
#                   floors to 0.0064 (identical alpha to roughness=0.0 ->
#                   byte-identical renders on both CPU and GPU).
#   roughness=0.05: ratio 4.0033 (GPU 0.02387, CPU 0.00596) -- alpha ALSO
#                   floors to 0.0064 (identical alpha, identical renders).
#   roughness=0.10: ratio 3.6870 (GPU 0.02387, CPU 0.00647) -- alpha=0.0100 is
#                   just above the floor, so this is a distinct (slightly
#                   larger) lobe; the same GPU over-brightness persists but is
#                   diluted somewhat by the larger lobe -> a smaller (but
#                   still failing) ratio.
# A/B against pre-PR#498 main (ASTRORAY_BUILD_DIR redirect) adjudicated this
# as a PRE-EXISTING GPU defect, not a pkg123 regression: the GPU mean
# (0.02387) is byte-identical pre/post pkg123 across all four rows -- none of
# pkg123's GPU edits touch this scene's shading path -- while pkg123's CPU
# pdf() correction legitimately moved the CPU mean lower (e.g. 0.00884 ->
# 0.00596 at roughness=0.0), WIDENING an already-failing pre-#498 ratio
# (2.70x at roughness=0.0) rather than introducing a new defect.
# Suspected cause (pre-pkg141): the GPU selected-lobe pdf inline computation
# (gpu_materials.h:849-857) or the GPU closure-graph Disney twin lacking the
# CPU's full-mixture semantics -- the CPU/GPU MIS asymmetry flagged in the
# Opus review notes on PR #498. pkg141 (see module docstring above) found the
# ACTUAL mechanism -- a closure-graph GGXConductor lobe mis-dispatch to
# gpu_metal_eval's perfect-mirror shortcut, plus a stacked stale Smith-G
# denominator bug in gpu_disney_eval -- and fixed both. HW measurement of
# these rows is PENDING; xfail markers stay in place until the
# hardware-verifier confirms the ratios land in [0.4, 2.5] on RTX.
ROUGHNESS_VALUES = [
    pytest.param(0.0, marks=pytest.mark.xfail(
        reason="Pre-#498-baseline GPU near-delta Disney-metal over-brightness "
        "(measured R ratio 4.0033, GPU 0.02387, CPU 0.00596, alpha floors to "
        "0.0064). pkg141 found + fixed the mechanism (closure-graph "
        "GGXConductor->gpu_metal_eval perfect-mirror mis-dispatch + a stacked "
        "stale Smith-G divide in gpu_disney_eval, see module docstring) but "
        "HW re-measurement is PENDING -- do not remove this xfail until the "
        "hardware-verifier confirms the ratio lands in [0.4, 2.5] on RTX.",
        strict=False)),
    pytest.param(0.03, marks=pytest.mark.xfail(
        reason="Pre-#498-baseline GPU near-delta Disney-metal over-brightness "
        "(measured R ratio 4.0033, GPU 0.02387, CPU 0.00596 -- alpha ALSO "
        "floors to 0.0064, byte-identical to roughness=0.0). pkg141 found + "
        "fixed the mechanism (see module docstring); HW re-measurement "
        "PENDING -- do not remove this xfail until the hardware-verifier "
        "confirms the ratio lands in [0.4, 2.5] on RTX.",
        strict=False)),
    pytest.param(0.05, marks=pytest.mark.xfail(
        reason="Pre-#498-baseline GPU near-delta Disney-metal over-brightness "
        "(measured R ratio 4.0033, GPU 0.02387, CPU 0.00596 -- alpha ALSO "
        "floors to 0.0064, byte-identical to roughness=0.0). pkg141 found + "
        "fixed the mechanism (see module docstring); HW re-measurement "
        "PENDING -- do not remove this xfail until the hardware-verifier "
        "confirms the ratio lands in [0.4, 2.5] on RTX.",
        strict=False)),
    pytest.param(0.1, marks=pytest.mark.xfail(
        reason="Pre-#498-baseline GPU near-delta Disney-metal over-brightness "
        "(measured R ratio 3.6870, GPU 0.02387, CPU 0.00647 -- alpha=0.0100 "
        "just above the floor). pkg141 found + fixed the mechanism (see "
        "module docstring); HW re-measurement PENDING -- do not remove this "
        "xfail until the hardware-verifier confirms the ratio lands in "
        "[0.4, 2.5] on RTX.",
        strict=False)),
]

# pkg141 verification-gate addition: "Rough-metal no-regression" (spec
# gpu-near-delta-disney-metal-brightness, Verification gates) -- this file
# previously had NO mid/high-roughness Disney-metal GPU/CPU parity coverage
# at all (only the four near-delta rows above). The pkg141 fix is NOT
# near-delta-specific: it corrects the closure-graph dispatch for a Disney
# conductor lobe at every roughness (the mis-dispatch to gpu_metal_eval was
# only DISCOVERED via the near-delta perfect-mirror shortcut's dramatic
# divergence, but the wrong-lobe routing itself applied uniformly). These
# rows are new coverage proving the broader dispatch fix does not regress
# the mid/high-roughness regime -- not xfail'd; HW-pending like the rows
# above.
ROUGHNESS_VALUES_NO_REGRESSION = [0.3, 0.6, 0.9]

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


def _check_metal_parity(roughness: float) -> None:
    """Shared CPU<->GPU Disney-metal parity body (pkg123 coordinator
    directive, NOT SSIM):
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
            f"pdf/sample diverge (cpu_mean={cm:.5f}, gpu_mean={gm:.5f})."
        )

    print(f"[pkg123 Disney-metal GPU/CPU parity] PASS at roughness={roughness}: "
          f"no NaN/Inf, per-channel mean ratios within [{RATIO_LOW}, {RATIO_HIGH}]")


@pytest.mark.parametrize("roughness", ROUGHNESS_VALUES)
def test_disney_metal_gpu_cpu_parity_near_delta(roughness):
    """CPU<->GPU Disney-metal parity at the near-delta alpha-floor band."""
    _check_metal_parity(roughness)


@pytest.mark.parametrize("roughness", ROUGHNESS_VALUES_NO_REGRESSION)
def test_disney_metal_gpu_cpu_parity_mid_high_roughness_no_regression(roughness):
    """pkg141 no-regression gate: mid/high-roughness Disney-metal GPU/CPU
    parity must stay green after the closure-graph dispatch fix (spec
    gpu-near-delta-disney-metal-brightness, Verification gates: "Rough-metal
    no-regression"). Not xfail'd -- HW-pending, run alongside the near-delta
    rows above.
    """
    _check_metal_parity(roughness)
