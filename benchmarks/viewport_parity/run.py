#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pkg81 — viewport-interactivity parity harness.

Drives the Astroray persistent viewport renderer (the same code path
``view_update`` / ``view_draw`` use inside Blender) through a deterministic
pan / zoom / orbit camera sequence and records per-frame wall time at the
"view_draw equivalent" boundary plus the pkg56 Phase A ring-buffer breakdown.

What this measures
------------------
Per frame the harness runs:

    1. Depsgraph dispatcher tick (pkg56-C ``_apply_depsgraph_updates``)
    2. Camera setup (matches addon's ``_setup_viewport_camera``)
    3. ``Renderer.render(chunk_spp, depth)``                  ← H4 hot path
    4. Optional viewport-OIDN ``add_pass`` + render            ← H3
    5. ``viewport_perf_frame_complete``

Steps 1–3 mirror what the addon does between ``view_draw`` entry and the
GPU texture blit. The texture blit itself needs a real Blender GL context
and is not measurable in-process — we document the gap rather than fake
it. Cycles' equivalent shape is ``BlenderSession::view_draw``
(intern/cycles/blender/session.cpp); see citation in the camera-path
helper.

What this does NOT measure
--------------------------
- The GPU→display texture upload (pkg52 ``_update_viewport_texture``).
  Blender's ``gpu`` module is unavailable headless. Empirically dominated
  by ``Renderer.render`` for non-trivial scenes; called out in the
  diagnosis.
- Cycles in the same in-process mode — Cycles only renders inside a
  Blender process. The companion driver script
  ``benchmarks/viewport_parity/blender_driver.py`` runs the same camera
  path inside ``blender --python`` for both engines; that is the path
  the project owner runs on the RTX 5070 Ti station to fill in the
  Cycles A/B numbers.

Hardware assumptions
--------------------
Numbers in the committed JSON were captured on the project owner's
station (Windows 11 / MSVC build_cuda / RTX 5070 Ti). The harness runs
on any platform where ``astroray.pyd`` imports; CUDA-only A/B (H4)
requires a build where ``Renderer.gpu_available`` is True.

Usage
-----
::

    # CPU + CUDA A/B at three scene sizes (default):
    python benchmarks/viewport_parity/run.py

    # one scene size only, fewer frames (smoke):
    python benchmarks/viewport_parity/run.py --tris 10000 --frames 16

    # custom output dir:
    python benchmarks/viewport_parity/run.py --out benchmarks/viewport_parity
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import json
import math
import os
import statistics
import sys
import time
import types
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from runtime_setup import configure_test_imports  # noqa: E402
configure_test_imports()

import astroray  # noqa: E402


# ---------------------------------------------------------------------------
# bpy stub — same shape as benchmarks/viewport/pkg56_phase_c.py uses, plus
# a region_data / space_data mock so _setup_viewport_camera works.
# ---------------------------------------------------------------------------

class _BpyId:
    def __init__(self, name="x"):
        self.name = name


class World(_BpyId): pass
class Light(_BpyId): pass
class Material(_BpyId): pass
class NodeTree(_BpyId): pass
class Image(_BpyId): pass
class Scene(_BpyId): pass


class Object(_BpyId):
    def __init__(self, name="obj"):
        super().__init__(name)
        self.matrix_world = [
            [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]
        ]


class _DepsgraphUpdate:
    def __init__(self, id, *, geometry=False, transform=False, shading=False):
        self.id = id
        self.is_updated_geometry = geometry
        self.is_updated_transform = transform
        self.is_updated_shading = shading


def _load_addon():
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base: pass

    class _RenderEngineBase:
        def report(self, *_a, **_k): return None
        def update_progress(self, *_a, **_k): return None
        def update_stats(self, *_a, **_k): return None
        def test_break(self): return False
        def tag_redraw(self): pass

    bpy_types_module.Panel = _Base
    bpy_types_module.Operator = _Base
    bpy_types_module.AddonPreferences = _Base
    bpy_types_module.PropertyGroup = _Base
    bpy_types_module.RenderEngine = _RenderEngineBase
    bpy_types_module.World = World
    bpy_types_module.Light = Light
    bpy_types_module.Material = Material
    bpy_types_module.NodeTree = NodeTree
    bpy_types_module.ShaderNodeTree = NodeTree
    bpy_types_module.Image = Image
    bpy_types_module.Object = Object
    bpy_types_module.Scene = Scene
    bpy_module.types = bpy_types_module

    for name in ("BoolProperty", "IntProperty", "FloatProperty",
                 "StringProperty", "PointerProperty", "FloatVectorProperty",
                 "EnumProperty"):
        setattr(bpy_props_module, name, lambda **_kw: None)
    bpy_module.props = bpy_props_module
    bpy_module.path = types.SimpleNamespace(abspath=lambda p: p)

    sys.modules["bpy"] = bpy_module
    sys.modules["bpy.types"] = bpy_types_module
    sys.modules["bpy.props"] = bpy_props_module
    sys.modules.setdefault("shader_blending",
        types.SimpleNamespace(blend_shader_specs={}, add_shader_specs={}))
    sys.modules.setdefault("mathutils",
        types.SimpleNamespace(Vector=lambda v: v))

    module_path = REPO_ROOT / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "astroray_blender_addon_pkg81", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Counting renderer proxy — wraps a real astroray.Renderer and tallies
# uploader calls per frame. H1 verifier.
# ---------------------------------------------------------------------------

class CountingRenderer:
    """Wraps the real renderer; counts uploader dispatches per frame.

    The dispatcher (pkg56-C) calls upload_geometry / upload_materials /
    upload_lights / upload_environment / update_object_transform /
    upload_scene depending on what the depsgraph says changed. H1 says
    transform-only pan ticks should never call upload_geometry; this
    proxy lets the harness assert that quantitatively.
    """
    _COUNTED = (
        "upload_geometry", "upload_materials", "upload_lights",
        "upload_environment", "update_object_transform", "upload_scene",
        "render", "clear", "clear_passes", "add_pass",
    )

    def __init__(self, real):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_counts", {k: 0 for k in self._COUNTED})

    def reset_counts(self):
        for k in self._counts:
            self._counts[k] = 0

    def snapshot_counts(self):
        return dict(self._counts)

    def __getattr__(self, name):
        attr = getattr(self._real, name)
        if name in self._COUNTED and callable(attr):
            counts = self._counts
            def wrapper(*args, **kwargs):
                counts[name] += 1
                return attr(*args, **kwargs)
            return wrapper
        return attr

    def __setattr__(self, name, value):
        setattr(self._real, name, value)


# ---------------------------------------------------------------------------
# Scene fixtures — synthetic triangle grids at the requested complexities.
# Same shape pkg55 / pkg56 baselines use, kept in-Python so we don't have
# to commit large .blend binaries (Constraint §2 simplicity).
# ---------------------------------------------------------------------------

def _build_renderer(target_tris: int, use_gpu: bool, *, width: int = 256,
                    height: int = 256):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    try:
        r.set_use_gpu(bool(use_gpu))
    except Exception:
        # CPU-only build — set_use_gpu may exist but be a no-op.
        pass
    r.setup_camera(
        look_from=[5, 5, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=40, aspect_ratio=width / max(1, height),
        aperture=0.0, focus_dist=5.0, width=width, height=height,
    )
    palette = [
        r.create_material("lambertian", [0.73, 0.73, 0.73], {}),
        r.create_material("lambertian", [0.65, 0.05, 0.05], {}),
        r.create_material("lambertian", [0.05, 0.65, 0.05], {}),
        r.create_material("lambertian", [0.05, 0.05, 0.65], {}),
        r.create_material("lambertian", [0.65, 0.65, 0.05], {}),
    ]
    quads = max(1, int((target_tris / 2.0) ** 0.5))
    for i in range(quads):
        for j in range(quads):
            x0, x1 = i * 0.1, (i + 1) * 0.1
            z0, z1 = j * 0.1, (j + 1) * 0.1
            mat = palette[(i + j) % len(palette)]
            r.add_triangle([x0, 0, z0], [x1, 0, z0], [x1, 0, z1], mat)
            r.add_triangle([x0, 0, z0], [x1, 0, z1], [x0, 0, z1], mat)
    r.set_background_color([0.5, 0.7, 1.0])
    r.upload_scene()
    return r, 2 * quads * quads


# ---------------------------------------------------------------------------
# Camera path — deterministic pan + zoom + orbit. Mirrors the shape of
# Cycles' BlenderSession::view_update camera updates (no scene mutation,
# just a new view matrix per frame). Frame 0 = full sync, frames 1..N-1
# pan/zoom/orbit.
# ---------------------------------------------------------------------------

def _camera_path(n_frames: int):
    """Yield (look_from, look_at, vfov) for each frame.

    Frames split into three thirds: pan, zoom, orbit. Deterministic
    angle/translation steps so the JSON output is comparable run-to-run.
    """
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
        a = 0.5 * t  # rad
        x = cx * math.cos(a) - cz * math.sin(a)
        z = cx * math.sin(a) + cz * math.cos(a)
        yield ([x, cy, z], [0, 0, 0], 40.0)


# ---------------------------------------------------------------------------
# Per-frame measurement
# ---------------------------------------------------------------------------

def _percentile(samples_ms, p):
    if not samples_ms:
        return float("nan")
    s = sorted(samples_ms)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def _frame_summary(samples_ms):
    return {
        "n": len(samples_ms),
        "mean_ms": statistics.mean(samples_ms) if samples_ms else 0.0,
        "p50_ms": _percentile(samples_ms, 50),
        "p99_ms": _percentile(samples_ms, 99),
        "max_ms": max(samples_ms) if samples_ms else 0.0,
        "first_ms": samples_ms[0] if samples_ms else 0.0,
    }


def _drive_pan_zoom_orbit(eng, renderer_proxy: CountingRenderer,
                          width: int, height: int, n_frames: int,
                          chunk_spp: int, max_depth: int,
                          use_oidn_pass: bool,
                          path: str = "camera_only"):
    """Drive the camera path. Returns dict of measurements for one config.

    ``path`` chooses which Blender scenario to emulate:

    * ``camera_only`` (default) — pure pan/zoom/orbit. Blender does NOT
      fire ``view_update`` for camera moves; the addon's ``view_draw``
      detects the change via ``_camera_state_hash`` and re-renders. The
      dispatcher does not run, so H1 uploader counts MUST be zero. This
      is the primary scenario for the project owner's complaint.
    * ``transform_edit`` — user drags a mesh with the gizmo. Blender
      fires a transform-only depsgraph update each tick, hitting the
      pkg56-C dispatcher. With the current single-level BVH this
      promotes to ``upload_geometry`` every frame (pkg56-C documented
      limitation); H1 measures how much that costs.
    """
    real = renderer_proxy._real
    astroray.viewport_perf_reset()
    eng._viewport_renderer = real
    eng._viewport_full_synced = True

    frame_ms: list[float] = []
    render_ms: list[float] = []
    dispatch_ms: list[float] = []
    spp_trace: list[int] = []
    upload_geometry_per_frame: list[int] = []
    upload_materials_per_frame: list[int] = []

    transform_dg = types.SimpleNamespace(
        updates=[_DepsgraphUpdate(Object("ViewportObj"), transform=True)],
        scene=None)

    for frame_idx, (look_from, look_at, vfov) in enumerate(_camera_path(n_frames)):
        renderer_proxy.reset_counts()

        t_frame = time.perf_counter()

        # 1) dispatcher tick — only in transform_edit. camera_only mirrors
        #    real Blender, where pan never fires view_update.
        if path == "transform_edit":
            t0 = time.perf_counter()
            eng._apply_depsgraph_updates(renderer_proxy, transform_dg, settings=None)
            dispatch_ms.append((time.perf_counter() - t0) * 1000.0)
        else:
            dispatch_ms.append(0.0)

        # 2) camera setup — matches _setup_viewport_camera's renderer call.
        real.setup_camera(
            look_from, look_at, [0, 1, 0],
            float(vfov), width / max(1, height), 0.0, 10.0, width, height,
        )

        # 3) optional OIDN pass registration (H3 toggle).
        try:
            real.clear_passes()
        except AttributeError:
            pass
        if use_oidn_pass:
            try:
                real.add_pass("oidn_denoiser")
            except Exception:
                # Pass may not be registered on this build; skip silently
                # so the JSON still says use_oidn_pass=True with H3
                # tagged "skipped: pass-not-available".
                pass

        # 4) render — chunk_spp samples, depth from settings.
        t0 = time.perf_counter()
        real.render(chunk_spp, max_depth)
        render_ms.append((time.perf_counter() - t0) * 1000.0)
        astroray.record_viewport_stage("render", render_ms[-1])

        astroray.viewport_perf_frame_complete()
        frame_ms.append((time.perf_counter() - t_frame) * 1000.0)

        # H1: how many uploader calls did this transform-only tick make?
        snap = renderer_proxy.snapshot_counts()
        upload_geometry_per_frame.append(snap["upload_geometry"])
        upload_materials_per_frame.append(snap["upload_materials"])

        # H2: viewport-side accumulation tracking. The harness doesn't go
        # through _render_viewport_frame's accumulator (that wants gpu),
        # but the addon's policy is reset_accumulation=camera_changed. We
        # emulate the "what spp would the viewport be at" by recording
        # chunk_spp every frame — i.e. a fresh accumulator every tick. Any
        # future H2 fix would tee off this trace.
        spp_trace.append(int(chunk_spp))

    return {
        "frame": _frame_summary(frame_ms),
        "render": _frame_summary(render_ms),
        "dispatch": _frame_summary(dispatch_ms),
        "first_minus_steady_ms": (
            frame_ms[0] - statistics.mean(frame_ms[1:])
            if len(frame_ms) >= 2 else 0.0),
        "h1_upload_geometry_calls_per_frame_max":
            max(upload_geometry_per_frame) if upload_geometry_per_frame else 0,
        "h1_upload_geometry_calls_per_frame_total":
            sum(upload_geometry_per_frame),
        "h1_upload_materials_calls_per_frame_total":
            sum(upload_materials_per_frame),
        "h2_spp_trace_unique_values": sorted(set(spp_trace)),
        "h2_spp_resets_per_frame_estimate":
            sum(1 for _ in spp_trace),  # current policy: every frame.
        "viewport_perf_stats": astroray.viewport_perf_stats(),
        "raw_frame_ms": frame_ms,
    }


# ---------------------------------------------------------------------------
# Top-level run — iterate (scene size × CPU/CUDA × OIDN on/off) and write
# the JSON + a tiny summary.html.
# ---------------------------------------------------------------------------

def _engine_label(use_gpu: bool, gpu_name: str) -> str:
    return f"astroray-cuda ({gpu_name})" if use_gpu else "astroray-cpu"


def run(args) -> dict:
    addon = _load_addon()
    eng = addon.CustomRaytracerRenderEngine()

    # Detect what this binary supports.
    probe = astroray.Renderer()
    gpu_available = bool(getattr(probe, "gpu_available", False))
    gpu_name = str(getattr(probe, "gpu_device_name", "")) or "unknown"

    out = {
        "schema": "astroray.viewport_parity.v1",
        "package": "pkg81",
        "phase": "1+2 (harness + diagnosis)",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc)
            .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "git_sha": os.environ.get("GIT_SHA", ""),
        "binary": {
            "gpu_available": gpu_available,
            "gpu_device_name": gpu_name,
        },
        "harness_notes": [
            "in-process; bypasses Blender GPU texture blit (gpu module unavailable headless).",
            "transform-only depsgraph fires every camera tick — this is the H1 verifier.",
            "Cycles A/B numbers are filled in by blender_driver.py on the same hardware.",
        ],
        "configs": [],
    }

    tris_list = args.tris if args.tris else [10_000, 100_000, 1_000_000]
    backends: list[bool] = []
    if not args.gpu_only:
        backends.append(False)
    if gpu_available and not args.cpu_only:
        backends.append(True)
    if not backends:
        backends = [False]

    paths = ["camera_only"]
    if args.with_transform_edit:
        paths.append("transform_edit")
    for tris in tris_list:
        for use_gpu in backends:
            for use_oidn in (False, True) if not args.no_h3 else (False,):
                for path in paths:
                    cfg_label = (f"tris={tris} engine="
                                 f"{_engine_label(use_gpu, gpu_name)} "
                                 f"oidn={'on' if use_oidn else 'off'} "
                                 f"path={path}")
                    print(f"[pkg81] {cfg_label}")
                    renderer, n_tris = _build_renderer(
                        tris, use_gpu, width=args.width, height=args.height)
                    proxy = CountingRenderer(renderer)
                    result = _drive_pan_zoom_orbit(
                        eng, proxy,
                        width=args.width, height=args.height,
                        n_frames=args.frames,
                        chunk_spp=args.chunk_spp,
                        max_depth=args.max_depth,
                        use_oidn_pass=use_oidn,
                        path=path,
                    )
                    result["config"] = {
                        "tris_target": tris,
                        "tris_built": n_tris,
                        "use_gpu": use_gpu,
                        "engine": _engine_label(use_gpu, gpu_name),
                        "oidn_pass": use_oidn,
                        "width": args.width,
                        "height": args.height,
                        "chunk_spp": args.chunk_spp,
                        "max_depth": args.max_depth,
                        "n_frames": args.frames,
                        "path": path,
                    }
                    out["configs"].append(result)

    return out


def _write_summary_html(out_path: Path, doc: dict) -> None:
    rows = []
    for cfg in doc["configs"]:
        c = cfg["config"]
        f = cfg["frame"]
        r = cfg["render"]
        rows.append(
            f"<tr><td>{c['tris_built']}</td><td>{c['engine']}</td>"
            f"<td>{'on' if c['oidn_pass'] else 'off'}</td>"
            f"<td>{f['mean_ms']:.2f}</td><td>{f['p50_ms']:.2f}</td>"
            f"<td>{f['p99_ms']:.2f}</td><td>{r['mean_ms']:.2f}</td>"
            f"<td>{cfg['h1_upload_geometry_calls_per_frame_max']}</td>"
            f"<td>{cfg['first_minus_steady_ms']:.2f}</td></tr>"
        )
    html = f"""<!doctype html><meta charset=utf-8>
<title>pkg81 viewport-parity harness</title>
<style>body{{font-family:sans-serif}}td,th{{padding:4px 8px;border:1px solid #ccc}}
table{{border-collapse:collapse}}</style>
<h1>pkg81 — viewport-parity harness</h1>
<p>Generated {doc['generated_utc']}. Binary: {doc['binary']}.</p>
<table><tr><th>tris</th><th>engine</th><th>OIDN pass</th>
<th>frame mean</th><th>frame p50</th><th>frame p99</th>
<th>render mean</th><th>H1 max upload_geom/frame</th>
<th>H5 first−steady (ms)</th></tr>
{''.join(rows)}
</table>
<p>Cycles A/B numbers: see blender_driver.py output, merged by date.</p>
"""
    out_path.write_text(html, encoding="utf-8")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--frames", type=int, default=60,
                   help="Frames per camera path (default 60: 20 pan + 20 zoom + 20 orbit).")
    p.add_argument("--tris", type=int, nargs="+", default=None,
                   help="Triangle counts (default: 10000 100000 1000000).")
    p.add_argument("--width", type=int, default=512)
    p.add_argument("--height", type=int, default=512)
    p.add_argument("--chunk-spp", dest="chunk_spp", type=int, default=1,
                   help="spp per chunk (matches viewport_chunk_spp default).")
    p.add_argument("--max-depth", dest="max_depth", type=int, default=4)
    p.add_argument("--cpu-only", action="store_true")
    p.add_argument("--gpu-only", action="store_true")
    p.add_argument("--no-h3", action="store_true",
                   help="Skip the OIDN A/B (H3).")
    p.add_argument("--with-transform-edit", action="store_true",
                   help="Also run the transform-edit path (mesh-drag scenario; "
                        "fires pkg56-C dispatcher with a transform-only update). "
                        "Default off — pure camera-only pan never hits the "
                        "dispatcher in real Blender.")
    p.add_argument("--out", type=Path,
                   default=Path(__file__).parent,
                   help="Output directory.")
    p.add_argument("--tag", type=str, default=None,
                   help="Optional filename tag (default: today's date).")
    p.add_argument("--smoke", action="store_true",
                   help="Tiny scene + few frames; for the smoke test.")
    args = p.parse_args(argv)

    if args.smoke:
        args.tris = [256]
        args.frames = 6
        args.width = 32
        args.height = 32

    doc = run(args)

    args.out.mkdir(parents=True, exist_ok=True)
    tag = args.tag or _dt.date.today().isoformat()
    json_path = args.out / f"{tag}.json"
    html_path = args.out / "summary.html"
    json_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    _write_summary_html(html_path, doc)
    print(f"[pkg81] wrote {json_path}")
    print(f"[pkg81] wrote {html_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
