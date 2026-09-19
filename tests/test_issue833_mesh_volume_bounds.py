"""Issue #833 — a mesh with a volume material is lowered to its world AABB.

Minimum fix: the addon SAYS so instead of dropping the shape silently
(``[astroray volume] mesh '<name>' volume rendered as its bounding box`` plus an
APPROXIMATED degradation row), unless the mesh is exactly that box (the #807
cabinet cubes). Also covers the #828 item 3 degradation entry: more than 8
bounded media -> the GPU side table ignores the rest.

Pure addon logic (stub bpy, no engine, no Blender).
"""
import math
import os
import sys

import numpy as np
import pytest
from _batch_a_stub import load_addon

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import volume_export as vol  # noqa: E402


# --------------------------------------------------------------------------- #
# Duck-typed Blender objects
# --------------------------------------------------------------------------- #
class _Sock:
    def __init__(self, v, linked=False):
        self.default_value = v
        self.is_linked = linked
        self.links = []


class _Node:
    def __init__(self, type_, bl_idname, inputs):
        self.type = type_
        self.bl_idname = bl_idname
        self.inputs = dict(inputs)
        self.outputs = {}


class _Link:
    def __init__(self, n):
        self.from_node = n


class _Mat:
    def __init__(self):
        principled = _Node("VOLUME_PRINCIPLED", "ShaderNodeVolumePrincipled", {
            "Color": _Sock((0.8, 0.8, 0.8, 1.0)), "Density": _Sock(1.0)})
        vin = _Sock(None, linked=True)
        vin.links = [_Link(principled)]
        out = _Node("OUTPUT_MATERIAL", "ShaderNodeOutputMaterial",
                    {"Volume": vin, "Surface": _Sock(None)})
        out.is_active_output = True

        class NT:
            pass
        self.node_tree = NT()
        self.node_tree.nodes = [out, principled]


class _V:
    def __init__(self, co):
        self.co = co


class _MeshData:
    def __init__(self, verts):
        self.vertices = [_V(tuple(v)) for v in verts]
        self.materials = [_Mat()]


class _Obj:
    def __init__(self, name, verts):
        self.name = name
        self.type = "MESH"
        self.data = _MeshData(verts)
        vs = np.asarray(verts, dtype=float)
        mn, mx = vs.min(axis=0), vs.max(axis=0)
        self.bound_box = [(x, y, z) for x in (mn[0], mx[0])
                          for y in (mn[1], mx[1]) for z in (mn[2], mx[2])]


class _Inst:
    def __init__(self, m):
        self.matrix_world = m


class _Renderer:
    def __init__(self):
        self.media = []

    def set_volume_grid(self, *a, **k):  # presence gates the volume path
        self.media.append(("grid", a, k))

    def add_homogeneous_medium(self, mn, mx, *a, **k):
        self.media.append(("homog", list(mn), list(mx)))


IDENT = [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]


def _cube(s=1.0):
    return [(x, y, z) for x in (-s, s) for y in (-s, s) for z in (-s, s)]


def _icosphere():
    t = (1.0 + math.sqrt(5.0)) / 2.0
    v = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t),
         (0, -1, -t), (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    return [tuple(c / math.sqrt(1 + t * t) for c in p) for p in v]


def _rot_z(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]


def _aabb(obj, m):
    w = vol.mesh_world_vertices(obj, m)
    return w.min(axis=0).tolist(), w.max(axis=0).tolist()


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_axis_aligned_cube_is_exact():
    o = _Obj("Cube", _cube())
    w = vol.mesh_world_vertices(o, IDENT)
    assert vol.mesh_bounds_is_exact(w, *_aabb(o, IDENT))


def test_icosphere_and_rotated_cube_are_not_exact():
    ico = _Obj("Ico", _icosphere())
    assert not vol.mesh_bounds_is_exact(vol.mesh_world_vertices(ico, IDENT), *_aabb(ico, IDENT))
    cube = _Obj("Cube", _cube())
    m = _rot_z(30.0)
    assert not vol.mesh_bounds_is_exact(vol.mesh_world_vertices(cube, m), *_aabb(cube, m))


def test_tetrahedron_on_box_corners_is_not_exact():
    tet = [(-1, -1, -1), (1, 1, -1), (1, -1, 1), (-1, 1, 1)] * 2  # 4 corners, 8 verts
    o = _Obj("Tet", tet)
    assert not vol.mesh_bounds_is_exact(vol.mesh_world_vertices(o, IDENT), *_aabb(o, IDENT))


# --------------------------------------------------------------------------- #
# Addon lowering (stub bpy)
# --------------------------------------------------------------------------- #
def _export(monkeypatch, obj, m, suffix):
    addon = load_addon(monkeypatch, suffix)
    # mesh_world_aabb needs mathutils' Matrix @ Vector; use the numpy twin.
    monkeypatch.setattr(vol, "mesh_world_aabb", _aabb)
    monkeypatch.setitem(sys.modules, "volume_export", vol)
    engine = addon.CustomRaytracerRenderEngine()
    r = _Renderer()
    consumed = engine._try_export_volume(obj, _Inst(m), r)
    return engine, r, consumed


def test_icosphere_volume_reports_bounding_box(monkeypatch, capsys):
    engine, r, consumed = _export(monkeypatch, _Obj("Ico", _icosphere()), IDENT, "i833a")
    assert consumed and r.media and r.media[0][0] == "homog"
    out = capsys.readouterr().out
    assert "[astroray volume] mesh 'Ico' volume rendered as its bounding box" in out, out
    feats = [f for f, _ in engine._degradation_report().approximated]
    assert "Mesh volume shape" in feats, feats


def test_axis_aligned_cube_volume_is_silent(monkeypatch, capsys):
    engine, r, consumed = _export(monkeypatch, _Obj("Cab", _cube(0.5)), IDENT, "i833b")
    assert consumed and r.media
    out = capsys.readouterr().out
    assert "bounding box" not in out, out
    assert engine._degradation_report().is_empty()


def test_more_than_eight_media_reports_gpu_cap(monkeypatch, capsys):
    addon = load_addon(monkeypatch, "i828cap")
    monkeypatch.setattr(vol, "mesh_world_aabb", _aabb)
    monkeypatch.setitem(sys.modules, "volume_export", vol)
    engine = addon.CustomRaytracerRenderEngine()
    engine._vol_media_count = 0
    r = _Renderer()
    for k in range(vol.GPU_MAX_VOLUME_MEDIA):
        engine._try_export_volume(_Obj("C%d" % k, _cube(0.5)), _Inst(IDENT), r)
    assert "GPU renders only" not in capsys.readouterr().out
    engine._try_export_volume(_Obj("C9", _cube(0.5)), _Inst(IDENT), r)
    out = capsys.readouterr().out
    assert len(r.media) == vol.GPU_MAX_VOLUME_MEDIA + 1
    assert "more than 8 volume media: the GPU renders only the first 8" in out, out
    ign = [f for f, _ in engine._degradation_report().ignored]
    assert "Volume media beyond 8" in ign, ign
