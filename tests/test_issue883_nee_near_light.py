"""#883 — near-light direct lighting: NEE on == NEE off == analytic.

A Lambertian floor lit by one small emitter (emissive sphere, emissive
triangle, dedicated rectangle lamp) 0.1 / 0.3 / 1 m above it. Direct lighting
of a plane has closed forms, so each leg is checked against an analytic
reference, not only against the other leg:
  * sphere of radiance L, radius r, centre height h (wholly above the plane):
    E = pi L r^2 cos(theta) / d^2 (exact for a Lambertian sphere).
  * polygon: Lambert's formula E = L/2 sum_i beta_i (n . (a_i x a_i+1)^).
Floor radiance = albedo/pi * E, averaged over 4x4 sub-pixels per pixel.

The #883 report (NEE-on/NEE-off 1.22 for a sphere light) was measured with
adaptive sampling ON: its colour-blind stop metric (pkg237) ends the noisy
NEE-off leg early on pixels that have not yet hit the small light, reading it
1.18-1.54x dark. With adaptive sampling off both legs match the analytic value.
The main-branch biases this also pins: the +0.001 triangle-pdf fudge (#851,
triangle NEE +4-11 %) and the pre-#852 area lamp (-24..-29 % at 0.1 m).

set_light_nee(False) is CPU-only (the GPU wavefront has no unbiased NEE-off
mode), so the GPU leg checks NEE-on against the same analytic value.
"""
import math

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

_RES, _SS, _CAM_H, _ALB = 32, 4, 3.0, 0.5
_SEEDS = (101, 102, 103, 104, 105)
_HEIGHTS = (0.1, 0.3, 1.0)
_KINDS = ("sphere", "triangle", "area")
_REL_TOL = 0.01      # predeclared #883 gate
_SIGMA_MULT = 3.0    # NEE-off is heavy-tailed: gate on max(1 %, 3 sigma)


def _floor_points(half):
    t = half / _CAM_H
    o = (np.arange(_SS) + 0.5) / _SS
    s = (np.arange(_RES)[:, None] + o[None, :]).ravel() / _RES
    u = (2 * s - 1) * t
    X = np.broadcast_to(u[None, :], (s.size, s.size)) * _CAM_H   # screen right = +x
    Z = np.broadcast_to(u[:, None], (s.size, s.size)) * _CAM_H   # image down = +z
    return X, Z


def _polygon_irradiance(X, Z, verts):
    P = np.stack([X, np.zeros_like(X), Z], -1)
    E = np.zeros_like(X)
    for i in range(len(verts)):
        a = np.asarray(verts[i], float) - P
        b = np.asarray(verts[(i + 1) % len(verts)], float) - P
        a /= np.linalg.norm(a, axis=-1, keepdims=True)
        b /= np.linalg.norm(b, axis=-1, keepdims=True)
        c = np.cross(a, b)
        beta = np.arccos(np.clip((a * b).sum(-1), -1.0, 1.0))
        E += beta * c[..., 1] / np.maximum(np.linalg.norm(c, axis=-1), 1e-30)
    return 0.5 * np.abs(E)


def _block(a):
    return a.reshape(_RES, _SS, _RES, _SS).mean(axis=(1, 3))


def _render(kind, h, nee, seed, spp, gpu=False):
    """Returns (ROI mean, analytic ROI mean)."""
    half = max(0.25, 0.75 * h)
    r = astroray.Renderer()
    if gpu:
        r.set_use_gpu(True)
    r.set_background_color([0.0, 0.0, 0.0])
    floor = r.create_material("lambertian", [_ALB] * 3, {})
    r.add_triangle([-5, 0, -5], [5, 0, 5], [5, 0, -5], floor)
    r.add_triangle([-5, 0, -5], [-5, 0, 5], [5, 0, 5], floor)
    X, Z = _floor_points(half)
    k = _CAM_H / (_CAM_H - h)            # emitter silhouette magnification
    if kind == "sphere":
        rad = 0.05
        L = (h / rad) ** 2 / math.pi
        r.add_sphere([0, h, 0], rad, r.create_material("light", [1, 1, 1], {"intensity": L}))
        d2 = X ** 2 + Z ** 2 + h * h
        E = L * math.pi * rad * rad * (h / np.sqrt(d2)) / d2
        occl = np.hypot(X, Z) < 1.1 * rad * k
    elif kind == "triangle":
        a = 0.1
        L = 2.0 * (h / a) ** 2 / math.pi
        v0, v1, v2 = [-a, h, -a / 2], [a, h, -a / 2], [0, h, a]  # normal -y
        r.add_triangle(v0, v1, v2, r.create_material("light", [1, 1, 1], {"intensity": L}))
        E = L * _polygon_irradiance(X, Z, [v0, v1, v2])
        occl = (np.abs(X) < 1.1 * a * k) & (np.abs(Z) < 1.1 * a * k)
    else:
        a = 0.1
        P = (h / a) ** 2
        L = P / (math.pi * a * a)            # Lambertian lamp radiance P/(pi A)
        r.add_area_light_dedicated([0, h, 0], [1, 0, 0], [0, 0, 1], a, a, "RECTANGLE",
                                   {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, P)
        q = a / 2
        E = L * _polygon_irradiance(X, Z, [[-q, h, -q], [q, h, -q], [q, h, q], [-q, h, q]])
        occl = np.zeros_like(X, bool)       # lamps are camera-invisible
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)          # pkg237 confound (the #883 report)
    if not gpu:
        r.set_light_nee(nee)
    vfov = 2 * math.degrees(math.atan(half / _CAM_H))
    r.setup_camera([0, _CAM_H, 0], [0, 0, 0], [0, 0, -1], vfov, 1.0, 0.0, _CAM_H, _RES, _RES)
    r.set_seed(seed)
    img = np.asarray(r.render(spp, 4, None, False), np.float64).reshape(_RES, _RES, 3)
    mask = _block(occl.astype(float)) == 0
    ref = _block(_ALB / math.pi * E)
    return float(img.mean(-1)[mask].mean()), float(ref[mask].mean())


def _stats(v):
    a = np.asarray(v, float)
    return float(a.mean()), float(a.std(ddof=1) / math.sqrt(a.size))


@pytest.mark.cpu
@pytest.mark.parametrize("h", _HEIGHTS)
@pytest.mark.parametrize("kind", _KINDS)
def test_cpu_nee_on_off_match_analytic(kind, h):
    on_runs = [_render(kind, h, True, s, 256) for s in _SEEDS]
    ref = on_runs[0][1]
    on, sem_on = _stats([m for m, _ in on_runs])
    off, sem_off = _stats([_render(kind, h, False, s, 8192)[0] for s in _SEEDS])
    assert abs(on / ref - 1) < _REL_TOL, (
        f"{kind} h={h}: NEE-on {on:.5f}+-{sem_on:.5f} vs analytic {ref:.5f} "
        f"(ratio {on / ref:.4f})")
    tol = max(_REL_TOL * on, _SIGMA_MULT * math.hypot(sem_on, sem_off))
    assert abs(on - off) <= tol, (
        f"{kind} h={h}: NEE-on {on:.5f} vs NEE-off {off:.5f}+-{sem_off:.5f} "
        f"(on/off {on / off:.4f}, tol {tol / on:.4f}); analytic {ref:.5f}")


@pytest.mark.gpu
@pytest.mark.parametrize("h", _HEIGHTS)
@pytest.mark.parametrize("kind", _KINDS)
def test_gpu_nee_matches_analytic(kind, h):
    if not getattr(astroray, "__features__", {}).get("cuda", False):
        pytest.skip("CUDA build required")
    runs = [_render(kind, h, True, s, 256, gpu=True) for s in _SEEDS]
    ref = runs[0][1]
    on, sem = _stats([m for m, _ in runs])
    assert abs(on / ref - 1) < _REL_TOL, (
        f"GPU {kind} h={h}: {on:.5f}+-{sem:.5f} vs analytic {ref:.5f} (ratio {on / ref:.4f})")
