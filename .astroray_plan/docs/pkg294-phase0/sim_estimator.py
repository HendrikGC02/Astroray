"""pkg294 Phase 0 analytic cross-check (numpy, engine-independent).

Per-sample relative variance of the textbook single-scatter segment NEE for the
centre-pixel camera ray of cube1 (equiangular-only / exponential-only distance,
area-uniform light point, HG g=0.55, homogeneous sigma_t = sigma_s). Compare
with the engines' 1-spp across-seed relVar. One-off; delete when pkg294 closes.
"""
import numpy as np

rng = np.random.default_rng(1)
N = 2_000_000
g, sig = 0.55, 4.0 * 0.96
cmin, cmax = np.array([-0.275, -0.275, 0.175]), np.array([0.275, 0.275, 0.725])
cam, tgt = np.array([0.0, -2.6, 0.75]), np.array([0.0, 0.0, 0.45])
d = (tgt - cam) / np.linalg.norm(tgt - cam)
Lc = np.array([0.0, 1.2, 0.9])
n = (tgt - Lc) / np.linalg.norm(tgt - Lc)          # lamp faces the cube centre
U = np.cross([0.0, 0.0, 1.0], -n); U /= np.linalg.norm(U)
V = np.cross(-n, U)
Wd, Hd = 1.5, 1.125
A = Wd * Hd


def slab(o, dirs):
    inv = 1.0 / np.where(np.abs(dirs) < 1e-12, 1e-12, dirs)
    t0, t1 = (cmin - o) * inv, (cmax - o) * inv
    return np.max(np.minimum(t0, t1), axis=-1), np.min(np.maximum(t0, t1), axis=-1)


a, b = (float(x[0]) for x in slab(cam[None], d[None]))


def hg(c):
    return (1 - g * g) / (4 * np.pi * (1 + g * g + 2 * g * c) ** 1.5)


def area_pts(k):
    u = rng.random((k, 2)) - 0.5
    return Lc + u[:, :1] * Wd * U + u[:, 1:] * Hd * V


def estimate(dist):
    if dist == "eq":
        anc = area_pts(N)
        tc = (anc - cam) @ d
        D = np.linalg.norm(anc - (cam + tc[:, None] * d), axis=1)
        thA, thB = np.arctan2(a - tc, D), np.arctan2(b - tc, D)
        t = tc + D * np.tan(thA + rng.random(N) * (thB - thA))
        pdf_t = D / ((thB - thA) * (D * D + (t - tc) ** 2))
    else:
        L = b - a
        t = a - np.log1p(-rng.random(N) * (-np.expm1(-sig * L))) / sig
        pdf_t = sig * np.exp(-sig * (t - a)) / (-np.expm1(-sig * L))
    P = cam + t[:, None] * d
    y = area_pts(N)
    wi = y - P
    r = np.linalg.norm(wi, axis=1)
    wi /= r[:, None]
    pdf_w = r * r / (A * np.maximum(-(wi @ n), 1e-9))
    tex = slab(P, wi)[1]
    f = np.exp(-sig * (t - a)) * sig * hg(-(wi @ d)) * np.exp(-sig * np.maximum(tex, 0.0))
    return f / (pdf_t * pdf_w)


for dist in ("eq", "exp"):
    e = estimate(dist)
    print(f"{dist:4s} area-draw  per-sample relVar {e.var() / e.mean() ** 2:.3f}")
