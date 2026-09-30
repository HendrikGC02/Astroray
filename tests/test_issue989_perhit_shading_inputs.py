"""#989 — per-hit shading inputs in the op-VM: Layer Weight, Fresnel, Geometry Backfacing.

OP_SHADING reads the hit's cos(view, shading normal) and back-face flag
(Cycles kernel/svm/fresnel.h svm_node_layer_weight / svm_node_fresnel and
svm/light_path.h NODE_LP_backfacing). CPU: ProgramTexture::valueAtHit; GPU: the
<HasProgram> shade block. A program over shading inputs only has no texture.
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import shader_vm_compiler as C  # noqa: E402


class Sock:
    def __init__(self, name, default=0.0, link=None, type=None):
        self.name = name
        self.default_value = default
        self._link = link
        if type is not None:
            self.type = type

    @property
    def is_linked(self):
        return self._link is not None

    @property
    def links(self):
        return [self._link] if self._link else []


class Link:
    def __init__(self, from_node, from_socket_name):
        self.from_node = from_node
        self.from_socket = type("S", (), {"name": from_socket_name, "type": "VALUE"})()


class SockList:
    def __init__(self, socks):
        self._socks = socks
        self._by_name = {s.name: s for s in socks}

    def get(self, name):
        return self._by_name.get(name)

    def __getitem__(self, i):
        return self._socks[i]

    def __len__(self):
        return len(self._socks)

    def __iter__(self):
        return iter(self._socks)


class Node:
    def __init__(self, type, inputs=None, **kw):
        self.type = type
        self.inputs = SockList(inputs or [])
        for k, v in kw.items():
            setattr(self, k, v)


_A, _B = (0.55, 0.04, 0.03), (0.95, 0.62, 0.2)


def _layer_weight_mix(blend=0.35, output='Facing'):
    lw = Node('LAYER_WEIGHT', inputs=[Sock('Blend', blend), Sock('Normal', [0, 0, 0])])
    mix = Node('MIX_RGB', blend_type='MIX',
               inputs=[Sock('Fac', 0.5, Link(lw, output)),
                       Sock('Color1', list(_A)), Sock('Color2', list(_B))])
    return Sock('Base Color', [0.8, 0.8, 0.8], Link(mix, 'Color'))


def _fresnel_metallic(ior=1.8, scale=0.6):
    fr = Node('FRESNEL', inputs=[Sock('IOR', ior), Sock('Normal', [0, 0, 0])])
    mul = Node('MATH', operation='MULTIPLY',
               inputs=[Sock('A', 0.0, Link(fr, 'Fac')), Sock('B', scale)])
    return Sock('Metallic', 0.0, Link(mul, 'Value'), type='VALUE')


# ---- Python reference of the Cycles formulas ----------------------------------
def _fresnel_dielectric_cos(cosi, eta):
    c = abs(cosi)
    g = eta * eta - 1 + c * c
    if g > 0:
        g = math.sqrt(g)
        a = (g - c) / (g + c)
        b = (c * (g + c) - 1) / (c * (g - c) + 1)
        return 0.5 * a * a * (1 + b * b)
    return 1.0


def _facing(cosi, blend):
    f = abs(cosi)
    if blend != 0.5:
        blend = min(max(blend, 0.0), 1.0 - 1e-5)
        blend = 2 * blend if blend < 0.5 else 0.5 / (1 - blend)
        f = f ** blend
    return 1 - f


# ---- compiler -----------------------------------------------------------------
def test_layer_weight_chain_compiles_without_texture():
    compiled = C.compile_chain(_layer_weight_mix())
    assert compiled is not None and compiled['per_hit'] and compiled['num_tex'] == 0
    ops = compiled['code_flat'][0::8]
    imms = compiled['code_flat'][7::8]
    assert C.OP_SHADING in ops
    assert imms[ops.index(C.OP_SHADING)] == C.SH_LAYER_FACING


def test_fresnel_and_backfacing_compile():
    compiled = C.compile_chain(_fresnel_metallic())
    assert compiled['per_hit'] and C.OP_SHADING in compiled['code_flat'][0::8]
    geo = Node('NEW_GEOMETRY')
    sock = Sock('Roughness', 0.5, Link(geo, 'Backfacing'), type='VALUE')
    compiled = C.compile_chain(sock)
    assert compiled['code_flat'][7::8][compiled['code_flat'][0::8].index(C.OP_SHADING)] \
        == C.SH_BACKFACING


def test_unsupported_shading_forms_raise():
    geo = Node('NEW_GEOMETRY')
    with pytest.raises(C.VMCompileError, match="Pointiness"):
        C.compile_chain(Sock('Roughness', 0.5, Link(geo, 'Pointiness'), type='VALUE'))
    bump = Node('BUMP')
    fr = Node('FRESNEL', inputs=[Sock('IOR', 1.5), Sock('Normal', [0, 0, 0], Link(bump, 'Normal'))])
    with pytest.raises(C.VMCompileError, match="linked Normal"):
        C.compile_chain(Sock('Metallic', 0.0, Link(fr, 'Fac'), type='VALUE'))


def test_texture_free_chain_without_shading_still_folds():
    mix = Node('MIX_RGB', blend_type='MIX',
               inputs=[Sock('Fac', 0.5), Sock('Color1', list(_A)), Sock('Color2', list(_B))])
    assert C.compile_chain(Sock('Base Color', [0.8] * 3, Link(mix, 'Color'))) is None


# ---- engine (CPU) ---------------------------------------------------------------
def _program(r, name, compiled):
    r.create_program_texture(name, "UV")
    r.set_program_texture_program(name, compiled['num_tex'], compiled['out_slot'],
                                  compiled['code_flat'], compiled['consts_flat'],
                                  compiled['ramps_flat'])


def _dir(theta):
    return [math.sin(theta), math.cos(theta), 0.0]


@pytest.mark.parametrize("theta_deg", [0.0, 35.0, 60.0, 80.0])
def test_cpu_layer_weight_base_color_matches_cycles_formula(theta_deg):
    astroray = pytest.importorskip("astroray")
    r = astroray.Renderer()
    _program(r, "lw989", C.compile_chain(_layer_weight_mix(0.35)))
    params = {"roughness": 0.32, "coat_weight": 1.0, "coat_roughness": 0.03}
    tex = r.create_material("principled", [0.8, 0.8, 0.8], dict(params, base_color_texture="lw989"))
    wo = _dir(math.radians(theta_deg))
    fac = _facing(math.cos(math.radians(theta_deg)), 0.35)
    ref_col = [a + (b - a) * fac for a, b in zip(_A, _B)]
    ref = r.create_material("principled", ref_col, dict(params))
    n = [0.0, 1.0, 0.0]
    for wi in (_dir(-math.radians(20.0)), [0.3, 0.8, 0.52]):
        np.testing.assert_allclose(r.eval_material(tex, wo, wi, n),
                                   r.eval_material(ref, wo, wi, n), rtol=2e-4, atol=1e-6)


@pytest.mark.parametrize("theta_deg", [0.0, 50.0, 75.0])
def test_cpu_fresnel_metallic_program_matches_cycles_formula(theta_deg):
    astroray = pytest.importorskip("astroray")
    r = astroray.Renderer()
    _program(r, "fr989", C.compile_chain(_fresnel_metallic(1.8, 0.6)))
    base = [0.55, 0.3, 0.1]
    tex = r.create_material("principled", base, {"roughness": 0.3, "metallic_program": "fr989"})
    cos_t = math.cos(math.radians(theta_deg))
    metal = 0.6 * _fresnel_dielectric_cos(cos_t, 1.8)
    ref = r.create_material("principled", base, {"roughness": 0.3, "metallic": metal})
    n, wo = [0.0, 1.0, 0.0], _dir(math.radians(theta_deg))
    wi = _dir(-math.radians(theta_deg))
    np.testing.assert_allclose(r.eval_material(tex, wo, wi, n),
                               r.eval_material(ref, wo, wi, n), rtol=2e-4, atol=1e-6)


# ---- GPU parity -----------------------------------------------------------------
def _sphere_scene(r, use_gpu):
    from base_helpers import setup_camera
    if use_gpu:
        r.set_use_gpu(True)
    r.set_seed(5)
    r.set_background_color([0.6, 0.6, 0.6])
    _program(r, "lw989g", C.compile_chain(_layer_weight_mix(0.35)))
    _program(r, "fr989g", C.compile_chain(_fresnel_metallic(1.8, 0.6)))
    mat = r.create_material("principled", [0.8, 0.8, 0.8],
                            {"roughness": 0.32, "base_color_texture": "lw989g",
                             "metallic_program": "fr989g"})
    # Tessellated sphere (the GPU program path runs on triangles).
    n_th, n_ph, rad = 24, 48, 1.0
    for i in range(n_th):
        t0, t1 = math.pi * i / n_th, math.pi * (i + 1) / n_th
        for j in range(n_ph):
            p0, p1 = 2 * math.pi * j / n_ph, 2 * math.pi * (j + 1) / n_ph
            q = [[rad * math.sin(t) * math.cos(p), rad * math.sin(t) * math.sin(p), rad * math.cos(t)]
                 for t, p in ((t0, p0), (t1, p0), (t1, p1), (t0, p1))]
            uv = {"UVMap": [[0, 0], [1, 0], [1, 1]]}
            r.add_triangle_layers(q[0], q[1], q[2], mat, uv, q[0], q[1], q[2])
            r.add_triangle_layers(q[0], q[2], q[3], mat, uv, q[0], q[2], q[3])
    setup_camera(r, look_from=[0, -4, 0], look_at=[0, 0, 0], vup=[0, 0, 1],
                 vfov=35, width=64, height=64)


def _has_cuda_gpu(r):
    import astroray
    return bool(astroray.__features__.get("cuda", False)) and bool(getattr(r, "gpu_available", False))


@pytest.mark.gpu
def test_gpu_perhit_shading_inputs_match_cpu():
    pytest.importorskip("astroray")
    from base_helpers import create_renderer, render_image
    rg = create_renderer()
    if not _has_cuda_gpu(rg):
        pytest.skip("No CUDA GPU")
    _sphere_scene(rg, True)
    gpu = render_image(rg, samples=64, max_depth=3, apply_gamma=False)
    rc = create_renderer()
    _sphere_scene(rc, False)
    cpu = render_image(rc, samples=64, max_depth=3, apply_gamma=False)
    # Centre (facing ~0 -> colour A, red) vs limb (facing -> 1 -> colour B, orange):
    # the green channel rises toward the limb on the GPU (flat before #989).
    cen = gpu[28:36, 28:36].reshape(-1, 3).mean(axis=0)
    limb = gpu[28:36, 49:53].reshape(-1, 3).mean(axis=0)
    assert limb[1] > cen[1] * 1.5, (cen, limb)
    g = gpu.reshape(8, 8, 8, 8, 3).mean(axis=(1, 3))
    c = cpu.reshape(8, 8, 8, 8, 3).mean(axis=(1, 3))
    ratio = g.reshape(-1, 3).mean(axis=0) / np.maximum(c.reshape(-1, 3).mean(axis=0), 1e-6)
    assert np.all((ratio > 0.95) & (ratio < 1.05)), ratio
    assert np.abs(g - c).mean() < 0.03, np.abs(g - c).mean()
