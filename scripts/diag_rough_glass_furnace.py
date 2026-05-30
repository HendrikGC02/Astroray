"""Phase-1 evidence: current CPU vs GPU Disney rough-glass white-furnace values.

Measures the same furnace as tests/test_disney_rough_glass_furnace.py across a
roughness sweep, CPU and GPU, so we can see exactly where the CPU residual lives.
"""
from __future__ import annotations

import sys
import numpy as np

sys.path.insert(0, "tests")
from runtime_setup import configure_test_imports  # noqa: E402

configure_test_imports()
import astroray  # noqa: E402

print("module:", astroray.__file__)
print("features:", astroray.__features__)


def furnace(roughness: float, *, use_gpu: bool, spp: int = 256, depth: int = 32) -> float:
    r = astroray.Renderer()
    r.set_background_color([1.0, 1.0, 1.0])
    g = r.create_material("disney", [1.0, 1.0, 1.0],
                          {"transmission": 1.0, "ior": 1.5, "roughness": roughness, "metallic": 0.0})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, g)
    r.set_integrator("path_tracer")
    if use_gpu:
        r.set_use_gpu(True)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 80, 80)
    r.set_seed(7)
    img = np.asarray(r.render(spp, depth, None, True), dtype=np.float32).reshape(80, 80, 3)
    return float(img[28:52, 28:52].mean())


ROUGH = [0.05, 0.1, 0.3, 0.6, 1.0]
gpu_ok = astroray.Renderer().gpu_available
print(f"\nGPU available: {gpu_ok}")
print(f"{'R':>6} | {'CPU@256':>9} | {'GPU@256':>9} | {'delta':>7}")
print("-" * 40)
for R in ROUGH:
    cpu = furnace(R, use_gpu=False)
    gpu = furnace(R, use_gpu=True) if gpu_ok else float("nan")
    print(f"{R:>6.2f} | {cpu:>9.4f} | {gpu:>9.4f} | {cpu-gpu:>+7.4f}")
