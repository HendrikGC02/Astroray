"""pkg268 — brute-force numpy reference for heterogeneous volume transport.

An INDEPENDENT ray-march oracle (not the engine's estimators): piecewise-constant
nearest-voxel σ_t sampled on a dense grid, identity transforms (index space ==
world space) so ``world_point -> voxel = floor(p) - bbox_min``.

Model matches the pkg268 engine scope: scalar σ_t = extinction * density(p);
scattering albedo is spectral (RGB) and enters only at a scatter. Used by
``tests/test_pkg268_heterogeneous_reference.py`` and ``..._volume_nee.py``.
"""

import numpy as np


def nearest_density(grid_nzyx, bbox_min, p):
    """Nearest-voxel density at world point p (identity transform). 0 outside."""
    ix = int(round(p[0])) - bbox_min[0]
    iy = int(round(p[1])) - bbox_min[1]
    iz = int(round(p[2])) - bbox_min[2]
    nz, ny, nx = grid_nzyx.shape
    if 0 <= ix < nx and 0 <= iy < ny and 0 <= iz < nz:
        return float(grid_nzyx[iz, iy, ix])
    return 0.0


def _aabb_overlap(o, d, mn, mx, t_lo, t_hi):
    t0, t1 = t_lo, t_hi
    for a in range(3):
        if abs(d[a]) < 1e-12:
            if o[a] < mn[a] or o[a] > mx[a]:
                return None
        else:
            inv = 1.0 / d[a]
            tn = (mn[a] - o[a]) * inv
            tf = (mx[a] - o[a]) * inv
            if tn > tf:
                tn, tf = tf, tn
            t0 = max(t0, tn)
            t1 = min(t1, tf)
            if t0 > t1:
                return None
    return t0, t1


def transmittance_raymarch(grid_nzyx, bbox_min, extinction, o, d,
                           t_min, t_max, n_steps=4000):
    """Grey transmittance exp(-∫ σ_t ds) via fine midpoint ray-march (unit d)."""
    o = np.asarray(o, dtype=np.float64)
    d = np.asarray(d, dtype=np.float64)
    dt = (t_max - t_min) / n_steps
    tau = 0.0
    for i in range(n_steps):
        t = t_min + (i + 0.5) * dt
        p = o + d * t
        tau += extinction * nearest_density(grid_nzyx, bbox_min, p) * dt
    return float(np.exp(-tau))


def phase_hg(cos_theta, g):
    denom = max(1.0 + g * g + 2.0 * g * cos_theta, 1e-6)
    return (0.25 / np.pi) * (1.0 - g * g) / (denom * np.sqrt(denom))


def single_scatter_raymarch(grid_nzyx, bbox_min, extinction, albedo_rgb, g,
                            o, d, aabb_min, aabb_max, light_pos, light_rgb,
                            n_steps=4000):
    """Single-scattering in-scatter radiance (RGB) along a camera ray through a
    bounded medium, lit by a point light with radiant intensity ``light_rgb``
    (falloff 1/dist²). Independent ray-march oracle for the NEE / single-scatter
    gate.
    """
    o = np.asarray(o, dtype=np.float64)
    d = np.asarray(d, dtype=np.float64)
    ov = _aabb_overlap(o, d, aabb_min, aabb_max, 1e-4, 1e9)
    if ov is None:
        return np.zeros(3)
    t0, t1 = ov
    dt = (t1 - t0) / n_steps
    albedo = np.asarray(albedo_rgb, dtype=np.float64)
    Lrgb = np.asarray(light_rgb, dtype=np.float64)
    out = np.zeros(3)
    for i in range(n_steps):
        t = t0 + (i + 0.5) * dt
        x = o + d * t
        sig_t = extinction * nearest_density(grid_nzyx, bbox_min, x)
        if sig_t <= 0.0:
            continue
        # transmittance camera -> x
        tr_cam = transmittance_raymarch(grid_nzyx, bbox_min, extinction, o, d,
                                        t0, t, n_steps=max(1, int((t - t0) / dt)))
        to_light = light_pos - x
        dist = np.linalg.norm(to_light)
        wl = to_light / dist
        # transmittance x -> light (only the part inside the AABB matters)
        ovl = _aabb_overlap(x, wl, aabb_min, aabb_max, 1e-4, dist)
        if ovl is None:
            tr_light = 1.0
        else:
            a0, a1 = ovl
            tr_light = transmittance_raymarch(grid_nzyx, bbox_min, extinction,
                                              x, wl, a0, a1,
                                              n_steps=max(1, int((a1 - a0) / dt)))
        cos_theta = float(np.dot(-d, wl))
        ph = phase_hg(cos_theta, g)
        sig_s = sig_t * albedo  # RGB
        out += tr_cam * sig_s * ph * tr_light * (Lrgb / (dist * dist)) * dt
    return out
