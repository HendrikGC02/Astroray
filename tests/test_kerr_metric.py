"""pkg40 Kerr/Schwarzschild metric analytic gates."""

import math
import os
from pathlib import Path

import pytest

from runtime_setup import configure_test_imports

os.environ.setdefault(
    "ASTRORAY_BUILD_DIR",
    str(Path(__file__).resolve().parent.parent / "build" / "Release"),
)
configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")


def test_metric_registry_contains_kerr_and_schwarzschild():
    names = set(astroray.metric_registry_names())
    assert {"kerr", "schwarzschild"} <= names


def test_schwarzschild_isco_radius():
    # Bardeen, Press, Teukolsky 1972 ApJ 178, 347 gives r_ISCO = 6M for a=0.
    r_isco = astroray.metric_isco_radius("schwarzschild", {"M": 1.0})
    assert r_isco == pytest.approx(6.0, rel=1e-12, abs=1e-12)


def test_extreme_kerr_isco_radius():
    # Bardeen, Press, Teukolsky 1972 ApJ 178, 347 gives prograde r_ISCO ~= 1.237M for a=0.998M.
    r_isco = astroray.metric_isco_radius("kerr", {"M": 1.0, "a": 0.998})
    assert r_isco == pytest.approx(1.237, rel=5e-3)


def test_schwarzschild_photon_sphere_radius():
    # Bardeen, Press, Teukolsky 1972 ApJ 178, 347 gives r_ph = 3M for a=0.
    r_ph = astroray.metric_photon_sphere_radius(
        "schwarzschild", {"M": 1.0}, prograde=True
    )
    assert r_ph == pytest.approx(3.0, rel=1e-12, abs=1e-12)


def test_extreme_kerr_photon_sphere_radius():
    # Bardeen, Press, Teukolsky 1972 ApJ 178, 347 gives prograde r_ph ~= 1.073M for a=0.998M.
    r_ph = astroray.metric_photon_sphere_radius(
        "kerr", {"M": 1.0, "a": 0.998}, prograde=True
    )
    assert r_ph == pytest.approx(1.073, rel=5e-3)


def test_extreme_kerr_horizon_frame_dragging():
    # Bardeen, Press, Teukolsky 1972 ApJ 178, 347 sets the horizon angular velocity scale.
    omega_h = astroray.metric_horizon_angular_velocity("kerr", {"M": 1.0, "a": 0.998})
    assert omega_h == pytest.approx(0.4694, rel=1e-2)


def test_kerr_metric_components_are_boyer_lindquist():
    metric = "kerr"
    params = {"M": 1.0, "a": 0.998}
    r = 4.0
    theta = math.pi / 2.0
    u_t = [1.0, 0.0, 0.0, 0.0]
    u_phi = [0.0, 0.0, 0.0, 1.0]

    g_tt = astroray.metric_inner_product(metric, params, 0.0, r, theta, 0.0, u_t, u_t)
    g_tphi = astroray.metric_inner_product(metric, params, 0.0, r, theta, 0.0, u_t, u_phi)

    assert g_tt == pytest.approx(-(1.0 - 2.0 / r), rel=1e-6)
    assert g_tphi == pytest.approx(-2.0 * 0.998 / r, rel=1e-6)
