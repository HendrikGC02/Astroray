#!/usr/bin/env python
"""#1154 - Cycles bump-map correction under a Normal Map / Bump.

Cycles (Blender v5.2.0, Apache-2.0) applies two terms to bumped closures:
* ensure_valid_specular_reflection (kernel/closure/bsdf_util.h:322-395), when the material's
  Bump Map Correction is on (default): a glossy closure's normal is lifted toward the surface
  normal until the mirror reflection of the view clears the surface;
* bump_shadowing_term (kernel/closure/bsdf.h:86-146): a light on the other side of sd->N than
  the bumped normal is rejected, and with the correction on a diffuse closure is softened by
  the GGX G1 of alpha^2 = 0.125 tan^2(N, sd->N) (Conty Estevez et al., Ray Tracing Gems 2019).

Expectations are analytic (Lambert + the G1 term, a delta mirror under a uniform sky) or from
Cycles 5.2.0 renders of the same scenes (CPU, 1024 spp, seed 3, Standard view transform; scene
description in .astroray_plan/docs/issue1154-bump-correction-research.md). GPU legs skip without
a CUDA device.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import test_blender_uv_plumbing as P  # stub loader + recording renderer

from base_helpers import create_renderer, render_image, setup_camera  # configures the import path
import astroray

BETA = 30.0     # normal-map tilt toward +x (tangent = +u = +x)
ALBEDO = 0.8
SUN_E = 3.0     # sun irradiance, W/m^2

# Cycles 5.2.0, same scenes (see module docstring): crop means.
CYCLES_GLOSSY_CORR = 0.3979     # Principled metallic white, roughness 0.2, grazing 10 deg, sky 0.5
CYCLES_GLOSSY_OFF = 0.0
CYCLES_DIFFUSE_SOFT = 0.54525   # Principled diffuse 0.8, sun 3 W/m^2 at 20 deg elevation from +x
CYCLES_DIFFUSE_OFF = 0.58521


def _renderer(use_gpu):
    r = create_renderer()
    if use_gpu:
        if not (bool(astroray.__features__.get("cuda", False)) and
                bool(getattr(r, "gpu_available", False))):
            pytest.skip("No CUDA GPU")
        r.set_use_gpu(True)
    r.set_seed(7)
    return r


def _tilted_normal_map(r):
    b = np.radians(BETA)
    n = np.array([np.sin(b), 0.0, np.cos(b)])
    r.load_texture("nm1154", np.tile((n * 0.5 + 0.5).astype(np.float32), (2, 2, 1)), 2, 2, "UV")


def _quad(r, mat, s, z=0.0, uv=True):
    A, B, C, D, n = [-s, -s, z], [s, -s, z], [s, s, z], [-s, s, z], [0, 0, 1]
    if uv:
        r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
        r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    else:
        r.add_triangle(A, B, C, mat)
        r.add_triangle(A, C, D, mat)


def _params(correction):
    p = {"normal_map_texture": "nm1154", "normal_strength": 1.0}
    if not correction:
        p["bump_map_correction"] = 0.0   # Material.cycles.use_bump_map_correction = False
    return p


# ---------------------------------------------------------------------------
# ensure_valid_specular_reflection: grazing view of a plane whose normal map tilts away
# ---------------------------------------------------------------------------

def _grazing_glossy(kind, correction, use_gpu, spp=256):
    """Camera 10 deg above a plane whose normal is tilted 30 deg away from it, so the mirror
    reflection about the bumped normal points 44 deg into the plane (onto a black floor just
    below). Corrected, it leaves 0.57 deg above the horizon and sees the 0.5 sky."""
    r = _renderer(use_gpu)
    r.set_background_color([0.5, 0.5, 0.5])
    _tilted_normal_map(r)
    p = _params(correction)
    if kind == "principled":
        p.update({"metallic": 1.0, "roughness": 0.2})
        mat = r.create_material("principled", [1.0, 1.0, 1.0], p)
    else:  # near-delta conductor, white: reflects the sky exactly (F = 1)
        p.update({"albedo": [1.0, 1.0, 1.0], "roughness": 0.001})
        mat = r.create_material("metal", [1.0, 1.0, 1.0], p)
    _quad(r, mat, 40.0)
    _quad(r, r.create_material("lambertian", [0.0, 0.0, 0.0], {}), 40.0, z=-0.01, uv=False)
    e = np.radians(10.0)
    setup_camera(r, look_from=[-6 * np.cos(e), 0, 6 * np.sin(e)], look_at=[0, 0, 0], vup=[0, 0, 1],
                 vfov=20, width=32, height=32)
    im = np.asarray(render_image(r, samples=spp, max_depth=4, apply_gamma=False), np.float32)
    return float(im[12:20, 8:24].mean())


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
def test_grazing_mirror_reflects_the_sky_when_corrected(use_gpu):
    """Delta mirror: corrected = sky radiance 0.5 exactly; without the correction the
    reflection about the bumped normal enters the plane and is black (old behaviour)."""
    assert abs(_grazing_glossy("metal", True, use_gpu, spp=64) / 0.5 - 1.0) < 0.02
    assert _grazing_glossy("metal", False, use_gpu, spp=64) < 0.01


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
def test_grazing_principled_metal_matches_cycles(use_gpu):
    corr = _grazing_glossy("principled", True, use_gpu)
    assert abs(corr / CYCLES_GLOSSY_CORR - 1.0) < 0.05, (corr, CYCLES_GLOSSY_CORR)
    assert _grazing_glossy("principled", False, use_gpu, spp=64) < 0.01 + CYCLES_GLOSSY_OFF


def test_grazing_principled_metal_cpu_gpu_twin():
    gpu = _grazing_glossy("principled", True, True)
    cpu = _grazing_glossy("principled", True, False)
    assert abs(gpu / cpu - 1.0) < 0.05, (gpu, cpu)


def test_ensure_valid_matches_the_closed_form():
    """The lifted normal reflects wo to exactly the Cycles threshold min(0.9 Iz, 0.01)."""
    e, b = np.radians(10.0), np.radians(BETA)
    wo = np.array([-np.cos(e), 0.0, np.sin(e)])
    n = np.array([np.sin(b), 0.0, np.cos(b)])
    # Cycles' quartic root (bsdf_util.h:371-392), Ng = +z, X = +x
    iz, ix, t = wo[2], wo[0], min(0.9 * wo[2], 0.01)
    a = ix * ix + iz * iz
    bb = 2.0 * (a + iz * t)
    c = (t + iz) ** 2
    nz2 = 0.25 * (bb + np.sqrt(bb * bb - 4 * a * c)) / a if ix < 0 else 0.25 * (bb - np.sqrt(bb * bb - 4 * a * c)) / a
    n2 = np.array([np.sqrt(1 - nz2), 0.0, np.sqrt(nz2)])
    r2 = 2 * (n2 @ wo) * n2 - wo
    assert abs(r2[2] - t) < 1e-6 and (2 * (n @ wo) * n - wo)[2] < 0


# ---------------------------------------------------------------------------
# bump_shadowing_term: diffuse terminator softening and the sd->N hemisphere test
# ---------------------------------------------------------------------------

def _expected_lambert(sun_elev, soft):
    b, e = np.radians(BETA), np.radians(sun_elev)
    n = np.array([np.sin(b), 0.0, np.cos(b)])
    i = np.array([np.cos(e), 0.0, np.sin(e)])          # toward the sun
    if i[2] * n[2] * (n @ i) < 0.0:                     # light behind sd->N: rejected
        return 0.0
    v = ALBEDO / np.pi * SUN_E * max(0.0, float(n @ i))
    if soft:                                            # GGX G1, alpha^2 = 0.125 tan^2(N, Ns)
        a2 = min(0.125 * (1.0 / n[2] ** 2 - 1.0), 1.0)
        lam = 0.5 * (np.sqrt(1.0 + a2 * (1.0 / i[2] ** 2 - 1.0)) - 1.0)
        v /= 1.0 + lam
    return v


def _sunlit_diffuse(kind, correction, sun_elev, use_gpu, spp=32):
    r = _renderer(use_gpu)
    r.set_background_color([0.0, 0.0, 0.0])
    _tilted_normal_map(r)
    p = _params(correction)
    if kind == "principled":
        p.update({"metallic": 0.0, "roughness": 0.5, "specular_ior_level": 0.0})
        mat = r.create_material("principled", [ALBEDO] * 3, p)
    else:
        mat = r.create_material("lambertian", [ALBEDO] * 3, p)
    _quad(r, mat, 1.0)
    e = np.radians(sun_elev)
    r.add_sun_light_dedicated([-np.cos(e), 0.0, -np.sin(e)], 0.02,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, SUN_E)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=30, width=32, height=32)
    im = np.asarray(render_image(r, samples=spp, max_depth=1, apply_gamma=False), np.float32)
    return float(im[10:22, 10:22].mean())


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
@pytest.mark.parametrize("correction", [True, False], ids=["corr", "off"])
def test_lambert_terminator_softening(correction, use_gpu):
    exp = _expected_lambert(20.0, correction)
    cyc = CYCLES_DIFFUSE_SOFT if correction else CYCLES_DIFFUSE_OFF
    assert abs(exp / cyc - 1.0) < 0.002, (exp, cyc)        # the closed form is Cycles' term
    got = _sunlit_diffuse("lambertian", correction, 20.0, use_gpu)
    assert abs(got / exp - 1.0) < 0.01, (got, exp)


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
def test_light_behind_the_smooth_normal_is_rejected(use_gpu):
    """Sun 10 deg below the plane, in front of the bumped normal: Cycles returns 0 for every
    closure (light leak through opaque geometry); Astroray used to light it with N.L = 0.34."""
    assert _sunlit_diffuse("lambertian", True, -10.0, use_gpu) < 1e-3
    assert _sunlit_diffuse("lambertian", False, -10.0, use_gpu) < 1e-3


@pytest.mark.parametrize("use_gpu", [False, pytest.param(True, marks=pytest.mark.xfail(
    strict=True, reason="#1153: the GPU closure graph has one normal, so a Principled under a "
                        "Bump takes the glossy rule (no diffuse-closure softening)"))],
    ids=["cpu", "gpu"])
def test_principled_diffuse_lobe_is_softened_like_cycles(use_gpu):
    got = _sunlit_diffuse("principled", True, 20.0, use_gpu)
    assert abs(got / CYCLES_DIFFUSE_SOFT - 1.0) < 0.01, (got, CYCLES_DIFFUSE_SOFT)


def test_principled_diffuse_lobe_unsoftened_when_correction_off():
    got = _sunlit_diffuse("principled", False, 20.0, False)
    assert abs(got / CYCLES_DIFFUSE_OFF - 1.0) < 0.01, (got, CYCLES_DIFFUSE_OFF)


# ---------------------------------------------------------------------------
# Addon: Material.cycles.use_bump_map_correction reaches the native material
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("flag", [True, False])
def test_addon_exports_bump_map_correction(monkeypatch, flag):
    addon = P._load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    engine._current_bump_map_correction = flag
    seen = {}
    engine._shader_spec_from_node = lambda node, renderer, tree: {'type': 'principled'}
    engine.load_bump_height_texture = lambda spec, renderer: "h1154"
    engine._create_material_from_shader_spec = lambda spec, renderer: seen.update(spec) or 7
    disp = {'bump_image': None, 'bump_node': object(), 'bump_strength': 1.0, 'bump_distance': 0.1}
    assert engine.convert_shader_node(P._Node("BSDF_PRINCIPLED"), P._RecordingRenderer(), None, disp) == 7
    # Only 'off' is written: the engine default is on (Blender's default).
    assert seen.get('bump_map_correction') == (None if flag else 0.0), seen


@pytest.mark.parametrize("flag", [True, False])
def test_addon_reads_the_flag_per_material(monkeypatch, flag):
    """#1154 review: the flag is read in convert_node_material, so the preview converter and the
    exporter (which call it directly) see it too."""
    import types
    addon = P._load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    mat = types.SimpleNamespace(name="m", node_tree=None,
                                cycles=types.SimpleNamespace(use_bump_map_correction=flag))
    engine.convert_node_material(mat, P._RecordingRenderer())
    assert engine._current_bump_map_correction is flag


def test_addon_output_displacement_bump_sets_sd_n(monkeypatch):
    addon = P._load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    seen = {}
    engine._shader_spec_from_node = lambda node, renderer, tree: {'type': 'principled'}
    engine.load_bump_height_texture = lambda spec, renderer: "h1154"
    engine._create_material_from_shader_spec = lambda spec, renderer: seen.update(spec) or 7
    disp = {'bump_image': None, 'bump_node': object(), 'bump_strength': 1.0, 'bump_distance': 0.1}
    engine.convert_shader_node(P._Node("BSDF_PRINCIPLED"), P._RecordingRenderer(), None, disp)
    assert seen.get('bump_sets_sd_n') == 1.0, seen


# ---------------------------------------------------------------------------
# #1154 review: an Output Displacement (Bump method) bump sets sd->N, so the term is 1
# ---------------------------------------------------------------------------

def _sunlit_displacement(sun_elev, use_gpu, spp=32):
    r = _renderer(use_gpu)
    r.set_background_color([0.0, 0.0, 0.0])
    _tilted_normal_map(r)
    p = _params(True)
    p["bump_sets_sd_n"] = 1.0
    mat = r.create_material("lambertian", [ALBEDO] * 3, p)
    _quad(r, mat, 1.0)
    e = np.radians(sun_elev)
    r.add_sun_light_dedicated([-np.cos(e), 0.0, -np.sin(e)], 0.02,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, SUN_E)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=30, width=32, height=32)
    im = np.asarray(render_image(r, samples=spp, max_depth=1, apply_gamma=False), np.float32)
    return float(im[10:22, 10:22].mean())


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
@pytest.mark.parametrize("sun_elev", [20.0, -10.0])
def test_displacement_bump_has_no_shadowing_term(sun_elev, use_gpu):
    """Cycles bump_from_displacement sets sd->N = the bumped normal (shader_graph.cpp:1092-1100),
    so bump_shadowing_term returns 1 (bsdf.h:91-93): plain Lambert on the bumped normal, no
    softening, and a sun below the original surface still lights it."""
    b, e = np.radians(BETA), np.radians(sun_elev)
    exp = ALBEDO / np.pi * SUN_E * float(np.array([np.sin(b), 0, np.cos(b)]) @
                                        np.array([np.cos(e), 0, np.sin(e)]))
    got = _sunlit_displacement(sun_elev, use_gpu)
    assert abs(got / exp - 1.0) < 0.01, (got, exp)


# ---------------------------------------------------------------------------
# #1154 review: delta samples are never zeroed (Cycles bsdf.h:297-315)
# ---------------------------------------------------------------------------

def _fresnel_dielectric(c, eta=1.5):
    s2 = (1.0 - c * c) / eta ** 2
    if s2 >= 1.0:
        return 1.0
    ct = np.sqrt(1.0 - s2)
    rs = (c - eta * ct) / (c + eta * ct)
    rp = (eta * c - ct) / (eta * c + ct)
    return 0.5 * (rs * rs + rp * rp)


def _lifted(e, b):
    """Cycles ensure_valid_specular_reflection for Ng = +z, wo in the x-z plane."""
    wo = np.array([-np.cos(e), 0.0, np.sin(e)])
    n = np.array([np.sin(b), 0.0, np.cos(b)])
    t = min(0.9 * wo[2], 0.01)
    if (2 * (n @ wo) * n - wo)[2] >= t:
        return n
    iz, ix = wo[2], wo[0]
    a = ix * ix + iz * iz
    bb = 2.0 * (a + iz * t)
    c = (t + iz) ** 2
    nz2 = 0.25 * (bb + np.sqrt(bb * bb - 4 * a * c)) / a if ix < 0 else 0.25 * (bb - np.sqrt(bb * bb - 4 * a * c)) / a
    return np.array([np.sqrt(1.0 - nz2), 0.0, np.sqrt(nz2)])


def _grazing_glass(kind, beta, correction, use_gpu, spp=128):
    """Smooth glass plane (one interface) under a uniform 0.5 sky, viewed 10 deg above the
    horizon through a 3 deg field, normal map tilted `beta` away from the camera. Every path
    ends on the sky, so the pixel is 0.5 (F + (1 - F) / eta^2) with F at the shading normal."""
    r = _renderer(use_gpu)
    r.set_background_color([0.5, 0.5, 0.5])
    b = np.radians(beta)
    n = np.array([np.sin(b), 0.0, np.cos(b)])
    r.load_texture("nm1154", np.tile((n * 0.5 + 0.5).astype(np.float32), (2, 2, 1)), 2, 2, "UV")
    p = _params(correction)
    if kind == "principled":
        p.update({"transmission": 1.0, "roughness": 0.0, "ior": 1.5})
        mat = r.create_material("principled", [1.0, 1.0, 1.0], p)
    elif kind == "thin":
        p.update({"ior": 1.5})
        mat = r.create_material("thin_glass", [1.0, 1.0, 1.0], p)
    else:
        p.update({"ior": 1.5})
        mat = r.create_material("glass", [1.0, 1.0, 1.0], p)
    _quad(r, mat, 40.0)
    e = np.radians(10.0)
    setup_camera(r, look_from=[-6 * np.cos(e), 0, 6 * np.sin(e)], look_at=[0, 0, 0], vup=[0, 0, 1],
                 vfov=3, width=32, height=32)
    im = np.asarray(render_image(r, samples=spp, max_depth=8, apply_gamma=False), np.float32)
    return float(im[12:20, 8:24].mean())


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
@pytest.mark.parametrize("kind", ["glass", "principled"])
@pytest.mark.parametrize("beta,correction", [(8.0, False), (30.0, True)], ids=["b8_off", "b30_on"])
def test_grazing_smooth_glass_matches_fresnel(kind, beta, correction, use_gpu):
    """b8_off: the delta reflection about the bumped normal points 6 deg below the surface; it
    must not be zeroed (the round-1 eval rule removed it: 0.04 instead of 0.45)."""
    e, b = np.radians(10.0), np.radians(beta)
    n = _lifted(e, b) if correction else np.array([np.sin(b), 0.0, np.cos(b)])
    F = _fresnel_dielectric(float(n @ np.array([-np.cos(e), 0.0, np.sin(e)])))
    exp = 0.5 * (F + (1.0 - F) / 1.5 ** 2)
    got = _grazing_glass(kind, beta, correction, use_gpu)
    assert abs(got / exp - 1.0) < 0.01, (got, exp)


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
@pytest.mark.parametrize("beta,correction", [(8.0, False), (30.0, True)], ids=["b8_off", "b30_on"])
def test_grazing_thin_glass_furnace(beta, correction, use_gpu):
    """Thin glass (R' + T' = 1, straight-through transmission) under a uniform sky = the sky."""
    assert abs(_grazing_glass("thin", beta, correction, use_gpu) / 0.5 - 1.0) < 0.005
