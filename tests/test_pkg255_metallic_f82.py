"""pkg255 - ShaderNodeBsdfMetallic F82 floor.

Two groups of tests:

  (A) Stub-Blender addon-dispatch tests (no live Blender process, no astroray
      module needed) -- shape mirrors tests/test_pkg178_stage5_native_routing.py.
      Assert `_standalone_bsdf_spec`'s BSDF_METALLIC branch routes F82-mode
      nodes onto the native-principled conductor param keys (specular_tint <-
      Edge Tint, anisotropic <- Anisotropy, anisotropic_rotation <- Rotation,
      thin_film_thickness/thin_film_ior) that plugins/materials/principled.cpp's
      conductorNK/F82-tint machinery (Gulbrandsen 2014 / Kutz-Hoffman) already
      reads for the Principled BSDF's own metallic lobe (pkg178/pkg253) -- and
      that PHYSICAL_CONDUCTOR mode + Normal/Tangent/Weight/distribution are
      never silently dropped.

  (B) Real-renderer tests (skip if astroray isn't built). A tiny metallic
      sphere lit by a single area light, using the SAME native param names the
      addon now emits, proves the F82 route actually reaches the conductor
      physics: non-grey / Edge-Tint-responsive result, roughness-monotone
      specular peak, PHYSICAL_CONDUCTOR-mode fallback renders without
      exception, and CPU/GPU parity in the existing conductor mean-ratio band
      (mirrors tests/test_pkg178_principled_gpu_cpu_parity.py).
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

REPO_ROOT = Path(__file__).resolve().parents[1]


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
    def __init__(self, default=0.0, socket_type="VALUE"):
        self.default_value = default
        self.is_linked = False
        self.links = []
        self.type = socket_type


class _Node:
    def __init__(self, ntype="", bl_idname="", inputs=None, **props):
        self.type = ntype
        self.bl_idname = bl_idname
        self.inputs = inputs or {}
        for k, v in props.items():
            setattr(self, k, v)


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


def _metallic_node(fresnel_type="F82", distribution="MULTI_GGX"):
    """A Blender-5.2-shaped ShaderNodeBsdfMetallic (live probe, 2026-09-07):
    Base Color, Edge Tint, IOR, Extinction (VECTOR), Roughness, Anisotropy,
    Rotation, Normal, Tangent, Weight, Thin Film Thickness, Thin Film IOR
    (VALUE unless noted). No 'Color' socket has ever existed on this node."""
    return _Node(
        ntype="BSDF_METALLIC",
        bl_idname="ShaderNodeBsdfMetallic",
        fresnel_type=fresnel_type,
        distribution=distribution,
        inputs={
            'Base Color':          _Socket(default=(0.9, 0.6, 0.2, 1.0), socket_type="RGBA"),
            'Edge Tint':            _Socket(default=(1.0, 0.9, 0.7, 1.0), socket_type="RGBA"),
            'IOR':                 _Socket(default=(1.5, 1.5, 1.5), socket_type="VECTOR"),
            'Extinction':          _Socket(default=(3.0, 3.0, 3.0), socket_type="VECTOR"),
            'Roughness':           _Socket(default=0.3),
            'Anisotropy':          _Socket(default=0.4),
            'Rotation':            _Socket(default=0.15),
            'Normal':              _Socket(socket_type="VECTOR"),
            'Tangent':             _Socket(socket_type="VECTOR"),
            'Weight':              _Socket(default=0.0),
            'Thin Film Thickness': _Socket(default=250.0),
            'Thin Film IOR':       _Socket(default=1.4),
        },
    )


def _engine(addon):
    return addon.CustomRaytracerRenderEngine()


def test_f82_maps_edge_tint_and_thin_film_to_native_conductor_params(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    engine._degradation = None

    node = _metallic_node(fresnel_type="F82")
    spec = engine._standalone_bsdf_spec(node)

    assert spec is not None
    assert spec["kind"] == "principled"
    assert abs(spec["base_color"][0] - 0.9) < 1e-6, "Base Color must be read directly"

    native = spec["native_params"]
    assert abs(native["metallic"] - 1.0) < 1e-6
    assert abs(native["roughness"] - 0.3) < 1e-6
    # Edge Tint -> the SAME native-principled conductor param the Principled
    # metallic lobe's F82-tint model reads (pkg178 _principled_native_params).
    assert native["specular_tint"] == [1.0, 0.9, 0.7]
    assert abs(native["anisotropic"] - 0.4) < 1e-6
    assert abs(native["anisotropic_rotation"] - 0.15) < 1e-6
    assert abs(native["thin_film_thickness"] - 250.0) < 1e-4
    assert abs(native["thin_film_ior"] - 1.4) < 1e-6

    renderer = _RecordingRenderer()
    engine._create_material_from_shader_spec(spec, renderer)
    assert len(renderer.created_materials) == 1
    mat_type, color, params = renderer.created_materials[0]
    assert mat_type == "principled", f"F82 must route to the native conductor material; got {mat_type!r}"
    assert params["specular_tint"] == [1.0, 0.9, 0.7]
    assert abs(params["thin_film_thickness"] - 250.0) < 1e-4


def test_physical_conductor_warns_and_falls_back_to_f82_defaults(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    engine._degradation = None

    node = _metallic_node(fresnel_type="PHYSICAL_CONDUCTOR")
    spec = engine._standalone_bsdf_spec(node)

    native = spec["native_params"]
    # No IOR/Extinction spectra are read; falls back to F82 defaults (no
    # explicit specular_tint override).
    assert "specular_tint" not in native

    report = engine._degradation_report()
    text = " ".join(report.messages())
    assert ("complex-IOR conductor Fresnel is approximated with the F82-tint "
            "model; IOR/Extinction spectra are not read") in text, (
        f"expected the exact PHYSICAL_CONDUCTOR warning; got {report.messages()!r}")

    # Renders without exception through the recording renderer.
    renderer = _RecordingRenderer()
    engine._create_material_from_shader_spec(spec, renderer)
    assert len(renderer.created_materials) == 1
    assert renderer.created_materials[0][0] == "principled"


def test_normal_tangent_weight_distribution_warned_every_render(monkeypatch):
    """Normal / Tangent / Weight / prop:distribution have no native-material
    equivalent (same non-goal class as pkg253's Coat Normal/Tangent/Weight)
    and must be named in the degradation report, never silently dropped."""
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    engine._degradation = None

    node = _metallic_node(fresnel_type="F82", distribution="GGX")
    engine._standalone_bsdf_spec(node)

    report = engine._degradation_report()
    text = " ".join(report.messages())
    assert "Normal" in text
    assert "Tangent" in text
    assert "Weight" in text
    assert "GGX" in text and "distribution" in text


def test_dead_color_branch_removed_base_color_read_unconditionally(monkeypatch):
    """The old defensive `if 'Base Color' in inputs ... else read 'Color'`
    branch is gone: a Metallic node (which never has a 'Color' socket, live
    5.2 probe 2026-09-07) reads 'Base Color' directly with no dependency on a
    'Color' key ever existing."""
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    engine._degradation = None

    node = _metallic_node()
    assert node.inputs.get('Color') is None  # sanity: node never had this socket
    spec = engine._standalone_bsdf_spec(node)
    assert spec["base_color"] == [0.9, 0.6, 0.2]


# ===========================================================================
# Group B -- real-renderer tests (need the built astroray module)
# ===========================================================================

needs_astroray = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

WIDTH = HEIGHT = 64


def _sphere_scene(use_gpu: bool, params: dict, albedo=(0.9, 0.6, 0.2)):
    r = astroray.Renderer()
    r.set_background_color([0.05, 0.05, 0.05])
    r.set_integrator("path_tracer")
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 20.0})
    r.add_sphere([1.6, 1.6, 2.2], 0.35, light)
    mat = r.create_material("principled", list(albedo), params)
    r.add_sphere([0.0, 0.0, 0.0], 0.9, mat)
    r.setup_camera([0.0, 0.0, 2.6], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   45.0, WIDTH / HEIGHT, 0.0, 2.6, WIDTH, HEIGHT)
    if use_gpu:
        r.set_use_gpu(True)
    return r


def _render(use_gpu: bool, params: dict, spp=192, depth=6, seed=255255, albedo=(0.9, 0.6, 0.2)):
    r = _sphere_scene(use_gpu, params, albedo=albedo)
    r.set_seed(seed)
    return np.asarray(r.render(spp, depth, None, False), dtype=np.float64)


@needs_astroray
def test_f82_renders_nongrey_and_edge_tint_responsive():
    """A metallic sphere with a saturated Edge Tint must render non-grey
    (channels differ), and changing the tint must change the rendered color
    -- proving the F82 conductor path (not a flat Disney metallic fallback)
    is actually being evaluated."""
    neutral = _render(False, {"metallic": 1.0, "roughness": 0.25,
                              "specular_tint": [1.0, 1.0, 1.0]}, seed=1)
    tinted = _render(False, {"metallic": 1.0, "roughness": 0.25,
                             "specular_tint": [1.0, 0.3, 0.1]}, seed=1)

    assert np.all(np.isfinite(neutral)) and np.all(np.isfinite(tinted))

    r_mean, g_mean, b_mean = (float(neutral[..., c].mean()) for c in range(3))
    assert not (abs(r_mean - g_mean) < 1e-4 and abs(g_mean - b_mean) < 1e-4), (
        f"neutral-tint F82 sphere rendered flat grey: R={r_mean:.5f} "
        f"G={g_mean:.5f} B={b_mean:.5f}")

    diff = float(np.abs(tinted - neutral).mean())
    assert diff > 1e-3, (
        f"changing Edge Tint from white to [1,0.3,0.1] produced negligible "
        f"render difference ({diff:.6f}) -- F82 tint is not reaching the "
        f"conductor closure")

    out_dir = os.path.join(REPO_ROOT, "test_results", "2026-09-08-pkg255")
    os.makedirs(out_dir, exist_ok=True)
    from PIL import Image
    for name, img in (("f82_edge_tint_neutral.png", neutral), ("f82_edge_tint_tinted.png", tinted)):
        Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).save(os.path.join(out_dir, name))


@needs_astroray
def test_f82_roughness_monotone_specular_peak():
    """Smooth F82 conductor concentrates the area-light reflection into a
    tighter, brighter peak than a rough one -- same physical property
    test_smooth_metal_has_tighter_specular_peak asserts for the 'metal'
    material (test_material_properties.py)."""
    params = lambda rough: {"metallic": 1.0, "roughness": rough,
                            "specular_tint": [1.0, 0.85, 0.6]}
    smooth = _render(False, params(0.05), seed=7)
    mid = _render(False, params(0.3), seed=7)
    rough = _render(False, params(0.7), seed=7)

    max_smooth = float(np.max(smooth))
    max_mid = float(np.max(mid))
    max_rough = float(np.max(rough))
    assert max_smooth >= max_mid >= max_rough, (
        f"F82 specular peak not monotone in roughness: "
        f"smooth={max_smooth:.4f} mid={max_mid:.4f} rough={max_rough:.4f}")


@needs_astroray
def test_physical_conductor_fallback_renders_without_exception():
    """Mirrors the addon's PHYSICAL_CONDUCTOR fallback (F82 defaults, no
    specular_tint override) through a real render -- must not raise and must
    produce finite pixels."""
    img = _render(False, {"metallic": 1.0, "roughness": 0.3}, seed=42)
    assert img.shape == (HEIGHT, WIDTH, 3)
    assert np.all(np.isfinite(img))


if AVAILABLE and not astroray.__features__.get("cuda", False):
    _CUDA_SKIP_REASON = "CUDA feature not in this build -- pkg255 F82 GPU/CPU parity needs the RTX box"
else:
    _CUDA_SKIP_REASON = None

RATIO_LOW = 0.95
RATIO_HIGH = 1.05

PARITY_CASES = [
    ("f82_r0.3", {"metallic": 1.0, "roughness": 0.3, "specular_tint": [0.9, 0.6, 0.3]}),
    ("f82_r0.6", {"metallic": 1.0, "roughness": 0.6, "specular_tint": [0.9, 0.6, 0.3]}),
]


@pytest.mark.skipif(_CUDA_SKIP_REASON is not None, reason=_CUDA_SKIP_REASON or "")
@pytest.mark.parametrize("label,params", PARITY_CASES, ids=[c[0] for c in PARITY_CASES])
def test_f82_gpu_cpu_parity(label, params):
    """CPU/GPU parity for the F82 route, in the SAME mean-ratio band pkg178
    already established for the native conductor lobe
    (test_pkg178_principled_gpu_cpu_parity.py CASES metallic_r0.3/r0.6) --
    pkg255 adds no new engine code, so it must land in the same band."""
    gpu = _render(True, params, seed=255178)
    cpu = _render(False, params, seed=255178)

    assert gpu.shape == cpu.shape == (HEIGHT, WIDTH, 3)
    assert np.all(np.isfinite(gpu)) and np.all(np.isfinite(cpu))

    print(f"\n[pkg255 F82 GPU/CPU parity] case={label} band=[{RATIO_LOW}, {RATIO_HIGH}]")
    for c, ch in enumerate("RGB"):
        cpu_mean, gpu_mean = float(cpu[..., c].mean()), float(gpu[..., c].mean())
        ratio = gpu_mean / cpu_mean if cpu_mean > 1e-8 else float("nan")
        print(f"  {ch}: cpu={cpu_mean:.5f} gpu={gpu_mean:.5f} ratio={ratio:.4f}")
        assert RATIO_LOW <= ratio <= RATIO_HIGH, (
            f"pkg255 F82 GPU/CPU parity FAILED case={label} channel {ch}: "
            f"ratio {ratio:.4f} outside [{RATIO_LOW}, {RATIO_HIGH}] "
            f"(cpu={cpu_mean:.5f}, gpu={gpu_mean:.5f})")
