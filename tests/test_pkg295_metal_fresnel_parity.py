"""pkg295 / #934 -- Disney metallic=1 under a sun vs Blender 5.2 Cycles.

Ladder (.astroray_plan/docs/pkg295-metal-ladder.md): the metal lobe's Fresnel
already matches Cycles (at metallic=1 the Schlick scale is 1 and Cycles' F82-tint
with a white tint is plain Schlick). The convicted term was the spectral upsample:
DisneyPlugin::evalSpectral (and the GPU twin gpu_material_eval_spectral) fed the
RGB eval to the Jakob-Hanika ALBEDO LUT, which clamps rgb to [0,1]. A GGX peak's
f*cos under a sun is far above 1 (r0.1: ~340), so sun NEE was capped at 1:
grey 0.8 r0.1 read 0.076x Cycles, copper r0.5 red 0.94x. Fix: magnitude-factor
the upsample (upsample(rgb/m)*m, m = max(rgb, 1)), as sampleSpectral already did.

References: Cycles 5.2 Principled (base colour, metallic 1, roughness r, specular
tint white), sun 1 W/m2 angle 0.526 deg, 256 spp, CPU, mean over [4:44, 4:44];
script astra_run/AK/ak-295/cycles_metal_ref.py.
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
SPP = 64
SEEDS = (11, 23, 37)
TOL = 0.05
GREY = (0.8, 0.8, 0.8)
COPPER = (0.955, 0.638, 0.538)
DOWN = (0.0, -1.0, 0.0)
OBLIQUE = (0.3, -1.0, 0.2)

# rung: (base colour, roughness, sun direction, Cycles 5.2 per-channel mean)
RUNGS = {
    "grey_r0.5_down": (GREY, 0.5, DOWN, (0.7853, 0.7853, 0.7853)),
    "grey_r0.5_oblique": (GREY, 0.5, OBLIQUE, (0.5054, 0.5054, 0.5054)),
    "grey_r0.1_down": (GREY, 0.1, DOWN, (2.1793, 2.1793, 2.1793)),
    "grey_r0.1_oblique": (GREY, 0.1, OBLIQUE, (1.4523, 1.4523, 1.4523)),
    "copper_r0.5_down": (COPPER, 0.5, DOWN, (0.9508, 0.6172, 0.5159)),
    "copper_r0.5_oblique": (COPPER, 0.5, OBLIQUE, (0.6120, 0.3973, 0.3321)),
    "copper_r0.1_down": (COPPER, 0.1, DOWN, (2.6016, 1.7380, 1.4655)),
    "copper_r0.1_oblique": (COPPER, 0.1, OBLIQUE, (1.7338, 1.1582, 0.9767)),
    # The pkg292 ladder's "metal" rung (base 0.5, r0.5): #934 quoted Cycles 0.563;
    # a fresh Cycles 5.2 render with the matched camera reads 0.4779.
    "grey0.5_r0.5_down": ((0.5, 0.5, 0.5), 0.5, DOWN, (0.4779, 0.4779, 0.4779)),
}


def _has_cuda() -> bool:
    return AVAILABLE and bool(astroray.__features__.get("cuda", False))


def _render(base, rough, sun, gpu, seed):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(seed)
    r.set_use_gpu(gpu)
    r.setup_camera(look_from=[0.0, 20.0, 0.01], look_at=[0.0, 0.0, 0.0],
                   vup=[0.0, 0.0, -1.0], vfov=40.0, aspect_ratio=1.0,
                   aperture=0.0, focus_dist=20.0, width=W, height=W)
    g = r.create_material("disney", list(base), {"metallic": 1.0, "roughness": rough})
    r.add_triangle([-40, 0, -40], [40, 0, -40], [40, 0, 40], g)
    r.add_triangle([-40, 0, -40], [40, 0, 40], [-40, 0, 40], g)
    r.add_sun_light_dedicated(list(sun), float(np.radians(0.526)),
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 1.0, 0, 0)
    r.set_integrator("path_tracer")
    img = np.asarray(r.render(SPP, 4, None, False), dtype=np.float64).reshape(W, W, -1)[..., :3]
    assert np.isfinite(img).all()
    return img[4:44, 4:44].mean(axis=(0, 1))


def _mean(rung, gpu):
    base, rough, sun, _ = RUNGS[rung]
    return np.mean([_render(base, rough, sun, gpu, s) for s in SEEDS], axis=0)


@pytest.mark.parametrize("rung", list(RUNGS))
def test_cpu_metal_matches_cycles(rung):
    cpu = _mean(rung, False)
    ref = np.asarray(RUNGS[rung][3])
    assert np.all(np.abs(cpu / ref - 1.0) < TOL), (rung, cpu, ref, cpu / ref)


@pytest.mark.skipif(not _has_cuda(), reason="needs CUDA build")
@pytest.mark.parametrize("rung", list(RUNGS))
def test_gpu_metal_matches_cycles_and_cpu(rung):
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")
    cpu = _mean(rung, False)
    gpu = _mean(rung, True)
    ref = np.asarray(RUNGS[rung][3])
    assert np.all(np.abs(gpu / cpu - 1.0) < TOL), (rung, cpu, gpu, gpu / cpu)
    assert np.all(np.abs(gpu / ref - 1.0) < TOL), (rung, gpu, ref, gpu / ref)


def _furnace(rough, gpu):
    r = astroray.Renderer()
    r.set_background_color([1.0, 1.0, 1.0])
    m = r.create_material("disney", [1.0, 1.0, 1.0], {"metallic": 1.0, "roughness": rough})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, m)
    r.set_integrator("path_tracer")
    r.set_use_gpu(gpu)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 80, 80)
    r.set_seed(7)
    # LINEAR: a gamma furnace clamps to [0,1] and cannot see energy gain.
    img = np.asarray(r.render(128, 32, None, False), dtype=np.float32).reshape(80, 80, 3)
    return float(img[28:52, 28:52].mean())


@pytest.mark.parametrize("gpu", [False, pytest.param(True, marks=pytest.mark.skipif(
    not _has_cuda(), reason="needs CUDA build"))])
@pytest.mark.parametrize("rough", [0.1, 0.5])
def test_metal_white_furnace_linear(rough, gpu):
    if gpu and not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")
    v = _furnace(rough, gpu)
    assert 0.98 <= v <= 1.005, (rough, gpu, v)
