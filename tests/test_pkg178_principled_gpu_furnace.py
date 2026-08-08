"""pkg178 Stage 2 — native `principled` GPU white-furnace energy conservation.

DRAFTED by the package-implementer, NOT YET RUN: no CUDA build available to a
subagent on this machine. The building/verifying LEAD runs this on RTX and
records the measured means in the PR (commands in the module footer).

This is the GPU twin of the Stage-1 CPU furnace (tests/test_principled_bsdf.py).
Each core lobe is compared to a white Lambertian rendered on the SAME backend
(GPU), LINEAR (apply_gamma=False), with a floor AND a ceiling (pkg166 / memory
gamma-furnace-cannot-detect-energy-gain: a gamma furnace can never see an energy
GAIN, and a floor-only furnace can never see one either). The bands mirror the
CPU furnace floors; the lead confirms or documents an exception on RTX.
"""
import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip(
        "CUDA feature not in this build -- pkg178 principled GPU furnace needs "
        "the RTX box (LEAD runs this).",
        allow_module_level=True,
    )


def _renderer():
    r = astroray.Renderer()
    r.setup_camera(
        look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0, width=32, height=32)
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_integrator("path_tracer")
    r.set_use_gpu(True)  # pkg178 Stage 2: GPU leg
    return r


def _mean(mat_type, color, params, samples=64):
    r = _renderer()
    mid = r.create_material(mat_type, color, params)
    r.add_sphere([0, 0, 0], 1.0, mid)
    px = np.array(r.render(samples, 8, None, False), dtype=np.float32)  # linear
    assert np.isfinite(px).all(), f"GPU {mat_type} {params} produced non-finite pixels"
    return float(np.mean(px))


def _ratio(color, params, samples=64):
    ref = _mean("lambertian", [1.0, 1.0, 1.0], {}, samples)
    mat = _mean("principled", color, params, samples)
    return mat, ref


def _assert_band(label, mat, ref, floor, ceil=1.05):
    assert mat <= ref * ceil, f"{label} GPU mean={mat:.3f} > {ceil:.2f}x white lambertian {ref:.3f} (energy GAIN)"
    assert mat >= ref * floor, f"{label} GPU mean={mat:.3f} < {floor:.2f}x white lambertian {ref:.3f} (energy LOSS)"


def test_gpu_principled_diffuse_lambert():
    mat, ref = _ratio([1.0, 1.0, 1.0], {"metallic": 0.0, "roughness": 0.5})
    print(f"\n[pkg178 GPU furnace] diffuse/Lambert mean={mat:.4f} ref={ref:.4f} ratio={mat/ref:.4f}")
    _assert_band("Principled diffuse/Lambert", mat, ref, floor=0.85)


def test_gpu_principled_diffuse_eon():
    mat, ref = _ratio([1.0, 1.0, 1.0], {"metallic": 0.0, "roughness": 0.5, "diffuse_roughness": 0.8})
    print(f"\n[pkg178 GPU furnace] EON diffuse mean={mat:.4f} ref={ref:.4f} ratio={mat/ref:.4f}")
    _assert_band("Principled EON diffuse", mat, ref, floor=0.80)


def test_gpu_principled_metallic_f82():
    for roughness in [0.3, 0.6]:
        mat, ref = _ratio([0.9, 0.9, 0.9], {"metallic": 1.0, "roughness": roughness})
        print(f"\n[pkg178 GPU furnace] metallic(r={roughness}) mean={mat:.4f} ref={ref:.4f} ratio={mat/ref:.4f}")
        _assert_band(f"Principled metallic(r={roughness})", mat, ref, floor=0.88)


def test_gpu_principled_transmission_glass():
    for roughness in [0.1, 0.4]:
        mat, ref = _ratio([1.0, 1.0, 1.0],
                          {"metallic": 0.0, "transmission_weight": 1.0, "ior": 1.5, "roughness": roughness})
        print(f"\n[pkg178 GPU furnace] glass(r={roughness}) mean={mat:.4f} ref={ref:.4f} ratio={mat/ref:.4f}")
        _assert_band(f"Principled glass(r={roughness})", mat, ref, floor=0.80)


# ===========================================================================
# LEAD RUN COMMANDS (after build_cuda_worktree.bat, on the RTX box):
#   pytest tests/test_pkg178_principled_gpu_furnace.py -v -s
# ===========================================================================
