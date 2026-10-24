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
    """The export must keep every closure of the stack (no parameter lerp), and the
    stack must lower to one GPU closure tree (graph-program Facs, emission baked into
    the first Principled): no GPU degradation is reported."""
    r = create_renderer()
    spec, mat, lines = _lower(monkeypatch, r, _stack())
    assert spec['kind'] == 'add', spec
    outer = spec['a']
    assert outer['kind'] == 'mix' and str(outer.get('fac_texture')).startswith('_graph_'), outer
    assert outer['a']['kind'] == 'mix' and str(outer['a'].get('fac_texture')).startswith('_graph_')
    assert spec['b']['kind'] == 'emission', spec['b']
    assert not lines, lines
    caps = r.get_material_backend_capabilities(mat)
    assert not caps['gpu_approximate'] and '4 closures' in caps['notes'], caps


def test_closure_stack_cpu_matches_analytic(monkeypatch):
    img, _ = _render(monkeypatch)
    _assert_stack(_cells(img), "CPU")


def test_closure_stack_gpu_matches_analytic(monkeypatch):
    img, _ = _render(monkeypatch, use_gpu=True)
    _assert_stack(_cells(img), "GPU")


# ---- engine: emission + BSDF on one surface continues the path -------------------
def _gpu_or_skip(r, use_gpu):
    if use_gpu:
        if not (astroray.__features__.get("cuda", False) and getattr(r, "gpu_available", False)):
            pytest.skip("No CUDA GPU — the #995 GPU leg runs on the RTX box.")
        r.set_use_gpu(True)


def _wall(make, spp=96, use_gpu=False):
    r = create_renderer()
    _gpu_or_skip(r, use_gpu)
    r.set_seed(5)
    r.set_adaptive_sampling(False)
    r.set_background_color([1.0, 1.0, 1.0])
    r.setup_camera([0, 0, 3], [0, 0, 0], [0, 1, 0], 20.0, 1.0, 0.0, 3.0, 24, 24)
    r.add_triangle([-20, -20, 0], [20, -20, 0], [0, 20, 0], make(r))
    img = np.asarray(r.render(spp, 4, None, False), dtype=np.float32)
    return img[9:15, 9:15].reshape(-1, 3).mean(0)


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
def test_principled_emission_keeps_its_bsdf(use_gpu):
    """Cycles writes the emission and continues through the BSDF (shade_surface.h);
    the integrators used to end the path at any emissive hit (L = E only)."""
    got = _wall(lambda r: r.create_material(
        "principled", [0.5, 0.5, 0.5],
        {"roughness": 1.0, "specular_ior_level": 0.0,
         "emission_color": [1.0, 1.0, 1.0], "emission_strength": 0.2}), use_gpu=use_gpu)
    np.testing.assert_allclose(got, [0.7, 0.7, 0.7], rtol=0.04)


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
def test_mix_material_constant_fac_weights_closures(use_gpu):
    def make(r):
        a = r.create_material("principled", [0.6, 0.1, 0.1], {"roughness": 1.0, "specular_ior_level": 0.0})
        b = r.create_material("light", [0.0, 0.5, 1.0], {"intensity": 1.0, "two_sided": 1.0})
        return r.create_mix_material(a, b, 0.25)
    # 0.75 * red albedo + 0.25 * emission (the GPU bakes the constant-weight emission
    # into the Principled leaf, closure_mix.h lowerClosureTree)
    np.testing.assert_allclose(_wall(make, use_gpu=use_gpu), [0.45, 0.2, 0.325], rtol=0.04)


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
def test_nested_add_mix_tree_sums_all_closures(use_gpu):
    """A 3-deep constant-Fac tree: Add(Mix(red, blue, 0.25), Add(green, 0.1 white))."""
    def make(r):
        d = {"roughness": 1.0, "specular_ior_level": 0.0}
        red = r.create_material("principled", [0.6, 0.1, 0.1], d)
        blue = r.create_material("principled", [0.1, 0.1, 0.6], d)
        green = r.create_material("principled", [0.1, 0.3, 0.1], d)
        grey = r.create_material("principled", [0.1, 0.1, 0.1], d)
        tree = r.create_add_material(r.create_mix_material(red, blue, 0.25),
                                     r.create_add_material(green, grey))
        assert not r.get_material_backend_capabilities(tree)["gpu_approximate"]
        return tree
    want = 0.75 * np.array([0.6, 0.1, 0.1]) + 0.25 * np.array([0.1, 0.1, 0.6]) + [0.2, 0.4, 0.2]
    np.testing.assert_allclose(_wall(make, spp=128, use_gpu=use_gpu), want, rtol=0.05)


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
def test_emissive_glass_sphere_nee_on_off_agree(use_gpu):
    """An emissive analytic sphere with a BSDF now runs NEE from its own surface; the
    sphere's cone sampler is undefined there (NaN samples dropped -> dark). NEE on and
    off must give the same mean."""
    def centre(nee):
        r = create_renderer()
        _gpu_or_skip(r, use_gpu)
        r.set_seed(7)
        r.set_adaptive_sampling(False)
        r.set_background_color([0.0, 0.0, 0.0])
        r.set_light_nee(nee)
        g = r.create_material("principled", [1, 1, 1],
                              {"transmission_weight": 1.0, "roughness": 0.05, "ior": 1.45})
        e = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 0.6, "two_sided": 1.0})
        r.add_sphere([0, 0, 0], 1.0, r.create_add_material(g, e))
        r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 30.0, 1.0, 0.0, 4.0, 32, 32)
        img = np.asarray(r.render(128, 4, None, False), dtype=np.float32)
        return img[13:19, 13:19, 0].mean()
    on, off = centre(True), centre(False)
    assert off > 0.8, off            # emission 0.6 + the inner wall seen through the glass
    assert abs(on / off - 1.0) < 0.03, (on, off)


# ---- review round (lead, ffcbb3cb) ------------------------------------------------------
def test_disney_route_textured_fac_lowers_to_a_gpu_tree(monkeypatch):
    """The legacy Disney route (native Principled off) must lower too: Disney's static
    gpuApproximate flag used to block the tree, so the GPU rendered leaf 0 only
    (pkg293 mix_textured_fac-disney GPU/CPU 6.1x / 0.06x on the Fac=1 squares)."""
    import test_pkg293_gpu_lobe_programs as P
    eng = P._addon_engine(monkeypatch, False)
    r = create_renderer()
    rec = P._Recorder(r)
    spec = eng._shader_spec_from_node(P._graph("mix_textured_fac"), rec, None)
    mat = eng._create_material_from_shader_spec(spec, rec)
    assert [k for k, _ in rec.materials] == ['disney', 'disney'], rec.materials
    assert 'closure tree (#995)' in r.get_material_backend_capabilities(mat)['notes']
    assert not any('first shader' in m for m in eng._degradation_report().messages())


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
@pytest.mark.parametrize("fac", [0.0, 1.0])
def test_zero_weight_emissive_leaf_emits_nothing(use_gpu, fac):
    """Mix(fac, Add(emissive Principled, Diffuse), Diffuse): at fac 1 the emissive leaf
    has weight 0 (Cycles prunes the branch), so nothing may emit; the GPU used to keep
    leaf 0's own emission when the tree's summed emission was 0."""
    d = {"roughness": 1.0, "specular_ior_level": 0.0}
    def make(r):
        glow = r.create_material("principled", [0.3, 0.3, 0.3],
                                 dict(d, emission_color=[1.0, 1.0, 1.0], emission_strength=0.4))
        a = r.create_add_material(glow, r.create_material("principled", [0.2, 0.2, 0.2], d))
        return r.create_mix_material(a, r.create_material("principled", [0.6, 0.6, 0.6], d), fac)
    want = [0.6] * 3 if fac == 1.0 else [0.3 + 0.2 + 0.4] * 3
    np.testing.assert_allclose(_wall(make, spp=128, use_gpu=use_gpu), want, rtol=0.04)


def _uv_sphere_mesh(r, mat, nu=24, nv=12):
    def p(i, j):
        th, ph = np.pi * j / nv, 2 * np.pi * i / nu
        return [float(np.sin(th) * np.cos(ph)), float(np.cos(th)), float(np.sin(th) * np.sin(ph))]
    for j in range(nv):
        for i in range(nu):
            a, b, c, e = p(i, j), p(i + 1, j), p(i + 1, j + 1), p(i, j + 1)
            for t in ((a, b, c), (a, c, e)):
                if np.linalg.norm(np.cross(np.subtract(t[1], t[0]), np.subtract(t[2], t[0]))) > 1e-9:
                    r.add_triangle(t[0], t[1], t[2], mat)


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
def test_emissive_mesh_with_bsdf_self_nee_is_finite_and_consistent(use_gpu):
    """An emissive triangle mesh with a BSDF does NEE on its own triangles (zero-cosine /
    coplanar samples have pdf 0, never Inf/NaN): NEE on and off agree."""
    def centre(nee):
        r = create_renderer()
        _gpu_or_skip(r, use_gpu)
        r.set_seed(7)
        r.set_adaptive_sampling(False)
        r.set_background_color([0.0, 0.0, 0.0])
        r.set_light_nee(nee)
        g = r.create_material("principled", [1, 1, 1],
                              {"transmission_weight": 1.0, "roughness": 0.3, "ior": 1.45})
        e = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 0.6, "two_sided": 1.0})
        _uv_sphere_mesh(r, r.create_add_material(g, e))
        r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 30.0, 1.0, 0.0, 4.0, 32, 32)
        img = np.asarray(r.render(128, 4, None, False), dtype=np.float32)
        assert np.isfinite(img).all()
        return img[13:19, 13:19, 0].mean()
    on, off = centre(True), centre(False)
    assert off > 0.75, off
    assert abs(on / off - 1.0) < 0.03, (on, off)


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
def test_bumped_emissive_principled_keeps_emission_and_bsdf(use_gpu):
    """The Bump / Normal Map decorator forwards emission and hasBSDF (it dropped the
    emission on the CPU; the GPU unwraps to the inner material and kept it)."""
    def make(r):
        r.create_procedural_texture("h995", "checker", [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 2.0])
        return r.create_material("principled", [0.5, 0.5, 0.5],
                                 {"roughness": 1.0, "specular_ior_level": 0.0,
                                  "emission_color": [1.0, 1.0, 1.0], "emission_strength": 0.2,
                                  "bump_map_texture": "h995", "bump_strength": 1.0})
    np.testing.assert_allclose(_wall(make, use_gpu=use_gpu), [0.7, 0.7, 0.7], rtol=0.04)
