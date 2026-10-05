"""#36 -- the addon reads the collection's Indirect Only flag at export.

Blender keeps LayerCollection.indirect_only on the ORIGINAL object's view-layer base
(``Object.indirect_only_get(view_layer=)``; the evaluated copy reads False). convert_objects
flags every triangle of such an object with ``set_object_indirect_only``; a holdout object
(Cycles: ``!use_holdout && BASE_INDIRECT_ONLY``) and an ordinary object are not flagged.
Same mock-bpy pattern as test_blender_object_motion_blur_wiring.py.
"""

import types

import pytest

from test_blender_object_motion_blur_wiring import (
    IDENTITY_ROWS, MockMatrix4, _FakeInstance, _FakeMesh, _FakeObj,
    _load_blender_addon, _make_renderer_cls, _patch_geometry_stubs,
)


def _export(monkeypatch, indirect_only, is_holdout=False, original_api=True):
    calls, flagged, view_layers = [], [], []
    Base = _make_renderer_cls(calls)

    class Renderer(Base):
        n = 0

        def scene_object_count(self):
            return self.n

        def add_triangles_bulk(self, *args):
            super().add_triangles_bulk(*args)
            self.n += 1

        def set_object_indirect_only(self, oid, v):
            flagged.append((oid, v))

    addon = _load_blender_addon(monkeypatch, Renderer)
    _patch_geometry_stubs(addon, monkeypatch, motion_should_be_called=False)
    obj = _FakeObj('Ball', _FakeMesh())
    obj.is_holdout = is_holdout
    if original_api:
        def indirect_only_get(view_layer=None):
            view_layers.append(view_layer)
            return indirect_only
        obj.original = types.SimpleNamespace(indirect_only_get=indirect_only_get)
    vl = object()
    depsgraph = types.SimpleNamespace(
        object_instances=[_FakeInstance(obj, MockMatrix4(IDENTITY_ROWS))], view_layer=vl)
    addon.CustomRaytracerRenderEngine().convert_objects(depsgraph, Renderer(), {})
    return flagged, view_layers, vl


def test_indirect_only_collection_flags_the_object(monkeypatch):
    flagged, view_layers, vl = _export(monkeypatch, indirect_only=True)
    assert flagged == [(0, True)]
    assert view_layers == [vl]  # asked of the depsgraph's view layer


def test_ordinary_object_not_flagged(monkeypatch):
    flagged, _, _ = _export(monkeypatch, indirect_only=False)
    assert flagged == []


def test_holdout_wins_over_indirect_only(monkeypatch):
    flagged, _, _ = _export(monkeypatch, indirect_only=True, is_holdout=True)
    assert flagged == []


def test_missing_blender_api_means_not_indirect_only(monkeypatch):
    flagged, _, _ = _export(monkeypatch, indirect_only=True, original_api=False)
    assert flagged == []


def _two_instances(monkeypatch, indirect_only):
    """_register_instanced_groups over two dupli instances of one mesh object."""
    added = []

    class Renderer(_make_renderer_cls([])):
        def register_mesh_bulk(self, *args):
            return 7

        def add_instance(self, mesh_id, matrix):
            added.append(mesh_id)
            return len(added) - 1

    addon = _load_blender_addon(monkeypatch, Renderer)
    monkeypatch.setattr(addon, "BULK_GEOMETRY_UPLOAD", True)
    monkeypatch.setattr(addon, "mathutils", types.SimpleNamespace(
        Matrix=types.SimpleNamespace(Identity=lambda n: n)))
    monkeypatch.setattr(addon, "mesh_to_bulk_arrays",
                        lambda *a, **k: (None, None, None, None, [], None))
    obj = _FakeObj('Ball', _FakeMesh())
    obj.original = types.SimpleNamespace(indirect_only_get=lambda view_layer=None: indirect_only)
    insts = [_FakeInstance(obj, MockMatrix4(IDENTITY_ROWS), is_instance=True) for _ in range(2)]
    depsgraph = types.SimpleNamespace(
        object_instances=insts, view_layer=object(), mode='RENDER',
        scene=types.SimpleNamespace(custom_raytracer=object()))
    engine = addon.CustomRaytracerRenderEngine()
    monkeypatch.setattr(engine, "_render_will_use_gpu", lambda s, r: True)
    return engine._register_instanced_groups(depsgraph, Renderer(), {}, True), added


def test_instanced_objects_are_instanced_by_default(monkeypatch):
    skip, added = _two_instances(monkeypatch, indirect_only=False)
    assert skip == {0, 1} and added == [7, 7]  # scene is non-vacuous


def test_indirect_only_object_is_flattened_not_instanced(monkeypatch):
    """The shared BLAS has no per-instance indirect-only flag: such an object takes the
    flatten path (where convert_objects sets the flag), not a two-level instance."""
    skip, added = _two_instances(monkeypatch, indirect_only=True)
    assert skip == set() and added == []


def _warnings(monkeypatch, integrator):
    Base = _make_renderer_cls([])

    class Renderer(Base):
        def scene_object_count(self):
            return 0

        def set_object_indirect_only(self, oid, v):
            pass

    addon = _load_blender_addon(monkeypatch, Renderer)
    _patch_geometry_stubs(addon, monkeypatch, motion_should_be_called=False)
    obj = _FakeObj('Ball', _FakeMesh())
    obj.is_holdout = False
    obj.original = types.SimpleNamespace(indirect_only_get=lambda view_layer=None: True)
    depsgraph = types.SimpleNamespace(
        object_instances=[_FakeInstance(obj, MockMatrix4(IDENTITY_ROWS))], view_layer=object(),
        scene=types.SimpleNamespace(custom_raytracer=types.SimpleNamespace(integrator_type=integrator)))
    engine = addon.CustomRaytracerRenderEngine()

    class R2(Renderer):
        n = 0

        def scene_object_count(self):
            return self.n

        def add_triangles_bulk(self, *args):
            self.n += 1

    engine.convert_objects(depsgraph, R2(), {})
    return engine._degradation_report().messages()


@pytest.mark.parametrize("integrator", ["restir_di", "multiwavelength_path_tracer"])
def test_integrators_ignoring_indirect_only_are_reported(monkeypatch, integrator):
    msgs = _warnings(monkeypatch, integrator)
    assert any("INDIRECT_ONLY" in m and integrator in m for m in msgs), msgs


def test_path_tracer_honours_indirect_only_no_warning(monkeypatch):
    assert not any("INDIRECT_ONLY" in m for m in _warnings(monkeypatch, "path_tracer"))
