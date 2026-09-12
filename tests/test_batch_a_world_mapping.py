"""Batch A item 3 (#796) — world Mapping node: vector_type (POINT vs TEXTURE
inverse), Scale/Location warn-and-drop, linked-Rotation warning.

Stub-bpy tests of setup_world's MAPPING walk. A minimal numpy mathutils.Euler
(engine XYZ convention) is installed by _batch_a_stub so the TEXTURE inverse is
exercised for real.
"""
import math
import os
import tempfile
import types

import pytest

from _batch_a_stub import load_addon, RecordingRenderer


def _socket(value, linked=False):
    return types.SimpleNamespace(default_value=value, is_linked=linked)


def _make_world(mapping_node, hdri_path):
    env_node = types.SimpleNamespace(
        type='TEX_ENVIRONMENT',
        image=types.SimpleNamespace(filepath=hdri_path),
    )
    bg_node = types.SimpleNamespace(
        type='BACKGROUND',
        inputs={
            'Strength': _socket(1.0),
            'Color': _socket((1.0, 1.0, 1.0, 1.0)),
        },
    )
    node_tree = types.SimpleNamespace(nodes=[env_node, bg_node, mapping_node])
    return types.SimpleNamespace(node_tree=node_tree, cycles=None)


def _mapping_node(vector_type='POINT', rot=(0.0, 0.0, math.pi / 2),
                  scale=(1.0, 1.0, 1.0), loc=(0.0, 0.0, 0.0),
                  rot_linked=False):
    return types.SimpleNamespace(
        type='MAPPING',
        vector_type=vector_type,
        inputs={
            'Rotation': _socket(list(rot), linked=rot_linked),
            'Scale': _socket(list(scale)),
            'Location': _socket(list(loc)),
        },
    )


@pytest.fixture()
def hdri(tmp_path):
    # A tiny real file so setup_world's os.path.exists(hdri_path) passes and the
    # loader is invoked. Content is irrelevant (RecordingRenderer stubs load).
    p = tmp_path / "env.hdr"
    p.write_bytes(b"#?RADIANCE\n")
    return str(p)


def _rz_passed(renderer):
    assert renderer.env_map_calls, "load_environment_map was not called"
    args = renderer.env_map_calls[0][0]
    # load_environment_map(path, strength, rx, ry, rz, tr, tg, tb, blender_conv)
    return args[4]


def test_point_mapping_forward_rotation(monkeypatch, hdri):
    addon = load_addon(monkeypatch, "map_point")
    engine = addon.CustomRaytracerRenderEngine()
    r = RecordingRenderer()
    scene = types.SimpleNamespace(
        world=_make_world(_mapping_node('POINT'), hdri))
    engine.setup_world(scene, r)
    assert _rz_passed(r) == pytest.approx(math.pi / 2, abs=1e-5)


def test_texture_mapping_inverts_rotation(monkeypatch, hdri):
    addon = load_addon(monkeypatch, "map_texture")
    engine = addon.CustomRaytracerRenderEngine()
    r = RecordingRenderer()
    scene = types.SimpleNamespace(
        world=_make_world(_mapping_node('TEXTURE'), hdri))
    engine.setup_world(scene, r)
    # TEXTURE applies the inverse: a +90 deg Z rotation becomes -90 deg.
    assert _rz_passed(r) == pytest.approx(-math.pi / 2, abs=1e-5)


def _approx_details(engine):
    rep = engine._degradation_report()
    return " || ".join(d for (_f, d) in rep.approximated)


def test_scale_dropped_is_warned(monkeypatch, hdri):
    addon = load_addon(monkeypatch, "map_scale")
    engine = addon.CustomRaytracerRenderEngine()
    r = RecordingRenderer()
    scene = types.SimpleNamespace(
        world=_make_world(_mapping_node('POINT', scale=(2.0, 2.0, 2.0)), hdri))
    engine.setup_world(scene, r)
    assert 'Scale' in _approx_details(engine)


def test_location_dropped_is_warned(monkeypatch, hdri):
    addon = load_addon(monkeypatch, "map_loc")
    engine = addon.CustomRaytracerRenderEngine()
    r = RecordingRenderer()
    scene = types.SimpleNamespace(
        world=_make_world(_mapping_node('POINT', loc=(0.5, 0.0, 0.0)), hdri))
    engine.setup_world(scene, r)
    assert 'Location' in _approx_details(engine)


def test_linked_rotation_is_warned(monkeypatch, hdri):
    addon = load_addon(monkeypatch, "map_linkrot")
    engine = addon.CustomRaytracerRenderEngine()
    r = RecordingRenderer()
    scene = types.SimpleNamespace(
        world=_make_world(_mapping_node('POINT', rot_linked=True), hdri))
    engine.setup_world(scene, r)
    assert 'Rotation is linked' in _approx_details(engine)


def test_default_mapping_no_spurious_warning(monkeypatch, hdri):
    addon = load_addon(monkeypatch, "map_clean")
    engine = addon.CustomRaytracerRenderEngine()
    r = RecordingRenderer()
    scene = types.SimpleNamespace(
        world=_make_world(_mapping_node('POINT'), hdri))
    engine.setup_world(scene, r)
    details = _approx_details(engine)
    assert 'Scale' not in details and 'Location' not in details, details
