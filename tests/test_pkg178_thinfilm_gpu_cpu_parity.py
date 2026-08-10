"""pkg178 Stage 4 PR-3 — thin-film iridescence GPU(wavefront) <-> CPU parity
plus the thickness-0 GPU bit-identity no-op guard.

DRAFTED by the package-implementer, NOT YET RUN: subagents on this machine
cannot build CUDA, so the GPU leg has never executed. The building/verifying
LEAD must run this after `build_cuda_worktree.bat` and record the measured
per-channel numbers in the PR. See the module footer for the exact commands.

Why this file exists
--------------------
PR-3 lands the GPU twin of the CPU thin-film work (PR-1 dielectric, PR-2
conductor). The device code (gpu_pr_thinFilm* in include/astroray/gpu_materials.h)
calls the SAME shared Belcour-Barla core (include/astroray/thin_film_fresnel.h)
as plugins/materials/principled.cpp, with the conductor (n,k,g) host-precomputed
at upload (scene_upload.cu) exactly as principled.cpp::precomputeConductorNK. So
CPU<->GPU should match TIGHTLY — this is the gate that proves the two legs agree.

Two gates here:
  1. test_thinfilm_zero_thickness_bit_identity — the load-bearing no-op: a GPU
     render with thin_film_thickness=0 must be BYTE-identical to the same GPU
     render with no thin-film param at all (film gated OFF below the 0.1nm
     cutoff, so the eval path is textually unchanged from PR-6).
  2. test_thinfilm_gpu_cpu_parity — dielectric specular / glass transmission /
     metallic spheres across a thickness sweep, per-channel mean + ratio-of-
     medians inside the band (ratio-of-medians, not median-of-ratios, because the
     backends draw independent MC streams; memory
     ssim-wrong-gate-for-independent-rng).

Bands are PROVISIONAL scaffolding: [0.95, 1.05] is the target for a genuinely
matched material (same math both legs). The lead re-measures on RTX and either
confirms the band or documents a per-row exception with a cause (do NOT loosen
silently). The RGB<->spectral hue difference is by construction and NOT gated
here (pkg128 §B); this test renders RGB on both legs.
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
        "CUDA feature not in this build -- pkg178 thin-film GPU/CPU parity "
        "needs the RTX box (LEAD runs this).",
        allow_module_level=True,
    )

WIDTH = HEIGHT = 48
SAMPLES = 256
MAX_DEPTH = 6
SEED = 178403

ALBEDO = [0.82, 0.66, 0.34]
BACKGROUND = [0.35, 0.45, 0.60]

RATIO_LOW = 0.95
RATIO_HIGH = 1.05

# thin_film_ior 1.4 (soap-ish); thickness sweep in nm. Each base material gets
# the same sweep so a lobe-specific divergence shows as a whole-column failure.
FILM_IOR = 1.4
THICKNESSES = [200.0, 550.0, 1200.0]

BASE_CASES = [
    ("dielectric_spec", {"metallic": 0.0, "roughness": 0.25}),
    ("glass_r0.2", {"metallic": 0.0, "transmission_weight": 1.0, "ior": 1.5, "roughness": 0.2}),
    ("metallic_r0.3", {"metallic": 1.0, "roughness": 0.3}),
]

CASES = []
for _label, _base in BASE_CASES:
    for _d in THICKNESSES:
        _p = dict(_base)
        _p["thin_film_thickness"] = _d
        _p["thin_film_ior"] = FILM_IOR
        CASES.append((f"{_label}_d{int(_d)}", _p))


def _make_scene(use_gpu: bool, params: dict):
    r = astroray.Renderer()
    r.set_background_color(BACKGROUND)
    mat = r.create_material("principled", ALBEDO, params)
    r.add_sphere([0.0, 0.0, 0.0], 0.9, mat)
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


@pytest.mark.parametrize(
    "params",
    [
        {"metallic": 0.0, "roughness": 0.25},
        {"metallic": 1.0, "roughness": 0.3},
        {"metallic": 0.0, "transmission_weight": 1.0, "ior": 1.5, "roughness": 0.2},
    ],
    ids=["dielectric_spec", "metallic", "glass"],
)
def test_thinfilm_zero_thickness_bit_identity(params):
    """The load-bearing no-op: GPU with thin_film_thickness=0 == GPU with no
    thin-film param at all (film gated off below the 0.1nm cutoff)."""
    off = _render(use_gpu=True, params=params)
    zero = _render(use_gpu=True, params={**params, "thin_film_thickness": 0.0,
                                         "thin_film_ior": FILM_IOR})
    assert np.array_equal(off, zero), (
        "pkg178 PR-3 thickness-0 GPU bit-identity FAILED: film-off and "
        "thickness=0 renders differ (max abs diff "
        f"{np.max(np.abs(off - zero)):.3e}) -- the film no-op guard is broken.")


@pytest.mark.parametrize("label,params", CASES, ids=[c[0] for c in CASES])
def test_thinfilm_gpu_cpu_parity(label, params):
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

    print(f"\n[pkg178 thin-film GPU/CPU parity] case={label} "
          f"band=[{RATIO_LOW}, {RATIO_HIGH}]")
    for ch, cm, gm, mr, cmed, gmed, medr in rows:
        print(f"  {ch}: mean cpu={cm:.5f} gpu={gm:.5f} ratio={mr:.4f} | "
              f"median cpu={cmed:.5f} gpu={gmed:.5f} ratio={medr:.4f}")

    for ch, cm, gm, mr, cmed, gmed, medr in rows:
        assert RATIO_LOW <= mr <= RATIO_HIGH, (
            f"pkg178 thin-film GPU/CPU MEAN parity FAILED case={label} "
            f"channel {ch}: ratio {mr:.4f} outside [{RATIO_LOW}, {RATIO_HIGH}] "
            f"(cpu={cm:.5f}, gpu={gm:.5f})")
        assert RATIO_LOW <= medr <= RATIO_HIGH, (
            f"pkg178 thin-film GPU/CPU MEDIAN parity FAILED case={label} "
            f"channel {ch}: ratio {medr:.4f} outside [{RATIO_LOW}, {RATIO_HIGH}] "
            f"(cpu={cmed:.5f}, gpu={gmed:.5f})")


# ===========================================================================
# LEAD RUN COMMANDS (after build_cuda_worktree.bat, on the RTX box):
#   pytest tests/test_pkg178_thinfilm_gpu_cpu_parity.py -v -s
# The -s flag surfaces the per-channel measured ratios to paste into the PR.
# ===========================================================================
