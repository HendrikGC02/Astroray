"""pkg114 inc 3d — exporter transform-only → TLAS-refit dispatch tests.

A transform-only viewport edit of an INSTANCED object (or an eligible instancer
empty) must take the cheap TLAS-only refit path — update_instance_transform per
dupli + upload_instance_transforms once + render(skip_upload=True) — and must NOT
re-upload geometry. Anything that instancing can't keep consistent with a partial
update (mixed flat+instanced batch, a poisoned/nested instancer, a non-GPU scene
with no instance map) falls back to the existing full-sync / geometry path.

These mirror the pkg56 Phase-C dispatch tests: a spy renderer records which
uploader entry points fire, driven through the REAL addon engine (so the real
refit_instance_transforms re-walk runs) with a stubbed bpy.

The refit re-derives EACH dupli's fresh matrix_world by re-walking
depsgraph.object_instances (pkg114 inc 3d) — a single obj.matrix_world is never
written onto a whole dupli group (that would collapse them).
"""

import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pytest


# --------------------------------------------------------------------------- #
# stub bpy with the bpy.types.* hierarchy the dispatcher classifies on
# --------------------------------------------------------------------------- #

class _BpyId:
    def __init__(self, name="x"):
        self.name = name


class World(_BpyId): pass
class Light(_BpyId): pass
class Material(_BpyId): pass
class NodeTree(_BpyId): pass
class Image(_BpyId): pass
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


def _load_addon(monkeypatch, renderer_cls):
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base: pass

    class _RenderEngineBase:
        def report(self, *_a, **_k): return None
        def update_progress(self, *_a, **_k): return None
        def update_stats(self, *_a, **_k): return None
        def test_break(self): return False
        def tag_redraw(self): pass

    bpy_types_module.Panel = _Base
    bpy_types_module.Operator = _Base
    bpy_types_module.AddonPreferences = _Base
    bpy_types_module.PropertyGroup = _Base
    bpy_types_module.RenderEngine = _RenderEngineBase
    bpy_types_module.World = World
    bpy_types_module.Light = Light
    bpy_types_module.Material = Material
    bpy_types_module.NodeTree = NodeTree
    bpy_types_module.ShaderNodeTree = NodeTree
    bpy_types_module.Image = Image
    bpy_types_module.Object = Object
    bpy_types_module.Scene = Scene
    bpy_module.types = bpy_types_module

    for name in ("BoolProperty", "IntProperty", "FloatProperty",
                 "StringProperty", "PointerProperty", "FloatVectorProperty",
                 "EnumProperty"):
        setattr(bpy_props_module, name, lambda **_kw: None)
    bpy_module.props = bpy_props_module
    bpy_module.path = types.SimpleNamespace(abspath=lambda p: p)

    shader_blending_module = types.ModuleType("shader_blending")
    shader_blending_module.blend_shader_specs = {}
    shader_blending_module.add_shader_specs = {}
    mathutils_module = types.ModuleType("mathutils")
    mathutils_module.Vector = lambda values: values
    mathutils_module.Matrix = types.SimpleNamespace(
        Identity=lambda n: [[1 if i == j else 0 for j in range(n)] for i in range(n)])

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {"cuda": False, "spectral": False}
    astroray_module.__file__ = "/fake/astroray.pyd"
    astroray_module.Renderer = renderer_cls
    astroray_module.integrator_registry_names = lambda: ["path_tracer"]
    astroray_module.material_registry_names = lambda: ["lambertian"]
    astroray_module.pass_registry_names = lambda: []

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    module_path = Path(__file__).parent.parent / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "astroray_blender_addon_pkg114_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# Spy renderer — records every uploader / refit entry point hit
# --------------------------------------------------------------------------- #

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

    # pkg114 inc 3d surface
    def update_instance_transform(self, iid, mat16):
        self._rec("update_instance_transform", iid, tuple(float(x) for x in mat16))

    def upload_instance_transforms(self):
        self._rec("upload_instance_transforms")

    def clear(self):                           self._rec("clear")
    def set_adaptive_sampling(self, *_):       pass
    def set_clamp_direct(self, *_):            pass
    def set_clamp_indirect(self, *_):          pass
    def set_filter_glossy(self, *_):           pass
    def set_use_reflective_caustics(self, *_): pass
    def set_use_refractive_caustics(self, *_): pass

    def names(self):
        return [c[0] for c in self.calls]


def _engine(monkeypatch):
    addon = _load_addon(monkeypatch, _SpyRenderer)
    eng = addon.CustomRaytracerRenderEngine()
    eng._viewport_renderer = _SpyRenderer()
    eng._viewport_full_synced = True
    return addon, eng, eng._viewport_renderer


def _mat(tx=0.0):
    return [[1, 0, 0, tx], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def _inst(name, matrix, *, is_instance=True, parent_name=None, instance_type='NONE'):
    obj = types.SimpleNamespace(name=name, instance_type=instance_type)
    parent = types.SimpleNamespace(name=parent_name) if parent_name is not None else None
    return types.SimpleNamespace(object=obj, matrix_world=matrix,
                                 is_instance=is_instance, parent=parent)


def _depsgraph(updates, object_instances=None, scene=None):
    return types.SimpleNamespace(
        updates=list(updates),
        object_instances=list(object_instances or []),
        scene=scene,
        mode='VIEWPORT')


# --------------------------------------------------------------------------- #
# 1. instanced SOURCE object transform-only → TLAS refit, no geometry upload
# --------------------------------------------------------------------------- #

def test_instanced_source_transform_refits(monkeypatch):
    _addon, eng, spy = _engine(monkeypatch)
    # Two duplis of "Prop" registered as instances 10 and 11.
    eng._renderer_instance_id_map = {"Prop": [10, 11]}
    eng._renderer_instancer_eligible = {}
    depsgraph = _depsgraph(
        [_DepsgraphUpdate(Object("Prop"), transform=True)],
        object_instances=[_inst("Prop", _mat(-1.6)), _inst("Prop", _mat(1.6))])

    res = eng._apply_depsgraph_updates(spy, depsgraph, settings=None)

    assert res == "dispatched"
    names = spy.names()
    assert names.count("update_instance_transform") == 2
    assert names.count("upload_instance_transforms") == 1
    assert "upload_geometry" not in names
    assert "update_object_transform" not in names
    # skip_upload flag was set on the exporter for the caller's render.
    assert eng._get_exporter()._viewport_skip_upload_next is True


# --------------------------------------------------------------------------- #
# 2. re-derive correctness — each dupli gets its OWN fresh matrix (FINDING 1)
# --------------------------------------------------------------------------- #

def test_refit_rederives_per_dupli_matrix(monkeypatch):
    _addon, eng, spy = _engine(monkeypatch)
    eng._renderer_instance_id_map = {"Prop": [10, 11]}
    eng._renderer_instancer_eligible = {}
    depsgraph = _depsgraph(
        [_DepsgraphUpdate(Object("Prop"), transform=True)],
        object_instances=[_inst("Prop", _mat(-1.6)), _inst("Prop", _mat(1.6))])

    eng._apply_depsgraph_updates(spy, depsgraph, settings=None)

    updates = [c for c in spy.calls if c[0] == "update_instance_transform"]
    by_id = {c[1]: c[2] for c in updates}
    # instance 10 gets dupli-0's matrix (tx=-1.6), instance 11 gets dupli-1's (tx=1.6);
    # a naive "obj.matrix_world onto the whole group" would give both the SAME matrix.
    assert by_id[10][3] == pytest.approx(-1.6)
    assert by_id[11][3] == pytest.approx(1.6)
    assert by_id[10] != by_id[11]


# --------------------------------------------------------------------------- #
# 3. eligible instancer EMPTY move → refit (empty not in id map, but eligible)
# --------------------------------------------------------------------------- #

def test_eligible_instancer_empty_move_refits(monkeypatch):
    _addon, eng, spy = _engine(monkeypatch)
    eng._renderer_instance_id_map = {"Prop": [10, 11]}
    eng._renderer_instancer_eligible = {"Coll": True}
    depsgraph = _depsgraph(
        [_DepsgraphUpdate(Object("Coll"), transform=True)],
        object_instances=[_inst("Prop", _mat(-1.6), parent_name="Coll"),
                          _inst("Prop", _mat(1.6), parent_name="Coll")])

    res = eng._apply_depsgraph_updates(spy, depsgraph, settings=None)

    assert res == "dispatched"
    names = spy.names()
    assert names.count("update_instance_transform") == 2
    assert names.count("upload_instance_transforms") == 1
    assert "upload_geometry" not in names
    assert eng._get_exporter()._viewport_skip_upload_next is True


# --------------------------------------------------------------------------- #
# 4. poisoned instancer (a flattened member) → full sync, no refit
# --------------------------------------------------------------------------- #

def test_poisoned_instancer_falls_back(monkeypatch):
    _addon, eng, spy = _engine(monkeypatch)
    eng._renderer_instance_id_map = {"Prop": [10, 11]}
    eng._renderer_instancer_eligible = {"Coll": False}  # has a flattened member
    depsgraph = _depsgraph(
        [_DepsgraphUpdate(Object("Coll"), transform=True)],
        object_instances=[_inst("Prop", _mat(-1.6), parent_name="Coll")])

    res = eng._apply_depsgraph_updates(spy, depsgraph, settings=None)

    assert res == "fallback"  # caller runs a full re-sync
    names = spy.names()
    assert "update_instance_transform" not in names
    assert "upload_instance_transforms" not in names
    assert eng._get_exporter()._viewport_skip_upload_next is False


# --------------------------------------------------------------------------- #
# 5. mixed batch (one flat object + one instanced source) → full sync
# --------------------------------------------------------------------------- #

def test_mixed_flat_and_instanced_falls_back(monkeypatch):
    _addon, eng, spy = _engine(monkeypatch)
    eng._renderer_instance_id_map = {"Prop": [10, 11]}
    eng._renderer_instancer_eligible = {}
    depsgraph = _depsgraph(
        [_DepsgraphUpdate(Object("Prop"), transform=True),
         _DepsgraphUpdate(Object("Floor"), transform=True)],  # flat, not in any map
        object_instances=[_inst("Prop", _mat(-1.6)), _inst("Prop", _mat(1.6))])

    res = eng._apply_depsgraph_updates(spy, depsgraph, settings=None)

    assert res == "fallback"
    names = spy.names()
    assert "update_instance_transform" not in names
    assert "upload_geometry" not in names  # fallback, not a partial upload


# --------------------------------------------------------------------------- #
# 6. CPU / non-instanced scene (empty maps) → geometry promote, never a refit
# --------------------------------------------------------------------------- #

def test_cpu_empty_maps_promotes_to_geometry(monkeypatch):
    _addon, eng, spy = _engine(monkeypatch)
    # convert_objects on CPU leaves both maps empty (instancing is GPU-only).
    eng._renderer_instance_id_map = {}
    eng._renderer_instancer_eligible = {}
    depsgraph = _depsgraph(
        [_DepsgraphUpdate(Object("Cube"), transform=True)],
        object_instances=[_inst("Cube", _mat(2.0), is_instance=False)])

    res = eng._apply_depsgraph_updates(spy, depsgraph, settings=None)

    assert res == "dispatched"
    names = spy.names()
    assert "upload_geometry" in names
    assert "update_instance_transform" not in names
    assert "upload_instance_transforms" not in names
    assert eng._get_exporter()._viewport_skip_upload_next is False


# --------------------------------------------------------------------------- #
# 7. render_viewport_frame forwards skip_upload as render()'s last positional arg
# --------------------------------------------------------------------------- #

class _RenderSpy(_SpyRenderer):
    def __init__(self):
        super().__init__()
        self.render_args = None

    def set_wavelength_range(self, *_):  pass
    def set_output_mode(self, *_):       pass
    def set_integrator(self, *_):        pass
    def clear_passes(self):              pass
    def add_pass(self, *_):              pass

    def render(self, *args):
        self.render_args = args
        return np.zeros(2 * 2 * 3, dtype=np.float32)


def _render_engine_methods():
    return {
        'viewport_render_key': lambda *a: "k",
        'viewport_target_samples': lambda s: 8,
        'viewport_chunk_samples': lambda s, cur: 4,
        'setup_viewport_camera': lambda *a: None,
        'wavelength_range_from_settings': lambda s: (380.0, 780.0),
        'effective_integrator_name': lambda s: "path_tracer",
        'resolve_denoiser_pass': lambda s: None,
        'check_gpu_limitations_and_report': lambda *a, **k: None,
        'update_viewport_texture': lambda *a: None,
        'update_viewport_status': lambda *a: None,
    }


def test_render_viewport_frame_forwards_skip_upload(monkeypatch):
    _addon, eng, _spy = _engine(monkeypatch)
    exporter = eng._get_exporter()
    renderer = _RenderSpy()
    settings = types.SimpleNamespace(
        max_bounces=6, diffuse_bounces=4, glossy_bounces=4, transmission_bounces=4,
        volume_bounces=0, transparent_bounces=8,
        viewport_display_pass="combined", viewport_oidn=False)
    region = types.SimpleNamespace(width=2, height=2)

    exporter.render_viewport_frame(renderer, context=None, settings=settings,
                                   region=region, reset_accumulation=True,
                                   engine_methods=_render_engine_methods(),
                                   skip_upload=True)

    assert renderer.render_args is not None
    # render(spp, depth, cb, gamma, d, g, t, v, tp, skip_upload) — 10 positionals.
    assert len(renderer.render_args) == 10
    assert renderer.render_args[9] is True
