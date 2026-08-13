"""pkg196 — reduced-resolution viewport navigation state machine.

While the camera is actively moving, view_draw renders at region/N resolution
(upscaled on display); once the view has been quiet for VIEWPORT_NAV_SETTLE_S it
snaps back to full resolution and hands off to the pkg191 progressive loop.
Accumulation resets on every resolution switch (never blend mixed-res buffers).

Cycles reference: intern/cycles/blender/session.cpp BlenderSession::reset +
start_resolution (Apache-2.0).

These drive the REAL addon engine through a mock RenderEngine (recording
renderer, stubbed bpy) with an injectable nav clock, so the settle debounce is
exercised deterministically without wall-clock sleeps.
"""

import importlib.util
import sys
import types
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Loader + stubs (same shape as test_blender_viewport_session.py)
# ---------------------------------------------------------------------------

def _load_blender_addon(monkeypatch, renderer_cls):
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base:
        pass

    class _RenderEngineBase:
        def __init__(self):
            self.tag_redraw_calls = 0
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
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_pkg196", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Matrix4:
    def __init__(self, rows):
        self.rows = [list(r) for r in rows]

    def __getitem__(self, i):
        return self.rows[i]

    def inverted(self):
        return _Matrix4([[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)])


IDENTITY = _Matrix4([[1.0, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
SHIFTED = _Matrix4([[1.0, 0, 0, 1.0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
SHIFTED2 = _Matrix4([[1.0, 0, 0, 2.0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])


def _make_settings():
    return types.SimpleNamespace(
        use_adaptive_sampling=False,
        clamp_direct=0.0, clamp_indirect=0.0, filter_glossy=0.0,
        use_reflective_caustics=True, use_refractive_caustics=True,
        light_sampler='power', device_mode='cpu',
        preview_samples=1, max_bounces=4,
        diffuse_bounces=2, glossy_bounces=2, transmission_bounces=2,
        volume_bounces=0, transparent_bounces=2,
        wavelength_preset='visible', wavelength_min=380.0, wavelength_max=780.0,
        colourmap='grayscale', integrator_type='path_tracer',
        viewport_display_pass='combined', viewport_oidn=False,
    )


def _make_context(view_matrix, region_w=320, region_h=240):
    rv3d = types.SimpleNamespace(
        view_matrix=view_matrix, view_perspective='PERSP',
        view_camera_zoom=0.0, view_camera_offset=(0.0, 0.0))
    region = types.SimpleNamespace(width=region_w, height=region_h)
    space = types.SimpleNamespace(lens=50.0)
    scene = types.SimpleNamespace(camera=None, custom_raytracer=_make_settings())
    return types.SimpleNamespace(region=region, region_data=rv3d,
                                 space_data=space, scene=scene)


class _RecordingRenderer:
    def __init__(self):
        self.render_calls = 0

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
    def clear(self): pass
    def clear_passes(self): pass
    def add_pass(self, *_): pass
    @property
    def gpu_available(self): return False
    def setup_camera(self, *args, **_kw): pass

    def render(self, *_a, **_k):
        self.render_calls += 1
        return np.full((2, 2, 3), float(self.render_calls), dtype=np.float32)


def _wire(monkeypatch, renderer_cls=_RecordingRenderer):
    """Load addon, build engine, stub scene sync + camera + display path.
    Returns (addon, engine, clock, dims) where clock is a mutable [t] list
    driving the nav-settle debounce and dims records rendered (w, h)."""
    addon = _load_blender_addon(monkeypatch, renderer_cls)
    engine = addon.CustomRaytracerRenderEngine()

    monkeypatch.setattr(engine, 'convert_materials', lambda dg, r: {})
    monkeypatch.setattr(engine, 'convert_objects', lambda dg, r, mm: None)
    monkeypatch.setattr(engine, 'convert_lights', lambda dg, r: None)
    monkeypatch.setattr(engine, 'setup_world', lambda scene, r: None)
    monkeypatch.setattr(engine, 'bind_display_space_shader', lambda s: None)
    monkeypatch.setattr(engine, 'unbind_display_space_shader', lambda: None)

    dims = []

    def _rec_camera(renderer, ctx, w, h):
        dims.append((w, h))
        renderer.setup_camera()
    monkeypatch.setattr(engine, '_setup_viewport_camera', _rec_camera)
    monkeypatch.setattr(engine, '_update_viewport_texture',
                        lambda pixels, w, h: setattr(engine, '_viewport_texture', object()))

    clock = [1000.0]
    monkeypatch.setattr(addon.exporter_module, '_nav_clock', lambda: clock[0])
    return addon, engine, clock, dims


def _draw(engine, ctx):
    depsgraph = types.SimpleNamespace(scene=ctx.scene)
    try:
        engine.view_draw(ctx, depsgraph)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_moving_camera_renders_reduced_resolution(monkeypatch):
    """A camera-motion view_draw frame renders at region/N resolution."""
    addon, engine, clock, dims = _wire(monkeypatch)
    exporter = engine._get_exporter()

    ctx = _make_context(IDENTITY)
    engine.view_update(ctx, types.SimpleNamespace(scene=ctx.scene))
    assert dims[-1] == (320, 240), "initial full sync must render full res"
    assert exporter._viewport_render_divisor == 1

    clock[0] += 0.01
    _draw(engine, _make_context(SHIFTED))
    n = addon.exporter_module.VIEWPORT_NAV_RES_DIVISOR
    assert dims[-1] == (320 // n, 240 // n), "camera move must render reduced res"
    assert exporter._viewport_render_divisor == n


def test_settle_snaps_back_to_full_resolution(monkeypatch):
    """After the settle window elapses with no camera change, view_draw snaps
    back to full resolution and resets accumulation (no mixed-res blend)."""
    addon, engine, clock, dims = _wire(monkeypatch)
    exporter = engine._get_exporter()
    settle = addon.exporter_module.VIEWPORT_NAV_SETTLE_S

    ctx = _make_context(IDENTITY)
    engine.view_update(ctx, types.SimpleNamespace(scene=ctx.scene))

    # Move -> reduced res.
    clock[0] += 0.01
    _draw(engine, _make_context(SHIFTED))
    assert exporter._viewport_render_divisor > 1
    renders_after_move = engine._viewport_renderer.render_calls

    # Still within settle, camera stable -> NO re-render, stays reduced.
    clock[0] += settle / 2.0
    _draw(engine, _make_context(SHIFTED))
    assert engine._viewport_renderer.render_calls == renders_after_move, (
        "within the settle window a stable camera must not re-render")
    assert exporter._viewport_render_divisor > 1

    # Past the settle window -> snap to full res, reset accumulation.
    clock[0] += settle * 2.0
    _draw(engine, _make_context(SHIFTED))
    assert dims[-1] == (320, 240), "settle must snap back to full resolution"
    assert exporter._viewport_render_divisor == 1
    assert exporter._viewport_current_spp == 1, (
        "resolution switch must reset accumulation to a fresh full-res chunk")


def test_no_stuck_low_res_after_settle(monkeypatch):
    """Once settled at full res, further stable frames stay full res and the
    still-frame path (pkg191) is not forced back to reduced res."""
    addon, engine, clock, _dims = _wire(monkeypatch)
    exporter = engine._get_exporter()
    settle = addon.exporter_module.VIEWPORT_NAV_SETTLE_S

    ctx = _make_context(IDENTITY)
    engine.view_update(ctx, types.SimpleNamespace(scene=ctx.scene))

    clock[0] += 0.01
    _draw(engine, _make_context(SHIFTED))          # reduced
    clock[0] += settle * 2.0
    _draw(engine, _make_context(SHIFTED))          # snap full
    assert exporter._viewport_render_divisor == 1

    # Several more quiet frames well past the window: must stay full res.
    for _ in range(3):
        clock[0] += settle * 2.0
        _draw(engine, _make_context(SHIFTED))
        assert exporter._viewport_render_divisor == 1, "stuck / re-reduced after settle"


def test_continuous_motion_stays_reduced(monkeypatch):
    """Every frame of a continuous orbit (new camera each frame) renders reduced."""
    addon, engine, clock, dims = _wire(monkeypatch)
    n = addon.exporter_module.VIEWPORT_NAV_RES_DIVISOR

    ctx = _make_context(IDENTITY)
    engine.view_update(ctx, types.SimpleNamespace(scene=ctx.scene))

    for mat in (SHIFTED, SHIFTED2, IDENTITY, SHIFTED):
        clock[0] += 0.016
        _draw(engine, _make_context(mat))
        assert dims[-1] == (320 // n, 240 // n)


def test_reduced_frame_still_skips_geometry_upload(monkeypatch):
    """The reduced-res nav frame must keep the pkg192 skip_upload=True fast path
    (no per-frame BVH rebuild) — reduced res layers on top, not instead."""
    class _SkipSpy(_RecordingRenderer):
        def __init__(self):
            super().__init__()
            self.skip_flags = []
        def render(self, *_a, **_k):
            self.skip_flags.append(bool(_a[9]) if len(_a) > 9 else False)
            return super().render(*_a, **_k)

    _addon, engine, clock, _dims = _wire(monkeypatch, renderer_cls=_SkipSpy)
    ctx = _make_context(IDENTITY)
    engine.view_update(ctx, types.SimpleNamespace(scene=ctx.scene))
    r = engine._viewport_renderer
    assert r.skip_flags == [False], "initial sync must upload (build BVH)"

    clock[0] += 0.01
    _draw(engine, _make_context(SHIFTED))
    assert r.skip_flags[-1] is True, "reduced nav frame must skip_upload=True"


def test_settled_full_res_render_path_is_unchanged(monkeypatch):
    """Byte-equivalence guard: at a settled camera the render dimensions equal
    the region dimensions exactly (divisor 1) — the full-res convergence path is
    identical to pre-pkg196, so the settled image is unchanged."""
    addon, engine, clock, dims = _wire(monkeypatch)
    exporter = engine._get_exporter()
    settle = addon.exporter_module.VIEWPORT_NAV_SETTLE_S

    ctx = _make_context(IDENTITY)
    engine.view_update(ctx, types.SimpleNamespace(scene=ctx.scene))
    # A still camera from the very first frame (no motion) renders full res.
    assert dims[-1] == (320, 240)
    assert exporter._viewport_render_divisor == 1

    # Orbit then settle; the settled frame's dims must be exactly the region.
    clock[0] += 0.01
    _draw(engine, _make_context(SHIFTED))
    clock[0] += settle * 2.0
    _draw(engine, _make_context(SHIFTED))
    assert dims[-1] == (ctx.region.width, ctx.region.height)
