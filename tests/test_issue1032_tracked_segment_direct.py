"""#1032 - tracked-collision segment direct light (volume::sampleSegmentDirectTracked).

Through the astroray_test_helpers seam ``segment_tracked_probe``:
  * closed forms on a homogeneous slab and a 1D grid density step (ray along +x,
    t = x + 1, hull [1, 9]);
  * a fine quadrature along the ray for an obliquely crossed grid with a scaled +
    rotated + translated world-to-index transform (multi-axis DDA steps, edge
    pieces), that grid overlapping a homogeneous box (one-grid majorant rule) and
    overlapping a second grid (sum of global majorants).
The estimate Tr * sigma_s(t) * w must average to I = int_a^b T(t) sigma_s(t) dt
per lane, for the distance strategy alone and for the 50/50 MIS with
equiangular; local and global ratio tracking must average to T over the hull.
Without Russian roulette the reservoir weights W_k = prod p_n * p_s are the
probabilities that delta tracking scatters at collision k, so they sum (in
expectation) to the analytic scatter probability on [a,b]:
E[sum W] = 1 - exp(-sigma_bar * p_s * (b - a)).
"""
import math

import pytest

helpers = pytest.importorskip("astroray_test_helpers")
assert hasattr(helpers, "segment_tracked_probe"), \
    "astroray_test_helpers lacks segment_tracked_probe; rebuild it"

LAMBDAS = [450.0, 520.0, 590.0, 660.0]
N = 100_000
ANCHOR = {"slab": (5.0, 2.0, 0.25), "step": (5.0, 2.0, 0.25),   # off-ray lamp
          "oblique": (0.5, 1.5, 0.5), "grid_hom": (0.5, 1.5, 0.5), "two_grids": (0.5, 1.5, 0.5)}
REGION = {"slab": (1.0, 9.0), "step": (4.5, 8.5)}   # density-1 interval in t


def closed_form(kind, density, su, st, a, b):
    r0, r1 = REGION[kind]
    lo, hi = max(a, r0), min(b, r1)
    if hi <= lo:
        return 0.0
    k = density * st
    return (su / st) * (math.exp(-k * (lo - r0)) - math.exp(-k * (hi - r0)))


def probe(kind, density, color, fa, fb, mis, seed, supervoxel=2):
    return helpers.segment_tracked_probe(kind, density, color, fa, fb, mis, ANCHOR[kind],
                                         N, seed, supervoxel, LAMBDAS)


def assert_mean(r, ref, i, tag):
    se = math.sqrt(max(r["var"][i], 0.0) / N)
    assert abs(r["mean"][i] - ref) <= 4.0 * se + 2e-3 * ref, (tag, i, r["mean"][i], ref, se)


@pytest.mark.parametrize("kind", ["slab", "step"])
@pytest.mark.parametrize("mis", [False, True])
@pytest.mark.parametrize("fa,fb", [(0.0, 1.0), (0.25, 0.75)])
def test_estimate_matches_closed_form(kind, mis, fa, fb):
    density = 0.6
    r = probe(kind, density, (0.5, 0.5, 0.5), fa, fb, mis, seed=1032 + int(mis) + int(8 * fa))
    a, b = 1.0 + 8.0 * fa, 1.0 + 8.0 * fb
    assert r["hull"] == pytest.approx([1.0, 9.0])
    for i in range(len(LAMBDAS)):
        ref = closed_form(kind, density, r["sigma_s_unit"][i], r["sigma_t_unit"][i], a, b)
        assert ref == pytest.approx(r["ref_integral"][i], rel=1e-3)   # quadrature sanity
        assert_mean(r, ref, i, (kind, mis, fa, fb))


@pytest.mark.parametrize("kind", ["oblique", "grid_hom", "two_grids"])
@pytest.mark.parametrize("mis", [False, True])
@pytest.mark.parametrize("fa,fb", [(0.0, 1.0), (0.3, 0.7)])
def test_estimate_matches_quadrature_oblique_and_overlaps(kind, mis, fa, fb):
    r = probe(kind, 1.5, (0.5, 0.5, 0.5), fa, fb, mis, seed=2032 + int(mis) + int(10 * fa))
    for i in range(len(LAMBDAS)):
        ref = r["ref_integral"][i]
        assert ref > 0.05, (kind, "fixture integral too small", ref)
        assert_mean(r, ref, i, (kind, mis, fa, fb))


@pytest.mark.parametrize("kind", ["slab", "step", "oblique", "grid_hom", "two_grids"])
def test_local_and_global_ratio_tracking_match_reference(kind):
    density = 0.6 if kind in REGION else 1.5
    r = probe(kind, density, (0.5, 0.5, 0.5), 0.0, 1.0, False, seed=7)
    for i in range(len(LAMBDAS)):
        ref = r["ref_tr"][i]
        if kind in REGION:
            r0, r1 = REGION[kind]
            assert ref == pytest.approx(math.exp(-density * r["sigma_t_unit"][i] * (r1 - r0)),
                                        rel=1e-3)
        for key in ("tr_local", "tr_global"):
            assert abs(r[key][i] - ref) <= 0.01 * ref + 2e-3, (kind, key, i, r[key][i], ref)


def test_reservoir_weights_sum_to_scatter_probability():
    density, fa, fb = 0.5, 0.25, 0.75
    r = probe("slab", density, (0.2, 0.2, 0.2), fa, fb, False, seed=11)
    sigma_bar = r["majorant"]
    su, st = r["sigma_s_unit"], r["sigma_t_unit"]
    # p_s = lane average of sigma_s / (sigma_s + sigma_n), sigma_n = sigma_bar - sigma_t.
    ps = sum(density * s / (density * s + sigma_bar - density * t) for s, t in zip(su, st)) / len(su)
    ref = 1.0 - math.exp(-sigma_bar * ps * 8.0 * (fb - fa))
    se = math.sqrt(ref * (1.0 - ref) / N)
    assert abs(r["wsum_mean"] - ref) <= 4.0 * se + 1e-3, (r["wsum_mean"], ref, se)
