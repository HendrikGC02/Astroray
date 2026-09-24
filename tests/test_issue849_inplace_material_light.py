"""#849 — in-place viewport material / light re-sync (no full sync per edit).

Part 1 (bpy-free, stubbed engine): a Base Color edit re-converts ONLY the edited
material from Blender and rebinds it behind the primitives' id, so the value
that reaches the renderer is the NEW one; a light edit re-runs convert_lights
over the dedicated-light range the last sync recorded. Anything the in-place
path cannot represent still full-syncs.

Part 2 (engine): rebind_material / remove_dedicated_lights change the rendered
image (pre-edit frame != post-edit frame), CPU and GPU.
"""

import importlib.util
import types
from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# stub bpy / depsgraph (same pattern as test_issue721_storm_material_domain.py)
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
    def __init__(self, name="obj", otype="MESH"):
        super().__init__(name)
        self.type = otype
        self.matrix_world = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


class _Upd:
    def __init__(self, id, *, geometry=False, transform=False, shading=False):
        self.id = id
        self.is_updated_geometry = geometry
        self.is_updated_transform = transform
        self.is_updated_shading = shading


class _Socket:
    def __init__(self, name, default_value=0.0, is_linked=False):
        self.name = name
        self.default_value = default_value
        self.is_linked = is_linked


class _Inputs:
    def __init__(self, sockets):
        self._s = sockets

    def get(self, name):
        return self._s.get(name)

    def __iter__(self):
        return iter(self._s.values())


class _Node:
    def __init__(self, ntype, inputs=None):
        self.type = ntype
        self.inputs = _Inputs(inputs or {})


class _Link:
    def __init__(self, fn, fs, tn, ts):
        self.from_node, self.from_socket, self.to_node, self.to_socket = fn, fs, tn, ts


def _principled_mat(name="Mat1", base=0.5):
    p = _Node("BSDF_PRINCIPLED", {
        "Base Color": _Socket("Base Color", [base, base, base, 1.0]),
        "Emission Strength": _Socket("Emission Strength", 0.0)})
    out = _Node("OUTPUT_MATERIAL", {"Surface": _Socket("Surface", is_linked=True)})
    m = Material(name)
    m.node_tree = types.SimpleNamespace(
        nodes=[p, out], links=[_Link(p, _Socket("BSDF"), out, _Socket("Surface"))])
    return m


class _Mats(dict):
    """bpy.data.materials stand-in: iterable over values, .get by name."""
    def __iter__(self):
        return iter(self.values())


def _load_exporter():
    path = Path(__file__).parent.parent / "blender_addon" / "exporter.py"
    spec = importlib.util.spec_from_file_location("astroray_exporter_849", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeEngineRenderer:
    """Models the engine contract the in-place path relies on: primitives hold
    a material by reference; rebind_material swaps it; dedicated lights are a
    list the range bookkeeping indexes."""

    def __init__(self):
        self.materials = {}          # id -> base colour
        self.next_id = 0
        self.prim_material = {}      # prim -> the material VALUE it renders with
        self.prim_id = {}            # prim -> material id
        self.dedicated = []          # (name, energy)
        self.calls = []
        self.refuse = False

    def create_material(self, base):
        i = self.next_id
        self.next_id += 1
        self.materials[i] = base
        return i

    def add_prim(self, prim, mat_id):
        self.prim_id[prim] = mat_id
        self.prim_material[prim] = self.materials[mat_id]

    def rebind_material(self, old_id, new_id):
        self.calls.append(("rebind_material", old_id, new_id))
        if self.refuse:
            return False
        for prim, mid in self.prim_id.items():
            if mid == old_id:
                self.prim_material[prim] = self.materials[new_id]
        self.materials[old_id] = self.materials.pop(new_id)
        return True

    def set_material_name(self, *_a):
        pass

    def dedicated_light_count(self):
        return len(self.dedicated)

    def remove_dedicated_lights(self, start, count):
        self.calls.append(("remove_dedicated_lights", start, count))
        del self.dedicated[start:start + count]

    def upload_materials(self):   self.calls.append(("upload_materials",))
    def upload_lights(self):      self.calls.append(("upload_lights",))
    def upload_geometry(self):    self.calls.append(("upload_geometry",))
    def upload_environment(self): self.calls.append(("upload_environment",))


def _setup(exp, lights=None):
    """Exporter whose last full sync converted Mat1 (id 0) onto prim 'sphere',
    dedicated lights [lights..., sky_sun] with convert_lights owning `lights`."""
    bpy = types.ModuleType("bpy")
    t = types.ModuleType("bpy.types")
    for k in (World, Light, Material, NodeTree, Image, Object, Mesh, Scene):
        setattr(t, k.__name__, k)
    t.ShaderNodeTree = NodeTree
    bpy.types = t
    mat = _principled_mat()
    bpy.data = types.SimpleNamespace(materials=_Mats(Mat1=mat))
    blender_lights = dict(lights or {})   # name -> energy (the live Blender state)

    class _Engine:
        _renderer_instance_id_map = {}
        _renderer_instancer_eligible = {}
        _renderer_object_id_map = {}
        _volume_material_map = {}
        _generated_textures_by_material = {}

        def convert_node_material(self, m, renderer):
            # Re-reads the live socket value, like the real converter.
            return renderer.create_material(
                m.node_tree.nodes[0].inputs.get("Base Color").default_value[0])

        def convert_lights(self, depsgraph, renderer):
            for name, energy in blender_lights.items():
                renderer.dedicated.append((name, energy))

        def setup_world(self, scene, renderer):
            pass

        def report(self, *_a, **_k):
            pass

    eng = _Engine()
    r = _FakeEngineRenderer()
    mid = r.create_material(0.5)
    r.add_prim("sphere", mid)
    eng.convert_lights(None, r)
    r.dedicated.append(("sky_sun", 1.0))   # setup_world lamp, outside the range

    exporter = exp.Exporter(eng, bpy, types.SimpleNamespace(Renderer=_FakeEngineRenderer))
    exporter._viewport_renderer = r
    exporter._viewport_full_synced = True
    exporter._viewport_material_ids = {"Mat1": mid}
    exporter._viewport_light_range = (0, len(blender_lights))
    exporter._materials_cache.observe([mat])
    return exporter, r, mat, blender_lights


def _dg(updates):
    return types.SimpleNamespace(updates=list(updates), scene=None)


def _edit_base(mat, value):
    mat.node_tree.nodes[0].inputs.get("Base Color").default_value = [value] * 3 + [1.0]


# ---------------------------------------------------------------------------
# Part 1: exporter routing (bpy-free)
# ---------------------------------------------------------------------------

def test_base_color_edit_reaches_primitive_without_full_sync():
    exp = _load_exporter()
    exporter, r, mat, _ = _setup(exp)
    _edit_base(mat, 0.9)
    res = exporter.apply_depsgraph_updates(
        r, _dg([_Upd(mat), _Upd(Object("Sphere"), shading=True)]), None,
        lambda *_: None, None)
    assert res == 'dispatched'
    assert r.prim_material["sphere"] == 0.9          # the NEW value is rendered
    names = [c[0] for c in r.calls]
    assert names.index("rebind_material") < names.index("upload_materials")
    assert "upload_geometry" not in names
    # The id the primitives hold keeps naming the material for the next edit.
    _edit_base(mat, 0.2)
    assert exporter.apply_depsgraph_updates(
        r, _dg([_Upd(mat)]), None, lambda *_: None, None) == 'dispatched'
    assert r.prim_material["sphere"] == 0.2


def test_deferred_storm_replays_latest_value_in_place():
    exp = _load_exporter()
    exporter, r, mat, _ = _setup(exp)
    for i in range(10):                        # worker busy: record only
        _edit_base(mat, 0.1 + 0.05 * i)
        exporter._record_deferred_dirty(_dg([_Upd(mat)]), None)
    assert exporter._deferred_full_sync is False
    assert r.calls == []
    assert exporter._replay_deferred_dirty(r, _dg([]), None, lambda *_: None, None)
    assert r.prim_material["sphere"] == pytest.approx(0.55)
    assert [c[0] for c in r.calls].count("rebind_material") == 1   # coalesced


def test_engine_refusal_falls_back_to_full_sync():
    exp = _load_exporter()
    exporter, r, mat, _ = _setup(exp)
    r.refuse = True                            # e.g. an emitter / pkg114 BLAS holder
    _edit_base(mat, 0.9)
    res = exporter.apply_depsgraph_updates(r, _dg([_Upd(mat)]), None,
                                           lambda *_: None, None)
    assert res == 'fallback'
    assert ("upload_materials",) not in r.calls


def test_volume_or_generated_material_falls_back():
    exp = _load_exporter()
    for attr in ("_volume_material_map", "_generated_textures_by_material"):
        exporter, r, mat, _ = _setup(exp)
        setattr(exporter.engine, attr, {"Mat1": {"x": 1}})
        _edit_base(mat, 0.9)
        assert exporter.apply_depsgraph_updates(
            r, _dg([_Upd(mat)]), None, lambda *_: None, None) == 'fallback'
        assert r.prim_material["sphere"] == 0.5


def test_no_sync_state_or_no_bindings_falls_back():
    exp = _load_exporter()
    exporter, r, mat, _ = _setup(exp)
    exporter._viewport_material_ids = None     # no full sync recorded the ids
    _edit_base(mat, 0.9)
    assert exporter.apply_depsgraph_updates(
        r, _dg([_Upd(mat)]), None, lambda *_: None, None) == 'fallback'


def test_light_energy_edit_resyncs_light_range_only():
    exp = _load_exporter()
    exporter, r, _mat, blender = _setup(exp, lights={"Lamp": 10.0, "Key": 3.0})
    blender["Lamp"] = 20.0                     # the Blender edit
    lamp = Object("Lamp", otype="LIGHT")
    res = exporter.apply_depsgraph_updates(
        r, _dg([_Upd(Light("Lamp")), _Upd(lamp, geometry=True, shading=True)]),
        None, lambda *_: None, None)
    assert res == 'dispatched'
    assert sorted(r.dedicated) == [("Key", 3.0), ("Lamp", 20.0), ("sky_sun", 1.0)]
    assert ("upload_lights",) in r.calls and ("upload_geometry",) not in r.calls
    # A second edit removes exactly the re-added range again.
    blender["Key"] = 6.0
    assert exporter.apply_depsgraph_updates(
        r, _dg([_Upd(lamp, transform=True)]), None,
        lambda *_: None, None) == 'dispatched'
    assert sorted(r.dedicated) == [("Key", 6.0), ("Lamp", 20.0), ("sky_sun", 1.0)]


def test_mesh_object_move_still_full_syncs():
    exp = _load_exporter()
    exporter, r, _mat, _ = _setup(exp)
    assert exporter.apply_depsgraph_updates(
        r, _dg([_Upd(Object("Cube"), transform=True)]), None,
        lambda *_: None, None) == 'fallback'


# ---------------------------------------------------------------------------
# Part 2: engine bindings change the rendered frame
# ---------------------------------------------------------------------------

def _renderer(astroray, device):
    r = astroray.Renderer()
    if device == "gpu":
        if not getattr(r, "gpu_available", False):
            pytest.skip("CUDA not available")
        r.set_use_gpu(True)
    r.setup_camera(look_from=[0, 0, 4], look_at=[0, 0, 0], vup=[0, 1, 0],
                   vfov=40.0, aspect_ratio=1.0, aperture=0.0, focus_dist=4.0,
                   width=24, height=24)
    return r


def _centre(img):
    img = np.asarray(img, dtype=np.float64).reshape(24, 24, -1)
    return img[9:15, 9:15, :3].mean(axis=(0, 1))


@pytest.mark.parametrize("device", ["cpu", "gpu"])
def test_rebind_material_changes_render(astroray_module, device):
    r = _renderer(astroray_module, device)
    red = r.create_material("diffuse", [0.8, 0.05, 0.05], {})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, red)
    r.add_point_light([0.0, 0.0, 4.0], {"mode": "rgb", "color": [1, 1, 1]}, 400.0,
                      0.0, "", 0, 0)
    before = _centre(r.render(16, 4, None, False))
    green = r.create_material("diffuse", [0.05, 0.8, 0.05], {})
    assert r.rebind_material(red, green) is True
    r.upload_materials()
    after = _centre(r.render(16, 4, None, False))
    assert before[0] > 4 * before[1]           # pre-edit frame is red
    assert after[1] > 4 * after[0]             # post-edit frame is green
    # The old id now names the new material: a second rebind through it works.
    blue = r.create_material("diffuse", [0.05, 0.05, 0.8], {})
    assert r.rebind_material(red, blue) is True
    assert _centre(r.render(16, 4, None, False))[2] > 4 * after[0]


def test_rebind_material_refuses_emitters(astroray_module):
    r = _renderer(astroray_module, "cpu")
    lamp = r.create_material("emission", [1, 1, 1], {"intensity": 5.0})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, lamp)
    diffuse = r.create_material("diffuse", [0.5, 0.5, 0.5], {})
    assert r.rebind_material(lamp, diffuse) is False


@pytest.mark.parametrize("device", ["cpu", "gpu"])
def test_remove_dedicated_lights_resyncs_energy(astroray_module, device):
    r = _renderer(astroray_module, device)
    grey = r.create_material("diffuse", [0.5, 0.5, 0.5], {})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, grey)
    r.add_point_light([0.0, 0.0, 4.0], {"mode": "rgb", "color": [1, 1, 1]}, 100.0,
                      0.0, "", 0, 0)
    before = _centre(r.render(16, 4, None, False)).mean()
    assert r.dedicated_light_count() == 1
    r.remove_dedicated_lights(0, 1)
    assert r.dedicated_light_count() == 0
    r.upload_lights()
    ambient = _centre(r.render(16, 4, None, False)).mean()   # default background only
    assert ambient < 0.8 * before                            # the lamp really went
    r.add_point_light([0.0, 0.0, 4.0], {"mode": "rgb", "color": [1, 1, 1]}, 200.0,
                      0.0, "", 0, 0)
    r.upload_lights()
    after = _centre(r.render(16, 4, None, False)).mean()
    assert after - ambient == pytest.approx(2.0 * (before - ambient), rel=0.1)
