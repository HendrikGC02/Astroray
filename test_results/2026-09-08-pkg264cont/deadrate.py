import os, sys, math
import numpy as np
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ASTRORAY_BUILD_DIR", r"C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/build_cuda")
sys.path.insert(0, os.path.join(REPO, "tests"))
from runtime_setup import configure_test_imports
configure_test_imports()
import astroray
def dead_rate(kind, roughness, theta_deg, N=20000):
    r = astroray.Renderer()
    if kind == "principled":
        p = {"transmission_weight": 1.0, "ior": 1.45, "roughness": roughness}
    else:
        p = {"transmission": 1.0, "ior": 1.45, "roughness": roughness, "metallic": 0.0}
    mid = r.create_material(kind, [1,1,1], p)
    th = math.radians(theta_deg)
    wo = [math.sin(th), math.cos(th), 0.0]   # normal is (0,1,0)
    u2 = np.random.rand(2, N).astype(np.float32)
    wi, pdf = r.debug_bsdf_sample_batch(mid, wo, u2)
    return float((pdf <= 0.0).mean())
print("dead-sample fraction (entering, normal=+Y)   principled / disney")
for rough in (0.2, 0.5, 0.85):
    row = []
    for th in (0, 45, 75, 85):
        row.append((th, dead_rate("principled",rough,th), dead_rate("disney",rough,th)))
    print(f"r={rough}: " + "  ".join(f"th{t}:{p:.2f}/{d:.2f}" for t,p,d in row))
