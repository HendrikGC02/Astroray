"""
pkg21 — ReSTIR light sample abstraction tests.

Covers ReSTIRCandidate validity rules and target-weight behaviour through the
ReSTIRCandidateHelper test binding.

Test strategy:
  - Valid candidate round-trip and field inspection.
  - isValid rejects all documented bad states (zero pdf, negative pdf, NaN/Inf
    pdf, non-finite emission, non-finite position).
  - targetLuminance returns a positive float for a white-light emitter and zero
    for invalid candidates.
  - targetLuminance ordering: brighter emitter produces higher luminance.
"""

import math
import pytest


ORIGIN    = [0.0, 0.0, 0.0]
UP_NORMAL = [0.0, 1.0, 0.0]
WHITE     = [1.0, 1.0, 1.0]
VALID_PDF = 0.5
VALID_DIST = 3.0


@pytest.fixture(scope="module")
def candidate_cls(astroray_module):
    return astroray_module.ReSTIRCandidateHelper


@pytest.fixture(scope="module")
def lambdas(astroray_module):
    return astroray_module.SampledWavelengths.sample_uniform(0.5)


def make(candidate_cls, *, position=None, normal=None,
         emission=None, pdf=None, distance=None):
    return candidate_cls(
        position=position or ORIGIN,
        normal=normal or UP_NORMAL,
        emission=emission or WHITE,
        pdf=pdf if pdf is not None else VALID_PDF,
        distance=distance if distance is not None else VALID_DIST,
    )


# ---------------------------------------------------------------------------
# Validity — positive cases
# ---------------------------------------------------------------------------

class TestIsValidPositive:
    def test_well_formed_candidate_is_valid(self, candidate_cls):
        c = make(candidate_cls)
        assert c.is_valid()

    def test_minimum_positive_pdf_is_valid(self, candidate_cls):
        c = make(candidate_cls, pdf=1e-30)
        assert c.is_valid()

    def test_bright_emission_is_valid(self, candidate_cls):
        c = make(candidate_cls, emission=[1000.0, 1000.0, 1000.0])
        assert c.is_valid()

    def test_zero_emission_is_valid(self, candidate_cls):
        # A candidate with zero emission is geometrically valid (pdf > 0),
        # but targetLuminance will return 0.
        c = make(candidate_cls, emission=[0.0, 0.0, 0.0])
        assert c.is_valid()


# ---------------------------------------------------------------------------
# Validity — rejection cases
# ---------------------------------------------------------------------------

class TestIsValidRejection:
    def test_zero_pdf_invalid(self, candidate_cls):
        assert not make(candidate_cls, pdf=0.0).is_valid()

    def test_negative_pdf_invalid(self, candidate_cls):
        assert not make(candidate_cls, pdf=-1.0).is_valid()

    def test_nan_pdf_invalid(self, candidate_cls):
        assert not make(candidate_cls, pdf=float("nan")).is_valid()

    def test_inf_pdf_invalid(self, candidate_cls):
        assert not make(candidate_cls, pdf=float("inf")).is_valid()

    def test_nan_emission_x_invalid(self, candidate_cls):
        assert not make(candidate_cls, emission=[float("nan"), 1.0, 1.0]).is_valid()

    def test_nan_emission_y_invalid(self, candidate_cls):
        assert not make(candidate_cls, emission=[1.0, float("nan"), 1.0]).is_valid()

    def test_nan_emission_z_invalid(self, candidate_cls):
        assert not make(candidate_cls, emission=[1.0, 1.0, float("nan")]).is_valid()

    def test_inf_emission_invalid(self, candidate_cls):
        assert not make(candidate_cls, emission=[float("inf"), 0.0, 0.0]).is_valid()

    def test_nan_position_x_invalid(self, candidate_cls):
        assert not make(candidate_cls, position=[float("nan"), 0.0, 0.0]).is_valid()

    def test_inf_position_invalid(self, candidate_cls):
        assert not make(candidate_cls, position=[float("inf"), 0.0, 0.0]).is_valid()


# ---------------------------------------------------------------------------
# Target luminance — correctness
# ---------------------------------------------------------------------------

class TestTargetLuminance:
    def test_valid_white_emitter_returns_positive(self, candidate_cls, lambdas):
        c = make(candidate_cls, emission=[1.0, 1.0, 1.0])
        Y = c.target_luminance(lambdas)
        assert Y > 0.0

    def test_black_emitter_returns_zero(self, candidate_cls, lambdas):
        c = make(candidate_cls, emission=[0.0, 0.0, 0.0])
        Y = c.target_luminance(lambdas)
        assert Y == 0.0

    def test_invalid_candidate_returns_zero(self, candidate_cls, lambdas):
        c = make(candidate_cls, pdf=0.0)
        assert c.target_luminance(lambdas) == 0.0

    def test_nan_pdf_returns_zero(self, candidate_cls, lambdas):
        c = make(candidate_cls, pdf=float("nan"))
        assert c.target_luminance(lambdas) == 0.0

    def test_brighter_emitter_has_higher_luminance(self, candidate_cls, lambdas):
        dim    = make(candidate_cls, emission=[0.1, 0.1, 0.1])
        bright = make(candidate_cls, emission=[10.0, 10.0, 10.0])
        assert bright.target_luminance(lambdas) > dim.target_luminance(lambdas)

    def test_luminance_is_finite(self, candidate_cls, lambdas):
        c = make(candidate_cls, emission=[5.0, 3.0, 1.0])
        Y = c.target_luminance(lambdas)
        assert math.isfinite(Y)

    def test_luminance_is_non_negative(self, candidate_cls, lambdas):
        for em in [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0],
                   [0.5, 0.5, 0.5], [0.0, 0.0, 0.0]]:
            c = make(candidate_cls, emission=em)
            assert c.target_luminance(lambdas) >= 0.0

    def test_luminance_stable_across_wavelength_samples(self, candidate_cls, astroray_module):
        """Same emission should give consistent luminance across different wavelength draws."""
        c = make(candidate_cls, emission=[1.0, 1.0, 1.0])
        results = []
        for u in [0.1, 0.3, 0.5, 0.7, 0.9]:
            wls = astroray_module.SampledWavelengths.sample_uniform(u)
            results.append(c.target_luminance(wls))
        # All should be positive; variance should be small relative to mean
        mean = sum(results) / len(results)
        assert mean > 0.0
        for v in results:
            assert abs(v - mean) / mean < 0.5, (
                f"Target luminance varies too much across wavelength samples: {results}"
            )
