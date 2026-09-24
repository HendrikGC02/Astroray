"""pkg89-wavefront (pkg55-C7) — dedicated lights in wavefront NEE.

Before C7 the wavefront passed (nullptr, 0) for dedicated lights into
gpu_nee_sample: a dedicated-light-only scene rendered BLACK on the
wavefront route (the pkg55-C5 gate-scene finding), and mixed scenes
over-sampled the last hittable emitter with a wrong selection pdf
(totalLightPower spans both kinds, so the hittable CDF walk fell
through). C7 threads the SAME unified power-CDF + device sampleLi the
MW megakernel uses (gpu_nee.cuh::gpu_dedicated_sample, PR #489/#500;
Cycles kernel/light/{point,spot,distant,area}.h via the CPU mirrors —
no new algorithm).

Gates compare the wavefront against the CPU oracle
(reference_pt_wavefront_render — the production pathTraceSpectral with
pkg89/pkg122-calibrated dedicated lights), NOT the megakernel, so they
survive the C7 megakernel deletion.

Measured 2026-07-25 (RTX 5070 Ti, 48x48, 256spp, md=3, seed 424242,
worktree pkg55-c7 @ e0185c8 + port):
  A dedicated-only POINT (delta): WF/CPU [0.9965, 0.9970, 0.9967]
  B dedicated-only AREA (rect):   WF/CPU [0.9965, 0.9972, 0.9967]
  C mixed emissive+point:         WF/CPU [0.9973, 0.9972, 0.9971]
Tolerance 0.05: an order of magnitude above the measured residual,
far below the pre-port failure (A/B render 0.0 => ratio 0).
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from runtime_setup import configure_test_imports  # noqa: E402

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE and not hasattr(astroray, "cuda_wavefront_render"):
    pytest.skip("cuda_wavefront_render not in this build (needs CUDA RTX box)",
                allow_module_level=True)

WIDTH = HEIGHT = 48
SPP = 256
MAX_DEPTH = 3
SEED = 424242
MEAN_RATIO_TOL = 0.05


def _require_gpu():
    if not astroray.Renderer().gpu_available:
        pytest.skip("No CUDA GPU available")


def _floor_scene():
    """pkg122 floor rig: gray Lambertian floor, black bg, top-down camera."""
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(SEED)
    r.setup_camera(
        look_from=[0.0, 20.0, 0.01], look_at=[0.0, 0.0, 0.0],
        vup=[0.0, 0.0, -1.0], vfov=20.0, aspect_ratio=1.0,
        aperture=0.0, focus_dist=20.0, width=WIDTH, height=HEIGHT)
    mat = r.create_material('lambertian', [0.5, 0.5, 0.5], {})
    r.add_triangle([-20, 0, -20], [20, 0, -20], [20, 0, 20], mat)
    r.add_triangle([-20, 0, -20], [20, 0, 20], [-20, 0, 20], mat)
    return r


def _add_lights(r, scene):
    if scene in ("point_only", "mixed"):
        # radius 0 => delta light: unified-CDF dedicated branch + the
        # pkg140 wt=1 MIS path.
        r.add_point_light(position=[0, 10, 0],
                          emission={'mode': 'rgb', 'color': [1.0, 0.8, 0.5]},
                          intensity=200.0, radius=0.0)
    if scene == "area_only":
        r.add_area_light_dedicated(
            center=[0, 10, 0], axis_u=[1, 0, 0], axis_v=[0, 0, 1],
            size_x=2.0, size_y=2.0, shape='rect',
            emission={'mode': 'rgb', 'color': [1, 1, 1]},
            intensity=100.0)
    if scene == "mixed":
        em = r.create_material('diffuse_light', [1.0, 1.0, 1.0],
                               {'intensity': 4.0})
        r.add_sphere([4.0, 6.0, 0.0], 1.0, em)


def _build(scene):
    r = _floor_scene()
    _add_lights(r, scene)
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator("path_tracer")
    _ = r.render(1, 1, None, False)  # BVH build
    return r


def _wf_over_cpu(scene):
    r_cpu = _build(scene)
    cpu = np.asarray(
        astroray.reference_pt_wavefront_render(r_cpu, SPP, MAX_DEPTH, SEED, False),
        dtype=np.float64).reshape(-1, 3)
    r_wf = _build(scene)
    wf = np.asarray(
        astroray.cuda_wavefront_render(r_wf, SPP, MAX_DEPTH, SEED),
        dtype=np.float64).reshape(-1, 3)
    cpu_mean = cpu.mean(axis=0)
    wf_mean = wf.mean(axis=0)
    assert np.all(cpu_mean > 1e-6), f"CPU oracle black on {scene}: {cpu_mean}"
    return wf_mean / cpu_mean, wf_mean


@pytest.mark.parametrize("scene", ["point_only", "area_only", "mixed"])
def test_wavefront_dedicated_light_nee(scene):
    """Wavefront NEE with dedicated lights matches the CPU oracle.

    point_only/area_only rendered BLACK on the wavefront before C7
    (numLights==0 skipped NEE entirely); mixed had a biased CDF
    fallthrough. Mean-ratio (not SSIM): independent RNG streams.
    """
    _require_gpu()
    ratios, wf_mean = _wf_over_cpu(scene)
    deviation = np.abs(ratios - 1.0)
    assert np.all(wf_mean > 1e-6), (
        f"wavefront renders black on {scene} — dedicated lights not wired "
        f"into wavefront NEE (the pre-C7 pkg89 gap)")
    assert np.all(deviation <= MEAN_RATIO_TOL), (
        f"wavefront/CPU mean ratio {ratios.round(4).tolist()} deviates more "
        f"than {MEAN_RATIO_TOL} on {scene} (measured 2026-07-25: ~0.997)")
    print(f"\n[pkg89-wavefront {scene}] PASS: WF/CPU = {ratios.round(4).tolist()}")


# ---------------------------------------------------------------------------
# #859 — sun + mesh emitter through Renderer.render() (the addon route).
# The GPU refused to upload a light tree containing dedicated lights and fell
# back to the power CDF, where a tessellated emitter's per-triangle mass leaves
# the sun a tiny selection probability: at viewport spp the sun-lit ground went
# dark on GPU while the CPU tree sampler (the addon default) was fine.
# ---------------------------------------------------------------------------
SUN_RES = 128
SUN_SPP = 16
SUN_SEEDS = (11, 23, 37, 51, 73)
SUN_ROI = (slice(8, 71), slice(8, 71))  # 63x63 sun-lit ground far from the quad


def _sun_scene(case, gpu, seed, integrator):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(seed)
    r.set_use_gpu(gpu)
    r.set_light_sampler("tree")  # addon default (cycles.use_light_tree)
    r.setup_camera(
        look_from=[0.0, 20.0, 0.01], look_at=[0.0, 0.0, 0.0],
        vup=[0.0, 0.0, -1.0], vfov=40.0, aspect_ratio=1.0,
        aperture=0.0, focus_dist=20.0, width=SUN_RES, height=SUN_RES)
    g = r.create_material("principled", [0.5, 0.5, 0.5], {})
    r.add_triangle([-40, 0, -40], [40, 0, -40], [40, 0, 40], g)
    r.add_triangle([-40, 0, -40], [40, 0, 40], [-40, 0, 40], g)
    r.add_sun_light_dedicated([0.3, -1.0, 0.2], float(np.radians(0.526)),
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 1.0, 0, 0)
    if case != "none":
        if case == "principled":
            m = r.create_material("principled", [0.8, 0.8, 0.8],
                                  {"emission_color": [1.0, 1.0, 1.0],
                                   "emission_strength": 5.0})
        else:
            m = r.create_material("diffuse_light", [1.0, 1.0, 1.0], {"intensity": 5.0})
        # Tessellated 4x2 m panel (400 triangles, like a Blender UV sphere):
        # the per-triangle power-CDF mass is what starves the sun.
        for i in range(20):
            for j in range(10):
                x, z = 5.0 + 0.2 * i, 5.0 + 0.2 * j
                r.add_triangle([x, 1, z], [x + 0.2, 1, z], [x + 0.2, 1, z + 0.2], m)
                r.add_triangle([x, 1, z], [x + 0.2, 1, z + 0.2], [x, 1, z + 0.2], m)
    r.set_integrator_param("use_temporal", 0)
    r.set_integrator_param("use_spatial", 0)
    r.set_integrator(integrator)
    return r


def _sun_roi_mean(case, gpu, integrator):
    means = []
    for s in SUN_SEEDS:
        r = _sun_scene(case, gpu, s, integrator)
        img = np.asarray(r.render(SUN_SPP, 4, None, False), dtype=np.float64)
        img = img.reshape(SUN_RES, SUN_RES, -1)[..., :3]
        means.append(img[SUN_ROI].mean(axis=(0, 1)))
    return np.mean(means, axis=0)


@pytest.mark.parametrize("integrator,case", [
    ("path_tracer", "none"),
    ("path_tracer", "principled"),
    ("path_tracer", "light"),
    ("restir-di", "none"),        # restir-di used to drop dedicated lights
    ("restir-di", "principled"),
])
def test_issue859_sun_survives_mesh_emitter(integrator, case):
    """GPU/CPU far-ground mean within MEAN_RATIO_TOL with a sun + mesh emitter.

    The oracle is always CPU path_tracer: the ground receives direct light
    only (no occluders/bounce surfaces near the ROI), so DI-only restir-di must
    match it, and the CPU restir-di has its own colour cast on a SUN.
    """
    _require_gpu()
    cpu = _sun_roi_mean(case, False, "path_tracer")
    gpu = _sun_roi_mean(case, True, integrator)
    assert np.all(cpu > 1e-3), f"CPU oracle dark on {integrator}/{case}: {cpu}"
    ratios = gpu / cpu
    print(f"\n[#859 {integrator}/{case}] CPU {cpu.round(4).tolist()} "
          f"GPU {gpu.round(4).tolist()} GPU/CPU {ratios.round(4).tolist()}")
    assert np.all(np.abs(ratios - 1.0) <= MEAN_RATIO_TOL), (
        f"#859: GPU/CPU far-ground ratio {ratios.round(4).tolist()} on "
        f"{integrator}/{case} (sun lost on GPU)")
