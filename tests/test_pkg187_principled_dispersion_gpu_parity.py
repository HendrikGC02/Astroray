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


def test_gpu_dispersion_wired_mirrors_dielectric_reference():
    # --- UPDATED by pkg189 (GPU wavefront hero-λ dispersion enablement). ---
    # This gate ORIGINALLY (pkg187) asserted GPU dispersion was a NO-OP
    # (0.95 <= disp/flat <= 1.05) for BOTH the dielectric reference and the
    # Principled wiring, because the GPU wavefront hero-collapse never persisted
    # to SoA (the pkg187 docstring above predicted: "enabling it lights up BOTH
    # dielectric and Principled through this same wiring"). pkg189 landed that
    # enablement, so the no-op assertion is now FALSE: dispersion measurably dims
    # the mean (the hero collapse drops the broadband wash), tracking the CPU
    # reference. The gate is flipped to assert dispersion is LIVE and that
    # Principled still MIRRORS the dielectric reference (the original intent).
    gp_flat = _means(_render(True, "principled", _P_FLAT))
    gp_disp = _means(_render(True, "principled", _P_DISP))
    gd_flat = _means(_render(True, "dielectric", {"ior": 1.5}))
    gd_disp = _means(_render(True, "dielectric", {"sellmeier_preset": "bk7"}))

    p_ratio = float(gp_disp.mean() / max(gp_flat.mean(), 1e-8))   # Principled disp/flat on GPU
    d_ratio = float(gd_disp.mean() / max(gd_flat.mean(), 1e-8))   # dielectric reference disp/flat on GPU

    print("\n[pkg189 GPU wiring gate — dispersion now LIVE]")
    print(f"  GPU principled disp/flat = {p_ratio:.4f}")
    print(f"  GPU dielectric disp/flat = {d_ratio:.4f}")

    # Dispersion is LIVE on the GPU wavefront leg (was a no-op ~1.0 pre-pkg189).
    assert p_ratio < 0.90, (
        f"pkg189 GPU: Principled dispersion is still a no-op (disp/flat={p_ratio:.4f} "
        f">= 0.90) — the hero-λ collapse write-back is not reaching the Principled "
        f"(<true,...,true>) shade instantiation.")
    assert d_ratio < 0.90, (
        f"pkg189 GPU: dielectric dispersion is still a no-op (disp/flat={d_ratio:.4f} "
        f">= 0.90) — the hero-λ collapse write-back is not reaching the dielectric "
        f"(<false,...,true>) shade instantiation.")
    # Principled tracks the dielectric reference's dispersion magnitude (original
    # "mirrors dielectric" intent): both dim by a similar factor.
    assert abs(p_ratio - d_ratio) < 0.15, (
        f"pkg189 GPU: Principled dispersion magnitude ({p_ratio:.4f}) diverges from "
        f"the dielectric reference ({d_ratio:.4f}) by > 0.15.")


def test_cpu_dispersion_is_real_and_mirrors_dielectric():
    # Companion to the GPU no-op gate: on CPU the wiring is LIVE -- Principled
    # dispersion measurably changes the render, tracking the dielectric reference.
    cp_flat = _means(_render(False, "principled", _P_FLAT)).mean()
    cp_disp = _means(_render(False, "principled", _P_DISP)).mean()
    cd_flat = _means(_render(False, "dielectric", {"ior": 1.5})).mean()
    cd_disp = _means(_render(False, "dielectric", {"sellmeier_preset": "bk7"})).mean()

    p_eff = cp_disp / cp_flat
    d_eff = cd_disp / cd_flat
    print(f"\n[pkg187 CPU wiring-is-real] principled disp/flat={p_eff:.4f} "
          f"dielectric bk7/flat={d_eff:.4f}")

    # CPU dispersion is live for Principled (dims, exactly as the dielectric does).
    assert p_eff < 0.9, (
        f"pkg187 CPU: Principled dispersion had no effect (disp/flat={p_eff:.4f}); "
        f"the CPU wiring is broken.")
    # And it tracks the dielectric reference's dispersion magnitude.
    assert abs(p_eff - d_eff) < 0.1, (
        f"pkg187 CPU: Principled dispersion magnitude ({p_eff:.4f}) diverges from "
        f"the dielectric reference ({d_eff:.4f}).")


# ===========================================================================
# LEAD RUN COMMANDS (after build_cuda_worktree.bat, on the RTX box, GPU lock held):
#   pytest tests/test_pkg187_principled_dispersion_gpu_parity.py -v -s
# ===========================================================================
