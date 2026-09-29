"""pkg292 / #876 -- Disney under a dedicated sun: GPU/CPU per-channel parity.

Root cause (ladder in .astroray_plan/docs/pkg292-gpu-cpu-ladders.md): the GPU
lowered opaque Disney to a closure graph diffuse(w=1) + GGX conductor(w=1)
tinted by baseColor, normalised by W=2. That swaps the F0=0.04 dielectric
specular for half a base-tinted metal; under a near-delta sun the metal peak
made the GPU 1.7-1.9x the CPU. Fix: opaque Disney is ONE closure that the GPU
evaluates with the monolithic gpu_disney_eval (twin of DisneyPlugin::eval).

Gates: GPU/CPU per channel within +-5 % (issue #876), 3 seeds pooled; the
default and diffuse-only rungs also within +-8 % of Blender 5.2 Cycles
(Principled, base 0.5, roughness 0.5, IOR 1.5, sun 1 W/m2, 256 spp; script
astra_run/batchU/ah1/cycles_ref.py). The 8 % band covers the documented model
difference (Burley diffuse + Disney compensation vs Cycles Lambert + GGX
multiscatter); the pre-fix GPU was +60-90 % off.
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

W = 48
SPP = 32
SEEDS = (11, 23, 37)
PARITY_TOL = 0.05
CYCLES_TOL = 0.08
# Cycles 5.2 means over the [4:44, 4:44] crop (sun straight down).
CYCLES_REF = {"default": 0.1965, "diffuse_only": 0.1592}

RUNGS = {
    "default": {},
    "diffuse_only": {"specular": 0.0},
    "metal": {"metallic": 1.0},
    "half_metal": {"metallic": 0.5},
    "sheen": {"sheen": 1.0},
    "clearcoat": {"clearcoat": 1.0},
    "rough_0.2": {"roughness": 0.2},
    # pkg295 / #934: a GGX peak far above 1 that the spectral upsample clamp
    # used to cap (both backends).
    "metal_r0.1": {"metallic": 1.0, "roughness": 0.1},
    # pkg295 / #933: partial transmission used the multi-lobe GPU lowering
    # (base-tinted metal + diffuse + glass); baseline GPU/CPU 0.67-4.2.
    "trans_0.3_r0.05": {"transmission": 0.3, "roughness": 0.05},
    "trans_0.3_r0.4": {"transmission": 0.3, "roughness": 0.4},
    "trans_0.7_r0.05": {"transmission": 0.7, "roughness": 0.05},
    "trans_0.7_r0.4": {"transmission": 0.7, "roughness": 0.4},
}
SUN_DIRS = {"down": [0.0, -1.0, 0.0], "oblique": [0.3, -1.0, 0.2]}


def _has_cuda() -> bool:
    return AVAILABLE and bool(astroray.__features__.get("cuda", False))


def _render(params, sun_dir, gpu, seed):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(seed)
    r.set_use_gpu(gpu)
    r.setup_camera(look_from=[0.0, 20.0, 0.01], look_at=[0.0, 0.0, 0.0],
                   vup=[0.0, 0.0, -1.0], vfov=40.0, aspect_ratio=1.0,
                   aperture=0.0, focus_dist=20.0, width=W, height=W)
    g = r.create_material("disney", [0.5, 0.5, 0.5], params)
    r.add_triangle([-40, 0, -40], [40, 0, -40], [40, 0, 40], g)
    r.add_triangle([-40, 0, -40], [40, 0, 40], [-40, 0, 40], g)
    r.add_sun_light_dedicated(sun_dir, float(np.radians(0.526)),
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 1.0, 0, 0)
    r.set_integrator("path_tracer")
    img = np.asarray(r.render(SPP, 4, None, False), dtype=np.float64).reshape(W, W, -1)[..., :3]
    assert np.isfinite(img).all()
    return img[4:44, 4:44].mean(axis=(0, 1))


def _mean(params, sun_dir, gpu):
    return np.mean([_render(params, sun_dir, gpu, s) for s in SEEDS], axis=0)


def test_opaque_disney_lowers_to_one_closure():
    r = astroray.Renderer()
    m = r.create_material("disney", [0.5, 0.5, 0.5], {"metallic": 0.3})
    graph = r.get_material_closure_graph(m)
    assert len(graph) == 1
    assert graph[0]["type"] == "ggx_conductor"
    assert graph[0]["metallic"] == pytest.approx(0.3)


def test_partial_transmission_disney_lowers_to_one_closure():
    # #933/pkg295: 0 < transmission < 0.999 rides the same single lobe.
    r = astroray.Renderer()
    m = r.create_material("disney", [0.5, 0.5, 0.5],
                          {"metallic": 0.2, "transmission": 0.6, "ior": 1.45})
    graph = r.get_material_closure_graph(m)
    assert len(graph) == 1
    assert graph[0]["type"] == "ggx_conductor"
    assert graph[0]["metallic"] == pytest.approx(0.2)
    assert graph[0]["transmission"] == pytest.approx(0.6)
    assert graph[0]["ior"] == pytest.approx(1.45)


@pytest.mark.parametrize("rung", ["default", "diffuse_only"])
def test_cpu_matches_cycles(rung):
    cpu = _mean(RUNGS[rung], SUN_DIRS["down"], False)
    ref = CYCLES_REF[rung]
    assert np.all(np.abs(cpu / ref - 1.0) < CYCLES_TOL), (rung, cpu, ref)


@pytest.mark.skipif(not _has_cuda(), reason="needs CUDA build")
@pytest.mark.parametrize("sun", list(SUN_DIRS))
@pytest.mark.parametrize("rung", list(RUNGS))
def test_gpu_cpu_parity(rung, sun):
    cpu = _mean(RUNGS[rung], SUN_DIRS[sun], False)
    gpu = _mean(RUNGS[rung], SUN_DIRS[sun], True)
    ratio = gpu / cpu
    assert np.all(np.abs(ratio - 1.0) < PARITY_TOL), (rung, sun, cpu, gpu, ratio)
    if sun == "down" and rung in CYCLES_REF:
        assert np.all(np.abs(gpu / CYCLES_REF[rung] - 1.0) < CYCLES_TOL), (rung, gpu)
