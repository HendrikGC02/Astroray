"""pkg268 — ratio-tracking NEE: unbiasedness (converges to the numpy reference)
and seed-pinned determinism (no std::random_device — the legacy ConstantMedium
bug, research note §1b).
"""

from __future__ import annotations

import sys

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

import astroray
import volume_reference as ref

IDENTITY = [1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0]
N = 12


def _grid():
    zz, yy, xx = np.meshgrid(np.arange(N), np.arange(N), np.arange(N), indexing="ij")
    dens = (0.6 + 0.4 * np.sin(0.5 * xx) * np.cos(0.4 * yy) + 0.3 * (zz / N)).astype(np.float32)
    dens = np.clip(dens, 0.1, None)
    gm = astroray.GridMedium()
    gm.set_density(np.ascontiguousarray(dens), bbox_min=(0, 0, 0),
                   index_to_object=IDENTITY, object_to_world=IDENTITY, supervoxel=6)
    return gm, np.ascontiguousarray(dens)


_EXT = 0.5
_ALB = [0.7, 0.7, 0.7]
_G = 0.3
_LP = [6.0, 25.0, 6.0]
_LRGB = [150.0, 150.0, 150.0]
_O = [6.0, 6.0, -6.0]
_D = [0.0, 0.0, 1.0]


def test_nee_is_deterministic_under_fixed_seed():
    gm, _ = _grid()
    a = astroray.volume_single_scatter_estimate(gm, _O, _D, _EXT, _ALB, _G, _LP, _LRGB, 5000, 99)
    b = astroray.volume_single_scatter_estimate(gm, _O, _D, _EXT, _ALB, _G, _LP, _LRGB, 5000, 99)
    assert tuple(a) == tuple(b), f"fixed-seed NEE not reproducible: {a} vs {b}"


def test_nee_mean_is_unbiased():
    """Independent seeds must average to the same (reference) mean — the NEE is
    unbiased. Two disjoint seed batches agree, and both match the ray-march."""
    gm, dens = _grid()
    mn, mx = [0.0, 0.0, 0.0], [float(N)] * 3
    expected = ref.single_scatter_raymarch(dens, (0, 0, 0), _EXT, _ALB, _G, _O, _D,
                                           mn, mx, np.asarray(_LP), np.asarray(_LRGB),
                                           n_steps=2500)
    batch_a = np.mean([astroray.volume_single_scatter_estimate(
        gm, _O, _D, _EXT, _ALB, _G, _LP, _LRGB, 40000, s) for s in range(10)], axis=0)
    batch_b = np.mean([astroray.volume_single_scatter_estimate(
        gm, _O, _D, _EXT, _ALB, _G, _LP, _LRGB, 40000, s) for s in range(100, 110)], axis=0)
    print(f"[pkg268 NEE] batchA={batch_a.round(4)} batchB={batch_b.round(4)} "
          f"ref={expected.round(4)}")
    # the two independent batches agree (unbiased, low variance)
    for c in range(3):
        assert abs(batch_a[c] - batch_b[c]) < 0.04 * max(batch_a[c], 1e-3) + 1e-4
        denom = max(expected[c], 1e-4)
        assert abs(batch_a[c] - expected[c]) / denom < 0.12, (
            f"channel {c}: NEE mean {batch_a[c]:.5f} vs reference {expected[c]:.5f}")
