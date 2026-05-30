"""pkg117 — non-MESH geometry (curve/text/metaball/surface) renders via to_mesh().

`convert_objects` used to `continue` on anything that wasn't a MESH, so curves,
text, metaballs and surfaces silently didn't render. pkg117 routes those types
through the evaluated object's `to_mesh()` (and frees it with `to_mesh_clear()`),
mirroring Cycles `intern/cycles/blender/mesh.cpp`. Plain meshes are unchanged.

These are bpy-free unit tests: they mock the Blender object/mesh the same way the
other addon tests do and assert the routing + lifecycle, not pixels (the visual
parity is an RTX `/verify` item per the spec).
"""

from __future__ import annotations

import types

from test_blender_uv_plumbing import _load_blender_addon
from test_blender_named_uv_layers import _Matrix, _Mesh, _MeshRenderer, _UVLayers


def _make_mesh():
    return _Mesh(_UVLayers([], active=None))


class _NonMeshObject:
    """A curve/text/metaball/surface-style object: no mesh in `.data`, geometry
    is produced on demand by `to_mesh()` and must be released by `to_mesh_clear()`."""

    name = "Curvy"
    material_slots = []
    pass_index = 0
    matrix_world = _Matrix()
    data = None  # curves/text/etc. do NOT carry a Mesh in .data

    def __init__(self, obj_type, mesh):
        self.type = obj_type
        self._mesh = mesh
        self.to_mesh_calls = 0
        self.to_mesh_clear_calls = 0

    def to_mesh(self):
        self.to_mesh_calls += 1
        return self._mesh

    def to_mesh_clear(self):
        self.to_mesh_clear_calls += 1


class _PlainMeshObject:
    type = "MESH"
    name = "Plain"
    material_slots = []
    pass_index = 0
    matrix_world = _Matrix()

    def __init__(self, mesh):
        self.data = mesh
        self.to_mesh_calls = 0
        self.to_mesh_clear_calls = 0

    def to_mesh(self):
        self.to_mesh_calls += 1
        return self.data

    def to_mesh_clear(self):
        self.to_mesh_clear_calls += 1


def _depsgraph_for(obj):
    return types.SimpleNamespace(object_instances=[
        types.SimpleNamespace(object=obj, matrix_world=obj.matrix_world)
    ])


def _convert(monkeypatch, obj):
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _MeshRenderer()
    engine.convert_objects(_depsgraph_for(obj), renderer, {})
    return renderer


def test_curve_routes_through_to_mesh_and_clears(monkeypatch):
    obj = _NonMeshObject("CURVE", _make_mesh())
    renderer = _convert(monkeypatch, obj)
    # The curve's to_mesh() geometry was uploaded …
    assert len(renderer.triangles) == 1, "curve to_mesh() triangle was not uploaded"
    assert obj.to_mesh_calls == 1
    # … and the temporary mesh was freed.
    assert obj.to_mesh_clear_calls == 1, "to_mesh_clear() was not called (mesh leak)"


def test_text_and_metaball_and_surface_render(monkeypatch):
    for obj_type in ("FONT", "META", "SURFACE"):
        obj = _NonMeshObject(obj_type, _make_mesh())
        renderer = _convert(monkeypatch, obj)
        assert len(renderer.triangles) == 1, f"{obj_type} did not render via to_mesh()"
        assert obj.to_mesh_clear_calls == 1, f"{obj_type} leaked its temporary mesh"


def test_none_to_mesh_is_skipped_gracefully(monkeypatch):
    # Non-basis metaball members / empty curves return None from to_mesh().
    obj = _NonMeshObject("META", None)
    renderer = _convert(monkeypatch, obj)
    assert renderer.triangles == [], "a None to_mesh() should produce no geometry"
    # Nothing was created, so nothing should be cleared.
    assert obj.to_mesh_clear_calls == 0


def test_plain_mesh_does_not_call_to_mesh(monkeypatch):
    # Regression: meshes must use obj.data directly and never touch the temp-mesh
    # lifecycle (calling to_mesh_clear on a real mesh would corrupt it).
    obj = _PlainMeshObject(_make_mesh())
    renderer = _convert(monkeypatch, obj)
    assert len(renderer.triangles) == 1
    assert obj.to_mesh_calls == 0, "plain MESH should not call to_mesh()"
    assert obj.to_mesh_clear_calls == 0, "plain MESH must not be cleared"
