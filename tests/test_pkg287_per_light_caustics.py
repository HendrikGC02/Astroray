#!/usr/bin/env python
"""pkg287 — photon caustics are emitted per light with that light's geometry.

A glass ball (r 0.5) above a white floor is lit from 30 deg off vertical by a
sun, a spot, a point lamp or an area lamp. The photon-mapped caustic (photons
ON) must match a brute-force path-traced caustic (photons OFF, Cycles style)
in integrated flux (10 %) and centroid (2 px) over the caustic core. Each
caustic is isolated as (glass ball) - (black ball) at the same light.

References: point/spot lamps are delta (never hit by BSDF rays), so their path
traced twin is an isotropic emissive sphere (r 0.3) of equal intensity; the
equality is checked on the direct-lit floor. The sun uses a 0.2 rad disc and
the area lamp is 0.6 m so the brute-force reference converges: 16384 spp (the
spec's 4096 left the small-source caustic heavy-tailed and ~15 % low). The
point photon flux is also checked against an independent ball-lens ray trace
(Snell + exact Fresnel, numpy).
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

W, H = 128, 96
SPP_ON, SPP_REF = 64, 16384
D = (0.0, -math.cos(math.radians(30)), math.sin(math.radians(30)))  # light -> ball
C = (0.0, 1.0, 0.0)
R_BALL = 0.5
LP = tuple(C[i] - D[i] * 3.0 for i in range(3))                    # lamp position
WHITE = {"mode": "rgb", "color": [1.0, 1.0, 1.0]}
P_LAMP = 300.0          # point/spot power (W): intensity P / 4pi
R_EMIT = 0.3            # emissive-sphere stand-in for the delta lamps
KINDS = ("sun", "spot", "point", "area")


def _scene(kind, photons, black=False, gpu=False, sun_angle=0.2, reflective=True):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    ball = (r.create_material("lambertian", [0.0, 0.0, 0.0], {}) if black else
            r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5}))
    i = r.scene_object_count()
    r.add_sphere(list(C), R_BALL, ball)
    r.set_object_caustic_caster(i, True)
    floor = r.create_material("lambertian", [0.8] * 3, {})
    r.add_triangle([-6, 0, -6], [6, 0, 6], [6, 0, -6], floor)
    r.add_triangle([-6, 0, -6], [-6, 0, 6], [6, 0, 6], floor)
    if kind == "sun":
        r.add_sun_light_dedicated(list(D), sun_angle, WHITE, 3.0)
    elif kind == "area":
        r.add_area_light_dedicated(list(LP), [1.0, 0.0, 0.0], [0.0, D[2], -D[1]],
                                   0.6, 0.6, "rectangle", WHITE, 60.0)
    elif photons or gpu:
        if kind == "point":
            r.add_point_light(list(LP), WHITE, P_LAMP, 0.0)
        else:  # the ball (9.6 deg) sits inside the 25 deg inner cone
            r.add_spot_light_dedicated(list(LP), list(D), math.radians(25),
                                       math.radians(30), WHITE, P_LAMP, 0.0)
    else:
        L = P_LAMP / (4 * math.pi) / (math.pi * R_EMIT * R_EMIT)   # I = L pi r^2
        r.add_sphere(list(LP), R_EMIT, r.create_material("light", [1.0, 1.0, 1.0],
                                                         {"intensity": L}))
    r.set_use_refractive_caustics(True)
    r.set_use_reflective_caustics(reflective)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 16)
    r.set_integrator_param_float("caustic_boost", 1.0)
    if gpu:
        r.set_use_gpu(True)
        r.set_use_photon_caustics(photons)
    else:
        r.set_integrator_param_str("caustics", "photon_map" if photons else "none")
    r.setup_camera([0, 3.0, 3.5], [0, 0, 0.6], [0, 1, 0], 45.0, W / H, 0.0, 4.0, W, H)
    return r


def _lum(r, spp, seed=5):
    r.set_seed(seed)
    img = np.asarray(r.render(spp, 16, None, False), dtype=np.float32).reshape(H, W, 3)
    return 0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]


def _caustic(kind, photons, spp, gpu=False):
    return (_lum(_scene(kind, photons, gpu=gpu), spp)
            - _lum(_scene(kind, photons, black=True, gpu=gpu), min(spp, 256)))


def _box(a, k=2):
    p = np.pad(a, k, mode="edge")
    return sum(p[k + dy:k + dy + a.shape[0], k + dx:k + dx + a.shape[1]]
               for dy in range(-k, k + 1) for dx in range(-k, k + 1)) / (2 * k + 1) ** 2


def _core(c):
    """Caustic core: > 20 % of the smoothed peak on the floor, dilated 4 px."""
    s = _box(c)
    s[: int(H * 0.45)] = 0.0                     # the ball itself
    m = s > 0.2 * s.max()
    for _ in range(4):
        m = m | np.roll(m, 1, 0) | np.roll(m, -1, 0) | np.roll(m, 1, 1) | np.roll(m, -1, 1)
    return m


def _centroid(c, m):
    yy, xx = np.mgrid[:H, :W]
    w = np.clip(c, 0.0, None) * m
    return np.array([(w * xx).sum(), (w * yy).sum()]) / w.sum()


@pytest.mark.parametrize("kind", KINDS)
def test_cpu_photon_caustic_matches_path_traced(kind, test_results_dir):
    on = _caustic(kind, True, SPP_ON)
    ref = _caustic(kind, False, SPP_REF)
    from base_helpers import save_image
    both = np.concatenate([on, ref], axis=1)
    save_image(np.repeat(np.clip(both / max(float(np.percentile(on, 99.5)), 1e-6), 0, 1)[..., None],
                         3, axis=2),
               os.path.join(test_results_dir, f"pkg287_{kind}_photon_vs_pt.png"))
    m = _core(on)
    ratio = float(on[m].sum() / ref[m].sum())
    shift = float(np.linalg.norm(_centroid(on, m) - _centroid(ref, m)))
    print(f"\n[pkg287 {kind}] core px={int(m.sum())} flux photon/PT={ratio:.4f} "
          f"centroid shift={shift:.2f} px")
    assert abs(ratio - 1.0) <= 0.10
    assert shift <= 2.0


def test_delta_lamp_stand_in_has_equal_intensity():
    """The emissive sphere used as the point/spot reference emits the same
    intensity as the dedicated point lamp (direct-lit floor, no ball)."""
    a = _lum(_scene("point", True, black=True), 64)
    b = _lum(_scene("point", False, black=True), 256)
    ratio = float(a[70:].sum() / b[70:].sum())
    print(f"\n[pkg287] point / emissive-sphere direct floor = {ratio:.4f}")
    assert abs(ratio - 1.0) <= 0.02


def test_cpu_split_drops_path_traced_twin():
    """#909 CPU twin: with the photon map live, receiver -> ball -> sun paths are
    dropped (the gather carries them). A small bright sun made them fireflies
    (64-spp max ~700x the p99.9 before); reflections stay path traced, so they
    are off here."""
    imgs = [_lum(_scene("sun", True, sun_angle=0.01, reflective=False), 64, seed)
            for seed in (11, 29, 47, 83)]
    ref = float(np.percentile(np.mean(imgs, axis=0), 99.9))
    worst = max(float(i.max()) for i in imgs)
    print(f"\n[pkg287 CPU split] 64spp max={worst:.2f} p99.9={ref:.3f}")
    assert worst <= 4.0 * ref


def _ball_lens_oracle_flux(n_rays=2_000_000):
    """Independent ball-lens trace: point lamp -> ball (exact Fresnel twice) ->
    floor. Returns the Y-flux per unit Y of the lamp SPD."""
    rng = np.random.default_rng(1)
    c, lp = np.array(C), np.array(LP)
    dist = np.linalg.norm(c - lp)
    cmax = math.sqrt(1 - (R_BALL / dist) ** 2)
    w = (c - lp) / dist
    t1 = np.cross(w, [1.0, 0.0, 0.0]); t1 /= np.linalg.norm(t1)
    t2 = np.cross(w, t1)
    cz = 1 - rng.random(n_rays) * (1 - cmax)
    sz = np.sqrt(1 - cz * cz)
    ph = 2 * math.pi * rng.random(n_rays)
    d = np.outer(sz * np.cos(ph), t1) + np.outer(sz * np.sin(ph), t2) + np.outer(cz, w)

    def hit(o, d, inside):
        oc = o - c
        b = np.sum(oc * d, 1)
        disc = b * b - (np.sum(oc * oc, 1) - R_BALL ** 2)
        t = -b + (1.0 if inside else -1.0) * np.sqrt(np.maximum(disc, 0))
        return (disc > 0) & (t > 1e-6), t

    def fres_t(cosi, eta):
        sint = eta * np.sqrt(np.maximum(0, 1 - cosi ** 2))
        cost = np.sqrt(np.maximum(0, 1 - sint ** 2))
        rp = (cosi - eta * cost) / (cosi + eta * cost)
        rs = (eta * cosi - cost) / (eta * cosi + cost)
        return np.where(sint >= 1, 0.0, 1 - 0.5 * (rp ** 2 + rs ** 2))

    def refract(d, nrm, eta):
        cosi = -np.sum(d * nrm, 1)
        out = d * eta + nrm * (eta * cosi - np.sqrt(np.maximum(0, 1 - eta ** 2 * (1 - cosi ** 2)))
                               )[:, None]
        return out / np.linalg.norm(out, axis=1)[:, None], cosi

    ok1, t = hit(np.tile(lp, (n_rays, 1)), d, False)
    p1 = lp + d * t[:, None]
    d1, c1 = refract(d, (p1 - c) / R_BALL, 1 / 1.5)
    ok2, t = hit(p1 + d1 * 1e-5, d1, True)
    p2 = p1 + d1 * t[:, None]
    d2, c2 = refract(d1, -(p2 - c) / R_BALL, 1.5)
    T = fres_t(c1, 1 / 1.5) * fres_t(c2, 1.5)
    good = ok1 & ok2 & (d2[:, 1] < 0)
    return P_LAMP / (4 * math.pi) * 2 * math.pi * (1 - cmax) / n_rays * float(T[good].sum())


def test_point_photon_flux_matches_ball_lens_oracle():
    r = _scene("point", True)
    _lum(r, 1)
    flux = r.get_integrator_stats()["pm_flux_y"]
    # The rgb (1,1,1) illuminant has Y ~= 1, so the oracle's flux per unit Y
    # compares directly (the 380-720 nm photon band drops < 1 %).
    ref = _ball_lens_oracle_flux()
    print(f"\n[pkg287 point] photon flux Y={flux:.4f} oracle={ref:.4f} ratio={flux/ref:.4f}")
    assert abs(flux / ref - 1.0) <= 0.03


def _gpu_ok():
    return AVAILABLE and astroray.__features__.get("cuda", False) and astroray.Renderer().gpu_available


@pytest.mark.skipif(not _gpu_ok(), reason="CUDA GPU not available")
@pytest.mark.parametrize("kind", KINDS)
def test_gpu_photon_caustic_matches_cpu(kind, test_results_dir):
    g = _caustic(kind, True, SPP_ON, gpu=True)
    c = _caustic(kind, True, SPP_ON)
    from base_helpers import save_image
    save_image(np.repeat(np.clip(g / max(float(np.percentile(g, 99.5)), 1e-6), 0, 1)[..., None],
                         3, axis=2),
               os.path.join(test_results_dir, f"pkg287_{kind}_gpu.png"))
    m = _core(c)
    ratio = float(g[m].sum() / c[m].sum())
    shift = float(np.linalg.norm(_centroid(g, m) - _centroid(c, m)))
    print(f"\n[pkg287 {kind}] GPU/CPU core flux={ratio:.4f} centroid shift={shift:.2f} px")
    assert abs(ratio - 1.0) <= 0.05
    assert shift <= 2.0
