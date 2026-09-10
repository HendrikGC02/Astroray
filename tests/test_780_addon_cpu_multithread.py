"""issue #780: the Blender addon's CPU renders must be multi-threaded.

``scripts/build/build_blender_addon.py`` forced ``-DASTRORAY_DISABLE_OPENMP=ON``
for every addon build, so every Blender CPU render (F12 and viewport CPU mode)
ran on one core while the in-process pytest ``.pyd`` used all of them.

The hang that motivated that flag (pkg147, memory ``mingw_openmp_blender_deadlock``)
was **not** a libgomp/vcomp toolchain defect. ``PyRenderer::render()`` held the
GIL across the whole CPU tile loop while the OpenMP worker that finished a tile
blocked in ``py::gil_scoped_acquire`` for the progress callback — a circular wait
between the master thread (parked in ``gomp_team_barrier_wait_end``, holding the
GIL) and every worker (parked in ``PyEval_AcquireThread``). pkg241 (#748) added
the ``py::gil_scoped_release`` around the CPU render, which removes it. Verified
on both toolchains (MinGW/libgomp and MSVC/vcomp140) and both Blender 5.1 and
5.2 — see ``.astroray_plan/docs/780-addon-openmp-deadlock-root-cause-2026-09.md``.

Three layers, cheapest first:

1. ``test_addon_build_config_enables_openmp`` — pure config assertion; this is
   the one that fails on the pre-fix tree and needs neither Blender nor a build.
2. ``test_configure_backend_cpu_accepts_openmp_build`` — the pkg147 refusal
   (``_check_openmp_disabled``) must stay gone; ``device_mode='cpu'`` with an
   OpenMP-enabled ``.pyd`` must select CPU instead of raising. Replaces
   ``tests/test_pkg147_openmp_guard.py``, whose author's intent (never let the
   addon walk into the hang) is now served by keeping the deadlock fixed rather
   than by refusing to render.
3. ``test_staged_addon_cpu_render_is_multithreaded`` — the real gate: run a
   headless ``blender -b`` F12 CPU render plus a raw-binding render shaped like
   the viewport leg's progress callback, under a hard timeout, and assert
   process-CPU-time / wall-time > 2. Skips when Blender or a staged addon
   (``dist/astroray``, or ``$ASTRORAY_ADDON_DIR``) is missing.
"""

import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build" / "build_blender_addon.py"

#: process-CPU / wall floor that separates "threaded" from "one core busy".
#: Measured 2026-09-09 on an 8-core 7800X3D: 0.89-0.95 single-threaded,
#: 4.4-5.6 threaded (MinGW and MSVC, Blender 5.1 and 5.2).
MIN_CPU_WALL_RATIO = 2.0


def _load_build_script():
    spec = importlib.util.spec_from_file_location("_bba_780", BUILD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# 1. Build configuration
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("backend", ["cpu", "cuda", "tcnn"])
def test_addon_build_config_enables_openmp(backend):
    """Every addon backend must configure -DASTRORAY_DISABLE_OPENMP=OFF."""
    module = _load_build_script()
    _build_dir, flags = module._backend_config(backend)
    assert "-DASTRORAY_DISABLE_OPENMP=OFF" in flags, (
        f"backend {backend!r} would build the addon single-threaded "
        f"(issue #780); flags={flags}"
    )
    assert "-DASTRORAY_DISABLE_OPENMP=ON" not in flags


def test_dev_loop_guard_requires_openmp_on():
    """scripts/dev_addon.ps1's (b) guard now defends the opposite invariant."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import dev_loop_guards as guards
    finally:
        sys.path.pop(0)
    assert guards.openmp_enabled_in_flags(["-DASTRORAY_DISABLE_OPENMP=OFF"]) is True
    assert guards.openmp_enabled_in_flags(["-DASTRORAY_DISABLE_OPENMP=ON"]) is False
    assert guards.openmp_enabled_in_flags([]) is False


# --------------------------------------------------------------------------- #
# 2. The pkg147 CPU-render refusal must stay removed
# --------------------------------------------------------------------------- #

def _make_stub_bpy():
    """Minimal stub bpy so blender_addon imports outside Blender.

    Lifted verbatim from the deleted tests/test_pkg147_openmp_guard.py.
    """
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")
    bpy_utils_module = types.ModuleType("bpy.utils")

    class _Base:
        pass

    for name in ("Panel", "Operator", "AddonPreferences", "PropertyGroup",
                 "RenderEngine", "Material", "Scene", "Object"):
        setattr(bpy_types_module, name, _Base)
    bpy_module.types = bpy_types_module

    for name in ("BoolProperty", "IntProperty", "FloatProperty", "StringProperty",
                 "PointerProperty", "FloatVectorProperty", "EnumProperty"):
        setattr(bpy_props_module, name, lambda **_kwargs: None)
    bpy_module.props = bpy_props_module

    registered = []
    bpy_utils_module.register_class = lambda cls: registered.append(cls)
    bpy_utils_module.unregister_class = (
        lambda cls: registered.remove(cls) if cls in registered else None)
    bpy_module.utils = bpy_utils_module
    bpy_module.path = types.SimpleNamespace(abspath=lambda p: p)

    mathutils_module = types.ModuleType("mathutils")
    mathutils_module.Vector = lambda values: values

    sys.modules["bpy"] = bpy_module
    sys.modules["bpy.types"] = bpy_types_module
    sys.modules["bpy.props"] = bpy_props_module
    sys.modules["bpy.utils"] = bpy_utils_module
    sys.modules["mathutils"] = mathutils_module
    return bpy_module


def _cleanup_bpy_mock():
    for key in list(sys.modules.keys()):
        if key.startswith("bpy") or key in ("blender_addon", "shader_blending"):
            del sys.modules[key]


class _StubSettings:
    device_mode = "cpu"
    wavelength_preset = "visible"
    integrator_type = "path_tracer"


class _StubRenderer:
    gpu_available = True

    def set_use_gpu(self, flag):
        pass


def test_features_dict_has_openmp_key(astroray_module):
    """astroray.__features__ still reports whether the module is threaded."""
    assert "openmp" in astroray_module.__features__
    assert isinstance(astroray_module.__features__["openmp"], bool)


def test_configure_backend_cpu_accepts_openmp_build(astroray_module):
    """device_mode='cpu' with an OpenMP-enabled .pyd must select CPU.

    Pre-#780 this raised RuntimeError from _check_openmp_disabled().
    """
    _make_stub_bpy()
    try:
        import blender_addon
        assert not hasattr(blender_addon, "_check_openmp_disabled"), (
            "the pkg147 OpenMP refusal is back; issue #780 removed it")
        with patch.object(astroray_module, "__features__", {"openmp": True}):
            settings = _StubSettings()
            settings.device_mode = "cpu"
            assert blender_addon.configure_backend(_StubRenderer(), settings) == "cpu"
    finally:
        _cleanup_bpy_mock()


# --------------------------------------------------------------------------- #
# 3. Headless Blender render — the real multi-threading gate
# --------------------------------------------------------------------------- #

_IN_BLENDER = r'''
import importlib.util, json, os, sys, time, traceback

argv = sys.argv[sys.argv.index("--") + 1:]
addon_dir, out_json, res, spp = argv[0], argv[1], int(argv[2]), int(argv[3])

result = {"status": "fail", "reason": "", "openmp": None, "pyd": None,
          "f12": None, "binding": None}


def timed(fn):
    t0, c0 = time.perf_counter(), time.process_time()
    fn()
    wall = max(time.perf_counter() - t0, 1e-9)
    cpu = time.process_time() - c0
    return {"wall_s": wall, "cpu_s": cpu, "ratio": cpu / wall}


try:
    import bpy

    sys.path.insert(0, addon_dir)
    for d in (addon_dir, os.path.join(addon_dir, "oidn")):
        if os.path.isdir(d):
            try:
                os.add_dll_directory(d)
            except (OSError, AttributeError):
                pass

    import astroray
    result["pyd"] = astroray.__file__
    result["openmp"] = bool(astroray.__features__.get("openmp", False))

    spec = importlib.util.spec_from_file_location(
        "astroray_addon_780", os.path.join(addon_dir, "__init__.py"))
    addon = importlib.util.module_from_spec(spec)
    sys.modules["astroray_addon_780"] = addon
    spec.loader.exec_module(addon)
    addon.register()

    # --- leg 1: the F12 path (RenderEngine.render -> renderer.render with a
    # progress callback that calls back into bpy from the OpenMP workers).
    bpy.ops.wm.read_factory_settings()
    scene = bpy.context.scene
    scene.render.resolution_x = res
    scene.render.resolution_y = res
    scene.render.resolution_percentage = 100
    scene.render.engine = "CUSTOM_RAYTRACER"
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = os.path.join(os.path.dirname(out_json), "issue780_f12")
    cr = scene.custom_raytracer
    cr.samples = spp
    cr.max_bounces = 4
    cr.device_mode = "cpu"
    cr.use_adaptive_sampling = False
    cr.use_denoising = False
    result["f12"] = timed(lambda: bpy.ops.render.render(write_still=True))

    # --- leg 2: the raw binding with a pure-Python progress callback, the
    # shape blender_addon/exporter.py's viewport legs use (view_draw needs a
    # GL context, so it cannot run under blender -b).
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    white = r.create_material("lambertian", [0.73, 0.73, 0.73], {})
    light = r.create_material("light", [1.0, 0.9, 0.8], {"intensity": 12.0})
    r.add_sphere([0.0, -100.5, 0.0], 100.0, white)
    r.add_sphere([0.0, 0.0, 0.0], 0.5, white)
    r.add_sphere([0.0, 2.0, 0.0], 0.6, light)
    r.setup_camera(look_from=[0, 0, 4], look_at=[0, 0, 0], vup=[0, 1, 0],
                   vfov=40, aspect_ratio=1.0, aperture=0.0, focus_dist=4.0,
                   width=res, height=res)
    # 64x the F12 sample budget: process_time() has ~16 ms resolution on
    # Windows, so the leg has to run long enough for the ratio to mean anything
    # (measured ~0.8 s threaded on an 8-core 7800X3D).
    result["binding"] = timed(
        lambda: r.render(spp * 64, 6, lambda _frac: True, False))

    result["status"] = "ok"
except Exception as exc:  # noqa: BLE001
    result["reason"] = "%s: %s" % (type(exc).__name__, exc)
    traceback.print_exc()

with open(out_json, "w") as fh:
    json.dump(result, fh)
print("ISSUE780_PROBE " + json.dumps(result), flush=True)
'''


def _staged_addon_dir():
    """The staged addon built by scripts/build/build_blender_addon.py."""
    explicit = os.environ.get("ASTRORAY_ADDON_DIR", "")
    candidates = [Path(explicit)] if explicit else []
    candidates.append(REPO_ROOT / "dist" / "astroray")
    for candidate in candidates:
        if (candidate / "__init__.py").is_file() and list(candidate.glob("astroray*.pyd")):
            return candidate
    return None


def _blender_exes():
    """(label, path) for every locally installed Blender the addon supports."""
    explicit = os.environ.get("BLENDER_EXE", "")
    if explicit and Path(explicit).is_file():
        return [(Path(explicit).parent.name, Path(explicit))]
    found = []
    for version in ("5.1", "5.2"):
        exe = Path(rf"C:\Program Files\Blender Foundation\Blender {version}\blender.exe")
        if exe.is_file():
            found.append((version, exe))
    return found


_BLENDERS = _blender_exes()
_ADDON_DIR = _staged_addon_dir()


@pytest.mark.skipif(not _BLENDERS, reason="no local Blender install")
@pytest.mark.skipif(
    _ADDON_DIR is None,
    reason="no staged addon; run scripts/build/build_blender_addon.py first")
@pytest.mark.parametrize("label,blender_exe", _BLENDERS,
                         ids=[label for label, _ in _BLENDERS])
def test_staged_addon_cpu_render_is_multithreaded(label, blender_exe, tmp_path):
    """A headless CPU render must finish and use more than one core."""
    script = tmp_path / "issue780_probe.py"
    script.write_text(_IN_BLENDER, encoding="utf-8")
    out_json = tmp_path / "issue780_probe.json"

    cmd = [str(blender_exe), "--background", "--factory-startup",
           "--python", str(script), "--",
           str(_ADDON_DIR), str(out_json), "96", "16"]
    # A regression re-introduces a deadlock, not a slowdown: cap the wall clock
    # and kill by handle (never by command-line match).
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)
    try:
        stdout, _ = proc.communicate(timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        pytest.fail(
            f"Blender {label} CPU render did not finish in 300 s — the addon "
            f"CPU render deadlocked (issue #780 / pkg241 GIL release)")
    print(stdout)

    assert out_json.is_file(), f"probe wrote no result (Blender {label})"
    result = json.loads(out_json.read_text())
    assert result["status"] == "ok", result["reason"]
    assert result["openmp"] is True, (
        f"staged .pyd at {result['pyd']} was built without OpenMP; rebuild with "
        f"scripts/build/build_blender_addon.py")

    for leg in ("f12", "binding"):
        ratio = result[leg]["ratio"]
        print(f"[issue780] Blender {label} {leg}: wall={result[leg]['wall_s']:.2f}s "
              f"cpu={result[leg]['cpu_s']:.2f}s ratio={ratio:.2f}")
        assert result[leg]["wall_s"] > 0.25, (
            f"Blender {label} {leg} leg ran for {result[leg]['wall_s']:.3f}s — too "
            f"short for time.process_time()'s ~16 ms resolution to be meaningful")
        assert ratio > MIN_CPU_WALL_RATIO, (
            f"Blender {label} {leg} render used {ratio:.2f} cores on average "
            f"(<= {MIN_CPU_WALL_RATIO}); the addon is rendering single-threaded")
