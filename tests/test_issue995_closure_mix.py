"""#995 / #955: Mix Shader with a per-texel Fac is a closure mix, Add Shader a closure sum.

Cycles (kernel/svm/closure.h svm_node_mix_closure) weights the two closure subtrees
by (1 - fac) and fac, with fac evaluated per shading point; Add passes the incoming
weight to both children. Emission is one more closure, and the path continues
through the BSDF closures (kernel/integrator/shade_surface.h). The addon used to
lerp Principled parameters with the Fac's constant default and to fold the
emission into the result, and the integrators ended the path at any emissive hit,
so the stack below rendered as its emission only.

Reference (analytic): a flat quad under a uniform white sky of radiance 1 returns
L = sum_i w_i albedo_i + E for Lambertian leaves. Stack:
  Add( Mix( Mix(red, blue, Checker.Fac), green, Checker.Color ), Emission E )
Checker cells: Fac 1 + Color 0.8 (cell kind X), Fac 0 + Color 0.3 (cell kind Y).
"""
import os
import sys

import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import shader_blending  # real module; the addon stub replaces it in sys.modules
from test_issue818_procedural_opvm import Link, Sock, _load_addon_stub
from test_pkg293_gpu_lobe_programs import _node, _Socks  # noqa: F401  (mock nodes)

_W = _H = 48
_VFOV = float(np.degrees(2 * np.arctan(0.95 / 3.0)))   # visible [-0.95, 0.95]
_BBOX_MIN = [-1.0, -1.0, -1.3]
_BBOX_SIZE = [2.0, 2.0, 2.0]

RED, BLUE, GREEN = [0.6, 0.1, 0.1], [0.1, 0.1, 0.6], [0.1, 0.6, 0.1]
EMIT_COLOR, EMIT_STRENGTH = [1.0, 0.5, 0.25], 0.4
C1, C2 = 0.8, 0.3                       # Checker Color1 / Color2 (grey) = outer Fac


def _expected():
    e = np.array(EMIT_COLOR) * EMIT_STRENGTH
    red, blue, green = map(np.array, (RED, BLUE, GREEN))
    x = (1.0 - C1) * blue + C1 * green + e      # inner Fac 1 -> blue, outer Fac 0.8
    y = (1.0 - C2) * red + C2 * green + e       # inner Fac 0 -> red, outer Fac 0.3
    return x, y


def _checker(name):
    return _node('TEX_CHECKER', name, [Sock('Vector'), Sock('Scale', 2.0),
                                       Sock('Color1', [C1, C1, C1, 1.0]),
                                       Sock('Color2', [C2, C2, C2, 1.0])])


def _diffuse(name, color):
    return _node('BSDF_DIFFUSE', name, [Sock('Color', color + [1.0]), Sock('Roughness', 0.0)])


def _mix(name, fac_link, a, b):
    return _node('MIX_SHADER', name, [Sock('Fac', 0.5, fac_link),
                                      Sock('Shader', None, Link(a, 'BSDF')),
                                      Sock('Shader_001', None, Link(b, 'Shader'))])


def _stack(with_emission=True):
    chk = _checker('Chk')
    inner = _mix('Inner', Link(chk, 'Fac'), _diffuse('Red', RED), _diffuse('Blue', BLUE))
    outer = _mix('Outer', Link(chk, 'Color'), inner, _diffuse('Green', GREEN))
    # inner.outputs are 'Shader'; the mock Link names the socket only for display.
    if not with_emission:
        return outer
    em = _node('EMISSION', 'Em', [Sock('Color', EMIT_COLOR + [1.0]),
                                  Sock('Strength', EMIT_STRENGTH)])
    return _node('ADD_SHADER', 'Add', [Sock('Shader', None, Link(outer, 'Shader')),
                                       Sock('Shader_001', None, Link(em, 'Emission'))])


def _engine(monkeypatch):
    addon = _load_addon_stub(monkeypatch)
    addon.blend_shader_specs = shader_blending.blend_shader_specs
    addon.add_shader_specs = shader_blending.add_shader_specs
    eng = addon.CustomRaytracerRenderEngine.__new__(addon.CustomRaytracerRenderEngine)
    eng._current_material_name = "M995"
    eng._generated_textures_by_material = {}
    eng._use_native_principled = lambda: True
    return eng


def _lower(monkeypatch, r, out_node):
    eng = _engine(monkeypatch)
    spec = eng._shader_spec_from_node(out_node, r, None)
    mat = eng._create_material_from_shader_spec(spec, r)
    for name in eng._generated_textures_by_material.get("M995", []):
        r.set_texture_generated_bbox(name, _BBOX_MIN, _BBOX_SIZE)
    return spec, mat, eng._degradation_report().messages()


def _render(monkeypatch, use_gpu=False, samples=192):
    r = create_renderer()
    if use_gpu:
        if not (astroray.__features__.get("cuda", False) and getattr(r, "gpu_available", False)):
            pytest.skip("No CUDA GPU — the #995 GPU leg runs on the RTX box.")
        r.set_use_gpu(True)
    r.set_seed(5)
    r.set_adaptive_sampling(False)
    r.set_background_color([1.0, 1.0, 1.0])
    _, mat, lines = _lower(monkeypatch, r, _stack())
    A, B, C, D = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=_VFOV, width=_W, height=_H)
    return np.asarray(render_image(r, samples=samples, max_depth=4, apply_gamma=False)), lines


def _cells(img):
    """Mean RGB of the four checker cells, away from the cell borders."""
    H, W = img.shape[:2]
    out = []
    for ya, yb in ((0.1, 0.4), (0.6, 0.9)):
        for xa, xb in ((0.1, 0.4), (0.6, 0.9)):
            out.append(img[int(ya * H):int(yb * H), int(xa * W):int(xb * W)].reshape(-1, 3).mean(0))
    return np.array(out)


def _assert_stack(cells, label):
    x, y = _expected()
    got = cells[np.argsort(cells[:, 0])]          # X cells have the lower red
    want = np.array([x, x, y, y])
    assert np.allclose(got, want, rtol=0.05, atol=0.01), (
        f"{label}: per-cell radiance != analytic closure stack\n got={got}\nwant={want}")


def test_spec_textured_fac_keeps_both_closures(monkeypatch):
    """The export must keep every closure of the stack (no parameter lerp)."""
    spec, _, lines = _lower(monkeypatch, create_renderer(), _stack())
    assert spec['kind'] == 'add', spec
    outer = spec['a']
    assert outer['kind'] == 'mix' and outer.get('fac_texture'), outer
    assert outer['a']['kind'] == 'mix' and outer['a'].get('fac_texture'), outer['a']
    assert spec['b']['kind'] == 'emission', spec['b']
    assert not any('constant mix' in m for m in lines), lines


def test_closure_stack_cpu_matches_analytic(monkeypatch):
    img, _ = _render(monkeypatch)
    _assert_stack(_cells(img), "CPU")


def test_closure_stack_gpu_matches_analytic(monkeypatch):
    img, _ = _render(monkeypatch, use_gpu=True)
    _assert_stack(_cells(img), "GPU")
