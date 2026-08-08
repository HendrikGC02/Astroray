# -*- coding: utf-8 -*-
"""pkg180 Phase 2 — standalone-engine localization probes (CPU, engine core only).

Experiments:
  E1 area_dedicated  : diffuse floor under 3x3 dedicated area light, vs numeric reference
                       (with and without the MIS power-heuristic weight), depth 1 and 8.
  E2 area_mesh       : same geometry but the emitter is a HITTABLE emissive mesh quad
                       with radiance matched to E1 -> both MIS legs exist.
  E3 sun             : diffuse floor under dedicated sun E=pi -> analytic L = 0.5.
  E4 mirror_lamp     : low-roughness metal floor, camera sees the lamp's reflection.
  E5 mirror_mesh     : same but emissive mesh quad instead of the dedicated lamp.
"""
import math
import os
import sys

import numpy as np

ROOT = r"C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray"
sys.path.insert(0, os.path.join(ROOT, "tests"))
import runtime_setup  # noqa: E402
runtime_setup.configure_test_imports()

import astroray  # noqa: E402

print("astroray:", astroray.__file__, flush=True)

SEED = 777  # nonzero: seed 0 is the random sentinel
ALBEDO = 0.5


def lum(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def center_rgb(px, patch=8):
    h, w = px.shape[0], px.shape[1]
    cy, cx = h // 2, w // 2
    p = px[cy - patch // 2:cy + patch // 2, cx - patch // 2:cx + patch // 2, :3]
    return np.mean(p, axis=(0, 1))


def floor_scene(metal=False):
    r = astroray.Renderer()
    try:
        r.set_use_gpu(False)
    except Exception:
        pass
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(SEED)
    if metal:
        mat = r.create_material('metal', [0.9, 0.9, 0.9], {'roughness': 0.05})
    else:
        mat = r.create_material('lambertian', [ALBEDO] * 3, {})
    r.add_triangle([-20, 0, -20], [20, 0, -20], [20, 0, 20], mat)
    r.add_triangle([-20, 0, -20], [20, 0, 20], [-20, 0, 20], mat)
    return r


def topdown_camera(r, res=48):
    r.setup_camera(look_from=[0.0, 20.0, 0.01], look_at=[0.0, 0.0, 0.0],
                   vup=[0.0, 0.0, -1.0], vfov=20.0, aspect_ratio=1.0,
                   aperture=0.0, focus_dist=20.0, width=res, height=res)


# ---------------------------------------------------------------------------
# Numeric reference for E1/E2: 3x3 plate at h=3 over floor point (0,0,0).
# L_e = P/(pi*A);  E = int L_e cos_s cos_l / d^2 dA  (cos_s = cos_l = h/d)
# L_ref = rho*E/pi.   MIS-lost prediction multiplies the integrand by
# wt = a^2/(a^2+b^2), a = d^2/(A*cos_l), b = cos_s/pi.
# ---------------------------------------------------------------------------
def area_reference(P=300.0, h=3.0, size=3.0, rho=ALBEDO, n=600):
    A = size * size
    Le = P / (math.pi * A)
    xs = (np.arange(n) + 0.5) / n * size - size / 2
    zs = xs.copy()
    X, Z = np.meshgrid(xs, zs)
    d2 = X * X + Z * Z + h * h
    d = np.sqrt(d2)
    cos = h / d
    dA = (size / n) ** 2
    integ = Le * cos * cos / d2                       # per-dA irradiance
    E = np.sum(integ) * dA
    a = d2 / (A * cos)                                # solid-angle light pdf
    b = cos / math.pi                                 # lambertian bsdf pdf
    wt = a * a / (a * a + b * b)
    E_mis = np.sum(integ * wt) * dA
    return rho * E / math.pi, rho * E_mis / math.pi, E_mis / E


def run(tag, r, spp, depth):
    px = np.array(r.render(spp, depth, None, False), dtype=np.float32)
    c = center_rgb(px)
    print(f"[{tag}] depth={depth} spp={spp} center_rgb={c} lum={lum(c):.5f} "
          f"img_mean={float(np.mean(px[..., :3])):.5f}", flush=True)
    return px


def exp_area_dedicated():
    ref, ref_mis, frac = area_reference()
    print(f"[E1-ref] analytic L={ref:.5f}  predicted-with-MIS-loss L={ref_mis:.5f} "
          f"(kept fraction {frac:.4f})", flush=True)
    for depth in (1, 8):
        r = floor_scene()
        topdown_camera(r)
        # normal = u x v = (1,0,0)x(0,0,1) = (0,-1,0) -> faces the floor
        r.add_area_light_dedicated([0.0, 3.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0],
                                   3.0, 3.0, 'RECTANGLE',
                                   {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]},
                                   300.0, 1.0)
        run("E1-area-dedicated", r, 768, depth)


def exp_area_mesh():
    # Radiance-matched emissive quad: L_e = 300/(9*pi)
    Le = 300.0 / (9.0 * math.pi)
    for depth in (1, 8):
        r = floor_scene()
        topdown_camera(r)
        em = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': Le})
        s = 1.5
        h = 3.0
        # Quad at y=3 facing down (winding chosen both ways below via two tris each
        # face order; emission side is measured, not assumed).
        r.add_triangle([-s, h, -s], [s, h, -s], [s, h, s], em)
        r.add_triangle([-s, h, -s], [s, h, s], [-s, h, s], em)
        run("E2-area-mesh", r, 768, depth)


def exp_sun():
    for depth in (1, 8):
        r = floor_scene()
        topdown_camera(r)
        r.add_sun_light_dedicated([0.0, -1.0, 0.0], math.radians(0.526),
                                  {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]},
                                  math.pi)
        run("E3-sun (analytic 0.5)", r, 768, depth)


def mirror_camera(r, res=96):
    r.setup_camera(look_from=[0.0, 3.0, 8.0], look_at=[0.0, 0.0, 0.0],
                   vup=[0.0, 1.0, 0.0], vfov=30.0, aspect_ratio=1.0,
                   aperture=0.0, focus_dist=8.5, width=res, height=res)


def bright_stats(px, k=40):
    l = 0.2126 * px[..., 0] + 0.7152 * px[..., 1] + 0.0722 * px[..., 2]
    flat = np.sort(l.ravel())[::-1]
    return float(flat[:k].mean()), float(l.max()), float(l.mean())


def exp_mirror(mesh):
    # Light centered at (0,3,-8): the mirror image of the camera direction at the
    # floor origin. Radiance L_e = 100/(pi*4) for both variants.
    P, size = 100.0, 2.0
    Le = P / (math.pi * size * size)
    n = np.array([0.0, -3.0, 8.0])
    n = n / np.linalg.norm(n)          # faces back toward the floor origin
    u = np.array([1.0, 0.0, 0.0])
    v = np.cross(n, u)                 # u x v = n
    c = np.array([0.0, 3.0, -8.0])
    r = floor_scene(metal=True)
    mirror_camera(r)
    if mesh:
        em = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': Le})
        hs = size / 2
        p00 = c - u * hs - v * hs
        p10 = c + u * hs - v * hs
        p11 = c + u * hs + v * hs
        p01 = c - u * hs + v * hs
        r.add_triangle(list(p00), list(p10), list(p11), em)
        r.add_triangle(list(p00), list(p11), list(p01), em)
        tag = "E5-mirror-mesh"
    else:
        r.add_area_light_dedicated(list(c), list(u), list(v), size, size,
                                   'RECTANGLE',
                                   {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]},
                                   P, 1.0)
        tag = "E4-mirror-lamp"
    px = np.array(r.render(512, 4, None, False), dtype=np.float32)
    top, mx, mean = bright_stats(px)
    print(f"[{tag}] top40_lum={top:.5f} max_lum={mx:.5f} img_mean={mean:.5f} "
          f"(reflected lamp radiance would be ~{Le * 0.9:.3f} on a perfect 0.9 mirror)",
          flush=True)
    np.save(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         f"{tag}.npy"), px)


if __name__ == "__main__":
    exp_area_dedicated()
    exp_area_mesh()
    exp_sun()
    exp_mirror(mesh=False)
    exp_mirror(mesh=True)
