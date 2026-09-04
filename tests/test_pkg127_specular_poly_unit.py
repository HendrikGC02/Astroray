#!/usr/bin/env python
"""pkg127 unit — Specular-Polynomials sphere seed finding (numeric oracle).

Locks the math behind include/astroray/manifold/specular_poly.h with a pure-numpy
reimplementation of the SAME sphere single-vertex derivation, and proves the two
properties pkg127 is built to deliver:

  1. COMPLETENESS: the degree-6 polynomial's real roots (after superfluous-root
     filtering) enumerate EVERY specular vertex a brute-force angular scan finds.
  2. Newton-from-one-seed MISSES branches the polynomial finds — the "one
     solution per seed" failure mode (Fan et al. 2024 §1; SMS Zeltner 2020 §4.4).

Re-derived from the CC BY 4.0 paper (arXiv:2405.13409); no engine build needed,
runs on CI. The C++ solver is validated against this same oracle by the
standalone harness recorded in the pkg127 research note.
"""
from __future__ import annotations

import numpy as np
from numpy.polynomial import polynomial as P


def _unit(v):
    return v / np.linalg.norm(v)


def _plane(x0, x2, c):
    a, b = np.asarray(x0, float) - c, np.asarray(x2, float) - c
    e1 = _unit(a)
    npl = _unit(np.cross(a, b))
    e2 = np.cross(npl, e1)
    return (np.array([a @ e1, a @ e2]), np.array([b @ e1, b @ e2]))


def _signed_residual(theta, a, b, r, eta):
    ct, st = np.cos(theta), np.sin(theta)
    p = r * np.array([ct, st])
    Ci, Co = a[1] * ct - a[0] * st, b[1] * ct - b[0] * st
    return Ci / np.linalg.norm(a - p) + eta * Co / np.linalg.norm(b - p)


def _brute_roots(a, b, r, eta, n=200000):
    th = np.linspace(-np.pi, np.pi, n, endpoint=False)
    g = np.array([_signed_residual(t, a, b, r, eta) for t in th])
    out = []
    for i in range(len(th)):
        if g[i] * g[(i + 1) % len(th)] < 0:
            lo, hi = th[i], th[i] + 2 * np.pi / n
            for _ in range(60):
                m = 0.5 * (lo + hi)
                if _signed_residual(lo, a, b, r, eta) * _signed_residual(m, a, b, r, eta) <= 0:
                    hi = m
                else:
                    lo = m
            out.append(0.5 * (lo + hi))
    return out


def _poly_roots(a, b, r, eta):
    one, t2 = np.array([1.0]), P.polypow([0.0, 1.0], 2)
    D, Cn, Sn = P.polyadd(one, t2), P.polysub(one, t2), np.array([0.0, 2.0])
    Ci = P.polysub(P.polymul([a[1]], Cn), P.polymul([a[0]], Sn))
    Co = P.polysub(P.polymul([b[1]], Cn), P.polymul([b[0]], Sn))
    adot = P.polyadd(P.polymul([a[0]], Cn), P.polymul([a[1]], Sn))
    bdot = P.polyadd(P.polymul([b[0]], Cn), P.polymul([b[1]], Sn))
    a2, b2, r2 = float(a @ a), float(b @ b), r * r
    Ri2 = P.polysub(P.polymul([a2 + r2], D), P.polymul([2 * r], adot))
    Ro2 = P.polysub(P.polymul([b2 + r2], D), P.polymul([2 * r], bdot))
    poly = P.polysub(P.polymul(P.polymul(Ci, Ci), Ro2),
                     P.polymul([eta * eta], P.polymul(P.polymul(Co, Co), Ri2)))
    thetas = []
    for z in P.polyroots(np.trim_zeros(poly, 'b')):
        if abs(z.imag) < 1e-6 * (1 + abs(z.real)):
            th = 2.0 * np.arctan(z.real)
            if abs(_signed_residual(th, a, b, r, eta)) < 1e-4:  # drop superfluous
                thetas.append(th)
    # dedup near-double roots
    out = []
    for x in sorted((y + np.pi) % (2 * np.pi) - np.pi for y in thetas):
        if not out or abs(x - out[-1]) > 1e-3:
            out.append(x)
    return out


def _newton_one_seed(a, b, r, eta):
    th = np.arctan2(a[1], a[0])  # seed at the sphere point facing x0
    for _ in range(20):
        g = _signed_residual(th, a, b, r, eta)
        if abs(g) < 1e-6:
            return (th + np.pi) % (2 * np.pi) - np.pi
        h = 1e-4
        dg = (_signed_residual(th + h, a, b, r, eta) -
              _signed_residual(th - h, a, b, r, eta)) / (2 * h)
        if abs(dg) < 1e-12:
            return None
        th -= g / dg
    return None


CASES = [
    ("refraction generic", [-3.0, 1.2, 0.4], [2.5, 2.0, -0.6], 1.0 / 1.52),
    ("reflection Alhazen", [-2.0, 2.0, 0.0], [2.0, 2.0, 0.3], 1.0),
    ("multi-branch",       [-1.8, 0.5, 0.0], [1.8, 0.5, 0.0], 1.0 / 1.52),
    ("SF11 dispersion",    [-2.5, 1.5, 0.7], [2.2, 1.1, -0.3], 1.0 / 1.78),
]


def test_poly_roots_match_brute_force():
    for label, x0, x2, eta in CASES:
        a, b = _plane(x0, x2, [0, 0, 0])
        brute = sorted((y + np.pi) % (2 * np.pi) - np.pi for y in _brute_roots(a, b, 1.0, eta))
        poly = _poly_roots(a, b, 1.0, eta)
        assert len(poly) == len(brute), f"{label}: {len(poly)} poly vs {len(brute)} brute"
        for o in brute:
            assert min(abs(o - p) for p in poly) < 1e-3, f"{label}: missed root {o:.5f}"


def test_polynomial_finds_branches_newton_misses():
    """The headline pkg127 property: on multi-solution configs the polynomial
    enumerates all branches while Newton-from-one-seed reaches at most one."""
    any_missed = False
    for label, x0, x2, eta in CASES:
        a, b = _plane(x0, x2, [0, 0, 0])
        poly = _poly_roots(a, b, 1.0, eta)
        nt = _newton_one_seed(a, b, 1.0, eta)
        n_newton = 0 if nt is None else 1
        assert len(poly) >= n_newton
        if len(poly) > n_newton:
            any_missed = True
    assert any_missed, "expected at least one config where Newton misses a branch"
