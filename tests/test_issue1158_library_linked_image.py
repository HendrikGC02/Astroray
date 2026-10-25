"""#1158 - an image linked from a library .blend has a ``//`` path relative to the
LIBRARY file, so ``bpy.path.abspath(filepath)`` (main-file relative) pointed at a
folder that does not exist: the pkg274 missing-texture guard replaced the texture with
the 1x1 magenta fallback and logged ``degraded <image>``. Fixed by resolving with
``bpy.path.abspath(filepath, library=image.library)`` (``_abspath_for``).

Two legs:
  * stub-bpy unit tests (always run) for the guard and the helper;
  * a real headless-Blender render of a generated two-file fixture (library .blend in
    one folder holding a textured plane + its image, main .blend in another folder that
    links the collection and instances it). Skips without Blender or a staged engine.

Engine: ``ASTRORAY_PYD_DIR`` (default ``<repo>/dist/astroray``) supplies astroray.pyd; the
addon python under test is always ``<repo>/blender_addon``.
"""
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_pkg274_addon_gaps as P  # stub-bpy addon loader + fakes  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
ADDON_DIR = REPO_ROOT / "blender_addon"
PYD_DIR = Path(os.environ.get("ASTRORAY_PYD_DIR", REPO_ROOT / "dist" / "astroray"))

# Raw (sRGB-encoded) texel stored in the PNG; the addon decodes it to scene-linear.
TEXEL_RAW = (0.2, 0.8, 0.3)


def _srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


# ---------------------------------------------------------------- stub-bpy leg

def _lib_aware_abspath(calls):
    def abspath(p, library=None):
        calls.append((p, library))
        return p if library is None else str(Path("LIBDIR") / p.lstrip("/"))
    return abspath


def test_guard_resolves_linked_image_against_its_library(monkeypatch, tmp_path):
    addon = P._load_addon(monkeypatch)
    calls = []
    sys.modules["bpy"].path = types.SimpleNamespace(abspath=_lib_aware_abspath(calls))
    lib = object()
    img = P._FakeImage("lib_tex.png", "//tex/lib_tex.png", library=lib)
    engine = addon.CustomRaytracerRenderEngine()
    engine._load_blender_image_resolved(img, P._RecordingRenderer(), P._resolved()) \
        if hasattr(P, "_resolved") else None
    assert (img.filepath, lib) in calls, calls


def test_abspath_for_local_image_passes_no_library(monkeypatch):
    addon = P._load_addon(monkeypatch)
    calls = []
    sys.modules["bpy"].path = types.SimpleNamespace(abspath=_lib_aware_abspath(calls))
    local = types.SimpleNamespace(library=None)
    assert addon._abspath_for(local, "//a.png") == "//a.png"
    assert calls == [("//a.png", None)]
    # stub images without a ``library`` attribute still resolve (older fakes)
    assert addon._abspath_for(types.SimpleNamespace(), "//b.png") == "//b.png"


# ----------------------------------------------------------- headless-Blender leg

_SCRIPT = r"""
import sys, os, glob, importlib.util
args = sys.argv[sys.argv.index("--") + 1:]
mode, addon_dir, pyd_dir, workdir = args[0], args[1], args[2], args[3]
import bpy
import numpy as np

lib_dir = os.path.join(workdir, "libfolder")
main_dir = os.path.join(workdir, "mainfolder")
lib_path = os.path.join(lib_dir, "lib.blend")
main_path = os.path.join(main_dir, "main.blend")
raw = tuple(float(x) for x in args[4].split(","))


def make_library():
    os.makedirs(os.path.join(lib_dir, "tex"), exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    img = bpy.data.images.new("lib_tex.png", 16, 16, alpha=False)
    img.pixels[:] = list(raw + (1.0,)) * (16 * 16)
    img.filepath_raw = os.path.join(lib_dir, "tex", "lib_tex.png")
    img.file_format = "PNG"
    img.save()
    mat = bpy.data.materials.new("LibMat")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    dif = nt.nodes.new("ShaderNodeBsdfDiffuse")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], dif.inputs["Color"])
    nt.links.new(dif.outputs["BSDF"], out.inputs["Surface"])
    bpy.ops.mesh.primitive_plane_add(size=20.0, location=(0, 0, 0))
    plane = bpy.context.active_object
    plane.name = "LibPlane"
    plane.data.materials.append(mat)
    coll = bpy.data.collections.new("LibColl")
    bpy.context.scene.collection.children.link(coll)
    for c in list(plane.users_collection):
        c.objects.unlink(plane)
    coll.objects.link(plane)
    bpy.ops.wm.save_as_mainfile(filepath=lib_path, relative_remap=True)
    print("[1158] library image filepath:", bpy.data.images["lib_tex.png"].filepath)


def make_main():
    os.makedirs(main_dir, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    with bpy.data.libraries.load(lib_path, link=True) as (data_from, data_to):
        data_to.collections = ["LibColl"]
    lib_coll = data_to.collections[0]
    scene = bpy.context.scene
    inst = bpy.data.objects.new("LibInstance", None)
    inst.instance_type = "COLLECTION"
    inst.instance_collection = lib_coll
    scene.collection.objects.link(inst)
    world = bpy.data.worlds.new("W")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (1, 1, 1, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0
    scene.world = world
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    scene.collection.objects.link(cam)
    cam.location = (0, 0, 3)
    scene.camera = cam
    bpy.ops.wm.save_as_mainfile(filepath=main_path, relative_remap=True)


def render():
    sys.path.insert(0, pyd_dir)
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(pyd_dir)
    os.environ.setdefault("ASTRORAY_DATA_DIR", os.path.join(pyd_dir, "data"))
    spec = importlib.util.spec_from_file_location("astroray_addon_i1158", addon_dir + "/__init__.py")
    addon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(addon)
    addon.register()
    print("[1158] addon:", addon.__file__)
    bpy.ops.wm.open_mainfile(filepath=main_path)
    img = bpy.data.images["lib_tex.png"]
    print("[1158] linked image library:", img.library.filepath if img.library else None)
    print("[1158] abspath(no library):", bpy.path.abspath(img.filepath), os.path.exists(bpy.path.abspath(img.filepath)))
    scene = bpy.context.scene
    scene.render.engine = "CUSTOM_RAYTRACER"
    scene.render.resolution_x = scene.render.resolution_y = 64
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Standard"
    cr = scene.custom_raytracer
    scene.cycles.samples = 16  # native control (pkg176)
    if hasattr(cr, "device_mode"):
        cr.device_mode = "cpu"
    if hasattr(cr, "use_adaptive_sampling"):
        cr.use_adaptive_sampling = False
    stem = os.path.join(workdir, "render")
    for f in glob.glob(stem + "*"):
        os.remove(f)
    scene.render.filepath = stem
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    bpy.ops.render.render(write_still=True)
    out = sorted(glob.glob(stem + "*"))[0]
    res = bpy.data.images.load(out)
    w, h = res.size
    px = np.asarray(res.pixels[:], dtype=np.float32).reshape(h, w, 4)[:, :, :3]
    roi = px[h // 2 - 16:h // 2 + 16, w // 2 - 16:w // 2 + 16].reshape(-1, 3).mean(axis=0)
    print("[1158] ROI_MEAN %.6f %.6f %.6f" % tuple(roi))


{"make": lambda: (make_library(), make_main()), "render": render}[mode]()
"""


def _find_blender():
    env = os.environ.get("BLENDER_EXE")
    if env and Path(env).is_file():
        return Path(env)
    for v in ("5.2", "5.1", "5.0"):
        p = Path(rf"C:\Program Files\Blender Foundation\Blender {v}\blender.exe")
        if p.is_file():
            return p
    return None


BLENDER_EXE = _find_blender()


def _run(mode, workdir):
    script = workdir / "i1158_driver.py"
    script.write_text(_SCRIPT, encoding="utf-8")
    cmd = [str(BLENDER_EXE), "--background", "--factory-startup", "--python", str(script),
           "--", mode, str(ADDON_DIR), str(PYD_DIR), str(workdir),
           ",".join(str(c) for c in TEXEL_RAW)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
    return r.returncode, r.stdout + "\n" + r.stderr


@pytest.fixture(scope="module")
def library_render(tmp_path_factory):
    if BLENDER_EXE is None:
        pytest.skip("Blender not found")
    if not list(PYD_DIR.glob("astroray*.pyd")):
        pytest.skip("no staged engine (set ASTRORAY_PYD_DIR or run scripts/build/build_blender_addon.py)")
    work = tmp_path_factory.mktemp("i1158")
    code, out = _run("make", work)
    assert code == 0, out
    assert re.search(r"library image filepath: //tex[/\\]lib_tex\.png", out), out
    code, out = _run("render", work)
    print(out)
    assert code == 0, out
    m = re.search(r"\[1158\] ROI_MEAN (\S+) (\S+) (\S+)", out)
    assert m, out
    return tuple(float(x) for x in m.groups()), out


@pytest.mark.skipif(BLENDER_EXE is None, reason="Blender not found")
def test_library_linked_image_renders_texture_not_magenta(library_render):
    roi, out = library_render
    assert "linked image library:" in out and "linked image library: None" not in out, out
    expected = tuple(_srgb_to_linear(c) for c in TEXEL_RAW)
    # Magenta fallback would be ~(1, 0, 1): green channel near zero, red/blue large.
    assert roi[1] > 2.0 * roi[0] and roi[1] > 2.0 * roi[2], f"ROI {roi} looks magenta/flat"
    for got, want in zip(roi, expected):
        assert got == pytest.approx(want, rel=0.15, abs=0.02), (roi, expected)


@pytest.mark.skipif(BLENDER_EXE is None, reason="Blender not found")
def test_library_linked_image_logs_no_degraded_entry(library_render):
    _roi, out = library_render
    assert not re.search(r"degraded lib_tex\.png", out), out
