"""pkg178 Stage 2 — native `principled` GPU(wavefront) <-> CPU render parity.

DRAFTED by the package-implementer, NOT YET RUN: subagents on this machine
cannot build CUDA, so the GPU leg has never executed. The building/verifying
LEAD must run this after `build_cuda_worktree.bat` and record the measured
per-channel numbers in the PR. See the module footer for the exact commands.

Why this file exists
--------------------
Stage 2 lands the GPU twin of the Stage-1 CPU core lobes (diffuse Lambert/EON,
specular GGX generalized-Schlick, metallic F82-tint, transmission rough glass)
via GMAT_CLOSURE_GRAPH + a single monolithic GCLOSURE_PRINCIPLED closure whose
device code (gpu_principled_* in include/astroray/gpu_materials.h) mirrors
plugins/materials/principled.cpp line-for-line. This is the gate that proves the
two legs agree; CPU<->GPU divergence in a monolithic BSDF twin is exactly the
pkg141/160/163/168/170 bug class this test is here to catch.

Scene / method (mirrors tests/test_pkg160_plain_metal_gpu_cpu_parity.py)
------------------------------------------------------------------------
A single principled sphere that FILLS the frame inside a uniform environment,
nothing else. Full coverage => no background pixels diluting the statistics
toward 1.0 (the whole-image-mean trap that hid pkg160 for so long); a uniform
environment lights every roughness including the near-delta rows. Per channel,
BOTH the mean ratio and the ratio-of-medians must land inside the band at every
row. Ratio-of-medians (not median-of-ratios) because the two backends draw
independent MC streams (memory ssim-wrong-gate-for-independent-rng).

Bands are PROVISIONAL scaffolding: [0.95, 1.05] is the target for a genuinely
matched material (pkg160 reference). The lead re-measures on RTX and, per the
Stage-0 APPROXIMATED policy, either confirms the band or documents a per-row
exception with a cause (do NOT loosen silently).
"""

from __future__ import annotations

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip(
        "CUDA feature not in this build -- pkg178 principled GPU/CPU parity "
        "needs the RTX box (LEAD runs this).",
        allow_module_level=True,
    )

WIDTH = HEIGHT = 48
SAMPLES = 256
MAX_DEPTH = 6
SEED = 178178

ALBEDO = [0.82, 0.66, 0.34]
BACKGROUND = [0.35, 0.45, 0.60]

RATIO_LOW = 0.95
RATIO_HIGH = 1.05

# (label, params) — one row per core-lobe axis. transmission_weight is the
# Cycles socket name the Stage-1 ctor reads (principled.cpp:587-588).
CASES = [
    ("diffuse_lambert", {"metallic": 0.0, "roughness": 0.5}),
    ("diffuse_eon", {"metallic": 0.0, "roughness": 0.5, "diffuse_roughness": 0.8}),
    ("metallic_r0.3", {"metallic": 1.0, "roughness": 0.3}),
    ("metallic_r0.6", {"metallic": 1.0, "roughness": 0.6}),
    ("glass_r0.1", {"metallic": 0.0, "transmission_weight": 1.0, "ior": 1.5, "roughness": 0.1}),
    ("glass_r0.4", {"metallic": 0.0, "transmission_weight": 1.0, "ior": 1.5, "roughness": 0.4}),
]


def _make_scene(use_gpu: bool, params: dict):
    r = astroray.Renderer()
    r.set_background_color(BACKGROUND)
    mat = r.create_material("principled", ALBEDO, params)
    r.add_sphere([0.0, 0.0, 0.0], 0.9, mat)
    # Same full-coverage framing as pkg160: sphere angular radius (41.8 deg)
    # exceeds the frame corner (39.2 deg), so every primary ray hits the sphere.
    r.setup_camera([0.0, 0.0, 1.35], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   60.0, WIDTH / HEIGHT, 0.0, 1.35, WIDTH, HEIGHT)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    if use_gpu:
        r.set_use_gpu(True)
    return r


def _render(use_gpu: bool, params: dict) -> np.ndarray:
    r = _make_scene(use_gpu=use_gpu, params=params)
    r.set_seed(SEED)
    # 4th positional arg is applyGamma -- False keeps both sides linear
    # (memory gamma-vs-linear-comparison-artifact).
    return np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float64)


@pytest.mark.parametrize("label,params", CASES, ids=[c[0] for c in CASES])
def test_principled_gpu_cpu_parity(label, params):
    gpu = _render(use_gpu=True, params=params)
    cpu = _render(use_gpu=False, params=params)

    assert gpu.shape == (HEIGHT, WIDTH, 3)
    assert cpu.shape == (HEIGHT, WIDTH, 3)
    assert np.all(np.isfinite(gpu)), "GPU render produced NaN/Inf"
    assert np.all(np.isfinite(cpu)), "CPU render produced NaN/Inf"

    rows = []
    for c, ch in enumerate("RGB"):
        cpu_mean, gpu_mean = float(cpu[..., c].mean()), float(gpu[..., c].mean())
        cpu_med, gpu_med = float(np.median(cpu[..., c])), float(np.median(gpu[..., c]))
        mr = gpu_mean / cpu_mean if cpu_mean > 1e-8 else float("nan")
        medr = gpu_med / cpu_med if cpu_med > 1e-8 else float("nan")
        rows.append((ch, cpu_mean, gpu_mean, mr, cpu_med, gpu_med, medr))

    print(f"\n[pkg178 principled GPU/CPU parity] case={label} "
          f"band=[{RATIO_LOW}, {RATIO_HIGH}]")
    for ch, cm, gm, mr, cmed, gmed, medr in rows:
        print(f"  {ch}: mean cpu={cm:.5f} gpu={gm:.5f} ratio={mr:.4f} | "
              f"median cpu={cmed:.5f} gpu={gmed:.5f} ratio={medr:.4f}")

    for ch, cm, gm, mr, cmed, gmed, medr in rows:
        assert RATIO_LOW <= mr <= RATIO_HIGH, (
            f"pkg178 principled GPU/CPU MEAN parity FAILED case={label} "
            f"channel {ch}: ratio {mr:.4f} outside [{RATIO_LOW}, {RATIO_HIGH}] "
            f"(cpu={cm:.5f}, gpu={gm:.5f})")
        assert RATIO_LOW <= medr <= RATIO_HIGH, (
            f"pkg178 principled GPU/CPU MEDIAN parity FAILED case={label} "
            f"channel {ch}: ratio {medr:.4f} outside [{RATIO_LOW}, {RATIO_HIGH}] "
            f"(cpu={cmed:.5f}, gpu={gmed:.5f})")


# ===========================================================================
# LEAD RUN COMMANDS (after build_cuda_worktree.bat, on the RTX box):
#   pytest tests/test_pkg178_principled_gpu_cpu_parity.py -v -s
# The -s flag surfaces the per-channel measured ratios to paste into the PR.
# ===========================================================================
