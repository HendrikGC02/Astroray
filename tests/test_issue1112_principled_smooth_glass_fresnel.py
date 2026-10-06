"""#1112: smooth Principled glass (roughness <= 0.03, delta branch) chose reflect vs
refract with Schlick at the INCIDENT angle, which is ~43 % low for internal
reflections (exit side, eta > 1). Fix: exact side-aware dielectric Fresnel (Cycles
bsdf_util.h fresnel_dielectric; pbrt-v4 FrDielectric) on CPU and GPU.

A white furnace is blind to this (the delta f/pdf is 1 whatever the split
probability), so it is kept only as a regression guard. The failing check is an
analytic reference: a perfect n=1.5 sphere lit by one rectangular lamp; the
bottom-right quadrant is the lamp seen after internal reflection(s), the top-left
the external reflection (calibrates the lamp radiance). Exact Fresnel, all
reflect/refract chains to depth 10, traced in numpy (from batch-i lane i11).

Measured CPU (96 px, 512 spp): BR/TL 5.28 before, 8.99 after; analytic 9.44.
"""

from __future__ import annotations

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

_N = 64
_ETA = 1.5
_LAMP_C = np.array([-3.0, 3.0, 6.0])


def _lamp_frame():
    n = -_LAMP_C / np.linalg.norm(_LAMP_C)
    u = np.cross([0, 1, 0], n); u /= np.linalg.norm(u)
    v = np.cross(u, n)
    if np.dot(np.cross(u, v), n) < 0:
        v = -v
    return n, u, v


def _fresnel(cosi, eta):  # exact unpolarised, eta = n_t / n_i, cosi >= 0
    sint2 = (1 - cosi ** 2) / eta ** 2
    tir = sint2 >= 1
    cost = np.sqrt(np.clip(1 - sint2, 0, 1))
    with np.errstate(invalid="ignore", divide="ignore"):  # 0/0 only at grazing TIR
        rs = (cosi - eta * cost) / (cosi + eta * cost)
        rp = (eta * cosi - cost) / (eta * cosi + cost)
    return np.where(tir, 1.0, 0.5 * (rs * rs + rp * rp)), cost, tir


def _analytic_br_over_tl(ss: int = 4, depth: int = 10) -> float:
    n, u, v = _lamp_frame()

    def hit_lamp(o, d):
        den = d @ n
        t = ((_LAMP_C - o) * n).sum(-1) / np.where(np.abs(den) < 1e-12, 1e-12, den)
        p = o + t[:, None] * d - _LAMP_C
        return ((den < 0) & (t > 0) & (np.abs(p @ u) <= 1.5) & (np.abs(p @ v) <= 1.5)).astype(float)

    def trace(o, d):
        b = (o * d).sum(-1); disc = b * b - ((o * o).sum(-1) - 1)
        hit = (disc > 0) & (-b - np.sqrt(np.maximum(disc, 0)) > 0)
        t = np.where(hit, -b - np.sqrt(np.maximum(disc, 0)), 0.0)
        P = o + t[:, None] * d
        Nn = P / np.linalg.norm(P, axis=-1, keepdims=True)
        cosi = np.clip(-(d * Nn).sum(-1), 0, 1)
        F, cost, _ = _fresnel(cosi, _ETA)
        res = hit * F * hit_lamp(P + 1e-6 * Nn, d + 2 * cosi[:, None] * Nn)
        dirr = d / _ETA + (cosi / _ETA - cost)[:, None] * Nn
        w = hit * (1 - F); pos = P
        for _ in range(depth):
            b = (pos * dirr).sum(-1)
            t = -b + np.sqrt(np.maximum(b * b - ((pos * pos).sum(-1) - 1), 0))
            Q = pos + t[:, None] * dirr
            Nq = Q / np.linalg.norm(Q, axis=-1, keepdims=True)
            ci = np.clip((dirr * Nq).sum(-1), 0, 1)
            F, cost, tir = _fresnel(ci, 1 / _ETA)
            out = dirr * _ETA + (-ci * _ETA + cost)[:, None] * Nq
            res += w * (1 - F) * np.where(tir, 0, hit_lamp(Q + 1e-6 * Nq, out))
            dirr = dirr - 2 * ci[:, None] * Nq; pos = Q; w = w * F
        return res

    cam = np.array([0, 0, 5.0])
    th = np.tan(np.radians(30) / 2)
    img = np.zeros((_N, _N))
    jj, ii = np.meshgrid(np.arange(_N), np.arange(_N))
    for sy in range(ss):
        for sx in range(ss):
            x = (2 * (jj + (sx + .5) / ss) / _N - 1) * th
            y = (1 - 2 * (ii + (sy + .5) / ss) / _N) * th
            d = np.stack([x, y, -np.ones_like(x)], -1)
            d /= np.linalg.norm(d, axis=-1, keepdims=True)
            img += trace(np.broadcast_to(cam, (_N * _N, 3)), d.reshape(-1, 3)).reshape(_N, _N)
    h = _N // 2
    return float(img[h:, h:].mean() / img[:h, :h].mean())


def _render_br_over_tl(*, use_gpu: bool, spp: int = 512) -> float:
    _, u, v = _lamp_frame()
    r = astroray.Renderer()
    if use_gpu:
        r.set_use_gpu(True)
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)
    r.set_background_color([0.0, 0.0, 0.0])
    g = r.create_material("principled", [1.0, 1.0, 1.0],
                          {"transmission_weight": 1.0, "ior": _ETA, "roughness": 0.0})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, g)
    r.add_area_light_dedicated(list(_LAMP_C), list(u), list(v), 3.0, 3.0, "RECTANGLE",
                               {"mode": "rgb", "color": [1, 1, 1]}, 300.0)
    r.setup_camera(look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=30.0,
                   aspect_ratio=1.0, aperture=0.0, focus_dist=5.0, width=_N, height=_N)
    r.set_seed(11)
    img = np.asarray(r.render(spp, 16, None, False), dtype=np.float32).reshape(_N, _N, 3).mean(-1)
    h = _N // 2
    return float(img[h:, h:].mean() / img[:h, :h].mean())


def _furnace_rim(*, use_gpu: bool, ior: float, spp: int = 128) -> float:
    r = astroray.Renderer()
    if use_gpu:
        r.set_use_gpu(True)
    r.set_background_color([1.0, 1.0, 1.0])
    g = r.create_material("principled", [1.0, 1.0, 1.0],
                          {"transmission_weight": 1.0, "ior": ior, "roughness": 0.0})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, g)
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 80, 80)
    r.set_seed(7)
    img = np.asarray(r.render(spp, 32, None, False), dtype=np.float32).reshape(80, 80, 3)
    yy, xx = np.mgrid[:80, :80]
    rad = np.hypot(yy - 39.5, xx - 39.5)
    return float(img[(rad > 20) & (rad < 26)].mean())


def _gpu_or_skip():
    if not astroray.__features__.get("cuda", False):
        pytest.skip("CUDA feature not in this build")
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
def test_smooth_glass_internal_reflection_matches_analytic(use_gpu):
    if use_gpu:
        _gpu_or_skip()
    want = _analytic_br_over_tl()
    got = _render_br_over_tl(use_gpu=use_gpu)
    # Before #1112: 5.28 / 9.44 = 0.56 (Schlick at the incident angle).
    assert abs(got / want - 1.0) < 0.10, (
        f"internal-reflection spot BR/TL {got:.3f} vs analytic {want:.3f}")


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
@pytest.mark.parametrize("ior", [1.33, 1.5, 1.8])
def test_smooth_glass_furnace_rim(use_gpu, ior):
    # Regression guard only (blind to the split probability, see module doc).
    if use_gpu:
        _gpu_or_skip()
    v = _furnace_rim(use_gpu=use_gpu, ior=ior)
    assert 0.97 <= v <= 1.03, f"smooth principled glass ior={ior} furnace rim = {v:.4f}"
