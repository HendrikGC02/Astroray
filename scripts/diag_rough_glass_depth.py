"""Localize the CPU rough-glass loss: furnace vs path depth (CPU only).

If the furnace value DROPS as depth increases, the loss compounds per internal
bounce (a per-interaction BSDF energy leak). If it is flat vs depth, a single
dominant event (e.g. first enter or the rough->delta boundary) is responsible.
"""
import sys
import numpy as np

sys.path.insert(0, "tests")
from runtime_setup import configure_test_imports  # noqa: E402
configure_test_imports()
import astroray  # noqa: E402


def furnace(roughness, depth, spp=256):
    r = astroray.Renderer()
    r.set_background_color([1.0, 1.0, 1.0])
    g = r.create_material("disney", [1.0, 1.0, 1.0],
                          {"transmission": 1.0, "ior": 1.5, "roughness": roughness, "metallic": 0.0})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, g)
    r.set_integrator("path_tracer")
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 80, 80)
    r.set_seed(7)
    img = np.asarray(r.render(spp, depth, None, True), dtype=np.float32).reshape(80, 80, 3)
    return float(img[28:52, 28:52].mean())


print(f"{'R':>6} | " + " ".join(f"d={d:<2}" for d in [1, 2, 4, 8, 16, 32]))
print("-" * 60)
for R in [0.03, 0.05, 0.1, 0.3, 1.0]:
    vals = [furnace(R, d) for d in [1, 2, 4, 8, 16, 32]]
    print(f"{R:>6.2f} | " + " ".join(f"{v:>5.3f}" for v in vals))
