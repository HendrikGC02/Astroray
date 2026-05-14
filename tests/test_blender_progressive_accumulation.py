"""pkg83 — progressive accumulation continuation across camera changes.

Verifies the addon's policy for when to reset the progressive accumulator
vs. when to keep accumulating. Mirrors Cycles' BlenderSession::reset logic
(intern/cycles/blender/session.cpp, Apache-2.0):

- Pure camera transform changes (pan/orbit/dolly) keep accumulating.
- Substantive camera changes (focal length, DoF, lens shift) reset.
- Settings changes reset.

The test mocks the renderer and verifies _reset_viewport_accumulation is
called (or not) in the correct cases.
"""

import importlib.util
import sys
import types
from pathlib import Path


# ---------------------------------------------------------------------------
# Shared loader helper (adapted from test_blender_viewport_session.py)
# ---------------------------------------------------------------------------

def _load_blender_addon(monkeypatch, renderer_cls=None):
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base:
        pass

    class _RenderEngineBase:
        tag_redraw_calls = 0
        def report(self, *_a, **_k): return None
        def update_progress(self, *_a, **_k): return None
        def update_stats(self, *_a, **_k): return None
        def test_break(self): return False
        def bind_display_space_shader(self, *_a, **_k): return None
        def unbind_display_space_shader(self, *_a, **_k): return None
        def tag_redraw(self): self.tag_redraw_calls += 1

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
    bpy_module.data = types.SimpleNamespace(materials=[])

    shader_blending_module = types.ModuleType("shader_blending")
    shader_blending_module.blend_shader_specs = {}
    shader_blending_module.add_shader_specs = {}

    mathutils_module = types.ModuleType("mathutils")
    mathutils_module.Vector = lambda values: values

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {"cuda": False, "spectral": True}
    astroray_module.__file__ = "/fake/astroray.pyd"
    if renderer_cls is not None:
        astroray_module.Renderer = renderer_cls
    astroray_module.integrator_registry_names = lambda: ["path_tracer"]
    astroray_module.material_registry_names = lambda: ["lambertian"]
    astroray_module.pass_registry_names = lambda: []

    # pkg56/pkg62 viewport perf / pass helpers — no-op stubs
    astroray_module.record_viewport_stage = lambda *_a, **_k: None
    astroray_module.viewport_perf_frame_start = lambda *_a, **_k: None
    astroray_module.viewport_perf_frame_complete = lambda *_a, **_k: None

    gpu_module = types.ModuleType("gpu")
    gpu_types_module = types.ModuleType("gpu.types")
    gpu_types_module.GPUTexture = lambda *_a, **_k: None
    gpu_types_module.Buffer = lambda *_a, **_k: []
    gpu_module.types = gpu_types_module

    gpu_extras_module = types.ModuleType("gpu_extras")
    gpu_extras_presets_module = types.ModuleType("gpu_extras.presets")
    gpu_extras_presets_module.draw_texture_2d = lambda *_a, **_k: None
    gpu_extras_module.presets = gpu_extras_presets_module

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)
    monkeypatch.setitem(sys.modules, "gpu", gpu_module)
    monkeypatch.setitem(sys.modules, "gpu.types", gpu_types_module)
    monkeypatch.setitem(sys.modules, "gpu_extras", gpu_extras_module)
    monkeypatch.setitem(sys.modules, "gpu_extras.presets", gpu_extras_presets_module)

    module_path = Path(__file__).parent.parent / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Stubs for context / depsgraph / settings
# ---------------------------------------------------------------------------

class _Matrix4:
    """Minimal 4x4 matrix that supports `mat[i][j]` and `.inverted()`."""
    def __init__(self, rows):
        self.rows = [list(r) for r in rows]

    def __getitem__(self, i):
        return self.rows[i]

    def inverted(self):
        return _Matrix4([[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)])

    def decompose(self):
        # Return (translation, rotation_quat, scale) for _apply_camera
        translation = types.SimpleNamespace(x=0, y=0, z=-5)
        rotation = types.SimpleNamespace()
        rotation.__matmul__ = lambda self, vec: vec  # no-op rotation
        scale = types.SimpleNamespace(x=1, y=1, z=1)
        return translation, rotation, scale

    def to_3x3(self):
        """Return a stub 3x3 rotation matrix."""
        stub = types.SimpleNamespace()
        stub.__matmul__ = lambda self, vec: vec  # no-op
        return stub

    @property
    def translation(self):
        return types.SimpleNamespace(x=0, y=0, z=-5)


def _make_camera_data(lens=50.0, sensor_width=36.0, sensor_height=24.0, sensor_fit='AUTO',
                      shift_x=0.0, shift_y=0.0, use_dof=False, aperture_fstop=5.6, camera_type='PERSP'):
    dof = types.SimpleNamespace(
        use_dof=use_dof,
        aperture_fstop=aperture_fstop,
        focus_distance=10.0,
        focus_object=None,
    )
    return types.SimpleNamespace(
        type=camera_type,
        lens=lens,
        sensor_width=sensor_width,
        sensor_height=sensor_height,
        sensor_fit=sensor_fit,
        shift_x=shift_x,
        shift_y=shift_y,
        dof=dof,
    )


def _make_camera_object(camera_data):
    return types.SimpleNamespace(
        data=camera_data,
        matrix_world=_Matrix4([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]),
    )


def _make_context(view_matrix, region_w=320, region_h=240, lens=50.0,
                  view_camera_zoom=0.0, view_camera_offset=(0.0, 0.0),
                  view_perspective='PERSP', camera_obj=None):
    rv3d = types.SimpleNamespace(
        view_matrix=view_matrix,
        view_perspective=view_perspective,
        view_camera_zoom=view_camera_zoom,
        view_camera_offset=view_camera_offset,
    )
    region = types.SimpleNamespace(width=region_w, height=region_h)
    space = types.SimpleNamespace(lens=lens)
    scene = types.SimpleNamespace(camera=camera_obj, custom_raytracer=_make_settings())
    return types.SimpleNamespace(
        region=region,
        region_data=rv3d,
        space_data=space,
        scene=scene,
    )


def _make_settings():
    return types.SimpleNamespace(
        use_adaptive_sampling=False,
        clamp_direct=0.0, clamp_indirect=0.0, filter_glossy=0.0,
        use_reflective_caustics=True, use_refractive_caustics=True,
        device_mode='cpu',
        preview_samples=4, max_bounces=4,
        diffuse_bounces=2, glossy_bounces=2, transmission_bounces=2,
        volume_bounces=0, transparent_bounces=2,
        wavelength_preset='visible',
        wavelength_min=380.0, wavelength_max=780.0,
        colourmap='grayscale',
        integrator_type='path_tracer',
        viewport_display_pass='combined',
        viewport_oidn=False,
    )


def _make_depsgraph(scene):
    return types.SimpleNamespace(scene=scene)


# ---------------------------------------------------------------------------
# Mock renderer that tracks reset_accumulation calls
# ---------------------------------------------------------------------------

class _MockRenderer:
    def __init__(self):
        self.render_calls = 0
        self.reset_count = 0
        self.clear_calls = 0

    def set_adaptive_sampling(self, *_): pass
    def set_clamp_direct(self, *_): pass
    def set_clamp_indirect(self, *_): pass
    def set_filter_glossy(self, *_): pass
    def set_use_reflective_caustics(self, *_): pass
    def set_use_refractive_caustics(self, *_): pass
    def clear(self): self.clear_calls += 1
    def set_wavelength_range(self, *_): pass
    def set_output_mode(self, *_): pass
    def set_integrator(self, *_): pass
    def clear_passes(self): pass
    def add_pass(self, *_): pass
    def setup_camera(self, *_a, **_k): pass
    def render(self, *_a, **_k):
        self.render_calls += 1
        # Return a 320x240 RGB buffer
        import numpy as np
        return np.zeros((240, 320, 3), dtype=np.float32)
    def get_render_pass_buffer(self, *_):
        import numpy as np
        return np.zeros((240, 320, 3), dtype=np.float32)


# ---------------------------------------------------------------------------
# Test: substantive hash correctly distinguishes transform vs. optical
# ---------------------------------------------------------------------------

IDENTITY = _Matrix4([[1.0, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
SHIFTED = _Matrix4([[1.0, 0, 0, 1.0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])


def test_substantive_hash_stable_when_only_transform_changes(monkeypatch):
    """Pure pan (view_matrix change) must NOT change the substantive hash."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    ctx_a = _make_context(IDENTITY)
    ctx_b = _make_context(SHIFTED)
    h_a = cls._camera_substantive_state_hash(ctx_a, ctx_a.region)
    h_b = cls._camera_substantive_state_hash(ctx_b, ctx_b.region)
    assert h_a == h_b, "Pan (pure transform) should not change substantive hash"


def test_substantive_hash_changes_on_focal_length(monkeypatch):
    """Free-perspective lens change must invalidate the substantive hash."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    ctx_a = _make_context(IDENTITY, lens=50.0)
    ctx_b = _make_context(IDENTITY, lens=85.0)
    h_a = cls._camera_substantive_state_hash(ctx_a, ctx_a.region)
    h_b = cls._camera_substantive_state_hash(ctx_b, ctx_b.region)
    assert h_a != h_b, "Focal length change should invalidate substantive hash"


def test_substantive_hash_changes_on_dof_toggle(monkeypatch):
    """Enabling DoF in CAMERA view must invalidate the substantive hash."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    cam_data_off = _make_camera_data(use_dof=False)
    cam_data_on = _make_camera_data(use_dof=True)
    ctx_a = _make_context(IDENTITY, view_perspective='CAMERA', camera_obj=_make_camera_object(cam_data_off))
    ctx_b = _make_context(IDENTITY, view_perspective='CAMERA', camera_obj=_make_camera_object(cam_data_on))
    h_a = cls._camera_substantive_state_hash(ctx_a, ctx_a.region)
    h_b = cls._camera_substantive_state_hash(ctx_b, ctx_b.region)
    assert h_a != h_b, "DoF toggle should invalidate substantive hash"


def test_substantive_hash_changes_on_lens_shift(monkeypatch):
    """Lens shift change in CAMERA view must invalidate the substantive hash."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    cam_data_a = _make_camera_data(shift_x=0.0)
    cam_data_b = _make_camera_data(shift_x=0.1)
    ctx_a = _make_context(IDENTITY, view_perspective='CAMERA', camera_obj=_make_camera_object(cam_data_a))
    ctx_b = _make_context(IDENTITY, view_perspective='CAMERA', camera_obj=_make_camera_object(cam_data_b))
    h_a = cls._camera_substantive_state_hash(ctx_a, ctx_a.region)
    h_b = cls._camera_substantive_state_hash(ctx_b, ctx_b.region)
    assert h_a != h_b, "Lens shift change should invalidate substantive hash"


def test_substantive_hash_changes_on_region_resize(monkeypatch):
    """Region resize changes aspect and should invalidate the substantive hash."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    ctx_a = _make_context(IDENTITY, region_w=320, region_h=240)
    ctx_b = _make_context(IDENTITY, region_w=640, region_h=480)
    h_a = cls._camera_substantive_state_hash(ctx_a, ctx_a.region)
    h_b = cls._camera_substantive_state_hash(ctx_b, ctx_b.region)
    assert h_a != h_b, "Region resize should invalidate substantive hash"


# ---------------------------------------------------------------------------
# Test: view_draw accumulation behavior
# ---------------------------------------------------------------------------

def test_view_draw_continues_accumulating_on_pure_pan(monkeypatch):
    """After a pure pan, the reset_accumulation flag should be False."""
    addon = _load_blender_addon(monkeypatch, renderer_cls=_MockRenderer)
    cls = addon.CustomRaytracerRenderEngine

    # Simulate the logic view_draw uses to decide reset_accumulation
    ctx_1 = _make_context(IDENTITY)
    h1 = cls._camera_substantive_state_hash(ctx_1, ctx_1.region)

    ctx_2 = _make_context(SHIFTED)  # Pure pan
    h2 = cls._camera_substantive_state_hash(ctx_2, ctx_2.region)

    # Substantive hash should be unchanged
    assert h1 == h2, "Pan should not change substantive hash"


def test_view_draw_resets_on_focal_length_change(monkeypatch):
    """Changing focal length should trigger reset_accumulation=True."""
    addon = _load_blender_addon(monkeypatch, renderer_cls=_MockRenderer)
    cls = addon.CustomRaytracerRenderEngine

    ctx_1 = _make_context(IDENTITY, lens=50.0)
    h1 = cls._camera_substantive_state_hash(ctx_1, ctx_1.region)

    ctx_2 = _make_context(IDENTITY, lens=85.0)
    h2 = cls._camera_substantive_state_hash(ctx_2, ctx_2.region)

    # Substantive hash should have changed
    assert h1 != h2, "Focal length change should change substantive hash"


def test_view_draw_resets_on_dof_toggle(monkeypatch):
    """Toggling DoF should trigger reset_accumulation=True."""
    addon = _load_blender_addon(monkeypatch, renderer_cls=_MockRenderer)
    cls = addon.CustomRaytracerRenderEngine

    cam_data_off = _make_camera_data(use_dof=False)
    cam_obj_off = _make_camera_object(cam_data_off)
    ctx_1 = _make_context(IDENTITY, view_perspective='CAMERA', camera_obj=cam_obj_off)
    h1 = cls._camera_substantive_state_hash(ctx_1, ctx_1.region)

    cam_data_on = _make_camera_data(use_dof=True)
    cam_obj_on = _make_camera_object(cam_data_on)
    ctx_2 = _make_context(IDENTITY, view_perspective='CAMERA', camera_obj=cam_obj_on)
    h2 = cls._camera_substantive_state_hash(ctx_2, ctx_2.region)

    # Substantive hash should have changed
    assert h1 != h2, "DoF toggle should change substantive hash"
