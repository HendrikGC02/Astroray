"""#772 - setup_world must resolve a shader-less World to black, matching Cycles.

Root cause (blender_addon/__init__.py `setup_world`, the TEX_ENVIRONMENT /
BACKGROUND / MAPPING node-tree walk): when the World has a node_tree but no
recognised BACKGROUND node (e.g. World Output.Surface unconnected, or the node
removed -- hdri_exterior_hair.blend with the Environment Texture node removed
per the issue's repro), `bg_color` stays None and the old code never called
`renderer.set_background_color(...)` at all. The engine's own default is a
NEGATIVE sentinel (`Vec3(-1)`, include/raytracer.h:2302) meaning "use the
built-in default sky gradient" (~0.15 observed), NOT black -- but Cycles
renders an unconnected/empty World Output.Surface as exactly 0.0.

Fix: when no HDRI loads and no bg_color is found, explicitly call
set_background_color([0, 0, 0]).

Two checks:
1. Unit-level (stub bpy, no real Blender): a World node_tree with no
   BACKGROUND node records an explicit set_background_color([0,0,0]) call.
2. Real headless Blender: build a scene with a World whose node tree has been
   cleared (no BACKGROUND/OUTPUT_WORLD wiring at all), render one frame with
   the Astroray engine (device_mode=cpu, OpenMP-OFF addon), and assert every
   background pixel is 0. Skips cleanly without Blender or a prior staged
   addon build (memory: blender-pixels-bottom-up-roi-flip -- we check the
   WHOLE image, not a directional ROI, so the flip is irrelevant here).
"""
import importlib.util
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE_DIR = REPO_ROOT / "dist" / "astroray"


# --------------------------------------------------------------------------- #
# Unit-level: stub bpy, real setup_world code path
# --------------------------------------------------------------------------- #

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

    module_path = REPO_ROOT / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_issue772_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _RecordingRenderer:
    def __init__(self):
        self.background_calls = []
        self.volume_calls = []

    def set_background_color(self, color):
        self.background_calls.append(list(color))

    def set_world_volume(self, *a, **k):
        self.volume_calls.append((a, k))

    def set_world_max_bounces(self, *a, **k): pass

    def load_environment_map(self, *a, **k):
        return False


def _make_shaderless_world(nodes=()):
    node_tree = types.SimpleNamespace(nodes=list(nodes))
    return types.SimpleNamespace(node_tree=node_tree, cycles=None)


def test_no_background_node_sets_explicit_black(monkeypatch):
    """World has a node_tree, but no BACKGROUND node at all (e.g. removed
    Environment Texture left the tree with nothing wired to Output.Surface)."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    scene = types.SimpleNamespace(world=_make_shaderless_world(nodes=[]))

    engine.setup_world(scene, renderer)

    assert renderer.background_calls == [[0.0, 0.0, 0.0]], (
        f"shader-less world must set an explicit black background, "
        f"got {renderer.background_calls} (engine default sky gradient would "
        f"otherwise show through, ~0.15 per #772)"
    )


def test_background_node_present_unaffected(monkeypatch):
    """Regression: a real BACKGROUND node still drives the color as before --
    the new black-fallback only fires when nothing was found."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    bg_node = types.SimpleNamespace(
        type='BACKGROUND',
        inputs={
            'Strength': types.SimpleNamespace(default_value=1.0),
            'Color': types.SimpleNamespace(is_linked=False, default_value=(0.2, 0.3, 0.4, 1.0)),
        },
    )
    scene = types.SimpleNamespace(world=_make_shaderless_world(nodes=[bg_node]))

    engine.setup_world(scene, renderer)

    assert renderer.background_calls == [[0.2, 0.3, 0.4]]


# --------------------------------------------------------------------------- #
# Headless Blender: full render, background pixels == 0
# --------------------------------------------------------------------------- #

_SCRIPT = r"""
import sys
import importlib.util

addon_dir = sys.argv[sys.argv.index("--") + 1]
sys.path.insert(0, addon_dir)

import bpy
import numpy as np

bpy.ops.wm.read_factory_settings(use_empty=True)

spec = importlib.util.spec_from_file_location(
    "astroray_addon_issue772_hb", addon_dir + "/__init__.py")
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)
addon.register()

failures = []

# Real World with a node_tree, but every node cleared -- nothing recognised
# is wired to World Output.Surface (matches the issue's repro: Environment
# Texture node removed from an otherwise-normal World).
world = bpy.data.worlds.new("Issue772ShaderlessWorld")
world.use_nodes = True
world.node_tree.nodes.clear()
bpy.context.scene.world = world

cam_data = bpy.data.cameras.new("Issue772Camera")
cam_obj = bpy.data.objects.new("Issue772Camera", cam_data)
bpy.context.scene.collection.objects.link(cam_obj)
cam_obj.location = (0.0, 0.0, 0.0)
bpy.context.scene.camera = cam_obj

scene = bpy.context.scene
scene.render.engine = "CUSTOM_RAYTRACER"
scene.render.resolution_x = 16
scene.render.resolution_y = 16
scene.render.resolution_percentage = 100
scene.render.film_transparent = False
scene.view_settings.view_transform = "Standard"
scene.view_settings.exposure = 0.0
scene.view_settings.gamma = 1.0
# #765-adjacent: since pkg176 Stage 4 the engine reads the NATIVE
# scene.cycles.* properties (not just custom_raytracer.*), so both must be
# set or this renders at Blender's factory-default 4096 samples.
if hasattr(scene, "cycles"):
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.seed = 7
if hasattr(scene, "custom_raytracer"):
    cr = scene.custom_raytracer
    cr.samples = 1
    if hasattr(cr, "preview_samples"):
        cr.preview_samples = 1
    if hasattr(cr, "device_mode"):
        cr.device_mode = "cpu"
    if hasattr(cr, "use_adaptive_sampling"):
        cr.use_adaptive_sampling = False

out_stem = sys.argv[sys.argv.index("--") + 2]
scene.render.filepath = out_stem
scene.render.image_settings.file_format = "OPEN_EXR"
scene.render.image_settings.color_depth = "32"
bpy.ops.render.render(write_still=True)

import glob
matches = sorted(glob.glob(out_stem + "*"))
if not matches:
    failures.append("no render output found for stem %r" % out_stem)
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)

img = bpy.data.images.load(matches[0])
w, h = img.size
px = np.asarray(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[:, :, :3]
max_val = float(px.max())
print("[issue772-HB] max background pixel value =", max_val)
if max_val > 1e-6:
    failures.append("shader-less world background is not black: max=%r (expected 0.0)" % max_val)

if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("[issue772-HB] ALL PASS")
sys.exit(0)
"""


def _find_blender():
    for candidate in (
        Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"),
    ):
        if candidate.is_file():
            return candidate
    return None


BLENDER_EXE = _find_blender()


@pytest.mark.skipif(BLENDER_EXE is None, reason="Blender not found at a default install path")
def test_shaderless_world_renders_black_headless():
    if not (STAGE_DIR / "build_report.json").exists():
        pytest.skip("no prior staged build (run scripts/build/build_blender_addon.py)")

    tmp_script = Path(tempfile.mkstemp(suffix=".py", prefix="issue772_hb_")[1])
    tmp_script.write_text(_SCRIPT, encoding="utf-8")
    tmp_dir = Path(tempfile.mkdtemp(prefix="issue772_out_"))
    out_stem = tmp_dir / "shaderless_world"

    cmd = [
        str(BLENDER_EXE), "--background", "--factory-startup",
        "--python", str(tmp_script), "--", str(STAGE_DIR), str(out_stem),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr, file=sys.stderr)
        assert result.returncode == 0, "headless shader-less-world render check failed (see output above)"
    finally:
        import shutil
        try:
            tmp_script.unlink(missing_ok=True)
        except OSError:
            pass
        shutil.rmtree(tmp_dir, ignore_errors=True)
