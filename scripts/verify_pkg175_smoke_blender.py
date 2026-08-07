"""pkg175 dev-loop smoke — headless liveness gate for the freshly built addon.

Run inside Blender (headless):

    "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" \
        --background --factory-startup \
        --python scripts/verify_pkg175_smoke_blender.py

Two modes, selected by the ASTRORAY_SMOKE_MODE env var:

  register  — load the staged/installed addon and call register(). Proves the
              package imports (its bundled .pyd + DLLs) and its render engine
              registers. This is dev-loop guard (d): run against the STAGED dir
              BEFORE the install copy. Prints PKG175_REGISTER_RESULT PASS/FAIL.

  render    — everything register does, plus build a fixed, cheap scene
              (lit cube + Principled material + camera), render it at low spp
              through the Astroray engine, and assert the image is non-black,
              finite, and within a plausible mean-luminance band. This is a
              LIVENESS gate, not a parity gate (parity is pkg119-B). Prints
              PKG175_SMOKE_RESULT PASS/FAIL and PKG175_SMOKE_STATS.

Env vars:
  ASTRORAY_SMOKE_MODE      register | render   (default: render)
  ASTRORAY_SMOKE_ADDON_DIR directory holding the addon __init__.py + astroray*.pyd
                           (staged dir or the installed extension dir). When
                           unset, falls back to tests/runtime_setup discovery of
                           the dev build_cuda tree + blender_addon source.

Blender's --python swallows unhandled exceptions and still exits 0, so a bare
crash would look like success. The bottom of this file converts any exception
into an explicit FAIL line + nonzero exit. Callers MUST gate on the printed
"... PASS" string, never on the exit code alone.
"""
import importlib.util
import os
import sys
from pathlib import Path

import bpy  # type: ignore

MODE = os.environ.get("ASTRORAY_SMOKE_MODE", "render").strip().lower()
REGISTER_TOKEN = "PKG175_REGISTER_RESULT"
SMOKE_TOKEN = "PKG175_SMOKE_RESULT"

W = H = 96
SAMPLES = 16
MAX_DEPTH = 3
SEED = 175175


def _bootstrap():
    """Put the addon dir + engine .pyd on sys.path, register the addon, and
    return (astroray_module, addon_module)."""
    repo_root = Path(__file__).resolve().parents[1]
    addon_dir = os.environ.get("ASTRORAY_SMOKE_ADDON_DIR")

    if addon_dir:
        addon_dir = Path(addon_dir)
        # The staged/installed dir is self-contained: astroray*.pyd, its bundled
        # MinGW/CUDA/OIDN DLLs, and the addon Python all live here.
        if str(addon_dir) not in sys.path:
            sys.path.insert(0, str(addon_dir))
        if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
            for d in (addon_dir, addon_dir / "oidn"):
                if d.is_dir():
                    os.add_dll_directory(str(d))
            # CUDA runtime DLLs may live in the toolkit rather than the package.
            cuda_root = Path(os.environ.get(
                "CUDA_PATH",
                r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.8"))
            for d in (cuda_root / "bin", cuda_root / "bin" / "x64"):
                if d.is_dir():
                    os.add_dll_directory(str(d))
        init_path = addon_dir / "__init__.py"
    else:
        # Fallback: dev tree. Reuse the shared test bootstrap (build_cuda +
        # runtime DLL dirs) and the blender_addon source.
        sys.path.insert(0, str(repo_root / "tests"))
        import runtime_setup  # type: ignore
        runtime_setup.configure_test_imports(include_blender_addon=True)
        init_path = repo_root / "blender_addon" / "__init__.py"

    import astroray
    print("engine:", astroray.__file__)

    spec = importlib.util.spec_from_file_location("astroray_addon", init_path)
    addon = importlib.util.module_from_spec(spec)
    sys.modules["astroray_addon"] = addon
    spec.loader.exec_module(addon)
    print("addon :", init_path)
    addon.register()  # let it raise — a failed register IS a guard-(d) failure
    return astroray, addon


def _engine_standin(addon):
    """A bpy RenderEngine subclass cannot be instantiated outside the render
    pipeline, so mirror its plain-Python methods onto a standalone object
    (same technique as scripts/verify_pkg88b_blender.py)."""
    Engine = addon.CustomRaytracerRenderEngine

    class _S:
        def report(self, *a, **k):
            pass

    for name, fn in Engine.__dict__.items():
        if callable(fn) and not name.startswith("__"):
            setattr(_S, name, fn)
    return _S()


def _build_scene():
    """Fixed cheap scene: one lit cube with a Principled material + a camera,
    black world so the mean-luminance band is meaningful."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    bpy.ops.mesh.primitive_cube_add(size=1.5, location=(0.0, 0.0, 0.0))
    cube = bpy.context.object
    mat = bpy.data.materials.new("SmokeMat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.8, 0.3, 0.2, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.5
    cube.data.materials.append(mat)

    world = bpy.data.worlds.new("W")
    world.use_nodes = False
    world.color = (0.0, 0.0, 0.0)
    scene.world = world

    light_data = bpy.data.lights.new("L", type='POINT')
    light_data.energy = 3000.0
    light = bpy.data.objects.new("L", light_data)
    light.location = (2.5, -3.0, 4.0)
    scene.collection.objects.link(light)

    cam_data = bpy.data.cameras.new("C")
    cam = bpy.data.objects.new("C", cam_data)
    cam.location = (0.0, -6.0, 0.0)
    cam.rotation_euler = (1.5708, 0.0, 0.0)
    scene.collection.objects.link(cam)
    scene.camera = cam
    scene.render.resolution_x = W
    scene.render.resolution_y = H
    return scene


def _render(astroray, addon):
    import numpy as np
    _build_scene()
    st = _engine_standin(addon)
    r = astroray.Renderer()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    st.convert_scene(depsgraph, r, W, H)   # (self, depsgraph, renderer, w, h)
    r.set_seed(SEED)
    img = np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float32)
    return img


def _check_image(img) -> tuple[bool, dict]:
    import numpy as np
    lum = 0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]
    stats = {
        "shape": list(img.shape),
        "mean_lum": float(lum.mean()),
        "max_lum": float(lum.max()),
        "nonblack_frac": float((lum > 1e-4).mean()),
        "finite": bool(np.isfinite(img).all()),
    }
    ok = (
        stats["finite"]
        and stats["max_lum"] > 0.0
        and stats["nonblack_frac"] > 0.01     # the cube is visible
        and 1e-4 < stats["mean_lum"] < 100.0  # plausible band, not blown out
    )
    return ok, stats


def main():
    astroray, addon = _bootstrap()

    if MODE == "register":
        assert hasattr(addon, "CustomRaytracerRenderEngine"), \
            "addon registered but CustomRaytracerRenderEngine is missing"
        print(f"{REGISTER_TOKEN} PASS")
        return

    img = _render(astroray, addon)
    ok, stats = _check_image(img)
    print(f"PKG175_SMOKE_STATS {stats!r}")
    print(f"{SMOKE_TOKEN} {'PASS' if ok else 'FAIL'}")
    if not ok:
        sys.exit(1)


try:
    main()
except SystemExit:
    raise
except BaseException as exc:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    token = REGISTER_TOKEN if MODE == "register" else SMOKE_TOKEN
    print()
    print(f"{token} FAIL")
    print(f"PKG175_ERROR {type(exc).__name__}: {exc}")
    sys.exit(1)
