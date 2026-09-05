"""pkg230 Phase 2 — coordinate-chain fallback warning (mocked addon, no bpy/engine).

A Vector Math / Vector Rotate node on an image-texture coordinate chain is a
per-texel coordinate op the affine resolver cannot express. It must surface a
VISIBLE ``_warn_shader_fallback`` (recorded in the degradation report), never a
silent plain-UV fallback. Uses the same stub-bpy loader pattern as the other
addon tests; no built module is required.
"""
from test_blender_uv_plumbing import (
    _FakeImage,
    _load_blender_addon,
    _Node,
    _RecordingRenderer,
    _Socket,
)


def _cls(monkeypatch):
    return _load_blender_addon(monkeypatch).CustomRaytracerRenderEngine


def test_vector_math_on_coord_chain_warns(monkeypatch):
    cls = _cls(monkeypatch)
    engine = cls()
    vm = _Node('VECT_MATH')
    socket = _Socket(linked_to=vm, output_name='Vector')
    coord, scale, offset, _rotation, _layer = engine._resolve_vector_input(
        socket, warn=engine._warn_shader_fallback)
    # fallback behavior is preserved: default UV with identity transform
    assert coord == "UV"
    assert scale == (1.0, 1.0) and offset == (0.0, 0.0)
    rep = engine._degradation_report()
    assert any('VECT_MATH' in feature for feature, _ in rep.approximated)


def test_vector_rotate_on_coord_chain_warns(monkeypatch):
    cls = _cls(monkeypatch)
    engine = cls()
    vr = _Node('VECTOR_ROTATE')
    socket = _Socket(linked_to=vr, output_name='Vector')
    cls._resolve_vector_input(socket, warn=engine._warn_shader_fallback)
    rep = engine._degradation_report()
    assert any('VECTOR_ROTATE' in feature for feature, _ in rep.approximated)


def test_supported_coord_source_does_not_warn(monkeypatch):
    cls = _cls(monkeypatch)
    engine = cls()
    tc = _Node('TEX_COORD')
    socket = _Socket(linked_to=tc, output_name='UV')
    coord, *_ = engine._resolve_vector_input(socket, warn=engine._warn_shader_fallback)
    assert coord == "UV"
    assert engine._degradation_report().is_empty()


def test_mapping_chain_with_inner_vector_math_warns(monkeypatch):
    cls = _cls(monkeypatch)
    engine = cls()
    vm = _Node('VECT_MATH')
    mapping = _Node('MAPPING', inputs={
        'Vector': _Socket(linked_to=vm, output_name='Vector'),
        'Location': _Socket(default=(0.0, 0.0, 0.0)),
        'Rotation': _Socket(default=(0.0, 0.0, 0.0)),
        'Scale': _Socket(default=(1.0, 1.0, 1.0)),
    })
    socket = _Socket(linked_to=mapping, output_name='Vector')
    coord, *_ = engine._resolve_vector_input(socket, warn=engine._warn_shader_fallback)
    assert coord == "UV"
    rep = engine._degradation_report()
    assert any('VECT_MATH' in feature for feature, _ in rep.approximated)


def test_mapping_matrix_still_none_for_vector_math(monkeypatch):
    # the affine resolver keeps returning None (behavior preserved) — the visible
    # degradation entry comes from _resolve_vector_input's warn hook.
    cls = _cls(monkeypatch)
    engine = cls()
    vm = _Node('VECT_MATH')
    socket = _Socket(linked_to=vm, output_name='Vector')
    assert engine._resolve_mapping_matrix(socket) is None


def test_load_blender_image_vector_math_records_degradation(monkeypatch):
    cls = _cls(monkeypatch)
    engine = cls()
    renderer = _RecordingRenderer()
    image = _FakeImage(name="coords.png")
    vm = _Node('VECT_MATH')
    name = engine.load_blender_image(
        image, renderer,
        vector_input=_Socket(linked_to=vm, output_name='Vector'))
    assert name is not None
    rep = engine._degradation_report()
    assert any('VECT_MATH' in feature for feature, _ in rep.approximated)


def test_procedural_coordinate_warning_reports_generated_default(monkeypatch):
    cls = _cls(monkeypatch)
    warnings = []
    coord, *_ = cls._resolve_vector_input(
        _Socket(linked_to=_Node('VECTOR_ROTATE'), output_name='Vector'),
        default_coord_mode='GENERATED', warn=lambda feature, reason: warnings.append(reason))
    assert coord == 'GENERATED'
    assert len(warnings) == 1 and 'GENERATED' in warnings[0]
    assert 'plain UV' not in warnings[0]
