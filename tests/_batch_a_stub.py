"""Shared stub-bpy loader for the Batch A addon-parity tests.

Loads blender_addon/__init__.py against a stub `bpy` (the same pattern as
tests/test_issue772_shaderless_world_black.py) so the pure export/translation
logic can be exercised without a real Blender. A minimal numpy-backed
`mathutils.Euler`/`Matrix` (consistent with the engine's XYZ convention,
R = Rz*Ry*Rx) is installed so the #796 world-Mapping inverse path is testable.
"""
import importlib.util
import math
import sys
import types
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Minimal mathutils (Euler + Matrix) matching the engine XYZ convention.
# --------------------------------------------------------------------------- #
class _Matrix:
    def __init__(self, arr):
        self._m = np.asarray(arr, dtype=float)

    def transposed(self):
        return _Matrix(self._m.T)

    def to_euler(self, order='XYZ'):
        assert order == 'XYZ'
        R = self._m
        ry = math.asin(max(-1.0, min(1.0, -R[2][0])))
        rx = math.atan2(R[2][1], R[2][2])
        rz = math.atan2(R[1][0], R[0][0])
        return _Euler((rx, ry, rz), 'XYZ')


class _Euler:
    def __init__(self, angles, order='XYZ'):
        self.x, self.y, self.z = float(angles[0]), float(angles[1]), float(angles[2])
        self.order = order

    def to_matrix(self):
        cx, sx = math.cos(self.x), math.sin(self.x)
        cy, sy = math.cos(self.y), math.sin(self.y)
        cz, sz = math.cos(self.z), math.sin(self.z)
        # R = Rz(z) * Ry(y) * Rx(x), row-major (matches raytracer.h buildRotMat).
        R = [
            [cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
            [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
            [-sy,     cy * sx,                cy * cx],
        ]
        return _Matrix(R)


def _make_mathutils():
    m = types.ModuleType("mathutils")
    m.Euler = _Euler
    m.Matrix = _Matrix

    class _Vector:
        def __init__(self, xyz):
            self.x, self.y, self.z = xyz

    m.Vector = _Vector
    return m


def load_addon(monkeypatch, module_suffix="batch_a"):
    """Load blender_addon against stub bpy + a working mathutils. Returns the
    imported module object."""
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base:
        pass

    class _RenderEngineBase:
        def report(self, *_a, **_k): return None
        def update_progress(self, *_a, **_k): return None
        def update_stats(self, *_a, **_k): return None
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

    shader_blending_module = types.ModuleType("shader_blending")
    shader_blending_module.blend_shader_specs = {}
    shader_blending_module.add_shader_specs = {}

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {"cuda": False, "spectral": True}
    astroray_module.__file__ = "/fake/astroray.pyd"
    astroray_module.integrator_registry_names = lambda: ["path_tracer"]
    astroray_module.material_registry_names = lambda: ["lambertian", "principled", "disney"]
    astroray_module.pass_registry_names = lambda: []

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", _make_mathutils())
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    module_path = REPO_ROOT / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "astroray_blender_addon_%s_test" % module_suffix, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RecordingRenderer:
    """Captures the engine calls the addon makes during setup/convert."""
    def __init__(self):
        self.env_map_calls = []
        self.background_calls = []
        self.render_region_calls = []
        self.clear_region_calls = 0
        self.world_volume_calls = []
        self.world_max_bounces = None

    def load_environment_map(self, *a, **k):
        self.env_map_calls.append((a, k))
        return True

    def set_background_color(self, color):
        self.background_calls.append(list(color))

    def set_world_volume(self, *a, **k):
        self.world_volume_calls.append((a, k))

    def set_world_max_bounces(self, n):
        self.world_max_bounces = n

    def set_render_region(self, x0, y0, x1, y1):
        self.render_region_calls.append((x0, y0, x1, y1))

    def clear_render_region(self):
        self.clear_region_calls += 1
