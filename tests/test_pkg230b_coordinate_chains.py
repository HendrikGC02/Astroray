"""pkg230b affine coordinate oracles and mock addon consumer contracts.

No native renderer is imported or invoked. Rotation oracles apply elementary
coordinate equations to points independently of the addon matrix builder.
"""

import math
import sys
import types

import numpy as np
import pytest
from test_blender_uv_plumbing import (
    _FakeImage,
    _load_blender_addon,
    _Node,
    _RecordingRenderer,
    _Socket,
)


class _Inputs:
    """Blender-style duplicate names: get returns the FIRST matching socket."""

    def __init__(self, sockets):
        self.sockets = sockets

    def __getitem__(self, index):
        return self.sockets[index]

    def get(self, name):
        return next((socket for socket in self.sockets if socket.name == name), None)


def _named(name, value=(0, 0, 0)):
    socket = value if isinstance(value, _Socket) else _Socket(default=value)
    socket.name = name
    return socket


def _source(mode='UV', layer=''):
    return _Socket(linked_to=_Node('TEX_COORD', uv_map=layer), output_name=mode)


def _math(operation, a, b=(0, 0, 0), scale=1.0):
    node = _Node('VECT_MATH', operation=operation, inputs=_Inputs([
        _named('Vector', a), _named('Vector', b),
        _named('Vector', _Socket(linked_to=_Node('UNSUPPORTED'))),
        _named('Scale', scale),
    ]))
    return _Socket(linked_to=node, output_name='Vector')


def _mapping(vector, location=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1), kind='POINT'):
    return _Socket(linked_to=_Node('MAPPING', vector_type=kind, inputs={
        'Vector': vector,
        'Location': _named('Location', location),
        'Rotation': _named('Rotation', rotation),
        'Scale': _named('Scale', scale),
    }), output_name='Vector')


def _rotate(vector, kind, center=(0, 0, 0), angle=0.0, axis=(0, 0, 1),
            euler=(0, 0, 0), invert=False):
    inputs = {'Vector': vector, 'Center': _named('Center', center)}
    # Blender 5.1 removes the other mode's sockets, rather than just disabling.
    if kind == 'EULER_XYZ':
        inputs['Rotation'] = _named('Rotation', euler)
    else:
        inputs['Angle'] = _named('Angle', angle)
        if kind == 'AXIS_ANGLE':
            inputs['Axis'] = _named('Axis', axis)
    return _Socket(linked_to=_Node('VECTOR_ROTATE', rotation_type=kind,
                                 invert=invert, inputs=inputs), output_name='Vector')


@pytest.fixture
def engine(monkeypatch):
    return _load_blender_addon(monkeypatch).CustomRaytracerRenderEngine()


def _resolved(engine, socket):
    return engine._resolve_affine_coordinates(socket, warn=engine._warn_shader_fallback)


def _point(engine, socket, point=(0.2, -0.3, 0.5)):
    return (_resolved(engine, socket)['matrix'] @ np.array([*point, 1.0]))[:3]


def _assert_point(got, expected):
    np.testing.assert_allclose(got, expected, atol=1e-6, rtol=1e-6)


@pytest.mark.parametrize(('operation', 'expected'), [
    ('ADD', (2.2, 2.7, 4.5)),
    ('SUBTRACT', (-1.8, -3.3, -3.5)),
    ('MULTIPLY', (0.4, -0.9, 2.0)),
    ('SCALE', (-0.4, 0.6, -1.0)),
])
def test_vector_math_explicit_point_oracles(engine, operation, expected):
    _assert_point(_point(engine, _math(operation, _source(), (2, 3, 4), -2)), expected)
    assert engine._degradation_report().is_empty()  # the unused third vector is invalid


@pytest.mark.parametrize('operation', ['ADD', 'SUBTRACT', 'MULTIPLY'])
def test_second_operand_provenance_and_order(engine, operation):
    socket = _math(operation, (2, 3, 4), _source('Object'))
    resolved = _resolved(engine, socket)
    assert resolved['coord_mode'] == 'OBJECT'
    expected = {'ADD': (2.2, 2.7, 4.5), 'SUBTRACT': (1.8, 3.3, 3.5),
                'MULTIPLY': (0.4, -0.9, 2.0)}[operation]
    _assert_point(_point(engine, socket), expected)


def test_scale_reads_no_other_vector_operand(engine):
    dead = _Socket(linked_to=_Node('UNSUPPORTED'))
    _assert_point(_point(engine, _math('SCALE', _source(), dead, -2)), (-0.4, 0.6, -1))
    assert engine._degradation_report().is_empty()


def test_linked_value_rgb_combine_constants(engine):
    value = _Node('VALUE', outputs=[types.SimpleNamespace(default_value=-2.0)])
    rgb = _Node('RGB', outputs=[types.SimpleNamespace(default_value=(2, 3, 4, 1))])
    combine = _Node('COMBXYZ', inputs={axis: _Socket(default=v)
                                     for axis, v in zip('XYZ', (2, 3, 4))})
    _assert_point(_point(engine, _math('SCALE', _source(), scale=_Socket(linked_to=value))),
                  (-0.4, 0.6, -1))
    for node in (rgb, combine):
        _assert_point(_point(engine, _math('ADD', _source(), _Socket(linked_to=node))),
                      (2.2, 2.7, 4.5))
    assert engine._degradation_report().is_empty()


def test_constant_only_affine_chain(engine):
    socket = _math('MULTIPLY', (2, -3, 4), (0, 5, -2))
    assert not _resolved(engine, socket)['varying']
    _assert_point(_point(engine, socket, (100, 200, 300)), (0, -15, -8))


def test_zero_scale_is_constant_and_can_combine_with_one_varying_source(engine):
    zero = _math('SCALE', _source('UV'), scale=0)
    assert not _resolved(engine, zero)['varying']
    socket = _math('ADD', zero, _source('Object'))
    _assert_point(_point(engine, socket), (0.2, -0.3, 0.5))
    assert _resolved(engine, socket)['coord_mode'] == 'OBJECT'
    assert engine._degradation_report().is_empty()


@pytest.mark.parametrize('mode', ['Generated', 'Object', 'UV'])
def test_coordinate_provenance_survives_rotations(engine, mode):
    socket = _rotate(_math('ADD', (1, 2, 3), _source(mode, 'DetailUV')),
                     'Z_AXIS', angle=0.4)
    resolved = _resolved(engine, socket)
    assert resolved['coord_mode'] == mode.upper()
    assert resolved['uv_layer'] == ('DetailUV' if mode == 'UV' else '')


def _axis_point(point, axis, angle):
    # Elementary component equations, independent of the matrix constructor.
    x, y, z = point
    c, s = math.cos(angle), math.sin(angle)
    if axis == 'X_AXIS':
        return np.array([x, c * y - s * z, s * y + c * z])
    if axis == 'Y_AXIS':
        return np.array([c * x + s * z, y, -s * x + c * z])
    return np.array([c * x - s * y, s * x + c * y, z])


@pytest.mark.parametrize('kind', ['X_AXIS', 'Y_AXIS', 'Z_AXIS', 'AXIS_ANGLE', 'EULER_XYZ'])
@pytest.mark.parametrize('invert', [False, True])
def test_rotations_center_inverse_and_removed_sockets(engine, kind, invert):
    point, center = np.array([0.2, -0.3, 0.5]), np.array([1.2, 2.3, -0.4])
    angles, angle = (0.3, -0.7, 0.9), 0.7
    if kind == 'EULER_XYZ':
        local = point - center
        # Inverse applies the REVERSED elementary rotations, not negative XYZ.
        order = list(zip(('X_AXIS', 'Y_AXIS', 'Z_AXIS'), angles))
        for axis, value in (reversed(order) if invert else order):
            local = _axis_point(local, axis, -value if invert else value)
        expected = center + local
    else:
        expected = center + _axis_point(point - center,
                                       'Z_AXIS' if kind == 'AXIS_ANGLE' else kind,
                                       -angle if invert else angle)
    socket = _rotate(_source(), kind, center, angle, (0, 0, 3), angles, invert)
    _assert_point(_point(engine, socket), expected)
    assert engine._degradation_report().is_empty()


def test_oblique_axis_and_zero_axis(engine):
    # Rotating (1,0,0) by 120 degrees around (1,1,1) cyclically permutes XYZ.
    socket = _rotate(_source(), 'AXIS_ANGLE', axis=(1, 1, 1), angle=2 * math.pi / 3)
    _assert_point(_point(engine, socket, (1, 0, 0)), (0, 1, 0))
    socket = _rotate(_source(), 'AXIS_ANGLE', center=(1, 2, 3), axis=(0, 0, 0), angle=1)
    _assert_point(_point(engine, socket), (0.2, -0.3, 0.5))


def test_noncommuting_mapping_rotation_chain(engine):
    inner = _mapping(_source(), location=(2, 0, 1), scale=(2, 3, 4))
    rotated = _rotate(inner, 'Z_AXIS', center=(1, 1, 0), angle=math.pi / 2)
    outer = _mapping(rotated, location=(0, 5, 0), scale=(-1, 2, 0))
    # p -> (2.4,-.9,3) -> (2.9,2.4,3) -> (-2.9,9.8,0)
    _assert_point(_point(engine, outer), (-2.9, 9.8, 0))


def test_singular_texture_mapping_safe_divide(engine):
    socket = _mapping(_source(), (1, 2, 3), (0, 0, math.pi / 2), (0, 2, -3), 'TEXTURE')
    _assert_point(_point(engine, socket, (3, 6, 9)), (0, -1, -2))


def test_unlinked_mapping_vector_is_constant(engine):
    socket = _mapping(_Socket(default=(2, -3, 4)), (1, 2, 3), scale=(2, 3, -1))
    for point in ((0, 0, 0), (100, -200, 300)):
        _assert_point(_point(engine, socket, point), (5, -7, -1))
    assert not _resolved(engine, socket)['varying']
    assert engine._degradation_report().is_empty()


def test_malformed_mapping_vector_warns_instead_of_silent_implicit_coordinates(engine):
    socket = _mapping(_Socket(default=0.0), location=(1, 0, 0))
    _assert_point(_point(engine, socket), (1.2, -0.3, 0.5))
    assert any('malformed Mapping Vector' in reason
               for _, reason in engine._degradation_report().approximated)


def test_rna_pointer_detects_cycle_across_distinct_python_wrappers(engine):
    socket = _mapping(_source())
    node = socket.links[0].from_node
    other_wrapper = _Node('MAPPING', inputs=node.inputs)
    node.as_pointer = other_wrapper.as_pointer = lambda: 123456
    node.inputs['Vector'] = _Socket(linked_to=other_wrapper, output_name='Vector')
    assert node is not other_wrapper
    _resolved(engine, socket)
    warnings = [reason for _, reason in engine._degradation_report().approximated]
    assert any('cycle detected' in reason for reason in warnings)
    assert not any('depth limit' in reason for reason in warnings)


@pytest.mark.parametrize('socket', [
    _math('SCALE', _source(), scale=1e39),
    _mapping(_source(), scale=(1e-320, 1, 1), kind='TEXTURE'),
])
def test_nonrepresentable_composed_matrix_warns_and_stays_finite(engine, socket):
    _assert_point(_point(engine, socket), (0.2, -0.3, 0.5))
    assert not engine._degradation_report().is_empty()


def test_normal_mapping_warns_about_bounded_approximation(engine):
    _resolved(engine, _mapping(_source(), scale=(2, 3, 4), kind='NORMAL'))
    assert any('normalization' in reason for _, reason in engine._degradation_report().approximated)


@pytest.mark.parametrize('operation', ['DIVIDE', 'NORMALIZE', 'CROSS_PRODUCT'])
def test_unsupported_operations_warn_and_fallback(engine, operation):
    _assert_point(_point(engine, _math(operation, _source(), (2, 3, 4))), (0.2, -0.3, 0.5))
    assert any(operation in reason for _, reason in engine._degradation_report().approximated)


def test_two_varying_inputs_rejected_visibly(engine):
    _assert_point(_point(engine, _math('ADD', _source('Generated'), _source('Object'))),
                  (0.2, -0.3, 0.5))
    assert any('multiple varying' in reason for _, reason in engine._degradation_report().approximated)


def test_linked_rotation_control_never_uses_socket_default(engine):
    control = _Socket(default=math.pi / 2, linked_to=_Node('TEX_NOISE'))
    _assert_point(_point(engine, _rotate(_source(), 'Z_AXIS', angle=control)), (0.2, -0.3, 0.5))
    assert any('linked TEX_NOISE' in reason for _, reason in engine._degradation_report().approximated)


def test_cycle_and_depth_fallback_are_visible(engine):
    cycle = _mapping(_source(), location=(1, 0, 0))
    cycle.links[0].from_node.inputs['Vector'] = cycle
    assert np.all(np.isfinite(_resolved(engine, cycle)['matrix']))
    deep = _source()
    for _ in range(40):
        deep = _mapping(deep)
    _resolved(engine, deep)
    warnings = [reason for _, reason in engine._degradation_report().approximated]
    assert any('cycle' in reason for reason in warnings)
    assert any('depth limit' in reason for reason in warnings)


def test_exact_identity_cancellation_and_tiny_cache_edits(engine):
    renderer, image = _RecordingRenderer(), _FakeImage('shared.png')
    plain = engine.load_blender_image(image, renderer)
    cancelled = _math('SUBTRACT', _math('ADD', _source(), (1, 2, 3)), (1, 2, 3))
    assert engine.load_blender_image(image, renderer, cancelled) == plain == 'shared.png'
    first = engine.load_blender_image(image, renderer, _math('ADD', _source(), (1e-5, 0, 0)))
    second = engine.load_blender_image(image, renderer, _math('ADD', _source(), (2e-5, 0, 0)))
    tiny = engine.load_blender_image(image, renderer, _math('ADD', _source(), (1e-9, 0, 0)))
    assert len({plain, first, second, tiny}) == 4
    assert all('program-child' not in key for key in (plain, first, second, tiny))
    assert len(renderer.loaded_textures) == 4
    assert len(renderer.mapping_matrix_calls) == 3


def test_image_resolves_once_and_preserves_named_uv(engine, monkeypatch):
    original = engine._resolve_affine_coordinates
    calls = []
    def counted(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(engine, '_resolve_affine_coordinates', counted)
    renderer = _RecordingRenderer()
    socket = _math('SUBTRACT', (1, 1, 0), _source('UV', 'DetailUV'))
    name = engine.load_blender_image(_FakeImage(), renderer, socket)
    assert calls == [socket]
    assert renderer.uv_layer_calls == [(name, 'DetailUV')]
    assert len(renderer.mapping_matrix_calls) == 1


class _ProgramRenderer(_RecordingRenderer):
    def __init__(self):
        super().__init__()
        self.textures, self.programs = {}, {}

    def load_texture(self, name, rgb, w, h):
        super().load_texture(name, rgb, w, h)
        self.textures[name] = object()

    def create_program_texture(self, name, mode):
        self.programs[name] = []

    def program_texture_add_input(self, name, child):
        self.programs[name].append(self.textures[child])

    def set_program_texture_program(self, *_args):
        pass


def _program(engine, monkeypatch, renderer, images, name):
    module = types.ModuleType('shader_vm_compiler')
    module.VMCompileError = ValueError
    module.compile_chain = lambda _socket: {
        'inputs': images, 'num_tex': len(images), 'out_slot': 0,
        'code_flat': [], 'consts_flat': [], 'ramps_flat': [],
    }
    monkeypatch.setitem(sys.modules, 'shader_vm_compiler', module)
    return engine._maybe_build_program_texture(_Socket(), _Node('BSDF_PRINCIPLED', name=name),
                                              'Base Color', renderer)


def test_program_children_identity_and_mapping_pointer_isolation(engine, monkeypatch):
    image, renderer = _FakeImage('same.png'), _ProgramRenderer()
    nodes = [_Node('TEX_IMAGE', image=image, inputs={'Vector': _math('ADD', _source(), (x, 0, 0))})
             for x in (0.1, 0.2)]
    a = _program(engine, monkeypatch, renderer, [nodes[0]], 'A')
    b = _program(engine, monkeypatch, renderer, [nodes[1]], 'B')
    c = _program(engine, monkeypatch, renderer, [nodes[0]], 'C')
    assert renderer.programs[a][0] is not renderer.programs[b][0]
    assert renderer.programs[a][0] is renderer.programs[c][0]
    assert len(renderer.loaded_textures) == 2
    assert {name for name, _ in renderer.mapping_matrix_calls} == {a, b, c}
    assert renderer.uv_transform_calls == []  # child textures receive no transform
    assert engine._degradation_report().is_empty()


def test_program_differing_input_mappings_degrade_before_upload(engine, monkeypatch):
    image, renderer = _FakeImage(), _ProgramRenderer()
    nodes = [_Node('TEX_IMAGE', image=image, inputs={'Vector': _source(mode)})
             for mode in ('UV', 'Generated')]
    assert _program(engine, monkeypatch, renderer, nodes, 'A') is None
    assert renderer.loaded_textures == [] and not renderer.programs
    assert any('differing coordinate' in reason for _, reason in engine._degradation_report().approximated)


def test_procedural_new_chain_warns_and_keeps_outer_legacy_mapping(engine):
    socket = _mapping(_math('ADD', _source(), (1, 2, 3)), location=(0.25, 0.5, 0))
    node = _Node('TEX_CHECKER', inputs={'Vector': socket}, name='checker')
    renderer = _RecordingRenderer()
    name = engine.load_procedural_texture(node, renderer, socket)
    assert name is not None and renderer.mapping_matrix_calls == []
    assert renderer.uv_transform_calls == [(name, 1, 1, 0.25, 0.5, 0)]
    assert (name, 'GENERATED') in renderer.coord_mode_calls
    assert any('pkg242' in reason for _, reason in engine._degradation_report().approximated)


def test_missing_matrix_binding_is_visible_and_does_not_project_to_2d(engine):
    renderer = types.SimpleNamespace(set_texture_coord_mode=lambda *_args: None)
    engine._apply_texture_transform(renderer, 'image', 'UV', (2, 3), (1, 2), 0.4,
                                    mapping_matrix=[1, 0, 0, 1, 0, 1, 0, 2, 0, 0, 1, 3])
    assert any('binding unavailable' in reason for _, reason in engine._degradation_report().approximated)
