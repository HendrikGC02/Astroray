"""pkg67: SampledWavelengths.redshift unit test.

Verifies that SampledWavelengths.redshift(g) applies λ_obs = λ_emit / g
(the convention documented on the C++ method, matching dc.g in
BlackHole::diskEmissionSpectral where g = ν_obs / ν_emit).
"""

import pytest


@pytest.fixture(scope="module")
def astroray_module():
    try:
        import astroray
    except ImportError as e:
        pytest.skip(f"astroray module not available: {e}")
    if not hasattr(astroray, "SampledWavelengths"):
        pytest.skip("astroray build predates pkg67 (no SampledWavelengths)")
    if not hasattr(astroray.SampledWavelengths(), "redshift"):
        pytest.skip("astroray build predates pkg67 (no redshift method)")
    return astroray


def _lambdas(swl):
    # binding exposes lambdas() as a list[float]
    return list(swl.lambdas())


def _pdfs(swl):
    return list(swl.pdfs())


@pytest.mark.parametrize("g", [1.0, 2.0, 0.5, 1.25])
def test_redshift_scales_wavelengths(astroray_module, g):
    swl = astroray_module.SampledWavelengths.sample_uniform(0.5)
    lam0 = _lambdas(swl)
    pdf0 = _pdfs(swl)
    swl.redshift(g)
    lam1 = _lambdas(swl)
    pdf1 = _pdfs(swl)
    for a, b in zip(lam0, lam1):
        assert b == pytest.approx(a / g, rel=1e-6), (
            f"redshift(g={g}) expected λ/g, got λ0={a}, λ1={b}"
        )
    for a, b in zip(pdf0, pdf1):
        # PDF density (1/length) scales by g
        assert b == pytest.approx(a * g, rel=1e-6)


def test_redshift_identity(astroray_module):
    swl = astroray_module.SampledWavelengths.sample_uniform(0.25)
    before = _lambdas(swl)
    swl.redshift(1.0)
    after = _lambdas(swl)
    assert before == after


def test_redshift_rejects_non_positive(astroray_module):
    # g <= 0 is degenerate; the C++ method short-circuits to a no-op.
    swl = astroray_module.SampledWavelengths.sample_uniform(0.5)
    before = _lambdas(swl)
    swl.redshift(0.0)
    assert _lambdas(swl) == before
    swl.redshift(-1.0)
    assert _lambdas(swl) == before
