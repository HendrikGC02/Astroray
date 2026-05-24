"""Test for pkg103b Camera Motion Blur wiring.

Verifies that Blender's scene.render.use_motion_blur reaches
renderer.set_camera_motion_blur() with correctly decomposed T/R/S components.
"""

import importlib.util
import sys
import types
from pathlib import Path


def _load_blender_addon(monkeypatch, renderer_cls):
    """Load the Blender addon with mocked bpy/astroray modules.

    Same pattern as test_blender_light_sampler_wiring.py.
    """
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base:
        pass

    class _RenderEngineBase:
        def report(self, *_args, **_kwargs):
            return None
        def update_progress(self, *_args, **_kwargs):
            return None
        def test_break(self):
            return False

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

    # Minimal mathutils mock with Matrix.decompose() support
    class MockVector:
        def __init__(self, xyz):
            self.x, self.y, self.z = xyz[0], xyz[1], xyz[2]

    class MockQuaternion:
        def __init__(self, wxyz):
            self.w, self.x, self.y, self.z = wxyz[0], wxyz[1], wxyz[2], wxyz[3]

    class MockMatrix:
        def __init__(self, rows):
            self._rows = rows

        def decompose(self):
            # Return (translation, rotation_quat, scale) — hardcoded for test
            # For a static camera, T/R/S are identical at t_start and t_end
            return (
                MockVector([1.0, 2.0, 3.0]),   # translation
                MockQuaternion([1.0, 0.0, 0.0, 0.0]),  # rotation (identity)
                MockVector([1.0, 1.0, 1.0])    # scale
            )

        def copy(self):
            return MockMatrix(self._rows)

    mathutils_module = types.ModuleType("mathutils")
    mathutils_module.Vector = MockVector
    mathutils_module.Quaternion = MockQuaternion
    mathutils_module.Matrix = MockMatrix

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {"cuda": False, "spectral": True}
    astroray_module.__file__ = "/fake/astroray.pyd"
    astroray_module.Renderer = renderer_cls
    astroray_module.integrator_registry_names = lambda: ["path_tracer", "ambient_occlusion"]
    astroray_module.integrator_capabilities = lambda name: {
        "gpuSupported": name in {"path_tracer", "ambient_occlusion"},
        "gpuFallbackReason": "" if name in {"path_tracer", "ambient_occlusion"} else "no GPU kernel implemented",
    }
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


def _make_settings(**kwargs):
    """Create a mock CustomRayTracerSettings namespace with required fields."""
    defaults = {
        "device_mode": "auto",
        "wavelength_preset": "visible",
        "wavelength_min": 380.0,
        "wavelength_max": 780.0,
        "colourmap": "grayscale",
        "integrator_type": "path_tracer",
        "last_render_stats": "",
        "use_adaptive_sampling": False,
        "preview_samples": 1,
        "samples": 16,
        "max_bounces": 4,
        "clamp_direct": 0.0,
        "clamp_indirect": 0.0,
        "filter_glossy": 0.0,
        "use_reflective_caustics": True,
        "use_refractive_caustics": True,
        "diffuse_bounces": 2,
        "glossy_bounces": 2,
        "transmission_bounces": 2,
        "volume_bounces": 0,
        "transparent_bounces": 2,
        "light_sampler": "power",
    }
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


def test_camera_motion_blur_disabled_by_default(monkeypatch):
    """When use_motion_blur=False, set_camera_motion_blur must NOT be called."""
    calls = []

    class MockRenderer:
        gpu_available = False
        def clear(self): pass
        def set_clamp_direct(self, v): pass
        def set_clamp_indirect(self, v): pass
        def set_filter_glossy(self, v): pass
        def set_use_reflective_caustics(self, v): pass
        def set_use_refractive_caustics(self, v): pass
        def set_light_sampler(self, mode): pass
        def set_film_exposure(self, v): pass
        def set_use_transparent_film(self, v): pass
        def set_transparent_glass(self, v): pass
        def set_seed(self, v): pass
        def set_pixel_filter(self, t, w): pass
        def set_camera_motion_blur(self, *args, **kwargs):
            calls.append(args)

    addon = _load_blender_addon(monkeypatch, MockRenderer)
    engine = addon.CustomRaytracerRenderEngine()

    settings = _make_settings()
    scene = types.SimpleNamespace(
        custom_raytracer=settings,
        cycles=None,
        render=types.SimpleNamespace(use_motion_blur=False),
        camera=None,
        frame_current=1,
    )
    depsgraph = types.SimpleNamespace(scene=scene, object_instances=[])

    # Patch methods that need geometry/camera conversion
    engine.setup_camera = lambda *a: None
    engine.convert_materials = lambda *a: {}
    engine.convert_objects = lambda *a: None
    engine.convert_lights = lambda *a: None
    engine.setup_world = lambda *a: None

    engine.convert_scene(depsgraph, MockRenderer(), 16, 16)

    assert len(calls) == 0, "set_camera_motion_blur must NOT be called when use_motion_blur=False"


def test_camera_motion_blur_enabled(monkeypatch):
    """When use_motion_blur=True, set_camera_motion_blur must be called with decomposed T/R/S."""
    calls = []

    class MockRenderer:
        gpu_available = False
        def clear(self): pass
        def set_clamp_direct(self, v): pass
        def set_clamp_indirect(self, v): pass
        def set_filter_glossy(self, v): pass
        def set_use_reflective_caustics(self, v): pass
        def set_use_refractive_caustics(self, v): pass
        def set_light_sampler(self, mode): pass
        def set_film_exposure(self, v): pass
        def set_use_transparent_film(self, v): pass
        def set_transparent_glass(self, v): pass
        def set_seed(self, v): pass
        def set_pixel_filter(self, t, w): pass
        def set_camera_motion_blur(self, start_t, start_r, start_s, end_t, end_r, end_s, shutter, position):
            calls.append({
                'start_t': start_t,
                'start_r': start_r,
                'start_s': start_s,
                'end_t': end_t,
                'end_r': end_r,
                'end_s': end_s,
                'shutter': shutter,
                'position': position,
            })

    addon = _load_blender_addon(monkeypatch, MockRenderer)
    engine = addon.CustomRaytracerRenderEngine()

    # Mock camera object with matrix_world
    class MockMatrix:
        def decompose(self):
            # Minimal mock: return static T/R/S
            import types
            loc = types.SimpleNamespace(x=1.0, y=2.0, z=3.0)
            rot = types.SimpleNamespace(w=1.0, x=0.0, y=0.0, z=0.0)
            scale = types.SimpleNamespace(x=1.0, y=1.0, z=1.0)
            return loc, rot, scale
        def copy(self):
            return self

    camera_obj = types.SimpleNamespace(
        matrix_world=MockMatrix(),
        evaluated_get=lambda dg: types.SimpleNamespace(matrix_world=MockMatrix()),
    )

    settings = _make_settings()
    scene = types.SimpleNamespace(
        custom_raytracer=settings,
        cycles=None,
        render=types.SimpleNamespace(
            use_motion_blur=True,
            motion_blur_shutter=0.5,
            motion_blur_position='CENTER',
        ),
        camera=camera_obj,
        frame_current=10,
        frame_subframe=0.0,
        frame_set=lambda frame, subframe: None,
    )
    depsgraph = types.SimpleNamespace(scene=scene, object_instances=[], update=lambda: None)

    # Patch methods that need geometry/camera conversion
    engine.setup_camera = lambda *a: None
    engine.convert_materials = lambda *a: {}
    engine.convert_objects = lambda *a: None
    engine.convert_lights = lambda *a: None
    engine.setup_world = lambda *a: None

    engine.convert_scene(depsgraph, MockRenderer(), 16, 16)

    assert len(calls) == 1, "set_camera_motion_blur must be called once when use_motion_blur=True"

    call = calls[0]
    # Verify decomposed components are lists
    assert isinstance(call['start_t'], list) and len(call['start_t']) == 3
    assert isinstance(call['start_r'], list) and len(call['start_r']) == 4  # quaternion [w,x,y,z]
    assert isinstance(call['start_s'], list) and len(call['start_s']) == 3
    assert isinstance(call['end_t'], list) and len(call['end_t']) == 3
    assert isinstance(call['end_r'], list) and len(call['end_r']) == 4
    assert isinstance(call['end_s'], list) and len(call['end_s']) == 3
    # Verify shutter and position
    assert call['shutter'] == 0.5
    assert call['position'] == 1  # CENTER = 1


def test_camera_motion_blur_shutter_positions(monkeypatch):
    """Verify all three shutter positions (START, CENTER, END) map correctly."""
    for blender_pos, expected_code in [('START', 0), ('CENTER', 1), ('END', 2)]:
        calls = []

        class MockRenderer:
            gpu_available = False
            def clear(self): pass
            def set_clamp_direct(self, v): pass
            def set_clamp_indirect(self, v): pass
            def set_filter_glossy(self, v): pass
            def set_use_reflective_caustics(self, v): pass
            def set_use_refractive_caustics(self, v): pass
            def set_light_sampler(self, mode): pass
            def set_film_exposure(self, v): pass
            def set_use_transparent_film(self, v): pass
            def set_transparent_glass(self, v): pass
            def set_seed(self, v): pass
            def set_pixel_filter(self, t, w): pass
            def set_camera_motion_blur(self, start_t, start_r, start_s, end_t, end_r, end_s, shutter, position):
                calls.append(position)

        addon = _load_blender_addon(monkeypatch, MockRenderer)
        engine = addon.CustomRaytracerRenderEngine()

        class MockMatrix:
            def decompose(self):
                import types
                loc = types.SimpleNamespace(x=0.0, y=0.0, z=0.0)
                rot = types.SimpleNamespace(w=1.0, x=0.0, y=0.0, z=0.0)
                scale = types.SimpleNamespace(x=1.0, y=1.0, z=1.0)
                return loc, rot, scale
            def copy(self):
                return self

        camera_obj = types.SimpleNamespace(
            matrix_world=MockMatrix(),
            evaluated_get=lambda dg: types.SimpleNamespace(matrix_world=MockMatrix()),
        )

        settings = _make_settings()
        scene = types.SimpleNamespace(
            custom_raytracer=settings,
            cycles=None,
            render=types.SimpleNamespace(
                use_motion_blur=True,
                motion_blur_shutter=1.0,
                motion_blur_position=blender_pos,
            ),
            camera=camera_obj,
            frame_current=5,
            frame_subframe=0.0,
            frame_set=lambda frame, subframe: None,
        )
        depsgraph = types.SimpleNamespace(scene=scene, object_instances=[], update=lambda: None)

        engine.setup_camera = lambda *a: None
        engine.convert_materials = lambda *a: {}
        engine.convert_objects = lambda *a: None
        engine.convert_lights = lambda *a: None
        engine.setup_world = lambda *a: None

        engine.convert_scene(depsgraph, MockRenderer(), 16, 16)

        assert len(calls) == 1
        assert calls[0] == expected_code, \
            f"motion_blur_position='{blender_pos}' must map to {expected_code}, got {calls[0]}"
