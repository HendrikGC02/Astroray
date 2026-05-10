"""pkg42 synchrotron emission plugin tests.

References:
- Pandya, Zhang, Chandra & Gammie 2016, ApJ 822, 34, Appendix A.
- Mościbrodzka & Gammie 2018 ipole, BSD-3, cited for invariant-transfer
  plumbing and the vendored symphony wrapper shape.
- RAPTOR/GYOTO are cross-validation references only; no GPL/CeCILL code is
  mirrored here.
"""

from __future__ import annotations

import math
from pathlib import Path
import sys

import numpy as np
import pytest

import astroray

SCENE_DIR = Path(__file__).resolve().parent / "scenes"
if str(SCENE_DIR) not in sys.path:
    sys.path.insert(0, str(SCENE_DIR))


def test_emission_registry_contains_synchrotron_jet():
    assert "synchrotron_jet" in astroray.emission_registry_names()


def test_thermal_emissivity_x1_matches_pandya_coefficient():
    B = 1.0
    n_e = 1.0
    T_e = 1.0e10
    theta = math.pi / 2.0
    theta_e = 1.380649e-16 * T_e / (9.1093837015e-28 * (2.99792458e10 ** 2))
    nu_c = astroray.synchrotron_cyclotron_frequency(B)
    nu_s = (2.0 / 9.0) * nu_c * theta_e * theta_e
    j = astroray.synchrotron_thermal_emissivity(nu_s, n_e, T_e, B, theta)
    prefactor = n_e * (4.803204712570263e-10 ** 2) * nu_c / 2.99792458e10
    coeff = j / prefactor
    expected = (math.sqrt(2.0) * math.pi / 27.0) * (
        1.0 + 2.0 ** (11.0 / 12.0)
    ) ** 2 * math.exp(-1.0)
    assert coeff == pytest.approx(expected, rel=1e-12)
    assert j == pytest.approx(1.083e-23, rel=0.02)


def test_powerlaw_spectral_slope_matches_pandya_fit():
    p = 2.5
    nu_c = astroray.synchrotron_cyclotron_frequency(1.0)
    nu1 = 10.0 * nu_c
    nu2 = 100.0 * nu_c
    j1 = astroray.synchrotron_powerlaw_emissivity(nu1, 1.0, 1.0, math.pi / 2, p, 1.0, 1.0e6)
    j2 = astroray.synchrotron_powerlaw_emissivity(nu2, 1.0, 1.0, math.pi / 2, p, 1.0, 1.0e6)
    slope = math.log(j1 / j2) / math.log(nu1 / nu2)
    assert slope == pytest.approx(-(p - 1.0) / 2.0, abs=1e-3)


def test_powerlaw_absorptivity_positive_and_steeper_than_emissivity():
    p = 2.5
    nu_c = astroray.synchrotron_cyclotron_frequency(3.0)
    nu1 = 10.0 * nu_c
    nu2 = 100.0 * nu_c
    a1 = astroray.synchrotron_powerlaw_absorptivity(nu1, 2.0, 3.0, math.pi / 2, p, 1.0, 1.0e6)
    a2 = astroray.synchrotron_powerlaw_absorptivity(nu2, 2.0, 3.0, math.pi / 2, p, 1.0, 1.0e6)
    assert a1 > 0.0 and a2 > 0.0
    slope = math.log(a1 / a2) / math.log(nu1 / nu2)
    assert slope == pytest.approx(-(p + 4.0) / 2.0, abs=1e-3)


def test_jet_cone_geometry_accepts_bipolar_axis_and_rejects_equator():
    params = {"half_angle_degrees": 5.0, "r_base": 6.0, "r_max": 50.0}
    assert astroray.synchrotron_jet_contains(params, [0.0, 10.0, 0.0])
    assert astroray.synchrotron_jet_contains(params, [0.0, -10.0, 0.0])
    assert not astroray.synchrotron_jet_contains(params, [10.0, 0.0, 0.0])
    assert not astroray.synchrotron_jet_contains(params, [0.0, 3.0, 0.0])


def test_jet_profiles_dim_with_radius():
    params = {
        "half_angle_degrees": 10.0,
        "r_base": 6.0,
        "r_max": 100.0,
        "lorentz_factor": 1.0,
        "base_density": 10.0,
        "magnetic_field": 20.0,
    }
    near = astroray.synchrotron_jet_sample_visible(params, [0.0, 6.0, 0.0], [1.0, 0.0, 0.0], 0.5, 1.0)
    far = astroray.synchrotron_jet_sample_visible(params, [0.0, 12.0, 0.0], [1.0, 0.0, 0.0], 0.5, 1.0)
    ratio = np.mean(near["values"]) / np.mean(far["values"])
    assert ratio == pytest.approx(2.0 ** 3.75, rel=0.02)


def test_gamma10_head_on_doppler_boost_recovers_d_cubed_scale():
    params = {"lorentz_factor": 10.0, "half_angle_degrees": 10.0, "r_base": 1.0, "r_max": 20.0}
    d = astroray.synchrotron_jet_doppler_factor(params, [0.0, 5.0, 0.0], [0.0, 1.0, 0.0])
    assert d ** 3 == pytest.approx(8000.0, rel=0.02)


def test_visible_sample_is_finite_and_power_law_blue_red_ordering():
    params = {"lorentz_factor": 1.0, "half_angle_degrees": 10.0, "r_base": 1.0, "r_max": 20.0}
    sample = astroray.synchrotron_jet_sample_visible(params, [0.0, 5.0, 0.0], [1.0, 0.0, 0.0], 0.25, 3.0)
    values = np.asarray(sample["values"], dtype=float)
    lambdas = np.asarray(sample["lambdas"], dtype=float)
    assert np.all(np.isfinite(values))
    assert np.all(values > 0.0)
    # For p=2.5, j_nu ~ nu^-0.75, so longer visible wavelengths are brighter.
    assert values[np.argmax(lambdas)] > values[np.argmin(lambdas)]


def test_tiny_synchrotron_scene_renders_visible_signal():
    from synchrotron_jet import build_scene

    renderer = build_scene(astroray, width=16, height=16)
    pixels = renderer.render(1, 2)
    arr = np.asarray(pixels, dtype=float).reshape((16, 16, 3))
    assert np.all(np.isfinite(arr))
    assert float(arr.max()) > 0.0
