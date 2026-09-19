"""pkg274 — Addon gaps: native device, missing textures, camera clip, holdout.

Four Blender-native controls previously ignored/warned-about are now honoured:

  * #722 ``scene.cycles.device`` drives the backend when ``device_mode=='auto'``;
  * #723 a missing image/env file records a DEGRADED entry + magenta fallback;
  * #724 ``camera.data.clip_start/clip_end`` bound the primary camera ray;
  * #36  ``object.is_holdout`` writes alpha 0 where the camera ray hits it.

The pure-Python tests below (device resolution, settings_map rows, the degraded
bucket, missing-texture detection with a fake bpy image) run WITHOUT a compiled
engine. The engine gates (clip, holdout, default byte-identity) are guarded with
``pytest.importorskip("astroray")`` so this file is collectable on a checkout
without a built ``.pyd``.
"""

import importlib.util
import pathlib
import sys
import types

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_ADDON = _REPO_ROOT / "blender_addon"


# --------------------------------------------------------------------------- #
# pure-Python loaders (mirror tests/test_pkg176_settings_map.py and
# tests/test_pkg119c_degradation.py)
# --------------------------------------------------------------------------- #

def _load_settings_map():
    spec = importlib.util.spec_from_file_location(
        "pkg274_settings_map", _ADDON / "settings_map.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_native_settings():
    if str(_ADDON) not in sys.path:
        sys.path.insert(0, str(_ADDON))
    spec = importlib.util.spec_from_file_location(
        "pkg274_native_settings", _ADDON / "native_settings.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sm = _load_settings_map()
ns = _load_native_settings()


def _row(native_prop):
    for e in sm.MAPPING:
        if e.native_prop == native_prop:
            return e
    raise AssertionError(f"{native_prop!r} row missing from settings_map")


# --------------------------------------------------------------------------- #
# Item 1 — native device honoured when device_mode == 'auto' (#722)
# --------------------------------------------------------------------------- #

def test_native_device_honoured_when_auto():
    cyc_cpu = types.SimpleNamespace(device="CPU")
    cyc_gpu = types.SimpleNamespace(device="GPU")

    # 'auto' reads the native scene.cycles.device.
    assert ns.resolve_device_mode(cyc_cpu, "auto") == "cpu"
    assert ns.resolve_device_mode(cyc_gpu, "auto") == "gpu"

    # An explicit Astroray 'cpu'/'gpu' override always wins.
    assert ns.resolve_device_mode(cyc_gpu, "cpu") == "cpu"
    assert ns.resolve_device_mode(cyc_cpu, "gpu") == "gpu"

    # A non-Cycles scene keeps the 'auto' safe fallback.
    assert ns.resolve_device_mode(None, "auto") == "auto"

    # The settings_map device_mode row is SUPPORTED with no "SEMANTIC MISMATCH".
    row = _row("device_mode")
    assert row.status == "approximated"
    assert row.pkg119a == "SUPPORTED"
    assert "SEMANTIC MISMATCH" not in row.note


def test_resolve_native_settings_wires_device_mode():
    settings = types.SimpleNamespace(device_mode="auto")
    cyc = types.SimpleNamespace(device="GPU")
    resolved = ns.resolve_native_settings(
        types.SimpleNamespace(custom_raytracer=settings, cycles=cyc))
    assert resolved.device_mode == "gpu"

    settings_cpu = types.SimpleNamespace(device_mode="cpu")
    resolved2 = ns.resolve_native_settings(
        types.SimpleNamespace(custom_raytracer=settings_cpu, cycles=cyc))
    assert resolved2.device_mode == "cpu"  # explicit override wins


# --------------------------------------------------------------------------- #
# Item 3 — clip rows flip to SUPPORTED in settings_map (#724)
# --------------------------------------------------------------------------- #

def test_clip_rows_supported_in_settings_map():
    for native_prop in ("clip_start", "clip_end"):
        row = _row(native_prop)
        assert row.status == "direct", row
        assert row.pkg119a == "SUPPORTED", row
        assert row.neutral_param == "setup_camera (clip near/far)", row


# --------------------------------------------------------------------------- #
# Item 2 — missing texture -> DEGRADED + magenta fallback (#723)
# --------------------------------------------------------------------------- #

def _load_addon(monkeypatch, modname="astroray_blender_addon_pkg274"):
    """Load blender_addon/__init__.py with a stub bpy (mirrors
    tests/test_pkg119c_degradation.py::_load_blender_addon)."""
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base:
        pass

    class _RenderEngineBase:
        def report(self, *a, **k):
            return None

        def update_progress(self, *a, **k):
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
    shader_blending_module.blend_shader_specs = lambda *a, **k: None
    shader_blending_module.add_shader_specs = lambda *a, **k: None

    mathutils_module = types.ModuleType("mathutils")
    mathutils_module.Vector = lambda values: values

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {"cuda": False, "spectral": True}
    astroray_module.__file__ = "/fake/astroray.pyd"
    astroray_module.integrator_registry_names = lambda: ["path_tracer"]
    astroray_module.material_registry_names = lambda: ["lambertian", "disney", "dielectric"]
    astroray_module.pass_registry_names = list

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    sys.modules.pop(modname, None)
    spec = importlib.util.spec_from_file_location(modname, _ADDON / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _RecordingRenderer:
    def __init__(self):
        self.loaded_textures = []

    def load_texture(self, name, rgb, width, height):
        self.loaded_textures.append((name, list(rgb), width, height))


class _FakeImage:
    def __init__(self, name, filepath, packed_file=None, **extra):
        self.name = name
        self.filepath = filepath
        self.packed_file = packed_file
        for k, v in extra.items():
            setattr(self, k, v)


def _resolved():
    import numpy as np
    return {'coord_mode': 'UV', 'uv_layer': '', 'matrix': np.identity(4)}


def test_missing_texture_degrades_and_magenta(monkeypatch, tmp_path):
    addon = _load_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    missing_path = str(tmp_path / "missing_texture.png")  # does not exist
    image = _FakeImage(name="missing_tex", filepath=missing_path)

    tex_name = engine._load_blender_image_resolved(image, renderer, _resolved())

    # The node still gets a texture (a 1x1 magenta constant), not None.
    assert tex_name is not None
    assert len(renderer.loaded_textures) == 1
    _name, rgb, w, h = renderer.loaded_textures[0]
    assert (w, h) == (1, 1)
    assert rgb == [1.0, 0.0, 1.0]

    # A DEGRADED entry names the node and the missing path.
    degraded = engine._degradation_report()._degraded
    assert any(feat == "missing_tex" and detail == missing_path
               for feat, detail in degraded), degraded


def test_existing_texture_adds_no_degraded_entry(monkeypatch, tmp_path):
    addon = _load_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    existing = tmp_path / "real.png"
    existing.write_bytes(b"\x00")  # a file that exists -> normal upload path
    image = _FakeImage(
        name="real_tex", filepath=str(existing),
        size=(1, 1), has_data=True, pixels=[1.0, 0.0, 0.0, 1.0],
    )

    engine._load_blender_image_resolved(image, renderer, _resolved())

    assert engine._degradation_report().is_empty(), (
        "an existing texture file must not record a degradation")


def test_packed_image_untouched_by_missing_file_detection(monkeypatch):
    addon = _load_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    # A packed image (packed_file truthy) is never treated as missing, even with
    # a bogus filepath. Its size is 0 -> the normal path returns None (no upload).
    image = _FakeImage(
        name="packed_tex", filepath="//nonexistent.png",
        packed_file=object(), size=(0, 0),
    )

    result = engine._load_blender_image_resolved(image, renderer, _resolved())

    assert result is None
    assert renderer.loaded_textures == []
    assert engine._degradation_report().is_empty()


# --------------------------------------------------------------------------- #
# Engine gates (guarded with importorskip; run by the lead after building).
# --------------------------------------------------------------------------- #

def _new_renderer(astroray, seed, width, height, transparent=False):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_seed(seed)
    if transparent:
        r.set_use_transparent_film(True)
    return r


def _cam_kwargs(width, height, **extra):
    kw = dict(
        look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=40, aspect_ratio=width / height, aperture=0.0, focus_dist=5.0,
        width=width, height=height,
    )
    kw.update(extra)
    return kw


def test_clip_end_hides_geometry():
    import numpy as np
    astroray = pytest.importorskip("astroray")
    import base_helpers as bh

    W = H = 64
    r = _new_renderer(astroray, seed=5, width=W, height=H, transparent=True)
    white = r.create_material("lambertian", [1.0, 1.0, 1.0], {})
    # A large plane at z=0 (distance 5 from the camera at z=5).
    r.add_triangle([-5, -5, 0], [5, -5, 0], [5, 5, 0], white)
    r.add_triangle([-5, -5, 0], [5, 5, 0], [-5, 5, 0], white)
    r.set_background_color([0.0, 0.0, 1.0])  # blue background on a miss

    # clip_end = 1.0 -> the plane (distance 5) is beyond the far clip -> hidden.
    r.setup_camera(**_cam_kwargs(W, H, clip_near=0.001, clip_far=1.0))
    img_clipped = bh.render_image(r, samples=8, max_depth=2, apply_gamma=False)
    alpha_clipped = np.asarray(r.get_alpha_buffer(), dtype=np.float32).reshape(H, W)

    assert float(np.max(alpha_clipped)) == 0.0, float(np.max(alpha_clipped))
    # The beauty is the blue background (not the white plane).
    assert float(np.mean(img_clipped[..., 2])) > float(np.mean(img_clipped[..., 0]))

    # clip_end = 10.0 -> the plane is within the far clip -> present (covered).
    r.setup_camera(**_cam_kwargs(W, H, clip_near=0.001, clip_far=10.0))
    bh.render_image(r, samples=8, max_depth=2, apply_gamma=False)
    alpha_full = np.asarray(r.get_alpha_buffer(), dtype=np.float32).reshape(H, W)
    assert float(np.max(alpha_full)) > 0.0, float(np.max(alpha_full))


def test_holdout_sphere_alpha_hole():
    import numpy as np
    astroray = pytest.importorskip("astroray")
    import base_helpers as bh

    W = H = 64
    r = _new_renderer(astroray, seed=7, width=W, height=H, transparent=True)
    white = r.create_material("lambertian", [0.8, 0.8, 0.8], {})

    # Background plane far behind the camera target, so background pixels are
    # covered (alpha > 0).
    r.add_triangle([-10, -10, -5], [10, -10, -5], [10, 10, -5], white)
    r.add_triangle([-10, -10, -5], [10, 10, -5], [-10, 10, -5], white)

    # A holdout sphere in front of the background plane.
    r.add_sphere([0, 0, 0], 1.0, white)
    r.set_object_holdout(r.scene_object_count() - 1, True)

    r.setup_camera(**_cam_kwargs(W, H))
    bh.render_image(r, samples=8, max_depth=2, apply_gamma=False)
    alpha = np.asarray(r.get_alpha_buffer(), dtype=np.float32).reshape(H, W)

    center = float(alpha[H // 2, W // 2])
    corner = float(alpha[4, 4])
    assert center == 0.0, f"holdout sphere center alpha {center} != 0"
    assert corner > 0.0, f"background corner alpha {corner} should be > 0"


def test_default_clip_render_byte_identical():
    import numpy as np
    astroray = pytest.importorskip("astroray")
    import base_helpers as bh

    W = H = 48

    def _render(clip_args):
        r = _new_renderer(astroray, seed=11, width=W, height=H)
        bh.create_cornell_box(r)
        r.setup_camera(**_cam_kwargs(W, H, **clip_args))
        return bh.render_image(r, samples=8, max_depth=4, apply_gamma=False)

    # The binding defaults (clip_near=0.001 / clip_far=FLT_MAX) are exactly the
    # pre-pkg274 hard-coded primary-ray bounds, so passing them explicitly must
    # be byte-identical to not passing clip args at all.
    a = _render({"clip_near": 0.001, "clip_far": 3.4028234663852886e38})
    b = _render({})
    assert np.array_equal(a, b), "default clip render must be byte-identical"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
