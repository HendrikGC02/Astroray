"""pkg/issue #721 + #835 — material-edit classification in the viewport commit.

#721 made a Base Color storm classify MATERIALS (upload_materials() replay)
instead of a full sync. #835 reverses the routing: the replay never re-converts,
so every material edit must full-sync; the MaterialsCache value/structural split
stays for a future in-place engine update. These are pure-Python, bpy-free unit tests using the
fake depsgraph/update object pattern from tests/test_pkg116_exporter_caches.py
and tests/test_pkg266_dirty_domain_commit.py.

Covered:
  (a) #835 supersedes the original (a): a Base-Color value edit must FULL-SYNC.
      upload_materials() re-pushes the engine's already-converted materials
      (primitives hold them by pointer), so the MATERIALS replay left the
      viewport stale (measured live: Base Color edit -> sphere stayed grey).
  (b) every structural case -> full sync: node-tree topology change, an image
      texture datablock change, a material-slot assignment, an emission-strength
      sign flip, a volume/displacement output change.
  (c) an object transform edit mixed with a material edit -> full sync (#835).
  (d) #835: same-sign emission-strength edits, light edits and non-instanced
      object moves full-sync on the synchronous (worker OFF) path too.
"""

import importlib.util
import types
from pathlib import Path


# ---------------------------------------------------------------------------
# stub bpy (matches test_pkg266, plus Mesh and bpy.data.materials)
# ---------------------------------------------------------------------------

class _BpyId:
    def __init__(self, name="x"):
        self.name = name


class World(_BpyId): pass
class Light(_BpyId): pass
class Material(_BpyId): pass
class NodeTree(_BpyId): pass
class Image(_BpyId): pass
class Mesh(_BpyId): pass
class Scene(_BpyId): pass


class Object(_BpyId):
    def __init__(self, name="obj", matrix_world=None):
        super().__init__(name)
        self.matrix_world = matrix_world or [
            [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]
        ]


class _DepsgraphUpdate:
    def __init__(self, id, *, geometry=False, transform=False, shading=False):
        self.id = id
        self.is_updated_geometry = geometry
        self.is_updated_transform = transform
        self.is_updated_shading = shading


# Minimal fake node-tree model: node.type + node.inputs (name -> _Socket) +
# node_tree.links (from_node/from_socket/to_node/to_socket).
class _Socket:
    def __init__(self, name, default_value=0.0, is_linked=False):
        self.name = name
        self.default_value = default_value
        self.is_linked = is_linked


class _Inputs:
    def __init__(self, sockets):
        self._sockets = sockets  # name -> _Socket

    def get(self, name):
        return self._sockets.get(name)

    def __iter__(self):
        return iter(self._sockets.values())


class _Node:
    def __init__(self, ntype, inputs=None):
        self.type = ntype
        self.inputs = _Inputs(inputs or {})


class _Link:
    def __init__(self, from_node, from_socket, to_node, to_socket):
        self.from_node = from_node
        self.from_socket = from_socket
        self.to_node = to_node
        self.to_socket = to_socket


class _FakeNodeTree:
    def __init__(self, nodes=None, links=None):
        self.nodes = nodes or []
        self.links = links or []


def _load_exporter_module():
    module_path = Path(__file__).parent.parent / "blender_addon" / "exporter.py"
    spec = importlib.util.spec_from_file_location(
        "astroray_exporter_pkg721", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _stub_bpy():
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_types_module.World = World
    bpy_types_module.Light = Light
    bpy_types_module.Material = Material
    bpy_types_module.NodeTree = NodeTree
    bpy_types_module.ShaderNodeTree = NodeTree
    bpy_types_module.Image = Image
    bpy_types_module.Object = Object
    bpy_types_module.Mesh = Mesh
    bpy_types_module.Scene = Scene
    bpy_module.types = bpy_types_module
    bpy_module.data = types.SimpleNamespace(materials=[])
    return bpy_module


def _stub_depsgraph(updates, scene=None):
    return types.SimpleNamespace(updates=list(updates), scene=scene)


class _SpyRenderer:
    def __init__(self):
        self.calls = []

    def _rec(self, name, *args):
        self.calls.append((name,) + args)

    def upload_geometry(self):    self._rec("upload_geometry")
    def upload_materials(self):   self._rec("upload_materials")
    def upload_lights(self):      self._rec("upload_lights")
    def upload_environment(self): self._rec("upload_environment")
    def update_object_transform(self, obj_id, mat16):
        self._rec("update_object_transform", obj_id, tuple(mat16))


def _make_exporter(exp, renderer_object_id_map=None):
    bpy = _stub_bpy()

    class _StubEngine:
        def __init__(self):
            self._renderer_instance_id_map = {}
            self._renderer_instancer_eligible = {}
            self._renderer_object_id_map = renderer_object_id_map or {}

        def setup_world(self, scene, renderer):
            renderer._rec("setup_world")

        def report(self, *_a, **_k):
            return None

    engine = _StubEngine()
    astroray = types.SimpleNamespace(Renderer=_SpyRenderer)
    exporter = exp.Exporter(engine, bpy, astroray)
    exporter._viewport_full_synced = True
    return exporter


# ---------------------------------------------------------------------------
# material builders
# ---------------------------------------------------------------------------

def _principled_mat(name="Mat1", base_color=0.5, emission_strength=0.0,
                    volume_out=False, displacement_out=False, extra_node=False):
    """A Principled BSDF + Material Output material. base_color varies per tick
    (the storm edit); everything else is structural."""
    principled = _Node("BSDF_PRINCIPLED", {
        "Base Color": _Socket("Base Color", default_value=[base_color, base_color, base_color, 1.0]),
        "Emission Strength": _Socket("Emission Strength", default_value=emission_strength),
    })
    output = _Node("OUTPUT_MATERIAL", {
        "Surface": _Socket("Surface", is_linked=True),
        "Volume": _Socket("Volume", is_linked=volume_out),
        "Displacement": _Socket("Displacement", is_linked=displacement_out),
    })
    nodes = [principled, output]
    if extra_node:
        nodes.append(_Node("TEX_IMAGE"))
    links = [_Link(principled, _Socket("BSDF"), output, _Socket("Surface"))]
    if volume_out:
        links.append(_Link(_Node("PRINCIPLED_VOLUME"), _Socket("Volume"), output, _Socket("Volume")))
    if displacement_out:
        links.append(_Link(_Node("BUMP"), _Socket("Normal"), output, _Socket("Displacement")))

    mat = Material(name)
    mat.node_tree = _FakeNodeTree(nodes=nodes, links=links)
    return mat


# ---------------------------------------------------------------------------
# (a) Base-Color value edit storm -> full sync (#835)
# ---------------------------------------------------------------------------

def test_base_color_storm_edits_force_full_sync():
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)

    # Post-full-sync state (fingerprints primed), then 20 Base Color value edits
    # while the worker is busy.
    exporter._materials_cache.observe([_principled_mat()])
    for i in range(20):
        exporter._record_deferred_dirty(
            _stub_depsgraph([_DepsgraphUpdate(_principled_mat(base_color=0.1 + i * 0.01))]),
            settings=None)

    # The idle commit must re-convert (full sync); an upload-only replay would
    # re-push the stale converted material.
    assert exporter._deferred_full_sync is True
    spy = _SpyRenderer()
    replayed = exporter._replay_deferred_dirty(
        spy, _stub_depsgraph([]), None, lambda *_: None, None)
    assert replayed is False
    assert spy.calls == []


def test_base_color_edit_falls_back_on_synchronous_path():
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)
    exporter._materials_cache.observe([_principled_mat()])
    spy = _SpyRenderer()
    res = exporter.apply_depsgraph_updates(
        spy, _stub_depsgraph([_DepsgraphUpdate(_principled_mat(base_color=0.9))]),
        None, lambda *_: None, None)
    assert res == 'fallback'
    assert spy.calls == []


# ---------------------------------------------------------------------------
# (b) must-still-fallback cases
# ---------------------------------------------------------------------------

def test_topology_change_falls_back():
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)

    # Prime the cache with the current topology, then edit to a topology that
    # gained a node.
    exporter._materials_cache.observe([_principled_mat()])
    exporter._record_deferred_dirty(
        _stub_depsgraph([_DepsgraphUpdate(_principled_mat(extra_node=True))]),
        settings=None)
    assert exporter._deferred_full_sync is True


def test_image_datablock_change_falls_back():
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)

    exporter._record_deferred_dirty(
        _stub_depsgraph([_DepsgraphUpdate(Image("Tex"))]), settings=None)
    assert exporter._deferred_full_sync is True


def test_material_slot_assignment_falls_back():
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)

    # A material-slot assignment tags the owning Mesh with a geometry update.
    exporter._record_deferred_dirty(
        _stub_depsgraph([_DepsgraphUpdate(Mesh("Cube.001"), geometry=True)]),
        settings=None)
    assert exporter._deferred_full_sync is True


def test_emission_strength_crossing_zero_falls_back():
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)

    # Emission OFF -> ON flips the light list.
    exporter._materials_cache.observe([_principled_mat(emission_strength=0.0)])
    exporter._record_deferred_dirty(
        _stub_depsgraph([_DepsgraphUpdate(_principled_mat(emission_strength=1.0))]),
        settings=None)
    assert exporter._deferred_full_sync is True


def test_volume_output_change_falls_back():
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)

    # Surface-only -> a Volume output appears.
    exporter._materials_cache.observe([_principled_mat()])
    exporter._record_deferred_dirty(
        _stub_depsgraph([_DepsgraphUpdate(_principled_mat(volume_out=True))]),
        settings=None)
    assert exporter._deferred_full_sync is True


def test_displacement_output_change_falls_back():
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)

    # Surface-only -> a Displacement output appears.
    exporter._materials_cache.observe([_principled_mat()])
    exporter._record_deferred_dirty(
        _stub_depsgraph([_DepsgraphUpdate(_principled_mat(displacement_out=True))]),
        settings=None)
    assert exporter._deferred_full_sync is True


# ---------------------------------------------------------------------------
# (c) transform + material mix -> full sync (#835)
# ---------------------------------------------------------------------------

def test_transform_plus_material_full_syncs():
    exp = _load_exporter_module()
    exporter = _make_exporter(exp, renderer_object_id_map={"Cube": 42})

    cube = Object("Cube")
    exporter._record_deferred_dirty(
        _stub_depsgraph([
            _DepsgraphUpdate(cube, transform=True),
            _DepsgraphUpdate(_principled_mat()),
        ]),
        settings=None)
    assert exporter._deferred_full_sync is True


# ---------------------------------------------------------------------------
# (d) #835: edits without a reconcile step full-sync on the synchronous path
# ---------------------------------------------------------------------------

def _sync_dispatch(exporter, updates):
    spy = _SpyRenderer()
    res = exporter.apply_depsgraph_updates(
        spy, _stub_depsgraph(updates), None, lambda *_: None, None)
    return res, spy.calls


def test_same_sign_emission_strength_edit_falls_back():
    # 5 -> 10 keeps the emission sign (fingerprint unchanged) but must still
    # re-convert: the #835 viewport repro edited 5 -> 10 with no visible change.
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)
    exporter._materials_cache.observe([_principled_mat(emission_strength=5.0)])
    res, calls = _sync_dispatch(
        exporter, [_DepsgraphUpdate(_principled_mat(emission_strength=10.0))])
    assert res == 'fallback'
    assert calls == []


def test_light_edit_falls_back():
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)
    res, calls = _sync_dispatch(exporter, [
        _DepsgraphUpdate(Object("Sun"), geometry=True, shading=True),
        _DepsgraphUpdate(Light("Sun"))])
    assert res == 'fallback'
    assert calls == []


def test_non_instanced_object_move_falls_back():
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)
    res, calls = _sync_dispatch(
        exporter, [_DepsgraphUpdate(Object("Sphere"), transform=True)])
    assert res == 'fallback'
    assert calls == []
