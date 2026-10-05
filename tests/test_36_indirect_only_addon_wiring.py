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
