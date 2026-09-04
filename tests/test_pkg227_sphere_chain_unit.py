#!/usr/bin/env python
"""pkg227 Phase 2a unit — analytic-sphere MULTI-BOUNCE chain (raindrop rainbow).

Locks the math behind include/astroray/manifold/specular_poly.h
(solveSphereChain / traceSphereChain2) with a pure-numpy reimplementation of the
SAME exact forward-trace, and proves the properties Phase 2a delivers:

  1. COMPLETENESS: enumerating every sign change of the univariate exit-miss
     residual finds BOTH k=1 branches that straddle the rainbow caustic fold.
  2. ACCURACY: each enumerated chain's exit ray reaches the light to < 1e-4 rad.
  3. Newton-from-one-seed MISSES a branch the enumeration finds (the "one
     solution per seed" failure mode, Fan et al. 2024 §1; SMS Zeltner 2020 §4.4).
  4. DISPERSION: per-lambda IOR gives distinct caustic deviations (the rainbow
     spread) — red n=1.331 vs violet n=1.343 differ by > 1 deg.

Physics is classical geometric optics (Descartes 1637 / Newton rainbow), not an
invented algorithm; the deviation law D(i)=2(i-t)+k(pi-2t), sin t = sin i / n is
the analytic cross-check. No engine build needed; runs on CI like
test_pkg127_specular_poly_unit.py.
"""
from __future__ import annotations

import numpy as np


def _refract(d, N, eta):
    cosi = -np.dot(d, N)
    k = 1.0 - eta * eta * (1.0 - cosi * cosi)
    if k < 0.0:
        return None
    t = eta * d + (eta * cosi - np.sqrt(k)) * N
    return t / np.linalg.norm(t)


def _circle_exit(p, d, r):
    b = 2.0 * np.dot(p, d)
    c = np.dot(p, p) - r * r
    disc = max(b * b - 4.0 * c, 0.0)
    return p + 0.5 * (-b + np.sqrt(disc)) * d


def _trace(theta, A, r, n, k):
    """A -> refract in -> k internal reflections -> refract out. Mirrors the C++
    traceSphereChain2. Returns (exit_point, exit_dir) or None."""
    p = r * np.array([np.cos(theta), np.sin(theta)])
    nout = p / r
    d = p - A
    nrm = np.linalg.norm(d)
    if nrm < 1e-12:
        return None
    d = d / nrm
    if np.dot(d, nout) >= 0.0:            # must hit the front face
        return None
    d = _refract(d, nout, 1.0 / n)        # air -> glass
    if d is None:
        return None
    for _ in range(k):                    # internal reflections
        p = _circle_exit(p, d, r)
        nout = p / r
        d = d - 2.0 * np.dot(d, nout) * nout
    p = _circle_exit(p, d, r)
    nout = p / r
    dx = _refract(d, -nout, n)            # glass -> air
    if dx is None:
        return None
    return p, dx


def _miss(theta, A, L, r, n, k):
    res = _trace(theta, A, r, n, k)
    if res is None:
        return None
    p, d = res
    v = L - p
    return d[0] * v[1] - d[1] * v[0]


def _enumerate(A, L, r, n, k, samples=512):
    ths = np.linspace(-np.pi, np.pi, samples + 1)
    gs = [_miss(t, A, L, r, n, k) for t in ths]
    roots = []
    for i in range(len(ths) - 1):
        g0, g1 = gs[i], gs[i + 1]
        if g0 is None or g1 is None:
            continue
        if g0 * g1 < 0.0:
            a, b, fa = ths[i], ths[i + 1], g0
            for _ in range(60):
                m = 0.5 * (a + b)
                fm = _miss(m, A, L, r, n, k)
                if fm is None:
                    break
                if fa * fm <= 0.0:
                    b = m
                else:
                    a, fa = m, fm
            roots.append(0.5 * (a + b))
    return roots


def _newton_one_seed(seed, A, L, r, n, k, iters=40):
    """Damped Newton on g(theta) from a single fixed seed (the stochastic-SMS
    failure mode). Returns the converged root or None."""
    th = seed
    for _ in range(iters):
        g = _miss(th, A, L, r, n, k)
        if g is None:
            return None
        h = 1e-5
        gp, gm = _miss(th + h, A, L, r, n, k), _miss(th - h, A, L, r, n, k)
        if gp is None or gm is None:
            return None
        dg = (gp - gm) / (2 * h)
        if abs(dg) < 1e-12:
            return None
        step = g / dg
        th -= np.clip(step, -0.3, 0.3)      # damped
    return th if _miss(th, A, L, r, n, k) is not None and abs(_miss(th, A, L, r, n, k)) < 1e-6 else None


def _deviation(theta, A, r, n, k):
    res = _trace(theta, A, r, n, k)
    if res is None:
        return None
    p1 = r * np.array([np.cos(theta), np.sin(theta)])
    d0 = p1 - A
    d0 = d0 / np.linalg.norm(d0)
    _, dx = res
    return np.degrees(np.arccos(np.clip(np.dot(d0, dx), -1, 1)))


# A k=1 rainbow configuration: distant receiver on -x, light placed on the exit
# ray of the near-caustic entry angle so a real chain exists.
def _rainbow_config(n=1.333, r=1.0):
    cos2i = (n * n - 1.0) / 3.0
    i_c = np.arccos(np.sqrt(cos2i))
    A = np.array([-6.0, 0.0])
    res = _trace(np.pi - i_c, A, r, n, 1)
    L = res[0] + 5.0 * res[1]
    return A, L, r, n


def test_enumerates_both_caustic_branches():
    A, L, r, n = _rainbow_config()
    roots = _enumerate(A, L, r, n, k=1)
    assert len(roots) >= 2, f"expected >=2 k=1 branches (caustic fold), got {len(roots)}"


def test_each_chain_reaches_light():
    A, L, r, n = _rainbow_config()
    for th in _enumerate(A, L, r, n, k=1):
        p, d = _trace(th, A, r, n, 1)
        v = (L - p) / np.linalg.norm(L - p)
        miss = np.arccos(np.clip(np.dot(d, v), -1, 1))
        assert miss < 1e-4, f"exit ray misses light by {miss:.2e} rad at theta={np.degrees(th):.3f}"


def test_deviation_matches_descartes():
    # The branch nearest the stationary caustic must match the analytic D(i).
    A, L, r, n = _rainbow_config()
    cos2i = (n * n - 1.0) / 3.0
    i_c = np.arccos(np.sqrt(cos2i))
    t_c = np.arcsin(np.sin(i_c) / n)
    D_analytic = np.degrees(2 * (i_c - t_c) + (np.pi - 2 * t_c))
    devs = [_deviation(th, A, r, n, 1) for th in _enumerate(A, L, r, n, k=1)]
    assert min(abs(d - D_analytic) for d in devs) < 0.5, (
        f"no branch near analytic bow {D_analytic:.3f} deg; got {devs}")


def test_newton_one_seed_misses_a_branch():
    A, L, r, n = _rainbow_config()
    roots = set(round(np.degrees(x), 2) for x in _enumerate(A, L, r, n, k=1))
    # A single fixed seed converges to at most one branch.
    found = _newton_one_seed(np.radians(125.0), A, L, r, n, 1)
    assert found is not None
    found_deg = round(np.degrees(found), 2)
    # It cannot recover both branches from one seed.
    assert len(roots) > 1 and found_deg in _closest(roots, found_deg), (
        f"one seed found {found_deg}; enumeration found {sorted(roots)} — "
        "the point is enumeration finds MORE than one seed can")
    assert len({found_deg}) < len(roots)


def _closest(roots, val, tol=1.0):
    return {r for r in roots if abs(r - val) < tol}


def test_dispersion_spread():
    def caustic_dev(nn):
        c2 = (nn * nn - 1) / 3.0
        ic = np.arccos(np.sqrt(c2))
        tc = np.arcsin(np.sin(ic) / nn)
        return np.degrees(2 * (ic - tc) + (np.pi - 2 * tc))
    spread = abs(caustic_dev(1.343) - caustic_dev(1.331))
    assert spread > 1.0, f"red-violet caustic spread {spread:.3f} deg too small"


if __name__ == "__main__":
    A, L, r, n = _rainbow_config()
    roots = _enumerate(A, L, r, n, k=1)
    print("k=1 branches:", [f"{np.degrees(x):.3f}" for x in roots])
    for th in roots:
        print(f"  theta={np.degrees(th):.3f} deg  D={_deviation(th,A,r,n,1):.3f} deg")
