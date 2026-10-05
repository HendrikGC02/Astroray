"""#1033 review follow-ups (Cycles path_state_next / shade_surface.h semantics, Apache-2.0).

A transparent pass-through is not a bounce, but several pieces of path state were still
keyed on it (CPU + GPU):
  1. GPU media RNG streams replayed the draws of the segment in front of a sheet.
  2. The photon-caustic split restarted behind a sheet that the gather never reaches.
  3. The MIS state (wasSpecular / bsdfPdfPrev / misNormalPrev) was overwritten by the pass.
  4. The camera far clip was dropped and Ray Length restarted at the sheet.
  5. The GPU denoise guides were taken from the last bounce-0 hit, not the first.
  6. Cryptomatte credited the sheet on its transparent-lobe sample.
  7. The CPU film alpha ignored alpha < 1 surfaces (GPU counts misses behind a sheet).
Every scene here is "an invisible (Alpha 0) sheet must not change the render".
"""
import math
import os
import sys

import numpy as np
import pytest
from test_issue991_light_path import (
    BACKENDS,
    C,
    _lp_value,
    _program,
    _render,
    _renderer,
    _roi,
)

sys.path.insert(0, os.path.dirname(__file__))


_UV = {"UVMap": [[0, 0], [1, 0], [1, 1]]}


def _quad(r, mat, c, u, v):
    """Quad centre c, half-edges u, v, normal u x v on every corner. (The shared
    test_issue991_light_path._quad passes the corner POSITIONS as normals: harmless for
    its ratio gates, but it tilts the shading normal and one-sided emitters never emit.)"""
    n = np.cross(u, v)
    n = (n / np.linalg.norm(n)).tolist()
    p = [[c[i] + su * u[i] + sv * v[i] for i in range(3)]
         for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    r.add_triangle_layers(p[0], p[1], p[2], mat, _UV, n, n, n)
    r.add_triangle_layers(p[0], p[2], p[3], mat, _UV, n, n, n)


_emitter = _quad


def _sheet(r, c, u, v):
    mat = r.create_material("principled", [1.0, 1.0, 1.0], {"alpha": 0.0})
    _quad(r, mat, c, u, v)


# ---- 1. GPU media RNG streams advance across a pass -----------------------------------
def _fog_value(use_gpu, sheets):
    r = _renderer(use_gpu)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_world_volume(0.25, [1.0, 1.0, 1.0], 0.0, 0.02)      # sigma_t 0.25, albedo 0.02
    emit = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 5.0})
    _emitter(r, emit, [0, 6.0, 0], [4.0, 0, 0], [0, 0, 4.0])
    for y in sheets:
        _sheet(r, [0, y, 0], [4.0, 0, 0], [0, 0, 4.0])
    return float(_roi(_render(r, [0, 0, 0], [0, 1, 0], spp=256, depth=6, size=24, vfov=10),
                      12, 12, 4).mean())


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_fog_survival_is_not_replayed_behind_alpha_sheets(use_gpu):
    """An emissive wall 6 units away in scattering fog (sigma_t 0.25, albedo 0.02): the
    radiance is 5 exp(-1.5) = 1.1 (+ a little in-scatter). Two invisible sheets must not
    change it. The GPU used to key the free-flight draws on `bounce`, which a pass no
    longer advances, so the three 2-unit segments shared one draw: survival
    exp(-sigma max(L)) = 0.61 instead of exp(-sigma sum(L)) = 0.22 (x2.7 bright)."""
    free = _fog_value(use_gpu, [])
    sheets = _fog_value(use_gpu, [2.0, 4.0])
    analytic = 5.0 * math.exp(-0.25 * 6.0)
    assert free == pytest.approx(analytic, rel=0.2), (free, analytic)
    assert sheets == pytest.approx(free, rel=0.08), (sheets, free)


# ---- 2. photon caustic split behind a sheet ------------------------------------------
@pytest.mark.slow   # ~40 s CPU
@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_photon_caustic_is_not_lost_behind_an_alpha_sheet(use_gpu):
    """Caustic photons ON vs brute-force path tracing (OFF) with an invisible sheet
    between the camera and the floor: the split chain used to restart at the floor behind
    the sheet (lamp hits dropped) while the gather only runs at the first hit (the sheet)."""
    import test_959_caustic_photon_split as T
    if use_gpu and not T._gpu_ok():
        pytest.skip("CUDA GPU not available")

    def lum(photons, spp, seed):
        r = T._scene(photons, use_gpu)
        mat = r.create_material("principled", [1.0, 1.0, 1.0], {"alpha": 0.0})
        e = 8.0
        r.add_triangle([-e, 5.0, -e], [e, 5.0, e], [e, 5.0, -e], mat)
        r.add_triangle([-e, 5.0, -e], [-e, 5.0, e], [e, 5.0, e], mat)
        r.set_seed(seed)
        img = np.asarray(r.render(spp, 16, None, False), dtype=np.float64).reshape(T.H, T.W, 3)
        return img @ T.LUM

    on = np.mean([lum(True, 64, s) for s in (1, 2)], axis=0)
    off = np.mean([lum(False, 1024 if not use_gpu else 4096, s) for s in (1, 2)], axis=0)
    a, b = T._regions(on), T._regions(off)
    ratios = {k: a[k] / b[k] for k in ("tir_beam", "whole")}
    print("\n[#1033] photons ON / path traced behind a sheet:", ratios)
    for k, v in ratios.items():
        assert abs(v - 1.0) <= 0.06, (k, v)


# ---- 3. MIS state survives a pass ------------------------------------------------------
def _lamp_floor(use_gpu, sheet, bsdf_only=False):
    """Diffuse floor, a 2x2 area lamp overhead, an invisible sheet BETWEEN them (outside
    the camera's view): floor -> sheet -> lamp must keep the BSDF-sampled MIS weight."""
    r = _renderer(use_gpu)
    r.set_background_color([0.0, 0.0, 0.0])
    floor = r.create_material("principled", [0.8, 0.8, 0.8],
                              {"roughness": 1.0, "specular_ior_level": 0.0})
    _quad(r, floor, [0, 0, 0], [6.0, 0, 0], [0, 6.0, 0])
    lamp = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 8.0})
    _emitter(r, lamp, [0, 0, 3.0], [1.0, 0, 0], [0, -1.0, 0])      # faces down
    if sheet:
        _sheet(r, [0, 0, 1.5], [1.6, 0, 0], [0, 1.6, 0])
    if bsdf_only:
        r.set_light_nee(False)
    return float(_roi(_render(r, [0, -6, 1.0], [0, 0, 0], spp=256, depth=4, size=24, vfov=8),
                      12, 12, 3).mean())


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_mis_state_survives_a_transparent_pass(use_gpu):
    """diffuse -> sheet -> emitter was double counted: the pass overwrote wasSpecular
    (delta) so the emitter hit took weight 1 instead of the power-heuristic w_B, on top of
    the NEE leg (Cycles keeps mis_ray_pdf / MIS_SKIP across LABEL_TRANSPARENT)."""
    free = _lamp_floor(use_gpu, False)
    mis = _lamp_floor(use_gpu, True)
    bsdf = _lamp_floor(use_gpu, True, bsdf_only=True)
    assert free > 0.3, free
    assert mis == pytest.approx(free, rel=0.05), (mis, free)
    assert bsdf == pytest.approx(free, rel=0.08), (bsdf, free)


# ---- 4. far clip and Ray Length across a pass -------------------------------------------
def _clip_scene(use_gpu, sheet, program=False, far=None):
    from base_helpers import setup_camera
    r = _renderer(use_gpu)
    r.set_background_color([1.0, 1.0, 1.0])
    kw = {"roughness": 1.0, "specular_ior_level": 0.0}
    if program:
        _program(r, "rl1033", C.compile_chain(_lp_value('Ray Length', 0.1)))
        kw["base_color_texture"] = "rl1033"
        wall = r.create_material("principled", [0.8, 0.8, 0.8], kw)
    else:
        wall = r.create_material("principled", [0.6, 0.6, 0.6], kw)
    _quad(r, wall, [0, 6.0, 0], [40.0, 0, 0], [0, 0, 40.0])
    if sheet:
        _sheet(r, [0, 2.0, 0], [4.0, 0, 0], [0, 0, 4.0])
    setup_camera(r, look_from=[0, 0, 0], look_at=[0, 1, 0], vup=[0, 0, 1], vfov=10,
                 width=24, height=24)
    if far is not None:
        r.setup_camera(look_from=[0, 0, 0], look_at=[0, 1, 0], vup=[0, 0, 1], vfov=10.0,
                       aspect_ratio=1.0, aperture=0.0, focus_dist=5.0, width=24, height=24,
                       clip_far=far)
    from base_helpers import render_image
    img = render_image(r, samples=48, max_depth=4, apply_gamma=False)
    return _roi(img, 12, 12, 3).mean()


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_far_clip_still_applies_behind_an_alpha_sheet(use_gpu):
    """Cycles keeps the camera ray's tmax across a pass: a wall at 6 stays clipped by
    clip_end 4 when an invisible sheet at 2 is in front of it (it used to reappear)."""
    plain = _clip_scene(use_gpu, False, far=4.0)
    through = _clip_scene(use_gpu, True, far=4.0)
    seen = _clip_scene(use_gpu, True, far=10.0)
    assert plain == pytest.approx(1.0, abs=0.02), plain   # clipped: the white world
    assert seen < 0.9, seen                               # un-clipped: the grey wall
    assert through == pytest.approx(plain, abs=0.02), (through, plain)


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_ray_length_is_cumulative_across_a_pass(use_gpu):
    """Light Path Ray Length at a wall 6 away behind a sheet at 2 is 6 (from the last
    real vertex = the camera), not 4 (from the sheet): colour = 0.1 * Ray Length."""
    ref = _clip_scene(use_gpu, False)                 # constant albedo 0.6
    prog = _clip_scene(use_gpu, False, program=True)
    through = _clip_scene(use_gpu, True, program=True)
    assert prog == pytest.approx(ref, rel=0.05), (prog, ref)
    assert through == pytest.approx(ref, rel=0.05), (through, ref)


# ---- 5. denoise guides record the first hit --------------------------------------------
@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_guide_depth_is_the_first_hit(use_gpu):
    from base_helpers import render_image, setup_camera
    r = _renderer(use_gpu)
    if use_gpu:
        r.set_gpu_guide_aovs(True)
    r.set_background_color([0.5, 0.5, 0.5])
    wall = r.create_material("principled", [0.2, 0.7, 0.2], {"roughness": 1.0})
    _quad(r, wall, [0, 6.0, 0], [40.0, 0, 0], [0, 0, 40.0])
    sheet = r.create_material("principled", [0.9, 0.1, 0.1], {"alpha": 0.0})
    _quad(r, sheet, [0, 2.0, 0], [4.0, 0, 0], [0, 0, 4.0])
    setup_camera(r, look_from=[0, 0, 0], look_at=[0, 1, 0], vup=[0, 0, 1], vfov=10,
                 width=24, height=24)
    render_image(r, samples=8, max_depth=3, apply_gamma=False)
    dep = np.asarray(r.get_depth_buffer(), dtype=np.float32).reshape(24, 24)
    assert dep[12, 12] == pytest.approx(2.0, abs=0.05), dep[12, 12]


# ---- 6. cryptomatte credits the surface, not the transparent lobe ---------------------------
@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_cryptomatte_does_not_credit_an_invisible_sheet(use_gpu):
    import astroray
    from base_helpers import render_image, setup_camera
    r = _renderer(use_gpu)
    r.set_background_color([0.5, 0.5, 0.5])
    wall = r.create_material("principled", [0.7, 0.7, 0.7], {"roughness": 1.0})
    n0 = r.scene_object_count()
    _quad(r, wall, [0, 6.0, 0], [40.0, 0, 0], [0, 0, 40.0])
    n1 = r.scene_object_count()
    sheet = r.create_material("principled", [1.0, 1.0, 1.0], {"alpha": 0.0})
    _quad(r, sheet, [0, 2.0, 0], [4.0, 0, 0], [0, 0, 4.0])
    n2 = r.scene_object_count()
    for i in range(n0, n1):
        r.set_object_name(i, "wall1033")
    for i in range(n1, n2):
        r.set_object_name(i, "sheet1033")
    r.set_cryptomatte_enabled(True)
    r.set_cryptomatte_depth(6)
    r.add_pass("cryptomatte")
    setup_camera(r, look_from=[0, 0, 0], look_at=[0, 1, 0], vup=[0, 0, 1], vfov=10,
                 width=24, height=24)
    render_image(r, samples=16, max_depth=3, apply_gamma=False)
    buf = np.asarray(r.get_cryptomatte_object_buffer()).reshape(24, 24, -1)
    ids = {float(buf[12, 12, k]): float(buf[12, 12, k + 1]) for k in range(0, buf.shape[2], 2)}
    w_wall = ids.get(float(astroray.crypto_hash_name("wall1033")), 0.0)
    w_sheet = ids.get(float(astroray.crypto_hash_name("sheet1033")), 0.0)
    assert w_wall > 0.5, ids
    assert w_sheet <= 0.02 * w_wall, (w_sheet, w_wall)


# ---- 7. CPU film alpha sees through an alpha sheet -------------------------------------
@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_film_alpha_sees_through_an_alpha_sheet(use_gpu):
    from base_helpers import render_image, setup_camera
    r = _renderer(use_gpu)
    r.set_use_transparent_film(True)
    r.set_background_color([0.2, 0.3, 0.8])
    sheet = r.create_material("principled", [1.0, 1.0, 1.0], {"alpha": 0.0})
    _quad(r, sheet, [0, 2.0, 0], [4.0, 0, 0], [0, 0, 4.0])
    setup_camera(r, look_from=[0, 0, 0], look_at=[0, 1, 0], vup=[0, 0, 1], vfov=10,
                 width=24, height=24)
    render_image(r, samples=16, max_depth=4, apply_gamma=False)
    a = np.asarray(r.get_alpha_buffer(), dtype=np.float32).reshape(24, 24)
    assert float(a[8:16, 8:16].mean()) < 0.05, float(a[8:16, 8:16].mean())
