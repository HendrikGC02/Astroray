"""pkg59 named UV-layer plumbing tests."""

from __future__ import annotations

import types

import pytest

from test_blender_uv_plumbing import (
    _FakeImage,
    _load_blender_addon,
    _Node,
    _RecordingRenderer,
    _Socket,
)


def test_resolve_vector_input_uvmap_node_returns_layer_name(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    uvmap = _Node("UVMAP", uv_map="Highres")
    socket = _Socket(linked_to=uvmap, output_name="UV")

    coord, scale, offset, rotation, layer = cls._resolve_vector_input(socket)

    assert coord == "UV"
    assert scale == (1.0, 1.0)
    assert offset == (0.0, 0.0)
    assert rotation == 0.0
    assert layer == "Highres"


def test_resolve_vector_input_texture_coordinate_uv_map(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    texcoord = _Node("TEX_COORD", uv_map="UVMap2")
    socket = _Socket(linked_to=texcoord, output_name="UV")

    coord, _scale, _offset, _rotation, layer = cls._resolve_vector_input(socket)

    assert coord == "UV"
    assert layer == "UVMap2"


def test_texture_variant_key_includes_uv_layer(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    image = _FakeImage(name="shared.png")

    highres = _Socket(linked_to=_Node("UVMAP", uv_map="Highres"), output_name="UV")
    lowres = _Socket(linked_to=_Node("UVMAP", uv_map="Lowres"), output_name="UV")

    n1 = engine.load_blender_image(image, renderer, vector_input=highres)
    n2 = engine.load_blender_image(image, renderer, vector_input=lowres)

    assert n1 != n2
    assert "Highres" in n1
    assert "Lowres" in n2
    assert renderer.uv_layer_calls == [(n1, "Highres"), (n2, "Lowres")]


class _Matrix:
    def __matmul__(self, other):
        return other

    def to_3x3(self):
        return self

    def inverted_safe(self):
        return self

    def transposed(self):
        return self


class _UVLayers(list):
    def __init__(self, layers, active=None):
        super().__init__(layers)
        self.active = active if active is not None else (layers[0] if layers else None)


class _Mesh:
    def __init__(self, uv_layers):
        self.vertices = [
            types.SimpleNamespace(co=[0.0, 0.0, 0.0]),
            types.SimpleNamespace(co=[1.0, 0.0, 0.0]),
            types.SimpleNamespace(co=[0.0, 1.0, 0.0]),
        ]
        self.loop_triangles = [
            types.SimpleNamespace(vertices=[0, 1, 2], loops=[0, 1, 2], material_index=0)
        ]
        self.uv_layers = uv_layers

    def calc_loop_triangles(self):
        pass


class _Object:
    type = "MESH"
    name = "UV Object"
    material_slots = [types.SimpleNamespace(material=types.SimpleNamespace(name="Mat"))]
    pass_index = 3
    matrix_world = _Matrix()

    def __init__(self, mesh):
        self._mesh = mesh
        self.data = mesh

    def evaluated_get(self, _depsgraph):
        return self

    def to_mesh(self):
        return self._mesh

    def to_mesh_clear(self):
        pass


class _MeshRenderer:
    def __init__(self):
        self.triangles = []
        self.layer_triangles = []

    def add_triangle(self, *args):
        self.triangles.append(args)

    def add_triangle_layers(self, *args):
        self.layer_triangles.append(args)


def _uv_layer(name, coords):
    data = [types.SimpleNamespace(uv=uv) for uv in coords]
    return types.SimpleNamespace(name=name, data=data)


def test_mesh_with_two_uv_layers_uploads_both(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    uv1 = _uv_layer("UVMap", [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    uv2 = _uv_layer("UVMap2", [[0.2, 0.2], [0.8, 0.2], [0.2, 0.8]])
    mesh = _Mesh(_UVLayers([uv1, uv2], active=uv1))
    renderer = _MeshRenderer()

    obj = _Object(mesh)
    depsgraph = types.SimpleNamespace(object_instances=[
        types.SimpleNamespace(object=obj, matrix_world=obj.matrix_world)
    ])
    engine.convert_objects(depsgraph, renderer, {"Mat": 7})

    assert renderer.triangles == []
    assert len(renderer.layer_triangles) == 1
    uv_layers = renderer.layer_triangles[0][4]
    assert uv_layers == {
        "UVMap": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
        "UVMap2": [[0.2, 0.2], [0.8, 0.2], [0.2, 0.8]],
    }


def test_mesh_with_one_uv_layer_keeps_single_layer_path(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    uv = _uv_layer("UVMap", [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    mesh = _Mesh(_UVLayers([uv], active=uv))
    renderer = _MeshRenderer()

    obj = _Object(mesh)
    depsgraph = types.SimpleNamespace(object_instances=[
        types.SimpleNamespace(object=obj, matrix_world=obj.matrix_world)
    ])
    engine.convert_objects(depsgraph, renderer, {"Mat": 7})

    assert renderer.layer_triangles == []
    assert len(renderer.triangles) == 1
    assert renderer.triangles[0][4:7] == (
        [0.0, 0.0],
        [1.0, 0.0],
        [0.0, 1.0],
    )


def test_renderer_exposes_named_uv_layer_bindings():
    try:
        import astroray
    except ImportError:
        pytest.skip("astroray module not available")

    renderer = astroray.Renderer()
    assert hasattr(renderer, "add_triangle_layers")
    assert hasattr(renderer, "set_texture_uv_layer")

    mat = renderer.create_material("lambertian", [0.8, 0.8, 0.8], {})
    renderer.add_triangle_layers(
        [0.0, 0.0, -1.0],
        [1.0, 0.0, -1.0],
        [0.0, 1.0, -1.0],
        mat,
        {
            "UVMap": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
            "UVMap2": [[0.2, 0.2], [0.8, 0.2], [0.2, 0.8]],
        },
    )
