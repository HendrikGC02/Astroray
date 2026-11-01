"""#1216 - a World Environment Texture pointing at an ``.exr`` rendered the fallback
background silently: the engine reads environments through stb_image (no EXR), and the
addon's load-failure branch only printed. Fixes:

  * the load-failure branch reports DEGRADED and renders the magenta fallback (as the
    pkg274 #723 missing-file branch does);
  * an ``.exr`` world is converted addon-side (Blender image API -> temp Radiance .hdr).
    Cycles samples an EXR as the scene-linear float buffer with no view transform, which
    is what ``image.pixels`` returns, so the engine sees the same values.

Headless-Blender renders of a synthetic 16-block map (distinct colours, so orientation and
colour errors move the per-quadrant means). Skips without Blender or a staged engine.

Engine: ``ASTRORAY_PYD_DIR`` (default ``<repo>/dist/astroray``); addon under test is
always ``<repo>/blender_addon``.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ADDON_DIR = REPO_ROOT / "blender_addon"
PYD_DIR = Path(os.environ.get("ASTRORAY_PYD_DIR", REPO_ROOT / "dist" / "astroray"))
sys.path.insert(0, str(ADDON_DIR))
import sky_bake  # noqa: E402  (write_hdr: the repo's Radiance writer)

H, W = 32, 64
QUADS = ("TL", "TR", "BL", "BR")

_SCRIPT = r"""
import sys, os, glob, importlib.util
args = sys.argv[sys.argv.index("--") + 1:]
mode, addon_dir, pyd_dir, workdir = args[:4]
import bpy
import numpy as np


def mkexr(npy, exr_path):
    rgb = np.load(npy)                       # (H, W, 3), row 0 = top of the map
    h, w = rgb.shape[:2]
    rgba = np.ones((h, w, 4), dtype=np.float32)
    rgba[:, :, :3] = rgb[::-1]               # Blender pixels are bottom-up
    img = bpy.data.images.new("map", w, h, alpha=False, float_buffer=True)
    img.pixels.foreach_set(rgba.ravel())
    img.filepath_raw = exr_path
    img.file_format = "OPEN_EXR"
    img.save()
    print("[1216] wrote", exr_path)


def render(world_image, out_stem, colorspace, engine):
    if engine == "CUSTOM_RAYTRACER":
        sys.path.insert(0, pyd_dir)
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(pyd_dir)
        os.environ.setdefault("ASTRORAY_DATA_DIR", os.path.join(pyd_dir, "data"))
        spec = importlib.util.spec_from_file_location("astroray_addon_i1216", addon_dir + "/__init__.py")
        addon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(addon)
        addon.register()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    world = bpy.data.worlds.new("W")
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(world_image)
    if colorspace:
        env.image.colorspace_settings.name = colorspace
    bg = nt.nodes.new("ShaderNodeBackground")
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    scene.world = world
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    cam.data.angle = 1.5707963  # 90 deg: the equator band, rows 8..24 of the map
    cam.rotation_euler = (1.5707963, 0.0, 0.0)
    scene.collection.objects.link(cam)
    scene.camera = cam
    scene.render.engine = engine
    scene.view_settings.view_transform = "Standard"
    scene.render.resolution_x = scene.render.resolution_y = 96
    scene.render.resolution_percentage = 100
    scene.cycles.samples = 16
    if engine == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.use_denoising = False
    else:
        cr = scene.custom_raytracer
        if hasattr(cr, "device_mode"):
            cr.device_mode = "cpu"
        if hasattr(cr, "use_adaptive_sampling"):
            cr.use_adaptive_sampling = False
    for f in glob.glob(out_stem + "*"):
        os.remove(f)
    scene.render.filepath = out_stem
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    bpy.ops.render.render(write_still=True)
    res = bpy.data.images.load(sorted(glob.glob(out_stem + "*"))[0])
    w, h = res.size
    px = np.asarray(res.pixels[:], dtype=np.float32).reshape(h, w, 4)[::-1, :, :3]
    print("[1216] MEAN %.6f %.6f %.6f" % tuple(px.reshape(-1, 3).mean(axis=0)))
    for name, (ys, xs) in zip(("TL", "TR", "BL", "BR"),
                              ((slice(0, h // 2), slice(0, w // 2)), (slice(0, h // 2), slice(w // 2, w)),
                               (slice(h // 2, h), slice(0, w // 2)), (slice(h // 2, h), slice(w // 2, w)))):
        print("[1216] Q %s %.6f %.6f %.6f" % ((name,) + tuple(px[ys, xs].reshape(-1, 3).mean(axis=0))))


if mode == "mkexr":
    mkexr(args[4], args[5])
else:
    render(args[4], args[5], args[6], "CYCLES" if mode == "cycles" else "CUSTOM_RAYTRACER")
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
pytestmark = pytest.mark.skipif(BLENDER_EXE is None, reason="Blender not found")


def _run(work, *args):
    script = work / "i1216_driver.py"
    script.write_text(_SCRIPT, encoding="utf-8")
    cmd = [str(BLENDER_EXE), "--background", "--factory-startup", "--python", str(script),
           "--", args[0], str(ADDON_DIR), str(PYD_DIR), str(work), *[str(a) for a in args[1:]]]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
    out = r.stdout + "\n" + r.stderr
    assert r.returncode == 0, out
    return out


def _parse(out):
    mean = tuple(float(x) for x in re.search(r"\[1216\] MEAN (\S+) (\S+) (\S+)", out).groups())
    quads = {m[0]: tuple(float(x) for x in m[1:])
             for m in re.findall(r"\[1216\] Q (\w\w) (\S+) (\S+) (\S+)", out)}
    return mean, quads


def _synthetic_map():
    """16 blocks (4 cols x 4 rows of 16x8 texels), each a distinct colour."""
    rng = np.random.default_rng(1216)
    blocks = rng.uniform(0.05, 4.0, size=(4, 4, 3)).astype(np.float32)
    return np.repeat(np.repeat(blocks, H // 4, axis=0), W // 4, axis=1)


@pytest.fixture(scope="module")
def renders(tmp_path_factory):
    if not list(PYD_DIR.glob("astroray*.pyd")):
        pytest.skip("no staged engine (set ASTRORAY_PYD_DIR or run scripts/build/build_blender_addon.py)")
    work = tmp_path_factory.mktemp("i1216")
    rgb = _synthetic_map()
    np.save(work / "map.npy", rgb)
    sky_bake.write_hdr(str(work / "ref.hdr"), rgb)          # row 0 = top
    _run(work, "mkexr", work / "map.npy", work / "map.exr")
    (work / "corrupt.exr").write_bytes(b"not an openexr file" * 20)
    (work / "corrupt.hdr").write_bytes(b"not a radiance file" * 20)
    outs = {}
    # Setting a colorspace on a loaded EXR makes Blender re-interpret its buffer (it assumes
    # the file is sRGB-tagged), so the explicit-colorspace reference is Cycles, not the raw map.
    for key, mode, img, cs in (("hdr", "render", "ref.hdr", ""), ("exr", "render", "map.exr", ""),
                               ("exr_noncolor", "render", "map.exr", "Non-Color"),
                               ("exr_linear", "render", "map.exr", "Linear Rec.709"),
                               ("cycles", "cycles", "map.exr", ""),
                               ("cycles_noncolor", "cycles", "map.exr", "Non-Color"),
                               ("cycles_linear", "cycles", "map.exr", "Linear Rec.709"),
                               ("corrupt_exr", "render", "corrupt.exr", ""),
                               ("corrupt_hdr", "render", "corrupt.hdr", "")):
        outs[key] = _run(work, mode, work / img, work / f"r_{key}", cs)
    return outs


def _assert_close(a, b, rel=0.03, what=""):
    assert a == pytest.approx(b, rel=rel, abs=0.02), (what, a, b)


def test_reference_hdr_render_is_non_degenerate(renders):
    """The synthetic map must make the four quadrants distinct, else orientation passes blind."""
    _mean, q = _parse(renders["hdr"])
    cols = [q[k] for k in QUADS]
    for i in range(4):
        for j in range(i + 1, 4):
            assert max(abs(x - y) for x, y in zip(cols[i], cols[j])) > 0.3, (QUADS[i], QUADS[j], cols)


def _assert_same_render(renders, key, ref_key):
    ref_mean, ref_q = _parse(renders[ref_key])
    mean, q = _parse(renders[key])
    _assert_close(mean, ref_mean, what="mean")
    for k in QUADS:
        _assert_close(q[k], ref_q[k], what=k)
    assert not re.search(r"degraded world HDRI", renders[key]), renders[key]


def test_exr_world_matches_hdr_world(renders):
    """Same mean AND same per-quadrant colours (catches flips/mirrors/channel swaps/view transform)."""
    _assert_same_render(renders, "exr", "hdr")


@pytest.mark.parametrize("suffix", ["", "_noncolor", "_linear"])
def test_exr_world_matches_cycles(renders, suffix):
    """Colour management parity: Astroray sees the values Cycles samples, whatever the
    image colorspace setting (default, explicit Non-Color, explicit Linear Rec.709)."""
    _assert_same_render(renders, "exr" + suffix, "cycles" + suffix)


@pytest.mark.parametrize("key", ["corrupt_exr", "corrupt_hdr"])
def test_unreadable_environment_degrades_and_renders_magenta(renders, key):
    out = renders[key]
    # The report is emitted once (Blender then mirrors it as a "Warning:" line).
    lines = re.findall(r"^Astroray degradation: .*$", out, flags=re.M)
    assert len(lines) == 1, out
    assert "1 degraded" in lines[0] and lines[0].count("degraded world HDRI") == 1, lines
    mean, _q = _parse(out)
    assert mean[0] == pytest.approx(1.0, abs=0.05) and mean[2] == pytest.approx(1.0, abs=0.05), mean
    assert mean[1] == pytest.approx(0.0, abs=0.05), mean
