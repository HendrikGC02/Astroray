"""pkg280 — thin-disk invariant wavelength transfer against analytic physics.

The native seam calls ``thinDiskInvariantTransferWavelength`` in the production
header. The frequency-domain expression below is an independent oracle; this
is analytic self-consistency, not the later external GYOTO validation.

pkg283 — volumetric (ADAF, synchrotron jet) invariant transport. The oracle
is the frame-transformation form (Rybicki & Lightman §4.9):
I_obs(nu) = g^3 I_em(nu/g), with I_em the fluid-frame slab solution over the
fluid-frame path L_fluid = ds_lab/g. Production integrates the invariant
affine form (j/nu^2, nu*alpha) instead, so agreement is a real cross-check.
"""

import math

import numpy as np
import pytest

helpers = pytest.importorskip("astroray_test_helpers")
for _name in (
    "thin_disk_invariant_transfer_wavelength",
    "thin_disk_emitted_wavelength_nm",
    "thin_disk_normalized_transfer_wavelength",
    "thin_disk_accumulate_finite",
    "gr_renderer_dispatch_probe",
    "gr_restir_registry_dispatch_probe",
):
    assert hasattr(helpers, _name), (
        f"astroray_test_helpers lacks {_name}; rebuild its fresh pkg280 target "
        "instead of validating against a stale native module"
    )


H = 6.62607015e-34
C = 299792458.0
K = 1.380649e-23
SIGMA = 5.670374419e-8


def _planck_lambda(lambda_nm, temperature_K):
    wavelength_m = np.asarray(lambda_nm, dtype=float) * 1.0e-9
    exponent = H * C / (wavelength_m * K * temperature_K)
    with np.errstate(over="ignore", under="ignore", divide="ignore"):
        return (2.0 * H * C * C / wavelength_m**5) / np.expm1(exponent)


def _planck_nu(frequency_hz, temperature_K):
    frequency_hz = np.asarray(frequency_hz, dtype=float)
    exponent = H * frequency_hz / (K * temperature_K)
    with np.errstate(over="ignore", under="ignore", divide="ignore"):
        return (2.0 * H * frequency_hz**3 / C**2) / np.expm1(exponent)


def _production(lambda_nm, temperature_K, g):
    return np.asarray([
        helpers.thin_disk_invariant_transfer_wavelength(float(lam), temperature_K, g)
        for lam in lambda_nm
    ])


def _trapezoid(values, coordinates):
    return np.trapezoid(values, coordinates) if hasattr(np, "trapezoid") else np.trapz(values, coordinates)


@pytest.mark.parametrize("g", [0.5, 1.0, 2.0])
def test_wavelength_and_frequency_forms_agree_per_bin(g):
    temperature_K = 7000.0
    lambdas_nm = np.geomspace(40.0, 40000.0, 401)
    got = _production(lambdas_nm, temperature_K, g)
    wavelength_m = lambdas_nm * 1.0e-9
    frequency_emit = C / (g * wavelength_m)
    expected = (C / wavelength_m**2) * g**3 * _planck_nu(frequency_emit, temperature_K)
    np.testing.assert_allclose(got, expected, rtol=1.0e-12, atol=0.0)


def test_identity_redshift_is_unshifted_planck():
    temperature_K = 9000.0
    lambdas_nm = np.geomspace(80.0, 100000.0, 301)
    np.testing.assert_allclose(
        _production(lambdas_nm, temperature_K, 1.0),
        _planck_lambda(lambdas_nm, temperature_K),
        rtol=1.0e-12,
        atol=0.0,
    )


@pytest.mark.parametrize("g", [0.5, 1.0, 2.0])
def test_recovered_colour_temperature_is_g_times_temperature(g):
    temperature_K = 8000.0
    lambdas_nm = np.geomspace(100.0, 100000.0, 601)
    got = _production(lambdas_nm, temperature_K, g)
    target_temperature = g * temperature_K
    candidates = np.linspace(target_temperature * 0.98, target_temperature * 1.02, 401)
    got_shape = got / np.max(got)
    errors = [np.mean((got_shape - _planck_lambda(lambdas_nm, candidate) /
                      np.max(_planck_lambda(lambdas_nm, candidate))) ** 2)
              for candidate in candidates]
    fitted_temperature = candidates[int(np.argmin(errors))]
    assert abs(fitted_temperature / target_temperature - 1.0) <= 0.01


@pytest.mark.parametrize("g", [0.5, 1.0, 2.0])
def test_monochromatic_emission_shift_uses_production_wavelength_transform(g):
    lambda_em_nm = 656.28
    lambda_obs_nm = lambda_em_nm / g
    assert helpers.thin_disk_emitted_wavelength_nm(lambda_obs_nm, g) == pytest.approx(
        lambda_em_nm, rel=1.0e-12
    )


def test_bolometric_ratio_is_g_to_the_fourth_on_enclosing_grid():
    temperature_K = 6000.0
    g = 2.0
    # This covers x = hc/(lambda kT) from < 1e-6 to > 1000 for both T and gT,
    # comfortably enclosing 99.9% of a Planck spectrum's bolometric flux.
    lambdas_nm = np.geomspace(1.0, 1.0e7, 12001)
    wavelengths_m = lambdas_nm * 1.0e-9
    for spectrum_temperature in (temperature_K, g * temperature_K):
        captured_flux = _trapezoid(
            _planck_lambda(lambdas_nm, spectrum_temperature), wavelengths_m
        )
        assert captured_flux / (SIGMA * spectrum_temperature**4 / math.pi) >= 0.999
    emitted = _production(lambdas_nm, temperature_K, 1.0)
    observed = _production(lambdas_nm, temperature_K, g)
    ratio = _trapezoid(observed, lambdas_nm) / _trapezoid(emitted, lambdas_nm)
    assert ratio == pytest.approx(g**4, rel=0.01)


def test_uncapped_transfer_remains_finite_above_former_output_limit():
    value = helpers.thin_disk_invariant_transfer_wavelength(500.0, 20000.0, 20.0)
    assert math.isfinite(value)
    assert value > 20.0
    assert value == pytest.approx(_planck_lambda(500.0, 20.0 * 20000.0), rel=1.0e-12)


def test_local_disk_normalization_and_accumulation_are_unclamped_and_finite():
    value = helpers.thin_disk_normalized_transfer_wavelength(
        500.0, 20000.0, 1.0e10, 5.0e-14, 1800.0
    )
    assert math.isfinite(value)
    assert value > 20.0
    assert helpers.thin_disk_accumulate_finite(0.0, value) == pytest.approx(value)


def test_local_disk_accumulation_rejects_only_unrepresentable_storage_values():
    prior = 7.0
    unrepresentable = float(np.finfo(np.float32).max) * 2.0
    assert helpers.thin_disk_accumulate_finite(prior, unrepresentable) == prior


def test_renderer_gr_dispatch_has_no_hidden_twenty_ceiling():
    for caustic in (False, True):
        unclamped, trace_calls = helpers.gr_renderer_dispatch_probe(64.0, caustic=caustic)
        assert trace_calls == 1
        assert unclamped == pytest.approx(64.0)
        clamped, clamped_trace_calls = helpers.gr_renderer_dispatch_probe(
            64.0, clamp_direct=10.0, caustic=caustic
        )
        assert clamped_trace_calls == 1
        assert clamped < unclamped


def test_registered_restir_gr_dispatch_preserves_uncapped_emission():
    reference, reference_trace_calls = helpers.gr_restir_registry_dispatch_probe(20.0)
    observed, observed_trace_calls = helpers.gr_restir_registry_dispatch_probe(64.0)
    assert reference_trace_calls == 1
    assert observed_trace_calls == 1
    assert reference > 0.0
    assert observed / reference == pytest.approx(64.0 / 20.0, rel=1.0e-6)


# ---------------------------------------------------------------- pkg283 ---

astroray = pytest.importorskip("astroray")

C_CGS = 2.99792458e10
H_CGS = 6.62607015e-27
K_CGS = 1.380649e-16
THETA_B = math.pi / 2.0

JET = {
    "half_angle_degrees": 30.0, "r_base": 1.0, "r_max": 100.0,
    "power_law_index": 2.5, "gamma_min": 10.0, "gamma_max": 1.0e5,
    "base_density": 1.0e4, "magnetic_field": 1.0e4, "intensity_scale": 1.0,
}
ADAF = {
    "mass": 4.0e6, "mdot_edd": 1.0e-5, "alpha": 0.1, "beta_mag": 0.1,
    "s": 0.3, "electron_temp": 5.0e10, "r_inner": 2.0, "r_outer": 100.0,
}
JET_POS = [0.0, 10.0, 0.0]          # on the +y jet axis
ADAF_POS = [0.0, 0.0, 10.0]
VISIBLE_NM = [420.0, 500.0, 580.0, 660.0]


def _unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def _dir_at_angle(deg):
    """Propagation direction at `deg` from the +y jet axis, in the xy plane."""
    a = math.radians(deg)
    return [math.sin(a), math.cos(a), 0.0]


def _g(beta, direction):
    b = np.asarray(beta, dtype=float)
    return math.sqrt(1.0 - b @ b) / (1.0 - b @ _unit(direction))


def _nu(lambda_nm):
    return C_CGS / (np.asarray(lambda_nm, dtype=float) * 1.0e-7)


def _planck_nu_cgs(nu, T):
    return (2.0 * H_CGS * nu**3 / C_CGS**2) / np.expm1(H_CGS * nu / (K_CGS * T))


def _jet_fluid_coefficients(nu_em, params, absorb):
    r = math.dist(JET_POS, [0.0, 0.0, 0.0])
    ne = params["base_density"] * (r / params["r_base"]) ** -2
    B = params["magnetic_field"] * (r / params["r_base"]) ** -1
    args = (THETA_B, params["power_law_index"], params["gamma_min"], params["gamma_max"])
    j = np.array([astroray.synchrotron_powerlaw_emissivity(float(n), ne, B, *args) for n in nu_em])
    a = np.array([astroray.synchrotron_powerlaw_absorptivity(float(n), ne, B, *args) for n in nu_em])
    return j, (a if absorb else np.zeros_like(a))


def _adaf_fluid_coefficients(nu_em, params):
    ne = astroray.adaf_density_at(params, ADAF_POS)
    T = astroray.adaf_electron_temperature_at(params, ADAF_POS)
    B = astroray.adaf_magnetic_field_at(params, ADAF_POS)
    j = np.array([astroray.synchrotron_thermal_emissivity(float(n), ne, T, B, THETA_B)
                  + astroray.bremsstrahlung_emissivity(float(n), ne, T) for n in nu_em])
    return j, j / _planck_nu_cgs(nu_em, T)  # Kirchhoff, R&L eq. 1.37


def _oracle(j_em, a_em, g, ds_lab):
    """Frame-transformation oracle: g^3 x fluid-frame uniform-slab intensity."""
    L_fluid = ds_lab / g
    tau = a_em * L_fluid
    with np.errstate(divide="ignore", invalid="ignore"):
        slab = np.where(tau > 1.0e-9, j_em / a_em * -np.expm1(-tau), j_em * L_fluid)
    return g**3 * slab


def _segment(model, params, pos, direction, lambdas, ds, beta=None):
    values, tau = helpers.volumetric_segment(model, params, list(pos), list(direction),
                                             [float(x) for x in lambdas], float(ds), beta)
    return np.asarray(values, dtype=float), np.asarray(tau, dtype=float)


@pytest.mark.parametrize("beta", [[0.0, 0.0, 0.0], [0.0, 0.6, 0.0], [0.3, -0.5, 0.4], [0.0, 0.99, 0.0]])
@pytest.mark.parametrize("deg", [0.0, 35.0, 90.0, 150.0])
def test_fluid_frame_frequency_is_minus_k_dot_u(beta, deg):
    nu_obs = 5.0e14
    n = _unit(_dir_at_angle(deg))
    b = np.asarray(beta)
    gamma = 1.0 / math.sqrt(1.0 - b @ b)
    expected = nu_obs * gamma * (1.0 - b @ n)   # -k.u, k=nu(1,n), u=gamma(1,b)
    got = helpers.volumetric_fluid_frequency(nu_obs, list(n), list(b))
    assert got == pytest.approx(expected, rel=1.0e-6)   # directions cross as float3


def test_model_fluid_velocities():
    # ADAF keeps its static fluid (no new ADAF kinematics in pkg283).
    assert helpers.volumetric_fluid_velocity("adaf", ADAF, ADAF_POS) == pytest.approx([0.0, 0.0, 0.0])
    moving = {**JET, "lorentz_factor": 5.0}
    beta = helpers.volumetric_fluid_velocity("synchrotron_jet", moving, JET_POS)
    assert beta == pytest.approx([0.0, math.sqrt(1.0 - 1.0 / 25.0), 0.0], rel=1.0e-6)
    d = astroray.synchrotron_jet_doppler_factor(moving, JET_POS, _dir_at_angle(35.0))
    nu_em = helpers.volumetric_fluid_frequency(5.0e14, _dir_at_angle(35.0), beta)
    assert 5.0e14 / nu_em == pytest.approx(d, rel=1.0e-6)


@pytest.mark.parametrize("absorb", [False, True])
def test_jet_g_equals_one_reduces_to_fluid_frame_slab(absorb):
    params = {**JET, "lorentz_factor": 1.0, "include_self_absorption": absorb}
    lam = [1.0e5, 2.0e5, 5.0e5, 1.0e6]
    j, a = _jet_fluid_coefficients(_nu(lam), params, absorb)
    ds = 1.0 / max(a[1], 1.0e-30) if absorb else 1.0e9
    got, _ = _segment("synchrotron_jet", params, JET_POS, _dir_at_angle(40.0), lam, ds)
    np.testing.assert_allclose(got, _oracle(j, a, 1.0, ds), rtol=1.0e-4)


def test_adaf_static_reduces_to_fluid_frame_slab():
    j, a = _adaf_fluid_coefficients(_nu(VISIBLE_NM), ADAF)
    ds = 1.0e12
    got, _ = _segment("adaf", ADAF, ADAF_POS, [1.0, 0.0, 0.0], VISIBLE_NM, ds)
    np.testing.assert_allclose(got, _oracle(j, a, 1.0, ds), rtol=1.0e-4)


@pytest.mark.parametrize("deg", [0.0, 10.0, 35.0, 90.0, 150.0])
def test_jet_static_vs_moving_ratio_is_d_cubed_no_double_counting(deg):
    """Same fluid-frame slab (L_fluid) and fluid-frame frequency: moving/static = D^3.

    The moving slab's lab path is D*L_fluid. Pre-pkg283 code gave D^4.
    """
    L_fluid = 1.0e9
    direction = _dir_at_angle(deg)
    moving = {**JET, "lorentz_factor": 5.0}
    static = {**JET, "lorentz_factor": 1.0}
    D = astroray.synchrotron_jet_doppler_factor(moving, JET_POS, direction)
    lam_em = np.asarray(VISIBLE_NM)
    I_static, _ = _segment("synchrotron_jet", static, JET_POS, direction, lam_em, L_fluid)
    I_moving, _ = _segment("synchrotron_jet", moving, JET_POS, direction, lam_em / D, D * L_fluid)
    np.testing.assert_allclose(I_moving / I_static, D**3, rtol=0.01)


@pytest.mark.parametrize("beta", [[0.0, 0.0, 0.5], [0.0, 0.0, -0.5], [0.4, 0.0, 0.3]])
def test_adaf_static_vs_moving_ratio_is_g_cubed_no_double_counting(beta):
    L_fluid = 1.0e12
    direction = [0.0, 0.0, 1.0]
    g = _g(beta, direction)
    lam_em = np.asarray(VISIBLE_NM)
    I_static, _ = _segment("adaf", ADAF, ADAF_POS, direction, lam_em, L_fluid, [0.0, 0.0, 0.0])
    I_moving, _ = _segment("adaf", ADAF, ADAF_POS, direction, lam_em / g, g * L_fluid, beta)
    np.testing.assert_allclose(I_moving / I_static, g**3, rtol=0.01)


def test_jet_public_segment_has_steady_jet_scaling():
    """Public binding, same lab path and wavelengths: moving/static = D^(2+alpha).

    Lind & Blandford 1985 steady-jet law, alpha = (p-1)/2. Pre-pkg283: D^(3+alpha).
    """
    direction = _dir_at_angle(10.0)
    moving = {**JET, "lorentz_factor": 5.0}
    static = {**JET, "lorentz_factor": 1.0}
    D = astroray.synchrotron_jet_doppler_factor(moving, JET_POS, direction)
    s = np.asarray(astroray.synchrotron_jet_sample_visible(static, JET_POS, direction, 0.5, 1.0e9)["values"])
    m = np.asarray(astroray.synchrotron_jet_sample_visible(moving, JET_POS, direction, 0.5, 1.0e9)["values"])
    np.testing.assert_allclose(m / s, D ** (2.0 + 0.75), rtol=0.01)


@pytest.mark.parametrize("deg", [0.0, 35.0, 150.0])
@pytest.mark.parametrize("tau_target", [0.3, 3.0])
def test_jet_invariant_residual_with_absorption(deg, tau_target):
    params = {**JET, "lorentz_factor": 5.0, "include_self_absorption": True}
    direction = _dir_at_angle(deg)
    D = astroray.synchrotron_jet_doppler_factor(params, JET_POS, direction)
    lam = np.asarray([1.0e5, 2.0e5, 5.0e5, 1.0e6])    # sub-mm/mm: tau ~ 1 reachable
    j, a = _jet_fluid_coefficients(_nu(lam) / D, params, True)
    ds = tau_target * D / a[1]
    got, tau = _segment("synchrotron_jet", params, JET_POS, direction, lam, ds)
    assert np.max(np.abs(got / _oracle(j, a, D, ds) - 1.0)) <= 0.01
    np.testing.assert_allclose(tau, a * ds / D, rtol=1.0e-4)


@pytest.mark.parametrize("beta", [[0.0, 0.0, 0.0], [0.0, 0.0, 0.5], [0.0, 0.0, -0.5]])
@pytest.mark.parametrize("tau_target", [0.3, 3.0])
def test_adaf_invariant_residual_with_absorption(beta, tau_target):
    direction = [0.0, 0.0, 1.0]
    g = _g(beta, direction)
    lam = np.asarray([3.0e5, 1.0e6, 3.0e6, 1.0e7])    # sub-mm to cm: self-absorbed
    j, a = _adaf_fluid_coefficients(_nu(lam) / g, ADAF)
    ds = tau_target * g / a[1]
    got, tau = _segment("adaf", ADAF, ADAF_POS, direction, lam, ds, beta)
    assert np.max(np.abs(got / _oracle(j, a, g, ds) - 1.0)) <= 0.01
    np.testing.assert_allclose(tau, a * ds / g, rtol=1.0e-4)


@pytest.mark.parametrize("model", ["synchrotron_jet", "adaf"])
def test_chord_march_attenuates_front_to_back(model):
    """N identical segments must equal one uniform slab of the total length."""
    if model == "adaf":
        params, pos, direction = ADAF, ADAF_POS, [0.0, 0.0, 1.0]
        lam = [3.0e5, 1.0e6, 3.0e6, 1.0e7]
    else:
        params = {**JET, "lorentz_factor": 5.0, "include_self_absorption": True}
        pos, direction, lam = JET_POS, _dir_at_angle(35.0), [1.0e5, 2.0e5, 5.0e5, 1.0e6]
    _, tau_unit = _segment(model, params, pos, direction, lam, 1.0)
    ds_total = 3.0 / tau_unit[1]
    whole, _ = _segment(model, params, pos, direction, lam, ds_total)
    n = 96
    marched = np.asarray(helpers.volumetric_chord(model, params, list(pos), list(direction),
                                                  [float(x) for x in lam], ds_total / n, n),
                         dtype=float)
    np.testing.assert_allclose(marched, whole, rtol=0.01)
