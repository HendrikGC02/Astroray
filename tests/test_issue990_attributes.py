"""#990 — Attribute / Color Attribute / Object Info as per-corner shading attribute
layers, CPU and GPU.

Semantics: Cycles kernel/svm/attribute.h svm_node_attr_surface_eval (output
conversions), kernel/svm/geometry.h NODE_INFO_OB_*, scene/object.cpp + blender/
object.cpp (Object Info Random), Apache-2.0. Engine: include/astroray/
attribute_layers.h (barycentric corner interpolation), AttributeTexture (CPU),
gpu_attrTexel (GPU).
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import _bulk_geometry as BG
import shader_vm_compiler as C
from test_issue989_perhit_shading_inputs import Link, Node, Sock


def _base(node, out):
    return Sock('Base Color', [0.8, 0.8, 0.8], Link(node, out))


# ---- compiler -----------------------------------------------------------------
@pytest.mark.parametrize("node,out,key", [
    (Node('VERTEX_COLOR', layer_name='Col'), 'Color', 'color:Col|rgb'),
    (Node('VERTEX_COLOR', layer_name=''), 'Alpha', 'color:|alpha'),
    (Node('ATTRIBUTE', attribute_type='GEOMETRY', attribute_name='rough'), 'Factor', 'attr:rough|fac'),
    (Node('ATTRIBUTE', attribute_type='GEOMETRY', attribute_name='v'), 'Vector', 'attr:v|rgb'),
    (Node('OBJECT_INFO'), 'Random', 'objinfo:Random'),
    (Node('OBJECT_INFO'), 'Location', 'objinfo:Location'),
])
def test_attribute_nodes_compile_to_layer_inputs(node, out, key):
    compiled = C.compile_chain(_base(node, out))
    assert compiled is not None and compiled['num_tex'] == 1
    assert C.OP_LOAD_TEX in compiled['code_flat'][0::8]
    assert C.attribute_layer_key(compiled['inputs'][0], compiled['input_variants'][0]) == key


def _hue_chain(with_map_range):
    vc = Node('VERTEX_COLOR', layer_name='Col')
    oi = Node('OBJECT_INFO')
    hue_src = Link(oi, 'Random')
    if with_map_range:
        mr = Node('MAP_RANGE', data_type='FLOAT', interpolation_type='LINEAR', clamp=True,
                  inputs=[Sock('Value', 0.5, Link(oi, 'Random')), Sock('From Min', 0.0),
                          Sock('From Max', 1.0), Sock('To Min', 0.25), Sock('To Max', 0.75),
                          Sock('Steps', 4.0)])
        hue_src = Link(mr, 'Result')
    hs = Node('HUE_SAT', inputs=[Sock('Hue', 0.5, hue_src), Sock('Saturation', 1.0),
                                 Sock('Value', 1.0), Sock('Fac', 1.0),
                                 Sock('Color', [0.8] * 3, Link(vc, 'Color'))])
    return _base(hs, 'Color')


def test_attribute_chain_with_two_layers():
    """Color Attribute -> Hue/Saturation <- Object Info Random: two layer inputs."""
    compiled = C.compile_chain(_hue_chain(False))
    keys = sorted(C.attribute_layer_key(n, v) for n, v in
                  zip(compiled['inputs'], compiled['input_variants']))
    assert keys == ['color:Col|rgb', 'objinfo:Random']


@pytest.mark.xfail(strict=True, raises=C.VMCompileError,
                   reason="#993: the prod_attributes chain (+ Map Range) needs 10 VM slots "
                          "(VM_MAX_SLOTS = 8); op-VM capacity is lane N2's")
def test_prod_attributes_chain_fits_the_op_vm():
    C.compile_chain(_hue_chain(True))


def test_unsupported_attribute_forms_are_reported_not_silent():
    with pytest.raises(C.VMCompileError, match="OBJECT"):
        C.compile_chain(_base(Node('ATTRIBUTE', attribute_type='OBJECT', attribute_name='x'), 'Color'))
    with pytest.raises(C.VMCompileError, match="Object Info output"):
        C.compile_chain(_base(Node('OBJECT_INFO'), 'Bogus'))


# ---- export-side layer values (Cycles conversions) --------------------------------
def test_cycles_object_random_matches_cycles_hash():
    # hash_uint2(hash_string(name), 0) / 0xFFFFFFFF, values cross-checked against a
    # Cycles 5.2 render of Object Info > Random (emission) on objects of these names.
    assert BG.cycles_object_random('Inst0') == pytest.approx(0.2948239, abs=2e-7)
    assert BG.cycles_object_random('Inst1') == pytest.approx(0.1035135, abs=2e-7)
    assert BG.cycles_object_random('Inst2') == pytest.approx(0.8790834, abs=2e-7)


@pytest.mark.parametrize("comp,variant,expect", [
    (1, 'rgb', [0.4, 0.4, 0.4]), (1, 'fac', [0.4] * 3), (1, 'alpha', [1.0] * 3),
    (2, 'rgb', [0.4, 0.6, 0.0]), (2, 'fac', [0.4] * 3),
    (3, 'fac', [0.6] * 3), (4, 'rgb', [0.4, 0.6, 0.8]), (4, 'fac', [0.6] * 3),
    (4, 'alpha', [0.5] * 3),
])
def test_attribute_output_conversions(comp, variant, expect):
    vals = np.array([0.4, 0.6, 0.8, 0.5][:comp], np.float32).reshape(1, 1, comp)
    vals = np.repeat(vals, 3, axis=1)
    out = BG._attribute_output(vals, variant)
    np.testing.assert_allclose(out[0, 0], expect, atol=1e-6)


# ---- engine ---------------------------------------------------------------------
BACKENDS = [pytest.param(False, id="cpu"), pytest.param(True, id="gpu", marks=pytest.mark.gpu)]


def _renderer(use_gpu):
    pytest.importorskip("astroray")
    from base_helpers import create_renderer
    r = create_renderer()
    if use_gpu:
        import astroray
        if not (astroray.__features__.get("cuda", False) and getattr(r, "gpu_available", False)):
            pytest.skip("No CUDA GPU")
        r.set_use_gpu(True)
    r.set_seed(11)
    r.set_background_color([1.0, 1.0, 1.0])
    return r


def _render(r):
    from base_helpers import render_image, setup_camera
    setup_camera(r, look_from=[0, 0, 0], look_at=[0, 1, 0], vup=[0, 0, 1], vfov=40,
                 width=48, height=48)
    return render_image(r, samples=64, max_depth=4, apply_gamma=False)


def _wall(r, mat, corner_colours=None):
    """A 4x4 wall at y=3 facing the camera, two triangles; corner_colours (4,3) are
    the attribute layer 'attr:Col|rgb' at corners (-x-z, +x-z, +x+z, -x+z)."""
    q = np.array([[-2, 3, -2], [2, 3, -2], [2, 3, 2], [-2, 3, 2]], np.float32)
    tris = np.stack([q[[0, 1, 2]], q[[0, 2, 3]]])  # wound to face -y (the camera)
    kw = {}
    if corner_colours is not None:
        cc = np.asarray(corner_colours, np.float32)
        kw = {'attr_names': ['attr:Col|rgb'],
              'attrs': np.stack([cc[[0, 1, 2]], cc[[0, 2, 3]]])[None]}
    r.add_triangles_bulk(tris, np.array([mat, mat], np.int32), np.zeros(2, np.int32), 0,
                         np.zeros((0,), np.float32), [], np.zeros((0,), np.float32), **kw)


def _attr_material(r, key='attr:Col|rgb'):
    node = Node('ATTRIBUTE', attribute_type='GEOMETRY', attribute_name='Col')
    compiled = C.compile_chain(_base(node, 'Color'))
    # The addon passes the layer's Cycles not-found value (#1047).
    r.create_attribute_texture('_attr_col', key, C.attribute_layer_missing(key))
    r.create_program_texture('acol', 'UV')
    r.program_texture_add_input('acol', '_attr_col')
    r.set_program_texture_program('acol', compiled['num_tex'], compiled['out_slot'],
                                  compiled['code_flat'], compiled['consts_flat'],
                                  compiled['ramps_flat'])
    return r.create_material('principled', [0.8, 0.8, 0.8],
                             {'roughness': 1.0, 'specular_ior_level': 0.0,
                              'base_color_texture': 'acol'})


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_uniform_attribute_equals_constant_albedo(use_gpu):
    col = [0.2, 0.5, 0.8]
    r = _renderer(use_gpu)
    _wall(r, _attr_material(r), [col] * 4)
    attr = _render(r)
    r = _renderer(use_gpu)
    _wall(r, r.create_material('principled', col, {'roughness': 1.0, 'specular_ior_level': 0.0}))
    ref = _render(r)
    a, b = attr[20:28, 20:28].reshape(-1, 3).mean(0), ref[20:28, 20:28].reshape(-1, 3).mean(0)
    np.testing.assert_allclose(a, b, rtol=0.03)


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_attribute_interpolates_across_the_wall(use_gpu):
    """Red rises 0 -> 1 from the left edge to the right: linear in x across both
    triangles (the shared diagonal agrees), as Cycles' POINT-domain interpolation."""
    r = _renderer(use_gpu)
    _wall(r, _attr_material(r), [[0, 0.5, 0.5], [1, 0.5, 0.5], [1, 0.5, 0.5], [0, 0.5, 0.5]])
    img = _render(r)
    # Camera at the origin, wall at y=3 spans x in [-2, 2]; vfov 40 shows |x| <= 1.09.
    xs = [12, 24, 36]
    reds = [img[22:26, x - 2:x + 2, 0].mean() / img[22:26, x - 2:x + 2, 1].mean() * 0.5
            for x in xs]
    half = 3.0 * math.tan(math.radians(20.0))
    expect = [0.5 + (x + 0.5 - 24.0) / 24.0 * half / 4.0 for x in xs]
    np.testing.assert_allclose(reds, expect, atol=0.03)


def test_attribute_missing_reads_zero_on_cpu():
    r = _renderer(False)
    _wall(r, _attr_material(r))  # no layer uploaded
    img = _render(r)
    assert img[20:28, 20:28].mean() < 0.01


def test_attribute_layer_missing_value_follows_cycles():
    # Cycles svm_node_attr_surface_eval: a not-found Attribute node reads 0 except
    # its Alpha output (1); Color Attribute (svm/vertex_color.h) reads 0 throughout.
    assert C.attribute_layer_missing('attr:Col|alpha') == 1.0
    assert C.attribute_layer_missing('attr:Col|rgb') == 0.0
    assert C.attribute_layer_missing('attr:Col|fac') == 0.0
    assert C.attribute_layer_missing('color:Col|alpha') == 0.0
    assert C.attribute_layer_missing('objinfo:Alpha') == 0.0


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_missing_attribute_alpha_reads_one(use_gpu):
    """#1047 item 2: a wall that has no 'attr:Col|alpha' layer reads the Attribute
    alpha as 1 (Cycles) -> same albedo as a constant-1 material; rgb stays 0."""
    r = _renderer(use_gpu)
    _wall(r, _attr_material(r, 'attr:Col|alpha'))   # no layer uploaded
    alpha = _render(r)
    r = _renderer(use_gpu)
    _wall(r, r.create_material('principled', [1.0, 1.0, 1.0],
                               {'roughness': 1.0, 'specular_ior_level': 0.0}))
    ref = _render(r)
    a, b = alpha[20:28, 20:28].reshape(-1, 3).mean(0), ref[20:28, 20:28].reshape(-1, 3).mean(0)
    assert b.mean() > 0.3
    np.testing.assert_allclose(a, b, rtol=0.03)
    r = _renderer(use_gpu)
    _wall(r, _attr_material(r, 'attr:Col|rgb'))
    assert _render(r)[20:28, 20:28].mean() < 0.01


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_attribute_read_only_by_a_light_path_switch_child(use_gpu):
    """#1047 item 1: Mix(Is Camera Ray, plain, Color-Attribute-driven). The attribute
    layer is referenced ONLY by the switch child (materialised after the geometry
    walk); the GPU uploader's second pass must still give it corner slices, so the
    camera sees the attribute colour (CPU == GPU == a constant-colour wall)."""
    col = [0.2, 0.5, 0.8]
    r = _renderer(use_gpu)
    plain = r.create_material('principled', [0.8, 0.1, 0.1],
                              {'roughness': 1.0, 'specular_ior_level': 0.0})
    sw = r.create_light_path_mix(plain, _attr_material(r),
                                 C.LIGHT_PATH_OUTPUTS.index('Is Camera Ray'))
    _wall(r, sw, [col] * 4)
    img = _render(r)
    r = _renderer(use_gpu)
    _wall(r, r.create_material('principled', col, {'roughness': 1.0, 'specular_ior_level': 0.0}))
    ref = _render(r)
    a, b = img[20:28, 20:28].reshape(-1, 3).mean(0), ref[20:28, 20:28].reshape(-1, 3).mean(0)
    assert b.mean() > 0.2
    np.testing.assert_allclose(a, b, rtol=0.03)
