#!/usr/bin/env python
"""GPU twins of the CPU Bump / Normal Map paths (#1220, #1156, #1214).

#1220: a bumped Principled with Bump Map Correction shaded every closure on one lifted normal on
       the GPU, and its diffuse closure skipped Cycles' terminator softening (bsdf.h:86-146 @
       v5.2.0); the CPU applies both per closure (principled.cpp). prod_car_paint read GPU/CPU
       +1.5-2 %.
#1156: an image Bump over a Normal Map took its surface frame from the mapped normal on the GPU
       (CPU: the pre-map normal, Cycles' dP); a zero-scale Mapping axis sent the CPU to a nearest
       texture-space step, the GPU to the Linear input-UV step.
#1214: the GPU applied image bumps to triangles only; the CPU bumps analytic spheres with the
       Sphere::hit UV and frame.

Render legs are CPU / GPU twins; the GPU legs skip without CUDA.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from base_helpers import create_renderer, render_image, setup_camera

astroray = pytest.importorskip("astroray")


def _renderer(use_gpu, seed=5):
    r = create_renderer()
    if use_gpu:
        if not (bool(astroray.__features__.get("cuda", False)) and bool(getattr(r, "gpu_available", False))):
            pytest.skip("No CUDA GPU")
        r.set_use_gpu(True)
    r.set_adaptive_sampling(False)
    r.set_seed(seed)
    r.set_background_color([0.0, 0.0, 0.0])
    return r


def _quad(r, mat):
    A, B, C, D, n = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0], [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)


def _sun(r, d, power=3.0):
    d = np.asarray(d, float)
    r.add_sun_light_dedicated((d / np.linalg.norm(d)).tolist(), 0.02, {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, power)


def _ramp(n_tex=64, along_v=False):
    ramp = (np.arange(n_tex, dtype=np.float32) + 0.5) / n_tex
    rows = np.repeat(ramp[:, None], n_tex, axis=1) if along_v else np.repeat(ramp[None, :], n_tex, axis=0)
    return np.repeat(rows[:, :, None], 3, axis=2).astype(np.float32)


# ---------------------------------------------------------------------------
# #1220 - per-closure bump correction on the GPU Principled
# ---------------------------------------------------------------------------

def _principled_quad(use_gpu, correction):
    """Principled (no coat) under a +u image ramp bump (normal tilted 27 deg toward -x), lit by
    a sun 15 deg above the horizon from -x: Ns.wi = 0.26, so Cycles' diffuse softening
    (alpha^2 = 0.125 tan^2 27 deg) takes ~9 % off the diffuse closure."""
    r = _renderer(use_gpu)
    r.load_texture("h1220", _ramp(), 64, 64, "UV")
    params = {"metallic": 0.0, "roughness": 0.5, "bump_map_texture": "h1220", "bump_distance": 1.0,
              "bump_strength": 1.0, "bump_map_correction": 1.0 if correction else 0.0}
    _quad(r, r.create_material("principled", [0.6, 0.6, 0.6], params))
    _sun(r, [0.97, 0.0, -0.26])
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=30, width=32, height=32)
    return np.asarray(render_image(r, samples=256, max_depth=1, apply_gamma=False), np.float32)


_C = (slice(8, 24), slice(8, 24))


@pytest.mark.parametrize("correction", [True, False], ids=["correction", "no_correction"])
def test_gpu_principled_bump_correction_per_closure_matches_cpu(correction):
    """Main (one lifted normal, glossy shadowing rule): GPU/CPU ~1.09 with the correction on;
    with it off both apply the hemisphere test only and agree."""
    g = float(_principled_quad(True, correction)[_C].mean())
    c = float(_principled_quad(False, correction)[_C].mean())
    assert c > 0.02, c
    assert abs(g / c - 1.0) < 0.02, (g, c)


# ---------------------------------------------------------------------------
# #1156 - image bump frame under a Normal Map; zero-scale Mapping axis
# ---------------------------------------------------------------------------

def _nm_bump_quad(use_gpu, bump=True):
    """A constant 40-degree v-tilted tangent-space Normal Map chained into an image Bump whose
    height ramps along v. The surface step dP.dy lies in the surface plane (pre-map normal x T);
    a frame built around the mapped normal steps out of it and weakens the relief by cos 40."""
    r = _renderer(use_gpu)
    a = np.radians(40.0)
    tilt = np.array([0.0, np.sin(a), np.cos(a)], np.float32) * 0.5 + 0.5
    r.load_texture("nm1156", np.tile(tilt, (2, 2, 1)).astype(np.float32), 2, 2, "UV")
    params = {"normal_map_texture": "nm1156", "normal_strength": 1.0}
    if bump:
        r.load_texture("h1156", _ramp(along_v=True), 64, 64, "UV")
        params.update({"bump_map_texture": "h1156", "bump_distance": 0.6, "bump_strength": 1.0})
    _quad(r, r.create_material("lambertian", [0.8, 0.8, 0.8], params))
    _sun(r, [0.3, -0.5, -1.0])
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=30, width=32, height=32)
    return np.asarray(render_image(r, samples=64, max_depth=1, apply_gamma=False), np.float32)


def test_gpu_image_bump_over_a_normal_map_matches_cpu():
    gpu, gpu_nm = _nm_bump_quad(True), _nm_bump_quad(True, bump=False)
    cpu, cpu_nm = _nm_bump_quad(False), _nm_bump_quad(False, bump=False)
    assert abs(gpu_nm[_C].mean() / cpu_nm[_C].mean() - 1.0) < 0.01
    relief_cpu, relief_gpu = float((cpu - cpu_nm)[_C].mean()), float((gpu - gpu_nm)[_C].mean())
    assert abs(relief_cpu) > 0.02, relief_cpu
    assert abs(relief_gpu / relief_cpu - 1.0) < 0.05, (relief_gpu, relief_cpu)


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
def test_image_bump_with_a_zero_scale_mapping_axis(use_gpu):
    """Mapping Scale (0, s): u is flattened, v scaled by s. The slope along v is s x the image
    slope (input-UV step before the Mapping), on both backends; main's CPU fell back to a
    texture-space step over 1.5 texels (slope not scaled by s, 2x too steep here)."""
    s, dist = 0.5, 0.5
    r = _renderer(use_gpu)
    r.load_texture("h0", _ramp(along_v=True), 64, 64, "UV")
    r.set_texture_mapping_matrix("h0", [0, 0, 0, 0.5, 0, s, 0, 0, 0, 0, 1, 0])
    _quad(r, r.create_material("lambertian", [0.8, 0.8, 0.8],
                               {"bump_map_texture": "h0", "bump_distance": dist, "bump_strength": 1.0}))
    sun = np.array([0.0, -1.0, -1.0]) / np.sqrt(2.0)
    _sun(r, sun)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=45, width=48, height=48)
    measured = float(np.asarray(render_image(r, samples=64, max_depth=1, apply_gamma=False))[16:32, 16:32].mean())
    g = s * 0.5  # dh/dy: v_tex per world y
    expect = []
    for sign in (1.0, -1.0):  # the image row order sets the slope's sign
        nb = np.array([0.0, sign * dist * g, 1.0])
        nb /= np.linalg.norm(nb)
        expect.append(0.8 / np.pi * 3.0 * max(0.0, float(-sun @ nb)))
    assert min(abs(measured / e - 1.0) for e in expect) < 0.02, (measured, expect)


def test_non_uv_normal_map_is_reported_on_gpu(capfd):
    r = _renderer(True)
    r.load_texture("nm_gen", np.full((2, 2, 3), 0.5, np.float32), 2, 2, "UV")
    r.set_texture_coord_mode("nm_gen", "GENERATED")
    _quad(r, r.create_material("lambertian", [0.8, 0.8, 0.8], {"normal_map_texture": "nm_gen"}))
    _sun(r, [0.0, 0.0, -1.0])
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=30, width=8, height=8)
    render_image(r, samples=1, max_depth=1, apply_gamma=False)
    assert "[#1156] DEGRADED: Normal Map" in capfd.readouterr().err


# ---------------------------------------------------------------------------
# #1214 - image bump on an analytic sphere
# ---------------------------------------------------------------------------

def _sphere(use_gpu, bump=True, res=64):
    """A Lambertian add_sphere with a 16x16 checker heightfield on its spherical UV."""
    r = _renderer(use_gpu, seed=7)
    params = {}
    if bump:
        ij = np.add.outer(np.arange(16), np.arange(16)) % 2
        r.load_texture("h1214", np.repeat(ij[:, :, None], 3, axis=2).astype(np.float32), 16, 16, "UV")
        params = {"bump_map_texture": "h1214", "bump_distance": 0.05, "bump_strength": 1.0}
    r.add_sphere([0.0, 0.0, 0.0], 1.0, r.create_material("lambertian", [0.8, 0.8, 0.8], params))
    _sun(r, [-0.5, -0.4, -1.0])
    setup_camera(r, look_from=[0, 0, 3.2], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=45, width=res, height=res)
    return np.asarray(render_image(r, samples=64, max_depth=1, apply_gamma=False), np.float32)


def _blocks(im, b=8):
    n = im.shape[0] // b
    return im.reshape(n, b, n, b, 3).mean(axis=(1, 3))


def test_gpu_sphere_image_bump_matches_cpu():
    """Main: the GPU sphere stayed flat (relief 0)."""
    gpu, gpu_flat = _sphere(True), _sphere(True, bump=False)
    cpu, cpu_flat = _sphere(False), _sphere(False, bump=False)
    relief_cpu, relief_gpu = np.abs(cpu - cpu_flat).mean(), np.abs(gpu - gpu_flat).mean()
    assert relief_cpu > 0.01, relief_cpu
    assert abs(relief_gpu / relief_cpu - 1.0) < 0.15, (relief_gpu, relief_cpu)
    block_relief = np.abs(_blocks(cpu) - _blocks(cpu_flat)).mean()
    block_diff = np.abs(_blocks(gpu) - _blocks(cpu)).mean()
    assert block_diff < max(0.3 * block_relief, 0.003), (block_diff, block_relief)
