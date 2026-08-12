"""pkg188 — Principled transmission colour/scalar-separation CPU<->GPU parity.

Finding A rewrote the film-OFF transmission spectral eval so the chromatic
reflectance COLOUR is upsampled at its natural magnitude and the achromatic
geometry/Fresnel scalar (incl. the glass eta^2) is applied AFTER the upsample,
instead of upsampling the whole RGB product with a max(...,1) floor (which, for a
sub-unit BSDF value, upsampled colour*scalar directly — the Jakob-Hanika
magnitude-nonlinearity bug pkg168/pkg167 already fixed elsewhere). Finding B added
the weight-path clamp-guard on the same eval.

Both the CPU eval (principled.cpp) and its device twin (gpu_materials.h) got the
identical rewrite. The risk this file guards is that the two legs drift out of
lockstep — a monolithic-BSDF twin divergence, exactly the pkg141/160/163/168/170
bug class. `path_tracer` is spectral-first, so a plain render() exercises the
spectral eval directly.

The materials use a SATURATED transmission tint (red-orange glass), which is where
the JH magnitude-nonlinearity has the largest effect, plus a coat-over-tinted-base
layered case that drives a chromatic running `weight` through the guarded path.

CUDA-gated: the building/verifying LEAD runs this on the RTX box and pastes the
per-channel ratios into the PR (commands in the footer).
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
        "CUDA feature not in this build -- pkg188 transmission parity needs the "
        "RTX box (LEAD runs this).",
        allow_module_level=True,
    )

WIDTH = HEIGHT = 48
SAMPLES = 256
MAX_DEPTH = 6
SEED = 188188

# Saturated red-orange glass tint: sqrt(base_color) tints the transmission lobe,
# so a strongly chromatic base is the maximal Finding-A signal.
GLASS_TINT = [0.85, 0.22, 0.10]
BACKGROUND = [0.40, 0.45, 0.55]

RATIO_LOW = 0.95
RATIO_HIGH = 1.05

CASES = [
    ("glass_tint_r0.15",
     GLASS_TINT, {"metallic": 0.0, "transmission_weight": 1.0, "ior": 1.5, "roughness": 0.15}),
    ("glass_tint_r0.40",
     GLASS_TINT, {"metallic": 0.0, "transmission_weight": 1.0, "ior": 1.5, "roughness": 0.40}),
    # Coat over a tinted transmissive base: the coat Beer tint makes the running
    # layering `weight` chromatic before it reaches the transmission lobe, so this
    # row exercises the Finding-B weight-path guard together with Finding A.
    ("coat_over_tinted_glass",
     GLASS_TINT, {"metallic": 0.0, "transmission_weight": 0.8, "ior": 1.5, "roughness": 0.25,
                  "coat_weight": 1.0, "coat_roughness": 0.1, "coat_tint": [0.3, 0.7, 1.0]}),
]


def _make_scene(use_gpu: bool, color, params: dict):
    r = astroray.Renderer()
    r.set_background_color(BACKGROUND)
    mat = r.create_material("principled", color, params)
    r.add_sphere([0.0, 0.0, 0.0], 0.9, mat)
    # Full-frame coverage (pkg160/pkg178 framing): every primary ray hits the sphere.
    r.setup_camera([0.0, 0.0, 1.35], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   60.0, WIDTH / HEIGHT, 0.0, 1.35, WIDTH, HEIGHT)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    if use_gpu:
        r.set_use_gpu(True)
    return r


def _render(use_gpu: bool, color, params: dict) -> np.ndarray:
    r = _make_scene(use_gpu=use_gpu, color=color, params=params)
    r.set_seed(SEED)
    # 4th positional arg is applyGamma -- False keeps both legs linear.
    return np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float64)


@pytest.mark.parametrize("label,color,params", CASES, ids=[c[0] for c in CASES])
def test_pkg188_transmission_gpu_cpu_parity(label, color, params):
    gpu = _render(use_gpu=True, color=color, params=params)
    cpu = _render(use_gpu=False, color=color, params=params)

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

    print(f"\n[pkg188 transmission GPU/CPU parity] case={label} "
          f"band=[{RATIO_LOW}, {RATIO_HIGH}]")
    for ch, cm, gm, mr, cmed, gmed, medr in rows:
        print(f"  {ch}: mean cpu={cm:.5f} gpu={gm:.5f} ratio={mr:.4f} | "
              f"median cpu={cmed:.5f} gpu={gmed:.5f} ratio={medr:.4f}")

    for ch, cm, gm, mr, cmed, gmed, medr in rows:
        assert RATIO_LOW <= mr <= RATIO_HIGH, (
            f"pkg188 transmission GPU/CPU MEAN parity FAILED case={label} "
            f"channel {ch}: ratio {mr:.4f} outside [{RATIO_LOW}, {RATIO_HIGH}] "
            f"(cpu={cm:.5f}, gpu={gm:.5f})")
        assert RATIO_LOW <= medr <= RATIO_HIGH, (
            f"pkg188 transmission GPU/CPU MEDIAN parity FAILED case={label} "
            f"channel {ch}: ratio {medr:.4f} outside [{RATIO_LOW}, {RATIO_HIGH}] "
            f"(cpu={cmed:.5f}, gpu={gmed:.5f})")


# ===========================================================================
# LEAD RUN COMMANDS (after build_cuda_worktree.bat, on the RTX box):
#   pytest tests/test_pkg188_transmission_colour_upsample_parity.py -v -s
# The -s flag surfaces the per-channel measured ratios to paste into the PR.
# ===========================================================================
