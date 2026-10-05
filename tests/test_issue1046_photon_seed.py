"""#1046 -- CPU photon-map emission is seeded from the resolved render seed.

Seed 0 is the engine's random sentinel (Renderer::resolveCameraGroup draws a fresh
seed per render). The CPU photon map used ``12345 ^ (seed * 0x9E3779B9)``, which for
seed 0 is the constant 12345: every 'random' render traced the identical caustic
photon pattern. Gates: two seed-0 maps differ; two maps with the same non-zero seed
are identical; different non-zero seeds still differ (#959 decorrelation).
"""

from __future__ import annotations

import pytest

import test_959_caustic_photon_split as t

pytestmark = pytest.mark.skipif(not t.AVAILABLE, reason="astroray not built")


def _map_fingerprint(seed):
    _, r = t._lum(True, False, 1, seed)
    s = r.get_integrator_stats()
    assert s.get("pm_ready") == 1.0 and s.get("pm_stored_photons", 0) > 1000, s
    return (s["pm_stored_photons"], s["pm_flux_y"], s["pm_gather_radius"])


def test_seed_zero_photon_maps_differ():
    assert _map_fingerprint(0) != _map_fingerprint(0), "seed-0 photon map is identical across renders"


def test_fixed_seed_photon_maps_are_identical():
    assert _map_fingerprint(7) == _map_fingerprint(7)


def test_different_fixed_seeds_give_different_maps():
    assert _map_fingerprint(7) != _map_fingerprint(8)
