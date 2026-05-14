#!/usr/bin/env python
"""Quick measurement: verify pkg84 pre-warm reduces first-frame latency.

Run two scenarios:
1. Cold start: fresh Renderer, enable CUDA, render immediately → ~12s first frame
2. Warm start: fresh Renderer, enable CUDA, prewarm_cuda(), render → ~14ms first frame

Expected results per pkg84 spec:
- Cold first frame: ~12,079 ms (pkg81 measurement)
- Warm first frame: ≤ 100 ms (target)
- Pre-warm itself: ~12 s (cost moved, not eliminated)
"""

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

from runtime_setup import configure_test_imports
configure_test_imports()

import astroray


def build_trivial_scene(renderer):
    """10k triangle scene — same size as pkg81 harness 'easy' config."""
    mat_id = renderer.create_material("disney", [0.8, 0.8, 0.8], {})
    # Simple grid of spheres
    for i in range(10):
        for j in range(10):
            renderer.add_sphere([i*2, 0, j*2], 0.5, mat_id)


def measure_cold_start():
    """Measure first-frame latency without pre-warm."""
    print("\n=== Cold Start (no pre-warm) ===")
    renderer = astroray.Renderer()

    if not renderer.gpu_available:
        print("SKIP: No CUDA GPU available")
        return None

    build_trivial_scene(renderer)
    renderer.setup_camera([5, 5, 5], [0, 0, 0], [0, 1, 0], 60.0, 1.0, 0.0, 1.0, 256, 256)

    # Enable CUDA but don't pre-warm
    renderer.set_use_gpu(True)

    # First render: this is where the JIT happens
    t0 = time.perf_counter()
    pixels = renderer.render(1, 4)  # 1 spp, 4 bounces
    first_frame_ms = (time.perf_counter() - t0) * 1000.0

    print(f"First frame: {first_frame_ms:.1f} ms")

    # Second render: should be fast (kernel is cached)
    t0 = time.perf_counter()
    pixels = renderer.render(1, 4)
    second_frame_ms = (time.perf_counter() - t0) * 1000.0

    print(f"Second frame: {second_frame_ms:.1f} ms")

    return first_frame_ms, second_frame_ms


def measure_warm_start():
    """Measure first-frame latency with pre-warm."""
    print("\n=== Warm Start (with pre-warm) ===")

    # Pre-warm on a separate temporary renderer (matches addon pattern)
    print("Running pre-warm on temporary renderer...")
    t0 = time.perf_counter()
    temp = astroray.Renderer()
    if not temp.gpu_available:
        print("SKIP: No CUDA GPU available")
        return None
    temp.set_use_gpu(True)
    temp.prewarm_cuda()
    prewarm_ms = (time.perf_counter() - t0) * 1000.0
    print(f"Pre-warm: {prewarm_ms:.1f} ms")
    del temp

    # Now create the real renderer and scene
    renderer = astroray.Renderer()
    build_trivial_scene(renderer)
    renderer.setup_camera([5, 5, 5], [0, 0, 0], [0, 1, 0], 60.0, 1.0, 0.0, 1.0, 256, 256)
    renderer.set_use_gpu(True)

    # First "real" render: should be fast (kernel is cached)
    t0 = time.perf_counter()
    pixels = renderer.render(1, 4)
    first_frame_ms = (time.perf_counter() - t0) * 1000.0

    print(f"First frame (post-prewarm): {first_frame_ms:.1f} ms")

    # Second render: also fast
    t0 = time.perf_counter()
    pixels = renderer.render(1, 4)
    second_frame_ms = (time.perf_counter() - t0) * 1000.0

    print(f"Second frame: {second_frame_ms:.1f} ms")

    return prewarm_ms, first_frame_ms, second_frame_ms


if __name__ == "__main__":
    cold_result = measure_cold_start()
    warm_result = measure_warm_start()

    if cold_result and warm_result:
        cold_first, cold_second = cold_result
        prewarm, warm_first, warm_second = warm_result

        print("\n=== Summary ===")
        print(f"Cold first frame:     {cold_first:>10.1f} ms  (JIT happens here)")
        print(f"Cold second frame:    {cold_second:>10.1f} ms  (cached)")
        print(f"Pre-warm:             {prewarm:>10.1f} ms  (cost moved here)")
        print(f"Warm first frame:     {warm_first:>10.1f} ms  (cached)")
        print(f"Warm second frame:    {warm_second:>10.1f} ms  (cached)")
        print()
        print(f"Improvement: {cold_first:.1f} ms → {warm_first:.1f} ms")
        print(f"  ({cold_first / warm_first:.1f}× faster first frame)")
        print()

        if warm_first <= 100:
            print("✓ pkg84 acceptance criterion met: first frame ≤ 100 ms")
        else:
            print(f"✗ First frame still {warm_first:.1f} ms (target ≤ 100 ms)")

        if prewarm >= 10000:
            print("✓ Pre-warm time ~12s (cost moved, not eliminated)")
        else:
            print(f"? Pre-warm unexpectedly fast: {prewarm:.1f} ms")
