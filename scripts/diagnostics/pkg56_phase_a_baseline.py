#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pkg56 Phase A — measured baseline driver.

Builds a ~100k-triangle reference scene against the C++ renderer
directly (no Blender), feeds the per-stage timings through the
``astroray.record_viewport_stage`` ring buffer, and prints
``astroray.viewport_perf_stats()`` so the numbers can be pasted into
the pkg56 spec.

Renderer-side only — the full Blender→addon→renderer baseline (with
mesh-eval and Python ↔ pyd marshalling overhead) requires running the
addon inside Blender on a real .blend, which Phase B's incremental
dispatch will optimise around. This script captures the inner
renderer cost so Phase C has a measured target.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from runtime_setup import configure_test_imports  # noqa: E402
configure_test_imports()

import astroray  # noqa: E402


def _build_scene(renderer, target_triangles: int) -> tuple[int, int]:
    """Push triangles + a handful of materials into ``renderer``.

    Returns (n_triangles, n_materials). Triangles are a regular grid of
    pairs of triangles (two per quad), so the count is rounded down to
    an even number.
    """
    palette = [
        renderer.create_material("lambertian", [0.73, 0.73, 0.73], {}),
        renderer.create_material("lambertian", [0.65, 0.05, 0.05], {}),
        renderer.create_material("lambertian", [0.05, 0.65, 0.05], {}),
        renderer.create_material("lambertian", [0.05, 0.05, 0.65], {}),
        renderer.create_material("lambertian", [0.65, 0.65, 0.05], {}),
    ]

    # n quads × 2 triangles ≈ target_triangles. Pick the closest square.
    quads_per_side = max(1, int((target_triangles / 2.0) ** 0.5))
    n_tris = 0
    for i in range(quads_per_side):
        for j in range(quads_per_side):
            x0, x1 = i * 0.1, (i + 1) * 0.1
            z0, z1 = j * 0.1, (j + 1) * 0.1
            mat = palette[(i + j) % len(palette)]
            renderer.add_triangle([x0, 0, z0], [x1, 0, z0], [x1, 0, z1], mat)
            renderer.add_triangle([x0, 0, z0], [x1, 0, z1], [x0, 0, z1], mat)
            n_tris += 2
    return n_tris, len(palette)


def main() -> int:
    target = int(os.environ.get("ASTRORAY_BASELINE_TRIS", "100000"))
    n_frames = int(os.environ.get("ASTRORAY_BASELINE_FRAMES", "5"))

    astroray.viewport_perf_reset()

    n_tris = 0
    n_materials = 0
    for _ in range(n_frames):
        renderer = astroray.Renderer()
        renderer.set_integrator("path_tracer")
        renderer.setup_camera(
            look_from=[5, 5, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
            vfov=40, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
            width=128, height=128,
        )

        # "materials" stage — palette upload.
        t0 = time.perf_counter()
        # build_scene allocates materials internally, so split: time the
        # material creation alone first.
        palette = [
            renderer.create_material("lambertian", [0.73, 0.73, 0.73], {}),
            renderer.create_material("lambertian", [0.65, 0.05, 0.05], {}),
            renderer.create_material("lambertian", [0.05, 0.65, 0.05], {}),
            renderer.create_material("lambertian", [0.05, 0.05, 0.65], {}),
            renderer.create_material("lambertian", [0.65, 0.65, 0.05], {}),
        ]
        astroray.record_viewport_stage(
            "materials", (time.perf_counter() - t0) * 1000.0)
        n_materials = len(palette)

        # "geometry" stage — triangle upload + (later) BVH build inside
        # render(). Here we capture just the upload cost; the BVH is
        # built lazily on the first render() call below and rolls into
        # the "render" stage. That matches the addon's measurement
        # boundary, where convert_objects() returns before render runs.
        t0 = time.perf_counter()
        quads = max(1, int((target / 2.0) ** 0.5))
        n_tris = 0
        for i in range(quads):
            for j in range(quads):
                x0, x1 = i * 0.1, (i + 1) * 0.1
                z0, z1 = j * 0.1, (j + 1) * 0.1
                mat = palette[(i + j) % len(palette)]
                renderer.add_triangle([x0, 0, z0], [x1, 0, z0], [x1, 0, z1], mat)
                renderer.add_triangle([x0, 0, z0], [x1, 0, z1], [x0, 0, z1], mat)
                n_tris += 2
        astroray.record_viewport_stage(
            "geometry", (time.perf_counter() - t0) * 1000.0)

        # "lights" stage — none (renderer-only bench, no Blender lights).
        astroray.record_viewport_stage("lights", 0.0)
        # "environment" stage — solid background.
        t0 = time.perf_counter()
        renderer.set_background_color([0.5, 0.7, 1.0])
        astroray.record_viewport_stage(
            "environment", (time.perf_counter() - t0) * 1000.0)

        # "render" stage — single low-spp pass (mirrors the viewport's
        # progressive chunk).
        t0 = time.perf_counter()
        renderer.render(1, 4, None, False)
        astroray.record_viewport_stage(
            "render", (time.perf_counter() - t0) * 1000.0)

        astroray.viewport_perf_frame_complete()

    stats = astroray.viewport_perf_stats()
    print(f"pkg56 Phase A baseline (renderer-only)")
    print(f"  triangles : {n_tris}")
    print(f"  materials : {n_materials}")
    print(f"  frames    : {stats['frames']}")
    print(f"  geometry  : {stats['geometry']:.2f} ms (mean)")
    print(f"  materials : {stats['materials']:.2f} ms (mean)")
    print(f"  lights    : {stats['lights']:.2f} ms (mean)")
    print(f"  environment: {stats['environment']:.2f} ms (mean)")
    print(f"  render    : {stats['render']:.2f} ms (mean, 1 spp / depth 4)")
    print(f"  TOTAL     : {stats['total']:.2f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
