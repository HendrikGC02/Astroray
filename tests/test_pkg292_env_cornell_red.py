"""pkg292 / #862 — session_n1_envmap_cornell GPU-vs-CPU red divergence ladder.

Each rung keeps a subset of the scene's materials (the rest become the floor
lambertian) so the diverging term is named by the failing rung. Ladder result
(2026-09-27, .astroray_plan/docs/pkg292-gpu-cpu-ladders.md):

- all-lambertian: GPU == CPU (<0.1 %). Env miss, lamp NEE, emissive hits agree.
- keep dielectric: GPU/CPU 1.092 (no bg, no lamp) -> the CPU wavefront ORACLE
  was wrong: advance_one_bounce carried rec.isDelta from a glass bounce into
  every later vertex and skipped lamp NEE there. Production pathTraceSpectral
  (independent integrator, fresh HitRecord per bounce) agrees with the GPU.
- keep disney: GPU red +3.6 % (env-only back wall +8 %) was the GPU Disney
  lowering (#876, 0.5 Lambert + 0.5 metal); with that fix the full scene passes.

64x64, 64 spp, seed 424242 (deterministic per build).
"""
import os
import sys

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scenes"))
import session_n1_envmap_cornell as scene  # noqa: E402

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

N, SPP, MAX_DEPTH, SEED = 64, 64, 8, 424242


def _renderer(keep):
    r = astroray.Renderer()
    scene.build_scene(r, keep=keep)
    scene.setup_camera(r, width=N, height=N)
    r.set_seed(SEED)
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator("path_tracer")
    r.render(1, 1, None, False)
    return r


def _oracle(keep):
    img = astroray.reference_pt_wavefront_render(_renderer(keep), SPP, MAX_DEPTH, SEED, False)
    return np.asarray(img, dtype=np.float64).reshape(-1, 3).mean(0)


def test_cpu_oracle_matches_production_after_glass_bounce():
    """CPU-only: the wavefront oracle vs production pathTraceSpectral on the
    glass-wall rung. Pre-fix the oracle dropped lamp NEE after every delta
    bounce: ratio [0.939, 0.955, 0.966]; fixed [0.994, 0.997, 0.997]."""
    keep = {"dielectric"}
    oracle = _oracle(keep)
    r = _renderer(keep)
    if hasattr(r, "set_use_gpu"):
        r.set_use_gpu(False)
    prod = np.asarray(r.render(SPP, MAX_DEPTH, None, False), dtype=np.float64).reshape(-1, 3).mean(0)
    ratio = oracle / prod
    print(f"[pkg292 #862] oracle/production {ratio.round(4)}")
    assert np.all(np.abs(ratio - 1.0) <= 0.02), (oracle, prod, ratio)


def _gpu_ratio(keep):
    if not hasattr(astroray, "cuda_wavefront_render") or not astroray.Renderer().gpu_available:
        pytest.skip("needs the CUDA wavefront build + GPU")
    cpu = _oracle(keep)
    gpu = np.asarray(astroray.cuda_wavefront_render(_renderer(keep), SPP, MAX_DEPTH, SEED),
                     dtype=np.float64).reshape(-1, 3).mean(0)
    ratio = gpu / cpu
    print(f"[pkg292 #862] keep={sorted(keep) if keep is not None else 'all'} "
          f"CPU {cpu.round(5)} GPU {gpu.round(5)} ratio {ratio.round(4)}")
    return ratio


@pytest.mark.parametrize("keep,tol", [
    (set(), 0.02),             # all lambertian: control
    ({"dielectric"}, 0.05),    # the #862 term (was 1.066/1.047/1.034)
    ({"disney"}, 0.05),        # measured red 1.036 (pkg293 residual)
])
def test_gpu_cpu_rung(keep, tol):
    ratio = _gpu_ratio(keep)
    assert np.all(np.abs(ratio - 1.0) <= tol), ratio


def test_gpu_cpu_full_scene_red():
    ratio = _gpu_ratio(None)
    assert abs(ratio[0] - 1.0) <= 0.05, ratio
