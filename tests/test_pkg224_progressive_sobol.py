"""
pkg224 -- Progressive (hash-Owen Sobol') sampler unit tests.

The sampler (include/astroray/sampling/progressive_sobol_device.h) is a single
__host__/__device__ source, so the host build exercised here is byte-identical
to the CUDA device build used by the GPU shade kernel. Pinning the host output
therefore validates the GPU sampler's math directly.

Coverage:
1. test_sobol_matches_scipy      -- the direction-vector table + direct Sobol'
   construction are byte-exact vs the authoritative scipy.stats.qmc.Sobol
   (Joe & Kuo 2008), for every table dimension.
2. test_owen_scramble_reversible -- FastOwenScrambler is a bijection (pins the
   pbrt-v4 port).
3. test_progressive_uniform      -- scrambled draws are uniform in [0,1) and
   per-pixel decorrelated.
4. test_prefix_progressive_property / test_convergence_beats_white_noise --
   the progressive prefix property: for a smooth test integral, the sampler's
   error decreases faster than the PCG32 white-noise 1/sqrt(N) (Sobol'-class).

GPU-side byte-identical-default and flag-on behaviour live in
test_pkg224_progressive_sobol_gpu.py (skipped without CUDA).
"""

import numpy as np
import pytest

th = pytest.importorskip("astroray_test_helpers")


def _sobol_direct_seq(dim, n):
    return np.array([th.sobol_direct(i, dim) for i in range(n)], dtype=np.uint32)


def test_sobol_matches_scipy():
    """C++ direct Sobol' == scipy Joe-Kuo, via the gray-code bijection
    scipy[n] == direct(n ^ (n>>1)) (scipy emits gray-code order, pbrt/Astroray
    emit direct index order -- same point set, verified per dimension)."""
    qmc = pytest.importorskip("scipy.stats").qmc
    N = 512
    ndims = int(th.SOBOL_NUM_DIMS)
    gray = np.array([n ^ (n >> 1) for n in range(N)], dtype=np.int64)
    worst = 0
    for d in range(ndims):
        mine = _sobol_direct_seq(d, N).astype(np.float64) / 2.0**32
        sci = qmc.Sobol(d=d + 1, scramble=False).random(N)[:, d]
        worst = max(worst, float(np.max(np.abs(mine[gray] - sci))))
    # scipy uses 30 direction bits; our 32-bit fixed point matches to 2^-30.
    assert worst < 2.0**-29, f"max deviation {worst} exceeds Sobol' 30-bit tol"


def test_owen_scramble_reversible():
    """FastOwenScrambler with a fixed seed is a bijection on a sample of the
    32-bit domain (each reversible op is a permutation)."""
    seed = 0x9e3779b9
    xs = np.random.default_rng(0).integers(0, 2**32, size=4096, dtype=np.uint64)
    ys = {int(th.fast_owen_scramble(int(x), seed)) for x in xs}
    assert len(ys) == len(xs), "FastOwenScrambler collided -> not a bijection"


def test_progressive_uniform():
    """Owen-scrambled draws fill [0,1) uniformly and different pixels get
    decorrelated sequences (the per-(pixel,dim) scramble seed)."""
    n = 4096
    a = np.array([th.progressive_sobol_sample(7, i, 0, 0) for i in range(n)])
    b = np.array([th.progressive_sobol_sample(99, i, 0, 0) for i in range(n)])
    assert a.min() >= 0.0 and a.max() < 1.0
    # Stratified mean is very close to 0.5 (much tighter than white noise).
    assert abs(a.mean() - 0.5) < 0.01
    # 16-bin chi-square-ish uniformity: every bin within 30% of n/16.
    hist, _ = np.histogram(a, bins=16, range=(0, 1))
    assert hist.min() > (n / 16) * 0.7 and hist.max() < (n / 16) * 1.3
    # Distinct pixels are decorrelated (low correlation of paired sequences).
    corr = np.corrcoef(a, b)[0, 1]
    assert abs(corr) < 0.1, f"pixel sequences correlated (r={corr})"


def _integrate(sampler, npix, n):
    """RMSE of a smooth 2D integral estimate over `npix` independent pixels,
    each using n samples. f(x,y)=exp(-(x+y)), exact = (1-e^-1)^2."""
    exact = (1.0 - np.exp(-1.0)) ** 2
    errs = []
    for p in range(npix):
        xs, ys = sampler(p, n)
        est = np.mean(np.exp(-(xs + ys)))
        errs.append(est - exact)
    return float(np.sqrt(np.mean(np.square(errs))))


def _progressive_sampler(p, n):
    xs = np.array([th.progressive_sobol_sample(p, i, 0, 0) for i in range(n)])
    ys = np.array([th.progressive_sobol_sample(p, i, 1, 0) for i in range(n)])
    return xs, ys


def _white_sampler(p, n):
    xs = np.empty(n)
    ys = np.empty(n)
    for i in range(n):
        r = th.WavefrontRNG(p, i, 0)
        xs[i] = r.Uniform()
        ys[i] = r.Uniform()
    return xs, ys


def test_convergence_beats_white_noise():
    """Progressive error is well below white-noise error at matched sample
    counts on a smooth integrand (the whole point of a low-discrepancy set)."""
    npix = 256
    for n in (256, 1024):
        e_prog = _integrate(_progressive_sampler, npix, n)
        e_white = _integrate(_white_sampler, npix, n)
        assert e_prog < 0.5 * e_white, (
            f"n={n}: progressive RMSE {e_prog:.2e} not < 0.5*white {e_white:.2e}")


def test_prefix_progressive_property():
    """The progressive prefix property: error keeps dropping across prefixes and
    the convergence rate is steeper than white noise's -0.5 slope."""
    npix = 256
    ns = np.array([64, 256, 1024, 4096])
    errs = np.array([_integrate(_progressive_sampler, npix, int(n)) for n in ns])
    # Monotone improvement across the whole prefix chain.
    assert np.all(np.diff(errs) < 0), f"prefix errors not monotone: {errs}"
    # Fitted log-log slope steeper (more negative) than -0.5 (white noise).
    slope = np.polyfit(np.log(ns), np.log(errs), 1)[0]
    assert slope < -0.75, f"convergence slope {slope:.2f} not better than sqrt(N)"
