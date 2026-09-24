"""pkg280 — thin-disk invariant wavelength transfer against analytic physics.

The native seam calls ``thinDiskInvariantTransferWavelength`` in the production
header. The frequency-domain expression below is an independent oracle; this
is analytic self-consistency, not the later external GYOTO validation.
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
