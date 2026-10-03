"""#991 — Light Path node: per-hit path state (op-VM OP_SHADING) and Mix Shader
closure switches (Is Camera Ray / Is Shadow Ray ...), CPU and GPU.

Semantics: Cycles kernel/svm/light_path.h svm_node_light_path and
integrator/path_state.h path_state_next (Apache-2.0); shared service
include/astroray/light_path.h. Research note:
.astroray_plan/docs/issue991-light-path-research.md.
"""
import math
import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import shader_vm_compiler as C
from test_issue989_perhit_shading_inputs import Link, Node, Sock


def _lp_value(output, scale=1.0):
    """Light Path <output> * scale -> a VALUE socket (Base Color broadcast)."""
    lp = Node('LIGHT_PATH')
    mul = Node('MATH', operation='MULTIPLY',
               inputs=[Sock('A', 0.0, Link(lp, output)), Sock('B', scale)])
    return Sock('Base Color', [0.8, 0.8, 0.8], Link(mul, 'Value'))


# ---- compiler -----------------------------------------------------------------
@pytest.mark.parametrize("output", C.LIGHT_PATH_OUTPUTS)
def test_light_path_outputs_compile_to_op_shading(output):
    compiled = C.compile_chain(_lp_value(output))
    assert compiled is not None and compiled['per_hit'] and compiled['num_tex'] == 0
    ops, imms = compiled['code_flat'][0::8], compiled['code_flat'][7::8]
    assert imms[ops.index(C.OP_SHADING)] == C.SH_LIGHT_PATH + C.LIGHT_PATH_OUTPUTS.index(output)
    assert (output in compiled['light_path_approx']) == (output in C.LIGHT_PATH_APPROXIMATE)


def test_light_path_portal_depth_is_reported_not_silent():
    with pytest.raises(C.VMCompileError, match="Portal Depth"):
        C.compile_chain(_lp_value('Portal Depth'))


def test_light_path_enum_matches_engine_header():
    """The compiler's output order must equal lightpath::Output (light_path.h)."""
    hdr = Path(__file__).resolve().parents[1].joinpath(
        "include", "astroray", "light_path.h").read_text(encoding="utf-8")
    body = hdr[hdr.index("enum Output"):hdr.index("LPO_COUNT")]
    names = [t.strip().split("=")[0].strip() for t in body.split("{", 1)[1].split(",") if t.strip()]
    assert len(names) == len(C.LIGHT_PATH_OUTPUTS)
    assert names[C.LIGHT_PATH_OUTPUTS.index('Ray Length')] == 'LPO_RAY_LENGTH'
    assert names[C.LIGHT_PATH_OUTPUTS.index('Is Shadow Ray')] == 'LPO_IS_SHADOW'
    assert C.LIGHT_PATH_BOOLEAN[-1] == 'Is Volume Scatter Ray'


# ---- engine scenes ----------------------------------------------------------------
def _program(r, name, compiled):
    r.create_program_texture(name, "UV")
    r.set_program_texture_program(name, compiled['num_tex'], compiled['out_slot'],
                                  compiled['code_flat'], compiled['consts_flat'],
                                  compiled['ramps_flat'])


_UV = {"UVMap": [[0, 0], [1, 0], [1, 1]]}


def _quad(r, mat, c, u, v):
    """Quad centre c, half-edges u, v (normal = u x v)."""
    p = [[c[i] + su * u[i] + sv * v[i] for i in range(3)]
         for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    r.add_triangle_layers(p[0], p[1], p[2], mat, _UV, p[0], p[1], p[2])
    r.add_triangle_layers(p[0], p[2], p[3], mat, _UV, p[0], p[2], p[3])


def _sphere(r, mat, centre, rad, n_th=16, n_ph=32):
    for i in range(n_th):
        t0, t1 = math.pi * i / n_th, math.pi * (i + 1) / n_th
        for j in range(n_ph):
            p0, p1 = 2 * math.pi * j / n_ph, 2 * math.pi * (j + 1) / n_ph
            q = [[centre[0] + rad * math.sin(t) * math.cos(p),
                  centre[1] + rad * math.sin(t) * math.sin(p),
                  centre[2] + rad * math.cos(t)] for t, p in ((t0, p0), (t1, p0), (t1, p1), (t0, p1))]
            r.add_triangle_layers(q[0], q[1], q[2], mat, _UV, q[0], q[1], q[2])  # outward
            r.add_triangle_layers(q[0], q[2], q[3], mat, _UV, q[0], q[2], q[3])


def _renderer(use_gpu):
    pytest.importorskip("astroray")
    from base_helpers import create_renderer
    r = create_renderer()
    if use_gpu:
        import astroray
        if not (astroray.__features__.get("cuda", False) and getattr(r, "gpu_available", False)):
            pytest.skip("No CUDA GPU")
        r.set_use_gpu(True)
    r.set_seed(7)
    return r


def _render(r, look_from, look_at, spp=64, depth=6, size=48, vfov=30):
    from base_helpers import render_image, setup_camera
    setup_camera(r, look_from=look_from, look_at=look_at, vup=[0, 0, 1], vfov=vfov,
                 width=size, height=size)
    return render_image(r, samples=spp, max_depth=depth, apply_gamma=False)


def _roi(img, cy, cx, h=3):
    return img[cy - h:cy + h, cx - h:cx + h].reshape(-1, 3).mean(axis=0)


BACKENDS = [pytest.param(False, id="cpu"), pytest.param(True, id="gpu", marks=pytest.mark.gpu)]


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_ray_length_program_equals_constant_albedo(use_gpu):
    """Base Color = Ray Length * 0.1 on a wall at distance d renders exactly like a
    constant albedo 0.1 d (camera rays: Ray Length = hit distance)."""
    imgs = {}
    for d in (3.0, 6.0):
        for kind in ("program", "constant"):
            r = _renderer(use_gpu)
            r.set_background_color([1.0, 1.0, 1.0])
            if kind == "program":
                _program(r, "rl991", C.compile_chain(_lp_value('Ray Length', 0.1)))
                mat = r.create_material("principled", [0.8, 0.8, 0.8],
                                        {"roughness": 1.0, "specular_ior_level": 0.0,
                                         "base_color_texture": "rl991"})
            else:
                mat = r.create_material("principled", [0.1 * d] * 3,
                                        {"roughness": 1.0, "specular_ior_level": 0.0})
            _quad(r, mat, [0, d, 0], [40.0, 0, 0], [0, 0, 40.0])  # normal -y (faces camera)
            imgs[(d, kind)] = _render(r, [0, 0, 0], [0, 1, 0], vfov=10)
    for d in (3.0, 6.0):
        p, c = _roi(imgs[(d, "program")], 24, 24), _roi(imgs[(d, "constant")], 24, 24)
        np.testing.assert_allclose(p, c, rtol=0.04)
    ratio = _roi(imgs[(6.0, "program")], 24, 24) / _roi(imgs[(3.0, "program")], 24, 24)
    np.testing.assert_allclose(ratio, 2.0, rtol=0.05)


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_is_singular_ray_program_tracks_path_state(use_gpu):
    """A wall whose base colour is Is Singular Ray is black seen directly and white
    seen through a perfect mirror (the path state survives the bounce)."""
    vals = {}
    for via_mirror in (False, True):
        r = _renderer(use_gpu)
        r.set_background_color([1.0, 1.0, 1.0])
        _program(r, "sg991", C.compile_chain(_lp_value('Is Singular Ray')))
        wall = r.create_material("principled", [0.8, 0.8, 0.8],
                                 {"roughness": 1.0, "specular_ior_level": 0.0,
                                  "base_color_texture": "sg991"})
        if via_mirror:
            mirror = r.create_material("metal", [1.0, 1.0, 1.0], {"roughness": 0.0})
            _quad(r, mirror, [0, 4, 0], [2.0, 0, 0], [0, 0, 2.0])   # faces the camera
            _quad(r, wall, [0, -4, 0], [0, 0, 2.0], [2.0, 0, 0])    # behind it, faces +y
        else:
            _quad(r, wall, [0, 4, 0], [2.0, 0, 0], [0, 0, 2.0])
        vals[via_mirror] = _roi(_render(r, [0, 0, 0], [0, 1, 0], vfov=10), 24, 24).mean()
    assert vals[False] < 0.02, vals
    assert vals[True] > 0.3, vals


def _emitter_scene(r, switch):
    r.set_background_color([0.02, 0.02, 0.02])
    floor = r.create_material("principled", [0.7, 0.7, 0.7],
                              {"roughness": 1.0, "specular_ior_level": 0.0})
    _quad(r, floor, [0, 0, 0], [6.0, 0, 0], [0, 6.0, 0])
    emit = r.create_material("light", [1.0, 0.85, 0.6], {"intensity": 20.0})
    if switch:
        hidden = r.create_material("principled", [1.0, 1.0, 1.0], {"alpha": 0.0})
        emit = r.create_light_path_mix(emit, hidden, C.LIGHT_PATH_OUTPUTS.index('Is Camera Ray'))
    _sphere(r, emit, [0, 0, 1.0], 0.35)


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_is_camera_ray_switch_hides_emitter_but_keeps_its_light(use_gpu):
    imgs = {}
    for switch in (False, True):
        r = _renderer(use_gpu)
        _emitter_scene(r, switch)
        imgs[switch] = _render(r, [0, -5, 2.2], [0, 0, 0.7], spp=128)
    centre_plain, centre_hidden = _roi(imgs[False], 18, 24, 2), _roi(imgs[True], 18, 24, 2)
    assert centre_plain.mean() > 5.0 * centre_hidden.mean(), (centre_plain, centre_hidden)
    # The floor in front of / beside the emitter is lit identically (the emission-
    # context child is the emitter: NEE and indirect hits see it).
    for cy, cx in ((40, 24), (34, 10), (34, 38)):
        a, b = _roi(imgs[False], cy, cx), _roi(imgs[True], cy, cx)
        np.testing.assert_allclose(b, a, rtol=0.08)


def _glass_shadow_scene(r, mode):
    r.set_background_color([0.05, 0.05, 0.05])
    # direction = the way the light travels: the sphere's shadow lands at (0.25, 0, 0)
    r.add_sun_light_dedicated([0.6, 0.0, -0.8], 0.01, {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]},
                              3.0, 0, 0)
    floor = r.create_material("principled", [0.7, 0.7, 0.7],
                              {"roughness": 1.0, "specular_ior_level": 0.0})
    _quad(r, floor, [0, 0, 0], [6.0, 0, 0], [0, 6.0, 0])
    if mode == "none":
        return
    glass = r.create_material("principled", [1.0, 1.0, 1.0],
                              {"transmission_weight": 1.0, "ior": 1.45, "roughness": 0.0})
    if mode == "switch":
        clear = r.create_material("principled", [1.0, 1.0, 1.0], {"alpha": 0.0})
        glass = r.create_light_path_mix(glass, clear, C.LIGHT_PATH_OUTPUTS.index('Is Shadow Ray'))
    _sphere(r, glass, [-0.5, 0, 1.0], 0.4)


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_is_shadow_ray_switch_makes_glass_shadow_transparent(use_gpu):
    """Mix(Glass, Transparent, Is Shadow Ray): no sun shadow (as with no sphere);
    the plain glass sphere blocks the delta sun light."""
    vals = {}
    for mode in ("none", "glass", "switch"):
        r = _renderer(use_gpu)
        _glass_shadow_scene(r, mode)
        img = _render(r, [0.25, -5, 0.6], [0.25, 0, 0], spp=96, vfov=24)
        vals[mode] = _roi(img, 24, 24, 2)  # the sun shadow of the sphere, (0.25, 0, 0)
    assert vals["glass"].mean() < 0.6 * vals["none"].mean(), vals
    np.testing.assert_allclose(vals["switch"], vals["none"], rtol=0.06)


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_camera_ray_survives_a_transparent_pass(use_gpu):
    """Cycles keeps the ray flags through a transparent pass (path_state_next
    LABEL_TRANSPARENT): a wall coloured Is Camera Ray seen through an Alpha-0
    sheet is still lit as a camera hit (white), and Transparent Depth counts 1."""
    vals = {}
    for output in ('Is Camera Ray', 'Transparent Depth'):
        r = _renderer(use_gpu)
        r.set_background_color([1.0, 1.0, 1.0])
        _program(r, "tp991", C.compile_chain(_lp_value(output)))
        wall = r.create_material("principled", [0.8, 0.8, 0.8],
                                 {"roughness": 1.0, "specular_ior_level": 0.0,
                                  "base_color_texture": "tp991"})
        sheet = r.create_material("principled", [1.0, 1.0, 1.0], {"alpha": 0.0})
        _quad(r, sheet, [0, 2, 0], [2.0, 0, 0], [0, 0, 2.0])
        _quad(r, wall, [0, 5, 0], [6.0, 0, 0], [0, 0, 6.0])
        vals[output] = _roi(_render(r, [0, 0, 0], [0, 1, 0], vfov=10), 24, 24).mean()
    assert vals['Is Camera Ray'] > 0.8, vals
    assert vals['Transparent Depth'] > 0.8, vals


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_normal_incidence_glass_is_a_transmission_not_a_transparent_pass(use_gpu):
    """Terra review: a smooth dielectric refracts a normal-incidence ray straight on
    (wi == -wo) like a transparent pass, but Cycles labels it a singular
    transmission. A wall coloured Is Transmission Ray seen through a glass slab
    at normal incidence must read 1."""
    r = _renderer(use_gpu)
    r.set_background_color([1.0, 1.0, 1.0])
    _program(r, "tr991", C.compile_chain(_lp_value('Is Transmission Ray')))
    wall = r.create_material("principled", [0.8, 0.8, 0.8],
                             {"roughness": 1.0, "specular_ior_level": 0.0,
                              "base_color_texture": "tr991"})
    glass = r.create_material("principled", [1.0, 1.0, 1.0],
                              {"transmission_weight": 1.0, "ior": 1.5, "roughness": 0.0})
    _quad(r, glass, [0, 2.0, 0], [1.0, 0, 0], [0, 0, 1.0])     # front face, normal -y
    _quad(r, glass, [0, 2.2, 0], [0, 0, 1.0], [1.0, 0, 0])     # back face, normal +y
    _quad(r, wall, [0, 5, 0], [6.0, 0, 0], [0, 0, 6.0])
    val = _roi(_render(r, [0, 0, 0], [0, 1, 0], vfov=2), 24, 24).mean()
    assert val > 0.3, val
