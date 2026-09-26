"""#896: the GR continuation ray starts at the geodesic's exit point.

The path tracer used to respawn the escaped ray from the influence-sphere ENTRY
point. Rays leaving near-tangent to the sphere there clipped it again, bounced
between passes until max depth ran out, and rendered a dotted dark ring at
~74-78 px (512^2, gr-kerr-94-faceon geometry). Check: every dark pixel of a
capture mask (white background, no disk emission, bank depth 5) lies inside the
analytic shadow (Bardeen critical curve; Chandrasekhar 1983 §63), and the
shadow itself is filled. a=0 and 0.94, equatorial and polar observers.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

N = 512
DIST_M = 48.0  # camera 12 world units, r_obs_M = 20 over influence radius 5
FOCAL_PX = (N / 2) / math.tan(math.radians(22.5))


def _mask(spin: float, polar: bool) -> np.ndarray:
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_seed(17)
    r.set_adaptive_sampling(False)
    if polar:
        r.setup_camera([0.0, 12.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 1.0],
                       45.0, 1.0, 0.0, 12.0, N, N)
    else:
        r.setup_camera([0.0, 0.0, 12.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                       45.0, 1.0, 0.0, 12.0, N, N)
    r.add_black_hole([0.0, 0.0, 0.0], 4.0e6, 5.0, {
        "spin": spin, "disk_outer": 18.0, "accretion_rate": 0.0,
        "inclination": 78.0, "enable_adaf": False, "r_obs_M": 20.0})
    lum = np.asarray(r.render(4, 5, None, False), dtype=np.float32).mean(2)
    return lum < 0.5 * float(np.median(lum))


def _critical_curve(a: float, polar: bool) -> np.ndarray:
    """Shadow boundary (x right, y up) in M for an observer at infinity."""
    if a == 0.0 or polar:
        if a == 0.0:
            radius = 3.0 * math.sqrt(3.0)
        else:  # L_z = 0 spherical photon orbit: r^3 - 3r^2 + a^2 r + a^2 = 0
            rr = 3.0
            for _ in range(60):
                rr -= (rr**3 - 3 * rr**2 + a * a * rr + a * a) / (3 * rr**2 - 6 * rr + a * a)
            d = rr * rr - 2 * rr + a * a
            radius = math.sqrt(rr**3 * (4 * d - rr * (rr - 1) ** 2) / (a * a * (rr - 1) ** 2) + a * a)
        t = np.linspace(0.0, 2.0 * math.pi, 721)
        return np.stack([radius * np.cos(t), radius * np.sin(t)], 1)
    # Equatorial observer: alpha = xi (prograde edge on image right, as GYOTO),
    # beta = +-sqrt(eta) over the spherical photon orbits with eta >= 0.
    r_pro = 2.0 * (1.0 + math.cos(2.0 / 3.0 * math.acos(-a)))
    r_ret = 2.0 * (1.0 + math.cos(2.0 / 3.0 * math.acos(a)))
    rr = np.linspace(r_pro, r_ret, 4001)
    xi = (rr**2 * (3 - rr) - a * a * (rr + 1)) / (a * (rr - 1))
    eta = np.maximum(rr**3 * (4 * a * a - rr * (rr - 3) ** 2) / (a * a * (rr - 1) ** 2), 0.0)
    top = np.stack([xi, np.sqrt(eta)], 1)
    return np.concatenate([top, top[::-1] * [1.0, -1.0]])


def _inside(poly: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Even-odd point-in-polygon."""
    inside = np.zeros(x.shape, dtype=bool)
    px, py = poly[:, 0], poly[:, 1]
    for i in range(len(poly)):
        x0, y0, x1, y1 = px[i - 1], py[i - 1], px[i], py[i]
        cross = (y0 > y) != (y1 > y)
        xint = x0 + (y - y0) * (x1 - x0) / np.where(y1 != y0, y1 - y0, 1.0)
        inside ^= cross & (x < xint)
    return inside


@pytest.mark.parametrize("polar", [False, True], ids=["equatorial", "polar"])
@pytest.mark.parametrize("spin", [0.0, 0.94])
def test_no_dark_pixels_outside_analytic_shadow(spin, polar):
    mask = _mask(spin, polar)
    curve = _critical_curve(spin, polar) * FOCAL_PX / DIST_M
    yy, xx = np.mgrid[0:N, 0:N] + 0.5
    x, y = xx - N / 2, N / 2 - yy
    outer = _inside(curve * 1.04, x, y)   # +1.4..3.6 px edge tolerance
    inner = _inside(curve * 0.96, x, y)
    stray = mask & ~outer  # includes the x=0 spin-axis column (#897)
    assert stray.sum() == 0, (
        f"{int(stray.sum())} dark px outside the shadow, radii "
        f"{np.unique(np.hypot(x, y)[stray].round())[:12]}")
    assert mask[inner].all(), f"{int((~mask[inner]).sum())} lit px inside the shadow"
