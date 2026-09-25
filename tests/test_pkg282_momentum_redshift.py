"""pkg282 — momentum-based thin-disk redshift and the pkg107 shadow-size offset.

Gate 1: disk redshift asymmetry delta = (g_R - g_L)/(g_R + g_L) of the
gr-kerr-94-faceon geometry (camera exactly edge-on, i=90) matches the frozen
GYOTO 2.0.2 values from pkg280 Phase 3 (astra_run/batchB-phase3/phase3_metrics.json)
within 5 %. The old sin(i)*sin(phi) formula gave delta ~ 0 here.
Gate 2: the a=0 capture radius matches the closed-form finite-camera mapping
(camera at D*r_obs/R M in the flat exterior), which explains pkg107's "0.37x".
"""

import math

import numpy as np
import pytest

helpers = pytest.importorskip("astroray_test_helpers")
assert hasattr(helpers, "gr_disk_redshift_image"), (
    "astroray_test_helpers lacks gr_disk_redshift_image; rebuild the pkg282 target")

N = 512
BAND = slice(248, 264)
# GYOTO 2.0.2 (94863d06), KerrBL, ThinDiskPL 6..18 M, i=90, Distance 48 M, 45 deg, 512^2.
GYOTO_DELTA = {0.0: 0.21560704644608786, 0.94: 0.20290409819826027}


def _probe(spin, r_obs=20.0, n=N):
    raw = helpers.gr_disk_redshift_image(
        [0.0, 0.0, 12.0], [0.0, 0.0, 0.0], 45.0, n, n, [0.0, 0.0, 0.0],
        5.0, 18.0, r_obs, spin)
    return np.asarray(raw, dtype=np.float64).reshape(n, n, 2)[..., 0]


@pytest.mark.parametrize("spin", [0.0, 0.94])
def test_edge_on_redshift_asymmetry_matches_gyoto(spin):
    g = _probe(spin)[BAND, :]
    left, right = g[:, : N // 2], g[:, N // 2:]
    g_l, g_r = np.median(left[left > 0]), np.median(right[right > 0])
    delta = (g_r - g_l) / (g_r + g_l)
    mismatch = abs(delta - GYOTO_DELTA[spin]) / GYOTO_DELTA[spin]
    assert g_r > 1.0 > g_l, (g_l, g_r)  # approaching (image right) side blueshifted
    assert mismatch <= 0.05, f"a={spin}: delta {delta:.4f} vs GYOTO {GYOTO_DELTA[spin]:.4f}"


@pytest.mark.parametrize("r_obs", [20.0, 40.0])
def test_shadow_radius_matches_finite_camera_closed_form(r_obs):
    d, r_inf, fov = 12.0, 5.0, 45.0
    bc = 3.0 * math.sqrt(3.0)

    def excess(t):  # b(theta) - b_crit; see buildInitialState's null condition
        sa = d * math.sin(t) / r_inf
        return d * r_obs / r_inf * math.sin(t) / math.sqrt(1.0 - 2.0 / r_obs * sa * sa) - bc

    lo, hi = 1e-9, math.asin(r_inf / d) - 1e-9
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if excess(mid) < 0.0 else (lo, mid)
    predicted = math.tan(lo) / math.tan(math.radians(fov / 2)) * N / 2
    captured = _probe(0.0, r_obs) < 0.0
    measured = math.sqrt(captured.sum() / math.pi)
    assert abs(measured / predicted - 1.0) <= 0.01, (measured, predicted)
