"""pkg201 Stage 1 — addon-side settings-honour fixes (pure Python, no GPU).

Covers the two Stage-1 items that close pkg200 HONEST-FAIL / known-gap rows:

  * Finding B: ``setup_world`` reads the world light-path bounce limit from
    ``world.cycles.max_bounces`` (the real Cycles prop), NOT the ambient-
    occlusion datablock ``world.light_settings.max_bounces`` (which has no such
    member, so the pre-pkg201 read was inert and getattr(..., 1024) always won).

  * use_light_tree reconciliation: ``native_settings.resolve_light_sampler``
    maps the native Cycles ``use_light_tree`` bool onto Astroray's
    uniform/power/light_tree tri-state, and ``resolve_native_settings`` folds it
    into the ResolvedSettings view so both the F12 (convert_scene) and viewport
    (sync_viewport_scene) paths honour the native toggle via the existing
    ``renderer.set_light_sampler(settings.light_sampler)`` call sites.
"""

import importlib.util
import pathlib
import sys
import types

import pytest

_ADDON = pathlib.Path(__file__).resolve().parents[1] / "blender_addon"


# --------------------------------------------------------------------------- #
# Finding B — world.cycles.max_bounces read (requires the full addon w/ mock bpy)
# --------------------------------------------------------------------------- #
def _load_blender_addon(monkeypatch, renderer_cls):
    """Load blender_addon/__init__.py with mocked bpy/astroray (pattern shared
    with test_blender_light_sampler_wiring.py)."""
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base:
        pass

    class _RenderEngineBase:
        def report(self, *_a, **_k):
            return None

    bpy_types_module.Panel = _Base
    bpy_types_module.Operator = _Base
    bpy_types_module.AddonPreferences = _Base
    bpy_types_module.PropertyGroup = _Base
    bpy_types_module.RenderEngine = _RenderEngineBase
    bpy_module.types = bpy_types_module

    for name in ("BoolProperty", "IntProperty", "FloatProperty", "StringProperty",
                 "PointerProperty", "FloatVectorProperty", "EnumProperty"):
        setattr(bpy_props_module, name, lambda **_k: None)

    bpy_module.props = bpy_props_module
    bpy_module.path = types.SimpleNamespace(abspath=lambda p: p)

    shader_blending_module = types.ModuleType("shader_blending")
    shader_blending_module.blend_shader_specs = {}
    shader_blending_module.add_shader_specs = {}

    mathutils_module = types.ModuleType("mathutils")
    mathutils_module.Vector = lambda values: values

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {"cuda": False, "spectral": True}
    astroray_module.__file__ = "/fake/astroray.pyd"
    astroray_module.Renderer = renderer_cls
    astroray_module.integrator_registry_names = lambda: ["path_tracer"]
    astroray_module.integrator_capabilities = lambda name: {
        "gpuSupported": True, "gpuFallbackReason": ""}
    astroray_module.material_registry_names = lambda: ["lambertian"]
    astroray_module.pass_registry_names = list

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    spec = importlib.util.spec_from_file_location(
        "astroray_blender_addon_pkg201_test", _ADDON / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _world(cycles_max_bounces=None, ao_max_bounces=None):
    """A minimal world with an empty node tree (so setup_world walks to the
    bounce-limit read without needing HDRI/volume node mocks)."""
    world = types.SimpleNamespace()
    world.node_tree = types.SimpleNamespace(nodes=[])
    if cycles_max_bounces is not None:
        world.cycles = types.SimpleNamespace(max_bounces=cycles_max_bounces)
    # The AO datablock. Pre-pkg201 the addon read max_bounces HERE by mistake;
    # give it a DIFFERENT value so a regression would be caught.
    world.light_settings = types.SimpleNamespace()
    if ao_max_bounces is not None:
        world.light_settings.max_bounces = ao_max_bounces
    return world


class _WorldRenderer:
    def __init__(self):
        self.world_max_bounces = None

    def set_world_volume(self, *_a):
        pass

    def set_world_max_bounces(self, v):
        self.world_max_bounces = v

    def set_background_color(self, *_a):
        pass

    def load_environment_map(self, *_a):
        return False


def test_world_max_bounces_reads_cycles_not_ao(monkeypatch):
    """setup_world must read world.cycles.max_bounces, ignoring the stray AO
    world.light_settings.max_bounces (pkg201 Finding B)."""
    addon = _load_blender_addon(monkeypatch, _WorldRenderer)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _WorldRenderer()
    scene = types.SimpleNamespace(world=_world(cycles_max_bounces=7, ao_max_bounces=99))

    engine.setup_world(scene, renderer)

    assert renderer.world_max_bounces == 7, (
        "world bounce limit must come from world.cycles.max_bounces (7), "
        f"not the AO datablock (99); got {renderer.world_max_bounces}"
    )


def test_world_max_bounces_default_when_no_cycles(monkeypatch):
    """A world without a cycles block falls back to the 1024 getattr default and
    never raises (non-Cycles scene / stub)."""
    addon = _load_blender_addon(monkeypatch, _WorldRenderer)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _WorldRenderer()
    scene = types.SimpleNamespace(world=_world(cycles_max_bounces=None, ao_max_bounces=99))

    engine.setup_world(scene, renderer)

    assert renderer.world_max_bounces == 1024


# --------------------------------------------------------------------------- #
# use_light_tree reconciliation — native_settings (no bpy needed)
# --------------------------------------------------------------------------- #
def _load_native_settings():
    if str(_ADDON) not in sys.path:
        sys.path.insert(0, str(_ADDON))
    spec = importlib.util.spec_from_file_location(
        "pkg201_native_settings", _ADDON / "native_settings.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ns = _load_native_settings()


@pytest.mark.parametrize("use_light_tree,custom,expected", [
    (True, "power", "light_tree"),       # native enable wins over any custom
    (True, "uniform", "light_tree"),
    (True, "light_tree", "light_tree"),
    (False, "uniform", "uniform"),       # native off -> defer to non-tree choice
    (False, "power", "power"),
    (False, "light_tree", "power"),      # native off overrides stale custom tree
])
def test_resolve_light_sampler_mapping(use_light_tree, custom, expected):
    cycles = types.SimpleNamespace(use_light_tree=use_light_tree)
    assert ns.resolve_light_sampler(cycles, custom) == expected


def test_resolve_light_sampler_no_cycles_falls_through():
    """No cycles datablock / no use_light_tree attr -> None (proxy keeps the
    custom value unchanged)."""
    assert ns.resolve_light_sampler(None, "uniform") is None
    assert ns.resolve_light_sampler(types.SimpleNamespace(), "uniform") is None


def _scene(cycles, light_sampler="power"):
    settings = types.SimpleNamespace(light_sampler=light_sampler)
    return types.SimpleNamespace(custom_raytracer=settings, cycles=cycles)


def test_resolve_native_settings_folds_light_tree_on():
    scene = _scene(types.SimpleNamespace(use_light_tree=True), light_sampler="power")
    resolved = ns.resolve_native_settings(scene)
    assert resolved.light_sampler == "light_tree"


def test_resolve_native_settings_light_tree_off_keeps_non_tree_choice():
    scene = _scene(types.SimpleNamespace(use_light_tree=False), light_sampler="uniform")
    resolved = ns.resolve_native_settings(scene)
    assert resolved.light_sampler == "uniform"


def test_resolve_native_settings_no_cycles_keeps_custom():
    scene = _scene(cycles=None, light_sampler="uniform")
    resolved = ns.resolve_native_settings(scene)
    assert resolved.light_sampler == "uniform"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
