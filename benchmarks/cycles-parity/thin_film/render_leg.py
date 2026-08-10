# -*- coding: utf-8 -*-
"""pkg178 thin-film A/B — single (config, engine, device) render leg (INSIDE Blender).

Spawned once per leg by ``harness.py`` for subprocess isolation (pkg71/pkg119b/
pkg129 discipline: Cycles and the Astroray addon hold conflicting global state, so
each renders in its own Blender process). Builds one thin-film-sweep config via
``scenes.build_thinfilm_scene``, renders it with one engine+device, and writes the
LINEAR scene-referred pixels to ``<out>.npy`` (float32 HxWx3) plus an sRGB PNG.

The astroray-addon bootstrap + linear-EXR->npy plumbing are lifted verbatim from
``benchmarks/cycles-parity/metal_ab/render_leg.py`` (same OpenMP-OFF-.pyd /
ASTRORAY_PYD_DIR pattern; memory mingw_openmp_blender_deadlock). The ONLY
functional difference is the scene builder and forcing ``use_native_principled``
ON for the Astroray leg so the sphere routes through the native Principled plugin
(which honours the thin-film sockets), not the Disney-conversion fallback.

Contract with the driver:
  * On success prints ``PKG178TF_LEG PASS`` and writes ``<out>.npy``.
  * On ANY failure prints ``PKG178TF_LEG FAIL <reason>`` and exits 0 (Blender
    swallows tracebacks and exits 0 anyway — the sentinel is the source of truth).
"""

import argparse
import glob
import os
import sys
import traceback
from pathlib import Path

SENTINEL = "PKG178TF_LEG"


def _fail(reason: str):
    print(f"{SENTINEL} FAIL {reason}", flush=True)
    sys.exit(0)


def _bootstrap_astroray_addon(repo_root: Path):
    """Load the OpenMP-OFF .pyd + register the addon (mirrors metal_ab)."""
    default_build = repo_root / "build_blender_addon_cuda"
    if not list(default_build.glob("astroray*.pyd")):
        default_build = repo_root / "build_cuda"
    build_dir = Path(os.environ.get("ASTRORAY_PYD_DIR", default_build))
    for entry in (str(build_dir), str(repo_root)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    cuda_bin_candidates = [
        Path(os.environ.get("CUDA_PATH", "")) / "bin",
        Path(os.environ.get("CUDA_PATH", "")) / "bin" / "x64",
        Path(r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.8") / "bin" / "x64",
        Path(r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v13.2") / "bin" / "x64",
    ]
    for dll_dir in [build_dir] + cuda_bin_candidates:
        if dll_dir.is_dir():
            try:
                os.add_dll_directory(str(dll_dir))
            except (OSError, AttributeError):
                pass
    import astroray  # noqa: F401
    print(f"[pkg178tf-leg] astroray module: {astroray.__file__}", flush=True)
    import blender_addon
    try:
        blender_addon.register()
    except Exception as exc:  # noqa: BLE001
        if "already registered" not in str(exc):
            raise


def _configure_render(scene, engine, device, res, samples):
    scene.render.resolution_x = res
    scene.render.resolution_y = res
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    # pkg166 linear: Standard view transform, no gamma, 32-bit linear EXR.
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.render.image_settings.exr_codec = "NONE"
    scene.render.engine = engine
    if engine == "CYCLES":
        scene.cycles.samples = samples
        scene.cycles.use_denoising = False
        scene.cycles.use_adaptive_sampling = False
        scene.cycles.seed = 7
    elif hasattr(scene, "custom_raytracer"):
        cr = scene.custom_raytracer
        cr.samples = samples
        if hasattr(cr, "preview_samples"):
            cr.preview_samples = samples
        if hasattr(cr, "device_mode"):
            cr.device_mode = device  # 'cpu' or 'gpu'
        # Route through the NATIVE Principled plugin (honours thin-film sockets),
        # not the Disney-conversion fallback — this gate exists to validate that
        # path. Explicit even though the property already defaults ON.
        if hasattr(cr, "use_native_principled"):
            cr.use_native_principled = True


def _render_to_npy(bpy, scene, out_stem: Path):
    import numpy as np

    for f in glob.glob(str(out_stem) + "*"):
        try:
            os.remove(f)
        except OSError:
            pass
    scene.render.filepath = str(out_stem)
    bpy.ops.render.render(write_still=True)

    matches = sorted(glob.glob(str(out_stem) + "*.exr")) or sorted(glob.glob(str(out_stem) + "*"))
    if not matches:
        raise RuntimeError(f"no render output for stem {out_stem}")
    img = bpy.data.images.load(matches[0])
    w, h = img.size
    px = np.asarray(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[:, :, :3]
    bpy.data.images.remove(img)
    for f in matches:
        try:
            os.remove(f)
        except OSError:
            pass

    npy_path = out_stem.with_suffix(".npy")
    np.save(npy_path, np.ascontiguousarray(px))
    try:
        from PIL import Image
        srgb = np.where(px <= 0.0031308, px * 12.92,
                        1.055 * np.clip(px, 0, None) ** (1 / 2.4) - 0.055)
        Image.fromarray((np.clip(srgb, 0, 1) * 255 + 0.5).astype(np.uint8)).save(
            out_stem.with_suffix(".png"))
    except Exception:  # noqa: BLE001 - PNG is cosmetic
        pass
    return npy_path


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--engine", required=True, choices=("CYCLES", "CUSTOM_RAYTRACER"))
    p.add_argument("--device", default="gpu", choices=("cpu", "gpu"))
    p.add_argument("--out", required=True, help="output stem (no extension)")
    p.add_argument("--res", type=int, default=128)
    p.add_argument("--samples", type=int, default=256)
    args = p.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    try:
        import bpy
        import scenes

        if args.engine == "CUSTOM_RAYTRACER":
            _bootstrap_astroray_addon(repo_root)

        cfg = scenes.config_by_name(args.config)
        scene = scenes.build_thinfilm_scene(bpy, cfg)
        _configure_render(scene, args.engine, args.device, args.res, args.samples)
        out_stem = Path(args.out)
        out_stem.parent.mkdir(parents=True, exist_ok=True)
        npy = _render_to_npy(bpy, scene, out_stem)
        print(f"[pkg178tf-leg] wrote {npy}", flush=True)
        print(f"{SENTINEL} PASS", flush=True)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _fail(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
