"""pkg288 (#915): a path continues through a hit dedicated lamp (Cycles
integrator_shade_light: add the lamp, re-intersect from t_lamp).

Before: a BSDF ray ended on the first lamp it hit while NEE shadow rays pass
through lamps, so with lamps in line NEE on != NEE off.

(a) two collinear area lamps above a white floor: NEE on == NEE off within 2 %
    per channel (point lamps are NEE-only in Astroray, pkg181, so the spec's
    "point lamps" are area lamps here).
(b) camera-visible sun disc over a coloured background: the disc pixels show
    disc + background (the ray continues to the env); a lit plane is unchanged
    by the disc's camera visibility.
(c) lamp between a mirror and the camera: the mirror shows the emissive wall
    behind the lamp through it.
"""
import math

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

astroray = pytest.importorskip("astroray")

_RES = 32


def _renderer(gpu, nee=True):
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
    r.set_light_nee(nee)
    return r


def _quad(r, a, b, c, d, mat):
    r.add_triangle(a, b, c, mat)
    r.add_triangle(a, c, d, mat)


def _render(r, spp, seed, depth=4):
    r.set_seed(seed)
    img = np.asarray(r.render(spp, depth, None, False), dtype=np.float64)
    return img.reshape(_RES, _RES, 3)


# --------------------------------------------------------------------------- #
# (a) two collinear lamps, NEE on vs off
# --------------------------------------------------------------------------- #
def _collinear(gpu, nee):
    r = _renderer(gpu, nee)
    r.set_background_color([0.0, 0.0, 0.0])
    white = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    _quad(r, [-6, 0, -6], [-6, 0, 6], [6, 0, 6], [6, 0, -6], white)
    em = lambda c: {"mode": "rgb", "color": c}
    # u x v = x x z = -y: both lamps face the floor; A is directly under B.
    r.add_area_light_dedicated([0, 2.0, 0], [1, 0, 0], [0, 0, 1], 1.2, 1.2,
                               "RECTANGLE", em([1.0, 0.2, 0.2]), 20.0)
    r.add_area_light_dedicated([0, 3.5, 0], [1, 0, 0], [0, 0, 1], 3.0, 3.0,
                               "RECTANGLE", em([0.2, 0.4, 1.0]), 60.0)
    r.setup_camera(look_from=[0, 1.0, 6.0], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=60.0,
                   aspect_ratio=1.0, aperture=0.0, focus_dist=6.0, width=_RES, height=_RES)
    return r


def _collinear_mean(gpu, nee, seeds=tuple(range(1, 17)), spp=512):
    # NEE off is the noisy leg: 16 x 512 spp puts its SEM near 0.25 %.
    return np.mean([_render(_collinear(gpu, nee), spp, s).mean(axis=(0, 1)) for s in seeds],
                   axis=0)


@pytest.mark.cpu
def test_pkg288a_collinear_lamps_cpu_nee_on_matches_off():
    on = _collinear_mean(False, True)
    off = _collinear_mean(False, False)
    np.testing.assert_allclose(on, off, rtol=0.02, err_msg=f"on={on} off={off}")


@pytest.mark.gpu
def test_pkg288a_collinear_lamps_gpu_matches_cpu():
    ref = _collinear_mean(False, False)
    for nee in (True, False):
        gpu = _collinear_mean(True, nee)
        np.testing.assert_allclose(gpu, ref, rtol=0.02,
                                   err_msg=f"nee={nee} gpu={gpu} cpu_off={ref}")


# --------------------------------------------------------------------------- #
# (b) camera-visible sun disc
# --------------------------------------------------------------------------- #
_SUN = math.radians(3.0)
_BG = [0.2, 0.3, 0.4]


def _sun(gpu, bg, camera_visible, plane):
    r = _renderer(gpu)
    r.set_background_color(bg)
    if plane:  # bottom rows of the frame: a sun-lit grey plane
        grey = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
        _quad(r, [-500, -1, 1], [500, -1, 1], [500, -1, -1000], [-500, -1, -1000], grey)
    else:
        grey = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
        r.add_sphere([0.0, 0.0, 1000.0], 1.0, grey)  # out of view; non-empty BVH
    toward = [0.0, math.sin(math.radians(2.0)), -math.cos(math.radians(2.0))]
    r.add_sun_light_dedicated([-t for t in toward], _SUN, {"mode": "rgb", "color": [1, 1, 1]},
                              0.002, 0, 0, camera_visible=camera_visible)
    r.setup_camera(look_from=[0, 0, 0], look_at=toward, vup=[0, 1, 0], vfov=8.0,
                   aspect_ratio=1.0, aperture=0.0, focus_dist=1.0, width=_RES, height=_RES)
    return r


def _check_sun(gpu):
    # Disc radius 1.5 deg = 6 px: the central r < 4 px disc is fully covered.
    # Sun radiance ~0.8 keeps its spectral noise small next to the background.
    spp = 1024
    lit = _render(_sun(gpu, _BG, True, False), spp, 1)
    dark = _render(_sun(gpu, [0.0, 0.0, 0.0], True, False), spp, 2)
    yy, xx = np.mgrid[0:_RES, 0:_RES] - (_RES - 1) / 2.0
    disc = xx * xx + yy * yy < 16.0
    assert dark[disc].mean() > 0.3, "sun disc not visible"
    # The ray continues past the disc to the background: lit - dark == bg.
    np.testing.assert_allclose((lit - dark)[disc].mean(axis=0), _BG, rtol=0.02)
    # A lit plane is unaffected by the disc's camera visibility.
    on = _render(_sun(gpu, _BG, True, True), 32, 1)
    off = _render(_sun(gpu, _BG, False, True), 32, 1)
    rows = slice(_RES - 6, _RES)  # plane only (disc spans rows 10-22)
    np.testing.assert_allclose(on[rows].mean(axis=(0, 1)), off[rows].mean(axis=(0, 1)),
                               rtol=0.02)


@pytest.mark.cpu
def test_pkg288b_sun_disc_continues_cpu():
    _check_sun(False)


@pytest.mark.gpu
def test_pkg288b_sun_disc_continues_gpu():
    _check_sun(True)


# --------------------------------------------------------------------------- #
# (c) lamp between a mirror and the camera
# --------------------------------------------------------------------------- #
def _mirror(gpu):
    r = _renderer(gpu)
    r.set_background_color([0.0, 0.0, 0.0])
    mirror = r.create_material("mirror", [1.0, 1.0, 1.0], {})
    _quad(r, [-4, -4, 0], [4, -4, 0], [4, 4, 0], [-4, 4, 0], mirror)
    wall = r.create_material("light", [0.0, 1.0, 0.0], {"intensity": 1.0})
    _quad(r, [-20, -20, 9], [-20, 20, 9], [20, 20, 9], [20, -20, 9], wall)
    # u x v = x x (-y) = -z: the lamp faces the mirror (its back to the camera).
    r.add_area_light_dedicated([0, 0, 2.5], [1, 0, 0], [0, -1, 0], 1.0, 1.0,
                               "RECTANGLE", {"mode": "rgb", "color": [1.0, 0.0, 0.0]}, 20.0)
    r.setup_camera(look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=40.0,
                   aspect_ratio=1.0, aperture=0.0, focus_dist=5.0, width=_RES, height=_RES)
    return r


def _check_mirror(gpu):
    img = _render(_mirror(gpu), 64, 1)
    lamp = img[..., 0] > 0.5 * img[..., 0].max()
    assert 4 <= lamp.sum() < lamp.size // 2, "lamp reflection not isolated"
    g_lamp = img[..., 1][lamp].mean()
    g_rest = img[..., 1][~lamp].mean()
    # The wall behind the lamp shows through it at full strength.
    assert g_rest > 0.5
    assert abs(g_lamp / g_rest - 1.0) < 0.02, f"green lamp={g_lamp} rest={g_rest}"


@pytest.mark.cpu
def test_pkg288c_mirror_sees_past_lamp_cpu():
    _check_mirror(False)


@pytest.mark.gpu
def test_pkg288c_mirror_sees_past_lamp_gpu():
    _check_mirror(True)
