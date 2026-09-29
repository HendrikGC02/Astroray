"""Batch AM (am-nodes): shader-node gaps found by corpus v2 `v2_textures_opvm`.

#944  Image Texture reads raw sRGB bytes (Cycles decodes sRGB -> linear) and the
      Voronoi Color output rendered Distance (grey).
#945  affine Mapping -> Checker used the legacy 2-D UV transform, which never
      touches the 3-D point the procedural reads -> one flat cell.
#891  Mapping downstream of a non-affine warp (Cycles graph order) compiled as
      an affine leaf and was dropped; now an in-program op. A procedural (Noise)
      may drive the warp (OP_LOAD_TEX 1).

Engine-level: the real astroray Renderer is driven through the real addon
functions (bpy stubbed, #818 pattern) and sampled point-wise with
sample_named_texture(_mapped), the pkg242 transformed-p contract.
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import shader_vm_compiler as C
from test_pkg277_coordinate_program import (
    Link, Node, Sock, _checker_parity, _mapping_matrix)

astroray_real = pytest.importorskip("astroray")

C1 = (0.9, 0.85, 0.2)
C2 = (0.1, 0.15, 0.6)
MAPPING = ((0.0, 0.0, 0.0), (0.0, 0.0, math.radians(20.0)), (5.0, 3.0, 1.0))  # corpus card
GRID = [((i + 0.5) / 24, (j + 0.5) / 24) for i in range(24) for j in range(24)]


def _engine(monkeypatch):
    from test_issue818_procedural_opvm import _load_addon_stub
    addon = _load_addon_stub(monkeypatch)
    eng = addon.CustomRaytracerRenderEngine.__new__(addon.CustomRaytracerRenderEngine)
    eng._current_material_name = "M"
    eng._generated_textures_by_material = {}
    return eng


def _renderer():
    return astroray_real.Renderer()


def _srgb_to_linear(x):
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


# --------------------------------------------------------------------------- #
# #944 Image colour space
# --------------------------------------------------------------------------- #
class _Img:
    def __init__(self, colorspace):
        import types
        self.name = "cs_" + colorspace
        self.size = (2, 1)
        self.has_data = True
        self.filepath = ""
        self.packed_file = None
        self.is_float = False
        self.colorspace_settings = types.SimpleNamespace(name=colorspace)
        # bottom-to-top RGBA floats as Image.pixels returns them (raw file values)
        self.pixels = [0.5960784, 0.1411765, 0.7, 1.0, 0.25, 0.5, 0.9, 1.0]


@pytest.mark.parametrize("colorspace,decode", [("sRGB", True), ("Non-Color", False)])
def test_944_image_srgb_decoded(monkeypatch, colorspace, decode):
    eng, r = _engine(monkeypatch), _renderer()
    name = eng.load_blender_image(_Img(colorspace), r)
    got = np.array(r.sample_named_texture(name, 0.25, 0.5))  # left texel
    raw = np.array([0.5960784, 0.1411765, 0.7])
    want = _srgb_to_linear(raw) if decode else raw
    assert np.allclose(got, want, atol=1e-5), (got, want)


# --------------------------------------------------------------------------- #
# #944 Voronoi Color output
# --------------------------------------------------------------------------- #
def _voronoi(out_name):
    vnode = Node('TEX_VORONOI', name='Voronoi', feature='F1', distance='EUCLIDEAN',
               normalize=False, inputs=[Sock('Vector'), Sock('Scale', 5.0),
                                        Sock('Randomness', 1.0)])
    base = Sock('Base Color', [0.8, 0.8, 0.8], Link(vnode, out_name))
    return Node('BSDF_PRINCIPLED', inputs=[base])


def _voronoi_samples(monkeypatch, out_name):
    eng, r = _engine(monkeypatch), _renderer()
    _, tex = eng.get_base_color_texture(_voronoi(out_name), 'Base Color', r)
    return np.array([r.sample_named_texture(tex, u, v) for u, v in GRID])


def test_944_voronoi_color_output_is_per_cell_colour(monkeypatch):
    col = _voronoi_samples(monkeypatch, 'Color')
    grey = np.abs(col[:, 0] - col[:, 1]) + np.abs(col[:, 1] - col[:, 2])
    assert (grey > 0.02).mean() > 0.9           # per-cell hash colour, not Distance
    assert col.min() >= 0.0 and col.max() <= 1.0
    assert len({tuple(np.round(c, 4)) for c in col}) > 3   # several distinct cells


def test_944_voronoi_distance_output_stays_grey(monkeypatch):
    dist = _voronoi_samples(monkeypatch, 'Distance')
    assert np.allclose(dist[:, 0], dist[:, 1]) and np.allclose(dist[:, 1], dist[:, 2])


def test_944_opvm_voronoi_color_requests_color_variant():
    vnode = Node('TEX_VORONOI', inputs=[Sock('Vector')])
    ramp_in = Sock('Color1', [0, 0, 0], Link(vnode, 'Color'))
    mix = Node('MIX_RGB', blend_type='MIX', inputs=[Sock('Fac', 0.5), ramp_in,
                                                    Sock('Color2', [1, 1, 1])])
    compiled = C.compile_chain(Sock('Color', [0, 0, 0], Link(mix, 'Color')))
    assert compiled['input_variants'] == ['color']
    dist_in = Sock('Color1', [0, 0, 0], Link(vnode, 'Distance'))
    mix2 = Node('MIX_RGB', blend_type='MIX', inputs=[Sock('Fac', 0.5), dist_in,
                                                     Sock('Color2', [1, 1, 1])])
    compiled = C.compile_chain(Sock('Color', [0, 0, 0], Link(mix2, 'Color')))
    assert compiled['input_variants'] == [None]


# --------------------------------------------------------------------------- #
# #945 affine Mapping -> Checker
# --------------------------------------------------------------------------- #
def _checker(vector):
    return Node('TEX_CHECKER', name='Checker', inputs=[
        vector, Sock('Color1', list(C1) + [1.0]), Sock('Color2', list(C2) + [1.0]),
        Sock('Scale', 1.0)])


def _mapping_node(vec_link, mapping=MAPPING):
    loc, rot, scale = mapping
    return Node('MAPPING', name='Mapping', vector_type='POINT', inputs=[
        Sock('Vector', (0, 0, 0), vec_link), Sock('Location', loc),
        Sock('Rotation', rot), Sock('Scale', scale)])


def _checker_ref(p, scale=1.0):
    par = _checker_parity(np.asarray(p), scale)
    return np.where(par[..., None], np.array(C1), np.array(C2))


def _match_fraction(got, ref):
    return float(np.mean(np.all(np.abs(got - ref) < 1e-4, axis=-1)))


def test_945_affine_mapping_reaches_checker_point(monkeypatch):
    eng, r = _engine(monkeypatch), _renderer()
    uv = Node('TEX_COORD')
    m = _mapping_node(Link(uv, 'UV'))
    vec = Sock('Vector', (0, 0, 0), Link(m, 'Vector'))
    name = eng.load_procedural_texture(_checker(vec), r, vector_input=vec)
    got = np.array([r.sample_named_texture_mapped(name, u, v) for u, v in GRID])
    M = _mapping_matrix(*MAPPING)
    pts = np.array([[u, v, 0.0] for u, v in GRID]) @ M[:3, :3].T + M[:3, 3]
    ref = _checker_ref(pts)
    assert len({tuple(np.round(c, 3)) for c in got}) == 2, "flat colour (#945)"
    assert _match_fraction(got, ref) > 0.97


# --------------------------------------------------------------------------- #
# #891 Mapping after a non-affine warp
# --------------------------------------------------------------------------- #
def _sin_warp(coord, k=6.0):
    """UV -> SepXYZ -> x*k -> Sin -> CombXYZ (the pkg277 warp)."""
    sep = Node('SEPXYZ', inputs=[Sock('Vector', (0, 0, 0), Link(coord, 'UV'))])
    mul = Node('MATH', operation='MULTIPLY',
               inputs=[Sock('Value', 0.0, Link(sep, 'X')), Sock('Value_001', k)])
    sin = Node('MATH', operation='SINE',
               inputs=[Sock('Value', 0.0, Link(mul, 'Value')), Sock('Value_001', 0.5)])
    return Node('COMBXYZ', inputs=[Sock('X', 0.0, Link(sin, 'Value')),
                                   Sock('Y', 0.0, Link(sep, 'Y')),
                                   Sock('Z', 0.0, Link(sep, 'Z'))])


def test_891_mapping_is_not_a_leaf_after_warp():
    uv = Node('TEX_COORD')
    m = _mapping_node(Link(_sin_warp(uv), 'Vector'))
    compiled = C.compile_coord_chain(Sock('Vector', (0, 0, 0), Link(m, 'Vector')))
    assert compiled is not None                       # before: rejected/leaf
    ops = [compiled['code_flat'][i] for i in range(0, len(compiled['code_flat']), 8)]
    assert C.OP_VEC_ROTATE in ops and ops.count(C.OP_LOAD_TEX) == 1
    # Mapping BEFORE the warp is still the affine leaf (unchanged behaviour).
    sep_in = _mapping_node(Link(uv, 'UV'))
    assert C.compile_coord_chain(Sock('Vector', (0, 0, 0), Link(sep_in, 'Vector'))) is None


def test_891_mapping_after_sin_warp_matches_numpy(monkeypatch):
    eng, r = _engine(monkeypatch), _renderer()
    uv = Node('TEX_COORD')
    m = _mapping_node(Link(_sin_warp(uv), 'Vector'))
    vec = Sock('Vector', (0, 0, 0), Link(m, 'Vector'))
    name = eng.load_procedural_texture(_checker(vec), r, vector_input=vec)
    assert name.endswith('::coordprog')
    assert not eng._degradation_report().messages()
    got = np.array([r.sample_named_texture_mapped(name, u, v) for u, v in GRID])
    pts = np.array([[math.sin(6.0 * u), v, 0.0] for u, v in GRID])
    M = _mapping_matrix(*MAPPING)
    ref = _checker_ref(pts @ M[:3, :3].T + M[:3, 3])
    assert _match_fraction(got, ref) > 0.97
    # ... and it differs from applying the same Mapping BEFORE the warp.
    wrong = _checker_ref(np.array([[math.sin(6.0 * (M @ [u, v, 0, 1])[0]), (M @ [u, v, 0, 1])[1], 0.0]
                                   for u, v in GRID]))
    assert _match_fraction(got, wrong) < 0.9


def _noise_warp_card(uv):
    """The corpus card: UV + 0.35 * Noise(UV) -> Mapping -> Checker."""
    nz = Node('TEX_NOISE', name='Noise', inputs=[Sock('Vector', (0, 0, 0), Link(uv, 'UV')),
                                                 Sock('Scale', 3.0)])
    scl = Node('VECT_MATH', operation='SCALE', inputs=[
        Sock('Vector', (0, 0, 0), Link(nz, 'Color')), Sock('Vector_001', (0, 0, 0)),
        Sock('Vector_002', (0, 0, 0)), Sock('Scale', 0.35)])
    add = Node('VECT_MATH', operation='ADD', inputs=[
        Sock('Vector', (0, 0, 0), Link(uv, 'UV')), Sock('Vector_001', (0, 0, 0), Link(scl, 'Vector'))])
    return _mapping_node(Link(add, 'Vector')), nz


def test_891_noise_driven_warp_then_mapping_matches_numpy(monkeypatch):
    eng, r = _engine(monkeypatch), _renderer()
    uv = Node('TEX_COORD')
    m, nz = _noise_warp_card(uv)
    vec = Sock('Vector', (0, 0, 0), Link(m, 'Vector'))
    compiled = C.compile_coord_chain(vec)
    assert len(compiled['inputs']) == 1 and compiled['inputs'][0] is nz
    name = eng.load_procedural_texture(_checker(vec), r, vector_input=vec)
    assert name.endswith('::coordprog') and not eng._degradation_report().messages()
    got = np.array([r.sample_named_texture_mapped(name, u, v) for u, v in GRID])
    # numpy reference from the engine's own Noise (loaded unwrapped by the addon).
    noise_tex = next(n for n in eng._proc_tex_cache.values() if 'noise' in n)
    pts = []
    for u, v in GRID:
        n = np.array(r.sample_named_texture(noise_tex, u, v))
        pts.append(np.array([u, v, 0.0]) + 0.35 * n)
    M = _mapping_matrix(*MAPPING)
    ref = _checker_ref(np.array(pts) @ M[:3, :3].T + M[:3, 3])
    assert _match_fraction(got, ref) > 0.95
    # not the flat / unwarped fallback
    unwarped = _checker_ref(np.array([[u, v, 0.0] for u, v in GRID]) @ M[:3, :3].T + M[:3, 3])
    assert _match_fraction(got, unwarped) < 0.95


def test_891_warp_texture_with_other_coordinate_is_refused(monkeypatch):
    eng, r = _engine(monkeypatch), _renderer()
    uv = Node('TEX_COORD')
    m, nz = _noise_warp_card(uv)
    nz.inputs = type(nz.inputs)([Sock('Vector', (0, 0, 0), Link(uv, 'Object')),
                                 Sock('Scale', 3.0)])   # different base coordinate
    vec = Sock('Vector', (0, 0, 0), Link(m, 'Vector'))
    eng.load_procedural_texture(_checker(vec), r, vector_input=vec)
    msgs = " ".join(str(x) for x in eng._degradation_report().messages())
    assert "different coordinate" in msgs


# --------------------------------------------------------------------------- #
# Review items: colour management, Voronoi dimensions, stable cache key
# --------------------------------------------------------------------------- #
def test_944_float_image_not_converted_again(monkeypatch):
    # Blender 5.2 (probed): float buffers are already scene-linear, even sRGB-tagged.
    eng, r = _engine(monkeypatch), _renderer()
    img = _Img('sRGB')
    img.name, img.is_float = "f_srgb", True
    name = eng.load_blender_image(img, r)
    assert np.allclose(r.sample_named_texture(name, 0.25, 0.5),
                       [0.5960784, 0.1411765, 0.7], atol=1e-5)


@pytest.mark.parametrize("cs,degraded", [("Linear Rec.709", False), ("Raw", False),
                                         ("AgX Base sRGB", True)])
def test_944_byte_colourspace_passthrough_or_degrade(monkeypatch, cs, degraded):
    eng, r = _engine(monkeypatch), _renderer()
    img = _Img(cs)
    name = eng.load_blender_image(img, r)
    assert np.allclose(r.sample_named_texture(name, 0.25, 0.5),
                       [0.5960784, 0.1411765, 0.7], atol=1e-5)
    msgs = " ".join(str(m) for m in eng._degradation_report().messages())
    assert (("colourspace" in msgs) == degraded), msgs


def test_voronoi_non_3d_dimensions_are_degraded(monkeypatch):
    eng, r = _engine(monkeypatch), _renderer()
    node = _voronoi('Color')
    vnode = node.inputs[0].links[0].from_node
    vnode.voronoi_dimensions = '4D'
    eng.get_base_color_texture(node, 'Base Color', r)
    assert "voronoi_dimensions '4D'" in " ".join(
        str(m) for m in eng._degradation_report().messages())


def test_procedural_cache_key_is_never_id_based(monkeypatch):
    eng, r = _engine(monkeypatch), _renderer()
    uv = Node('TEX_COORD')

    def mk(scale):
        n = Node('TEX_CHECKER', name='', inputs=[Sock('Vector', (0, 0, 0), Link(uv, 'UV')),
                                                  Sock('Color1', list(C1) + [1.0]),
                                                  Sock('Color2', list(C2) + [1.0]),
                                                  Sock('Scale', scale)])
        n.name = ''
        return n
    a, b = mk(1.0), mk(4.0)
    ka = eng.load_procedural_texture(a, r, vector_input=a.inputs[0])
    kb = eng.load_procedural_texture(b, r, vector_input=b.inputs[0])
    assert ka != kb                      # different content -> different key
    assert "anon_" in ka and str(id(a)) not in ka
    assert eng.load_procedural_texture(mk(1.0), r, vector_input=a.inputs[0]) == ka  # stable
