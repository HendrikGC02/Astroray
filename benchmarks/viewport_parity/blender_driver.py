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

    "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" ^
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
    print("blender_driver.py must be invoked via 'blender --python'.")
    raise


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


def run_offline(args) -> dict:
    scene = bpy.context.scene
    scene.render.engine = args.engine
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    if args.engine == "CYCLES":
        scene.cycles.samples = args.chunk_spp
        scene.cycles.preview_samples = args.chunk_spp
        scene.cycles.use_denoising = bool(args.oidn)
    elif hasattr(scene, "custom_raytracer"):
        scene.custom_raytracer.preview_samples = args.chunk_spp
        scene.custom_raytracer.viewport_chunk_spp = args.chunk_spp
        scene.custom_raytracer.viewport_oidn = bool(args.oidn)

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
        },
        "frame": _frame_summary(samples_ms),
        "raw_frame_ms": samples_ms,
        "notes": [
            "Offline mode = F12 render per camera position. Approximates",
            "per-frame view_draw cost; not a true viewport-interactivity",
            "measurement. Use --mode interactive in a GUI Blender for that.",
        ],
    }


def main():
    # Blender invokes us with the standard argv plus everything after `--`.
    if "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = []
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
    args = p.parse_args(argv)

    if args.mode == "offline":
        doc = run_offline(args)
    else:
        # Interactive mode kept as a documented stub. Implementing a
        # robust modal+timer recorder is its own ~day of work and is
        # routed to the project owner's station for the live numbers.
        # See blender_driver.py docstring.
        print("[pkg81] interactive mode is a stub — see docstring. "
              "Use offline for headless A/B numbers.")
        sys.exit(2)

    args.out.mkdir(parents=True, exist_ok=True)
    tag = args.tag or f"{_dt.date.today().isoformat()}-{args.engine.lower()}"
    json_path = args.out / f"{tag}.json"
    json_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"[pkg81] wrote {json_path}")


if __name__ == "__main__":
    main()
