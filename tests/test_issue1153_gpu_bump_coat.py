#!/usr/bin/env python
"""#1153 - GPU parity for a procedural / op-VM Bump Height and the Principled coat / sheen
normals under a Bump / Normal Map (CPU landed in #1157, issues #1004 / #1005).

1. scene_upload.cu uploaded ImageTexture bumps only: a Noise / Wave / Voronoi Height (Object
   / Generated coordinates, directly or as op-VM inputs) rendered unbumped on the GPU. It is
   now differenced per hit (gpu_bumpProceduralNormal), the CPU NormalMappedPlugin world-step
   branch's twin.
2. The GPU closure-graph Principled shaded the coat on the bumped normal. Cycles' unlinked Coat
   Normal is sd->N (svm/closure.h:152-161 @ v5.2.0) and the sheen sits on
   normalize(mix(N, sd->N, coat_weight)); the GPU now does both (gpu_coatN_*).

Render legs are CPU / GPU twins; the GPU legs skip without CUDA.
"""

import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import test_blender_uv_plumbing as P  # addon stub loader + recording renderer

astroray = pytest.importorskip("astroray")
import test_issue1007_perhit_procedural_gpu as T1007  # Noise / Wave / Voronoi / program textures
from base_helpers import create_renderer, render_image, setup_camera

_SUN = np.array([-1.0, 0.0, -0.6]) / np.linalg.norm([-1.0, 0.0, -0.6])


def _gpu_or_skip(r):
    if not (bool(astroray.__features__.get("cuda", False)) and bool(getattr(r, "gpu_available", False))):
        pytest.skip("No CUDA GPU")
    r.set_use_gpu(True)


def _save(img, name):
    out = os.environ.get("ISSUE1153_EVIDENCE_DIR")
    if out:
        from base_helpers import save_image
        save_image(np.clip(img, 0, 1) ** (1 / 2.2), os.path.join(out, name))


def _quad(r, mat):
    A, B, C, D, n = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0], [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)


# ---------------------------------------------------------------------------
# 1. Procedural / op-VM Bump Height
# ---------------------------------------------------------------------------

RES = 96


def _tex_voronoi_distance_object(r):
    # prod_car_paint's flake Height: Voronoi F1 Distance in Object coordinates (the #1007
    # case reads the Color output, piecewise constant: no slope inside a cell).
    r.create_procedural_texture("vd1153", "voronoi", T1007.VORONOI[:16] + [0.0], "OBJECT")
    return "vd1153"


TEX = dict(T1007.CASES, voronoi_distance_object=_tex_voronoi_distance_object)
# case -> Bump Distance giving a per-pixel relief of 0.025 - 0.05 (CPU build):
PROC_CASES = {"wave_object": 0.004, "noise_generated": 0.02, "voronoi_distance_object": 0.01,
              "program_object": 0.006, "coordprog_object": 0.004}


def _proc_bump_render(case, use_gpu, bump=True, seed=7):
    """Sun-lit Lambertian quad, Height = a #1007 test texture (period a few pixels)."""
    r = create_renderer()
    if use_gpu:
        _gpu_or_skip(r)
    r.set_adaptive_sampling(False)
    r.set_seed(seed)
    r.set_background_color([0.0, 0.0, 0.0])
    params = {}
    if bump:
        params = {"bump_map_texture": TEX[case](r), "bump_distance": PROC_CASES[case], "bump_strength": 1.0}
    _quad(r, r.create_material("lambertian", [0.8, 0.8, 0.8], params))
    r.add_sun_light_dedicated(_SUN.tolist(), 0.02, {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 3.0)
    setup_camera(r, look_from=[0, 0, 3.0], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=30.0, width=RES, height=RES)
    return np.asarray(render_image(r, samples=32, max_depth=1, apply_gamma=False), np.float32)


def _blocks(im, b=8):
    return im.reshape(RES // b, b, RES // b, b, 3).mean(axis=(1, 3))


@pytest.mark.parametrize("case", sorted(PROC_CASES))
def test_gpu_procedural_bump_matches_cpu(case, capfd):
    """The GPU applies the procedural Height (main: unbumped, relief 0) with the CPU's
    relief: per pixel the same amount, per 8x8 block the same pattern. CPU seed-to-seed
    noise (CPU build, 32 spp): pixel 0.005-0.011, block 0.0006-0.0014; relief per pixel
    0.025-0.049, per block 0.003-0.02."""
    flat = _proc_bump_render(case, True, bump=False)
    gpu = _proc_bump_render(case, True)
    err = capfd.readouterr().err
    cpu = _proc_bump_render(case, False)
    cpu_flat = _proc_bump_render(case, False, bump=False)
    _save(gpu, f"proc_{case}_gpu.png")
    _save(cpu, f"proc_{case}_cpu.png")
    assert "[#1153] DEGRADED" not in err, err[-800:]
    relief_cpu, relief_gpu = np.abs(cpu - cpu_flat).mean(), np.abs(gpu - flat).mean()
    assert relief_cpu > 0.02, relief_cpu
    assert abs(relief_gpu / relief_cpu - 1.0) < 0.2, (relief_gpu, relief_cpu)
    block_relief = np.abs(_blocks(cpu) - _blocks(cpu_flat)).mean()
    block_diff = np.abs(_blocks(gpu) - _blocks(cpu)).mean()
    assert block_diff < max(0.35 * block_relief, 0.003), (block_diff, block_relief)
    assert abs(gpu.mean() / cpu.mean() - 1.0) < 0.02, (gpu.mean(), cpu.mean())


def test_gpu_bump_height_supported_binding():
    """The engine's own answer the addon uses to decide the GPU report (#1153)."""
    r = create_renderer()
    if not hasattr(r, "gpu_bump_height_supported"):
        pytest.skip("native module predates #1153")
    for case in PROC_CASES:
        assert r.gpu_bump_height_supported(TEX[case](r)), case
    assert not r.gpu_bump_height_supported(T1007._tex_checker_object(r))   # bake only
    r.create_procedural_texture("uv_noise", "noise_perlin", T1007.NOISE)  # UV coordinates
    assert not r.gpu_bump_height_supported("uv_noise")
    r.load_texture("img_h", np.zeros((4, 4, 3), np.float32), 4, 4, "UV")  # image: the UV path
    assert not r.gpu_bump_height_supported("img_h")
    assert not r.gpu_bump_height_supported("no_such_texture")


def test_gpu_unsupported_procedural_bump_is_reported(capfd):
    r = create_renderer()
    _gpu_or_skip(r)
    r.set_background_color([0.0, 0.0, 0.0])
    tex = T1007._tex_checker_object(r)
    _quad(r, r.create_material("lambertian", [0.8, 0.8, 0.8],
                               {"bump_map_texture": tex, "bump_distance": 0.01}))
    r.add_sun_light_dedicated(_SUN.tolist(), 0.02, {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 3.0)
    setup_camera(r, look_from=[0, 0, 3.0], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=30.0, width=16, height=16)
    render_image(r, samples=1, max_depth=1, apply_gamma=False)
    assert "[#1153] DEGRADED" in capfd.readouterr().err


@pytest.mark.parametrize("supported", [True, False], ids=["supported", "unsupported"])
def test_addon_reports_gpu_bump_only_when_the_engine_cannot_difference_it(monkeypatch, supported):
    addon = P._load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    vnode = P._Node("TEX_VORONOI", inputs={"Vector": P._Socket()})
    bump = P._Node("BUMP", inputs={"Strength": P._Socket(0.35), "Distance": P._Socket(0.02),
                                   "Height": P._Socket(linked_to=vnode, output_name="Distance"),
                                   "Normal": P._Socket()})
    shader = P._Node("BSDF_PRINCIPLED", inputs={"Normal": P._Socket(linked_to=bump, output_name="Normal")})
    res = engine.get_normal_inputs(shader)
    seen = []
    engine._warn_shader_fallback = lambda *a, **k: seen.append(a)
    engine._bump_render_on_gpu = lambda renderer: True

    class _R(P._RecordingRenderer):
        def gpu_bump_height_supported(self, name):
            return supported

    tex = engine.load_bump_height_texture(res, _R())
    assert tex is not None
    bump_msgs = [a[1] for a in seen if a[0] == "BUMP"]
    assert bool(bump_msgs) is (not supported), seen


# ---------------------------------------------------------------------------
# 2. Coat and sheen normals under a Bump
# ---------------------------------------------------------------------------

def _ramp_tex(r, name="h_ramp1153", n_tex=64):
    ramp = (np.arange(n_tex, dtype=np.float32) + 0.5) / n_tex
    r.load_texture(name, np.repeat(np.repeat(ramp[None, :, None], n_tex, axis=0), 3, axis=2), n_tex, n_tex, "UV")
    return name


def _layered_render(use_gpu, bump, sun, sheen=0.0, coat_follows=False, proc=None):
    """Principled base 0.4 with a clear coat (and optionally sheen); steep image-ramp or
    procedural bump; a sun from `sun`."""
    r = create_renderer()
    if use_gpu:
        _gpu_or_skip(r)
    r.set_adaptive_sampling(False)
    r.set_seed(5)
    r.set_background_color([0.0, 0.0, 0.0])
    params = {"metallic": 0.0, "roughness": 0.5, "coat_weight": 1.0, "coat_roughness": 0.2,
              "coat_ior": 1.5, "sheen_weight": sheen, "sheen_roughness": 0.4}
    if bump:
        tex = TEX[proc](r) if proc else _ramp_tex(r)
        params.update({"bump_map_texture": tex, "bump_distance": PROC_CASES[proc] if proc else 1.0,
                       "bump_strength": 1.0})
        if coat_follows:
            params["coat_follows_bump"] = 1.0
    _quad(r, r.create_material("principled", [0.4, 0.4, 0.4], params))
    d = np.asarray(sun, float)
    r.add_sun_light_dedicated((d / np.linalg.norm(d)).tolist(), 0.05,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 3.0)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=30, width=32, height=32)
    return np.asarray(render_image(r, samples=256, max_depth=1, apply_gamma=False), np.float32)


_C = (slice(8, 24), slice(8, 24))
LAYERED = {
    # name: (sun direction, sheen, coat_follows, procedural height)
    "coat_mirror_sun": ([0.0, 0.0, -1.0], 0.0, False, None),
    "coat_oblique_sun": ([-0.5, 0.2, -1.0], 0.0, False, None),
    "sheen_coat": ([-0.6, 0.0, -1.0], 0.8, False, None),
    "coat_follows": ([0.0, 0.0, -1.0], 0.0, True, None),
    "coat_voronoi": ([0.0, 0.0, -1.0], 0.0, False, "voronoi_distance_object"),
}


@pytest.mark.parametrize("case", sorted(LAYERED))
def test_gpu_layered_principled_under_bump_matches_cpu(case):
    """A coated (and sheened) Principled under a Bump: the GPU coat stays on sd->N and the
    sheen on normalize(mix(N, sd->N, coat_weight)), as the CPU (#1005); with
    coat_follows_bump both follow the bump on both backends. Main's GPU coat followed every
    bump; the CPU with coat_follows_bump stands in for it: coat_mirror_sun 0.20x,
    coat_voronoi 0.56x, coat_oblique_sun 0.98x, sheen_coat 0.99x (the last two are parity
    checks of the layering). CPU seed-to-seed spread <= 0.1 %."""
    sun, sheen, follows, proc = LAYERED[case]
    gpu = _layered_render(True, True, sun, sheen, follows, proc)
    cpu = _layered_render(False, True, sun, sheen, follows, proc)
    _save(gpu, f"layered_{case}_gpu.png")
    _save(cpu, f"layered_{case}_cpu.png")
    g, c = float(gpu[_C].mean()), float(cpu[_C].mean())
    assert c > 0.01, c
    assert abs(g / c - 1.0) < 0.04, (g, c)
