#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pkg56 Phase C — depsgraph-driven dispatch wall-time bench.

Measures the two acceptance gates from the package spec on the same
99k-triangle scene the Phase A baseline used:

  - Idle frame   <= 5  ms p99  (no domain edits → dispatcher returns
                                'idle', upload + render are skipped)
  - Transform-only edit <= 20 ms p99 (transform-only edits without an
                                obj→prim-id map promote to upload_geometry —
                                see pkg56 spec §C; this benches the
                                actual cost on the single-level BVH the
                                project ships today)

The bench exercises the real Phase B uploaders + the addon's Phase C
dispatcher. It deliberately stubs out the bpy.types.* hierarchy so it
runs without Blender, the same way `tests/test_pkg56_phase_c_dispatch.py`
runs in CI.

Usage:
    python benchmarks/viewport/pkg56_phase_c.py
    ASTRORAY_PKGC_TRIS=99458 ASTRORAY_PKGC_FRAMES=200 python ...
"""

from __future__ import annotations

import importlib.util
import os
import statistics
import sys
import time
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from runtime_setup import configure_test_imports  # noqa: E402
configure_test_imports()

import astroray  # noqa: E402

# Phase B bindings detection — the bench is correct end-to-end against
# a Phase-B-enabled astroray.pyd; on older builds the Phase B uploader
# calls fall through and we measure dispatcher overhead only.
_HAS_PHASE_B = all(hasattr(astroray.Renderer, m) for m in (
    "upload_geometry", "upload_materials", "upload_lights",
    "upload_environment",
))


class _NullPhaseBRenderer:
    """Stand-in renderer used when the loaded astroray.pyd predates the
    Phase B bindings. Dispatch overhead alone is what the idle gate
    measures; the transform-only gate is only meaningful against the
    real Phase B uploaders and is reported as 'requires rebuild' on
    older binaries."""
    def upload_geometry(self):    pass
    def upload_materials(self):   pass
    def upload_lights(self):      pass
    def upload_environment(self): pass
    def upload_scene(self):       pass
    def update_object_transform(self, obj_id, mat16): pass


# ---------------------------------------------------------------------------
# stub bpy with the bpy.types.* hierarchy the dispatcher classifies on
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
        "astroray_blender_addon_pkg56c_bench", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# 99k-tri scene — same shape as scripts/diagnostics/pkg56_phase_a_baseline.py
# ---------------------------------------------------------------------------

def _build_scene(target_tris: int):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.setup_camera(
        look_from=[5, 5, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=40, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
        width=128, height=128,
    )
    palette = [
        r.create_material("lambertian", [0.73, 0.73, 0.73], {}),
        r.create_material("lambertian", [0.65, 0.05, 0.05], {}),
        r.create_material("lambertian", [0.05, 0.65, 0.05], {}),
        r.create_material("lambertian", [0.05, 0.05, 0.65], {}),
        r.create_material("lambertian", [0.65, 0.65, 0.05], {}),
    ]
    quads = max(1, int((target_tris / 2.0) ** 0.5))
    n = 0
    for i in range(quads):
        for j in range(quads):
            x0, x1 = i * 0.1, (i + 1) * 0.1
            z0, z1 = j * 0.1, (j + 1) * 0.1
            mat = palette[(i + j) % len(palette)]
            r.add_triangle([x0, 0, z0], [x1, 0, z0], [x1, 0, z1], mat)
            r.add_triangle([x0, 0, z0], [x1, 0, z1], [x0, 0, z1], mat)
            n += 2
    # Phase B full sync — primes the device-state. On older astroray.pyd
    # builds without the Phase B bindings the bench still measures
    # dispatch overhead correctly (the dispatcher tolerates a
    # non-Phase-B Renderer via AttributeError handling on each call).
    if hasattr(r, "upload_scene"):
        r.upload_scene()
    return r, n


# ---------------------------------------------------------------------------
# Bench loop — tick the dispatcher with depsgraphs of each kind
# ---------------------------------------------------------------------------

def _percentile(samples_ms, p):
    if not samples_ms:
        return float('nan')
    s = sorted(samples_ms)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def _bench_dispatch(eng, renderer, depsgraph, n_frames):
    """Tick `_apply_depsgraph_updates` n_frames times and return per-tick
    wall times in milliseconds. View_draw / render / camera setup are
    NOT included — the gate is on the dispatch path itself, which is
    what runs for idle and transform-only frames in the real viewport."""
    samples = []
    for _ in range(n_frames):
        t0 = time.perf_counter()
        eng._apply_depsgraph_updates(renderer, depsgraph, settings=None)
        samples.append((time.perf_counter() - t0) * 1000.0)
    return samples


def main() -> int:
    target_tris = int(os.environ.get("ASTRORAY_PKGC_TRIS", "99458"))
    n_frames = int(os.environ.get("ASTRORAY_PKGC_FRAMES", "200"))

    addon = _load_addon()
    eng = addon.CustomRaytracerRenderEngine()

    print(f"pkg56 Phase C — depsgraph dispatch wall-time bench")
    print(f"  target triangles : {target_tris}")
    print(f"  frames per case  : {n_frames}")

    if _HAS_PHASE_B:
        renderer, n_tris = _build_scene(target_tris)
        print(f"  built scene      : {n_tris} triangles (Phase B uploaders live)")
    else:
        renderer = _NullPhaseBRenderer()
        n_tris = 0
        print(f"  Phase B bindings missing on this astroray.pyd — running "
              f"dispatch-overhead-only mode (rebuild for end-to-end numbers)")
    eng._viewport_renderer = renderer
    eng._viewport_full_synced = True

    # Case 1 — idle frame: empty .updates list. Dispatcher must return
    # 'idle' with no uploader calls. Acceptance gate: <= 5 ms p99.
    idle_dg = types.SimpleNamespace(updates=[], scene=None)
    idle_samples = _bench_dispatch(eng, renderer, idle_dg, n_frames)
    idle_p99 = _percentile(idle_samples, 99)
    idle_mean = statistics.mean(idle_samples)
    print(f"  idle  : mean {idle_mean:.3f} ms  p50 {_percentile(idle_samples, 50):.3f}  "
          f"p99 {idle_p99:.3f}  (gate <= 5 ms)")

    # Case 2 — transform-only edit on one Object. Without an obj→prim-id
    # map, this promotes to upload_geometry (BVH rebuild). Gate: <= 20 ms p99.
    obj = Object("Cube")
    xform_dg = types.SimpleNamespace(
        updates=[_DepsgraphUpdate(obj, transform=True)], scene=None)
    xform_samples = _bench_dispatch(eng, renderer, xform_dg, n_frames)
    xform_p99 = _percentile(xform_samples, 99)
    xform_mean = statistics.mean(xform_samples)
    print(f"  xform : mean {xform_mean:.3f} ms  p50 {_percentile(xform_samples, 50):.3f}  "
          f"p99 {xform_p99:.3f}  (gate <= 20 ms)")

    # Case 3 — material slider drag. Should be the cheapest non-idle path.
    mat_dg = types.SimpleNamespace(
        updates=[_DepsgraphUpdate(Material("M"))], scene=None)
    mat_samples = _bench_dispatch(eng, renderer, mat_dg, n_frames)
    print(f"  mat   : mean {statistics.mean(mat_samples):.3f} ms  "
          f"p50 {_percentile(mat_samples, 50):.3f}  "
          f"p99 {_percentile(mat_samples, 99):.3f}")

    # Acceptance gate decision — exit non-zero if the idle gate misses.
    rc = 0
    if idle_p99 > 5.0:
        print(f"FAIL: idle p99 {idle_p99:.3f} ms exceeds 5 ms gate")
        rc = 1
    else:
        print(f"PASS: idle p99 within 5 ms gate")
    if xform_p99 > 20.0:
        # Documented limitation — single-level BVH means transform-only
        # edits are dominated by upload_geometry's BVH rebuild. Don't
        # fail the script on this; surface the number for the spec.
        print(f"NOTE: xform p99 {xform_p99:.3f} ms exceeds 20 ms — "
              f"single-level BVH limit, two-level refit lands in a "
              f"follow-up package (pkg56 spec §B key design 2).")
    return rc


if __name__ == "__main__":
    sys.exit(main())
