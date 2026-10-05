"""pkg322 -- Geometry > Pointiness as a per-vertex attribute layer ('geom:Pointiness').

Port of Cycles `attr_create_pointiness` (intern/cycles/blender/mesh.cpp, Apache-2.0);
blender_addon/pointiness.py. The value rides the #990 per-corner layer, so the engine
needs no change: CPU `AttributeTexture`, GPU `gpu_attrTexel`.

The Cycles gate bakes Geometry > Pointiness through an Emission shader into a float
POINT colour attribute with Cycles 5.2 (headless) and compares per vertex.
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

ADDON = os.path.join(os.path.dirname(__file__), "..", "blender_addon")
sys.path.insert(0, ADDON)
import _bulk_geometry as BG
import pointiness as PT
import shader_vm_compiler as C
from test_issue989_perhit_shading_inputs import Link, Node, Sock

BLENDER = Path(os.environ.get("BLENDER_EXE", r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"))


# ---- host-side value -------------------------------------------------------------
def _grid(n=5):
    xs = np.linspace(-1, 1, n)
    co = np.array([(x, y, 0.0) for y in xs for x in xs], np.float32)
    edges = []
    for j in range(n):
        for i in range(n):
            v = j * n + i
            if i + 1 < n:
                edges.append((v, v + 1))
            if j + 1 < n:
                edges.append((v, v + n))
    return co, np.array([[0, 0, 1]] * len(co), np.float32), np.array(edges)


def test_flat_plane_interior_is_one_half():
    # Cycles: the unit edge directions around an interior flat vertex cancel, so
    # acos(dot(n, 0)) / pi = 0.5 (and the blur keeps 0.5).
    co, nrm, edges = _grid()
    p = PT.compute_pointiness(co, nrm, edges)
    inner = [v for v in range(25) if 0 < v % 5 < 4 and 0 < v // 5 < 4]
    np.testing.assert_allclose(p[inner], 0.5, atol=1e-6)


def test_colocated_vertices_are_welded():
    """Two quads sharing an edge but with the shared edge's vertices duplicated (a split
    mesh): the welded result equals the connected mesh and duplicates share one value."""
    co = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [2, 0, 0.5], [2, 1, 0.5]],
                  np.float32)
    nrm = np.tile(np.array([0, 0, 1], np.float32), (6, 1))
    joined = PT.compute_pointiness(co, nrm, np.array(
        [(0, 1), (1, 2), (2, 3), (3, 0), (1, 4), (4, 5), (5, 2)]))
    co_s = np.concatenate([co, co[[1, 2]]])           # duplicates of verts 1, 2 (idx 6, 7)
    nrm_s = np.tile(np.array([0, 0, 1], np.float32), (8, 1))
    split = PT.compute_pointiness(co_s, nrm_s, np.array(
        [(0, 1), (1, 2), (2, 3), (3, 0), (6, 4), (4, 5), (5, 7)]))
    np.testing.assert_allclose(split[:6], joined, atol=1e-6)
    assert split[6] == split[1] and split[7] == split[2]


def test_unwelded_would_differ():
    # The weld maps the duplicate (2) onto the first colocated vertex (1) and they share a value.
    co = np.array([[0, 0, 0], [1, 0, 0], [1, 0, 0], [2, 0.5, 0]], np.float32)
    nrm = np.tile(np.array([0, 0, 1], np.float32), (4, 1))
    p = PT.compute_pointiness(co, nrm, np.array([(0, 1), (2, 3)]))
    assert p[1] == p[2]
    assert list(PT._weld_index(co)) == [0, 1, 1, 3]  # the higher index points at the first


# ---- compiler -------------------------------------------------------------------
def test_pointiness_compiles_to_a_layer_input_not_a_per_hit_op():
    geo = Node('NEW_GEOMETRY')
    compiled = C.compile_chain(Sock('Roughness', 0.5, Link(geo, 'Pointiness'), type='VALUE'),
                               allow_leaf=True)
    assert compiled is not None and compiled['num_tex'] == 1 and not compiled['per_hit']
    assert C.OP_LOAD_TEX in compiled['code_flat'][0::8] and C.OP_SHADING not in compiled['code_flat'][0::8]
    node, variant = compiled['inputs'][0], compiled['input_variants'][0]
    assert node.type in C.ATTRIBUTE_NODE_TYPES
    assert C.attribute_layer_key(node, variant) == 'geom:Pointiness'
    assert C.attribute_layer_missing('geom:Pointiness') == 0.0


def test_other_geometry_outputs_still_raise():
    geo = Node('NEW_GEOMETRY')
    with pytest.raises(C.VMCompileError, match="Parametric"):
        C.compile_chain(Sock('Roughness', 0.5, Link(geo, 'Parametric'), type='VALUE'))


# ---- export fill (fake mesh) -----------------------------------------------------------
class _Coll:
    def __init__(self, data):
        self._d = data

    def __len__(self):
        return len(next(iter(self._d.values())))

    def foreach_get(self, name, out):
        out[:] = np.asarray(self._d[name], out.dtype).ravel()


class _FakeMesh:
    """Two triangles of a bent quad, in loop-triangle order."""
    def __init__(self):
        co = np.array([[0, 0, 0], [1, 0, 0.3], [1, 1, 0], [0, 1, 0.3]], np.float32)
        self.vertices = _Coll({'co': co})
        self.edges = _Coll({'vertices': np.array([(0, 1), (1, 2), (2, 3), (3, 0), (0, 2)])})
        self.vertex_normals = _Coll({'vector': np.tile(np.array([0, 0, 1], np.float32), (4, 1))})
        self.loop_triangles = _Coll({'vertices': np.array([[0, 1, 2], [0, 2, 3]]),
                                     'loops': np.array([[0, 1, 2], [0, 2, 3]]),
                                     'polygon_index': np.array([0, 0]),
                                     'material_index': np.array([0, 0])})


def test_mesh_attribute_layers_fills_pointiness_per_corner():
    mesh = _FakeMesh()
    names, attrs, notes = BG.mesh_attribute_layers(mesh, None, np.eye(4), {'geom:Pointiness'}, [])
    assert names == ['geom:Pointiness'] and not notes and attrs.shape == (1, 2, 3, 3)
    pv = PT.mesh_pointiness(mesh)
    assert pv.std() > 1e-3  # the bent quad is not a constant
    for t, tri in enumerate(([0, 1, 2], [0, 2, 3])):
        for c, v in enumerate(tri):
            np.testing.assert_allclose(attrs[0, t, c], [pv[v]] * 3, atol=1e-7)


# ---- Cycles per-vertex gate (Blender 5.2 headless) ----------------------------------------
_BAKE = textwrap.dedent('''
    import bpy, bmesh, sys, json, numpy as np, mathutils
    addon, out = sys.argv[sys.argv.index('--') + 1:][:2]
    sys.path.insert(0, addon)
    import pointiness

    def make(kind):
        me = bpy.data.meshes.new(kind)
        bm = bmesh.new()
        if kind == 'bevel_cube':
            bmesh.ops.create_cube(bm, size=2.0)
            bmesh.ops.bevel(bm, geom=list(bm.edges), offset=0.25, segments=2, affect='EDGES')
        elif kind == 'dent_sphere':
            bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16, radius=1.0)
            for v in bm.verts:
                d = (v.co - mathutils.Vector((0.7, 0.0, 0.7))).length
                v.co *= 1.0 - 0.25 * np.exp(-(d / 0.5) ** 2)
        elif kind == 'fold_plane':
            bmesh.ops.create_grid(bm, x_segments=10, y_segments=10, size=1.0)
            for v in bm.verts:
                v.co.z = 0.5 * abs(v.co.x) + 0.1 * np.sin(3 * v.co.y)
        elif kind == 'split_cube':   # every edge split: 24 verts, colocated duplicates
            bmesh.ops.create_cube(bm, size=2.0)
            bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=1, use_grid_fill=True)
            for v in bm.verts:
                v.co += v.co.normalized() * 0.05 * np.sin(5 * v.co.x + 3 * v.co.z)
            bmesh.ops.split_edges(bm, edges=list(bm.edges))
        bm.to_mesh(me)
        bm.free()
        for p in me.polygons:
            p.use_smooth = True
        return me

    res = {}
    for kind in ('bevel_cube', 'dent_sphere', 'fold_plane', 'split_cube'):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        sc = bpy.context.scene
        sc.render.engine = 'CYCLES'
        sc.cycles.device = 'CPU'
        sc.cycles.samples = 1
        me = make(kind)
        ob = bpy.data.objects.new(kind, me)
        sc.collection.objects.link(ob)
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        mat = bpy.data.materials.new('m')
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()
        g = nt.nodes.new('ShaderNodeNewGeometry')
        e = nt.nodes.new('ShaderNodeEmission')
        o = nt.nodes.new('ShaderNodeOutputMaterial')
        nt.links.new(g.outputs['Pointiness'], e.inputs['Color'])
        nt.links.new(e.outputs[0], o.inputs[0])
        me.materials.append(mat)
        me.color_attributes.new('bake', 'FLOAT_COLOR', 'POINT')
        me.color_attributes.active_color = me.color_attributes['bake']
        sc.render.bake.target = 'VERTEX_COLORS'
        bpy.ops.object.bake(type='EMIT')
        ca = me.color_attributes['bake']
        buf = np.empty(len(ca.data) * 4, np.float32)
        ca.data.foreach_get('color', buf)
        ref = buf.reshape(-1, 4)[:, 0]
        mine = pointiness.mesh_pointiness(me)
        res[kind] = {'n': len(ref), 'max_abs': float(np.abs(ref - mine).max()),
                     'spread': float(ref.max() - ref.min())}
    json.dump(res, open(out, 'w'))
''')


@pytest.mark.skipif(not BLENDER.is_file(), reason="needs Blender 5.2 (BLENDER_EXE)")
def test_pointiness_matches_a_cycles_bake_per_vertex(tmp_path):
    script, out = tmp_path / "bake.py", tmp_path / "res.json"
    script.write_text(_BAKE, encoding="utf-8")
    run = subprocess.run([str(BLENDER), "-b", "--factory-startup", "--python", str(script), "--",
                          str(Path(ADDON).resolve()), str(out)],
                         capture_output=True, text=True, timeout=300, check=False,
                         env=dict(os.environ, OMP_NUM_THREADS="8"))
    assert out.is_file(), (run.stdout + run.stderr)[-1500:]
    res = json.loads(out.read_text())
    for kind, r in res.items():
        assert r['spread'] > 0.02, f"{kind}: vacuous (Cycles Pointiness is constant)"
        assert r['max_abs'] < 1e-3, f"{kind}: max |astroray - cycles| = {r['max_abs']:.2e}"


# ---- engine: Pointiness -> Color Ramp -> Base Color, CPU and GPU -------------------------------
BACKENDS = [pytest.param(False, id="cpu"), pytest.param(True, id="gpu", marks=pytest.mark.gpu)]


class _Ramp:
    @staticmethod
    def evaluate(f):
        return (f, 0.5 * f, 1.0 - f, 1.0)


def _ramp_chain():
    geo = Node('NEW_GEOMETRY')
    ramp = Node('VALTORGB', inputs=[Sock('Fac', 0.0, Link(geo, 'Pointiness'))], color_ramp=_Ramp())
    return Sock('Base Color', [0.5, 0.5, 0.5], Link(ramp, 'Color'))


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


def _wall(r, mat, layer=None):
    q = np.array([[-2, 3, -2], [2, 3, -2], [2, 3, 2], [-2, 3, 2]], np.float32)
    tris = np.stack([q[[0, 1, 2]], q[[0, 2, 3]]])
    kw = {}
    if layer is not None:
        cc = np.repeat(np.asarray(layer, np.float32)[:, None], 3, axis=1)
        kw = {'attr_names': ['geom:Pointiness'],
              'attrs': np.stack([cc[[0, 1, 2]], cc[[0, 2, 3]]])[None]}
    r.add_triangles_bulk(tris, np.array([mat, mat], np.int32), np.zeros(2, np.int32), 0,
                         np.zeros((0,), np.float32), [], np.zeros((0,), np.float32), **kw)


def _render(r):
    from base_helpers import render_image, setup_camera
    setup_camera(r, look_from=[0, 0, 0], look_at=[0, 1, 0], vup=[0, 0, 1], vfov=40,
                 width=48, height=48)
    return render_image(r, samples=64, max_depth=4, apply_gamma=False)


def _pointiness_material(r):
    compiled = C.compile_chain(_ramp_chain())
    key = C.attribute_layer_key(compiled['inputs'][0], compiled['input_variants'][0])
    r.create_attribute_texture('_attr_pt', key, C.attribute_layer_missing(key))
    r.create_program_texture('ptex', 'UV')
    r.program_texture_add_input('ptex', '_attr_pt')
    r.set_program_texture_program('ptex', compiled['num_tex'], compiled['out_slot'],
                                  compiled['code_flat'], compiled['consts_flat'],
                                  compiled['ramps_flat'])
    return r.create_material('principled', [0.8, 0.8, 0.8],
                             {'roughness': 1.0, 'specular_ior_level': 0.0,
                              'base_color_texture': 'ptex'})


def _const(r, col):
    return r.create_material('principled', list(col), {'roughness': 1.0, 'specular_ior_level': 0.0})


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_pointiness_ramp_matches_constant_albedo(use_gpu):
    """Uniform layer 0.3 and a left-right gradient 0.2 -> 0.8 (centre 0.5): the ramped
    Base Color equals a constant-albedo wall of ramp(value) within 3 %."""
    for layer, probe, value in (([0.3] * 4, (20, 28, 20, 28), 0.3),
                                ([0.2, 0.8, 0.8, 0.2], (22, 26, 22, 26), 0.5)):
        r = _renderer(use_gpu)
        _wall(r, _pointiness_material(r), layer)
        img = _render(r)
        r = _renderer(use_gpu)
        _wall(r, _const(r, _Ramp.evaluate(value)[:3]))
        ref = _render(r)
        y0, y1, x0, x1 = probe
        a = img[y0:y1, x0:x1].reshape(-1, 3).mean(0)
        b = ref[y0:y1, x0:x1].reshape(-1, 3).mean(0)
        np.testing.assert_allclose(a, b, rtol=0.03)
