
import argparse
import hashlib
import json
import sys
import traceback
import uuid
from pathlib import Path

SENTINEL = "GATE_D_LEG"


def _fail(reason):
    print(SENTINEL + " FAIL " + str(reason), flush=True)
    sys.exit(0)  # sentinel, not exit code, is the source of truth


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def _diffuse_mat(bpy, name, color):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (color[0], color[1], color[2], 1.0)
    bsdf.inputs["Roughness"].default_value = 0.9
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return m


def _checker_mat(bpy, name, scale):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.9
    checker = nt.nodes.new("ShaderNodeTexChecker")
    checker.inputs["Scale"].default_value = scale
    checker.inputs["Color1"].default_value = (0.04, 0.04, 0.04, 1.0)
    checker.inputs["Color2"].default_value = (0.9, 0.9, 0.9, 1.0)
    nt.links.new(checker.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return m


def _build_scene(bpy):
    """Deterministic floor scene: flat (featureless) left half, checker right
    half, area light above/front, camera looking forward-and-down. The camera is
    centred on the split, so the left image half lands on the flat plane and the
    right half on the checker (declared top-down ROIs)."""
    import math
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(-5.0, 0.0, 0.0))
    flat = bpy.context.object
    flat.scale = (10.0, 20.0, 1.0)
    flat.data.materials.append(_diffuse_mat(bpy, "GateDFlat", (0.6, 0.6, 0.6)))

    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(5.0, 0.0, 0.0))
    chk = bpy.context.object
    chk.scale = (10.0, 20.0, 1.0)
    chk.data.materials.append(_checker_mat(bpy, "GateDChecker", 20.0))

    ld = bpy.data.lights.new("GateDLight", type="AREA")
    ld.energy = 600.0
    ld.size = 0.5
    light = bpy.data.objects.new("GateDLight", ld)
    light.location = (1.0, -2.0, 4.0)
    light.rotation_euler = (0.0, 0.0, 0.0)
    scene.collection.objects.link(light)

    cam_data = bpy.data.cameras.new("GateDCam")
    cam = bpy.data.objects.new("GateDCam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, -6.0, 1.5)
    cam.rotation_euler = (math.radians(78.0), 0.0, 0.0)
    scene.camera = cam

    world = bpy.data.worlds.new("GateDWorld")
    world.use_nodes = False
    world.color = (0.0, 0.0, 0.0)
    scene.world = world

    scene.render.resolution_x = 128
    scene.render.resolution_y = 128
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.exr_codec = "NONE"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    return scene


def _scene_manifest(scene):
    cam = scene.camera
    light = next((o for o in scene.objects if o.type == "LIGHT"), None)
    return {
        "resolution": [int(scene.render.resolution_x), int(scene.render.resolution_y)],
        "camera_location": [float(v) for v in cam.location],
        "camera_rotation_euler": [float(v) for v in cam.rotation_euler],
        "light_location": [float(v) for v in light.location] if light else None,
        "light_energy": float(light.data.energy) if light else None,
        "light_size": float(getattr(light.data, "size", 0.0)) if light else None,
        "view_transform": str(scene.view_settings.view_transform),
        "exposure": float(scene.view_settings.exposure),
        "gamma": float(scene.view_settings.gamma),
        "film_transparent": bool(scene.render.film_transparent),
    }


def _render_leg(bpy, scene, out_dir, stem, engine_cls):
    """Render one leg through the real F12 path and return the top-down linear
    HxWx3 array (or None + error)."""
    import numpy as np
    path = out_dir / (stem + ".exr")
    path.unlink(missing_ok=True)
    capture = {"end_result_calls": 0, "write_pixels_calls": 0,
               "trace_observed": False, "result_seen": False,
               "passes": [], "telemetry": [], "valid": False,
               "reason": None, "sample_count": None}
    orig_write = engine_cls.write_pixels

    def capture_write(self, pixels, width, height, alpha=None, renderer=None,
                      view_layer=None, scene=None, layer_name=None):
        capture["write_pixels_calls"] += 1
        if renderer is not None:
            try:
                capture["telemetry"].append(dict(renderer.last_render_info() or {}))
            except Exception as exc:  # noqa: BLE001
                capture["telemetry"].append({"last_render_info_error": repr(exc)})

        # ``end_result`` is Blender RNA and can bypass a temporary class
        # attribute.  Trace only this original pure-Python method instead: its
        # ``result`` local exists after ``begin_result`` and before it is passed
        # to native ``end_result``.  Never infer Sample Count from Combined.
        previous_trace = sys.gettrace()

        def inspect_result(result):
            capture["result_seen"] = True
            try:
                # Retain only the latest line snapshot.  The line event for
                # self.end_result(result) occurs before native release, after
                # write_pixels has filled every registered pass.
                capture["passes"] = []
                capture["sample_count"] = None
                for layer in result.layers:
                    for render_pass in layer.passes:
                        name = str(getattr(render_pass, "name", ""))
                        channels = int(getattr(render_pass, "channels", 0))
                        rect = np.asarray(render_pass.rect[:], dtype=np.float32)
                        capture["passes"].append({"layer": str(getattr(layer, "name", "")),
                                                   "name": name, "channels": channels,
                                                   "rect_len": int(rect.size)})
                        if name == "Debug Sample Count":
                            capture["sample_count"] = {"channels": channels,
                                                       "rect": rect.copy()}
            except Exception as exc:  # noqa: BLE001
                capture["reason"] = "trace result capture failed: %r" % (exc,)

        def trace(frame, event, _arg):
            if frame.f_code is orig_write.__code__ and event == "line":
                capture["trace_observed"] = True
                result = frame.f_locals.get("result")
                if result is not None:
                    inspect_result(result)
            return trace

        sys.settrace(trace)
        try:
            return orig_write(self, pixels, width, height, alpha=alpha, renderer=renderer,
                              view_layer=view_layer, scene=scene, layer_name=layer_name)
        finally:
            sys.settrace(previous_trace)

    engine_cls.write_pixels = capture_write
    try:
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
    finally:
        engine_cls.write_pixels = orig_write
    capture["valid"] = (capture["trace_observed"] and capture["result_seen"]
                        and capture["reason"] is None)
    if not capture["valid"]:
        capture["reason"] = capture["reason"] or "write_pixels trace did not expose result"
    if not path.is_file():
        return None, None, "no EXR produced for stem %s" % stem, capture
    img = bpy.data.images.load(str(path))
    try:
        w, h = int(img.size[0]), int(img.size[1])
        if w <= 0 or h <= 0:
            return None, path, "rendered image has empty size"
        px = np.asarray(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
        arr = np.ascontiguousarray(px[::-1, :, :3])  # bottom-up -> top-down, once
    finally:
        bpy.data.images.remove(img)
    return arr, path, None, capture


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", required=True)
    p.add_argument("--backend", required=True, choices=["cpu", "gpu"])
    p.add_argument("--repo-root", required=True)
    p.add_argument("--expected-build-id")
    p.add_argument("--expected-module-sha256")
    p.add_argument("--expected-addon-init-sha256")
    args = p.parse_args(argv)

    import numpy as np
    import bpy

    repo_root = Path(args.repo_root).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    scripts = repo_root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))

    addon_dir = __import__("os").environ.get("ASTRORAY_SMOKE_ADDON_DIR")
    if not addon_dir or not Path(addon_dir).is_dir():
        _fail("ASTRORAY_SMOKE_ADDON_DIR is unset or missing; refusing the "
              "dev-tree fallback (exact engine/build provenance required)")

    # Reuse the ONE canonical addon bootstrap (no duplicate registration path).
    import verify_pkg175_smoke_blender as smoke
    astroray, addon = smoke._bootstrap()

    if not hasattr(addon, "CustomRaytracerRenderEngine"):
        _fail("addon registered but CustomRaytracerRenderEngine is missing")

    engine_id = "CUSTOM_RAYTRACER"
    scene = _build_scene(bpy)
    try:
        scene.render.engine = engine_id
    except TypeError as exc:
        _fail("engine %r is not registered: %s" % (engine_id, exc))
    if str(scene.render.engine) != engine_id:
        _fail("engine did not stick (got %r, want %r) - refusing to render on a "
              "default/fallback engine" % (str(scene.render.engine), engine_id))

    if not hasattr(scene, "custom_raytracer"):
        _fail("scene.custom_raytracer missing - addon registration incomplete")
    if not hasattr(scene, "cycles"):
        _fail("scene.cycles missing - native Cycles panels are unavailable")

    build = {
        "engine_id": engine_id,
        "build_id": str(getattr(astroray, "__build__", "")),
        "version": str(getattr(astroray, "__version__", "")),
        "astroray_module": str(getattr(astroray, "__file__", "")),
        "addon_dir": str(Path(addon_dir).resolve()),
        "addon_init": str(getattr(addon, "__file__", "")),
        "blender_version": str(bpy.app.version_string),
        "blender_binary": str(bpy.app.binary_path),
    }
    build["module_sha256"] = _sha256(Path(build["astroray_module"])) \
        if Path(build["astroray_module"]).is_file() else None
    build["addon_init_sha256"] = _sha256(Path(build["addon_init"])) \
        if Path(build["addon_init"]).is_file() else None
    if not build["build_id"] or not build["module_sha256"] or not build["addon_init_sha256"]:
        _fail("missing build identity or hash; refusing unproven runtime provenance")
    expected = {"build_id": args.expected_build_id,
                "module_sha256": args.expected_module_sha256,
                "addon_init_sha256": args.expected_addon_init_sha256}
    supplied = {key: value for key, value in expected.items() if value}
    build["expected_identity"] = supplied or None
    build["provenance_claim"] = "candidate" if supplied else "baseline_diagnostic"
    for key, value in supplied.items():
        if build.get(key) != value:
            _fail("loaded %s does not match expected candidate identity" % key)

    # Backend selection uses the addon's SUPPORTED device selector only.
    try:
        scene.custom_raytracer.device_mode = args.backend
    except (TypeError, AttributeError) as exc:
        _fail("cannot set custom_raytracer.device_mode=%r: %s" % (args.backend, exc))

    probe = astroray.Renderer()
    gpu_available = bool(getattr(probe, "gpu_available", False))
    del probe
    build["gpu_available"] = gpu_available

    legs_meta = {}
    artifacts = {}

    if args.backend == "gpu" and not gpu_available:
        record = {
            "schema_version": 1,
            "instrument": "gate_native_panels",
            "backend": args.backend,
            "status": "unmeasured",
            "reason": "no CUDA GPU available for the gpu backend",
            "build": build,
            "scene": _scene_manifest(scene),
            "scene_sha256": hashlib.sha256(
                json.dumps(_scene_manifest(scene), sort_keys=True).encode("utf-8")).hexdigest(),
            "legs": {},
            "checks": {},
            "artifacts": {},
        }
        _write_json(out_dir / ("legs_" + args.backend + ".json"), record)
        print(SENTINEL + " PASS", flush=True)
        return

    specs = [
        ("adaptive_off", False, False, 64),
        ("adaptive_on", True, False, 64),
        ("denoise_off", False, False, 64),
        ("denoise_on", False, True, 64),
        ("reference", False, False, 512),
    ]

    run_id = uuid.uuid4().hex
    aov_captures = {}
    aov_arrays = {}
    for name, adaptive, denoise, samples in specs:
        # NATIVE PANEL ONLY: samples / adaptive / denoise come exclusively from
        # scene.cycles.*. The custom_raytracer duplicates are never written here.
        scene.cycles.samples = int(samples)
        scene.cycles.use_adaptive_sampling = bool(adaptive)
        scene.cycles.use_denoising = bool(denoise)
        view_layer = bpy.context.view_layer
        requested_sample_count_pass = False
        try:
            view_layer.cycles.pass_debug_sample_count = True
            requested_sample_count_pass = bool(view_layer.cycles.pass_debug_sample_count)
        except (AttributeError, TypeError):
            requested_sample_count_pass = False

        resolved = addon.resolve_native_settings(scene)
        arr, exr_path, err, capture = _render_leg(
            bpy, scene, out_dir, run_id + "_" + args.backend + "_" + name,
            addon.CustomRaytracerRenderEngine)
        if err:
            _fail("%s/%s: %s" % (args.backend, name, err))

        stem = args.backend + "_" + name
        npy_path = out_dir / (run_id + "_" + stem + ".npy")
        np.save(npy_path, arr)
        artifacts[str(npy_path.name)] = {
            "path": str(npy_path),
            "sha256": _sha256(npy_path),
            "kind": "linear_topdown_npy",
            "shape": [int(v) for v in arr.shape],
        }
        if exr_path is not None and Path(exr_path).exists():
            artifacts[Path(exr_path).name] = {
                "path": str(exr_path),
                "sha256": _sha256(exr_path),
                "kind": "linear_exr",
            }

        lum = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
        legs_meta[name] = {
            "backend": args.backend,
            "leg": name,
            "artifact": npy_path.name,
            "sha256": artifacts[npy_path.name]["sha256"],
            "shape": [int(v) for v in arr.shape],
            "finite": bool(np.isfinite(arr).all()),
            "mean_luminance": float(lum.mean()),
            "native": {
                "samples": int(scene.cycles.samples),
                "use_adaptive_sampling": bool(scene.cycles.use_adaptive_sampling),
                "use_denoising": bool(scene.cycles.use_denoising),
            },
            "resolved": {
                "samples": int(resolved.samples),
                "use_adaptive_sampling": bool(resolved.use_adaptive_sampling),
                "use_denoising": bool(resolved.use_denoising),
                "device_mode": str(resolved.device_mode),
            },
            "rendered": True,
            "error": None,
            "output_telemetry": capture["telemetry"],
            "requested_sample_count_pass": requested_sample_count_pass,
        }

        if name in ("adaptive_off", "adaptive_on"):
            aov_info = {k: v for k, v in capture.items() if k != "sample_count"}
            aov_info["requested"] = requested_sample_count_pass
            aov_info["pass_name"] = "Debug Sample Count"
            aov_info["units"] = "normalized_to_max_samples"
            aov_info["normalization_max_samples"] = int(scene.cycles.samples)
            sample = capture.get("sample_count")
            if sample is None:
                aov_info["present"] = False
                aov_info["reason"] = (aov_info.get("reason") if not capture["valid"]
                                      else "requested Debug Sample Count pass not registered")
            else:
                channels = int(sample["channels"] or 0)
                rect = np.asarray(sample["rect"], dtype=np.float32)
                expected = int(arr.shape[0]) * int(arr.shape[1]) * channels
                if channels <= 0 or rect.size != expected:
                    aov_info.update({"present": False, "valid": False,
                                     "reason": "sample-count pass rect shape invalid"})
                else:
                    aov_arr = rect.reshape(arr.shape[0], arr.shape[1], channels)[::-1].copy()
                    aov_info["present"] = True
                    aov_info["reason"] = None
            aov_captures[name] = aov_info
            if aov_info.get("present"):
                aov_path = out_dir / (run_id + "_" + args.backend + "_aov_" + name + ".npy")
                np.save(aov_path, aov_arr)
                artifacts[aov_path.name] = {
                    "path": str(aov_path),
                    "sha256": _sha256(aov_path),
                    "kind": "sample_count_aov",
                    "shape": [int(v) for v in aov_arr.shape],
                }
                aov_arrays[name] = {
                    "artifact": aov_path.name,
                    "sha256": artifacts[aov_path.name]["sha256"],
                }

    scene_manifest = _scene_manifest(scene)
    record = {
        "schema_version": 1,
        "instrument": "gate_native_panels",
        "backend": args.backend,
        "status": "measured",
        "build": build,
        "scene": scene_manifest,
        "scene_sha256": hashlib.sha256(
            json.dumps(scene_manifest, sort_keys=True).encode("utf-8")).hexdigest(),
        "legs": legs_meta,
        "run_id": run_id,
        "aov": {"captures": aov_captures, "artifacts": aov_arrays},
        "artifacts": artifacts,
    }
    _write_json(out_dir / ("legs_" + args.backend + ".json"), record)
    print(SENTINEL + " PASS", flush=True)


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:  # noqa: BLE001
        traceback.print_exc()
        _fail("%s: %s" % (type(exc).__name__, exc))
