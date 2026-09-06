"""pkg241 Phase 1a — present-first blit + interactive-resolution budget.

Two viewport-response levers, addon Python only, layered on the pkg196 nav
divisor (extends it, does not fork a parallel ladder):

  1. Present-first: view_update renders and caches a texture it does NOT blit;
     the next view_draw presents THAT fresh texture before scheduling its own
     refinement chunk, removing the material double-render (view_update render +
     a second view_draw render before the first present).
  2. Interactive-resolution budget: a fresh edit whose estimated full-res render
     exceeds VIEWPORT_INTERACTIVE_BUDGET_MS starts coarse (W/4 x H/4) for a fast
     first present, then refines one rung toward full res per settled frame
     (4 -> 2 -> 1). Cheap scenes (below the measured threshold) render full res.

Same harness shape as test_pkg196_nav_resolution.py: the REAL addon engine is
driven through a mock RenderEngine (recording renderer, stubbed bpy) with an
injectable nav clock, so no wall-clock sleeps are needed.
"""

import importlib.util
import sys
import types
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Loader + stubs (same shape as test_pkg196_nav_resolution.py)
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
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_pkg241", module_path)
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
    Returns (addon, engine, clock, dims)."""
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


def _update(engine, ctx):
    engine.view_update(ctx, types.SimpleNamespace(scene=ctx.scene))


def _draw(engine, ctx):
    depsgraph = types.SimpleNamespace(scene=ctx.scene)
    try:
        engine.view_draw(ctx, depsgraph)
    except Exception:
        # The blit (draw_texture_2d) needs the real gpu module, absent in the
        # headless stub; view_draw's own try/except swallows it AFTER the
        # render/present decision under test has already executed.
        pass


# ---------------------------------------------------------------------------
# Interactive-resolution budget
# ---------------------------------------------------------------------------

def test_budget_divisor_engages_above_measured_threshold(monkeypatch):
    """_budget_start_divisor returns the coarse divisor only when the measured
    estimated full-res render exceeds the interaction budget."""
    addon, engine, _clock, _dims = _wire(monkeypatch)
    exporter = engine._get_exporter()
    budget = addon.exporter_module.VIEWPORT_INTERACTIVE_BUDGET_MS
    coarse = addon.exporter_module.VIEWPORT_START_RES_DIVISOR

    exporter._viewport_last_full_render_ms = 0.0
    assert exporter._budget_start_divisor() == 1, "no measurement -> full res"

    exporter._viewport_last_full_render_ms = budget * 0.5
    assert exporter._budget_start_divisor() == 1, "cheap scene stays full res"

    exporter._viewport_last_full_render_ms = budget * 5.0
    assert exporter._budget_start_divisor() == coarse, "expensive scene starts coarse"


def test_expensive_edit_starts_coarse(monkeypatch):
    """A scene edit whose estimated full-res render is over budget renders its
    view_update chunk at the coarse starting divisor (fast first present)."""
    addon, engine, _clock, dims = _wire(monkeypatch)
    exporter = engine._get_exporter()
    coarse = addon.exporter_module.VIEWPORT_START_RES_DIVISOR

    # First (fresh-sync) frame has no measurement yet -> full res.
    _update(engine, _make_context(IDENTITY))
    assert dims[-1] == (320, 240)

    # Mark the profile expensive, then a second scene edit must start coarse.
    exporter._viewport_last_full_render_ms = \
        addon.exporter_module.VIEWPORT_INTERACTIVE_BUDGET_MS * 5.0
    _update(engine, _make_context(IDENTITY))
    assert dims[-1] == (320 // coarse, 240 // coarse), \
        "expensive edit must start at the coarse budget divisor"
    assert exporter._viewport_render_divisor == coarse


def test_cheap_edit_stays_full_res(monkeypatch):
    """Below the measured threshold the ordinary full-res edit path is unchanged
    (no coarse start), so cheap scenes are unaffected."""
    addon, engine, _clock, dims = _wire(monkeypatch)
    exporter = engine._get_exporter()

    _update(engine, _make_context(IDENTITY))
    exporter._viewport_last_full_render_ms = \
        addon.exporter_module.VIEWPORT_INTERACTIVE_BUDGET_MS * 0.5
    _update(engine, _make_context(IDENTITY))
    assert dims[-1] == (320, 240)
    assert exporter._viewport_render_divisor == 1


# ---------------------------------------------------------------------------
# Present-first
# ---------------------------------------------------------------------------

def test_view_update_flags_present_pending(monkeypatch):
    """view_update caches a texture and flags it present-pending for view_draw."""
    _addon, engine, _clock, _dims = _wire(monkeypatch)
    exporter = engine._get_exporter()

    _update(engine, _make_context(IDENTITY))
    assert exporter._viewport_texture is not None, "view_update must cache a texture"
    assert exporter._viewport_present_pending is True


def test_view_draw_blits_fresh_chunk_without_extra_render(monkeypatch):
    """When a fresh view_update chunk is pending and the view is unchanged, the
    next view_draw presents it WITHOUT rendering another chunk first (removes the
    material double-render)."""
    _addon, engine, _clock, _dims = _wire(monkeypatch)
    exporter = engine._get_exporter()

    _update(engine, _make_context(IDENTITY))
    calls_after_update = engine._viewport_renderer.render_calls
    assert exporter._viewport_present_pending is True

    # Same camera/settings -> present-first: blit the cached chunk, no re-render.
    _draw(engine, _make_context(IDENTITY))
    assert engine._viewport_renderer.render_calls == calls_after_update, \
        "present-first must blit the fresh chunk without an extra render"
    assert exporter._viewport_present_pending is False, "pending flag consumed"


def test_stale_pending_not_presented_after_camera_change(monkeypatch):
    """A camera change since the view_update chunk invalidates present-first: the
    next view_draw renders the new view instead of blitting a stale cache."""
    _addon, engine, clock, _dims = _wire(monkeypatch)
    exporter = engine._get_exporter()

    _update(engine, _make_context(IDENTITY))
    calls_after_update = engine._viewport_renderer.render_calls

    clock[0] += 0.01
    _draw(engine, _make_context(SHIFTED))
    assert engine._viewport_renderer.render_calls > calls_after_update, \
        "a moved camera must render, never present a stale view_update cache"
    assert exporter._viewport_present_pending is False


def test_expensive_edit_refines_to_full_res(monkeypatch):
    """After an expensive edit starts coarse (divisor 4), successive settled
    view_draw frames step the resolution down 4 -> 2 -> 1 (refine to full res)."""
    addon, engine, _clock, dims = _wire(monkeypatch)
    exporter = engine._get_exporter()
    coarse = addon.exporter_module.VIEWPORT_START_RES_DIVISOR
    assert coarse == 4

    _update(engine, _make_context(IDENTITY))
    exporter._viewport_last_full_render_ms = \
        addon.exporter_module.VIEWPORT_INTERACTIVE_BUDGET_MS * 5.0
    _update(engine, _make_context(IDENTITY))
    assert exporter._viewport_render_divisor == 4

    # Frame 1: present-first blits the coarse chunk (no divisor change yet).
    _draw(engine, _make_context(IDENTITY))
    assert exporter._viewport_render_divisor == 4, "present-first holds the divisor"

    # Frames 2..: refine one rung per settled frame toward full res.
    _draw(engine, _make_context(IDENTITY))
    assert exporter._viewport_render_divisor == 2
    _draw(engine, _make_context(IDENTITY))
    assert exporter._viewport_render_divisor == 1
    assert dims[-1] == (320, 240), "must resolve to full region resolution"
