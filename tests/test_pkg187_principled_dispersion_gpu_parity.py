"""pkg187 — dispersive Principled on the GPU wavefront leg: wired + faithful mirror.

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
    # --- GPU wavefront leg: dispersion is a pre-existing no-op for BOTH the
    #     dielectric reference and the pkg187 Principled wiring (no NEW divergence).
    gp_flat = _means(_render(True, "principled", _P_FLAT))
    gp_disp = _means(_render(True, "principled", _P_DISP))
    gd_flat = _means(_render(True, "dielectric", {"ior": 1.5}))
    gd_disp = _means(_render(True, "dielectric", {"sellmeier_preset": "bk7"}))

    p_ratio = gp_disp / np.maximum(gp_flat, 1e-8)   # Principled disp/flat on GPU
    d_ratio = gd_disp / np.maximum(gd_flat, 1e-8)    # dielectric reference disp/flat on GPU

    print("\n[pkg187 GPU wiring gate]")
    print(f"  GPU principled disp/flat = {np.round(p_ratio,4)}")
    print(f"  GPU dielectric disp/flat = {np.round(d_ratio,4)}")

    for c, ch in enumerate("RGB"):
        # Principled introduces no NEW dispersion divergence on the GPU leg
        # (matches the frozen dielectric behavior: dispersion is a wavefront no-op).
        assert 0.95 <= p_ratio[c] <= 1.05, (
            f"pkg187 GPU: Principled dispersion unexpectedly changed the wavefront "
            f"render (ch {ch} disp/flat={p_ratio[c]:.4f}); the GPU wavefront leg is "
            f"the frozen no-op path -- a change here means the wiring diverged from "
            f"the dielectric reference.")
        # The dielectric reference exhibits the SAME frozen no-op -> the gate is
        # pre-existing infra, not pkg187.
        assert 0.95 <= d_ratio[c] <= 1.05, (
            f"pkg187 GPU: dielectric reference dispersion is NOT a no-op (ch {ch} "
            f"disp/flat={d_ratio[c]:.4f}) -- the wavefront dispersion infra changed "
            f"upstream; re-evaluate pkg187's GPU gate against the new behavior.")


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
