"""pkg136 Stage 1A — directional quadtree (DTree) C++ port unit test.

Reproduces the numpy de-risking result (`.astroray_plan/docs/pkg136-stage1-
derisking.md`) against the actual C++ `astroray::guiding::DTree`
(include/astroray/guiding/dtree.h) bound in astroray_test_helpers. The same
hard-transport integrand and learn-then-sample training loop that validated the
algorithm in numpy is run here through the real primitives, asserting:

  1. the equal-area cylindrical map round-trips and its jacobian is 4π;
  2. the tree's square-measure pdf integrates to 1 (any topology);
  3. guide/BSDF MIS is unbiased and cuts variance by a large factor on the
     hard integrand (the pkg136 thesis) — the #1 de-risk gotcha (train from the
     evolving guide, not BSDF-only) is baked into the training loop.

Clean-room port of Müller 2017; OpenPGL (Apache-2.0) structural reference only.
"""

import math

import astroray_test_helpers as th
import numpy as np
import pytest

RNG = np.random.default_rng(20260905)

# ---- Hard-transport integrand (full-sphere; upper hemisphere is lit) --------
# Surface normal +z, Lambertian albedo/π BSDF. Incident radiance Li is a bright,
# NARROW spike about a near-grazing direction the cosine lobe mostly misses.
ALBEDO = 0.8
SPIKE_DIR = np.array([math.sin(1.3), 0.0, math.cos(1.3)])  # cosθ≈0.267, grazing
SPIKE_K = 60.0        # vMF-like concentration → narrow
SPIKE_A = 30.0        # peak radiance


def Li(w):
    return SPIKE_A * math.exp(SPIKE_K * (float(np.dot(w, SPIKE_DIR)) - 1.0))


def f_cos(w):
    """BSDF·cos for a Lambertian upper hemisphere (0 below the horizon)."""
    return (ALBEDO / math.pi) * w[2] if w[2] > 0.0 else 0.0


def p_bsdf_sa(w):
    """Cosine-hemisphere solid-angle pdf."""
    return (w[2] / math.pi) if w[2] > 0.0 else 0.0


def sample_bsdf():
    u1, u2 = RNG.random(), RNG.random()
    r = math.sqrt(u1)
    phi = 2.0 * math.pi * u2
    w = np.array([r * math.cos(phi), r * math.sin(phi), math.sqrt(max(0.0, 1.0 - u1))])
    return w, p_bsdf_sa(w)


# ---- Ground truth by dense hemisphere quadrature ---------------------------
def ground_truth():
    n_t, n_p = 800, 800
    total = 0.0
    for i in range(n_t):
        ct = (i + 0.5) / n_t            # cosθ ∈ (0,1)
        st = math.sqrt(1.0 - ct * ct)
        for j in range(n_p):
            phi = 2.0 * math.pi * (j + 0.5) / n_p
            w = np.array([st * math.cos(phi), st * math.sin(phi), ct])
            total += f_cos(w) * Li(w)
    # dω = dcosθ dφ, uniform grid over cosθ∈[0,1], φ∈[0,2π]
    return total * (1.0 / n_t) * (2.0 * math.pi / n_p)


def test_equal_area_map_roundtrip_and_jacobian():
    for _ in range(2000):
        v = RNG.normal(size=3)
        v /= np.linalg.norm(v)
        x, y = th.guiding_dir_to_square(*v)
        assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
        wx, wy, wz = th.guiding_square_to_dir(x, y)
        assert np.allclose([wx, wy, wz], v, atol=2e-3)
    assert th.GUIDING_SPHERE_JACOBIAN == pytest.approx(4.0 * math.pi, rel=1e-5)

    # Uniform points on the square ↔ uniform directions on the sphere: the mean
    # direction of many square-uniform samples is ~0 (isotropic).
    pts = RNG.random((40000, 2))
    dirs = np.array([th.guiding_square_to_dir(x, y) for x, y in pts])
    assert np.linalg.norm(dirs.mean(axis=0)) < 0.02


def _build_guide(iters=6, spi=6000, alpha=0.5, rho=0.008):
    """Learn-then-sample training with MIS draws from the evolving guide."""
    tree = th.DTree()
    for it in range(iters):
        if it > 0:
            tree.refine(rho)          # grow from previous flux (before reset)
        guide = None if it == 0 else tree.snapshot()   # frozen previous guide
        tree.reset()
        for _ in range(spi):
            if guide is None:
                w, pw = sample_bsdf()
            else:
                if RNG.random() < alpha:
                    gx, gy, _ = guide.sample(RNG.random(), RNG.random())
                    w = np.array(th.guiding_square_to_dir(gx, gy))
                else:
                    w, _ = sample_bsdf()
                pg = guide.pdf_dir(*w)
                pb = p_bsdf_sa(w)
                pw = alpha * pg + (1.0 - alpha) * pb
            if pw > 0.0:
                lv = Li(w)
                if lv > 0.0:
                    x, y = th.guiding_dir_to_square(*w)
                    tree.splat(x, y, lv / pw)
    return tree


def test_dtree_pdf_normalizes():
    tree = _build_guide(iters=5, spi=4000)
    assert tree.num_leaves() > 20          # it actually subdivided past the root
    # ∫ pdf over the unit square ≈ 1 (square measure), independent of topology.
    grid = 200
    s = 0.0
    for i in range(grid):
        for j in range(grid):
            s += tree.pdf((i + 0.5) / grid, (j + 0.5) / grid)
    s /= grid * grid
    assert s == pytest.approx(1.0, abs=0.05)


def _estimate(tree, alpha, n_trials=300, spp=64):
    """Return per-trial mean estimates of I for BSDF / guided / MIS."""
    truth = ground_truth()
    out = {"bsdf": [], "guided": [], "mis": []}
    for _ in range(n_trials):
        acc = {"bsdf": 0.0, "guided": 0.0, "mis": 0.0}
        for _ in range(spp):
            # BSDF-only
            w, pw = sample_bsdf()
            acc["bsdf"] += (f_cos(w) * Li(w) / pw) if pw > 0.0 else 0.0
            # guided-only
            gx, gy, _ = tree.sample(RNG.random(), RNG.random())
            w = np.array(th.guiding_square_to_dir(gx, gy))
            pg = tree.pdf_dir(*w)
            acc["guided"] += (f_cos(w) * Li(w) / pg) if pg > 0.0 else 0.0
            # MIS(guide, bsdf)
            if RNG.random() < alpha:
                gx, gy, _ = tree.sample(RNG.random(), RNG.random())
                w = np.array(th.guiding_square_to_dir(gx, gy))
            else:
                w, _ = sample_bsdf()
            pm = alpha * tree.pdf_dir(*w) + (1.0 - alpha) * p_bsdf_sa(w)
            acc["mis"] += (f_cos(w) * Li(w) / pm) if pm > 0.0 else 0.0
        for k, val in acc.items():
            out[k].append(val / spp)
    return truth, {k: np.array(v) for k, v in out.items()}


def test_guided_mis_unbiased_and_variance_reduction():
    alpha = 0.5
    tree = _build_guide(iters=6, spi=6000, alpha=alpha)
    truth, est = _estimate(tree, alpha)

    var_bsdf = est["bsdf"].var()
    var_mis = est["mis"].var()

    # (a) MIS is unbiased — mean converges to the reference (BSDF is the noisy
    #     unbiased control, so it agrees too, just with huge variance).
    assert abs(est["mis"].mean() - truth) / truth < 0.08, (
        f"MIS biased: {est['mis'].mean():.5f} vs truth {truth:.5f}"
    )
    assert abs(est["bsdf"].mean() - truth) / truth < 0.20  # control, high variance

    # (b) MIS cuts variance by a large factor on the hard integrand (numpy
    #     de-risk got ~110×; assert a conservative ≥10× so the C++ port is
    #     clearly delivering the thesis, not marginal).
    assert var_mis * 10.0 < var_bsdf, (
        f"variance reduction too small: bsdf={var_bsdf:.3e} mis={var_mis:.3e} "
        f"ratio={var_bsdf / max(var_mis, 1e-30):.1f}×"
    )
