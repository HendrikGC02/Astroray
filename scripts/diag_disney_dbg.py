"""pkg118: single-roughness CPU disney-glass furnace + depth sweep.

  python scripts/diag_disney_dbg.py 0.05            # one roughness, depth 32
  python scripts/diag_disney_dbg.py 0.05 4,16,64    # depth sweep (truncation test)

The per-event DISNEY_DBG instrumentation used to localize the leak (rough_refl /
rough_refr / delta_refl / delta_refr counts + avg throughput + fallthrough count) is
described in .astroray_plan/docs/pkg118-multiscatter-energy-research.md ("PRECISE
LOCALIZATION"). Re-add it to disney.cpp::sample() for the next fix attempt.
"""
import sys
import numpy as np

sys.path.insert(0, "tests")
from runtime_setup import configure_test_imports  # noqa: E402
configure_test_imports()
import astroray  # noqa: E402

R = float(sys.argv[1]) if len(sys.argv) > 1 else 0.05
depths = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else [32]
for depth in depths:
    r = astroray.Renderer()
    r.set_background_color([1.0, 1.0, 1.0])
    g = r.create_material("disney", [1.0, 1.0, 1.0],
                          {"transmission": 1.0, "ior": 1.5, "roughness": R, "metallic": 0.0})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, g)
    r.set_integrator("path_tracer")
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 80, 80)
    r.set_seed(7)
    img = np.asarray(r.render(256, depth, None, True), dtype=np.float32).reshape(80, 80, 3)
    print("R=%.3f depth=%-4d furnace=%.4f" % (R, depth, float(img[28:52, 28:52].mean())))
