"""pkg136 Stage 1A — spatial binary tree (SDTree) de-risk + C++ port unit test.

De-risks the spatial half of the SD-tree (the piece the directional de-risk note
flagged as "still to de-risk"): point-count leaf split, leaf lookup from a world
point, directional-tree inheritance on split, and — the point of the whole
spatial cache — that two spatially-separated shade regions with *different*
incident-radiance spikes learn *different* directional guides.

Drives the real C++ astroray::guiding::SDTree (include/astroray/guiding/sdtree.h)
bound in astroray_test_helpers. Clean-room port of Müller 2017; OpenPGL
(Apache-2.0) structural reference only.
"""

import astroray_test_helpers as th
import numpy as np

RNG = np.random.default_rng(20260905)


def _unit_sphere_sample():
    v = RNG.normal(size=3)
    return v / np.linalg.norm(v)


def test_leaf_lookup_covers_space_and_contains_point():
    mn, mx = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]
    tree = th.SDTree(mn, mx)
    # Force splits: dump many samples into one sub-region so it exceeds threshold.
    for _ in range(500):
        p = [RNG.random() * 0.4, RNG.random() * 0.4, RNG.random() * 0.4]
        w = _unit_sphere_sample()
        tree.record(p, w[0], w[1], w[2], 1.0)
    tree.refine(spatial_threshold=100, dir_rho=0.01)
    assert tree.num_leaves() > 1  # it split

    # Every probe point maps to a leaf whose AABB actually contains it.
    for _ in range(2000):
        p = [RNG.random(), RNG.random(), RNG.random()]
        b = tree.leaf_bounds(p)
        assert b[0] <= p[0] <= b[3]
        assert b[1] <= p[1] <= b[4]
        assert b[2] <= p[2] <= b[5]


def test_split_inherits_directional_tree():
    """After a spatial split, both children start from the parent's learned
    guide. A quadtree only concentrates over several refine-then-resplat
    iterations (the de-risk finding), so we first train the root to concentration
    (spatial_threshold huge → no spatial split), THEN force one spatial split and
    verify the children carry the parent's spike."""
    mn, mx = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]
    tree = th.SDTree(mn, mx)
    spike = np.array([0.0, 0.0, 1.0])

    def train_pass():
        tree.reset_iteration()
        for _ in range(5000):
            p = [RNG.random(), RNG.random(), RNG.random()]
            w = spike + 0.15 * RNG.normal(size=3)
            w /= np.linalg.norm(w)
            tree.record(p, w[0], w[1], w[2], 1.0)

    # Concentrate the (single) root leaf's directional tree over 5 iterations,
    # refining directions only (huge spatial threshold ⇒ no spatial split yet).
    train_pass()
    for _ in range(5):
        tree.refine(spatial_threshold=10**9, dir_rho=0.01)
        train_pass()
    assert tree.num_leaves() == 1  # not split yet

    # Now force ONE spatial split; children inherit the concentrated tree. Do NOT
    # reset afterwards, so the inherited flux is what gets sampled.
    tree.refine(spatial_threshold=100, dir_rho=0.01)
    assert tree.num_leaves() >= 2

    # Two points now in different leaves both still prefer the +z spike.
    for p in ([0.1, 0.1, 0.1], [0.9, 0.9, 0.9]):
        hits = 0
        for _ in range(3000):
            wx, wy, wz, _ = tree.sample_dir(p, RNG.random(), RNG.random())
            if np.dot([wx, wy, wz], spike) > 0.85:
                hits += 1
        assert hits / 3000 > 0.5, f"inherited guide lost the spike at {p}: {hits/3000:.2f}"


def _train_two_region(iters=5, spi_per_region=3000):
    """Two regions (low-x, high-x) with different spikes; learn-then-sample."""
    mn, mx = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]
    tree = th.SDTree(mn, mx)
    spike_lo = np.array([0.0, 0.0, 1.0])        # region x<0.5 → +z
    spike_hi = np.array([0.0, 0.0, -1.0])       # region x>0.5 → -z
    for it in range(iters):
        if it > 0:
            tree.refine(spatial_threshold=200, dir_rho=0.01)
        tree.reset_iteration()
        for region, spike in ((0.0, spike_lo), (0.5, spike_hi)):
            for _ in range(spi_per_region):
                p = [region + RNG.random() * 0.5, RNG.random(), RNG.random()]
                w = spike + 0.12 * RNG.normal(size=3)
                w /= np.linalg.norm(w)
                tree.record(p, w[0], w[1], w[2], 1.0)
    return tree, spike_lo, spike_hi


def test_spatial_regions_specialise_to_different_guides():
    """The core spatial-cache property: region A samples A's spike, not B's."""
    tree, spike_lo, spike_hi = _train_two_region()
    assert tree.num_leaves() >= 2, "spatial tree never split the two regions apart"

    def frac_toward(p, spike, n=4000):
        hits = 0
        for _ in range(n):
            wx, wy, wz, _ = tree.sample_dir(p, RNG.random(), RNG.random())
            if np.dot([wx, wy, wz], spike) > 0.8:
                hits += 1
        return hits / n

    p_lo, p_hi = [0.2, 0.5, 0.5], [0.8, 0.5, 0.5]
    lo_to_lo = frac_toward(p_lo, spike_lo)
    lo_to_hi = frac_toward(p_lo, spike_hi)
    hi_to_hi = frac_toward(p_hi, spike_hi)
    hi_to_lo = frac_toward(p_hi, spike_lo)

    # Each region overwhelmingly samples its OWN spike and rarely the other's.
    assert lo_to_lo > 0.6, f"low region didn't learn +z: {lo_to_lo:.2f}"
    assert hi_to_hi > 0.6, f"high region didn't learn -z: {hi_to_hi:.2f}"
    assert lo_to_hi < 0.1, f"low region leaked to -z: {lo_to_hi:.2f}"
    assert hi_to_lo < 0.1, f"high region leaked to +z: {hi_to_lo:.2f}"
