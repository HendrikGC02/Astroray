"""pkg294 (#922): full-spread rectangle lamps are sampled in solid angle.

Cycles draws a rectangular area light with the spherical-rectangle map of
Urena, Fajardo & King 2013 (kernel/light/area.h::area_light_rect_sample) for
every non-segment sample and lamp-hit pdf; Astroray drew it uniformly over the
area. Both are unbiased; the solid-angle draw removes the r^2/cos pdf variation,
which dominates for points close to a large lamp.

Control: the same lamp with a half-spread just below pi/2 keeps the
area-uniform draw (the spread-clamped rectangle is not ported), so the
variance ratio fails (about 1) before the change and passes after it. The
means of both legs must agree (the spread attenuation at 89.99 deg is ~1).
NEE on/off and analytic gates for the same lamp: test_issue883 (area kind)
and test_925/929 (box, fog).
"""
import math

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

astroray = pytest.importorskip("astroray")

_RES = 16
_SEEDS = tuple(range(1, 25))
_FULL = math.pi / 2.0          # Blender spread 180 deg (binding default)
_AREA = 1.5707                 # just below: area-uniform control


def _render(spread, seed, spp, gpu=False):
    r = astroray.Renderer()
    if gpu:
        try:
            r.set_use_gpu(True)
        except Exception as e:  # noqa: BLE001 - CPU-only build
            pytest.skip("GPU unavailable: %s" % e)
        if not getattr(r, "gpu_available", False):
            pytest.skip("gpu_available is False")
    elif hasattr(r, "set_use_gpu"):
        r.set_use_gpu(False)
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)
    r.set_background_color([0.0, 0.0, 0.0])
    # Isotropic scattering slab right under a large down-facing lamp.
    r.add_homogeneous_medium([-1, -1, 0], [1, 1, 1], 2.0, [0.9, 0.9, 0.9],
                             [0.0, 0.0, 0.0], 0.0)
    r.add_area_light_dedicated([0, 0, 1.02], [0, 1, 0], [1, 0, 0], 3.0, 3.0, "RECTANGLE",
                               {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 50.0, spread)
    r.setup_camera([0, -5, 0.5], [0, 0, 0.5], [0, 0, 1], 22.0, 1.0, 0.0, 5.0, _RES, _RES)
    r.set_seed(seed)
    img = np.asarray(r.render(spp, 8, None, False), dtype=np.float64)
    return img.reshape(_RES, _RES, 3).mean(-1)


def _leg(spread, spp, gpu=False):
    st = np.stack([_render(spread, s, spp, gpu) for s in _SEEDS])
    m = st.mean(0)
    mask = m > 0.25 * m.max()
    rel_var = float((st.var(0, ddof=1)[mask] / m[mask] ** 2).mean())
    seed_means = st[:, mask].mean(1)
    return float(seed_means.mean()), float(seed_means.std(ddof=1) / math.sqrt(len(_SEEDS))), rel_var


def _check(gpu):
    m_sa, se_sa, v_sa = _leg(_FULL, 4, gpu)
    m_ar, se_ar, v_ar = _leg(_AREA, 4, gpu)
    assert abs(m_sa - m_ar) <= 4.0 * math.hypot(se_sa, se_ar) + 0.005 * m_ar, (
        f"means differ: solid-angle {m_sa:.5f}+-{se_sa:.5f} vs area {m_ar:.5f}+-{se_ar:.5f}")
    assert v_sa < 0.6 * v_ar, (
        f"solid-angle draw should cut per-pixel variance: relVar {v_sa:.4f} vs area {v_ar:.4f} "
        f"(ratio {v_sa / v_ar:.3f})")


@pytest.mark.cpu
def test_pkg294_rect_solid_angle_draw_cpu():
    _check(False)


@pytest.mark.gpu
def test_pkg294_rect_solid_angle_draw_gpu():
    if not getattr(astroray, "__features__", {}).get("cuda", False):
        pytest.skip("CUDA build required")
    _check(True)


# ---------------------------------------------------------------------------
# Deterministic checks of the shared map and the CPU AreaLight.
# ---------------------------------------------------------------------------
_C = (0.0, 0.0, 1.0)
_X, _Y = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)      # x cross y = +z: the lamp faces +z
_W, _H = 1.2, 0.7
_POSES = ((0.0, 0.0, 2.0), (0.3, -0.2, 1.3), (2.0, 1.5, 1.6), (-0.1, 0.05, 1.05),
          (5.0, -4.0, 9.0))


def _tri_solid_angle(p, a, b, c):
    """Van Oosterom & Strackee 1983 solid angle of triangle abc seen from p."""
    r1, r2, r3 = (np.asarray(v, float) - np.asarray(p, float) for v in (a, b, c))
    l1, l2, l3 = (np.linalg.norm(v) for v in (r1, r2, r3))
    num = abs(np.dot(r1, np.cross(r2, r3)))
    den = l1 * l2 * l3 + np.dot(r1, r2) * l3 + np.dot(r1, r3) * l2 + np.dot(r2, r3) * l1
    return 2.0 * math.atan2(num, den)


def _rect_corners():
    c, x, y = (np.asarray(v, float) for v in (_C, _X, _Y))
    hx, hy = 0.5 * _W * x, 0.5 * _H * y
    return c - hx - hy, c + hx - hy, c + hx + hy, c - hx + hy


def _analytic_omega(p):
    a, b, c, d = _rect_corners()
    return _tri_solid_angle(p, a, b, c) + _tri_solid_angle(p, a, c, d)


@pytest.mark.cpu
@pytest.mark.parametrize("pose", _POSES)
def test_sphrect_pdf_is_inverse_solid_angle(pose):
    pdf, _ = astroray._sphrect_sample(pose, _C, _X, _W, _Y, _H, 0.5, 0.5)
    omega = _analytic_omega(pose)
    assert pdf > 0.0 and abs(1.0 / pdf / omega - 1.0) < 0.005, (pose, 1.0 / pdf, omega)


@pytest.mark.cpu
@pytest.mark.parametrize("pose", _POSES[:3])
def test_sphrect_draw_is_uniform_in_solid_angle(pose):
    """Area measure: bin the drawn points over a 4x4 grid of sub-rectangles;
    each bin's share must equal its own solid angle over the total."""
    rng = np.random.default_rng(7)
    n, k = 40000, 4
    counts = np.zeros((k, k))
    c, x, y = np.asarray(_C), np.asarray(_X), np.asarray(_Y)
    for u1, u2 in rng.random((n, 2)):
        pdf, q = astroray._sphrect_sample(pose, _C, _X, _W, _Y, _H, float(u1), float(u2))
        assert pdf > 0.0
        lu = (np.dot(np.asarray(q) - c, x) / _W + 0.5) * k
        lv = (np.dot(np.asarray(q) - c, y) / _H + 0.5) * k
        counts[min(int(lu), k - 1), min(int(lv), k - 1)] += 1
    a0 = c - 0.5 * _W * x - 0.5 * _H * y
    omega = _analytic_omega(pose)
    ex, ey = (_W / k) * x, (_H / k) * y
    for i in range(k):
        for j in range(k):
            o = a0 + i * ex + j * ey
            w = (_tri_solid_angle(pose, o, o + ex, o + ex + ey)
                 + _tri_solid_angle(pose, o, o + ex + ey, o + ey)) / omega
            sigma = math.sqrt(n * w * (1 - w))
            assert abs(counts[i, j] - n * w) <= 4.0 * sigma + 1.0, (i, j, counts[i, j], n * w)


@pytest.mark.cpu
@pytest.mark.parametrize("pose", _POSES)
def test_area_light_draw_pdf_equals_lamp_hit_pdf(pose):
    rows = np.asarray(astroray._area_light_probe(_C, _X, _Y, _W, _H, _FULL, pose, 256, 3))
    q, pdf, pdf_li, hit_t, hit = rows[:, :3], rows[:, 3], rows[:, 4], rows[:, 5], rows[:, 6]
    assert np.all(pdf > 0.0) and np.all(np.isfinite(pdf))
    np.testing.assert_allclose(pdf_li, pdf, rtol=1e-4)         # NEE pdf == reverse pdf
    np.testing.assert_allclose(1.0 / pdf, _analytic_omega(pose), rtol=0.005)
    assert np.all(hit == 1.0)                                   # the direction hits the lamp
    np.testing.assert_allclose(hit_t, np.linalg.norm(q - np.asarray(pose), axis=1), rtol=1e-4)
    local = q - np.asarray(_C)
    assert np.all(np.abs(local[:, 2]) < 1e-5)                   # on the lamp plane
    assert np.all(np.abs(local[:, 0]) <= 0.5 * _W + 1e-5)
    assert np.all(np.abs(local[:, 1]) <= 0.5 * _H + 1e-5)


@pytest.mark.cpu
def test_area_light_is_one_sided():
    rows = np.asarray(astroray._area_light_probe(_C, _X, _Y, _W, _H, _FULL, (0.2, 0.1, 0.4),
                                                  64, 5))
    assert np.all(rows[:, 3] == 0.0) and np.all(np.isfinite(rows[:, :7]))


@pytest.mark.cpu
def test_segment_anchor_is_area_uniform():
    rows = np.asarray(astroray._area_light_probe(_C, _X, _Y, _W, _H, _FULL, (0.3, -0.2, 1.3),
                                                  20000, 11))
    local = rows[:, 7:10] - np.asarray(_C)
    assert np.all(np.abs(local[:, 2]) < 1e-5)
    assert np.all(np.abs(local[:, 0]) <= 0.5 * _W) and np.all(np.abs(local[:, 1]) <= 0.5 * _H)
    # Uniform over the area (Cycles area_light_eval<true>): moments of U(-L/2, L/2),
    # unlike the solid-angle draws, which crowd toward the side nearest the pose.
    np.testing.assert_allclose(local[:, :2].mean(0), 0.0, atol=0.01)
    np.testing.assert_allclose(local[:, :2].var(0), [_W * _W / 12, _H * _H / 12], rtol=0.03)
    draws = rows[:, :3] - np.asarray(_C)
    assert draws[:, 0].mean() > 0.02 and draws[:, 1].mean() < -0.01


@pytest.mark.cpu
@pytest.mark.parametrize("p", [(0.1, 0.1, 1.0), (0.6, 0.0, 1.0), (0.6, 0.35, 1.0),
                               (0.6, 0.35, 1.0 + 1e-9), (float("nan"), 0.0, 2.0)])
def test_sphrect_degenerate_on_plane_is_zero(p):
    for u in ((0.5, 0.5), (0.0, 0.0), (1.0, 1.0)):
        pdf, q = astroray._sphrect_sample(p, _C, _X, _W, _Y, _H, *u)
        assert pdf == 0.0, (p, u, pdf)
        assert np.all(np.isfinite(q))
    rows = np.asarray(astroray._area_light_probe(_C, _X, _Y, _W, _H, _FULL, p, 16, 1))
    assert np.all(rows[:, 3] == 0.0) and not np.any(np.isnan(rows[:, 3:7]))


@pytest.mark.cpu
@pytest.mark.parametrize("size,dist", [(1e-6, 1e3), (1e-3, 1e4), (1e-20, 1.0), (0.0, 1.0)])
def test_sphrect_tiny_lamp_is_finite(size, dist):
    for u in ((0.5, 0.5), (0.1, 0.9)):
        pdf, q = astroray._sphrect_sample((0.0, 0.0, 1.0 + dist), _C, _X, size, _Y, size, *u)
        assert pdf == 0.0 or (math.isfinite(pdf) and pdf > 0.0), (size, dist, pdf)
        assert np.all(np.isfinite(q))
        if pdf > 0.0:   # solid angle ~ area / dist^2 for a far, tiny lamp
            assert abs(pdf * size * size / dist ** 2 - 1.0) < 0.01


# ---------------------------------------------------------------------------
# Render leg: NEE draw pdf and lamp-hit pdf pair up (MIS weights sum to 1),
# pinned against Lambert's analytic irradiance under a large, close lamp.
# ---------------------------------------------------------------------------
def _floor_render(nee, seed, spp, gpu):
    from test_issue883_nee_near_light import _ALB, _block, _floor_points, _polygon_irradiance
    h, a, half, cam_h = 0.1, 1.0, 0.25, 3.0
    r = astroray.Renderer()
    if gpu:
        try:
            r.set_use_gpu(True)
        except Exception as e:  # noqa: BLE001 - CPU-only build
            pytest.skip("GPU unavailable: %s" % e)
        if not getattr(r, "gpu_available", False):
            pytest.skip("gpu_available is False")
    elif hasattr(r, "set_use_gpu"):
        r.set_use_gpu(False)
    r.set_background_color([0.0, 0.0, 0.0])
    floor = r.create_material("lambertian", [_ALB] * 3, {})
    r.add_triangle([-5, 0, -5], [5, 0, 5], [5, 0, -5], floor)
    r.add_triangle([-5, 0, -5], [-5, 0, 5], [5, 0, 5], floor)
    power = 2.0
    radiance = power / (math.pi * a * a)
    r.add_area_light_dedicated([0, h, 0], [1, 0, 0], [0, 0, 1], a, a, "RECTANGLE",
                               {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, power)
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)
    if not gpu:
        r.set_light_nee(nee)
    vfov = 2 * math.degrees(math.atan(half / cam_h))
    res = 32   # == test_issue883 _RES (its _floor_points/_block grid)
    r.setup_camera([0, cam_h, 0], [0, 0, 0], [0, 0, -1], vfov, 1.0, 0.0, cam_h, res, res)
    r.set_seed(seed)
    img = np.asarray(r.render(spp, 4, None, False), np.float64).reshape(res, res, 3)
    X, Z = _floor_points(half)
    q = a / 2
    E = radiance * _polygon_irradiance(X, Z, [[-q, h, -q], [q, h, -q], [q, h, q], [-q, h, q]])
    return float(img.mean()), float(_block(_ALB / math.pi * E).mean())


@pytest.mark.parametrize("gpu", [pytest.param(False, marks=pytest.mark.cpu),
                                 pytest.param(True, marks=pytest.mark.gpu)])
def test_large_close_lamp_nee_matches_analytic(gpu):
    if gpu and not getattr(astroray, "__features__", {}).get("cuda", False):
        pytest.skip("CUDA build required")
    runs = [_floor_render(True, s, 64, gpu) for s in (11, 12, 13)]
    ref = runs[0][1]
    on = float(np.mean([m for m, _ in runs]))
    assert abs(on / ref - 1.0) < 0.01, f"NEE on {on:.5f} vs analytic {ref:.5f}"
    if not gpu:
        off = float(np.mean([_floor_render(False, s, 1024, False)[0] for s in (11, 12, 13)]))
        assert abs(off / ref - 1.0) < 0.01, f"NEE off {off:.5f} vs analytic {ref:.5f}"
