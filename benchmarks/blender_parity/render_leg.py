# -*- coding: utf-8 -*-
"""pkg119 Phase B - single (feature, engine) render leg (runs INSIDE Blender).

Invoked once per feature per engine by ``harness.py`` for subprocess isolation
(pkg71 discipline: Cycles and the Astroray addon hold conflicting global state,
so each engine renders in its own Blender process). Builds the scene for exactly
one matrix feature via ``scene_library``, renders it with one engine, and writes
the LINEAR scene-referred pixels to ``<out>.npy`` (float32 HxWx3, row 0 = TOP of
the frame - flipped from Blender's native bottom-up buffer) plus a display PNG
for the human report.

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
import hashlib
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
    import astroray
    print(f"[pkg119b-leg] astroray module: {astroray.__file__}", flush=True)
    import blender_addon
    try:
        blender_addon.register()
    except Exception as exc:  # noqa: BLE001
        if "already registered" not in str(exc):
            raise
    return astroray, blender_addon


def _configure_render(scene, engine, res, samples, device="gpu", res_y=None, seed=278):
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
        scene.cycles.seed = seed
        scene.cycles.use_animated_seed = False
    if engine == "CUSTOM_RAYTRACER" and hasattr(scene, "custom_raytracer"):
        cr = scene.custom_raytracer
        cr.samples = samples
        if hasattr(cr, "preview_samples"):
            cr.preview_samples = samples
        if hasattr(cr, "device_mode"):
            cr.device_mode = device
        # Adaptive sampling remains an Astroray-only setting in the resolver.
        cr.use_adaptive_sampling = False


def _to_top_down(px):
    """Flip Blender's native bottom-up pixel buffer (row 0 = bottom of the
    picture) to top-down (row 0 = top), matching every ROI constant in
    harness.py (HDRI_BACKGROUND_ROI "top strip", HAIR_ROI "above the scalp
    apex", CHECKER_ROI "row 3, col 1") - blender_addon/__init__.py's
    image-loading path does the same flip for the same reason. Pure/bpy-free
    (takes a plain ndarray) so it is unit-testable without Blender - see
    tests/test_blender_parity_harness.py."""
    import numpy as np
    return np.ascontiguousarray(px[::-1, :, :])


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
    px = _to_top_down(px)
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


def _gate_c_control(bpy, scene, control):
    """Apply exactly one declared, reversible gate-C negative control."""
    kind = control.get("kind") if isinstance(control, dict) else ""
    receipt = {"kind": kind, "ok": False}
    if kind == "checker_flat":
        mat = bpy.data.materials.get(control.get("material")); node = mat and mat.node_tree.nodes.get(control.get("node"))
        if node is None or node.bl_idname != "ShaderNodeTexChecker":
            raise ValueError("gate-c checker binding is absent or wrong type")
        before = [list(node.inputs[n].default_value[:]) for n in ("Color1", "Color2")]
        flat = tuple((before[0][i] + before[1][i]) / 2.0 for i in range(4))
        node.inputs["Color1"].default_value = flat; node.inputs["Color2"].default_value = flat
        receipt.update({"material": mat.name, "node": node.name, "before": before, "after": [list(flat), list(flat)], "ok": True})
    elif kind == "hair_off":
        obj = bpy.data.objects.get(control.get("object"))
        if obj is None or obj.type != "CURVES": raise ValueError("gate-c hair binding is absent or wrong type")
        receipt.update({"object": obj.name, "type": obj.type, "was_hide_render": bool(obj.hide_render), "ok": True})
        obj.hide_render = True
    elif kind == "hdri_off":
        world = bpy.data.worlds.get(control.get("world")); node = world and world.node_tree.nodes.get(control.get("node"))
        if node is None or node.bl_idname != "ShaderNodeTexEnvironment": raise ValueError("gate-c HDRI binding is absent or wrong type")
        receipt.update({"world": world.name, "node": node.name, "image": getattr(node.image, "filepath", ""), "ok": bool(node.image)})
        node.image = None
    else: raise ValueError("unknown gate-c control")
    return receipt


def _gate_c_mask(bpy, scene, control, shape):
    """Return a source-geometry-derived top-down mask, never an image crop."""
    import numpy as np
    h, w = shape; spec = control.get("mask", {}); kind = spec.get("kind")
    mask = np.zeros((h, w), dtype=np.uint8)
    if kind == "rect":
        x0, y0, x1, y1 = spec["roi"]; mask[int(y0*h):int(y1*h), int(x0*w):int(x1*w)] = 255
        return mask
    obj = bpy.data.objects.get(control.get("object")) if kind in ("object_polygon", "curves") else None
    if kind in ("object_polygon", "curves") and obj is None: raise ValueError("gate-c mask object absent")
    from bpy_extras.object_utils import world_to_camera_view
    def point(co):
        v = world_to_camera_view(scene, scene.camera, obj.matrix_world @ co)
        return (v.x*w, (1.0-v.y)*h)
    if kind == "object_polygon":
        if not obj.data.polygons: raise ValueError("gate-c checker object has no face")
        pts = [point(obj.data.vertices[i].co) for i in obj.data.polygons[0].vertices]
        cx, cy = sum(p[0] for p in pts)/len(pts), sum(p[1] for p in pts)/len(pts); inset = float(spec.get("inset", 0.0))
        pts = [(cx+(x-cx)*(1-inset), cy+(y-cy)*(1-inset)) for x,y in pts]
        # Ray-crossing fill; plane vertices are the actual named card geometry.
        yy, xx = np.mgrid[:h, :w]; inside = np.zeros((h,w), dtype=bool)
        for (x0,y0),(x1,y1) in zip(pts, pts[1:]+pts[:1]):
            inside ^= ((y0 > yy) != (y1 > yy)) & (xx < (x1-x0)*(yy-y0)/(y1-y0+1e-12)+x0)
        mask[inside] = 255
    elif kind == "curves":
        radius = int(spec.get("radius_px", 1))
        for curve in obj.data.curves:
            pts = [point(p.position) for p in curve.points]
            for (x0,y0),(x1,y1) in zip(pts, pts[1:]):
                steps=max(1,int(max(abs(x1-x0),abs(y1-y0))*2))
                for t in range(steps+1):
                    x=int(round(x0+(x1-x0)*t/steps)); y=int(round(y0+(y1-y0)*t/steps))
                    mask[max(0,y-radius):min(h,y+radius+1), max(0,x-radius):min(w,x+radius+1)] = 255
    elif kind == "sky_rays":
        # Visibility mask: only camera rays that miss actual scene geometry may witness the world.
        x0,y0,x1,y1=spec["roi"]; frame=scene.camera.data.view_frame(scene=scene); origin=scene.camera.matrix_world.translation
        deps=bpy.context.evaluated_depsgraph_get()
        for y in range(int(y0*h), int(y1*h)):
            v=1.0-(y+.5)/h
            for x in range(int(x0*w), int(x1*w)):
                u=(x+.5)/w; local=frame[0].lerp(frame[1],u).lerp(frame[3].lerp(frame[2],u),v).normalized(); direction=(scene.camera.matrix_world.to_3x3() @ local).normalized()
                if not scene.ray_cast(deps, origin, direction)[0]: mask[y,x]=255
    else: raise ValueError("unknown gate-c mask kind")
    if not mask.any(): raise ValueError("gate-c geometry mask is empty")
    return mask


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
    p.add_argument("--corpus-manifest", default="",
                   help="validated reference-corpus manifest; requires --corpus-scene")
    p.add_argument("--corpus-scene", default="",
                   help="exact reference-corpus scene ID, never an arbitrary path")
    p.add_argument("--gate-c-freeze", default="", help="hash-pinned gate-c freeze input")
    p.add_argument("--gate-c-freeze-sha256", default="")
    p.add_argument("--gate-c-build-id", default="")
    p.add_argument("--gate-c-seed", type=int, default=278)
    p.add_argument("--gate-c-control", default="", help="declared gate-c negative control kind")
    p.add_argument("--gate-c-mask-out", default="", help="write source-geometry gate-c mask here")
    p.add_argument("--report-only", action="store_true",
                   help="with --load-blend: print an object/node census as "
                        "JSON and exit, no render")
    args = p.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    try:
        import bpy
        import scene_library

        if bool(args.corpus_manifest) != bool(args.corpus_scene):
            raise ValueError("--corpus-manifest and --corpus-scene must be supplied together")
        corpus_entry = None
        if args.corpus_scene:
            corpus = scene_library.load_corpus_manifest(Path(args.corpus_manifest))
            corpus_entry = corpus.get(args.corpus_scene)
            if corpus_entry is None:
                raise ValueError(f"corpus scene absent: {args.corpus_scene!r}")
            args.load_blend = str((repo_root / corpus_entry["blend_path"]).resolve())
            for key, arg in (("res_x", "res"), ("res_y", "res_y"), ("samples", "samples")):
                requested = getattr(args, arg)
                declared = corpus_entry["settings"][key]
                if requested != p.get_default(arg) and requested != declared:
                    raise ValueError(f"corpus scene {args.corpus_scene!r} requires {arg}={declared}")
                setattr(args, arg, declared)
            if args.gate_c_freeze:
                freeze = Path(args.gate_c_freeze)
                if (not freeze.is_file() or hashlib.sha256(freeze.read_bytes()).hexdigest() != args.gate_c_freeze_sha256):
                    raise ValueError("gate-c freeze artifact hash mismatch")
        if args.load_blend:
            bpy.ops.wm.open_mainfile(filepath=args.load_blend)
            scene = bpy.context.scene
        else:
            if not args.category or not args.feature:
                raise ValueError("--category/--feature are required unless --load-blend is given")
            scene = scene_library.build_scene(
                bpy, args.category, args.feature, args.bl_idname, engine=args.engine)

        control = None
        if args.gate_c_control:
            if not args.gate_c_freeze:
                raise ValueError("gate-c control requires a frozen declaration")
            role = next((v for v in freeze.get("roles", {}).values() if v.get("scene_id") == args.corpus_scene), None)
            control = next((c for c in role.get("controls", []) if c.get("kind") == args.gate_c_control), None) if role else None
            if control is None: raise ValueError("gate-c control is not declared for corpus scene")
            # Mask before mutation/render; it binds the named original geometry.
            if args.gate_c_mask_out:
                import numpy as np
                mask = _gate_c_mask(bpy, scene, control, (int(scene.render.resolution_y), int(scene.render.resolution_x)))
                Path(args.gate_c_mask_out).parent.mkdir(parents=True, exist_ok=True); np.save(args.gate_c_mask_out, mask)
            receipt = _gate_c_control(bpy, scene, control)
        else:
            receipt = {"kind": "baseline", "ok": True}

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

        astroray = addon = None
        if args.engine == "CUSTOM_RAYTRACER":
            astroray, addon = _bootstrap_astroray_addon(repo_root)

        _configure_render(scene, args.engine, args.res, args.samples, args.device,
                           res_y=args.res_y, seed=args.gate_c_seed)
        out_stem = Path(args.out)
        out_stem.parent.mkdir(parents=True, exist_ok=True)
        telemetry = []
        engine_cls = getattr(addon, "CustomRaytracerRenderEngine", None) if addon else None
        original_write = getattr(engine_cls, "write_pixels", None) if engine_cls else None
        if original_write is not None:
            def capture_write(self, *call_args, **call_kwargs):
                renderer = call_kwargs.get("renderer")
                if renderer is None and len(call_args) >= 5:
                    renderer = call_args[4]
                if renderer is not None:
                    try: telemetry.append(dict(renderer.last_render_info() or {}))
                    except Exception as exc: telemetry.append({"last_render_info_error": repr(exc)})
                return original_write(self, *call_args, **call_kwargs)
            engine_cls.write_pixels = capture_write
        try:
            npy = _render_to_npy(bpy, scene, out_stem, args.res)
        finally:
            if engine_cls is not None and original_write is not None:
                engine_cls.write_pixels = original_write
        if corpus_entry is not None:
            module = ""; module_sha = ""; addon_path = ""; addon_sha = ""; observed_build = ""
            if args.engine == "CUSTOM_RAYTRACER":
                module = str(Path(astroray.__file__).resolve())
                module_sha = hashlib.sha256(Path(module).read_bytes()).hexdigest()
                addon_path = str(Path(addon.__file__).resolve())
                addon_sha = hashlib.sha256(Path(addon_path).read_bytes()).hexdigest()
                observed_build = str(getattr(astroray, "__build__", ""))
            devices = [info.get("device") for info in telemetry if isinstance(info, dict) and isinstance(info.get("device"), (int, float))]
            effective_device = ("gpu" if devices and all(value >= 0 for value in devices) else
                                ("cpu" if devices and all(value < 0 for value in devices) else ""))
            print(f"{SENTINEL} REPORT {json.dumps({'corpus_scene': args.corpus_scene, 'blend_sha256': hashlib.sha256(Path(args.load_blend).read_bytes()).hexdigest(), 'freeze_sha256': args.gate_c_freeze_sha256, 'build_id': observed_build, 'requested_device': args.device, 'effective_device': effective_device, 'telemetry': telemetry, 'engine': str(scene.render.engine), 'res_x': int(scene.render.resolution_x), 'res_y': int(scene.render.resolution_y), 'samples': int(scene.cycles.samples), 'resolved_seed': int(scene.cycles.seed), 'animated_seed': bool(scene.cycles.use_animated_seed), 'blender_version': bpy.app.version_string, 'module_path': module, 'module_sha256': module_sha, 'addon_path': addon_path, 'addon_sha256': addon_sha, 'mutation_receipt': receipt, 'mask_path': args.gate_c_mask_out})}", flush=True)
        print(f"[pkg119b-leg] wrote {npy}", flush=True)
        print(f"{SENTINEL} PASS", flush=True)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _fail(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
