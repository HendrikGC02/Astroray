"""pkg109 — world-space photon-map kd-tree: C++ correctness vs a numpy oracle.

Validates the C++ `astroray::photon::PhotonMap` (balanced kd-tree build + k-NN
locate + Jensen 1996 density estimate) through the `_photon_map_knn_d2` /
`_photon_map_irradiance` test bindings against the same float64 brute-force
reference used by scripts/prototypes/pkg109_photon_map_prototype.py.

References: Jensen, "A Practical Guide to Global Illumination using Photon Maps",
SIGGRAPH 2000 Course 8, §2.2 (balanced kd-tree), §3.4 (locate_photons), §3.1
Eq. 8 (radiance/irradiance estimate). See
.astroray_plan/docs/pkg109-110-111-photon-map-research.md.
"""

import math

import numpy as np
import pytest

import astroray

pytestmark = pytest.mark.skipif(
    not hasattr(astroray, "_photon_map_knn_d2"),
    reason="photon-map test bindings not present — rebuild astroray.pyd (pkg109)",
)


def _brute_knn_d2(points, q, k):
    d2 = np.sum((points - q) ** 2, axis=1)
    return np.sort(d2)[:k]


def test_knn_matches_brute_force():
    """The C++ k-NN must return exactly the k nearest (by squared distance) as a
    numpy brute-force search, for many random queries (set + radii identical)."""
    rng = np.random.default_rng(20260529)
    n, k = 3000, 20
    points = rng.uniform(-5.0, 5.0, size=(n, 3))
    pts_list = points.tolist()
    big_radius = 1.0e6  # so the radius cap never clips — pure k-NN

    max_err = 0.0
    for _ in range(120):
        q = rng.uniform(-6.0, 6.0, size=3)
        cpp_d2 = np.asarray(
            astroray._photon_map_knn_d2(pts_list, q.tolist(), k, big_radius)
        )
        bf_d2 = _brute_knn_d2(points, q, k)
        assert cpp_d2.shape == bf_d2.shape, (cpp_d2.shape, bf_d2.shape)
        # squared distances are reorder-invariant; compare element-wise.
        max_err = max(max_err, float(np.max(np.abs(cpp_d2 - bf_d2))))
    # float32 kd-tree vs float64 oracle: distances agree to single-precision.
    assert max_err < 1e-3, f"k-NN squared-distance mismatch: {max_err:.3e}"


def test_knn_radius_cap():
    """With a small max_radius, only photons within that radius are returned."""
    rng = np.random.default_rng(7)
    points = rng.uniform(-5.0, 5.0, size=(2000, 3))
    q = np.array([0.0, 0.0, 0.0])
    radius = 1.0
    cpp_d2 = np.asarray(astroray._photon_map_knn_d2(points.tolist(), q.tolist(), 64, radius))
    bf_d2 = np.sum((points - q) ** 2, axis=1)
    within = np.sort(bf_d2[bf_d2 < radius * radius])[:64]
    assert cpp_d2.shape == within.shape
    assert np.max(cpp_d2) <= radius * radius + 1e-5


def test_irradiance_converges_to_areal_density():
    """Jensen Eq. 8 with unit-power photons on a plane recovers the true areal
    flux density N/A = (1/(pi r^2)) * sum over the k nearest."""
    rng = np.random.default_rng(20260529)
    side, npl, k = 4.0, 40000, 200
    plane = np.zeros((npl, 3))
    plane[:, 0] = rng.uniform(-side / 2, side / 2, size=npl)
    plane[:, 2] = rng.uniform(-side / 2, side / 2, size=npl)
    powers = np.ones((npl, 3))  # unit XYZ power per photon
    true_density = npl / (side * side)

    ests = []
    for x in (-1.0, 0.0, 1.0):
        X, Y, Z = astroray._photon_map_irradiance(
            plane.tolist(), powers.tolist(), [x, 0.0, 0.0], k, 1.0e6
        )
        ests.append(Y)
    rel_err = abs(np.mean(ests) - true_density) / true_density
    assert rel_err < 0.10, f"density estimate rel_err {rel_err:.3%} (true {true_density})"


def test_irradiance_empty_region_is_dark():
    """A query far from any photon (beyond max_radius) returns zero irradiance —
    this is what keeps the receiver dark outside the caustic band."""
    points = [[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.0, 0.0, 0.1]]
    powers = [[1.0, 1.0, 1.0]] * 3
    X, Y, Z = astroray._photon_map_irradiance(points, powers, [100.0, 0.0, 0.0], 8, 1.0)
    assert (X, Y, Z) == (0.0, 0.0, 0.0)
