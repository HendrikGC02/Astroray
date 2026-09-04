#!/usr/bin/env python
"""pkg227 Phase 2b-flat solver oracle — the flat-triangle specular-polynomial
solver matches the EXACT analytic sphere solver over a fine tessellation.

Pure-numpy, CI-runnable (no build). This is the algorithm-level gate for
`include/astroray/manifold/mesh_specular_poly.h`: the C++ solver is a line-for-
line port of `flat_triangle_specular` below, and the sphere oracle here is the
same numpy mirror the LANDED pkg127 sphere solver is validated against
(`tests/test_pkg127_specular_poly_unit.py`). Full de-risking (convergence order,
superfluous-root accounting, the eta-direction gotcha) lives in
`.astroray_plan/docs/pkg227-phase2b-research.md` /
`scratchpad/proto_mesh_specular.py`.

Asserts, over 4 configurations (refraction / reflection / multi-branch /
SF11-dispersion), for every analytic-sphere root:
  1. ORACLE MATCH: the flat-triangle solver on a fine local tessellation finds
     the specular vertex to < 1e-4 rad (the pkg227 gate).
  2. SUPERFLUOUS-ROOT FILTER: the signed-residual + in-triangle filter removes
     the squared-form spurious roots (survivors << raw roots).
  3. ETA CONVENTION: inverting eta (the plausible-but-wrong n_to/n_from) breaks
     the oracle match for the refractive cases — locking the port's convention.
"""
from __future__ import annotations

import numpy as np
from numpy.polynomial import polynomial as P

TWO_PI = 2.0 * np.pi


def _unit(v):
    return v / np.linalg.norm(v)


# --- sphere oracle (verbatim structure from test_pkg127_specular_poly_unit) ---
def _plane_basis(x0, x2, c):
    a, b = np.asarray(x0, float) - c, np.asarray(x2, float) - c
    e1 = _unit(a)
    npl = _unit(np.cross(a, b))
    e2 = np.cross(npl, e1)
    return e1, e2, np.array([a @ e1, a @ e2]), np.array([b @ e1, b @ e2])


def _sphere_resid(ct, st, a, b, r, eta):
    p = r * np.array([ct, st])
    Ci, Co = a[1] * ct - a[0] * st, b[1] * ct - b[0] * st
    Ri, Ro = np.linalg.norm(a - p), np.linalg.norm(b - p)
    if Ri < 1e-12 or Ro < 1e-12:
        return 1e9
    return Ci / Ri + eta * Co / Ro


def _sphere_roots_theta(a, b, r, eta):
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
            if abs(_sphere_resid(np.cos(th), np.sin(th), a, b, r, eta)) < 1e-4:
                thetas.append(th)
    out = []
    for x in sorted((y + np.pi) % TWO_PI - np.pi for y in thetas):
        if not out or abs(x - out[-1]) > 1e-3:
            out.append(x)
    return out


def sphere_oracle_vertices(x0, x2, center, radius, eta):
    x0, x2, center = (np.asarray(v, float) for v in (x0, x2, center))
    e1, e2, a, b = _plane_basis(x0, x2, center)
    return [center + radius * _unit(np.cos(th) * e1 + np.sin(th) * e2)
            for th in _sphere_roots_theta(a, b, radius, eta)]


# --- flat-triangle solver (numpy mirror of mesh_specular_poly.h) ---
def flat_triangle_specular(x0, x2, P0, P1, P2, eta, invert_eta=False):
    if invert_eta:
        eta = 1.0 / eta
    x0, x2 = np.asarray(x0, float), np.asarray(x2, float)
    P0, P1, P2 = np.asarray(P0, float), np.asarray(P1, float), np.asarray(P2, float)
    e1v, e2v = P1 - P0, P2 - P0
    N = np.cross(e1v, e2v)
    if np.linalg.norm(N) < 1e-14:
        return []
    N = _unit(N)
    w = np.cross(x2 - x0, N)
    k = float(np.cross(x0, x2) @ N)
    c1, c2, rhs = float(e1v @ w), float(e2v @ w), k - float(P0 @ w)
    if abs(c1) < 1e-14 and abs(c2) < 1e-14:
        return []
    if np.linalg.norm(w) < 1e-14:
        return []
    param_is_u = abs(c2) > 1e-10
    if param_is_u:
        def p_of_t(t):
            v = (rhs - c1 * t) / c2
            return P0 + t * e1v + v * e2v, (t, v)
    else:
        def p_of_t(t):
            u = (rhs - c2 * t) / c1
            return P0 + u * e1v + t * e2v, (u, t)
    eb1 = _unit(x2 - x0)
    eb2 = np.cross(_unit(w), eb1)
    pA, _ = p_of_t(0.0)
    pB, _ = p_of_t(1.0)
    p0 = np.array([(pA - x0) @ eb1, (pA - x0) @ eb2])
    p1 = np.array([(pB - x0) @ eb1, (pB - x0) @ eb2])
    dpx, dpy = p1 - p0
    px0, py0 = p0
    b2 = np.array([(x2 - x0) @ eb1, (x2 - x0) @ eb2])
    n2 = np.array([N @ eb1, N @ eb2])
    Ci = np.array([n2[0] * (-py0) - n2[1] * (-px0), n2[0] * (-dpy) - n2[1] * (-dpx)])
    Co = np.array([n2[0] * (b2[1] - py0) - n2[1] * (b2[0] - px0), Ci[1]])
    Ri2 = np.array([px0**2 + py0**2, 2 * (px0 * dpx + py0 * dpy), dpx**2 + dpy**2])
    Ro2 = np.array([(b2[0] - px0)**2 + (b2[1] - py0)**2,
                    -2 * ((b2[0] - px0) * dpx + (b2[1] - py0) * dpy),
                    dpx**2 + dpy**2])
    poly = P.polysub(P.polymul(P.polymul(Ci, Ci), Ro2),
                     eta * eta * P.polymul(P.polymul(Co, Co), Ri2))

    def g(t):
        p2 = np.array([px0 + t * dpx, py0 + t * dpy])
        Ci_ = n2[0] * (-p2[1]) - n2[1] * (-p2[0])
        Co_ = n2[0] * (b2[1] - p2[1]) - n2[1] * (b2[0] - p2[0])
        Ri_, Ro_ = np.linalg.norm(p2), np.linalg.norm(b2 - p2)
        if Ri_ < 1e-12 or Ro_ < 1e-12:
            return 1e9
        return Ci_ / Ri_ + eta * Co_ / Ro_

    if not np.any(np.abs(poly) > 1e-14):
        return []
    sols, raw = [], 0
    for z in P.polyroots(np.trim_zeros(poly, 'b')):
        if abs(z.imag) > 1e-6 * (1 + abs(z.real)):
            continue
        raw += 1
        t = float(z.real)
        for _ in range(4):
            h = 1e-5
            dg = (g(t + h) - g(t - h)) / (2 * h)
            if abs(dg) < 1e-9:
                break
            t -= g(t) / dg
        if abs(g(t)) > 1e-3:
            continue
        p3d, (u, v) = p_of_t(t)
        if u < -1e-6 or v < -1e-6 or (u + v) > 1 + 1e-6:
            continue
        if not any(np.linalg.norm(p3d - s['position']) < 1e-5 for s in sols):
            sols.append({'position': p3d, 'normal': N.copy(), 'raw': raw})
    return sols


def _icosphere(subdiv, radius=1.0):
    t = (1.0 + np.sqrt(5.0)) / 2.0
    verts = [_unit(v) for v in np.array([
        [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t],
        [0, -1, -t], [0, 1, -t], [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]],
        dtype=float)]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9),
             (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2),
             (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10),
             (8, 6, 7), (9, 8, 1)]
    cache = {}

    def mid(i, j):
        key = (min(i, j), max(i, j))
        if key not in cache:
            verts.append(_unit((verts[i] + verts[j]) * 0.5))
            cache[key] = len(verts) - 1
        return cache[key]

    for _ in range(subdiv):
        nf = []
        for i0, i1, i2 in faces:
            a, b, c = mid(i0, i1), mid(i1, i2), mid(i2, i0)
            nf += [(i0, a, c), (a, i1, b), (c, b, i2), (a, b, c)]
        faces = nf
    return np.array(verts) * radius, np.array(faces, dtype=int)


def _ang_err(p_est, p_true, center):
    return float(np.arccos(np.clip(_unit(p_est - center) @ _unit(p_true - center), -1, 1)))


def _drill(x0, x2, eta, op, center, radius, levels=20, beam=6, invert_eta=False):
    V, F = _icosphere(3, 1.0)
    fc = V[F].mean(axis=1)
    tris = [tuple(V[F[fi]]) for fi in np.argsort(np.linalg.norm(fc - op, axis=1))[:beam]]
    best = None
    for _ in range(levels):
        for P0, P1, P2 in tris:
            for s in flat_triangle_specular(x0, x2, P0, P1, P2, eta, invert_eta=invert_eta):
                e = _ang_err(s['position'], op, center)
                best = e if best is None else min(best, e)
        nt = []
        for P0, P1, P2 in tris:
            ab, bc, ca = _unit((P0 + P1) / 2), _unit((P1 + P2) / 2), _unit((P2 + P0) / 2)
            nt += [(P0, ab, ca), (ab, P1, bc), (ca, bc, P2), (ab, bc, ca)]
        cens = np.array([_unit(sum(tr) / 3) for tr in nt])
        tris = [nt[i] for i in np.argsort(np.linalg.norm(cens - op, axis=1))[:beam]]
    return best


CASES = [
    ("refraction", [-3.0, 1.2, 0.4], [2.5, 2.0, -0.6], 1.0 / 1.52),
    ("reflection", [-2.0, 2.0, 0.0], [2.0, 2.0, 0.3], 1.0),
    ("multi-branch", [-1.8, 0.5, 0.0], [1.8, 0.5, 0.0], 1.0 / 1.52),
    ("SF11", [-2.5, 1.5, 0.7], [2.2, 1.1, -0.3], 1.0 / 1.78),
]
CENTER, RADIUS = np.zeros(3), 1.0


def test_flat_triangle_matches_sphere_oracle():
    """Every analytic-sphere specular vertex is reproduced by the flat-triangle
    solver on a fine tessellation to < 1e-4 rad (the pkg227 gate)."""
    worst = 0.0
    matched = 0
    for label, x0, x2, eta in CASES:
        oracle = sphere_oracle_vertices(x0, x2, CENTER, RADIUS, eta)
        assert oracle, f"[{label}] oracle found no roots"
        for op in oracle:
            err = _drill(x0, x2, eta, op, CENTER, RADIUS)
            assert err is not None, f"[{label}] no flat-triangle solution near oracle vertex"
            assert err < 1e-4, f"[{label}] err {err:.3e} rad exceeds 1e-4 gate"
            worst = max(worst, err)
            matched += 1
    assert matched >= 8, f"expected >= 8 oracle roots across cases, matched {matched}"
    assert worst < 1e-4


def test_superfluous_root_filter_removes_spurious():
    """The squared-form quartic emits spurious roots; the signed-residual +
    in-triangle filter removes them. Across a subdiv=5 sweep of the 25 facets
    nearest each oracle vertex, only the handful of facets actually CONTAINING a
    vertex survive (most of the ~200 facet-solves have their roots filtered as
    superfluous or out-of-triangle) — and every survivor is a real vertex, not a
    squaring artifact."""
    V, F = _icosphere(5, 1.0)
    fc = V[F].mean(axis=1)
    survivors = []
    for label, x0, x2, eta in CASES:
        oracle = sphere_oracle_vertices(x0, x2, CENTER, RADIUS, eta)
        for op in oracle:
            for fi in np.argsort(np.linalg.norm(fc - op, axis=1))[:25]:
                for s in flat_triangle_specular(x0, x2, *V[F[fi]], eta):
                    survivors.append(_ang_err(s['position'], op, CENTER))
    # Filter does real work: a vertex is inside only a couple of the 25 nearest
    # facets, so survivors are FEW relative to the ~200 facet-solves per config.
    assert 1 <= len(survivors) <= 30, f"unexpected survivor count {len(survivors)}"
    # Every survivor is a genuine near-vertex (subdiv=5 edge ~0.02 -> err <~0.02),
    # never a spurious far-off squaring root.
    assert max(survivors) < 0.05, f"a survivor was far from any oracle vertex ({max(survivors):.3f})"


def test_eta_inversion_breaks_refraction_match():
    """Locks the eta convention (research note §3): passing eta UNMODIFIED
    matches the oracle; the plausible n_to/n_from inversion silently fails the
    refractive cases. Guards the top port risk."""
    _label, x0, x2, eta = CASES[0]  # refraction generic
    op = sphere_oracle_vertices(x0, x2, CENTER, RADIUS, eta)[0]
    correct = _drill(x0, x2, eta, op, CENTER, RADIUS, invert_eta=False)
    inverted = _drill(x0, x2, eta, op, CENTER, RADIUS, invert_eta=True)
    assert correct is not None and correct < 1e-4, f"correct convention err {correct}"
    # Inverted convention converges to a DIFFERENT specular point (or none) — it
    # never reproduces this oracle vertex; the gap must be orders of magnitude.
    assert inverted is None or inverted > 100 * correct, (
        f"eta inversion did NOT diverge as expected (correct={correct}, inverted={inverted})")


if __name__ == "__main__":
    test_flat_triangle_matches_sphere_oracle()
    test_superfluous_root_filter_removes_spurious()
    test_eta_inversion_breaks_refraction_match()
    print("pkg227 Phase 2b-flat oracle: all checks PASS")
