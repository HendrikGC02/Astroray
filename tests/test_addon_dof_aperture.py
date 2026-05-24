"""pkg102 — Blender addon DOF aperture unit conversion.

The addon must compute aperture using the photographic relation
`aperture_radius = focal_length_m / (2 * fstop)` (matching Cycles), then pass
**diameter** to the C++ Camera (which halves it to get lensRadius).

This test constructs a stub Blender camera and asserts:
1. With use_dof=True, lens=50mm, fstop=5.6 → aperture ≈ 0.00893 m (diameter).
2. With use_dof=False → aperture = 0.0 (no DOF).

The test must fail on HEAD (before fix) and pass after fix.
"""

import importlib.util
import math
import sys
import types
from pathlib import Path


# ---------------------------------------------------------------------------
# Shared loader helper (from test_addon_viewport_camera_vfov.py pattern)
# ---------------------------------------------------------------------------

def _load_blender_addon(monkeypatch):
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

    mathutils_module = types.ModuleType("mathutils")
    mathutils_module.Vector = lambda values: _Vec3(*values)

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {"cuda": False, "spectral": True}
    astroray_module.__file__ = "/fake/astroray.pyd"
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
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Matrix stubs (minimal for camera transform)
# ---------------------------------------------------------------------------

class _Vec3:
    """Minimal 3D vector."""
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z

    def __getitem__(self, i):
        if i == 0: return self.x
        if i == 1: return self.y
        if i == 2: return self.z
        raise IndexError(f"Vector index {i} out of range")

    def __sub__(self, other):
        return _Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    @property
    def length(self):
        return math.sqrt(self.x**2 + self.y**2 + self.z**2)


class _Quaternion:
    """Minimal quaternion (identity rotation)."""
    def __init__(self):
        pass

    def __matmul__(self, vec):
        # Identity rotation: return vec as-is.
        return _Vec3(vec[0], vec[1], vec[2])


class _Matrix4:
    """Minimal 4x4 matrix that supports .translation, .decompose()."""
    def __init__(self, rows):
        self.rows = [list(r) for r in rows]

    def __getitem__(self, i):
        return self.rows[i]

    @property
    def translation(self):
        return _Vec3(self.rows[0][3], self.rows[1][3], self.rows[2][3])

    def decompose(self):
        """Return (location, rotation, scale). For simplicity, return identity."""
        loc = self.translation
        rot = _Quaternion()
        scale = _Vec3(1.0, 1.0, 1.0)
        return loc, rot, scale

    def to_3x3(self):
        class _Mat3:
            def __init__(self, rows):
                self.rows = rows
            def __matmul__(self, vec):
                return _Vec3(
                    self.rows[0][0]*vec[0] + self.rows[0][1]*vec[1] + self.rows[0][2]*vec[2],
                    self.rows[1][0]*vec[0] + self.rows[1][1]*vec[1] + self.rows[1][2]*vec[2],
                    self.rows[2][0]*vec[0] + self.rows[2][1]*vec[1] + self.rows[2][2]*vec[2],
                )
        return _Mat3([
            [self.rows[0][0], self.rows[0][1], self.rows[0][2]],
            [self.rows[1][0], self.rows[1][1], self.rows[1][2]],
            [self.rows[2][0], self.rows[2][1], self.rows[2][2]],
        ])

    def inverted(self):
        return _Matrix4([[1.0 if i==j else 0.0 for j in range(4)] for i in range(4)])


# ---------------------------------------------------------------------------
# Stub renderer
# ---------------------------------------------------------------------------

class _RecordingRenderer:
    """Minimal renderer stub that records setup_camera calls."""
    def __init__(self):
        self.setup_camera_calls = []

    def set_adaptive_sampling(self, *_): pass
    def set_clamp_direct(self, *_): pass
    def set_clamp_indirect(self, *_): pass
    def set_filter_glossy(self, *_): pass
    def set_use_reflective_caustics(self, *_): pass
    def set_use_refractive_caustics(self, *_): pass
    def set_wavelength_range(self, *_): pass
    def set_output_mode(self, *_): pass
    def set_integrator(self, *_): pass
    def set_use_gpu(self, *_): pass

    @property
    def gpu_available(self):
        return False

    def setup_camera(self, *args, **_kw):
        self.setup_camera_calls.append(args)


# ---------------------------------------------------------------------------
# Test: DOF aperture computation
# ---------------------------------------------------------------------------

def test_dof_aperture_enabled(monkeypatch):
    """With use_dof=True, lens=50mm, fstop=5.6, the addon must pass
    aperture ≈ 0.00893 m (diameter) to setup_camera.

    Formula (Cycles): aperture_radius = focal_length_m / (2 * fstop)
    → aperture_diameter = 2 * aperture_radius
                        = focal_length_m / fstop
                        = 0.050 / 5.6 ≈ 0.00893 m

    On HEAD (before fix): aperture = 1/(2*5.6) ≈ 0.0893 (10× too large).
    After fix: aperture ≈ 0.00893.
    """
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    # Stub camera with DOF enabled.
    camera_matrix = _Matrix4([
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, -5],
        [0, 0, 0, 1],
    ])
    camera_obj = types.SimpleNamespace(
        matrix_world=camera_matrix,
        data=types.SimpleNamespace(
            type='PERSP',
            lens=50.0,  # 50mm
            sensor_width=36.0,
            sensor_height=24.0,
            sensor_fit='AUTO',
            shift_x=0.0,
            shift_y=0.0,
            dof=types.SimpleNamespace(
                use_dof=True,
                aperture_fstop=5.6,
                focus_object=None,
                focus_distance=3.0,
            ),
        ),
    )

    scene = types.SimpleNamespace(
        camera=camera_obj,
        custom_raytracer=types.SimpleNamespace(
            use_adaptive_sampling=False,
            clamp_direct=0.0, clamp_indirect=0.0, filter_glossy=0.0,
            use_reflective_caustics=True, use_refractive_caustics=True,
            device_mode='cpu',
            preview_samples=1, max_bounces=4,
            diffuse_bounces=2, glossy_bounces=2, transmission_bounces=2,
            volume_bounces=0, transparent_bounces=2,
            wavelength_preset='visible',
            wavelength_min=380.0, wavelength_max=780.0,
            colourmap='grayscale',
            integrator_type='path_tracer',
            viewport_display_pass='combined',
            viewport_oidn=False,
        )
    )

    # Call _apply_camera (internal method that computes aperture).
    engine._apply_camera(renderer, camera_obj, 320, 240)

    # Extract aperture from setup_camera call.
    # setup_camera signature: (look_from, look_at, vup, vfov, aspect,
    #                           aperture, focus_dist, width, height, shift_x, shift_y)
    args = renderer.setup_camera_calls[-1]
    aperture = args[5]

    # Expected: diameter = focal_length_m / fstop = 0.050 / 5.6 ≈ 0.008928571
    expected_aperture = 0.050 / 5.6
    assert abs(aperture - expected_aperture) / expected_aperture < 0.01, (
        f"DOF aperture mismatch: expected {expected_aperture:.6f} m (diameter), "
        f"got {aperture:.6f} m. Formula must be: aperture_radius = focal_length_m / (2*fstop), "
        f"then pass 2*aperture_radius as diameter."
    )


def test_dof_aperture_disabled(monkeypatch):
    """With use_dof=False, the addon must pass aperture=0.0 to setup_camera
    (no defocus blur)."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    camera_matrix = _Matrix4([
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, -5],
        [0, 0, 0, 1],
    ])
    camera_obj = types.SimpleNamespace(
        matrix_world=camera_matrix,
        data=types.SimpleNamespace(
            type='PERSP',
            lens=50.0,
            sensor_width=36.0,
            sensor_height=24.0,
            sensor_fit='AUTO',
            shift_x=0.0,
            shift_y=0.0,
            dof=types.SimpleNamespace(
                use_dof=False,  # DOF disabled
                aperture_fstop=5.6,
                focus_object=None,
                focus_distance=3.0,
            ),
        ),
    )

    scene = types.SimpleNamespace(
        camera=camera_obj,
        custom_raytracer=types.SimpleNamespace(
            use_adaptive_sampling=False,
            clamp_direct=0.0, clamp_indirect=0.0, filter_glossy=0.0,
            use_reflective_caustics=True, use_refractive_caustics=True,
            device_mode='cpu',
            preview_samples=1, max_bounces=4,
            diffuse_bounces=2, glossy_bounces=2, transmission_bounces=2,
            volume_bounces=0, transparent_bounces=2,
            wavelength_preset='visible',
            wavelength_min=380.0, wavelength_max=780.0,
            colourmap='grayscale',
            integrator_type='path_tracer',
            viewport_display_pass='combined',
            viewport_oidn=False,
        )
    )

    engine._apply_camera(renderer, camera_obj, 320, 240)

    args = renderer.setup_camera_calls[-1]
    aperture = args[5]

    assert aperture == 0.0, (
        f"With use_dof=False, aperture must be 0.0 (no DOF), got {aperture}."
    )
