"""pkg52 — persistent viewport session tests.

Three behaviors verified here, all driven by the project-owner's triage:

1. The viewport renderer is **persistent** — `view_update` and `view_draw`
   share one `astroray.Renderer` instance instead of constructing fresh.
2. `view_draw` detects camera changes (orbit / pan / wheel-zoom) by hashing
   the RegionView3D state and re-renders only when the hash changes.
3. CAMERA-view wheel-zoom (`view_camera_zoom`) is honored — the rendered
   FOV narrows as the user zooms in, instead of staying locked at the
   camera's natural framing.

Tests use the same monkeypatching pattern as test_blender_backend_policy.py.
"""

import importlib.util
import math
import sys
import types
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Shared loader helper
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
# Stubs for context / depsgraph / settings
# ---------------------------------------------------------------------------

class _Matrix4:
    """Minimal 4x4 matrix that supports `mat[i][j]` and `.inverted()`."""
    def __init__(self, rows):
        self.rows = [list(r) for r in rows]

    def __getitem__(self, i):
        return self.rows[i]

    def inverted(self):
        # The hash test only uses view_matrix, not its inverse, but the
        # free-perspective camera path may still call inverted(). Return
        # identity — the camera math is not what these tests verify.
        return _Matrix4([[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)])


def _make_context(view_matrix, region_w=320, region_h=240, lens=50.0,
                  view_camera_zoom=0.0, view_camera_offset=(0.0, 0.0),
                  view_perspective='PERSP', has_camera=False):
    rv3d = types.SimpleNamespace(
        view_matrix=view_matrix,
        view_perspective=view_perspective,
        view_camera_zoom=view_camera_zoom,
        view_camera_offset=view_camera_offset,
    )
    region = types.SimpleNamespace(width=region_w, height=region_h)
    space = types.SimpleNamespace(lens=lens)
    scene = types.SimpleNamespace(camera=None, custom_raytracer=_make_settings())
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
        light_sampler='power',
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


# ---------------------------------------------------------------------------
# 1. _camera_view_zoom_scale — the Cycles formula
# ---------------------------------------------------------------------------

def test_camera_view_zoom_scale_zero_is_unity(monkeypatch):
    """zoom=0 must produce scale=1.0 (no FOV change at the camera's natural
    framing)."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    assert abs(cls._camera_view_zoom_scale(0.0) - 1.0) < 1e-3


def test_camera_view_zoom_scale_zoom_in_narrows_fov(monkeypatch):
    """Positive zoom (wheel-in) must produce scale < 1.0 (narrower FOV)."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    assert cls._camera_view_zoom_scale(50.0) < 0.5


def test_camera_view_zoom_scale_zoom_out_widens_fov(monkeypatch):
    """Negative zoom (wheel-out) must produce scale > 1.0 (wider FOV)."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    assert cls._camera_view_zoom_scale(-30.0) > 2.0


# ---------------------------------------------------------------------------
# 2. Camera state hash — sensitive to all the right inputs
# ---------------------------------------------------------------------------

IDENTITY = _Matrix4([[1.0, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
SHIFTED = _Matrix4([[1.0, 0, 0, 1.0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])


def test_camera_hash_stable_when_nothing_changes(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    ctx_a = _make_context(IDENTITY)
    ctx_b = _make_context(IDENTITY)
    assert cls._camera_state_hash(ctx_a, ctx_a.region) == \
           cls._camera_state_hash(ctx_b, ctx_b.region)


def test_camera_hash_changes_on_view_matrix(monkeypatch):
    """Pan/orbit (view matrix change) must invalidate the hash."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    ctx_a = _make_context(IDENTITY)
    ctx_b = _make_context(SHIFTED)
    assert cls._camera_state_hash(ctx_a, ctx_a.region) != \
           cls._camera_state_hash(ctx_b, ctx_b.region)


def test_camera_hash_changes_on_camera_view_zoom(monkeypatch):
    """CAMERA-view wheel-zoom must invalidate the hash."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    ctx_a = _make_context(IDENTITY, view_camera_zoom=0.0)
    ctx_b = _make_context(IDENTITY, view_camera_zoom=50.0)
    assert cls._camera_state_hash(ctx_a, ctx_a.region) != \
           cls._camera_state_hash(ctx_b, ctx_b.region)


def test_camera_hash_changes_on_region_resize(monkeypatch):
    """Resizing the 3D viewport (region width/height) must invalidate."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    ctx_a = _make_context(IDENTITY, region_w=320, region_h=240)
    ctx_b = _make_context(IDENTITY, region_w=640, region_h=480)
    assert cls._camera_state_hash(ctx_a, ctx_a.region) != \
           cls._camera_state_hash(ctx_b, ctx_b.region)


def test_camera_hash_changes_on_lens(monkeypatch):
    """Free-perspective lens change must invalidate."""
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    ctx_a = _make_context(IDENTITY, lens=50.0)
    ctx_b = _make_context(IDENTITY, lens=85.0)
    assert cls._camera_state_hash(ctx_a, ctx_a.region) != \
           cls._camera_state_hash(ctx_b, ctx_b.region)


# ---------------------------------------------------------------------------
# 3. Persistent renderer + view_draw triggers re-render on camera change
# ---------------------------------------------------------------------------

class _RecordingRenderer:
    """Counts construction and render() calls so tests can assert reuse."""
    construction_count = 0

    def __init__(self):
        type(self).construction_count += 1
        self.render_calls = 0
        self.setup_camera_calls = []
        self.cleared = 0
        self.scene_synced = 0  # incremented by _RenderEngine wrapper

    # -- noop stubs to satisfy the addon's calls --
    def set_adaptive_sampling(self, *_): pass
    def set_clamp_direct(self, *_): pass
    def set_clamp_indirect(self, *_): pass
    def set_filter_glossy(self, *_): pass
    def set_use_reflective_caustics(self, *_): pass
    def set_use_refractive_caustics(self, *_): pass
    def set_light_sampler(self, *_): pass
    def set_wavelength_range(self, *_): pass
    def set_output_mode(self, *_): pass
    def set_integrator(self, *_): pass
    def set_use_gpu(self, *_): pass
    @property
    def gpu_available(self): return False
    def setup_camera(self, *args, **_kw):
        self.setup_camera_calls.append(args)

    def clear(self):
        self.cleared += 1

    def render(self, *_a, **_k):
        self.render_calls += 1
        return np.full((2, 2, 3), float(self.render_calls), dtype=np.float32)


def _patch_out_gpu_calls(addon, monkeypatch, engine):
    """The addon's `_update_viewport_texture` and view_draw blit need a real
    `gpu` module. For these tests we replace them with no-ops and instead
    flag that a render landed."""
    monkeypatch.setattr(engine, '_update_viewport_texture',
                        lambda pixels, w, h: setattr(engine, '_viewport_texture', object()))
    monkeypatch.setattr(addon, 'configure_backend', lambda r, s: 'cpu')


def test_renderer_is_constructed_once_across_view_updates(monkeypatch):
    """view_update + view_update + view_update must share one Renderer."""
    _RecordingRenderer.construction_count = 0
    addon = _load_blender_addon(monkeypatch, renderer_cls=_RecordingRenderer)
    engine = addon.CustomRaytracerRenderEngine()
    _patch_out_gpu_calls(addon, monkeypatch, engine)

    # Stub scene-conversion methods so view_update doesn't need a real
    # depsgraph.
    monkeypatch.setattr(engine, 'convert_materials',
                        lambda dg, r: {})
    monkeypatch.setattr(engine, 'convert_objects',
                        lambda dg, r, mm: None)
    monkeypatch.setattr(engine, 'convert_lights',
                        lambda dg, r: None)
    monkeypatch.setattr(engine, 'setup_world',
                        lambda scene, r: None)
    # Skip the real camera math (which dereferences mathutils.Vector @ ...)
    monkeypatch.setattr(engine, '_setup_viewport_camera',
                        lambda r, ctx, w, h: r.setup_camera())

    ctx = _make_context(IDENTITY)
    depsgraph = types.SimpleNamespace(scene=ctx.scene)

    engine.view_update(ctx, depsgraph)
    engine.view_update(ctx, depsgraph)
    engine.view_update(ctx, depsgraph)

    assert _RecordingRenderer.construction_count == 1, (
        f"Expected one Renderer construction, got "
        f"{_RecordingRenderer.construction_count}"
    )
    # All three view_updates rendered.
    assert engine._viewport_renderer.render_calls == 3


def test_view_draw_re_renders_when_camera_changes(monkeypatch):
    """Two view_draw calls with different view matrices must re-render."""
    _RecordingRenderer.construction_count = 0
    addon = _load_blender_addon(monkeypatch, renderer_cls=_RecordingRenderer)
    engine = addon.CustomRaytracerRenderEngine()
    _patch_out_gpu_calls(addon, monkeypatch, engine)

    monkeypatch.setattr(engine, 'convert_materials', lambda dg, r: {})
    monkeypatch.setattr(engine, 'convert_objects', lambda dg, r, mm: None)
    monkeypatch.setattr(engine, 'convert_lights', lambda dg, r: None)
    monkeypatch.setattr(engine, 'setup_world', lambda scene, r: None)
    monkeypatch.setattr(engine, '_setup_viewport_camera',
                        lambda r, ctx, w, h: r.setup_camera())
    # Stop view_draw's actual blit (no real GPU module in tests).
    monkeypatch.setattr(engine, 'bind_display_space_shader', lambda s: None)
    monkeypatch.setattr(engine, 'unbind_display_space_shader', lambda: None)

    # Initial sync (one render).
    ctx_a = _make_context(IDENTITY)
    depsgraph_a = types.SimpleNamespace(scene=ctx_a.scene)
    engine.view_update(ctx_a, depsgraph_a)
    initial_renders = engine._viewport_renderer.render_calls
    assert initial_renders == 1

    # First view_draw at the same camera state → no re-render.
    # The blit fails on bare metal (no real `gpu` module) but the camera
    # check is what we care about; swallow the import error path.
    try:
        engine.view_draw(ctx_a, depsgraph_a)
    except Exception:
        pass
    assert engine._viewport_renderer.render_calls == initial_renders, (
        "view_draw must NOT re-render when camera state is unchanged"
    )

    # Now simulate the user panning — view_matrix changes.
    ctx_b = _make_context(SHIFTED)
    depsgraph_b = types.SimpleNamespace(scene=ctx_b.scene)
    try:
        engine.view_draw(ctx_b, depsgraph_b)
    except Exception:
        pass
    assert engine._viewport_renderer.render_calls == initial_renders + 1, (
        "view_draw must re-render when view_matrix changes (pan/orbit)"
    )


class _SkipUploadRecordingRenderer(_RecordingRenderer):
    """Also captures the skip_upload flag (10th positional render arg) so
    pkg192 can assert camera-only frames avoid the per-frame geometry
    re-upload / BVH rebuild."""
    def __init__(self):
        super().__init__()
        self.skip_upload_flags = []

    def render(self, *_a, **_k):
        # render_viewport_frame passes skip_upload as the 10th positional arg.
        skip = _a[9] if len(_a) > 9 else _k.get("skip_upload", False)
        self.skip_upload_flags.append(bool(skip))
        return super().render(*_a, **_k)


def test_view_draw_camera_only_frame_skips_geometry_upload(monkeypatch):
    """pkg192: a pure camera move (orbit/pan/zoom) must re-render with
    skip_upload=True so the per-frame CPU BVH rebuild is avoided, while the
    initial full sync still uploads (skip_upload=False) to build the BVH."""
    _SkipUploadRecordingRenderer.construction_count = 0
    addon = _load_blender_addon(monkeypatch,
                                renderer_cls=_SkipUploadRecordingRenderer)
    engine = addon.CustomRaytracerRenderEngine()
    _patch_out_gpu_calls(addon, monkeypatch, engine)

    monkeypatch.setattr(engine, 'convert_materials', lambda dg, r: {})
    monkeypatch.setattr(engine, 'convert_objects', lambda dg, r, mm: None)
    monkeypatch.setattr(engine, 'convert_lights', lambda dg, r: None)
    monkeypatch.setattr(engine, 'setup_world', lambda scene, r: None)
    monkeypatch.setattr(engine, '_setup_viewport_camera',
                        lambda r, ctx, w, h: r.setup_camera())
    monkeypatch.setattr(engine, 'bind_display_space_shader', lambda s: None)
    monkeypatch.setattr(engine, 'unbind_display_space_shader', lambda: None)

    # Initial sync via view_update — must upload (build the BVH).
    ctx_a = _make_context(IDENTITY)
    depsgraph_a = types.SimpleNamespace(scene=ctx_a.scene)
    engine.view_update(ctx_a, depsgraph_a)
    r = engine._viewport_renderer
    assert r.skip_upload_flags == [False], (
        "the initial view_update sync must render with skip_upload=False "
        "so the geometry/BVH is uploaded")

    # User orbits/pans — view_matrix changes. This camera-only frame must
    # render from device state with skip_upload=True.
    ctx_b = _make_context(SHIFTED)
    depsgraph_b = types.SimpleNamespace(scene=ctx_b.scene)
    try:
        engine.view_draw(ctx_b, depsgraph_b)
    except Exception:
        pass
    assert r.skip_upload_flags[-1] is True, (
        "a camera-only view_draw frame must render with skip_upload=True "
        "(no per-frame geometry re-upload on orbit/pan/zoom)")


def test_view_draw_re_renders_on_camera_view_zoom_change(monkeypatch):
    """The user reported 'zooming in or out doesnt change how the image is
    rendered' — the view_draw camera-zoom hash must catch this."""
    _RecordingRenderer.construction_count = 0
    addon = _load_blender_addon(monkeypatch, renderer_cls=_RecordingRenderer)
    engine = addon.CustomRaytracerRenderEngine()
    _patch_out_gpu_calls(addon, monkeypatch, engine)

    monkeypatch.setattr(engine, 'convert_materials', lambda dg, r: {})
    monkeypatch.setattr(engine, 'convert_objects', lambda dg, r, mm: None)
    monkeypatch.setattr(engine, 'convert_lights', lambda dg, r: None)
    monkeypatch.setattr(engine, 'setup_world', lambda scene, r: None)
    monkeypatch.setattr(engine, '_setup_viewport_camera',
                        lambda r, ctx, w, h: r.setup_camera())
    monkeypatch.setattr(engine, 'bind_display_space_shader', lambda s: None)
    monkeypatch.setattr(engine, 'unbind_display_space_shader', lambda: None)

    ctx_a = _make_context(IDENTITY, view_perspective='CAMERA',
                          view_camera_zoom=0.0)
    depsgraph = types.SimpleNamespace(scene=ctx_a.scene)
    engine.view_update(ctx_a, depsgraph)
    baseline = engine._viewport_renderer.render_calls

    # Simulate wheel-zoom in.
    ctx_b = _make_context(IDENTITY, view_perspective='CAMERA',
                          view_camera_zoom=50.0)
    try:
        engine.view_draw(ctx_b, depsgraph)
    except Exception:
        pass
    assert engine._viewport_renderer.render_calls == baseline + 1, (
        "view_draw must re-render when view_camera_zoom changes"
    )


def test_view_draw_progresses_until_preview_sample_target(monkeypatch):
    """pkg52 progressive preview: same camera, no scene sync, keep rendering
    one-sample chunks until preview_samples is reached.

    pkg241 Phase 1a (present-first): view_update caches a chunk it does not blit,
    so the FIRST view_draw now PRESENTS that pending chunk instead of rendering
    another one (removing the material double-render). The progressive refinement
    is unchanged in substance — it just costs one extra view_draw because the
    first still-frame draw is spent presenting the already-rendered chunk before
    scheduling the next."""
    _RecordingRenderer.construction_count = 0
    addon = _load_blender_addon(monkeypatch, renderer_cls=_RecordingRenderer)
    engine = addon.CustomRaytracerRenderEngine()
    _patch_out_gpu_calls(addon, monkeypatch, engine)

    monkeypatch.setattr(engine, 'convert_materials', lambda dg, r: {})
    monkeypatch.setattr(engine, 'convert_objects', lambda dg, r, mm: None)
    monkeypatch.setattr(engine, 'convert_lights', lambda dg, r: None)
    monkeypatch.setattr(engine, 'setup_world', lambda scene, r: None)
    monkeypatch.setattr(engine, '_setup_viewport_camera',
                        lambda r, ctx, w, h: r.setup_camera())
    monkeypatch.setattr(engine, 'bind_display_space_shader', lambda s: None)
    monkeypatch.setattr(engine, 'unbind_display_space_shader', lambda: None)

    ctx = _make_context(IDENTITY)
    ctx.scene.custom_raytracer.preview_samples = 3
    depsgraph = types.SimpleNamespace(scene=ctx.scene)

    engine.view_update(ctx, depsgraph)
    assert engine._viewport_renderer.render_calls == 1
    assert engine._viewport_current_spp == 1

    # pkg241: present-first. This draw blits the pending view_update chunk; it
    # does not render a new one, so spp/render_calls hold.
    engine.view_draw(ctx, depsgraph)
    assert engine._viewport_renderer.render_calls == 1
    assert engine._viewport_current_spp == 1

    engine.view_draw(ctx, depsgraph)
    assert engine._viewport_renderer.render_calls == 2
    assert engine._viewport_current_spp == 2

    engine.view_draw(ctx, depsgraph)
    assert engine._viewport_renderer.render_calls == 3
    assert engine._viewport_current_spp == 3

    engine.view_draw(ctx, depsgraph)
    assert engine._viewport_renderer.render_calls == 3
    assert engine._viewport_current_spp == 3
    assert engine.tag_redraw_calls >= 2


class _Vec3:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z

    def __iter__(self):
        yield self.x
        yield self.y
        yield self.z

    def __sub__(self, other):
        return _Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    @property
    def length(self):
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)


class _Quat:
    def __matmul__(self, vec):
        return _Vec3(float(vec[0]), float(vec[1]), float(vec[2]))


class _CameraMatrix:
    def decompose(self):
        return _Vec3(1.0, 2.0, 3.0), _Quat(), None


def test_camera_view_offset_is_passed_as_camera_shift(monkeypatch):
    """CAMERA-view panning must affect projection, not only invalidate the hash.

    pkg193: panning/zoom/lens-shift are ALL baked into Blender's camera-view
    ``window_matrix`` off-center terms (window_matrix[0][2]/[1][2]); the addon
    now reads the image-plane shift directly from there as shiftX=m02/2,
    shiftY=m12/2 rather than additively re-deriving it from view_camera_offset +
    datablock shift (which was measured 25-223 px off Blender's overlay). This
    test supplies a window_matrix whose off-center terms encode a pan/shift and
    asserts the addon extracts the matching image-plane shift.
    """
    addon = _load_blender_addon(monkeypatch, renderer_cls=_RecordingRenderer)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    dof = types.SimpleNamespace(
        use_dof=False,
        aperture_fstop=0.0,
        focus_object=None,
        focus_distance=10.0,
    )
    camera_data = types.SimpleNamespace(
        type='PERSP',
        sensor_fit='HORIZONTAL',
        sensor_width=36.0,
        sensor_height=24.0,
        lens=50.0,
        shift_x=0.1,
        shift_y=-0.2,
        dof=dof,
    )
    camera_obj = types.SimpleNamespace(
        matrix_world=_CameraMatrix(),
        data=camera_data,
    )
    ctx = _make_context(
        IDENTITY,
        view_perspective='CAMERA',
        view_camera_offset=(0.25, -0.5),
    )
    ctx.scene.camera = camera_obj
    # Off-center window_matrix: m02=0.70 -> shiftX=0.35, m12=-1.40 -> shiftY=-0.70.
    ctx.region_data.window_matrix = _Matrix4([
        [1.3, 0.0, 0.70, 0.0],
        [0.0, 2.2, -1.40, 0.0],
        [0.0, 0.0, -1.0, -0.2],
        [0.0, 0.0, -1.0, 0.0],
    ])

    engine._setup_viewport_camera(renderer, ctx, 320, 240)

    args = renderer.setup_camera_calls[-1]
    assert len(args) == 11
    assert abs(args[9] - 0.35) < 1e-6, "shiftX must equal window_matrix[0][2]/2"
    assert abs(args[10] - (-0.7)) < 1e-6, "shiftY must equal window_matrix[1][2]/2"
