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
# back to the power CDF, where the mesh emitter's mass leaves the sun a tiny
# selection probability: the sun-lit ground went dark on GPU while the CPU tree
# sampler (the addon default) was fine. The rig is the addon's own export of a
# Blender scene (Z-up 40 m plane, default UV sphere with smooth normals via
# add_triangles_bulk, default SUN, recorded camera, clamp_indirect 10).
# ---------------------------------------------------------------------------
SUN_RES = 256
SUN_SPP = 16
SUN_SEEDS = (11, 23, 37, 51, 73)
# 63x63 far sun-lit ground (engine rows; Blender's top-down [8:71, 8:71]).
SUN_ROI = (slice(185, 248), slice(8, 71))


def _uv_sphere_bulk(r, mat, center=(0.0, 0.0, 1.0), rad=1.0, seg=32, rings=16):
    """Blender default UV sphere (Z-up), smooth normals, bulk-ingested."""
    th = np.linspace(0.0, np.pi, rings + 1)
    ph = np.linspace(0.0, 2.0 * np.pi, seg + 1)

    def n(i, j):
        return [np.sin(th[i]) * np.cos(ph[j]), np.sin(th[i]) * np.sin(ph[j]), np.cos(th[i])]

    def p(i, j):
        v = n(i, j)
        return [center[k] + rad * v[k] for k in range(3)]

    pos, nrm = [], []
    for i in range(rings):
        for j in range(seg):
            a, b, c, d = (i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)
            if i > 0:
                pos.append([p(*a), p(*b), p(*d)])
                nrm.append([n(*a), n(*b), n(*d)])
            if i < rings - 1:
                pos.append([p(*b), p(*c), p(*d)])
                nrm.append([n(*b), n(*c), n(*d)])
    pos = np.asarray(pos, np.float32)
    k = len(pos)
    r.add_triangles_bulk(pos, np.full(k, mat, np.int32), np.zeros(k, np.int32), 0,
                         np.zeros((1, k, 3, 2), np.float32), ["UVMap"],
                         np.asarray(nrm, np.float32))


def _sun_scene(case, gpu, seed, integrator, sun=True):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(seed)
    r.set_use_gpu(gpu)
    r.set_light_sampler("tree")  # addon default (cycles.use_light_tree)
    # Cycles' default sample_clamp_indirect, sent by the addon. With the sun
    # starved in NEE, only clamped BSDF-hit lamp samples reached the ground.
    # Measured on main 0dd98e18: GPU/CPU 0.105 (principled/light), restir 0.0.
    r.set_clamp_indirect(10.0)
    r.setup_camera(
        look_from=[0.0, -12.0, 8.0], look_at=[0.0, -11.1808, 7.4264],
        vup=[0.0, 0.5736, 0.8192], vfov=39.598, aspect_ratio=1.0,
        aperture=0.0, focus_dist=10.0, width=SUN_RES, height=SUN_RES)
    # Same call order as the addon export: materials, plane, sphere, then sun.
    # Principled with Blender defaults (white Emission Color, strength 0).
    m = None
    if case == "principled":
        m = r.create_material("principled", [0.8, 0.8, 0.8],
                              {"emission_color": [1.0, 1.0, 1.0], "emission_strength": 5.0})
    elif case == "light":
        m = r.create_material("diffuse_light", [1.0, 1.0, 1.0], {"intensity": 5.0})
    g = r.create_material("principled", [0.8, 0.8, 0.8],
                          {"emission_color": [1.0, 1.0, 1.0], "emission_strength": 0.0})
    plane = np.asarray([[[-20, -20, 0], [20, -20, 0], [20, 20, 0]],
                        [[-20, -20, 0], [20, 20, 0], [-20, 20, 0]]], np.float32)
    r.add_triangles_bulk(plane, np.full(2, g, np.int32), np.zeros(2, np.int32), 0,
                         np.zeros((1, 2, 3, 2), np.float32), ["UVMap"],
                         np.tile(np.asarray([0, 0, 1], np.float32), (2, 3, 1)))
    if m is not None:
        _uv_sphere_bulk(r, m)
    if sun:
        r.add_sun_light_dedicated([-0.17435, 0.47943, -0.86009], 0.0091804,
                                  {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 1.0, 0, 0)
    r.set_integrator_param("use_temporal", 0)
    r.set_integrator_param("use_spatial", 0)
    r.set_integrator(integrator)
    return r


def _sun_roi_mean(case, gpu, integrator, sun=True):
    means = []
    for s in SUN_SEEDS:
        r = _sun_scene(case, gpu, s, integrator, sun)
        img = np.asarray(r.render(SUN_SPP, 12, None, False), dtype=np.float64)
        img = img.reshape(SUN_RES, SUN_RES, -1)[..., :3]
        means.append(img[SUN_ROI].mean(axis=(0, 1)))
    return np.mean(means, axis=0)


@pytest.mark.parametrize("integrator,case", [
    ("path_tracer", "none"),
    ("path_tracer", "principled"),
    ("path_tracer", "light"),
    ("restir-di", "none"),        # restir-di used to drop dedicated lights
    pytest.param("restir-di", "principled", marks=pytest.mark.xfail(
        strict=True,
        reason="#885: restir-di drops the mesh emitter when a sun is present "
               "(CPU+GPU; GPU sun+emitter 0.2097 vs sum-of-parts 0.2317)")),
])
def test_issue859_sun_survives_mesh_emitter(integrator, case):
    """GPU/CPU far-ground mean within MEAN_RATIO_TOL with a sun + mesh emitter.

    Oracle = CPU path_tracer, built by linearity: CPU(sun only) +
    CPU(emitter only). The CPU tree sampler drops the emitter when a sun is in
    the same tree (measured: sun+emitter 0.209 vs 0.2096 + 0.0246; identical
    at emission 5 and 50), so a direct CPU(sun+emitter) render is not a valid
    oracle. The ROI sees direct light only, so DI-only restir-di must match
    too (CPU restir-di has its own colour cast on a SUN).
    """
    # TODO(#859/u851): once fix/u-851-light-tree lands (TreeLightSampler
    # pdfValue proxy-normal MIS fix), switch back to a straight CPU(sun+emitter)
    # render as the oracle.
    _require_gpu()
    cpu = _sun_roi_mean("none", False, "path_tracer")
    if case != "none":
        cpu = cpu + _sun_roi_mean(case, False, "path_tracer", sun=False)
    gpu = _sun_roi_mean(case, True, integrator)
    assert np.all(cpu > 1e-3), f"CPU oracle dark on {integrator}/{case}: {cpu}"
    ratios = gpu / cpu
    print(f"\n[#859 {integrator}/{case}] CPU {cpu.round(4).tolist()} "
          f"GPU {gpu.round(4).tolist()} GPU/CPU {ratios.round(4).tolist()}")
    assert np.all(np.abs(ratios - 1.0) <= MEAN_RATIO_TOL), (
        f"#859: GPU/CPU far-ground ratio {ratios.round(4).tolist()} on "
        f"{integrator}/{case} (sun lost on GPU)")


def _order_scene(gpu, sun_first):
    """Sun + UV-sphere emitter, power sampler; only the add order differs."""
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(11)
    r.set_use_gpu(gpu)
    r.set_light_sampler("power")
    r.setup_camera(
        look_from=[0.0, -12.0, 8.0], look_at=[0.0, -11.1808, 7.4264],
        vup=[0.0, 0.5736, 0.8192], vfov=39.598, aspect_ratio=1.0,
        aperture=0.0, focus_dist=10.0, width=64, height=64)
    m = r.create_material("principled", [0.8, 0.8, 0.8],
                          {"emission_color": [1.0, 1.0, 1.0], "emission_strength": 5.0})
    g = r.create_material("principled", [0.8, 0.8, 0.8], {})
    r.add_triangle([-20, -20, 0], [20, -20, 0], [20, 20, 0], g)
    r.add_triangle([-20, -20, 0], [20, 20, 0], [-20, 20, 0], g)

    def sun():
        r.add_sun_light_dedicated([-0.17435, 0.47943, -0.86009], 0.0091804,
                                  {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 1.0, 0, 0)
    if sun_first:
        sun()
    _uv_sphere_bulk(r, m, seg=8, rings=4)
    if not sun_first:
        sun()
    r.set_integrator("path_tracer")
    return np.asarray(r.render(4, 4, None, False), dtype=np.float64)


@pytest.mark.parametrize("gpu", [False, True], ids=["cpu", "gpu"])
def test_issue859_light_add_order_invariant(gpu):
    """#859: LightList built powerDist in CALL order while every consumer
    (PowerLightSampler, scene_upload) indexes it hittables-first. A dedicated
    light added before a mesh emitter scrambled all selection probabilities.
    Same scene, sun-first vs emitter-first, must render identically."""
    if gpu:
        _require_gpu()
    a = _order_scene(gpu, sun_first=True)
    b = _order_scene(gpu, sun_first=False)
    diff = float(np.abs(a - b).max())
    assert diff <= 1e-6, f"#859: light add order changes the render (max |diff| {diff})"
