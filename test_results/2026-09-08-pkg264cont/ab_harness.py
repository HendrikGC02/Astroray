# -*- coding: utf-8 -*-
"""pkg264-cont render-level A/B — in-process reproduction of the pkg263 glass
scene through the raw engine binding (build_cuda .pyd), to isolate the mechanism
of the limb darkening BEFORE any formula change.

Reproduces benchmarks/cycles-parity/metal_ab/scenes.build_glass_scene exactly
as the addon translates it (ShaderNodeBsdfGlass -> native 'principled',
transmission_weight=1, ior=1.45, roughness=r; grey world 0.6*0.3=0.18; one
area light energy=150, size 1.0; grey plane; camera through the sphere centre),
then sweeps ONE integrator lever at a time and reports centre/limb ROI means.

Not committed as a reusable script (one-off diagnostic under test_results/).
"""
import argparse
import math
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# A/B uses the MAIN checkout's build_cuda .pyd (no C++ change on this branch yet).
BUILD = os.environ.get("ASTRORAY_BUILD_DIR",
                       r"C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/build_cuda")
os.environ["ASTRORAY_BUILD_DIR"] = BUILD
sys.path.insert(0, os.path.join(REPO, "tests"))
from runtime_setup import configure_test_imports  # noqa: E402
configure_test_imports()
import astroray  # noqa: E402
print("astroray:", astroray.__file__, "features:", astroray.__features__)

# ---- pkg263 scene constants (scenes.py) ----
IOR = 1.45
SR = 0.6                       # sphere radius
GAP = 0.05
Z = SR + GAP                   # 0.65 sphere centre height
CAM_D = 2.4
FOV = 50.0                     # full angle (cam_data.angle)
WORLD = 0.6 * 0.3              # grey world colour * strength = 0.18
PLANE = 0.5
LIGHT_E = 150.0
LIGHT_SIZE = 1.0
LIGHT_LOC = (1.2, -1.2, Z + 1.75)
LIGHT_EULER = (math.radians(35.0), 0.0, math.radians(25.0))


def euler_xyz_matrix(rx, ry, rz):
    """Blender Euler('XYZ').to_matrix() == Rz @ Ry @ Rx (extrinsic X,Y,Z)."""
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def build(r, roughness):
    r.set_background_color([WORLD, WORLD, WORLD])
    glass = r.create_material(
        "principled", [1.0, 1.0, 1.0],
        {"transmission_weight": 1.0, "ior": IOR, "roughness": roughness,
         "emission_color": [0.0, 0.0, 0.0], "emission_strength": 0.0})
    r.add_sphere([0.0, 0.0, Z], SR, glass)

    # grey diffuse floor (two triangles, 20x20 at z=0)
    floor = r.create_material("principled", [PLANE, PLANE, PLANE], {"roughness": 0.6})
    h = 10.0
    r.add_triangle([-h, -h, 0.0], [h, -h, 0.0], [h, h, 0.0], floor)
    r.add_triangle([-h, -h, 0.0], [h, h, 0.0], [-h, h, 0.0], floor)

    # area light (addon convention: axis_u=basis@X, axis_v=basis@-Y, emit u x v = -Z)
    basis = euler_xyz_matrix(*LIGHT_EULER)
    au = list(basis @ np.array([1.0, 0.0, 0.0]))
    av = list(basis @ np.array([0.0, -1.0, 0.0]))
    r.add_area_light_dedicated(
        list(LIGHT_LOC), au, av, LIGHT_SIZE, LIGHT_SIZE, "RECTANGLE",
        {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, LIGHT_E, 1.0)

    r.set_integrator("path_tracer")
    r.setup_camera([0.0, -CAM_D, Z], [0.0, 0.0, Z], [0.0, 0.0, 1.0],
                   FOV, 1.0, 0.0, CAM_D, RES, RES)


def roi_means(img):
    """centre disc (<0.35R) and limb annulus (0.8R-0.98R), sphere centred."""
    alpha = math.asin(SR / CAM_D)
    rpx = (math.tan(alpha) / math.tan(math.radians(FOV / 2.0))) * (RES / 2.0)
    yy, xx = np.mgrid[0:RES, 0:RES]
    cy = cx = RES / 2.0 - 0.5
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    centre = d < 0.35 * rpx
    limb = (d >= 0.80 * rpx) & (d <= 0.98 * rpx)
    lum = img.mean(axis=2)
    return float(lum[centre].mean()), float(lum[limb].mean()), rpx


RES = 200
SPP = 128


def render(roughness, maxd, db, gb, tb, seed=7):
    r = astroray.Renderer()
    build(r, roughness)
    r.set_seed(seed)
    img = np.asarray(r.render(SPP, maxd, None, False, db, gb, tb),
                     dtype=np.float32).reshape(RES, RES, 3)
    return img


# pkg263 pinned references (linear luminance ~ per-channel mean since neutral)
CYCLES = {0.0: (0.1773, 0.2842), 0.2: (0.1801, 0.3139),
          0.5: (0.2225, 0.4271), 0.85: (0.2917, 0.5099)}
ADDON = {0.0: (0.1708, 0.2315), 0.2: (0.1710, 0.2112),
         0.5: (0.1801, 0.1891), 0.85: (0.1532, 0.1741)}


def render_cfg(roughness, maxd, db, gb, tb, filter_glossy=None, seed=7):
    r = astroray.Renderer()
    build(r, roughness)
    if filter_glossy is not None:
        r.set_filter_glossy(filter_glossy)
    r.set_seed(seed)
    img = np.asarray(r.render(SPP, maxd, None, False, db, gb, tb),
                     dtype=np.float32).reshape(RES, RES, 3)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spp", type=int, default=128)
    ap.add_argument("--res", type=int, default=200)
    args = ap.parse_args()
    global RES, SPP
    RES, SPP = args.res, args.spp

    print(f"\nRES={RES} SPP={SPP}")
    print("Reference pkg263:  Cycles(centre/limb)   addon(centre/limb)")
    print(f"{'r':>5} {'cfg':22} {'centre':>8} {'limb':>8} {'lc':>6}"
          f" {'c/Cyc':>7} {'l/Cyc':>7} {'c/addon':>8} {'l/addon':>8}")
    for roughness in (0.0, 0.2, 0.5, 0.85):
        cc, cl = CYCLES[roughness]
        ac, al = ADDON[roughness]
        cfgs = [
            ("baseline_d4g4t12", 12, 4, 4, 12, None),
            ("high_all_64", 64, 64, 64, 64, None),
            ("filterglossy_0", 12, 4, 4, 12, 0.0),
            ("filterglossy_1", 12, 4, 4, 12, 1.0),
        ]
        for name, md, db, gb, tb, fg in cfgs:
            img = render_cfg(roughness, md, db, gb, tb, filter_glossy=fg)
            c, l, _ = roi_means(img)
            lc = l / c if c > 0 else float("nan")
            print(f"{roughness:>5} {name:22} {c:8.4f} {l:8.4f} {lc:6.3f}"
                  f" {c/cc:7.3f} {l/cl:7.3f} {c/ac:8.3f} {l/al:8.3f}")


if __name__ == "__main__":
    main()
