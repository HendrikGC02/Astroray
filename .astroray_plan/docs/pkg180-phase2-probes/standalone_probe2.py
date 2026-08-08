# -*- coding: utf-8 -*-
"""pkg180 Phase 2 — refined E1/E2: dedicated-vs-mesh emitter, off-axis floor patch,
reference integral evaluated at the SAME floor point. Quantifies the MIS-leg loss."""
import math
import os
import sys

import numpy as np

ROOT = r"C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray"
sys.path.insert(0, os.path.join(ROOT, "tests"))
import runtime_setup  # noqa: E402
runtime_setup.configure_test_imports()

import astroray  # noqa: E402

SEED = 777
ALBEDO = 0.5
RES = 96
HALF_SPAN = 20.0 * math.tan(math.radians(10.0))  # floor half-extent in view (~3.527)


def lum(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def patch_at(px, fx, fz, patch=6):
    """Mean rgb of the patch at floor point (fx, fz). Camera: from (0,20,0.01)
    to (0,0,0), vup (0,0,-1). Image x tracks +x?, image y tracks +/-z — sample
    all 4 symmetric candidates and return them so orientation doesn't matter."""
    res = px.shape[0]

    def grab(ix, iy):
        x0 = int(round(ix - patch / 2))
        y0 = int(round(iy - patch / 2))
        return np.mean(px[y0:y0 + patch, x0:x0 + patch, :3], axis=(0, 1))

    cx = cy = res / 2
    sx = fx / HALF_SPAN * (res / 2)
    sz = fz / HALF_SPAN * (res / 2)
    vals = [grab(cx + sx, cy + sz), grab(cx + sx, cy - sz),
            grab(cx - sx, cy + sz), grab(cx - sx, cy - sz)]
    return np.mean(np.array(vals), axis=0), np.array([lum(v) for v in vals])


def area_reference_at(fx, fz, P=300.0, h=3.0, size=3.0, rho=ALBEDO, n=800):
    A = size * size
    Le = P / (math.pi * A)
    xs = (np.arange(n) + 0.5) / n * size - size / 2
    X, Z = np.meshgrid(xs, xs)
    dx = X - fx
    dz = Z - fz
    d2 = dx * dx + dz * dz + h * h
    d = np.sqrt(d2)
    cos = h / d
    dA = (size / n) ** 2
    integ = Le * cos * cos / d2
    E = np.sum(integ) * dA
    a = d2 / (A * cos)
    b = cos / math.pi
    wt = a * a / (a * a + b * b)
    E_mis = np.sum(integ * wt) * dA
    return rho * E / math.pi, rho * E_mis / math.pi


def floor_scene():
    r = astroray.Renderer()
    try:
        r.set_use_gpu(False)
    except Exception:
        pass
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(SEED)
    mat = r.create_material('lambertian', [ALBEDO] * 3, {})
    r.add_triangle([-20, 0, -20], [20, 0, -20], [20, 0, 20], mat)
    r.add_triangle([-20, 0, -20], [20, 0, 20], [-20, 0, 20], mat)
    r.setup_camera(look_from=[0.0, 20.0, 0.01], look_at=[0.0, 0.0, 0.0],
                   vup=[0.0, 0.0, -1.0], vfov=20.0, aspect_ratio=1.0,
                   aperture=0.0, focus_dist=20.0, width=RES, height=RES)
    return r


FX, FZ = 2.4, 0.0  # probe point well outside the 3x3 quad footprint

ref, ref_mis = area_reference_at(FX, FZ)
print(f"[ref@({FX},{FZ})] analytic L={ref:.5f}  with-MIS-loss L={ref_mis:.5f} "
      f"(kept {ref_mis / ref:.4f})", flush=True)

# --- dedicated lamp ---
r = floor_scene()
r.add_area_light_dedicated([0.0, 3.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0],
                           3.0, 3.0, 'RECTANGLE',
                           {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]}, 300.0, 1.0)
px = np.array(r.render(1024, 4, None, False), dtype=np.float32)
mean_rgb, lums = patch_at(px, FX, FZ)
print(f"[dedicated] patch lums={np.round(lums, 4)} mean={lum(mean_rgb):.5f} "
      f"ratio-vs-analytic={lum(mean_rgb) / ref:.4f} "
      f"ratio-vs-MIS-pred={lum(mean_rgb) / ref_mis:.4f}", flush=True)

# --- radiance-matched hittable emissive mesh ---
r = floor_scene()
Le = 300.0 / (9.0 * math.pi)
em = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': Le})
s, h = 1.5, 3.0
r.add_triangle([-s, h, -s], [s, h, -s], [s, h, s], em)
r.add_triangle([-s, h, -s], [s, h, s], [-s, h, s], em)
px = np.array(r.render(1024, 4, None, False), dtype=np.float32)
mean_rgb, lums = patch_at(px, FX, FZ)
print(f"[mesh-emitter] patch lums={np.round(lums, 4)} mean={lum(mean_rgb):.5f} "
      f"ratio-vs-analytic={lum(mean_rgb) / ref:.4f}", flush=True)
