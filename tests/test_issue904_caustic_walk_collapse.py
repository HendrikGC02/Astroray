"""#904: a hero-wavelength collapse in pathTraceSpectralCaustic's specular walk
(walkLambdas) must propagate to the caller's wavelengths, else the walk's
hero-only contribution is weighted as if every wavelength followed it."""

import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

helpers = pytest.importorskip("astroray_test_helpers")
if not hasattr(helpers, "caustic_walk_collapse_probe"):
    pytest.skip("astroray_test_helpers lacks caustic_walk_collapse_probe; rebuild it",
                allow_module_level=True)


def test_walk_collapse_reaches_caller_lambdas():
    trials = 64
    collapsed = helpers.caustic_walk_collapse_probe(trials)
    # The walk refracts through BK7 on most seeds (Fresnel reflection ~4-8% per
    # face); each such refraction collapses the hero wavelength.
    assert collapsed >= trials // 2, f"only {collapsed}/{trials} walks collapsed caller lambdas"
