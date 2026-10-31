"""#1178 / #1198: a bounce is classified by the SAMPLED closure's label, not the material.

Cycles v5.2.0 (Apache-2.0) ``kernel/integrator/path_state.h:174-217`` (path_state_next) counts a
reflection as diffuse or glossy from the sampled closure's label (``LABEL_DIFFUSE`` /
``LABEL_GLOSSY`` / ``LABEL_SINGULAR``, ``kernel/types.h:329-342``) and sets
``PATH_RAY_DIFFUSE_ANCESTOR`` on a diffuse one. Astroray used ``Material::isGlossy()``, which is
true for every Principled and for any Add/Mix with a glossy child, so a Principled diffuse
reflection counted as glossy: the diffuse cap never fired on it (#1178), a Principled floor never
became a diffuse ancestor so the refractive-caustics toggle was inert on it (#1198), and Light
Path "Is Diffuse Ray" read 0 after it. Research note:
.astroray_plan/docs/issue1178-sampled-lobe-label-research.md.
"""
import math
import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "blender_addon"))

BACKENDS = ["cpu", pytest.param("gpu", marks=pytest.mark.gpu)]


def _renderer(backend):
    import runtime_setup
    runtime_setup.configure_test_imports()
    import astroray
    r = astroray.Renderer()
    if backend == "gpu":
        if not (astroray.__features__.get("cuda", False) and getattr(r, "gpu_available", False)):
            pytest.skip("No CUDA GPU")
    return r


# --------------------------------------------------------------------------- #
# #1178: closed emitting box, bounce counts (the #1165 analytic box)
# --------------------------------------------------------------------------- #

def _cycles_box(n_cap, rho=0.5, le=1.0):
    """L = Le * sum_{j=0}^{N+1} rho^j for a cap of N (Cycles max_<type>_bounce = N + 1)."""
    return le * sum(rho ** j for j in range(n_cap + 2))


def _box_mean(backend, walls, diffuse=-1, glossy=-1, spp=64):
    r = _renderer(backend)
    if walls == "principled":   # diffuse-only Principled (no specular lobe), emission 1
        mat = r.create_material("principled", [0.5, 0.5, 0.5], {
            "roughness": 1.0, "metallic": 0.0, "specular_ior_level": 0.0,
            "coat_weight": 0.0, "sheen_weight": 0.0,
            "emission_color": [1.0, 1.0, 1.0], "emission_strength": 1.0})
    elif walls == "mix_lambert_metal":   # Add(Mix(Lambertian, rough Metal), Emission)
        lam = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
        metal = r.create_material("metal", [0.5, 0.5, 0.5], {"roughness": 0.6})
        emit = r.create_material("emissive", [1.0, 1.0, 1.0], {})
        mat = r.create_add_material(r.create_mix_material(lam, metal, 0.5), emit)
    else:   # "mix_principled_metal": Mix(emissive diffuse Principled, rough Metal)
        pr = r.create_material("principled", [0.5, 0.5, 0.5], {
            "roughness": 1.0, "metallic": 0.0, "specular_ior_level": 0.0,
            "coat_weight": 0.0, "sheen_weight": 0.0,
            "emission_color": [1.0, 1.0, 1.0], "emission_strength": 1.0})
        metal = r.create_material("metal", [0.5, 0.5, 0.5], {"roughness": 0.6})
        mat = r.create_mix_material(pr, metal, 0.5)
    c = [np.array([x, y, z], float) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    for a, b, cc, d in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
        for tri in ((a, b, cc), (a, cc, d)):
            v0, v1, v2 = (c[i] for i in tri)
            if np.dot(np.cross(v1 - v0, v2 - v0), -(v0 + v1 + v2)) < 0:   # wind inward
                v1, v2 = v2, v1
            r.add_triangle(v0.tolist(), v1.tolist(), v2.tolist(), mat)
    r.set_background_color([0.0, 0.0, 0.0])
    r.setup_camera([0, 0, 0], [0, 0, -1], [0, 1, 0], 60.0, 1.0, 0.0, 6.0, 32, 32)
    r.set_integrator("path_tracer")
    r.set_seed(1178)
    r.set_adaptive_sampling(False)
    r.set_use_gpu(backend == "gpu")
    img = np.asarray(r.render(spp, 64, None, False, diffuse, glossy, -1, -1, -1), dtype=np.float64)
    return float(img.mean())


@pytest.mark.parametrize("backend", BACKENDS)
def test_principled_diffuse_cap_bounce_count_matches_cycles(backend):
    """A diffuse Principled scatter counts against the diffuse cap (Cycles values, as Lambertian)."""
    got = {n: _box_mean(backend, "principled", diffuse=n) for n in (0, 1, 2, 3)}
    for n, mean in got.items():
        assert abs(mean - _cycles_box(n)) < 0.01, (backend, n, got)


@pytest.mark.parametrize("backend", BACKENDS)
def test_principled_diffuse_scatter_ignores_glossy_cap(backend):
    """A glossy cap of 0 leaves a diffuse-only Principled box uncapped (2.0, not 1.5)."""
    capped = _box_mean(backend, "principled", glossy=0)
    assert abs(capped - _cycles_box(64)) < 0.01, (backend, capped)


@pytest.mark.parametrize("walls,backend", [
    ("mix_lambert_metal", "cpu"),
    ("mix_principled_metal", "cpu"),
    pytest.param("mix_principled_metal", "gpu", marks=pytest.mark.gpu),
])
def test_mix_shader_classifies_by_picked_child(walls, backend):
    """Mix(diffuse, rough metal): the diffuse child's scatters count as diffuse, so a diffuse cap
    of 0 darkens the box and a glossy cap of 0 darkens it too (both children are capped by their
    own type). Before #1178 the Mix's isGlossy() made every scatter glossy: the diffuse cap
    did nothing."""
    free = _box_mean(backend, walls)
    dcap = _box_mean(backend, walls, diffuse=0)
    gcap = _box_mean(backend, walls, glossy=0)
    assert dcap < 0.97 * free, (backend, walls, free, dcap, gcap)
    assert gcap < 0.97 * free, (backend, walls, free, dcap, gcap)


# --------------------------------------------------------------------------- #
# #1198: refractive-caustics toggle on a Principled floor
# --------------------------------------------------------------------------- #

CW, CH = 140, 110


def _caustic_render(backend, floor, refractive):
    r = _renderer(backend)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_integrator("path_tracer")
    r.set_seed(1198)
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})
    r.add_sphere([0.0, 0.0, 0.0], 0.6, glass)
    if floor == "lambertian":
        fm = r.create_material("lambertian", [0.85, 0.85, 0.85], {})
    else:   # diffuse-only Principled: the same BSDF as the Lambertian
        fm = r.create_material("principled", [0.85, 0.85, 0.85],
                               {"roughness": 1.0, "specular_ior_level": 0.0})
    r.add_triangle([-3.0, -1.1, -3.0], [4.0, -1.1, -3.0], [4.0, -1.1, 3.0], fm)
    r.add_triangle([-3.0, -1.1, -3.0], [4.0, -1.1, 3.0], [-3.0, -1.1, 3.0], fm)
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 40.0})
    r.add_triangle([-1.0, 2.2, -1.0], [1.0, 2.2, -1.0], [1.0, 2.2, 1.0], light)
    r.add_triangle([-1.0, 2.2, -1.0], [1.0, 2.2, 1.0], [-1.0, 2.2, 1.0], light)
    r.setup_camera(look_from=[0.0, 0.6, 4.2], look_at=[0.0, -0.6, 0.0],
                   vup=[0, 1, 0], vfov=42, aspect_ratio=CW / CH,
                   aperture=0.0, focus_dist=4.0, width=CW, height=CH)
    r.set_use_refractive_caustics(refractive)
    r.set_use_gpu(backend == "gpu")
    img = np.asarray(r.render(96, 8, None, False), dtype=np.float64)
    return img @ np.array([0.2126, 0.7152, 0.0722])


def _caustic_roi(lum):
    """The refractive caustic on the floor under the sphere (rows 66-75, cols 56-83)."""
    return float(lum[66:76, 56:84].mean())


@pytest.mark.parametrize("backend", BACKENDS)
def test_refractive_caustics_off_drops_principled_floor_caustic_like_lambertian(backend, tmp_path):
    ratio = {}
    for floor in ("lambertian", "principled"):
        on = _caustic_render(backend, floor, True)
        off = _caustic_render(backend, floor, False)
        ratio[floor] = _caustic_roi(off) / _caustic_roi(on)
        out = os.environ.get("ASTRORAY_I1178_EVIDENCE")
        if out:
            np.save(Path(out) / f"caustic_{backend}_{floor}_on.npy", on)
            np.save(Path(out) / f"caustic_{backend}_{floor}_off.npy", off)
    assert ratio["lambertian"] < 0.8, ratio
    assert abs(ratio["principled"] - ratio["lambertian"]) < 0.05, ratio


# --------------------------------------------------------------------------- #
# Light Path "Is Diffuse Ray" after a Principled diffuse bounce
# --------------------------------------------------------------------------- #

_UV = {"UVMap": [[0, 0], [1, 0], [1, 1]]}


def _quad(r, mat, c, u, v):
    p = [[c[i] + su * u[i] + sv * v[i] for i in range(3)]
         for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    r.add_triangle_layers(p[0], p[1], p[2], mat, _UV, p[0], p[1], p[2])
    r.add_triangle_layers(p[0], p[2], p[3], mat, _UV, p[0], p[2], p[3])


def _is_diffuse_panel(backend, panel):
    """Camera -> panel -> wall whose base colour is Is Diffuse Ray, lit by a sun the panel's
    front does not see. The panel is lit only through the wall, so it reads 0 unless the
    panel's bounce is labelled diffuse."""
    import shader_vm_compiler as C
    from test_issue989_perhit_shading_inputs import Link, Node, Sock
    r = _renderer(backend)
    r.set_seed(1178)
    r.set_background_color([0.0, 0.0, 0.0])
    lp = Node('LIGHT_PATH')
    mul = Node('MATH', operation='MULTIPLY',
               inputs=[Sock('A', 0.0, Link(lp, 'Is Diffuse Ray')), Sock('B', 1.0)])
    compiled = C.compile_chain(Sock('Base Color', [0.8, 0.8, 0.8], Link(mul, 'Value')))
    r.create_program_texture("isdiff1178", "UV")
    r.set_program_texture_program("isdiff1178", compiled['num_tex'], compiled['out_slot'],
                                  compiled['code_flat'], compiled['consts_flat'],
                                  compiled['ramps_flat'])
    wall = r.create_material("principled", [0.8, 0.8, 0.8],
                             {"roughness": 1.0, "specular_ior_level": 0.0,
                              "base_color_texture": "isdiff1178"})
    if panel == "lambertian":
        pm = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    else:
        pm = r.create_material("principled", [0.8, 0.8, 0.8],
                               {"roughness": 1.0, "specular_ior_level": 0.0})
    _quad(r, pm, [0, 4, 0], [2.0, 0, 0], [0, 0, 2.0])      # normal -y: faces the camera
    _quad(r, wall, [0, -4, 0], [0, 0, 6.0], [6.0, 0, 0])   # normal +y: faces the panel
    # light travels (0, -1, -1): lights the wall's front, the panel's back
    r.add_sun_light_dedicated([0.0, -0.7071, -0.7071], 0.01,
                              {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]}, 3.0, 0, 0)
    from base_helpers import render_image, setup_camera
    setup_camera(r, look_from=[0, 0, 0], look_at=[0, 1, 0], vup=[0, 0, 1], vfov=10,
                 width=48, height=48)
    r.set_use_gpu(backend == "gpu")
    img = render_image(r, samples=128, max_depth=6, apply_gamma=False)
    return float(img[20:28, 20:28].mean())


@pytest.mark.parametrize("backend", BACKENDS)
def test_is_diffuse_ray_after_principled_diffuse_bounce(backend):
    lam = _is_diffuse_panel(backend, "lambertian")
    pr = _is_diffuse_panel(backend, "principled")
    assert lam > 1e-3, (backend, lam, pr)
    assert abs(pr / lam - 1.0) < 0.1, (backend, lam, pr)
