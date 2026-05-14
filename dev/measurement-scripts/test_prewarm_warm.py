#!/usr/bin/env python
"""Measure warm-start first-frame latency (with pre-warm)."""

import sys, time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from runtime_setup import configure_test_imports
configure_test_imports()

import astroray


def build_trivial_scene(renderer):
    mat_id = renderer.create_material("disney", [0.8, 0.8, 0.8], {})
    for i in range(10):
        for j in range(10):
            renderer.add_sphere([i*2, 0, j*2], 0.5, mat_id)


print("=== Warm Start (with pre-warm) ===")

# Pre-warm on temporary renderer
print("Running pre-warm on temporary renderer...")
t0 = time.perf_counter()
temp = astroray.Renderer()
if not temp.gpu_available:
    print("SKIP: No CUDA GPU available")
    sys.exit(0)
temp.set_use_gpu(True)
temp.prewarm_cuda()
prewarm_ms = (time.perf_counter() - t0) * 1000.0
print(f"Pre-warm: {prewarm_ms:.1f} ms")
del temp

# Real renderer and scene
renderer = astroray.Renderer()
build_trivial_scene(renderer)
renderer.setup_camera([5, 5, 5], [0, 0, 0], [0, 1, 0], 60.0, 1.0, 0.0, 1.0, 256, 256)
renderer.set_use_gpu(True)

# First render: should be fast (kernel cached)
t0 = time.perf_counter()
pixels = renderer.render(1, 4)
first_ms = (time.perf_counter() - t0) * 1000.0

# Second render
t0 = time.perf_counter()
pixels = renderer.render(1, 4)
second_ms = (time.perf_counter() - t0) * 1000.0

print(f"First frame (post-prewarm): {first_ms:.1f} ms (should be fast)")
print(f"Second frame: {second_ms:.1f} ms")
print(f"PREWARM={prewarm_ms:.1f}")
print(f"WARM_FIRST={first_ms:.1f}")
