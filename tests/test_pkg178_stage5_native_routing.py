"""pkg178 Stage 5 — Blender Principled BSDF -> native 'principled' routing.

Stub-Blender tests (no live Blender process). Assert:
  * flag ON (default) -> a Principled node produces a create_material(
    'principled', ...) call with the mapped native params (coat/sheen/aniso/
    alpha present, Cycles socket names).
  * flag OFF -> the Disney path is unchanged (create_material('disney', ...)
    with the historical alpha->transmission conflation).
  * alpha routes through the native 'alpha' param on the flagged path (NOT the
    transmission conflation — the BSDF_TRANSPARENT bug family this stage retires).

Shape mirrors tests/test_blender_native_nodes.py.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_blender_addon(monkeypatch):
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base:
        pass

    class _RenderEngineBase:
        def report(self, *a, **k): return None
        def update_progress(self, *a, **k): return None
        def test_break(self): return False

    bpy_types_module.Panel = _Base
    bpy_types_module.Operator = _Base
    bpy_types_module.AddonPreferences = _Base
    bpy_types_module.PropertyGroup = _Base
    bpy_types_module.RenderEngine = _RenderEngineBase
    bpy_module.types = bpy_types_module

    for name in ("BoolProperty", "IntProperty", "FloatProperty", "StringProperty",
                 "PointerProperty", "FloatVectorProperty", "EnumProperty"):
        setattr(bpy_props_module, name, lambda **_kwargs: None)
    bpy_module.props = bpy_props_module
    bpy_module.path = types.SimpleNamespace(abspath=lambda p: p)

    # Use the real shader_blending module (native_params blending is exercised
    # indirectly by the addon import; the mix path is not under test here).
    sys.path.insert(0, str(REPO_ROOT / "blender_addon"))

    mathutils_module = types.ModuleType("mathutils")
    mathutils_module.Vector = lambda values: values

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {"cuda": False, "spectral": True}
    astroray_module.__file__ = "/fake/astroray.pyd"
    astroray_module.integrator_registry_names = lambda: ["path_tracer"]
    astroray_module.material_registry_names = lambda: ["lambertian", "disney", "principled"]
    astroray_module.pass_registry_names = lambda: []

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    sys.modules.pop("astroray_blender_addon_test", None)
    module_path = REPO_ROOT / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# --- Stub Blender data primitives ---

class _Socket:
    def __init__(self, default=0.0, socket_type="VALUE"):
        self.default_value = default
        self.is_linked = False
        self.links = []
        self.type = socket_type


class _Node:
    def __init__(self, ntype="", bl_idname="", inputs=None):
        self.type = ntype
        self.bl_idname = bl_idname
        self.inputs = inputs or {}


class _RecordingRenderer:
    def __init__(self):
        self.created_materials = []
        self._next_id = 1

    def create_material(self, mat_type, color, params):
        self.created_materials.append((mat_type, list(color), dict(params)))
        mid = self._next_id
        self._next_id += 1
        return mid

    def set_material_spectral_profile(self, *a, **k): pass
    def clear_material_spectral_profile(self, *a, **k): pass


def _principled_node():
    """A Blender-5.2-shaped Principled node with coat/sheen/aniso/alpha set."""
    return _Node(
        ntype="BSDF_PRINCIPLED",
        bl_idname="ShaderNodeBsdfPrincipled",
        inputs={
            'Base Color':          _Socket(default=(0.6, 0.3, 0.2, 1.0), socket_type="RGBA"),
            'Metallic':            _Socket(default=0.25),
            'Roughness':           _Socket(default=0.4),
            'IOR':                 _Socket(default=1.5),
            'Alpha':               _Socket(default=0.7),
            'Diffuse Roughness':   _Socket(default=0.1),
            'Subsurface Weight':   _Socket(default=0.0),
            'Subsurface Radius':   _Socket(default=(1.0, 0.2, 0.1), socket_type="VECTOR"),
            'Subsurface Scale':    _Socket(default=0.05),
            'Specular IOR Level':  _Socket(default=0.5),
            'Specular Tint':       _Socket(default=(1.0, 1.0, 1.0, 1.0), socket_type="RGBA"),
            'Anisotropic':         _Socket(default=0.8),
            'Anisotropic Rotation':_Socket(default=0.25),
            'Transmission Weight': _Socket(default=0.0),
            'Coat Weight':         _Socket(default=0.9),
            'Coat Roughness':      _Socket(default=0.15),
            'Coat IOR':            _Socket(default=1.5),
            'Coat Tint':           _Socket(default=(0.8, 0.9, 1.0, 1.0), socket_type="RGBA"),
            'Sheen Weight':        _Socket(default=0.6),
            'Sheen Roughness':     _Socket(default=0.3),
            'Sheen Tint':          _Socket(default=(1.0, 0.5, 0.5, 1.0), socket_type="RGBA"),
            'Subsurface Anisotropy': _Socket(default=0.0),
            'Thin Film Thickness': _Socket(default=0.0),
            'Thin Film IOR':       _Socket(default=1.33),
            'Thin Wall':           _Socket(default=False, socket_type="VALUE"),
            'Emission Color':      _Socket(default=(0.0, 0.0, 0.0, 1.0), socket_type="RGBA"),
            'Emission Strength':   _Socket(default=0.0),
            'Normal':              _Socket(socket_type="VECTOR"),
        },
    )


def _engine(addon, native_flag):
    engine = addon.CustomRaytracerRenderEngine()
    engine._use_native_principled_flag = native_flag
    return engine


def test_flag_on_routes_to_native_with_mapped_params(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon, native_flag=True)

    node = _principled_node()
    spec = engine._principled_shader_spec(node, renderer=None)
    renderer = _RecordingRenderer()
    engine._create_material_from_shader_spec(spec, renderer)

    assert len(renderer.created_materials) == 1
    mat_type, color, params = renderer.created_materials[0]
    assert mat_type == "principled", f"flag ON must route to native; got {mat_type!r}"
    assert abs(color[0] - 0.6) < 1e-5

    # Native Cycles socket names present with the mapped values.
    assert abs(params["metallic"] - 0.25) < 1e-6
    assert abs(params["coat_weight"] - 0.9) < 1e-6
    assert abs(params["coat_roughness"] - 0.15) < 1e-6
    assert abs(params["coat_ior"] - 1.5) < 1e-6
    assert params["coat_tint"] == [0.8, 0.9, 1.0]
    assert abs(params["sheen_weight"] - 0.6) < 1e-6
    assert abs(params["sheen_roughness"] - 0.3) < 1e-6
    assert params["sheen_tint"] == [1.0, 0.5, 0.5]
    assert abs(params["anisotropic"] - 0.8) < 1e-6
    assert abs(params["anisotropic_rotation"] - 0.25) < 1e-6
    assert abs(params["specular_ior_level"] - 0.5) < 1e-6
    assert params["specular_tint"] == [1.0, 1.0, 1.0]
    assert abs(params["diffuse_roughness"] - 0.1) < 1e-6
    assert params["subsurface_radius"] == [1.0, 0.2, 0.1]

    # Alpha is a REAL native param, NOT folded into transmission.
    assert abs(params["alpha"] - 0.7) < 1e-6
    assert abs(params.get("transmission_weight", 0.0)) < 1e-6, (
        "native path must NOT conflate alpha into transmission")
    assert "transmission" not in params, (
        "native path must not emit the Disney 'transmission' key")


def test_flag_off_disney_path_unchanged(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon, native_flag=False)

    node = _principled_node()
    spec = engine._principled_shader_spec(node, renderer=None)
    renderer = _RecordingRenderer()
    engine._create_material_from_shader_spec(spec, renderer)

    assert len(renderer.created_materials) == 1
    mat_type, _color, params = renderer.created_materials[0]
    assert mat_type == "disney", f"flag OFF must keep the Disney path; got {mat_type!r}"
    # Disney param names (byte-unchanged fallback). The Disney parse historically
    # never read the Alpha socket at all (alpha only entered via a Mix-with-
    # Transparent), so a plain Principled leaves transmission at 0 and carries no
    # 'alpha' key — the native path is what finally honours the Alpha socket.
    assert "clearcoat" in params
    assert "coat_weight" not in params
    assert abs(params.get("transmission", 0.0)) < 1e-6
    assert "alpha" not in params


def test_default_flag_is_native_on(monkeypatch):
    """The experimental build ships native Principled ON by default: a fresh
    engine with no convert_materials() call routes to 'principled'."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()  # no flag set

    node = _principled_node()
    spec = engine._principled_shader_spec(node, renderer=None)
    renderer = _RecordingRenderer()
    engine._create_material_from_shader_spec(spec, renderer)

    mat_type, _color, _params = renderer.created_materials[0]
    assert mat_type == "principled", (
        f"default (unset) flag must be native ON; got {mat_type!r}")


def test_thin_film_thin_wall_route_native(monkeypatch):
    """pkg178 Stage 4/5: Thin Film Thickness/IOR, Thin Wall and Subsurface
    Anisotropy are wired to the native material (engine gained them on main).
    A Principled node with those set routes to create_material('principled', ...)
    with the four native params present and NOT reported as gaps."""
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon, native_flag=True)
    engine._degradation = None  # fresh report accumulator

    node = _principled_node()
    node.inputs['Thin Film Thickness'].default_value = 550.0
    node.inputs['Thin Film IOR'].default_value = 1.4
    node.inputs['Thin Wall'].default_value = True
    node.inputs['Subsurface Anisotropy'].default_value = 0.3

    spec = engine._principled_shader_spec(node, renderer=None)
    renderer = _RecordingRenderer()
    engine._create_material_from_shader_spec(spec, renderer)

    assert len(renderer.created_materials) == 1
    mat_type, _color, params = renderer.created_materials[0]
    assert mat_type == "principled", f"flag ON must route to native; got {mat_type!r}"

    assert abs(params["thin_film_thickness"] - 550.0) < 1e-4
    assert abs(params["thin_film_ior"] - 1.4) < 1e-6
    # Thin Wall boolean -> 1.0 float (engine reads thin_wall>0.5).
    assert abs(params["thin_wall"] - 1.0) < 1e-6
    assert abs(params["subsurface_anisotropy"] - 0.3) < 1e-6

    # These four are no longer pkg119-C gaps.
    report = engine._degradation_report()
    text = " ".join(report.messages())
    assert "Thin Film" not in text and "Thin Wall" not in text, (
        f"thin-film/thin-wall must NOT be reported as dropped now; got {report.messages()!r}")


def test_subsurface_gap_reported_on_native_path(monkeypatch):
    """pkg119-C: an active subsurface weight is reported as approximated on the
    native path (never silently dropped)."""
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon, native_flag=True)
    engine._degradation = None  # fresh report accumulator

    node = _principled_node()
    node.inputs['Subsurface Weight'].default_value = 0.5
    spec = engine._principled_shader_spec(node, renderer=None)
    renderer = _RecordingRenderer()
    engine._create_material_from_shader_spec(spec, renderer)

    report = engine._degradation_report()
    text = " ".join(report.messages())
    assert "Subsurface" in text or "subsurface" in text, (
        "an active subsurface weight must surface a pkg119-C approximation line; "
        f"got {report.messages()!r}")
