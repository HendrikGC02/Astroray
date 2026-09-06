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
                entry["classes"][cls] = {
                    "n_events": len(ev),
                    "truncated": r["truncated"],
                    "material": r.get("material"),
                    "present": _agg(ev, "present_ms"),
                    "entry": _agg(ev, "entry_ms"),
                    "render": _agg(ev, "render_ms"),
                    "block": _agg(ev, "block_ms"),
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
             "| scene | tris | region | prev_spp | device | class | n | p50 | p95 | p99 | max | trunc |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in doc["configs"]:
        reg = "x".join(str(v) for v in (c.get("region") or []))
        for cls, d in c["classes"].items():
            p = d["present"] or {}
            lines.append(
                f"| {c['scene']} | {c['tris']} | {reg} | "
                f"{c.get('preview_samples')} | {c['device']} | {cls} | "
                f"{d['n_events']} | {p.get('p50_ms')} | {p.get('p95_ms')} | "
                f"{p.get('p99_ms')} | {p.get('max_ms')} | "
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
                   choices=["offline", "interactive"])
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
    args = p.parse_args(argv)
    if args.cpu_events is None:
        args.cpu_events = args.events
    if args.cpu_reps is None:
        args.cpu_reps = args.reps

    if args.mode == "interactive":
        doc = run_interactive(args)
        args.out.mkdir(parents=True, exist_ok=True)
        tag = args.tag or _dt.date.today().isoformat()
        json_path = args.out / f"{tag}-phase0.json"
        json_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        _write_summary_md(doc, args.out / f"{tag}-phase0-summary.md")
        print(f"[pkg241] wrote {json_path}")
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
