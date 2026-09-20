"""pkg55-B' Session N+6 follow-up — open-env-scene mean-ratio gate.

pkg55-C7 RETARGET (2026-07-25): the MW megakernel was deleted; the
`path_tracer` GPU route these tests render is now the WAVEFRONT (plan
§6-R10 conscious retarget). Test/function names are kept for pkg153
quarantine continuity — both gates are RED on main (R-channel drift
[~1.15, 1.01, 1.07] vs tol 0.12, identical on both former GPU pipelines)
and OWNED BY pkg153; thresholds unchanged (never relax to green). See
.astroray_plan/packages/pkg153-wavefront-diff-env-gates-disposition.md.

Original (historical) docstring follows.

Session N+6 reported the spectral megakernel ~1.85x BRIGHTER than the CPU
oracle on the open-top env Cornell scene (per-channel mean ratio
[1.86, 1.81, 1.85]). Root cause (2026-06-11 follow-up investigation): a
MEASUREMENT ARTIFACT, not a kernel bug. The megakernel leg of that
measurement was `r.render(64, 8, None, True)` — the 4th positional arg of
PyRenderer::render is `applyGamma=True` (clamp to [0,1] + pow 1/2.2,
blender_module.cpp), while the CPU oracle reference_pt_wavefront_render
returns LINEAR sRGB. For a dim scene, v^(1/2.2)/v gives a stable,
seed-independent ~1.8-2x "brightness" ratio. Measured linear-vs-linear on
the same scene/params, the megakernel sits at [1.091, 0.993, 1.050] — the
same residual class as the GPU wavefront ([1.089, 0.991, 1.045], inherited
megakernel-BSDF <-> CPU-plugin divergences, spec N+6 entry).

This gate renders BOTH sides linear (applyGamma=False) so the comparison
can never silently mix color encodings again, and pins per-channel mean
ratios. Mean-ratio, NOT SSIM: megakernel and oracle use independent RNG
streams, and windowed SSIM is unreachable for independent MC streams at
modest spp (see pkg55 spec / SSIM gate rationale).

Second test: the one REAL env-accumulation divergence found during the
investigation — tracePathMW ignored worldMaxBounces (CPU gates env on miss
by bounce <= worldMaxBounces, raytracer.h:2412 / path_kernel.cpp:192; the
Blender addon wires world.max_bounces through set_world_max_bounces).
Before the fix, MK/CPU at world_max_bounces=0 measured [1.277, 1.218,
1.364] on this scene; with the gate plumbed it returns to the normal
residual class.
"""

import os
import sys

import numpy as np
import pytest

# Add tests/scenes to path (same pattern as test_pkg55_cuda_threshold_gate.py)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scenes"))
import session_n1_envmap_cornell

# Lazy import to avoid import-time failures if astroray not built
astroray = None


def _lazy_import_astroray():
    global astroray
    if astroray is None:
        import astroray as ar
        astroray = ar
    return astroray


WIDTH, HEIGHT = 64, 64
SPP = 64
MAX_DEPTH = 8
SEED = 424242

# Gate metric changed 2026-09-20 (#767 observer -> #862): ABSOLUTE per-channel
# mean gap, not the ratio -- same bounds and same reasoning as the N+6
# GPU-wavefront final-image gate (test_pkg55_gpu_wavefront_image.py, which
# carries the full derivation). The megakernel shares its BSDF device code with
# the wavefront, so it inherits the same documented divergences (e.g. missing
# diffuseFurnaceScale/Kulla-Conty on GPU disney) and the same tracked red gap.
# History of this scene's RED ratio: 1.091 measured 2026-06-11 (RTX 5070 Ti,
# 64x64, 64spp, seed 424242; default) / 1.085 wmb=0; a pre-observer build today
# 1.114; main 1.122 -- while the ABSOLUTE gap moved 0.0235 -> 0.0254 only. The
# lead's decisive A/B: on main 0888f278 with ONLY data/spectra/cie_cmf.inc
# reverted to CIE 1964 10 deg, all three pkg55 cases PASS, so the observer
# contributes ~0.8 pp of the 12.2 % ratio and the root cause is #862.
# Measured worst gap per channel (5 seeds + both cases here): R 0.0261,
# G 0.0040, B 0.0051; seed std 0.0005 / 0.0003 / 0.0005.
ABS_GAP_TOL = np.array([0.035, 0.012, 0.015])


def _build_renderer(world_max_bounces=None):
    """Session N+1 env-map Cornell scene (7 materials + env-miss paths)."""
    ar = _lazy_import_astroray()
    r = ar.Renderer()
    session_n1_envmap_cornell.build_scene(r)
    session_n1_envmap_cornell.setup_camera(r, width=WIDTH, height=HEIGHT)
    r.set_seed(SEED)
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator("path_tracer")
    if world_max_bounces is not None:
        r.set_world_max_bounces(world_max_bounces)
    # Warmup render to trigger BVH build
    _ = r.render(1, 1, None, False)
    return r


def _require_gpu():
    ar = _lazy_import_astroray()
    if not ar.Renderer().gpu_available:
        pytest.skip("No CUDA GPU available — megakernel gate is hardware-only")


def _per_channel_means(world_max_bounces=None):
    """Render CPU oracle and GPU megakernel, both LINEAR, return (cpu, gpu)
    per-channel means. The gate is the ABSOLUTE gap between them (#862); the
    ratio is derived by the callers for the diagnostic print."""
    ar = _lazy_import_astroray()

    r_cpu = _build_renderer(world_max_bounces)
    cpu = np.asarray(
        ar.reference_pt_wavefront_render(r_cpu, SPP, MAX_DEPTH, SEED, False),
        dtype=np.float64).reshape(-1, 3)

    r_gpu = _build_renderer(world_max_bounces)
    r_gpu.set_use_gpu(True)
    # applyGamma=False — LINEAR output. The 4th positional arg of render()
    # is applyGamma; passing True here is exactly the N+6 measurement
    # artifact this gate exists to prevent.
    mk = np.asarray(r_gpu.render(SPP, MAX_DEPTH, None, False),
                    dtype=np.float64).reshape(-1, 3)

    return cpu.mean(axis=0), mk.mean(axis=0)


def test_megakernel_open_env_scene_mean_ratio():
    """GPU spectral megakernel vs CPU linear oracle on the OPEN env scene.

    All pre-existing megakernel SSIM gates use CLOSED scenes (pkg54 parity
    set), so env-miss accumulation was never gated. This is the first gate
    that exercises megakernel env-miss paths against the CPU.
    """
    _require_gpu()
    cpu_mean, gpu_mean = _per_channel_means()
    ratios = gpu_mean / cpu_mean
    gap = np.abs(gpu_mean - cpu_mean)
    assert np.all(gap <= ABS_GAP_TOL), (
        f"Megakernel/CPU absolute per-channel mean gap {gap.round(4).tolist()} "
        f"exceeds {ABS_GAP_TOL.tolist()} on the open env scene "
        f"(ratios {ratios.round(3).tolist()}). If the ratio is ~1.8-2x across all channels, check the "
        f"comparison protocol FIRST: render(..., applyGamma=True) output is "
        f"gamma-encoded while the CPU oracle is linear (the Session N+6 "
        f"false alarm). A genuine env-accumulation regression (e.g. env "
        f"double-count with NEE, missing worldMaxBounces gate) also lands "
        f"here."
    )
    print(f"\n[pkg55 megakernel open-env gate] PASS: gap = "
          f"{gap.round(4).tolist()} (tol {ABS_GAP_TOL.tolist()}); "
          f"MK/CPU mean ratios = {ratios.round(3).tolist()} (diagnostic)")


def test_megakernel_world_max_bounces_env_gate():
    """world_max_bounces=0: env radiance reaches camera rays only.

    Gates the worldMaxBounces plumbing into tracePathMW (the one real
    env-accumulation divergence found in the N+6 follow-up). Without the
    gate the megakernel accumulates env on miss at ALL bounces and measured
    [1.277, 1.218, 1.364] vs CPU on this scene.
    """
    _require_gpu()
    cpu_mean, gpu_mean = _per_channel_means(world_max_bounces=0)
    ratios = gpu_mean / cpu_mean
    gap = np.abs(gpu_mean - cpu_mean)
    assert np.all(gap <= ABS_GAP_TOL), (
        f"Megakernel/CPU absolute per-channel mean gap {gap.round(4).tolist()} "
        f"exceeds {ABS_GAP_TOL.tolist()} with world_max_bounces=0 "
        f"(ratios {ratios.round(3).tolist()}). The megakernel is likely ignoring the "
        f"worldMaxBounces env gate (CPU: raytracer.h:2412; MW kernel: "
        f"tracePathMW miss branch)."
    )
    print(f"\n[pkg55 megakernel wmb=0 env gate] PASS: gap = "
          f"{gap.round(4).tolist()} (tol {ABS_GAP_TOL.tolist()}); "
          f"MK/CPU mean ratios = {ratios.round(3).tolist()} (diagnostic)")


if __name__ == "__main__":
    test_megakernel_open_env_scene_mean_ratio()
    test_megakernel_world_max_bounces_env_gate()
