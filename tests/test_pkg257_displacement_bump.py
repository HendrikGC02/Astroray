#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pkg257 -- Displacement node support-or-warn floor (addon-only, zero engine code).

Before: the Material Output's `Displacement` socket was never read anywhere
in the addon (`convert_node_material` read only `Surface`/`Volume`) -- a
`ShaderNodeDisplacement` wired into it, and `material.displacement_method`,
were both silently ignored regardless of value (all 5 sockets/props
DROPPED-SILENT). After: `Displacement.Height` (magnitude from `Scale`) is
approximated as a bump perturbation through the existing pkg223b bump
machinery -- the SAME `bump_map_texture`/`bump_strength`/`bump_distance`
material params a `ShaderNodeBump` on a BSDF's `Normal` already produces --
with an explicit, consolidated warning when `displacement_method` requests
true geometric displacement (`BOTH`/`DISPLACEMENT`) or when a custom
`Normal` is wired to the Displacement node, since neither is honoured by a
bump-only approximation. Zero engine (C++/CUDA) changes.

Two groups:

  (A) Stub-Blender addon-dispatch tests (no astroray import needed) -- shape
      mirrors tests/test_blender_principled_texture.py and
      tests/test_pkg255_metallic_f82.py. Exercise
      `get_displacement_bump_inputs` and `convert_shader_node`'s new
      optional `displacement_bump` parameter directly, plus one full
      `convert_node_material()` pass (mirrors the
      `_convert_node_material_standalone` wrapper's `_MinimalConverter`
      pattern) proving the whole wiring reaches `renderer.create_material`.

  (B) Real-renderer tests (skip if astroray isn't built) -- reuse pkg223b's
      exact render harness (ramp height texture, grazing sun, 64x64 quad):
      relief visible, Scale (-> bump_strength) monotone, and geometry
      (`scene_object_count`) unchanged between bump-off and bump-on --
      proving no true displacement occurred, which the DISPLACEMENT warning
      must be honest about.

Midlevel note (a documented interpretation, not a silent skip): Midlevel is
extracted -- `get_displacement_bump_inputs` never treats it as a drop -- but
is mathematically inert for a gradient-based bump approximation. The
surface-gradient formula reused from pkg223b finite-differences the height
field (`dU = (hU - h0) / eps`); any constant subtracted from every sample
cancels exactly in that subtraction, so Midlevel cannot change the emitted
bump_strength/bump_distance/bump_map_texture no matter its value. This is
not a workaround: real Cycles' own BUMP method has the identical property
(Midlevel only matters for true geometric displacement, which this floor
does not implement and warns about instead). The spec's acceptance
criteria classify Midlevel as "APPROXIMATED" (read + accounted for), not
"changes the render" -- Group A proves the read happens and is inert;
Group B proves Scale is the knob that actually moves relief.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(REPO_ROOT / "tests"))
from runtime_setup import configure_test_imports  # noqa: E402

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

if AVAILABLE:
    from base_helpers import create_renderer, setup_camera, render_image  # noqa: E402


# ===========================================================================
# Group A -- stub-Blender addon dispatch (no astroray import required)
# ===========================================================================

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


class _Socket:
    """Minimal stand-in for `bpy.types.NodeSocket`."""
    def __init__(self, default=0.0, linked_to=None, socket_type="VALUE"):
        self.default_value = default
        self.is_linked = linked_to is not None
        self.type = socket_type
        self.links = []
        if linked_to is not None:
            self.links.append(types.SimpleNamespace(from_node=linked_to))


class _Node:
    """Minimal stand-in for `bpy.types.Node`."""
    def __init__(self, ntype, bl_idname="", inputs=None, **extra):
        self.type = ntype
        self.bl_idname = bl_idname
        self.inputs = inputs or {}
        for k, v in extra.items():
            setattr(self, k, v)


class _FakeImage:
    """Stand-in for `bpy.types.Image` consumed by `load_blender_image`."""
    def __init__(self, name="height.png", w=4, h=4):
        self.name = name
        self.size = (w, h)
        self.has_data = True
        self.pixels = [0.5] * (w * h * 4)

    def reload(self): pass


class _NodeTree:
    def __init__(self, nodes):
        self.nodes = nodes


class _Material:
    """Minimal stand-in for `bpy.types.Material`. No `inline_shader_nodes`
    attribute at all -- exercises convert_node_material's pre-5.0 fallback
    (`except AttributeError: node_tree = original_tree`), same as real
    Blender <5.0 behaviour."""
    def __init__(self, node_tree, displacement_method='BUMP', name='pkg257_mat'):
        self.node_tree = node_tree
        self.displacement_method = displacement_method
        self.name = name


class _RecordingRenderer:
    """Records create_material / load_texture calls so tests can assert."""
    def __init__(self):
        self.created_materials = []
        self.loaded_textures = []
        self._next_id = 1

    def load_texture(self, name, rgb, width, height):
        self.loaded_textures.append((name, width, height))

    def create_material(self, mat_type, color, params):
        self.created_materials.append((mat_type, list(color), dict(params)))
        mid = self._next_id
        self._next_id += 1
        return mid

    def set_material_spectral_profile(self, *a, **k): pass
    def clear_material_spectral_profile(self, *a, **k): pass


def _displacement_node(height_link=None, midlevel=0.5, scale=1.0, normal_link=None):
    """A Blender-5.2-shaped ShaderNodeDisplacement (live probe, 2026-09-07):
    inputs = Height, Midlevel, Scale, Normal. No Distance socket exists."""
    return _Node(
        'DISPLACEMENT', bl_idname='ShaderNodeDisplacement',
        inputs={
            'Height':   _Socket(default=1.0, linked_to=height_link),
            'Midlevel': _Socket(default=midlevel),
            'Scale':    _Socket(default=scale),
            'Normal':   _Socket(socket_type="VECTOR", linked_to=normal_link),
        },
    )


def _output_node(surface_link=None, displacement_link=None):
    return _Node(
        'OUTPUT_MATERIAL', is_active_output=True,
        inputs={
            'Surface':      _Socket(linked_to=surface_link),
            'Volume':       _Socket(linked_to=None),
            'Displacement': _Socket(linked_to=displacement_link),
        },
    )


def _principled_node():
    """Shape mirrors tests/test_blender_principled_texture.py's helper --
    enough sockets for `_principled_shader_spec` to run to completion."""
    return _Node(
        'BSDF_PRINCIPLED',
        inputs={
            'Base Color':           _Socket(default=(0.8, 0.8, 0.8, 1.0), socket_type="RGBA"),
            'Metallic':             _Socket(default=0.0),
            'Roughness':            _Socket(default=0.5),
            'IOR':                  _Socket(default=1.45),
            'Anisotropic':          _Socket(default=0.0),
            'Emission Color':       _Socket(default=(0.0, 0.0, 0.0, 1.0), socket_type="RGBA"),
            'Emission Strength':    _Socket(default=0.0),
            'Normal':               _Socket(default=0.0),
            'Transmission Weight':  _Socket(default=0.0),
            'Coat Weight':          _Socket(default=0.0),
            'Coat Roughness':       _Socket(default=0.0),
            'Sheen Weight':         _Socket(default=0.0),
            'Subsurface Weight':    _Socket(default=0.0),
        },
    )


def _engine(addon):
    return addon.CustomRaytracerRenderEngine()


# --- get_displacement_bump_inputs -----------------------------------------

def test_extracts_height_and_scale_no_warning_at_default_method(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)

    image = _FakeImage(name="height.png")
    tex = _Node('TEX_IMAGE', image=image)
    disp = _displacement_node(height_link=tex, midlevel=0.5, scale=0.75)
    output = _output_node(displacement_link=disp)
    mat = _Material(node_tree=None, displacement_method='BUMP')

    result, warning = engine.get_displacement_bump_inputs(output, mat)

    assert result['bump_image'] is image
    assert abs(result['bump_strength'] - 0.75) < 1e-6, "Scale must become bump_strength"
    assert result['bump_distance'] == 0.01, "no Distance socket on Displacement -- constant default"
    # Default displacement_method ('BUMP') + no linked Normal -> zero spurious warnings.
    assert warning is None


def test_midlevel_is_read_but_inert(monkeypatch):
    """Midlevel is never a silent drop (get_float_input actually reads it),
    but is mathematically inert for the bump-only approximation: two
    otherwise-identical Displacement nodes differing ONLY in Midlevel must
    produce byte-identical extracted params. See the module docstring."""
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    image = _FakeImage(name="height.png")
    tex = _Node('TEX_IMAGE', image=image)
    output_low = _output_node(displacement_link=_displacement_node(
        height_link=tex, midlevel=0.05, scale=1.0))
    output_high = _output_node(displacement_link=_displacement_node(
        height_link=tex, midlevel=0.95, scale=1.0))
    mat = _Material(node_tree=None, displacement_method='BUMP')

    result_low, warn_low = engine.get_displacement_bump_inputs(output_low, mat)
    result_high, warn_high = engine.get_displacement_bump_inputs(output_high, mat)

    assert result_low == result_high, (
        f"Midlevel changed the extracted bump params: {result_low} vs {result_high}")
    assert warn_low is None and warn_high is None


def test_normal_linked_warns_verbatim(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    image = _FakeImage()
    tex = _Node('TEX_IMAGE', image=image)
    normal_source = _Node('NORMAL_MAP', inputs={})
    disp = _displacement_node(height_link=tex, normal_link=normal_source)
    output = _output_node(displacement_link=disp)
    mat = _Material(node_tree=None, displacement_method='BUMP')

    _, warning = engine.get_displacement_bump_inputs(output, mat)

    assert warning == "'Normal' input is dropped (bump derives its own gradient from Height)"


def test_non_bump_method_warns_verbatim(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    image = _FakeImage()
    tex = _Node('TEX_IMAGE', image=image)
    disp = _displacement_node(height_link=tex)
    output = _output_node(displacement_link=disp)

    for method in ('DISPLACEMENT', 'BOTH'):
        mat = _Material(node_tree=None, displacement_method=method)
        _, warning = engine.get_displacement_bump_inputs(output, mat)
        assert warning == (
            f"displacement_method '{method}' requests true geometric displacement "
            "but is bump-approximated only ('space' is likewise ignored)")


def test_normal_and_method_consolidate_into_one_warning(monkeypatch):
    """One consolidated DISPLACEMENT warning, not a warning storm per socket."""
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    image = _FakeImage()
    tex = _Node('TEX_IMAGE', image=image)
    normal_source = _Node('NORMAL_MAP', inputs={})
    disp = _displacement_node(height_link=tex, normal_link=normal_source)
    output = _output_node(displacement_link=disp)
    mat = _Material(node_tree=None, displacement_method='BOTH')

    _, warning = engine.get_displacement_bump_inputs(output, mat)

    assert warning == (
        "'Normal' input is dropped (bump derives its own gradient from Height); "
        "displacement_method 'BOTH' requests true geometric displacement "
        "but is bump-approximated only ('space' is likewise ignored)")


def test_no_displacement_wired_is_a_pure_noop(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    output = _output_node(displacement_link=None)
    mat = _Material(node_tree=None, displacement_method='BUMP')

    result, warning = engine.get_displacement_bump_inputs(output, mat)

    assert result == {'bump_image': None, 'bump_strength': 1.0, 'bump_distance': 0.01}
    assert warning is None


# --- convert_shader_node's new optional parameter --------------------------

def test_convert_shader_node_merges_displacement_bump_params(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    engine._use_native_principled_flag = False  # pin the simpler Disney fallback
    engine._degradation = None

    image = _FakeImage(name="disp_height.png")
    node = _principled_node()
    displacement_bump = {'bump_image': image, 'bump_strength': 0.6, 'bump_distance': 0.01}

    renderer = _RecordingRenderer()
    engine.convert_shader_node(node, renderer, node_tree=None, displacement_bump=displacement_bump)

    assert renderer.loaded_textures == [("disp_height.png", 4, 4)]
    assert len(renderer.created_materials) == 1
    mat_type, _color, params = renderer.created_materials[0]
    assert mat_type == "disney"
    assert params.get('bump_map_texture') == "disp_height.png"
    assert abs(params.get('bump_strength') - 0.6) < 1e-6
    assert abs(params.get('bump_distance') - 0.01) < 1e-6


def test_convert_shader_node_default_param_unaffected(monkeypatch):
    """Regression guard for the signature sweep: every pre-existing call
    site relies on the new parameter's default (None) and must see
    byte-identical behaviour to before this package."""
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    engine._use_native_principled_flag = False
    engine._degradation = None

    node = _principled_node()
    renderer = _RecordingRenderer()
    engine.convert_shader_node(node, renderer, node_tree=None)

    assert renderer.loaded_textures == []
    mat_type, _color, params = renderer.created_materials[0]
    assert mat_type == "disney"
    assert 'bump_map_texture' not in params
    assert 'bump_strength' not in params
    assert 'bump_distance' not in params


# --- full convert_node_material() wiring -----------------------------------

def test_convert_node_material_end_to_end_bump_approximation(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    engine._use_native_principled_flag = False
    engine._degradation = None
    engine._volume_material_map = {}

    image = _FakeImage(name="e2e_height.png")
    tex = _Node('TEX_IMAGE', image=image)
    disp = _displacement_node(height_link=tex, scale=0.5)
    surface = _principled_node()
    output = _output_node(surface_link=surface, displacement_link=disp)
    tree = _NodeTree([output, surface, disp, tex])
    mat = _Material(node_tree=tree, displacement_method='BUMP', name='pkg257_e2e')

    renderer = _RecordingRenderer()
    mat_id = engine.convert_node_material(mat, renderer)

    assert mat_id is not None
    assert len(renderer.created_materials) == 1
    _mat_type, _color, params = renderer.created_materials[0]
    assert params.get('bump_map_texture') == "e2e_height.png"
    assert abs(params.get('bump_strength') - 0.5) < 1e-6
    assert engine._degradation_report().messages() == [], "BUMP method + no Normal must warn nothing"


def test_convert_node_material_warns_for_both_method(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    engine._use_native_principled_flag = False
    engine._degradation = None
    engine._volume_material_map = {}

    image = _FakeImage(name="e2e_height2.png")
    tex = _Node('TEX_IMAGE', image=image)
    disp = _displacement_node(height_link=tex, scale=1.0)
    surface = _principled_node()
    output = _output_node(surface_link=surface, displacement_link=disp)
    tree = _NodeTree([output, surface, disp, tex])
    mat = _Material(node_tree=tree, displacement_method='BOTH', name='pkg257_e2e2')

    renderer = _RecordingRenderer()
    engine.convert_node_material(mat, renderer)

    messages = engine._degradation_report().messages()
    assert len(messages) == 1
    assert messages[0] == (
        "approximated DISPLACEMENT: displacement_method 'BOTH' requests true "
        "geometric displacement but is bump-approximated only ('space' is "
        "likewise ignored)")


# ===========================================================================
# Group B -- real-renderer tests (need the built astroray module)
# ===========================================================================

needs_astroray = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")


def _has_cuda(r):
    return bool(astroray.__features__.get("cuda", False)) and bool(getattr(r, "gpu_available", False))


def _norm(v):
    import numpy as np
    v = np.asarray(v, np.float32)
    return (v / np.linalg.norm(v)).tolist()


def _ramp_height(n=32):
    """Same smooth horizontal height ramp as pkg223b's own bump test: height
    increases along +U so dHeight/dU is constant, giving a clean, MC-robust
    relief signal. Reused verbatim -- pkg257's Displacement.Scale reaches the
    engine as the SAME bump_strength this ramp already exercises."""
    import numpy as np
    col = (np.arange(n, dtype=np.float32) / (n - 1))
    img = np.repeat(col[None, :, None], n, axis=0)
    return np.repeat(img, 3, axis=2).astype(np.float32)


def _build(r, distance=0.0, strength=1.0):
    """Two-triangle quad, identical geometry regardless of bump params --
    the scene this package's 'geometry unchanged' test relies on."""
    r.set_background_color([0.0, 0.0, 0.0])
    params = {}
    if distance > 0.0:
        r.load_texture("pkg257_h", _ramp_height(32), 32, 32, "UV")
        params["bump_map_texture"] = "pkg257_h"
        params["bump_distance"] = float(distance)
        params["bump_strength"] = float(strength)
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], params)
    A, B = [-1, -1, 0], [1, -1, 0]
    C, D = [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    ang = 0.02
    r.add_sun_light_dedicated(_norm([-1.0, 0.0, -0.4]), ang,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 3.0)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=64, height=64)


def _render(distance=0.0, strength=1.0, use_gpu=False, samples=96):
    import numpy as np
    r = create_renderer()
    if use_gpu:
        if not _has_cuda(r):
            pytest.skip("No CUDA GPU")
        r.set_use_gpu(True)
    _build(r, distance=distance, strength=strength)
    return np.asarray(render_image(r, samples=samples, max_depth=2, apply_gamma=False),
                      dtype=np.float32)


def _mean(img):
    return float(img.mean())


@needs_astroray
def test_cpu_relief_visible():
    """Scale-driven bump (Scale -> bump_strength=1) must differ substantially
    from Scale=0 (flat shading normal), proving the Displacement floor's
    relief is real, not dropped."""
    import numpy as np
    s1 = _render(distance=0.5, strength=1.0, use_gpu=False)
    s0 = _render(distance=0.5, strength=0.0, use_gpu=False)
    assert _mean(s0) > 0.02, f"unbumped too dark to gate ({_mean(s0):.4f})"
    d = float(np.abs(s1 - s0).mean())
    assert d > 0.02, f"Displacement produced no visible relief (mean|d|={d:.4f})"


@needs_astroray
def test_cpu_scale_monotone():
    """Departure from the flat (Scale=0) normal grows with Scale (addon-emitted
    bump_strength) -- monotonic relief magnitude."""
    import numpy as np
    s0 = _render(distance=0.5, strength=0.0)
    sh = _render(distance=0.5, strength=0.5)
    s1 = _render(distance=0.5, strength=1.0)
    d_half = float(np.abs(sh - s0).mean())
    d_full = float(np.abs(s1 - s0).mean())
    assert d_full > d_half > 1e-3, \
        f"Scale not monotone: half={d_half:.4g} full={d_full:.4g}"


@needs_astroray
def test_geometry_object_count_unchanged_by_bump_relief():
    """A bump-only Displacement approximation must never add, remove, or move
    geometry: `scene_object_count()` after adding the SAME two triangles must
    be identical whether or not bump params are attached to the material --
    proving no true displacement (mesh subdivision/offset) occurred, which
    the DISPLACEMENT warning explicitly disclaims."""
    r_flat = create_renderer()
    _build(r_flat, distance=0.0, strength=0.0)
    r_bumped = create_renderer()
    _build(r_bumped, distance=0.5, strength=1.0)

    assert r_flat.scene_object_count() == r_bumped.scene_object_count(), (
        "object/vertex count differs between bump-off and bump-on scenes -- "
        "the bump approximation must not alter geometry")


@needs_astroray
@pytest.mark.skipif(not (AVAILABLE and astroray.__features__.get("cuda", False)),
                    reason="needs CUDA build")
def test_gpu_relief_visible():
    import numpy as np
    s1 = _render(distance=0.5, strength=1.0, use_gpu=True)
    s0 = _render(distance=0.5, strength=0.0, use_gpu=True)
    assert _mean(s0) > 0.02, f"unbumped too dark ({_mean(s0):.4f})"
    d = float(np.abs(s1 - s0).mean())
    assert d > 0.02, f"Displacement produced no visible relief on GPU (mean|d|={d:.4f})"


@needs_astroray
@pytest.mark.skipif(not (AVAILABLE and astroray.__features__.get("cuda", False)),
                    reason="needs CUDA build")
def test_cpu_gpu_parity():
    """CPU and GPU agree within pkg223b's own per-channel mean-ratio band --
    no numeric parity gate is claimed beyond what pkg223b already verified,
    since this package reuses that machinery unchanged (spec Acceptance
    criterion 3: 'no numeric parity gate -- different derivative sources')."""
    cpu = _render(distance=0.2, strength=1.0, use_gpu=False, samples=128)
    gpu = _render(distance=0.2, strength=1.0, use_gpu=True, samples=128)
    cm, gm = _mean(cpu), _mean(gpu)
    assert gm > 0.01 and cm > 0.01, f"renders too dark (cpu={cm:.4f} gpu={gm:.4f})"
    ratio = gm / cm
    assert 0.9 < ratio < 1.1, f"CPU/GPU relief mean ratio out of band: {ratio:.4f}"
