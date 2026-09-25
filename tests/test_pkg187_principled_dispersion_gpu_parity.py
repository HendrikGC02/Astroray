"""pkg187 — dispersive Principled on the GPU wavefront leg: wired + faithful mirror.

UPDATED 2026-08-13 by pkg189: the "GPU dispersion is a frozen no-op" premise below
is HISTORICAL. pkg189 enabled the GPU wavefront hero-λ collapse (persisting it to
SoA), so dispersion is now LIVE for BOTH dielectric and Principled — exactly as the
"enabling it lights up BOTH" note predicted. test_gpu_dispersion_wired_mirrors_
dielectric_reference below has been flipped to assert the live behavior; the CPU
companion is unchanged. The no-op measurements in the table below are the pre-pkg189
state, kept for the record.

WHY THIS GATE IS "MIRROR THE DIELECTRIC", NOT "GPU==CPU"
--------------------------------------------------------
The production GPU path is the wavefront (megakernels were deleted;
src/gpu/wavefront/stage_advance.cu -> gpu_material_sample_spectral). On that leg
the spectral hero-wavelength-collapse dispersion is a PRE-EXISTING, frozen
feature: the only end-to-end GPU dispersion test (test_pkg64_gpu_cpu_parity) has
been xfail since 2026-06-08 ("SMS-GPU is frozen"), and pkg64 defers GPU
per-wavelength multi-IOR refraction to a Session-2 increment. Measured on this
build (256 spp, spectral srgb, glass sphere refracting a colored backdrop):

    PRINCIPLED  CPU flat=0.2053 disp=0.1138 | GPU flat=0.2041 disp=0.2041
    DIELECTRIC  CPU flat=0.2144 bk7 =0.1183 | GPU flat=0.2131 bk7 =0.2139

i.e. CPU dispersion is live for BOTH materials, GPU dispersion is a no-op for
BOTH. pkg187 wires Principled into the SAME infrastructure the dielectric uses
(scene_upload uploads the Cauchy fit + isDispersive; gpu_material_sample_spectral
injects the hero-IOR + terminateSecondary). So the correct, ACHIEVABLE GPU gate
is: pkg187 introduces NO NEW divergence — GPU dispersive Principled tracks the
GPU dispersive DIELECTRIC reference (both no-op on the wavefront leg today), and
GPU dispersive Principled tracks GPU flat Principled (the gated no-op). A CPU
companion proves the wiring is REAL (dispersion measurably changes the render,
mirroring the dielectric). The full chromatic-caustic visual gate stays CPU-side
(test_pkg187_principled_dispersion.py).

GPU-visible wavefront dispersion is a separately-filed follow-up (2026-08-12);
enabling it lights up BOTH dielectric and Principled through this same wiring.
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
        "CUDA feature not in this build -- pkg187 GPU dispersion wiring gate needs "
        "the RTX box (LEAD runs this).",
        allow_module_level=True,
    )

WIDTH = HEIGHT = 48
SAMPLES = 256
MAX_DEPTH = 8
SEED = 187187

DISP = {"dispersion_scale": 1.0, "dispersion_abbe": 20.0}


def _render(use_gpu: bool, kind: str, params: dict) -> np.ndarray:
    r = astroray.Renderer()
    r.set_background_color([0.30, 0.45, 0.65])
    red = r.create_material("lambertian", [1.0, 0.05, 0.03], {})
    green = r.create_material("lambertian", [0.05, 1.0, 0.08], {})
    blue = r.create_material("lambertian", [0.03, 0.08, 1.0], {})
    r.add_triangle([-3, -3, -2.5], [0, -3, -2.5], [0, 3, -2.5], red)
    r.add_triangle([-3, -3, -2.5], [0, 3, -2.5], [-3, 3, -2.5], red)
    r.add_triangle([0, -3, -2.5], [3, -3, -2.5], [3, 3, -2.5], blue)
    r.add_triangle([0, -3, -2.5], [3, 3, -2.5], [0, 3, -2.5], blue)
    r.add_triangle([-3, -3, -2.6], [3, -3, -2.6], [0, -1.2, -2.6], green)
    mat = r.create_material(kind, [1.0, 1.0, 1.0], params)
    r.add_sphere([0.0, 0.0, 0.0], 0.9, mat)
    r.setup_camera([0.0, 0.0, 2.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   55.0, WIDTH / HEIGHT, 0.0, 2.0, WIDTH, HEIGHT)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    if use_gpu:
        r.set_use_gpu(True)
        r.set_wavelength_range(380.0, 780.0)   # engage the spectral wavefront leg
        r.set_output_mode("srgb")
    r.set_seed(SEED)
    return np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float64)


def _means(img):
    return np.array([float(img[..., c].mean()) for c in range(3)])


_P_FLAT = {"transmission_weight": 1.0, "ior": 1.5, "roughness": 0.02, "metallic": 0.0}
_P_DISP = {**_P_FLAT, **DISP}


ENERGY_TOL = 0.05


def _check_mirrors_dielectric(use_gpu: bool) -> None:
    """Dispersion is LIVE (signed red/blue fringes at achromatic edges), conserves
    energy (disp/flat within +-5 %), and Principled mirrors the dielectric
    reference on both counts.

    UPDATED 2026-09-25 (hero-collapse pdf fix): the former liveness gate
    (disp/flat < 0.90, "dispersion dims the mean ~0.55x") encoded the
    terminateSecondary bug (no pbrt-v4 pdf[0] /= N -> dispersive transmission
    ~4x too dark). Measured after the fix: disp/flat 1.006 (Principled) on both
    backends."""
    import os
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from scenes.prism_reference import edge_fringe, render_edge_prism

    tag = "GPU" if use_gpu else "CPU"
    p_ratio = float(_means(_render(use_gpu, "principled", _P_DISP)).mean()
                    / max(_means(_render(use_gpu, "principled", _P_FLAT)).mean(), 1e-8))
    d_ratio = float(_means(_render(use_gpu, "dielectric", {"sellmeier_preset": "bk7"})).mean()
                    / max(_means(_render(use_gpu, "dielectric", {"ior": 1.5})).mean(), 1e-8))
    fr = {name: edge_fringe(render_edge_prism(astroray, kind, params, use_gpu=use_gpu))
          for name, kind, params in [("p_flat", "principled", _P_FLAT),
                                     ("p_disp", "principled", _P_DISP),
                                     ("d_flat", "dielectric", {"ior": 1.5}),
                                     ("d_disp", "dielectric", {"sellmeier_preset": "bk7"})]}
    print(f"\n[pkg187 {tag}] disp/flat principled={p_ratio:.4f} dielectric={d_ratio:.4f} "
          f"fringe {({k: round(v, 4) for k, v in fr.items()})}")

    for name, ratio in (("principled", p_ratio), ("dielectric", d_ratio)):
        assert abs(ratio - 1.0) <= ENERGY_TOL, (
            f"{tag} {name}: disp/flat={ratio:.4f} outside 1+-{ENERGY_TOL} "
            f"(hero-collapse pdf rescale missing or doubled?)")
    for m in ("p", "d"):
        assert fr[f"{m}_disp"] > 0.15 and fr[f"{m}_disp"] > 4.0 * fr[f"{m}_flat"], (
            f"{tag} {'principled' if m == 'p' else 'dielectric'}: dispersion not live "
            f"(edge fringe {fr[f'{m}_disp']:.4f} vs flat {fr[f'{m}_flat']:.4f}); "
            f"on GPU check the pkg189 HasDispersion write-back.")
    assert abs(p_ratio - d_ratio) <= ENERGY_TOL, (
        f"{tag}: Principled disp/flat {p_ratio:.4f} diverges from dielectric {d_ratio:.4f}")


def test_gpu_dispersion_wired_mirrors_dielectric_reference():
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available on this machine")
    _check_mirrors_dielectric(use_gpu=True)


def test_cpu_dispersion_is_real_and_mirrors_dielectric():
    _check_mirrors_dielectric(use_gpu=False)


# ===========================================================================
# LEAD RUN COMMANDS (after build_cuda_worktree.bat, on the RTX box, GPU lock held):
#   pytest tests/test_pkg187_principled_dispersion_gpu_parity.py -v -s
# ===========================================================================
