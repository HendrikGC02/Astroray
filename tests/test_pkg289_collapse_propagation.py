"""pkg289: hero-wavelength collapse propagation (#904 gap, #917).

#904: a collapse inside pathTraceSpectralCaustic's specular walk must reach the
caller's lambdas: landed in efc9f89a, gated by test_issue904_caustic_walk_collapse.py.

#917: path-guiding training snapshots (Csnap, betaSnap) were luminances taken
with the lambdas at snapshot time; a later dispersive collapse changes the lane
pdfs, so Yfinal - Csnap was collapse noise, not downstream radiance. The probe
scene has ~zero radiance downstream of the recorded diffuse vertex (only a rare
hit on a small lamp), so spurious records appear only with the bug.
"""
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

helpers = pytest.importorskip("astroray_test_helpers")
if not hasattr(helpers, "guide_snapshot_collapse_probe"):
    pytest.skip("astroray_test_helpers lacks guide_snapshot_collapse_probe; rebuild it",
                allow_module_level=True)

_TRIALS = 512
# Legit records: continuation hits the 0.2-radius lamp 3 units away (~0.1 % of
# the cosine hemisphere) -> well under 2 % of trials.
_MAX_FRAC = 0.02


@pytest.mark.cpu
def test_917_guide_snapshot_control_clear_glass():
    records, trials = helpers.guide_snapshot_collapse_probe(_TRIALS, False)
    assert records <= _MAX_FRAC * trials, (records, trials)


@pytest.mark.cpu
def test_917_guide_snapshot_survives_dispersive_collapse():
    records, trials = helpers.guide_snapshot_collapse_probe(_TRIALS, True)
    assert records <= _MAX_FRAC * trials, (
        f"{records}/{trials} spurious guide records after a dispersive collapse")
