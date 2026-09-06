"""pkg219a — Coordinate + Mapping unification.

Full 3-D Blender Mapping matrix (incl. X/Y rotation, Z loc/scale) + real
Generated/Object/Camera/Window/Reflection/Normal TexCoord modes, wired into the
existing texture special-case. Reference: Cycles svm/mapping_util.h svm_mapping
POINT (Apache-2.0), out = location + Rotate(euler_XYZ)*(scale*vector).

These are addon-level tests (no engine build needed). A native CPU/GPU render
parity test lives in test_pkg219a_mapping_render.py.
"""

import math

import numpy as np
from test_blender_uv_plumbing import (
    _FakeImage,
    _load_blender_addon,
    _Node,
    _RecordingRenderer,
    _Socket,
)

# ---------------------------------------------------------------------------
# 1. _compose_mapping_matrix — matches Blender POINT mapping exactly
# ---------------------------------------------------------------------------

def _cls(monkeypatch):
    return _load_blender_addon(monkeypatch).CustomRaytracerRenderEngine


def test_compose_identity(monkeypatch):
    cls = _cls(monkeypatch)
    M = cls._compose_mapping_matrix((0, 0, 0), (0, 0, 0), (1, 1, 1))
    assert np.allclose(M, np.identity(4))


def test_compose_scale(monkeypatch):
    cls = _cls(monkeypatch)
    M = cls._compose_mapping_matrix((0, 0, 0), (0, 0, 0), (2, 3, 4))
    assert np.allclose(np.diag(M)[:3], [2, 3, 4])
    # A point (1,1,1) scales to (2,3,4).
    p = M @ np.array([1, 1, 1, 1.0])
    assert np.allclose(p[:3], [2, 3, 4])


def test_compose_translation(monkeypatch):
    cls = _cls(monkeypatch)
    M = cls._compose_mapping_matrix((0.5, -0.25, 1.0), (0, 0, 0), (1, 1, 1))
    p = M @ np.array([0, 0, 0, 1.0])
    assert np.allclose(p[:3], [0.5, -0.25, 1.0])


def test_compose_z_rotation_90(monkeypatch):
    cls = _cls(monkeypatch)
    M = cls._compose_mapping_matrix((0, 0, 0), (0, 0, math.pi / 2), (1, 1, 1))
    # Rz(90): x-axis -> +y.
    p = M @ np.array([1, 0, 0, 1.0])
    assert np.allclose(p[:3], [0, 1, 0], atol=1e-6)


def test_compose_x_rotation_90(monkeypatch):
    """X rotation is the axis the old 2-D transform DROPPED — pkg219a keeps it.
    Rx(90): y-axis -> +z."""
    cls = _cls(monkeypatch)
    M = cls._compose_mapping_matrix((0, 0, 0), (math.pi / 2, 0, 0), (1, 1, 1))
    p = M @ np.array([0, 1, 0, 1.0])
    assert np.allclose(p[:3], [0, 0, 1], atol=1e-6)


def test_compose_order_scale_then_rotate_then_translate(monkeypatch):
    """Cycles POINT: out = loc + R*(scale*v). Verify composition order."""
    cls = _cls(monkeypatch)
    loc, rot, scl = (1.0, 2.0, 3.0), (0.0, 0.0, math.pi / 2), (2.0, 2.0, 2.0)
    M = cls._compose_mapping_matrix(loc, rot, scl)
    v = np.array([1.0, 0.0, 0.0])
    expected = np.array(loc) + _rot_z(math.pi / 2) @ (np.array(scl) * v)
    got = (M @ np.array([*v, 1.0]))[:3]
    assert np.allclose(got, expected, atol=1e-6)


def _rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


# ---------------------------------------------------------------------------
# 2. _resolve_mapping_matrix — walks the Mapping chain
# ---------------------------------------------------------------------------

def test_resolve_matrix_none_when_no_mapping(monkeypatch):
    cls = _cls(monkeypatch)
    engine = cls()
    tc = _Node('TEX_COORD')
    socket = _Socket(linked_to=tc, output_name='UV')
    assert engine._resolve_mapping_matrix(socket) is None


def test_resolve_matrix_none_for_identity_mapping(monkeypatch):
    cls = _cls(monkeypatch)
    engine = cls()
    mapping = _Node('MAPPING', inputs={
        'Vector': _Socket(linked_to=_Node('TEX_COORD'), output_name='UV'),
        'Location': _Socket(default=(0.0, 0.0, 0.0)),
        'Rotation': _Socket(default=(0.0, 0.0, 0.0)),
        'Scale': _Socket(default=(1.0, 1.0, 1.0)),
    })
    socket = _Socket(linked_to=mapping, output_name='Vector')
    assert engine._resolve_mapping_matrix(socket) is None


def test_resolve_matrix_full_3d_rotation(monkeypatch):
    """X/Y/Z rotation all preserved (the old path dropped X/Y)."""
    cls = _cls(monkeypatch)
    engine = cls()
    mapping = _Node('MAPPING', inputs={
        'Vector': _Socket(linked_to=_Node('TEX_COORD'), output_name='UV'),
        'Location': _Socket(default=(0.0, 5.6, 0.0)),
        'Rotation': _Socket(default=(1.30, 0.87, 0.95)),  # owner's repro mapping
        'Scale': _Socket(default=(0.4, 0.4, 0.4)),
    })
    socket = _Socket(linked_to=mapping, output_name='Vector')
    m = engine._resolve_mapping_matrix(socket)
    assert m is not None and len(m) == 12
    expected = cls._compose_mapping_matrix((0.0, 5.6, 0.0), (1.30, 0.87, 0.95), (0.4, 0.4, 0.4))
    assert np.allclose(np.array(m).reshape(3, 4), expected[:3, :], atol=1e-6)


def test_resolve_matrix_chained_composes(monkeypatch):
    """Two Mapping nodes compose (outer @ inner)."""
    cls = _cls(monkeypatch)
    engine = cls()
    inner = _Node('MAPPING', inputs={
        'Vector': _Socket(linked_to=_Node('TEX_COORD'), output_name='UV'),
        'Location': _Socket(default=(0.0, 0.0, 0.0)),
        'Rotation': _Socket(default=(0.0, 0.0, 0.0)),
        'Scale': _Socket(default=(2.0, 2.0, 2.0)),
    })
    outer = _Node('MAPPING', inputs={
        'Vector': _Socket(linked_to=inner, output_name='Vector'),
        'Location': _Socket(default=(1.0, 0.0, 0.0)),
        'Rotation': _Socket(default=(0.0, 0.0, 0.0)),
        'Scale': _Socket(default=(1.0, 1.0, 1.0)),
    })
    socket = _Socket(linked_to=outer, output_name='Vector')
    m = np.array(engine._resolve_mapping_matrix(socket)).reshape(3, 4)
    # A point (1,1,1): inner scales to (2,2,2), outer translates +x → (3,2,2).
    p = m @ np.array([1, 1, 1, 1.0])
    assert np.allclose(p[:3], [3, 2, 2], atol=1e-6)


def test_resolve_matrix_linked_input_degrades(monkeypatch):
    """A linked Mapping input can't be constant-folded → degradation entry,
    falls back to the socket default (never a silent grey)."""
    cls = _cls(monkeypatch)
    engine = cls()
    driver = _Node('TEX_NOISE')
    mapping = _Node('MAPPING', inputs={
        'Vector': _Socket(linked_to=_Node('TEX_COORD'), output_name='UV'),
        'Location': _Socket(default=(1.0, 0.0, 0.0)),  # unlinked, non-identity
        'Rotation': _Socket(default=(0.0, 0.0, 0.0)),
        'Scale': _Socket(default=(2.0, 2.0, 2.0), linked_to=driver, output_name='Fac'),
    })
    socket = _Socket(linked_to=mapping, output_name='Vector')
    m = engine._resolve_mapping_matrix(socket)
    # The linked Scale can't be constant-folded → neutral fallback (never a
    # silent grey), but the unlinked Location still applies, so the matrix is
    # non-identity AND a visible degradation entry is recorded.
    assert m is not None
    rep = engine._degradation_report()
    assert not rep.is_empty()
    assert any('MAPPING' in feature for feature, _ in rep.approximated)


# ---------------------------------------------------------------------------
# 3. Non-UV TexCoord modes now route through (were UV-fallback before)
# ---------------------------------------------------------------------------

def test_texcoord_camera(monkeypatch):
    cls = _cls(monkeypatch)
    tc = _Node('TEX_COORD')
    socket = _Socket(linked_to=tc, output_name='Camera')
    coord, *_ = cls._resolve_vector_input(socket)
    assert coord == "CAMERA"


def test_texcoord_window(monkeypatch):
    cls = _cls(monkeypatch)
    tc = _Node('TEX_COORD')
    socket = _Socket(linked_to=tc, output_name='Window')
    coord, *_ = cls._resolve_vector_input(socket)
    assert coord == "WINDOW"


def test_texcoord_reflection(monkeypatch):
    cls = _cls(monkeypatch)
    tc = _Node('TEX_COORD')
    socket = _Socket(linked_to=tc, output_name='Reflection')
    coord, *_ = cls._resolve_vector_input(socket)
    assert coord == "REFLECTION"


def test_texcoord_normal(monkeypatch):
    cls = _cls(monkeypatch)
    tc = _Node('TEX_COORD')
    socket = _Socket(linked_to=tc, output_name='Normal')
    coord, *_ = cls._resolve_vector_input(socket)
    assert coord == "NORMAL"


# ---------------------------------------------------------------------------
# 4. End-to-end plumbing: load_blender_image ships the matrix + coord mode
# ---------------------------------------------------------------------------

def test_load_image_3d_mapping_sends_matrix(monkeypatch):
    cls = _cls(monkeypatch)
    engine = cls()
    renderer = _RecordingRenderer()
    image = _FakeImage(name="wood.png")
    mapping = _Node('MAPPING', inputs={
        'Vector': _Socket(linked_to=_Node('TEX_COORD'), output_name='UV'),
        'Location': _Socket(default=(0.0, 5.6, 0.0)),
        'Rotation': _Socket(default=(1.30, 0.87, 0.95)),
        'Scale': _Socket(default=(0.4, 0.4, 0.4)),
    })
    name = engine.load_blender_image(
        image, renderer, vector_input=_Socket(linked_to=mapping, output_name='Vector'))
    assert renderer.uv_transform_calls == []
    assert len(renderer.mapping_matrix_calls) == 1
    n, m = renderer.mapping_matrix_calls[0]
    assert n == name and len(m) == 12
    expected = cls._compose_mapping_matrix((0.0, 5.6, 0.0), (1.30, 0.87, 0.95), (0.4, 0.4, 0.4))
    assert np.allclose(np.array(m).reshape(3, 4), expected[:3, :], atol=1e-6)


def test_load_image_camera_coord_sends_mode(monkeypatch):
    cls = _cls(monkeypatch)
    engine = cls()
    renderer = _RecordingRenderer()
    image = _FakeImage(name="cam.png")
    tc = _Node('TEX_COORD')
    name = engine.load_blender_image(
        image, renderer, vector_input=_Socket(linked_to=tc, output_name='Camera'))
    assert (name, "CAMERA") in renderer.coord_mode_calls
