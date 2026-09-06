# -*- coding: utf-8 -*-
"""pkg119 Phase B - single (feature, engine) render leg (runs INSIDE Blender).

Invoked once per feature per engine by ``harness.py`` for subprocess isolation
(pkg71 discipline: Cycles and the Astroray addon hold conflicting global state,
so each engine renders in its own Blender process). Builds the scene for exactly
one matrix feature via ``scene_library``, renders it with one engine, and writes
the LINEAR scene-referred pixels to ``<out>.npy`` (float32 HxWx3) plus a display
PNG for the human report.

Contract with the driver:
  * On success prints ``PKG119B_LEG PASS`` and writes ``<out>.npy``.
  * On ANY failure prints ``PKG119B_LEG FAIL <reason>`` and exits 0 (Blender
    swallows tracebacks and exits 0 anyway - the sentinel, not the exit code, is
    the source of truth; memory: dev_loop_guards sentinel). The driver treats a
    missing/!PASS leg as a crashed feature, records it, and continues.

Run:
    blender --background --factory-startup --python render_leg.py -- \
        --category shader_node --feature TEX_NOISE \
        --bl-idname ShaderNodeTexNoise --engine CYCLES --out <path> \
        --res 128 --samples 64
"""

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

SENTINEL = "PKG119B_LEG"


def _fail(reason: str):
    print(f"{SENTINEL} FAIL {reason}", flush=True)
    # Exit 0 on purpose: the driver keys on the sentinel, not the exit code.
    sys.exit(0)


def _bootstrap_astroray_addon(repo_root: Path):
    """Load the .pyd + register the addon, mirroring generate_blender_parity_matrix."""
    default_build = repo_root / "build_cuda"
    if not list(default_build.glob("astroray*.pyd")):
        default_build = repo_root / "build_cuda" / "Release"
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
    print(f"[pkg119b-leg] astroray module: {astroray.__file__}", flush=True)
    import blender_addon
    try:
        blender_addon.register()
    except Exception as exc:  # noqa: BLE001
        if "already registered" not in str(exc):
            raise


def _configure_render(scene, engine, res, samples, device="gpu", res_y=None):
    scene.render.resolution_x = res
    scene.render.resolution_y = res if res_y is None else res_y
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.render.image_settings.exr_codec = "NONE"
    scene.render.engine = engine
    # Astroray also consumes these native Cycles settings (pkg176).
    if hasattr(scene, "cycles"):
        scene.cycles.samples = samples
        scene.cycles.use_denoising = False
        scene.cycles.use_adaptive_sampling = False
        scene.cycles.seed = 7
    if engine == "CUSTOM_RAYTRACER" and hasattr(scene, "custom_raytracer"):
        cr = scene.custom_raytracer
        cr.samples = samples
        if hasattr(cr, "preview_samples"):
            cr.preview_samples = samples
        if hasattr(cr, "device_mode"):
            cr.device_mode = device
        # Adaptive sampling remains an Astroray-only setting in the resolver.
        cr.use_adaptive_sampling = False


def _render_to_npy(bpy, scene, out_stem: Path, res: int):
    import glob
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
    # Display PNG (sRGB) for the human report.
    try:
        from PIL import Image
        srgb = np.where(px <= 0.0031308, px * 12.92,
                        1.055 * np.clip(px, 0, None) ** (1 / 2.4) - 0.055)
        Image.fromarray((np.clip(srgb, 0, 1) * 255 + 0.5).astype(np.uint8)).save(
            out_stem.with_suffix(".png"))
    except Exception:  # noqa: BLE001 - PNG is cosmetic
        pass
    return npy_path


def _object_and_node_report(bpy):
    """Reopen-verification payload: object counts + shader-graph node ids.
    Pure inspection, no render - used by --report-only after --load-blend."""
    scene = bpy.context.scene
    obj_counts: dict = {}
    for obj in scene.objects:
        obj_counts[obj.type] = obj_counts.get(obj.type, 0) + 1

    node_ids = set()
    for mat in bpy.data.materials:
        if mat.use_nodes and mat.node_tree:
            node_ids.update(n.bl_idname for n in mat.node_tree.nodes)
    if scene.world and scene.world.use_nodes and scene.world.node_tree:
        node_ids.update(n.bl_idname for n in scene.world.node_tree.nodes)

    tri_count = 0
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        for poly in obj.data.polygons:
            tri_count += max(0, len(poly.vertices) - 2)
    # Hair/curve strand segments (not triangles, but part of the geometry
    # census the manifest records).
    curve_points = 0
    curve_count = 0
    for obj in scene.objects:
        if obj.type == "CURVES":
            curve_count += len(obj.data.curves)
            curve_points += len(obj.data.points)

    return {
        "object_counts": obj_counts,
        "object_names": sorted(o.name for o in scene.objects),
        "node_ids": sorted(node_ids),
        "triangle_count": tri_count,
        "curve_count": curve_count,
        "curve_point_count": curve_points,
    }


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--category", default="")
    p.add_argument("--feature", default="")
    p.add_argument("--bl-idname", default="")
    p.add_argument("--engine", choices=("CYCLES", "CUSTOM_RAYTRACER"))
    p.add_argument("--out", help="output stem (no extension)")
    p.add_argument("--res", type=int, default=128)
    p.add_argument("--res-y", type=int, default=None)
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--device", choices=("cpu", "gpu", "auto"), default="gpu",
                   help="Astroray backend (default: gpu; Cycles stays on CPU)")
    p.add_argument("--export-blend", default="",
                   help="build the (category, feature) scene and save it as a "
                        ".blend at this path instead of rendering")
    p.add_argument("--load-blend", default="",
                   help="open this .blend instead of building a scene from "
                        "(category, feature)")
    p.add_argument("--report-only", action="store_true",
                   help="with --load-blend: print an object/node census as "
                        "JSON and exit, no render")
    args = p.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    try:
        import bpy
        import scene_library

        if args.load_blend:
            bpy.ops.wm.open_mainfile(filepath=args.load_blend)
            scene = bpy.context.scene
        else:
            if not args.category or not args.feature:
                raise ValueError("--category/--feature are required unless --load-blend is given")
            scene = scene_library.build_scene(
                bpy, args.category, args.feature, args.bl_idname, engine=args.engine)

        if args.report_only:
            report = _object_and_node_report(bpy)
            print(f"{SENTINEL} REPORT {json.dumps(report)}", flush=True)
            print(f"{SENTINEL} PASS", flush=True)
            return

        if args.export_blend:
            spec = scene_library.REFERENCE_SCENES.get(args.feature)
            if spec is None:
                raise ValueError(f"--export-blend needs a reference_scene feature, got {args.feature!r}")
            _configure_render(scene, "CYCLES", spec["res_x"], spec["samples"],
                               res_y=spec["res_y"])
            out_path = Path(args.export_blend)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            bpy.ops.wm.save_as_mainfile(filepath=str(out_path))
            # The HDRI world (hdri_exterior_hair only) was loaded via an
            # absolute path so the build could read real pixels; now that
            # bpy.data.filepath is the final saved location, rewrite it to
            # the repo-relative "//..." form and re-save so a fresh Blender
            # process resolves it from THIS file's directory (task spec:
            # verify the relative path resolves from the scene directory).
            hdri_relpath = scene.get("hdri_relpath")
            if hdri_relpath:
                for img in bpy.data.images:
                    if img.source == "FILE" and img.filepath.endswith("test_env.hdr"):
                        img.filepath_raw = hdri_relpath
                bpy.ops.wm.save_as_mainfile(filepath=str(out_path))
            print(f"[pkg119b-leg] exported {out_path}", flush=True)
            print(f"{SENTINEL} PASS", flush=True)
            return

        if args.engine == "CUSTOM_RAYTRACER":
            _bootstrap_astroray_addon(repo_root)

        _configure_render(scene, args.engine, args.res, args.samples, args.device,
                           res_y=args.res_y)
        out_stem = Path(args.out)
        out_stem.parent.mkdir(parents=True, exist_ok=True)
        npy = _render_to_npy(bpy, scene, out_stem, args.res)
        print(f"[pkg119b-leg] wrote {npy}", flush=True)
        print(f"{SENTINEL} PASS", flush=True)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _fail(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
