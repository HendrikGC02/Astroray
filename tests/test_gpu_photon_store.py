#!/usr/bin/env python
"""pkg113 Phase 1 — GPU photon STORE + query vs a numpy float64 brute-force oracle.

Validates the GPU uniform spatial hash grid (pbrt-v3 sppm.cpp ToGrid/hash, plus
the Jensen 2000 §3.1 Eq. 8 fixed-radius irradiance estimate) through the
`_gpu_photon_store_query` binding against the SAME brute-force reference used by
tests/test_photon_map.py for the CPU kd-tree.

Store decision: uniform spatial hash grid, NOT a CUDA kd-tree
(packages/pkg113-gpu-photon-map-caustics.md Decisions §2; owner 2026-05-30).

The hash grid returns the EXACT in-radius neighbor SET (set-match, deterministic)
and a density estimate matching the numpy oracle to single precision. This is the
Phase-1 acceptance: "GPU store gather vs CPU (Phase 1) — aggregate energy bound".

GPU-gated: skips gracefully when CUDA is absent (CI has no GPU); /verify runs this
on the RTX box. Mirrors the skip pattern of tests/test_pkg64_gpu_cpu_parity.py:41-46.

References: Jensen 2000 Course 8 §3.1 Eq. 8; pbrt-v3 src/integrators/sppm.cpp
(BSD-2-Clause). See .astroray_plan/docs/pkg113-gpu-photon-store-research.md.
"""

from __future__ import annotations

import numpy as np
import pytest

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip(
        "CUDA feature not in this build — pkg113 Phase 1 GPU photon store needs "
        "CUDA; /verify runs this on the RTX box.",
        allow_module_level=True,
    )

if AVAILABLE and not hasattr(astroray, "_gpu_photon_store_query"):
    pytest.skip(
        "GPU photon-store binding not present — rebuild astroray.pyd (pkg113).",
        allow_module_level=True,
    )


# float32 (GPU) vs float64 (oracle) can disagree on a photon sitting within an
# ULP-thin shell of the radius boundary — that is a precision tie, not a store
# bug. We compare the set EXACTLY for photons clearly inside/outside the radius
# and tolerate disagreement only inside a narrow boundary shell. Same idea as
# test_photon_map.py comparing squared distances to a 1e-3 tolerance.
_BOUNDARY_REL = 1e-4  # shell half-width as a fraction of radius^2


def _brute_in_radius_sets(points, q, radius):
    """Return (definitely_in, ambiguous): index sets that are unambiguously
    inside the radius vs within the float-precision boundary shell."""
    d2 = np.sum((points - q) ** 2, axis=1)
    r2 = radius * radius
    shell = _BOUNDARY_REL * r2
    definitely_in = set(np.where(d2 < r2 - shell)[0].tolist())
    ambiguous = set(np.where(np.abs(d2 - r2) <= shell)[0].tolist())
    return definitely_in, ambiguous


def test_radius_neighbor_set_matches_brute_force():
    """The GPU hash-grid in-radius neighbor set must match a numpy brute-force
    radius search for every photon outside the float-precision boundary shell,
    over many random queries (deterministic set away from the boundary)."""
    rng = np.random.default_rng(20260530)
    n = 4000
    points = rng.uniform(-5.0, 5.0, size=(n, 3))
    powers = np.ones((n, 3))
    radius = 0.6

    queries = rng.uniform(-5.0, 5.0, size=(64, 3))
    results = astroray._gpu_photon_store_query(
        points.tolist(), powers.tolist(), queries.tolist(), radius, 4096
    )
    assert len(results) == len(queries)

    mismatches = 0
    for qi, (_E, gpu_idx, found) in enumerate(results):
        gpu_set = set(int(v) for v in gpu_idx)
        # No duplicates in the returned set (the cell-id de-dup must hold).
        assert len(gpu_set) == len(list(gpu_idx)), (
            f"query {qi}: duplicate indices returned"
        )
        definitely_in, ambiguous = _brute_in_radius_sets(points, queries[qi], radius)
        # Every clearly-inside photon must be present.
        missing = definitely_in - gpu_set
        # Every returned photon must be either clearly-inside or boundary-ambiguous.
        extra = gpu_set - definitely_in - ambiguous
        if missing or extra:
            mismatches += 1
    assert mismatches == 0, f"{mismatches}/{len(queries)} neighbor-set mismatches"


def test_irradiance_matches_disk_area_density():
    """Jensen Eq. 8 fixed-radius estimate on the GPU must match the numpy
    oracle E = (1/(pi r^2)) * sum(power within r) to single precision."""
    rng = np.random.default_rng(7)
    n = 3000
    points = rng.uniform(-4.0, 4.0, size=(n, 3))
    powers = rng.uniform(0.1, 2.0, size=(n, 3))
    radius = 0.8

    queries = rng.uniform(-4.0, 4.0, size=(48, 3))
    results = astroray._gpu_photon_store_query(
        points.tolist(), powers.tolist(), queries.tolist(), radius, 4096
    )

    norm = np.pi * radius * radius
    max_rel = 0.0
    for qi, (E, _idx, _found) in enumerate(results):
        d2 = np.sum((points - queries[qi]) ** 2, axis=1)
        mask = d2 < radius * radius
        bf_E = powers[mask].sum(axis=0) / norm  # XYZ
        E = np.asarray(E, dtype=np.float64)
        denom = np.maximum(np.abs(bf_E), 1e-6)
        max_rel = max(max_rel, float(np.max(np.abs(E - bf_E) / denom)))
    assert max_rel < 1e-3, f"irradiance rel-err {max_rel:.3e} exceeds 1e-3"


def test_irradiance_converges_to_areal_density():
    """Unit-power photons on a dense plane recover the true areal flux density
    N/A within the fixed-radius footprint — same convergence check as the CPU
    test_photon_map.py::test_irradiance_converges_to_areal_density."""
    rng = np.random.default_rng(20260530)
    side, npl = 4.0, 40000
    plane = np.zeros((npl, 3))
    plane[:, 0] = rng.uniform(-side / 2, side / 2, size=npl)
    plane[:, 2] = rng.uniform(-side / 2, side / 2, size=npl)
    powers = np.ones((npl, 3))
    true_density = npl / (side * side)
    radius = 0.25  # small vs the plane so the disk lies inside it

    queries = np.array([[-1.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    results = astroray._gpu_photon_store_query(
        plane.tolist(), powers.tolist(), queries.tolist(), radius, 65536
    )
    ests = [E[1] for (E, _idx, _found) in results]  # Y channel
    rel_err = abs(np.mean(ests) - true_density) / true_density
    assert rel_err < 0.10, f"density estimate rel_err {rel_err:.3%} (true {true_density})"


def test_empty_region_is_dark():
    """A query far from any photon (beyond radius) returns zero irradiance and
    an empty neighbor set — keeps the receiver dark outside the caustic band."""
    points = [[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.0, 0.0, 0.1]]
    powers = [[1.0, 1.0, 1.0]] * 3
    results = astroray._gpu_photon_store_query(
        points, powers, [[100.0, 0.0, 0.0]], 1.0, 16
    )
    E, idx, found = results[0]
    assert found == 0
    assert list(idx) == []
    assert tuple(E) == (0.0, 0.0, 0.0)
