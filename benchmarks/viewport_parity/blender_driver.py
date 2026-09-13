#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pkg81 — Cycles A/B driver (run inside Blender).

Companion to ``run.py``. Drives the *same* deterministic pan/zoom/orbit
camera path inside a real Blender process so we can fairly compare
Astroray vs Cycles. Unlike the in-process harness, this script needs
Blender's depsgraph and (for true viewport timings) a 3D View in
RENDERED shading mode.

Two modes:

  --mode offline  (works in --background)
      Single-frame F12 renders at preview-spp settings, one render call
      per camera position. Measures the "per-frame cost" each engine
      pays at viewport sample chunk size. Not the same as live
      view_draw, but the closest engine-to-engine A/B reachable in
      headless. Cycles' BlenderSession::render() vs ours.

  --mode interactive  (requires GUI Blender)
      Registers a modal operator that nudges the 3D View camera every
      timer tick, records ``time.perf_counter()`` deltas around
      view_draw via a draw-handler, and writes JSON on exit.
      Only meaningful when run from a Blender session with the 3D View
      already in rendered shading mode.

How to run
----------
::

    "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" ^
        --background ^
        scenes/cornell_99k.blend ^
        --python benchmarks/viewport_parity/blender_driver.py ^
        -- --engine CYCLES --mode offline --out benchmarks/viewport_parity

The ``--`` separator is Blender convention: anything after it is passed
to this script.

Reference (read-only): intern/cycles/blender/session.cpp, view_draw /
view_update sample-loop shape — Apache-2.0. We do not copy code; the
camera-path generator below mirrors run.py's (pkg81 in-process harness)
1:1 so the comparison is apples-to-apples.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

try:
    import bpy  # type: ignore
except ImportError:
    # --mode offline runs INSIDE Blender (blender --python) and needs bpy.
    # --mode interactive (pkg241) runs OUTSIDE Blender as a plain-Python client
    # that drives a live GUI Blender over the mcp socket bridge; it never
    # touches bpy locally, so a missing bpy is only fatal for offline mode.
    bpy = None  # type: ignore


def _camera_path(n_frames: int):
    """Same path as run.py._camera_path. Yields (look_from, look_at, vfov)."""
    n_pan = n_frames // 3
    n_zoom = n_frames // 3
    n_orbit = n_frames - n_pan - n_zoom
    cx, cy, cz = 5.0, 5.0, 5.0
    for i in range(n_pan):
        t = i / max(1, n_pan - 1)
        yield ([cx + 2.0 * t, cy, cz], [0, 0, 0], 40.0)
    for i in range(n_zoom):
        t = i / max(1, n_zoom - 1)
        vfov = 40.0 - 15.0 * t
        yield ([cx, cy, cz], [0, 0, 0], vfov)
    for i in range(n_orbit):
        t = i / max(1, n_orbit - 1)
        a = 0.5 * t
        x = cx * math.cos(a) - cz * math.sin(a)
        z = cx * math.sin(a) + cz * math.cos(a)
        yield ([x, cy, z], [0, 0, 0], 40.0)


def _percentile(samples_ms, p):
    if not samples_ms:
        return float("nan")
    s = sorted(samples_ms)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def _frame_summary(samples_ms):
    if not samples_ms:
        return {"n": 0, "mean_ms": 0.0, "p50_ms": 0.0, "p99_ms": 0.0,
                "max_ms": 0.0, "first_ms": 0.0}
    return {
        "n": len(samples_ms),
        "mean_ms": statistics.mean(samples_ms),
        "p50_ms": _percentile(samples_ms, 50),
        "p99_ms": _percentile(samples_ms, 99),
        "max_ms": max(samples_ms),
        "first_ms": samples_ms[0],
    }


def _get_or_make_camera(scene):
    cam = scene.camera
    if cam is None:
        bpy.ops.object.camera_add()
        cam = bpy.context.active_object
        scene.camera = cam
    return cam


def _set_camera_from_path(cam, look_from, look_at, vfov_deg):
    cam.location = look_from
    # Aim at look_at: simplest possible — we set rotation_euler from a
    # look-direction. Rough but deterministic and applies identically to
    # both engines so the A/B is fair.
    fx = look_at[0] - look_from[0]
    fy = look_at[1] - look_from[1]
    fz = look_at[2] - look_from[2]
    n = math.sqrt(fx * fx + fy * fy + fz * fz) or 1.0
    fx, fy, fz = fx / n, fy / n, fz / n
    yaw = math.atan2(fx, -fz)  # Blender camera looks along -Z
    pitch = -math.asin(fy)
    cam.rotation_euler = (math.pi / 2.0 + pitch, 0.0, yaw)
    # vfov → focal length: lens_mm = sensor / (2 tan(vfov/2)). Blender's
    # default vertical sensor is 18mm; horizontal 36mm. We treat vfov as
    # the vertical FOV.
    sensor_v = cam.data.sensor_height or 18.0
    cam.data.lens = sensor_v / (2.0 * math.tan(math.radians(vfov_deg) / 2.0))


def _make_grid_scene(target_tris: int):
    """Mirror run.py's _build_renderer geometry: a flat quad grid of
    ~target_tris triangles, 5 diffuse materials tiled (i+j)%5, sky-blue
    world. One mesh per material (fast from_pydata construction)."""
    # Clear default objects (cube/light keep the A/B unfair).
    for obj in list(bpy.data.objects):
        if obj.type in ("MESH", "LIGHT"):
            bpy.data.objects.remove(obj, do_unlink=True)

    palette_rgba = [
        (0.73, 0.73, 0.73, 1.0),
        (0.65, 0.05, 0.05, 1.0),
        (0.05, 0.65, 0.05, 1.0),
        (0.05, 0.05, 0.65, 1.0),
        (0.65, 0.65, 0.05, 1.0),
    ]
    mats = []
    for k, rgba in enumerate(palette_rgba):
        m = bpy.data.materials.new(f"pkg81_grid_{k}")
        m.use_nodes = True
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = rgba
            bsdf.inputs["Roughness"].default_value = 1.0
        mats.append(m)

    quads = max(1, int((target_tris / 2.0) ** 0.5))
    buckets = {k: ([], []) for k in range(len(mats))}  # verts, faces
    for i in range(quads):
        for j in range(quads):
            k = (i + j) % len(mats)
            verts, faces = buckets[k]
            x0, x1 = i * 0.1, (i + 1) * 0.1
            z0, z1 = j * 0.1, (j + 1) * 0.1
            base = len(verts)
            verts.extend([(x0, 0.0, z0), (x1, 0.0, z0),
                          (x1, 0.0, z1), (x0, 0.0, z1)])
            faces.append((base, base + 1, base + 2))
            faces.append((base, base + 2, base + 3))
    for k, (verts, faces) in buckets.items():
        mesh = bpy.data.meshes.new(f"pkg81_grid_mesh_{k}")
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(f"pkg81_grid_obj_{k}", mesh)
        obj.data.materials.append(mats[k])
        bpy.context.scene.collection.objects.link(obj)

    world = bpy.context.scene.world or bpy.data.worlds.new("pkg81_world")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs[0].default_value = (0.5, 0.7, 1.0, 1.0)
    return 2 * quads * quads


def _bootstrap_astroray_addon():
    """Register the repo addon in a headless Blender (the pkg108
    verification-script pattern: repo root on sys.path + register())."""
    repo_root = Path(__file__).resolve().parents[2]
    # Fresh-module guard (memory: stale_pyd_locations): Blender's Python can
    # find an installed/stale astroray; force THIS worktree's build first
    # and verify the import resolved to it.
    build_dir = repo_root / "build_cuda" / "Release"
    for entry in (str(build_dir), str(repo_root)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    # Python 3.13 on Windows resolves extension-module DLL deps only via
    # add_dll_directory, not PATH — the .pyd needs the CUDA runtime.
    cuda_bin = Path(os.environ.get(
        "CUDA_PATH", r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.8")) / "bin"
    for dll_dir in (build_dir, cuda_bin):
        if dll_dir.is_dir():
            os.add_dll_directory(str(dll_dir))
    import astroray  # noqa: E402
    print(f"[pkg81-driver] astroray module: {astroray.__file__}")
    import blender_addon  # noqa: E402
    try:
        blender_addon.register()
    except Exception as exc:  # already registered is fine
        if "already registered" not in str(exc):
            raise


def _enable_cycles_gpu():
    """Prefer OPTIX, fall back to CUDA, for a fair GPU-vs-GPU A/B."""
    prefs = bpy.context.preferences.addons.get("cycles")
    if prefs is None:
        return "cpu (cycles addon prefs unavailable)"
    cprefs = prefs.preferences
    for dev_type in ("OPTIX", "CUDA"):
        try:
            cprefs.compute_device_type = dev_type
        except TypeError:
            continue
        cprefs.get_devices()
        n = 0
        for d in cprefs.devices:
            use = d.type != "CPU"
            d.use = use
            n += int(use)
        if n:
            bpy.context.scene.cycles.device = "GPU"
            return f"{dev_type} x{n}"
    return "cpu (no GPU device type accepted)"


def run_offline(args) -> dict:
    scene = bpy.context.scene
    if args.make_scene:
        built = _make_grid_scene(args.make_scene)
        print(f"[pkg81-driver] built grid scene: {built} tris")
    if args.engine == "CUSTOM_RAYTRACER":
        _bootstrap_astroray_addon()
    scene.render.engine = args.engine
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    gpu_note = ""
    if args.engine == "CYCLES":
        scene.cycles.samples = args.chunk_spp
        scene.cycles.preview_samples = args.chunk_spp
        scene.cycles.use_denoising = bool(args.oidn)
        gpu_note = _enable_cycles_gpu()
        print(f"[pkg81-driver] cycles device: {gpu_note}")
    elif hasattr(scene, "custom_raytracer"):
        # pkg176 Stage 4: samples come from native Cycles props now (the exporter
        # reads them via resolve_native_settings); the custom preview_samples
        # alias was retired.
        scene.cycles.samples = args.chunk_spp
        scene.cycles.preview_samples = args.chunk_spp
        if hasattr(scene.custom_raytracer, "viewport_chunk_spp"):
            scene.custom_raytracer.viewport_chunk_spp = args.chunk_spp
        if hasattr(scene.custom_raytracer, "viewport_oidn"):
            scene.custom_raytracer.viewport_oidn = bool(args.oidn)
        if args.integrator and hasattr(scene.custom_raytracer, "integrator_type"):
            scene.custom_raytracer.integrator_type = args.integrator
            print(f"[pkg81-driver] astroray integrator: {args.integrator}")
        if hasattr(scene.custom_raytracer, "device_mode"):
            scene.custom_raytracer.device_mode = "gpu"

    cam = _get_or_make_camera(scene)
    samples_ms: list[float] = []
    for look_from, look_at, vfov in _camera_path(args.frames):
        _set_camera_from_path(cam, look_from, look_at, vfov)
        # Force depsgraph eval before timing the render call so we measure
        # render-only, matching what view_draw would charge.
        bpy.context.view_layer.update()
        t0 = time.perf_counter()
        bpy.ops.render.render(write_still=False)
        samples_ms.append((time.perf_counter() - t0) * 1000.0)

    return {
        "schema": "astroray.viewport_parity.cycles_compare.v1",
        "package": "pkg81",
        "phase": "1+2 (Cycles A/B, offline mode)",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc)
            .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "blender_version": bpy.app.version_string,
        "engine": args.engine,
        "config": {
            "frames": args.frames, "width": args.width, "height": args.height,
            "chunk_spp": args.chunk_spp, "oidn": bool(args.oidn),
            "blend_file": bpy.data.filepath,
            "make_scene_tris": args.make_scene,
            "integrator": args.integrator,
            "cycles_gpu": gpu_note,
        },
        "frame": _frame_summary(samples_ms),
        "raw_frame_ms": samples_ms,
        "notes": [
            "Offline mode = F12 render per camera position. Approximates",
            "per-frame view_draw cost; not a true viewport-interactivity",
            "measurement. Use --mode interactive in a GUI Blender for that.",
        ],
    }


# ---------------------------------------------------------------------------
# pkg241 Phase 0 — interactive latency recorder (client of the live GUI Blender)
#
# Runs OUTSIDE Blender as a plain-Python process. Drives the running GUI Blender
# 5.2 through the Blender Lab ``mcp`` socket bridge (localhost:9876): it sends
# ``blender_recorder.py`` (a bpy.app.timers + SpaceView3D draw-handler recorder)
# and ``blender_cancel_probe.py`` as ``execute`` requests, polls the recorder
# state, and aggregates real UI-event -> presented-frame latencies. The bridge
# wire protocol is: json.dumps({"type":"execute","code":..,"strict_json":..})+"\0".
# ---------------------------------------------------------------------------

import socket as _socket

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
_BIG_SCENE = _HERE / "scenes" / "pkg241_grid_100k.blend"
_METAL_SWEEP = _REPO / "blender_addon" / "scenes" / "metal_sweep.blend"
_ADDON = "bl_ext.user_default.astroray"


def _bridge(code: str, host: str, port: int, timeout: float = 120.0) -> dict:
    """One request/response against the mcp bridge. Raises on transport or
    Blender-side error so the driver fails loudly rather than banking noise."""
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((host, port))
    try:
        payload = {"type": "execute", "code": code, "strict_json": False}
        s.sendall((json.dumps(payload) + "\0").encode("utf-8"))
        buf = bytearray()
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf.extend(chunk)
            if buf.endswith(b"\0"):
                break
    finally:
        s.close()
    resp = json.loads(buf.rstrip(b"\0").decode("utf-8"))
    if resp.get("status") != "ok":
        raise RuntimeError("Blender bridge error:\n" + str(resp.get("message")))
    return resp.get("result", {})


def _recorder_src() -> str:
    return (_HERE / "blender_recorder.py").read_text(encoding="utf-8")


def _cancel_src() -> str:
    return (_HERE / "blender_cancel_probe.py").read_text(encoding="utf-8")


# --- in-Blender snippets (sent verbatim) -----------------------------------

_ENSURE_RENDERED = """
import bpy
sc = bpy.context.scene
sc.render.engine = 'CUSTOM_RAYTRACER'
area = None
for win in bpy.context.window_manager.windows:
    for a in win.screen.areas:
        if a.type == 'VIEW_3D':
            area = a
tri = sum(max(0, len(p.vertices) - 2) for o in bpy.data.objects
          if o.type == 'MESH' for p in o.data.polygons)
region = None
if area is not None:
    area.spaces.active.shading.type = 'RENDERED'
    area.tag_redraw()
    for r in area.regions:
        if r.type == 'WINDOW':
            region = [r.width, r.height]
result = {'engine': sc.render.engine, 'tris': tri, 'v3d': area is not None,
          'file': bpy.data.filepath, 'region': region,
          'preview_samples': int(getattr(sc.cycles, 'preview_samples', 0)),
          'nav_res_divisor': 2}
"""

_BUILD_BIG = r"""
import bpy, bmesh, math
# ~100k-tri procedural stress scene: one subdivision-6 icosphere (~82k tris)
# plus a subdivided ground grid (~20k tris), lit by a sun, seen by a camera.
# Built via bmesh + the data API (NOT operators) because read_homefile leaves a
# restricted context where bpy.context.active_object is unavailable.
bpy.ops.wm.read_homefile(use_empty=True)
scene = bpy.context.scene
coll = scene.collection
mats = []
for k, rgba in enumerate([(0.8,0.3,0.2,1), (0.2,0.5,0.8,1), (0.7,0.7,0.2,1)]):
    m = bpy.data.materials.new('pkg241_' + str(k))
    m.use_nodes = True
    b = m.node_tree.nodes.get('Principled BSDF')
    if b is not None:
        b.inputs['Base Color'].default_value = rgba
        b.inputs['Metallic'].default_value = 0.6 if k == 0 else 0.0
        b.inputs['Roughness'].default_value = 0.3
    mats.append(m)

def _mesh_obj(name, build_fn, mat, smooth=False, location=(0,0,0)):
    bm = bmesh.new()
    build_fn(bm)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    ob.location = location
    coll.objects.link(ob)
    return ob

_mesh_obj('pkg241_ico', lambda bm: bmesh.ops.create_icosphere(
    bm, subdivisions=7, radius=2.0), mats[0], smooth=True, location=(0, 0, 2))
_mesh_obj('pkg241_grid', lambda bm: bmesh.ops.create_grid(
    bm, x_segments=100, y_segments=100, size=20.0), mats[1])

light = bpy.data.lights.new('pkg241_sun', 'SUN')
light.energy = 4.0
lob = bpy.data.objects.new('pkg241_sun', light)
lob.location = (4, 4, 10)
coll.objects.link(lob)

camd = bpy.data.cameras.new('pkg241_cam')
cam = bpy.data.objects.new('pkg241_cam', camd)
cam.location = (9, -9, 7)
cam.rotation_euler = (math.radians(60), 0.0, math.radians(45))
coll.objects.link(cam)
scene.camera = cam
w = bpy.context.scene.world or bpy.data.worlds.new('pkg241_world')
bpy.context.scene.world = w
w.use_nodes = True
bg = w.node_tree.nodes.get('Background')
if bg is not None:
    bg.inputs[0].default_value = (0.5, 0.7, 1.0, 1.0)
sc = bpy.context.scene
sc.render.engine = 'CUSTOM_RAYTRACER'
sc.render.resolution_x = 480
sc.render.resolution_y = 270
sc.render.resolution_percentage = 100
bpy.ops.wm.save_as_mainfile(filepath=__BIG_PATH__)
tri = sum(max(0, len(p.vertices) - 2) for o in bpy.data.objects
          if o.type == 'MESH' for p in o.data.polygons)
result = {'tris': tri, 'saved': __BIG_PATH__}
"""

_DEVICE_SWITCH = r"""
import bpy
sc = bpy.context.scene
sc.custom_raytracer.device_mode = __MODE__
# Force the viewport engine (+exporter) to rebuild on the new device by cycling
# the 3D view out of and back into RENDERED shading: Blender frees the
# RenderEngine on leaving rendered shading and recreates it on return, so the
# next sync reconfigures the backend (configure_backend_for_context).
area = None
for win in bpy.context.window_manager.windows:
    for a in win.screen.areas:
        if a.type == 'VIEW_3D':
            area = a
sp = area.spaces.active
sp.shading.type = 'SOLID'
area.tag_redraw()
def _back():
    sp.shading.type = 'RENDERED'
    area.tag_redraw()
    return None
bpy.app.timers.register(_back, first_interval=0.3)
result = {'device_mode': sc.custom_raytracer.device_mode}
"""

_ENGINE_SWITCH = r"""
import bpy
sc = bpy.context.scene
target = __ENGINE__
sc.render.engine = target
if target == 'CYCLES':
    gpu_note = 'cpu (cycles addon prefs unavailable)'
    prefs = bpy.context.preferences.addons.get('cycles')
    if prefs is not None:
        cprefs = prefs.preferences
        for dev_type in ('OPTIX', 'CUDA'):
            try:
                cprefs.compute_device_type = dev_type
            except TypeError:
                continue
            cprefs.get_devices()
            n = 0
            for d in cprefs.devices:
                use = d.type != 'CPU'
                d.use = use
                n += int(use)
            if n:
                sc.cycles.device = 'GPU'
                gpu_note = dev_type + ' x' + str(n)
                break
    sc.cycles.samples = 1024
    sc.cycles.preview_samples = 1024
    sc.cycles.use_denoising = False
else:
    if hasattr(sc, 'custom_raytracer'):
        sc.custom_raytracer.device_mode = 'gpu'
    gpu_note = 'astroray-gpu'
# Cycle the 3D view out of and back into RENDERED shading so the active
# RenderEngine is freed and recreated against the new engine/device (same
# trick as _DEVICE_SWITCH below).
area = None
for win in bpy.context.window_manager.windows:
    for a in win.screen.areas:
        if a.type == 'VIEW_3D':
            area = a
sp = area.spaces.active
sp.shading.type = 'SOLID'
area.tag_redraw()
def _back():
    sp.shading.type = 'RENDERED'
    area.tag_redraw()
    return None
bpy.app.timers.register(_back, first_interval=0.3)
region = None
for r in area.regions:
    if r.type == 'WINDOW':
        region = [r.width, r.height]
result = {'engine': sc.render.engine, 'gpu': gpu_note, 'region': region}
"""

_STATUS = ("import bpy; result = "
           "bpy.app.driver_namespace['_pkg241']['status']()")
_RESULTS = ("import bpy; result = "
            "bpy.app.driver_namespace['_pkg241']['results']()")
_STOP = ("import bpy; _S = bpy.app.driver_namespace.get('_pkg241');\n"
         "_S and _S.__setitem__('done', True);\n"
         "_S and _S.get('teardown') and _S['teardown']();\n"
         "result = {'stopped': bool(_S)}")
_TEARDOWN = ("import bpy; _S = bpy.app.driver_namespace.get('_pkg241');\n"
             "_S and _S.get('teardown') and _S['teardown']();\n"
             "result = {'torn_down': bool(_S)}")
_GPU_NAME = r"""
import astroray
r = astroray.Renderer()
try:
    r.set_use_gpu(True)
    name = r.gpu_device_name
except Exception as exc:
    name = 'unknown (' + str(exc) + ')'
result = {'gpu': str(name)}
"""


def _open_scene(host, port, which):
    """Open (or build) a pinned scene and return its info dict."""
    def _open(path):
        return ("import bpy; bpy.ops.wm.open_mainfile(filepath="
                + json.dumps(str(path)) + "); result = {'ok': True}")

    if which == "big":
        if not _BIG_SCENE.exists():
            _BIG_SCENE.parent.mkdir(parents=True, exist_ok=True)
            build = _BUILD_BIG.replace("__BIG_PATH__", json.dumps(str(_BIG_SCENE)))
            info = _bridge(build, host, port, timeout=180.0)
            print(f"[pkg241] built big scene: {info['tris']} tris")
        else:
            _bridge(_open(_BIG_SCENE), host, port)
    else:
        _bridge(_open(_METAL_SWEEP), host, port)
    return _bridge(_ENSURE_RENDERED, host, port)


def _switch_device(host, port, mode):
    _bridge(_DEVICE_SWITCH.replace("__MODE__", json.dumps(mode)), host, port)
    time.sleep(3.0)  # let the shading toggle rebuild + do a fresh sync frame


def _switch_engine(host, port, engine):
    """engine: 'CUSTOM_RAYTRACER' (Astroray, GPU) or 'CYCLES' (GPU)."""
    info = _bridge(_ENGINE_SWITCH.replace("__ENGINE__", json.dumps(engine)),
                    host, port)
    time.sleep(3.0)  # let the shading toggle rebuild + do a fresh sync frame
    return info


def _run_class(host, port, event_class, n, reps, warmup, deadline_s,
               rotate_deg=1.0):
    """Install the recorder for one event class, poll to completion (or the
    per-config wall-clock deadline), fetch and return non-warmup events."""
    cfg = {"event_class": event_class, "n": n, "reps": reps, "warmup": warmup,
           "rotate_deg": rotate_deg}
    setup = "_PKG241_CONFIG = " + json.dumps(cfg) + "\n" + _recorder_src()
    info = _bridge(setup, host, port)
    if info.get("setup") != "ok":
        raise RuntimeError(f"recorder setup failed: {info}")
    t_start = time.time()
    truncated = False
    while True:
        time.sleep(1.0)
        st = _bridge(_STATUS, host, port)
        if st.get("error"):
            raise RuntimeError("recorder error:\n" + st["error"])
        if st.get("done"):
            break
        if time.time() - t_start > deadline_s:
            _bridge(_STOP, host, port)
            truncated = True
            break
    res = _bridge(_RESULTS, host, port)
    _bridge(_TEARDOWN, host, port)
    events = [e for e in res.get("events", []) if not e.get("warmup")]
    return {"events": events, "truncated": truncated,
            "material": res.get("material")}


def _run_cancel(host, port, samples):
    src = "_PKG241_CANCEL = " + json.dumps({"samples": samples}) + "\n" + _cancel_src()
    return _bridge(src, host, port, timeout=600.0)


def _run_ui_latency(host, port, duration_s, warmup_s, tick_s,
                    pattern="continuous", burst_s=0.4, settle_s=2.0, _retries=1):
    """pkg241 Phase 2: install the fine-ticker recorder, poll to completion,
    fetch the raw tick/render/present streams for one (scene, engine) rep.

    One retry on a lost driver_namespace['_pkg241'] key (observed rarely,
    root cause not isolated -- possibly an interaction between the rapid
    alternating camera/material edits and Blender's undo-step bookkeeping;
    harmless to retry since the whole recorder state is freshly reinstalled
    by the setup call below and no partial results are banked on failure)."""
    cfg = {"event_class": "ui_latency", "duration_s": duration_s,
           "warmup_s": warmup_s, "tick_s": tick_s,
           "pattern": pattern, "burst_s": burst_s, "settle_s": settle_s}
    setup = "_PKG241_CONFIG = " + json.dumps(cfg) + "\n" + _recorder_src()
    info = _bridge(setup, host, port)
    if info.get("setup") != "ok":
        raise RuntimeError(f"ui_latency recorder setup failed: {info}")
    deadline_s = warmup_s + duration_s + 30.0
    t_start = time.time()
    truncated = False
    try:
        while True:
            time.sleep(0.5)
            st = _bridge(_STATUS, host, port)
            if st.get("error"):
                raise RuntimeError("ui_latency recorder error:\n" + st["error"])
            if st.get("done"):
                break
            if time.time() - t_start > deadline_s:
                _bridge(_STOP, host, port)
                truncated = True
                break
    except RuntimeError as exc:
        if _retries > 0 and "_pkg241" in str(exc):
            print(f"[pkg241-p2]     recorder state lost mid-rep "
                  f"({exc}); retrying once")
            return _run_ui_latency(host, port, duration_s, warmup_s, tick_s,
                                    pattern=pattern, burst_s=burst_s,
                                    settle_s=settle_s, _retries=_retries - 1)
        raise
    res = _bridge(_RESULTS, host, port)
    _bridge(_TEARDOWN, host, port)
    res["truncated"] = truncated
    return res


def _reduce_spike_events(events):
    """pkg241 Phase 2 A2 spike (§9): reduce the generation-tagged lifeline events
    to the pinned statistics. `events` is a list of
    (name, generation, t_perf_counter, epoch, extra), from the off-thread worker
    (ASTRORAY_VIEWPORT_WORKER=1). Returns None if no events (synchronous path)."""
    if not events:
        return None
    ev = sorted(events, key=lambda e: e[2])

    # request generation timeline (for supersession) + per-name index by gen.
    request_ts = sorted((g, t) for (n, g, t, _e, _x) in ev if n == "request")
    by_gen = {}
    for (n, g, t, _e, x) in ev:
        by_gen.setdefault(g, {}).setdefault(n, []).append((t, x))

    def _first(g, name):
        lst = by_gen.get(g, {}).get(name)
        return lst[0][0] if lst else None

    # per-PUBLICATION enqueue/blit index (pkg241 P2.2 item 3, Terra review 4).
    # Progressive frame age is measured per publication (mailbox_enqueue(pub) ->
    # first_blit(pub)), which is necessarily >= 0. The spike's old definition
    # (render_end -> first_blit) went NEGATIVE because the worker publishes
    # progressive chunks BEFORE the terminal render_end, so it never established a
    # rendering failure — it was a metric-definition bug.
    enqueue_t, blit_t = {}, {}
    for (n, g, t, _e, x) in ev:
        if n == "mailbox_enqueue" and "pub_id" in x:
            enqueue_t.setdefault(x["pub_id"], t)
        elif n == "first_blit" and "pub_id" in x:
            blit_t.setdefault(x["pub_id"], t)
    frame_age_ms = []
    for pub, tb in blit_t.items():
        te = enqueue_t.get(pub)
        if te is not None:
            frame_age_ms.append(max(0.0, (tb - te) * 1000.0))

    request_to_blit_ms = []
    commit_ms = []  # pkg241 P2.2 item 2: per-generation main-thread commit cost
    for g in by_gen:
        r_req = _first(g, "request")
        f_blit = _first(g, "first_blit")
        c_start = _first(g, "commit_start")
        c_end = _first(g, "commit_end")
        if c_start is not None and c_end is not None:
            commit_ms.append((c_end - c_start) * 1000.0)
        if f_blit is not None and r_req is not None:
            request_to_blit_ms.append((f_blit - r_req) * 1000.0)

    # terminal completion + present rate (pkg241 P2.2 item 3, Terra review 4).
    # A terminal_publication(g, pub_id) is emitted by the worker ONLY when a render
    # reached its target spp without cancellation, so its existence already encodes
    # "reached its marked final publication without cancellation". A terminal gen is
    # ELIGIBLE (present-rate denominator) when it remained current until its final
    # publication blitted (a blitted terminal frame was current at blit — the drain
    # discards superseded frames) or was never superseded through run end; a terminal
    # gen deliberately superseded before its terminal frame blitted is excluded.
    # Settle mode is UNGRADEABLE when no eligible terminal generation exists.
    max_request_gen = max((g for (g, _t) in request_ts), default=0)
    terminal = {}  # gen -> terminal pub_id
    for (n, g, _t, _e, x) in ev:
        if n == "terminal_publication" and "pub_id" in x:
            terminal[g] = x["pub_id"]
    completed = superseded = presented_completed = 0
    for g, pub in terminal.items():
        if pub in blit_t:
            completed += 1
            presented_completed += 1
        elif g >= max_request_gen:
            completed += 1          # never superseded, but its final frame missed
        else:
            superseded += 1         # deliberately superseded before blit — excluded

    # cancel-ack (pkg241 P2.2 item 3/4, Terra review 4): each cancel_request(g) is
    # now tagged with the actual IN-FLIGHT generation and emitted only on the
    # false->true transition (exporter.py request()). Pair it ONLY with the
    # idle_ack(g)/idle_drain(g) of the SAME generation — the old code paired each
    # cancel with any next idle by timestamp, which let a cancel pair with an
    # unrelated generation's idle and made the p99 invalid.
    #  - worker-side diagnostic (cancel_request(g) -> idle_ack(g)): how fast the
    #    worker stops its in-flight chunk and enqueues idle.
    #  - the usable gate (cancel_request(in-flight g) -> idle_drain(g)): adds the
    #    time the idle notification waits on the busy main thread before the pump
    #    consumes it. This is the number the p99 <= 300 ms gate is graded against.
    cancel_reqs = [(g, t) for (n, g, t, _e, _x) in ev if n == "cancel_request"]
    idle_ack_by_gen, idle_drain_by_gen = {}, {}
    for (n, g, t, _e, _x) in ev:
        if n == "idle_ack":
            idle_ack_by_gen.setdefault(g, []).append(t)
        elif n == "idle_drain":
            idle_drain_by_gen.setdefault(g, []).append(t)
    for g in idle_ack_by_gen:
        idle_ack_by_gen[g].sort()
    for g in idle_drain_by_gen:
        idle_drain_by_gen[g].sort()
    cancel_ack_ms, cancel_ack_pump_ms = [], []
    for (g, tc) in cancel_reqs:
        ack = next((ti for ti in idle_ack_by_gen.get(g, []) if ti >= tc), None)
        if ack is not None:
            cancel_ack_ms.append((ack - tc) * 1000.0)
        drn = next((ti for ti in idle_drain_by_gen.get(g, []) if ti >= tc), None)
        if drn is not None:
            cancel_ack_pump_ms.append((drn - tc) * 1000.0)

    # texture-upload tail: mailbox_dequeue -> the next texture_upload_end (ms).
    tex_tail_ms = []
    pending_dq = None
    for (n, _g, t, _e, _x) in ev:
        if n == "mailbox_dequeue":
            pending_dq = t
        elif n == "texture_upload_end" and pending_dq is not None:
            tex_tail_ms.append((t - pending_dq) * 1000.0)
            pending_dq = None

    # mailbox depth (never > 1) from enqueue depth_after / dequeue depth_before.
    depths = []
    for (n, _g, _t, _e, x) in ev:
        if n == "mailbox_enqueue" and "depth_after" in x:
            depths.append(int(x["depth_after"]))
        elif n == "mailbox_dequeue" and "depth_before" in x:
            depths.append(int(x["depth_before"]))
    mailbox_depth_max = max(depths) if depths else 0

    # per-generation device + CUDA error capture.
    devices = sorted({int(x["device"]) for (n, _g, _t, _e, x) in ev
                      if n == "render_device" and "device" in x})
    n_render_device = sum(1 for (n, *_r) in ev if n == "render_device")
    n_errors = sum(1 for (n, *_r) in ev if n == "error")

    # pkg266 (§13 item 1): cancellation-bounded dispatch accounting. Each
    # `bounded_units` event carries the native last_render_info units_launched /
    # cancelled_at_unit for one chunk. Report the units-launched distribution and
    # the cancelled-at-unit values (a cancel bounded to an early unit is the whole
    # point — a low cancelled_at_unit means the in-flight chunk stopped promptly).
    units_launched = [int(x["units_launched"]) for (n, _g, _t, _e, x) in ev
                      if n == "bounded_units" and "units_launched" in x]
    cancelled_at_unit = [int(x["cancelled_at_unit"]) for (n, _g, _t, _e, x) in ev
                         if n == "bounded_units"
                         and int(x.get("cancelled_at_unit", -1)) >= 0]

    def _pct(xs):
        if not xs:
            return None
        s = sorted(xs)
        return {"n": len(s), "p50_ms": round(_percentile(s, 50), 2),
                "p95_ms": round(_percentile(s, 95), 2),
                "p99_ms": round(_percentile(s, 99), 2),
                "max_ms": round(max(s), 2)}

    # pkg266 (Batch G): MEASURED chunk spp + samples/s. Every texture_upload_end
    # carries the accumulated spp of the PRESENTED chunk. Within a generation the
    # progressive spp is monotonic, so that generation's largest presented spp is
    # the samples it actually put on screen; summed across generations / the run
    # wall gives a measured samples/s (no inference from a fixed chunk size).
    presented_spp = [(g, int(x["spp"])) for (n, g, _t, _e, x) in ev
                     if n == "texture_upload_end" and "spp" in x]
    max_spp_by_gen = {}
    for g, spp in presented_spp:
        if spp > max_spp_by_gen.get(g, 0):
            max_spp_by_gen[g] = spp
    total_presented_spp = sum(max_spp_by_gen.values())
    wall_s = (ev[-1][2] - ev[0][2]) if len(ev) >= 2 else 0.0
    samples_per_s = (round(total_presented_spp / wall_s, 2)
                     if wall_s > 0 else None)
    chunk_spp_vals = sorted(spp for _g, spp in presented_spp)
    chunk_spp = ({"n": len(chunk_spp_vals),
                  "min": chunk_spp_vals[0], "max": chunk_spp_vals[-1],
                  "p50": int(_percentile(chunk_spp_vals, 50)),
                  "mean": round(sum(chunk_spp_vals) / len(chunk_spp_vals), 2)}
                 if chunk_spp_vals else None)

    # present-rate is UNGRADEABLE when no eligible terminal generation exists
    # (e.g. the continuous edit storm never lets a render reach its terminal
    # publication while still desired). Report the flag rather than a fake 0.
    present_rate_gradeable = completed > 0
    present_rate = (presented_completed / completed) if completed else None
    return {
        "n_events": len(ev),
        "request_to_first_blit": _pct(request_to_blit_ms),
        "frame_age": _pct(frame_age_ms),
        "commit_cost": _pct(commit_ms),
        "cancel_ack": _pct(cancel_ack_ms),
        "cancel_ack_pump": _pct(cancel_ack_pump_ms),
        "texture_upload_tail": _pct(tex_tail_ms),
        "mailbox_depth_max": mailbox_depth_max,
        "completed_generations": completed,
        "superseded_generations": superseded,
        "presented_completed": presented_completed,
        "present_rate": round(present_rate, 4) if present_rate is not None else None,
        "present_rate_gradeable": present_rate_gradeable,
        "devices_seen": devices,
        "n_render_device": n_render_device,
        "cuda_errors": n_errors,
        # pkg266 (Batch G): measured chunk spp + samples/s from presented chunks.
        "chunk_spp": chunk_spp,
        "samples_per_s": samples_per_s,
        "total_presented_spp": total_presented_spp,
        # pkg266 bounded dispatch (§13 item 1)
        "units_launched": _pct([float(u) for u in units_launched]) if units_launched else None,
        "cancelled_at_unit_n": len(cancelled_at_unit),
        "cancelled_at_unit_max": max(cancelled_at_unit) if cancelled_at_unit else None,
        "cancelled_at_unit_p95": (round(_percentile(sorted(cancelled_at_unit), 95), 2)
                                  if cancelled_at_unit else None),
    }


def _summarize_ui_latency(res):
    """Reduce one rep's raw tick/render/present streams to the reported
    statistics: tick-gap percentiles (the UI-latency proxy, works for any
    engine) and, when Astroray hooks fired, the render-time-fraction
    cross-check (works only when Astroray is the active engine)."""
    ticks = res.get("ticks") or []
    gaps_ms = [(ticks[i] - ticks[i - 1]) * 1000.0 for i in range(1, len(ticks))]
    renders = res.get("renders") or []
    presents = res.get("presents") or []
    tick_s = (res.get("cfg") or {}).get("tick_s", 0.005)
    nominal_ms = tick_s * 1000.0
    total_wall_ms = (ticks[-1] - ticks[0]) * 1000.0 if len(ticks) >= 2 else 0.0
    render_ms_total = sum((e - s) for s, e in renders) * 1000.0
    blocked_excess_ms = sum(max(0.0, g - nominal_ms) for g in gaps_ms)
    return {
        "gaps_ms": gaps_ms,
        "n_ticks": len(ticks),
        "n_renders": len(renders),
        "n_presents": len(presents),
        "render_ms_total": round(render_ms_total, 1),
        "total_wall_ms": round(total_wall_ms, 1),
        "blocked_excess_ms": round(blocked_excess_ms, 1),
        "truncated": bool(res.get("truncated")),
        "engine_has_hooks": res.get("engine_has_hooks"),
        # pkg241 Phase 2 A2 spike (§9): raw generation-tagged events for this rep,
        # concatenated + reduced across reps in run_ui_latency.
        "events": res.get("events") or [],
    }


def _agg(events, field):
    xs = sorted(e[field] for e in events if e.get(field) is not None)
    if not xs:
        return None
    return {
        "n": len(xs),
        "mean_ms": round(statistics.mean(xs), 2),
        "p50_ms": round(_percentile(xs, 50), 2),
        "p95_ms": round(_percentile(xs, 95), 2),
        "p99_ms": round(_percentile(xs, 99), 2),
        "max_ms": round(max(xs), 2),
    }


# Budgets pinned by the lead/Terra (pkg241 spec Evidence + Acceptance).
_BUDGETS = {
    "gpu_present_p95_ms": 100.0,
    "gpu_present_p99_ms": 150.0,
    "cancel_ack_p95_ms": 200.0,
    "cancel_ack_p99_ms": 300.0,
    # pkg241 Phase 2 (owner, 2026-09-07 evening): UI holds 30 fps while a
    # viewport chunk renders.
    "ui_latency_p95_ms": 33.0,
}


def run_interactive(args) -> dict:
    host, port = args.host, args.port
    scenes = args.scenes
    devices = args.devices
    classes = args.classes
    gpu_name = ""
    try:
        gpu_name = _bridge(_GPU_NAME, host, port).get("gpu", "")
    except Exception as exc:  # non-fatal
        gpu_name = f"probe failed ({exc})"

    configs = []
    for scene in scenes:
        sinfo = _open_scene(host, port, scene)
        print(f"[pkg241] scene={scene} tris={sinfo.get('tris')} "
              f"file={sinfo.get('file')}")
        for device in devices:
            _switch_device(host, port, device)
            # CPU renders can be 10-20x slower; a hard per-class deadline keeps
            # the matrix tractable while still banking >= the accepted floor.
            deadline = args.cpu_deadline_s if device == "cpu" else args.gpu_deadline_s
            n_ev = args.cpu_events if device == "cpu" else args.events
            n_rep = args.cpu_reps if device == "cpu" else args.reps
            entry = {"scene": scene, "tris": sinfo.get("tris"),
                     "region": sinfo.get("region"),
                     "preview_samples": sinfo.get("preview_samples"),
                     "device": device, "classes": {}}
            for cls in classes:
                print(f"[pkg241]   {device}/{cls} ...", flush=True)
                r = _run_class(host, port, cls, n_ev, n_rep,
                               args.warmup, deadline, args.rotate_deg)
                ev = r["events"]
                # pkg241 Phase 1: integer distributions for the stale-frame /
                # double-render guard (renders_before_present) and the engaged
                # interactive-resolution divisor (start_divisor).
                def _dist(field):
                    d = {}
                    for e in ev:
                        v = e.get(field)
                        if v is not None:
                            d[str(v)] = d.get(str(v), 0) + 1
                    return d
                entry["classes"][cls] = {
                    "n_events": len(ev),
                    "truncated": r["truncated"],
                    "material": r.get("material"),
                    "present": _agg(ev, "present_ms"),
                    "entry": _agg(ev, "entry_ms"),
                    "render": _agg(ev, "render_ms"),
                    "block": _agg(ev, "block_ms"),
                    "renders_before_present": _dist("renders_before_present"),
                    "start_divisor": _dist("start_divisor"),
                    "raw_present_ms": [round(e["present_ms"], 2)
                                       for e in ev if e.get("present_ms")],
                }
                p = entry["classes"][cls]["present"]
                print(f"[pkg241]     present p50={p['p50_ms']} "
                      f"p95={p['p95_ms']} p99={p['p99_ms']} (n={p['n']})")
            if args.cancel:
                print(f"[pkg241]   {device}/cancel (F12 full-stop floor) ...",
                      flush=True)
                entry["cancel"] = _run_cancel(host, port, args.cancel_samples)
                print(f"[pkg241]     F12 render_ms="
                      f"{entry['cancel'].get('render_ms')}")
            configs.append(entry)

    return {
        "schema": "astroray.viewport_parity.pkg241_phase0.v1",
        "package": "pkg241",
        "phase": "0 (viewport + cancellation latency recorder)",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc)
            .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "host": f"{host}:{port}",
        "gpu": gpu_name,
        "budgets": _BUDGETS,
        "protocol": {
            "bridge": "Blender Lab mcp socket; execute requests over localhost",
            "recorder": "blender_recorder.py (bpy.app.timers state machine + "
                        "SpaceView3D POST_PIXEL draw handler; wraps "
                        "CustomRaytracerRenderEngine.view_update/view_draw and "
                        "Exporter.render_viewport_frame)",
            "dispatch_zero": "time.perf_counter() taken in the timer immediately "
                             "before the scene edit + tag_redraw (excludes "
                             "Blender input-event routing a socket harness "
                             "cannot exercise)",
            "present": "SpaceView3D POST_PIXEL draw-handler timestamp of the "
                       "first redraw at/after dispatch = edit->present",
            "camera_event": f"{args.rotate_deg} deg view_rotation nudge "
                            "(view_draw path)",
            "material_event": "Principled Base Color red-channel toggle "
                              "0.3<->0.7 (view_update depsgraph path)",
            "cancel": "F12 render wall-time = current cancel full-stop floor; "
                      "the return value of test_break is discarded natively "
                      "(blender_module.cpp:2220) so ESC cannot stop early",
            "warmup_discarded": args.warmup,
            "reps_x_events": f"{args.reps}x{args.events}",
        },
        "configs": configs,
    }


def _write_summary_md(doc, path):
    lines = ["# pkg241 Phase 0 — viewport / cancellation latency", "",
             f"Generated: {doc['generated_utc']}  ", f"GPU: {doc['gpu']}  ",
             f"Bridge: {doc['host']}  ",
             f"Protocol: {doc['protocol']['reps_x_events']} events/class, "
             f"{doc['protocol']['warmup_discarded']} warmup discarded, "
             f"dispatch->present via POST_PIXEL draw handler.", "",
             "Budgets (GPU): edit->present p95 <= 100 ms / p99 <= 150 ms; "
             "cancel-ack p95 <= 200 ms / p99 <= 300 ms.", "",
             "Latency scales with viewport pixel count (region x nav-divisor) "
             "and the chunk/target sample budget; the region and preview_samples "
             "per config are recorded so numbers are interpretable.", "",
             "## edit -> present (ms)", "",
             "| scene | tris | region | prev_spp | device | class | n | p50 | p95 | p99 | max | rbp | start_div | trunc |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in doc["configs"]:
        reg = "x".join(str(v) for v in (c.get("region") or []))
        for cls, d in c["classes"].items():
            p = d["present"] or {}
            rbp = d.get("renders_before_present") or {}
            sdv = d.get("start_divisor") or {}
            rbp_s = ",".join(f"{k}:{v}" for k, v in sorted(rbp.items())) or "-"
            sdv_s = ",".join(f"{k}:{v}" for k, v in sorted(sdv.items())) or "-"
            lines.append(
                f"| {c['scene']} | {c['tris']} | {reg} | "
                f"{c.get('preview_samples')} | {c['device']} | {cls} | "
                f"{d['n_events']} | {p.get('p50_ms')} | {p.get('p95_ms')} | "
                f"{p.get('p99_ms')} | {p.get('max_ms')} | {rbp_s} | {sdv_s} | "
                f"{'Y' if d['truncated'] else ''} |")
    lines += ["", "## cancel full-stop floor (F12 render wall-time, ms)", "",
              "| scene | device | samples | render_ms |",
              "|---|---|---|---|"]
    for c in doc["configs"]:
        cn = c.get("cancel")
        if cn:
            lines.append(f"| {c['scene']} | {c['device']} | "
                         f"{cn.get('samples')} | {cn.get('render_ms')} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# pkg241 Phase 2 — UI event latency while a viewport chunk renders.
#
# Owner observation (design doc "Phase 2 — decouple the UI"): with Astroray
# the Blender UI runs at the viewport render's frame rate; Cycles decouples
# them because its viewport session renders on its own thread and view_draw
# only blits. This is the measurement step that must land BEFORE any
# threading change (spec: "Sequence: Phase 1b -> Phase 2 measurement ->
# Phase 2 design review -> implementation").
# ---------------------------------------------------------------------------

_ENGINE_NAME = {"astroray": "CUSTOM_RAYTRACER", "cycles": "CYCLES"}


def _run_present_check(host, port, duration_s, warmup_s, tick_s):
    """pkg241 P2.2 item 1 bridge test (one scene): install the present-check
    recorder, poll to done, fetch the read-back evidence for a settled worker
    frame."""
    cfg = {"event_class": "present_check", "duration_s": duration_s,
           "warmup_s": warmup_s, "tick_s": tick_s}
    setup = "_PKG241_CONFIG = " + json.dumps(cfg) + "\n" + _recorder_src()
    info = _bridge(setup, host, port)
    if info.get("setup") != "ok":
        raise RuntimeError(f"present_check recorder setup failed: {info}")
    deadline_s = warmup_s + duration_s + 30.0
    t_start = time.time()
    while True:
        time.sleep(0.5)
        st = _bridge(_STATUS, host, port)
        if st.get("error"):
            raise RuntimeError("present_check recorder error:\n" + st["error"])
        if st.get("done"):
            break
        if time.time() - t_start > deadline_s:
            _bridge(_STOP, host, port)
            break
    res = _bridge(_RESULTS, host, port)
    _bridge(_TEARDOWN, host, port)
    return res


def run_present_check(args) -> dict:
    """pkg241 P2.2 item 1: verify a settled off-thread worker frame actually
    reaches the screen (the spike's presented=0 / grid), per scene, with pixel
    read-back through the isolated Blender. PASS requires, on every scene:
    Exporter._worker_present was called >= 1 time for the settled generation
    (present-wiring restored) with a presented-buffer std above a rendered-content
    floor (not a uniform clear)."""
    host, port = args.host, args.port
    # A near-uniform clear/grid buffer has std ~ 0; any rendered scene at these
    # settings has clear spatial variation. 1e-4 is well above float noise and
    # far below a real render's std.
    MIN_STD = 1e-4
    scenes = []
    all_pass = True
    # present_check is astroray-only (the worker path); ignore --ui-engines.
    for scene in args.scenes:
        sinfo = _open_scene(host, port, scene)
        einfo = _switch_engine(host, port, _ENGINE_NAME["astroray"])
        print(f"[pkg241-p2] present_check scene={scene} "
              f"tris={sinfo.get('tris')} region={einfo.get('region')}")
        res = _run_present_check(host, port, args.duration_s, args.warmup_s,
                                 args.tick_s)
        std = res.get("max_present_std")
        n_calls = res.get("n_present_calls", 0)
        fb_std = res.get("fb_std_max")
        passed = (bool(res.get("engine_has_hooks")) and n_calls >= 1
                  and std is not None and std > MIN_STD)
        all_pass = all_pass and passed
        print(f"[pkg241-p2]   n_present_calls={n_calls} max_present_std={std} "
              f"fb_std_max={fb_std} -> {'PASS' if passed else 'FAIL'}")
        scenes.append({"scene": scene, "tris": sinfo.get("tris"),
                       "region": einfo.get("region"),
                       "n_present_calls": n_calls, "max_present_std": std,
                       "fb_std_max": fb_std, "passed": passed,
                       "sample_buffers": res.get("present_buffers"),
                       "n_fb_reads": res.get("n_fb_reads")})
    return {
        "schema": "astroray.viewport_parity.pkg241_p22_present_check.v1",
        "package": "pkg241", "phase": "P2.2 item 1 (present-wiring bridge test)",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc)
            .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "host": f"{host}:{port}", "min_std_floor": MIN_STD,
        "passed": all_pass, "scenes": scenes,
    }


# pkg241 P2.2 item 5 (Terra review 4): the Buffer byte-identity regression, run
# inside the isolated GUI Blender (which has a live GPU context — gpu.types.Buffer
# cannot be constructed under `blender -b`, which is why this is a bridge test and
# not a pure headless pytest). It reproduces the addon's exact array pipeline
# (__init__.py _update_viewport_texture: RGBA float32, alpha 1.0, vertically
# flipped, contiguous, reshaped flat) and asserts the buffer-protocol path
# (gpu.types.Buffer('FLOAT', n, flat)) is byte-identical to the legacy
# flat.tolist() path that the ~195 ms/present upload used.
_BUFFER_IDENTITY = r'''
import struct
import numpy as np
import gpu
width, height = 129, 71  # odd dims to catch any stride/pad assumption
rng = np.random.default_rng(12345)
pixels = rng.random((height, width, 3), dtype=np.float32)
pixels[0, 0, :] = (0.1, 0.2, 0.3)
pixels[1, 1, :] = (1.0 / 3.0, 2.0 / 3.0, 0.7)
pixels[2, 2, :] = (65504.0, 6.1e-5, 0.0)  # near half-float extremes
rgba = np.ones((height, width, 4), dtype=np.float32)
rgba[:, :, :3] = pixels
rgba = np.ascontiguousarray(rgba[::-1])
flat = rgba.reshape(-1)
n = int(flat.shape[0])
buf_np = gpu.types.Buffer('FLOAT', n, flat)              # the buffer-protocol flip
buf_list = gpu.types.Buffer('FLOAT', n, flat.tolist())   # legacy tolist() path
b_np = bytes(buf_np)
b_list = bytes(buf_list)
equal = (b_np == b_list)
roundtrips = (buf_np.to_list() == flat.tolist())
ndiff = 0
if not equal:
    for i in range(n):
        if (struct.unpack_from('<f', b_np, i * 4)[0]
                != struct.unpack_from('<f', b_list, i * 4)[0]):
            ndiff += 1
result = {'equal': bool(equal), 'roundtrips': bool(roundtrips),
          'n_floats': n, 'n_diff': int(ndiff)}
'''


def run_buffer_identity(args) -> dict:
    """pkg241 P2.2 item 5: assert the gpu.types.Buffer-from-numpy upload is
    byte-identical to flat.tolist(), inside the isolated GUI Blender's GPU
    context. PASS requires equal bytes AND an exact source round-trip."""
    host, port = args.host, args.port
    res = _bridge(_BUFFER_IDENTITY, host, port)
    passed = bool(res.get("equal")) and bool(res.get("roundtrips"))
    print(f"[pkg241-p2] buffer_identity equal={res.get('equal')} "
          f"roundtrips={res.get('roundtrips')} n_floats={res.get('n_floats')} "
          f"n_diff={res.get('n_diff')} -> {'PASS' if passed else 'FAIL'}")
    return {
        "schema": "astroray.viewport_parity.pkg241_p22_buffer_identity.v1",
        "package": "pkg241",
        "phase": "P2.2 item 5 (Buffer byte-identity bridge test)",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc)
            .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "host": f"{host}:{port}", "passed": passed, "result": res,
    }


def run_ui_latency(args) -> dict:
    host, port = args.host, args.port
    configs = []
    for scene in args.scenes:
        sinfo = _open_scene(host, port, scene)
        print(f"[pkg241-p2] scene={scene} tris={sinfo.get('tris')} "
              f"file={sinfo.get('file')}")
        for engine in args.ui_engines:
            einfo = _switch_engine(host, port, _ENGINE_NAME[engine])
            print(f"[pkg241-p2]   engine={engine} ({einfo.get('gpu')}) "
                  f"region={einfo.get('region')}")
            reps = []
            for rep in range(args.ui_reps):
                res = _run_ui_latency(host, port, args.duration_s,
                                       args.warmup_s, args.tick_s,
                                       pattern=args.ui_pattern,
                                       burst_s=args.ui_burst_s,
                                       settle_s=args.ui_settle_s)
                summ = _summarize_ui_latency(res)
                reps.append(summ)
                print(f"[pkg241-p2]     rep {rep + 1}/{args.ui_reps}: "
                      f"n_ticks={summ['n_ticks']} n_renders={summ['n_renders']} "
                      f"n_presents={summ['n_presents']} "
                      f"render_ms_total={summ['render_ms_total']} / "
                      f"wall_ms={summ['total_wall_ms']}"
                      f"{' TRUNCATED' if summ['truncated'] else ''}")
            all_gaps = [g for r in reps for g in r["gaps_ms"]]
            gap_agg = _agg([{"g": g} for g in all_gaps], "g")
            total_wall_ms = sum(r["total_wall_ms"] for r in reps)
            render_ms_total = sum(r["render_ms_total"] for r in reps)
            nominal_ms = args.tick_s * 1000.0
            blocked_excess_ms = sum(r["blocked_excess_ms"] for r in reps)
            blocked_fraction_ticks = (blocked_excess_ms / total_wall_ms
                                       if total_wall_ms > 0 else None)
            render_fraction = (render_ms_total / total_wall_ms
                                if total_wall_ms > 0 else None)
            n_renders = sum(r["n_renders"] for r in reps)
            n_presents = sum(r["n_presents"] for r in reps)
            # pkg241 Phase 2 A2 spike (§9): reduce the concatenated lifeline events.
            all_events = [e for r in reps for e in (r.get("events") or [])]
            spike = _reduce_spike_events(all_events)
            configs.append({
                "scene": scene, "tris": sinfo.get("tris"),
                "region": einfo.get("region"), "engine": engine,
                "gpu": einfo.get("gpu"),
                "reps": args.ui_reps, "duration_s": args.duration_s,
                "warmup_s": args.warmup_s, "tick_s": args.tick_s,
                "nominal_tick_ms": round(nominal_ms, 3),
                "gap_ms": gap_agg,
                "total_wall_ms": round(total_wall_ms, 1),
                "n_ticks": sum(r["n_ticks"] for r in reps),
                "n_renders": n_renders,
                "n_presents": n_presents,
                "render_ms_total": round(render_ms_total, 1),
                "blocked_time_fraction_from_ticks":
                    round(blocked_fraction_ticks, 4)
                    if blocked_fraction_ticks is not None else None,
                "render_time_fraction": round(render_fraction, 4)
                    if render_fraction is not None else None,
                "engine_has_render_hooks": reps[0]["engine_has_hooks"]
                    if reps else None,
                "truncated": any(r["truncated"] for r in reps),
                # pkg241 Phase 2 A2 spike (§9): the generation-tagged reduction
                # (None on the synchronous path / when the worker flag is off).
                "spike": spike,
            })
            p95 = (gap_agg or {}).get("p95_ms")
            print(f"[pkg241-p2]   gap p50={_or(gap_agg, 'p50_ms')} "
                  f"p95={p95} p99={_or(gap_agg, 'p99_ms')} "
                  f"max={_or(gap_agg, 'max_ms')} "
                  f"blocked_frac={blocked_fraction_ticks} "
                  f"render_frac={render_fraction} "
                  f"budget<=33ms: {'PASS' if p95 is not None and p95 <= 33.0 else 'FAIL/NA'}")
            if spike is not None:
                ca = spike.get("cancel_ack") or {}
                cap = spike.get("cancel_ack_pump") or {}
                tt = spike.get("texture_upload_tail") or {}
                cc = spike.get("commit_cost") or {}
                _pr = (spike['present_rate'] if spike.get('present_rate_gradeable')
                       else "UNGRADEABLE")
                print(f"[pkg241-p2]   spike: completed={spike['completed_generations']} "
                      f"presented={spike['presented_completed']} "
                      f"present_rate={_pr} "
                      f"mailbox_depth_max={spike['mailbox_depth_max']} "
                      f"commit p95={cc.get('p95_ms')} "
                      f"cancel_ack p99={ca.get('p99_ms')} "
                      f"cancel_ack_pump p99={cap.get('p99_ms')} "
                      f"tex_tail p95={tt.get('p95_ms')} "
                      f"devices={spike['devices_seen']} "
                      f"cuda_errors={spike['cuda_errors']} "
                      f"n_render_device={spike['n_render_device']} "
                      f"samples/s={spike.get('samples_per_s')} "
                      f"chunk_spp={spike.get('chunk_spp')}")

    return {
        "schema": "astroray.viewport_parity.pkg241_phase2_ui_latency.v1",
        "package": "pkg241",
        "phase": "2 (UI event latency while a viewport chunk renders)",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc)
            .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "host": f"{host}:{port}",
        "budgets": {"ui_latency_p95_ms": _BUDGETS["ui_latency_p95_ms"]},
        "protocol": {
            "bridge": "Blender Lab mcp socket; execute requests over localhost",
            "recorder": "blender_recorder.py _install_ui_latency: a "
                        "bpy.app.timers ticker at tick_s (default 5 ms) "
                        "records its own invocation timestamps while every "
                        "tick also dispatches the next camera/material edit "
                        "+ tag_redraw, so the main thread is continuously "
                        "either running the ticker or blocked inside the "
                        "redraw/render that ticker just triggered -- never "
                        "idle (avoids the Phase 0 idle-window timer-"
                        "throttling artifact structurally rather than via "
                        "OS input injection).",
            "metric": "tick-gap p50/p95/p99/max (ms); a gap >> tick_s is "
                      "main-thread blocking. blocked_time_fraction_from_ticks "
                      "= sum(max(0, gap - tick_s)) / total wall time -- "
                      "computed identically for both engines from the ticks "
                      "alone, so it needs no engine-specific hook.",
            "cross_check": "render_time_fraction = time inside "
                           "Exporter.render_viewport_frame / total wall time "
                           "(Astroray only -- Cycles has no Python "
                           "view_update/view_draw hook to wrap). Presents "
                           "(POST_PIXEL draw-handler) count is recorded for "
                           "both engines as a liveness check that the "
                           "viewport was actually refining, not idle.",
            "warmup_discarded_s": args.warmup_s,
            "duration_s_per_rep": args.duration_s,
            "reps": args.ui_reps,
            "tick_s": args.tick_s,
        },
        "configs": configs,
    }


def _or(d, k):
    return d.get(k) if d else None


def _write_ui_latency_summary_md(doc, path):
    lines = ["# pkg241 Phase 2 — UI event latency while a viewport chunk renders",
             "", f"Generated: {doc['generated_utc']}  ",
             f"Bridge: {doc['host']}  ",
             f"Protocol: {doc['protocol']['reps']}x{doc['protocol']['duration_s_per_rep']}s "
             f"per config, {doc['protocol']['warmup_discarded_s']}s warmup "
             f"discarded, tick_s={doc['protocol']['tick_s']}.", "",
             f"Budget: UI-latency-during-render p95 <= "
             f"{doc['budgets']['ui_latency_p95_ms']} ms (30 fps).", "",
             "## tick-gap (ms) -- lower is more responsive; ~tick_s means fully decoupled", "",
             "| scene | tris | region | engine | gpu | n_ticks | p50 | p95 | p99 | max | blocked_frac | render_frac | n_renders | n_presents | budget | trunc |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in doc["configs"]:
        reg = "x".join(str(v) for v in (c.get("region") or []))
        g = c.get("gap_ms") or {}
        p95 = g.get("p95_ms")
        budget = doc["budgets"]["ui_latency_p95_ms"]
        verdict = ("PASS" if p95 is not None and p95 <= budget else
                   ("FAIL" if p95 is not None else "-"))
        lines.append(
            f"| {c['scene']} | {c['tris']} | {reg} | {c['engine']} | "
            f"{c.get('gpu')} | {c.get('n_ticks')} | {g.get('p50_ms')} | "
            f"{p95} | {g.get('p99_ms')} | {g.get('max_ms')} | "
            f"{c.get('blocked_time_fraction_from_ticks')} | "
            f"{c.get('render_time_fraction')} | {c.get('n_renders')} | "
            f"{c.get('n_presents')} | {verdict} | "
            f"{'Y' if c.get('truncated') else ''} |")
    lines.append("")
    lines.append(
        "`render_frac` (Astroray only -- time inside "
        "`Exporter.render_viewport_frame` / total wall time) cross-checks "
        "`blocked_frac` (derived purely from tick gaps, so it applies to "
        "Cycles too, which has no Python view_update/view_draw hook to "
        "wrap): the two should track together on the Astroray rows, "
        "confirming the tick gaps are real render blocking and not a "
        "timer-throttling artifact. Cycles rows are expected to show "
        "`render_frac`=0/None (no Astroray render calls happened -- Cycles "
        "is native C++, no Python hook to wrap) alongside a low "
        "`blocked_frac` and a nonzero, growing `n_presents` (proving the "
        "viewport kept refining, not merely idling), demonstrating the "
        "decoupled reference the owner described.")
    lines.append("")

    # pkg241 P2.2 (§9 + items 2/3): the generation-tagged worker reduction, when
    # present (ASTRORAY_VIEWPORT_WORKER=1). Empty on the synchronous path.
    spike_rows = [c for c in doc["configs"] if c.get("spike")]
    if spike_rows:
        def _p(d, k, s="p95_ms"):
            v = (d or {}).get(k) or {}
            return v.get(s)
        lines += [
            "## worker lifeline (ASTRORAY_VIEWPORT_WORKER=1) -- generation-tagged",
            "",
            "| scene | engine | completed | presented | present_rate | commit p95 | "
            "cancel_ack p99 | cancel_ack_pump p99 | frame_age p95 | tex_tail p95 | "
            "mailbox_max | chunk_spp (p50/max) | samples/s | devices | cuda_err |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for c in spike_rows:
            s = c["spike"]
            # pkg241 P2.2 item 3 (Terra review 4): present_rate is UNGRADEABLE when
            # no eligible terminal generation exists (continuous storm), not a fake 0.
            pr = (s["present_rate"] if s.get("present_rate_gradeable")
                  else "UNGRADEABLE")
            cspp = s.get("chunk_spp") or {}
            cspp_txt = (f"{cspp.get('p50')}/{cspp.get('max')}" if cspp else "-")
            lines.append(
                f"| {c['scene']} | {c['engine']} | {s['completed_generations']} | "
                f"{s['presented_completed']} | {pr} | "
                f"{_p(s, 'commit_cost')} | {_p(s, 'cancel_ack', 'p99_ms')} | "
                f"{_p(s, 'cancel_ack_pump', 'p99_ms')} | {_p(s, 'frame_age')} | "
                f"{_p(s, 'texture_upload_tail')} | {s['mailbox_depth_max']} | "
                f"{cspp_txt} | {s.get('samples_per_s')} | "
                f"{s['devices_seen']} | {s['cuda_errors']} |")
        lines += [
            "",
            "`commit p95` (P2.2 item 2) is the per-generation main-thread commit "
            "cost; a bounded commit is what lets `cancel_ack_pump p99` (P2.2 item "
            "3/4 -- cancel_request(in-flight g) to the pump draining that gen's "
            "idle_drain(g)) meet the <= 300 ms gate. `present_rate` (terminal "
            "generations whose final publication blitted / eligible terminal "
            "generations) and `frame_age` (per-publication mailbox_enqueue -> "
            "first_blit, >= 0) are defined under `--ui-pattern settle`; when no "
            "eligible terminal generation exists (the continuous stress storm) "
            "`present_rate` is reported UNGRADEABLE, not 0. `chunk_spp` "
            "(p50/max) and `samples/s` (Batch G) are MEASURED: every presented "
            "chunk reports its accumulated spp, and `samples/s` is the sum of each "
            "generation's largest presented spp over the run wall — not inferred "
            "from a fixed chunk size.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    # Blender invokes us with the standard argv plus everything after `--`.
    if "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = sys.argv[1:]
    p = argparse.ArgumentParser()
    p.add_argument("--engine", default="CYCLES",
                   choices=["CYCLES", "CUSTOM_RAYTRACER"])
    p.add_argument("--mode", default="offline",
                   choices=["offline", "interactive", "ui_latency",
                            "present_check", "buffer_identity"])
    p.add_argument("--frames", type=int, default=30)
    p.add_argument("--width", type=int, default=512)
    p.add_argument("--height", type=int, default=512)
    p.add_argument("--chunk-spp", dest="chunk_spp", type=int, default=1)
    p.add_argument("--oidn", action="store_true")
    p.add_argument("--out", type=Path,
                   default=Path(__file__).resolve().parent)
    p.add_argument("--tag", type=str, default=None)
    p.add_argument("--make-scene", dest="make_scene", type=int, default=0,
                   help="build the pkg81 quad-grid scene with ~N tris "
                        "in-Blender (mirrors run.py geometry; use when no "
                        ".blend is provided)")
    p.add_argument("--integrator", default=None,
                   help="Astroray integrator name for the CUSTOM_RAYTRACER "
                        "engine (e.g. wavefront_path_tracer)")
    # pkg241 interactive-mode options (client of the live GUI Blender bridge).
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9876)
    p.add_argument("--scenes", nargs="+", default=["metal_sweep", "big"],
                   choices=["metal_sweep", "big"])
    p.add_argument("--devices", nargs="+", default=["gpu", "cpu"],
                   choices=["gpu", "cpu"])
    p.add_argument("--classes", nargs="+", default=["camera", "material"],
                   choices=["camera", "material"])
    p.add_argument("--events", type=int, default=50)
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--warmup", type=int, default=5)
    # CPU is the slow correctness oracle (~10-15x GPU per frame at this viewport
    # size); a bounded CPU count keeps the matrix tractable. Defaults are set in
    # main() to the GPU counts unless explicitly overridden.
    p.add_argument("--cpu-events", dest="cpu_events", type=int, default=None)
    p.add_argument("--cpu-reps", dest="cpu_reps", type=int, default=None)
    p.add_argument("--rotate-deg", dest="rotate_deg", type=float, default=1.0)
    p.add_argument("--cancel", action="store_true",
                   help="also run the F12 cancel full-stop-floor probe")
    p.add_argument("--cancel-samples", dest="cancel_samples", type=int,
                   default=64)
    p.add_argument("--gpu-deadline-s", dest="gpu_deadline_s", type=float,
                   default=300.0)
    p.add_argument("--cpu-deadline-s", dest="cpu_deadline_s", type=float,
                   default=300.0)
    # pkg241 Phase 1: the same recorder records before/after; --label names the
    # output file so a phase-1 A/B run does not overwrite the phase-0 baseline.
    p.add_argument("--label", default="phase0",
                   help="output-file phase label (e.g. phase0, phase1)")
    # pkg241 Phase 2 (--mode ui_latency): UI event latency while a viewport
    # chunk renders. astroray = CUSTOM_RAYTRACER/gpu; cycles = CYCLES/gpu.
    p.add_argument("--ui-engines", dest="ui_engines", nargs="+",
                   default=["astroray", "cycles"],
                   choices=["astroray", "cycles"])
    p.add_argument("--ui-reps", dest="ui_reps", type=int, default=3)
    p.add_argument("--duration-s", dest="duration_s", type=float, default=10.0,
                   help="measured (post-warmup) seconds per rep")
    p.add_argument("--warmup-s", dest="warmup_s", type=float, default=2.0)
    p.add_argument("--tick-s", dest="tick_s", type=float, default=0.005,
                   help="fine ticker interval (default 5 ms)")
    # pkg241 P2.2 item 4: edit-dispatch pattern for --mode ui_latency.
    p.add_argument("--ui-pattern", dest="ui_pattern", default="continuous",
                   choices=["continuous", "settle"],
                   help="continuous = an edit every tick (stress; present-rate "
                        "undefined); settle = edit bursts + idle spans so "
                        "completed/present-rate/frame-age are defined")
    p.add_argument("--ui-burst-s", dest="ui_burst_s", type=float, default=0.4,
                   help="settle pattern: seconds of edits per cycle")
    p.add_argument("--ui-settle-s", dest="ui_settle_s", type=float, default=2.0,
                   help="settle pattern: idle seconds per cycle (worker "
                        "completes + presents the settling generation)")
    args = p.parse_args(argv)
    if args.cpu_events is None:
        args.cpu_events = args.events
    if args.cpu_reps is None:
        args.cpu_reps = args.reps

    if args.mode == "interactive":
        doc = run_interactive(args)
        args.out.mkdir(parents=True, exist_ok=True)
        tag = args.tag or _dt.date.today().isoformat()
        json_path = args.out / f"{tag}-{args.label}.json"
        json_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        _write_summary_md(doc, args.out / f"{tag}-{args.label}-summary.md")
        print(f"[pkg241] wrote {json_path}")
        return

    if args.mode == "present_check":
        doc = run_present_check(args)
        args.out.mkdir(parents=True, exist_ok=True)
        tag = args.tag or _dt.date.today().isoformat()
        json_path = args.out / f"{tag}-{args.label}.json"
        json_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        print(f"[pkg241-p2] wrote {json_path}")
        sys.exit(0 if doc.get("passed") else 1)

    if args.mode == "buffer_identity":
        doc = run_buffer_identity(args)
        args.out.mkdir(parents=True, exist_ok=True)
        tag = args.tag or _dt.date.today().isoformat()
        json_path = args.out / f"{tag}-{args.label}.json"
        json_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        print(f"[pkg241-p2] wrote {json_path}")
        sys.exit(0 if doc.get("passed") else 1)

    if args.mode == "ui_latency":
        doc = run_ui_latency(args)
        args.out.mkdir(parents=True, exist_ok=True)
        tag = args.tag or _dt.date.today().isoformat()
        json_path = args.out / f"{tag}-{args.label}.json"
        json_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        _write_ui_latency_summary_md(doc, args.out / f"{tag}-{args.label}-summary.md")
        print(f"[pkg241-p2] wrote {json_path}")
        return

    if bpy is None:
        print("blender_driver.py --mode offline must be invoked via "
              "'blender --python'.")
        sys.exit(2)
    doc = run_offline(args)
    args.out.mkdir(parents=True, exist_ok=True)
    tag = args.tag or f"{_dt.date.today().isoformat()}-{args.engine.lower()}"
    json_path = args.out / f"{tag}.json"
    json_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"[pkg81] wrote {json_path}")


if __name__ == "__main__":
    main()
