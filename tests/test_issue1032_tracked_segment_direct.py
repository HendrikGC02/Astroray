"""#1032 - tracked-collision segment direct light (volume::sampleSegmentDirectTracked).

Closed forms through the astroray_test_helpers seam: a homogeneous slab and a 1D
grid density step (ray along +x, t = x + 1, hull entry t = 1). The estimate
Tr * sigma_s(t) * w must average to the single-scatter integral
I = int_a^b T(t) sigma_s(t) dt per lane, for the distance strategy alone and for
the 50/50 MIS with equiangular. Without Russian roulette the reservoir weights
W_k = prod p_n * p_s are the probabilities that delta tracking scatters at
collision k, so they sum (in expectation) to the analytic probability of a
scatter on [a,b]: E[sum W] = 1 - exp(-sigma_bar * p_s * (b - a)).
"""
import math

import pytest

helpers = pytest.importorskip("astroray_test_helpers")
assert hasattr(helpers, "segment_tracked_probe"), \
    "astroray_test_helpers lacks segment_tracked_probe; rebuild it"

LAMBDAS = [450.0, 520.0, 590.0, 660.0]
N = 100_000
ANCHOR = (5.0, 2.0, 0.25)          # off-ray lamp: equiangular D = 1.75
REGION = {"slab": (1.0, 9.0), "step": (4.5, 8.5)}   # density-1 interval in t


def closed_form(kind, density, su, st, a, b):
    r0, r1 = REGION[kind]
    lo, hi = max(a, r0), min(b, r1)
    if hi <= lo:
        return 0.0
    k = density * st
    return (su / st) * (math.exp(-k * (lo - r0)) - math.exp(-k * (hi - r0)))


def probe(kind, density, color, a, b, anchor, seed, supervoxel=2):
    return helpers.segment_tracked_probe(kind, density, color, a, b, anchor is not None,
                                         anchor or (0.0, 0.0, 0.0), N, seed, supervoxel,
                                         LAMBDAS)


@pytest.mark.parametrize("kind", ["slab", "step"])
@pytest.mark.parametrize("mis", [False, True])
@pytest.mark.parametrize("a,b", [(1.0, 9.0), (3.0, 7.0)])
def test_estimate_matches_single_scatter_integral(kind, mis, a, b):
    density = 0.6
    r = probe(kind, density, (0.5, 0.5, 0.5), a, b, ANCHOR if mis else None,
              seed=1032 + int(mis) + 7 * int(a))
    for i in range(len(LAMBDAS)):
        ref = closed_form(kind, density, r["sigma_s_unit"][i], r["sigma_t_unit"][i], a, b)
        se = math.sqrt(max(r["var"][i], 0.0) / N)
        assert abs(r["mean"][i] - ref) <= 4.0 * se + 1e-3 * ref, \
            (kind, mis, a, b, i, r["mean"][i], ref, se)


@pytest.mark.parametrize("kind", ["slab", "step"])
def test_local_and_global_ratio_tracking_match_beer_lambert(kind):
    density = 0.6
    r = probe(kind, density, (0.5, 0.5, 0.5), 1.0, 9.0, None, seed=7)
    r0, r1 = REGION[kind]
    for i in range(len(LAMBDAS)):
        ref = math.exp(-density * r["sigma_t_unit"][i] * (r1 - r0))
        for key in ("tr_local", "tr_global"):
            assert abs(r[key][i] - ref) <= 0.01 * ref + 2e-3, (kind, key, i, r[key][i], ref)


def test_reservoir_weights_sum_to_scatter_probability():
    density, a, b = 0.5, 3.0, 7.0
    r = probe("slab", density, (0.2, 0.2, 0.2), a, b, None, seed=11)
    sigma_bar = r["majorant"]
    su, st = r["sigma_s_unit"], r["sigma_t_unit"]
    # p_s = hero average of sigma_s / (sigma_s + sigma_n), sigma_n = sigma_bar - sigma_t.
    ps = sum(density * s / (density * s + sigma_bar - density * t) for s, t in zip(su, st)) / len(su)
    ref = 1.0 - math.exp(-sigma_bar * ps * (b - a))
    se = math.sqrt(ref * (1.0 - ref) / N)
    assert abs(r["wsum_mean"] - ref) <= 4.0 * se + 1e-3, (r["wsum_mean"], ref, se)
