"""pkg281: BlackHole honours `spin` (Kerr geodesics, CPU).

Renders the gr-kerr-94-faceon geometry (camera at 48 M on +z, spin axis +y, so
the view is exactly equatorial) as a capture mask and checks the horizontal
shadow edges against the analytic equatorial critical impact parameters
(Bardeen 1973; Chandrasekhar 1983 §63): a=0.94 -> 2.64 M prograde / 6.90 M
retrograde, a=0 -> 3*sqrt(3) M. Before pkg281 the engine ignored spin and
rendered both edges at ~5.2 M. The prograde (flattened) edge lies on image
right (+x), matching GYOTO 2.0.2 in the pkg280 Phase 3 comparison.
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

N = 256
DIST_M = 48.0  # camera 12 world units, r_obs_M=20 over influence radius 5
FOCAL_PX = (N / 2) / math.tan(math.radians(22.5))


def _mask(spin: float) -> np.ndarray:
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_seed(17)
    r.set_adaptive_sampling(False)
    r.setup_camera([0.0, 0.0, 12.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   45.0, 1.0, 0.0, 12.0, N, N)
    r.add_black_hole([0.0, 0.0, 0.0], 4.0e6, 5.0, {
        "spin": spin, "disk_outer": 18.0, "accretion_rate": 0.0,
        "inclination": 78.0, "enable_adaf": False, "r_obs_M": 20.0})
    img = np.asarray(r.render(4, 4, None, False), dtype=np.float32).mean(2)
    return img < 0.5 * float(np.median(img))


def _edges(mask: np.ndarray) -> tuple[float, float]:
    """Left/right shadow half-widths (px) along the central rows."""
    c = N // 2
    row = mask[c - 3:c + 3, :].mean(0) >= 0.5
    left = next(k for k in range(c - 1, -1, -1) if not row[k])
    right = next(k for k in range(c, N) if not row[k])
    return (c - left - 0.5), (right - c + 0.5)


def _px(b_M: float) -> float:
    return FOCAL_PX * b_M / DIST_M


def test_spin_094_matches_bardeen_equatorial_edges():
    left, right = _edges(_mask(0.94))
    assert right == pytest.approx(_px(2.64), abs=2.0), (left, right)
    assert left == pytest.approx(_px(6.90), abs=2.0), (left, right)


def _polar_radius_M(a: float) -> float:
    """Shadow radius for an on-axis observer (Chandrasekhar 1983 §63).

    Only L_z = 0 photons reach the axis: the spherical photon orbit with
    lambda = 0 solves r^3 - 3r^2 + a^2 r + a^2 = 0 (M=1), and the critical
    curve is a circle of radius sqrt(eta + a^2),
    eta = r^3 (4 Delta - r (r-1)^2) / (a^2 (r-1)^2).
    """
    r = 3.0
    for _ in range(60):  # Newton from the a=0 root
        f = r**3 - 3 * r**2 + a * a * r + a * a
        r -= f / (3 * r**2 - 6 * r + a * a)
    delta = r * r - 2 * r + a * a
    eta = r**3 * (4 * delta - r * (r - 1) ** 2) / (a * a * (r - 1) ** 2)
    return math.sqrt(eta + a * a)


def test_polar_observer_circular_bardeen_radius():
    n = 512
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_seed(17)
    r.set_adaptive_sampling(False)
    # Camera on the spin axis (+y), 48 M out; the central ray runs along theta=0.
    r.setup_camera([0.0, 12.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 1.0],
                   45.0, 1.0, 0.0, 12.0, n, n)
    r.add_black_hole([0.0, 0.0, 0.0], 4.0e6, 5.0, {
        "spin": 0.94, "disk_outer": 18.0, "accretion_rate": 0.0,
        "inclination": 0.0, "enable_adaf": False, "r_obs_M": 20.0})
    img = np.asarray(r.render(4, 4, None, False), dtype=np.float32)
    assert np.isfinite(img).all()
    lum = img.mean(2)
    mask = lum < 0.5 * float(np.median(lum))

    focal = (n / 2) / math.tan(math.radians(22.5))
    expected = focal * _polar_radius_M(0.94) / DIST_M        # ~62.9 px
    schw = focal * 3.0 * math.sqrt(3.0) / DIST_M             # ~66.9 px
    yy, xx = np.mgrid[0:n, 0:n] + 0.5
    rad = np.hypot(xx - n / 2, yy - n / 2)
    # Filled disc of the analytic radius: no pole streaks inside or just
    # outside. The annulus stops at 70 px: a faint dotted ring at ~74-77 px
    # predates pkg281 (present at a=0 on the old build; pkg280 side note).
    assert mask[rad < expected - 1.5].all()
    assert not mask[(rad > expected + 1.5) & (rad < 70.0)].any()
    # Pole streak check: the central row/column (theta ~ 0 rays) stay lit
    # beyond 70 px out to the frame edge, apart from that ring.
    ring = (rad > 72.0) & (rad < 79.0)
    for line in (mask[n // 2 - 1:n // 2 + 1, :], mask[:, n // 2 - 1:n // 2 + 1].T):
        far = (rad[n // 2 - 1:n // 2 + 1, :] > 70.0) & ~ring[n // 2 - 1:n // 2 + 1, :]
        assert not line[far].any()
    # Area-equivalent radius: tighter than the 4 px gap to Schwarzschild.
    r_eq = math.sqrt(mask[rad < 70.0].sum() / math.pi)
    assert r_eq == pytest.approx(expected, abs=1.0), (r_eq, expected, schw)


def _disk_flux(spin: float) -> float:
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(17)
    r.set_adaptive_sampling(False)
    r.setup_camera([0.0, 0.0, 12.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   45.0, 1.0, 0.0, 12.0, 96, 96)
    r.add_black_hole([0.0, 0.0, 0.0], 4.0e6, 5.0, {
        "spin": spin, "disk_outer": 18.0, "accretion_rate": 1.0,
        "inclination": 78.0, "enable_adaf": False, "r_obs_M": 20.0})
    return float(np.asarray(r.render(4, 4, None, False), dtype=np.float32).sum())


def test_spin_keeps_thin_disk_emission():
    # The Schwarzschild-formula disk fed a Kerr ISCO (<3M) lost all flux.
    assert _disk_flux(0.94) > 0.5 * _disk_flux(0.0)


def test_spin_zero_unchanged_schwarzschild():
    left, right = _edges(_mask(0.0))
    b = 3.0 * math.sqrt(3.0)
    assert left == pytest.approx(_px(b), abs=2.0)
    assert right == pytest.approx(_px(b), abs=2.0)
