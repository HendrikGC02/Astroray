"""Issue #833 — a mesh with a volume material.

pkg296 re-pin (was: the icosphere is lowered to its AABB and reported): a mesh
that is not exactly its AABB now passes its world triangles as the medium
boundary, so a CLOSED mesh is silent on the CPU; a non-closed mesh is still
reported (``volume boundary is not closed`` + an APPROXIMATED row), and a GPU
render reports the bounding-box fallback until pkg296 Phase 2. The axis-aligned
box (the #807 cabinet cubes) stays an AABB medium with no boundary. Also covers
the #828 item 3 degradation entry: more than 8 bounded media -> the GPU side
table ignores the rest.

Pure addon logic (stub bpy, no engine, no Blender).
"""
import math
import os
import sys

import numpy as np
from _batch_a_stub import load_addon

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import volume_export as vol


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


class _Tri:
    def __init__(self, v):
        self.vertices = tuple(v)


class _MeshData:
    def __init__(self, verts, faces=()):
        self.vertices = [_V(tuple(v)) for v in verts]
        self.loop_triangles = [_Tri(f) for f in faces]
        self.materials = [_Mat()]


class _Obj:
    def __init__(self, name, verts, faces=()):
        self.name = name
        self.type = "MESH"
        self.data = _MeshData(verts, faces)
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
        self.media.append(("homog", list(mn), list(mx), k))


IDENT = [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]


def _cube(s=1.0):
    return [(x, y, z) for x in (-s, s) for y in (-s, s) for z in (-s, s)]


def _icosphere():
    t = (1.0 + math.sqrt(5.0)) / 2.0
    v = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t),
         (0, -1, -t), (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    return [tuple(c / math.sqrt(1 + t * t) for c in p) for p in v]


# Outward (counter-clockwise seen from outside) icosahedron faces.
ICO_FACES = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9),
             (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2),
             (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10),
             (8, 6, 7), (9, 8, 1)]


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


def test_mesh_is_closed():
    assert vol.mesh_is_closed(ICO_FACES)
    assert not vol.mesh_is_closed(ICO_FACES[1:])                    # a hole
    flipped = [ICO_FACES[0][::-1]] + ICO_FACES[1:]
    assert not vol.mesh_is_closed(flipped)                          # inconsistent winding


def test_negative_scale_flips_boundary_winding():
    o = _Obj("Ico", _icosphere(), ICO_FACES)
    mirror = [[-1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]
    v, idx = vol.mesh_world_triangles(o, mirror)
    n = np.cross(v[idx[:, 1]] - v[idx[:, 0]], v[idx[:, 2]] - v[idx[:, 0]])
    c = v[idx].mean(axis=1)
    assert ((n * c).sum(axis=1) > 0).all()                          # still outward


def test_closed_icosphere_volume_passes_boundary_silently(monkeypatch, capsys):
    # pkg296 re-pin: was "reports bounding box"; a closed mesh now carries its
    # triangles and renders as the mesh on the CPU.
    engine, r, consumed = _export(monkeypatch, _Obj("Ico", _icosphere(), ICO_FACES),
                                  IDENT, "i833a")
    assert consumed and r.media and r.media[0][0] == "homog"
    k = r.media[0][3]
    assert k["boundary_indices"].shape == (20, 3)
    assert k["boundary_vertices"].shape == (12, 3)
    out = capsys.readouterr().out
    assert "bounding box" not in out and "not closed" not in out, out
    assert engine._degradation_report().is_empty()
    engine._report_gpu_volume_cap("gpu")                            # GPU: AABB until Phase 2
    out = capsys.readouterr().out
    assert "mesh 'Ico' volume rendered as its bounding box on the GPU" in out, out


def test_open_mesh_volume_is_reported(monkeypatch, capsys):
    engine, r, consumed = _export(monkeypatch, _Obj("Open", _icosphere(), ICO_FACES[1:]),
                                  IDENT, "i833c")
    assert consumed and "boundary_indices" in r.media[0][3]
    out = capsys.readouterr().out
    assert "mesh 'Open' volume boundary is not closed" in out, out
    feats = [f for f, _ in engine._degradation_report().approximated]
    assert "Mesh volume shape" in feats, feats


def test_axis_aligned_cube_volume_is_silent(monkeypatch, capsys):
    engine, r, consumed = _export(monkeypatch, _Obj("Cab", _cube(0.5)), IDENT, "i833b")
    assert consumed and r.media
    assert "boundary_indices" not in r.media[0][3]                  # stays an AABB medium
    out = capsys.readouterr().out
    assert "bounding box" not in out, out
    assert engine._degradation_report().is_empty()


def test_more_than_eight_media_reports_gpu_cap_on_gpu_only(monkeypatch, capsys):
    addon = load_addon(monkeypatch, "i828cap")
    monkeypatch.setattr(vol, "mesh_world_aabb", _aabb)
    monkeypatch.setitem(sys.modules, "volume_export", vol)
    engine = addon.CustomRaytracerRenderEngine()
    engine._vol_media_count = 0
    r = _Renderer()
    for k in range(vol.GPU_MAX_VOLUME_MEDIA):
        engine._try_export_volume(_Obj(f"C{k}", _cube(0.5)), _Inst(IDENT), r)
    engine._report_gpu_volume_cap("gpu")
    assert "GPU renders only" not in capsys.readouterr().out      # exactly 8: fine
    engine._try_export_volume(_Obj("C9", _cube(0.5)), _Inst(IDENT), r)
    assert len(r.media) == vol.GPU_MAX_VOLUME_MEDIA + 1
    engine._report_gpu_volume_cap("cpu")                           # CPU honours all 9
    assert "GPU renders only" not in capsys.readouterr().out
    assert not engine._degradation_report().ignored
    engine._report_gpu_volume_cap("gpu")
    out = capsys.readouterr().out
    assert "9 volume media: the GPU renders only the first 8" in out, out
    ign = [f for f, _ in engine._degradation_report().ignored]
    assert "Volume media beyond 8" in ign, ign
