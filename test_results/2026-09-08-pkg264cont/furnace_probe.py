# -*- coding: utf-8 -*-
"""pkg264-cont — white-furnace probe: does the NATIVE 'principled' transmission
lobe conserve energy like 'disney' glass does? Clear glass in a uniform white
field must render ~1.0 (radiance invariant along a bent ray). The pkg263 gate
renders 'principled'; the shipped furnace gates cover 'disney'."""
import os
import sys
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ASTRORAY_BUILD_DIR",
                      r"C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/build_cuda")
sys.path.insert(0, os.path.join(REPO, "tests"))
from runtime_setup import configure_test_imports  # noqa: E402
configure_test_imports()
import astroray  # noqa: E402


def furnace(kind, roughness, spp=256, depth=32, ior=1.45):
    r = astroray.Renderer()
    r.set_background_color([1.0, 1.0, 1.0])
    if kind == "principled":
        params = {"transmission_weight": 1.0, "ior": ior, "roughness": roughness}
    else:  # disney
        params = {"transmission": 1.0, "ior": ior, "roughness": roughness, "metallic": 0.0}
    g = r.create_material(kind, [1.0, 1.0, 1.0], params)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, g)
    r.set_integrator("path_tracer")
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 80, 80)
    r.set_seed(7)
    img = np.asarray(r.render(spp, depth, None, False), dtype=np.float32).reshape(80, 80, 3)
    return float(img[28:52, 28:52].mean())


print(f"IOR 1.45 white furnace (target 1.0)   {'roughness':>10}")
print(f"{'r':>6} {'principled':>12} {'disney':>10}")
for rough in (0.0, 0.2, 0.5, 0.85, 1.0):
    p = furnace("principled", rough)
    d = furnace("disney", rough)
    print(f"{rough:>6} {p:>12.4f} {d:>10.4f}")
