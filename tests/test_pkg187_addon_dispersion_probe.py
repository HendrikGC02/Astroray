"""pkg187 — Blender addon forward-compatible Dispersion socket probe.

No shipped Blender (probed: 4.3.2 / 4.5.0 / 5.1.0 / 5.2.0) exposes a Dispersion
socket on the Principled BSDF — it is unmerged upstream WIP (Blender PR #162041).
So the addon cannot map a live socket today. Instead `_principled_native_params`
carries a FORWARD-COMPATIBLE probe:

    put_float('dispersion_scale', 'Dispersion Scale', 'Dispersion')
    put_float('dispersion_abbe',  'Dispersion Abbe Number')

This test proves the probe:
  1. is a NO-OP on a node with no dispersion inputs (today's real Blender) — so
     the engine stays non-dispersive and nothing regresses;
  2. maps the two-socket WIP layout ('Dispersion Scale' + 'Dispersion Abbe
     Number') onto dispersion_scale / dispersion_abbe;
  3. maps a single-socket 'Dispersion' alias onto dispersion_scale.

Runs OUTSIDE Blender via a mocked `bpy` (the standard addon-unit-test pattern
from tests/test_addon_dof_aperture.py), with a synthetic node carrying the
inputs the WIP will add.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _load_blender_addon(monkeypatch):
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base:
        pass

    class _RenderEngineBase:
        def report(self, *_a, **_k): return None

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

    shader_blending_module = types.ModuleType("shader_blending")
    shader_blending_module.blend_shader_specs = {}
    shader_blending_module.add_shader_specs = {}

    mathutils_module = types.ModuleType("mathutils")
    mathutils_module.Vector = lambda values: list(values)

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {"cuda": False, "spectral": True}
    astroray_module.__file__ = "/fake/astroray.pyd"
    astroray_module.integrator_registry_names = lambda: ["path_tracer"]
    astroray_module.material_registry_names = lambda: ["lambertian", "principled"]
    astroray_module.pass_registry_names = list

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    module_path = Path(__file__).parent.parent / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_pkg187", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _StubInput:
    def __init__(self, value):
        self.is_linked = False
        self.default_value = float(value)
        self.type = "VALUE"


class _StubNode:
    """A Principled-like node exposing only the given named inputs."""
    def __init__(self, sockets):
        self._inputs = {name: _StubInput(v) for name, v in sockets.items()}

    class _Inputs:
        def __init__(self, d):
            self._d = d

        def get(self, name):
            return self._d.get(name)

    @property
    def inputs(self):
        return _StubNode._Inputs(self._inputs)


def _engine(monkeypatch):
    module = _load_blender_addon(monkeypatch)
    # Skip __init__ (needs a live Blender RenderEngine); the mapping helpers only
    # use self.get_float_input / self.get_color_input, which are pure.
    return object.__new__(module.CustomRaytracerRenderEngine)


def test_probe_noop_without_dispersion_sockets(monkeypatch):
    """Today's real Blender: no dispersion socket -> engine stays non-dispersive."""
    eng = _engine(monkeypatch)
    node = _StubNode({"Metallic": 0.0, "Roughness": 0.1, "IOR": 1.5})
    p = eng._principled_native_params(node)
    assert "dispersion_scale" not in p
    assert "dispersion_abbe" not in p


def test_probe_maps_two_socket_wip_layout(monkeypatch):
    """PR #162041 two-socket layout round-trips onto the engine param names."""
    eng = _engine(monkeypatch)
    node = _StubNode({
        "IOR": 1.5,
        "Transmission Weight": 1.0,
        "Dispersion Scale": 0.7,
        "Dispersion Abbe Number": 15.0,
    })
    p = eng._principled_native_params(node)
    assert p["dispersion_scale"] == pytest.approx(0.7)
    assert p["dispersion_abbe"] == pytest.approx(15.0)


def test_probe_single_socket_dispersion_alias(monkeypatch):
    """A one-socket 'Dispersion' build aliases onto dispersion_scale."""
    eng = _engine(monkeypatch)
    node = _StubNode({"IOR": 1.5, "Dispersion": 0.5})
    p = eng._principled_native_params(node)
    assert p["dispersion_scale"] == pytest.approx(0.5)
    assert "dispersion_abbe" not in p
