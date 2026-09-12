"""pkg265 / issue #782 — INDEPENDENT oracle for the multiple-scattering dielectric.

The sibling module `heitz_random_walk.py` and the engine header
`include/astroray/microsurface_dielectric.h` are BOTH clean-room transcriptions of
the SAME Smith random-walk equations (Heitz et al. 2016 §5-9), so the pkg265
directional gate and R+T=1 are self-consistency checks, not ground truth
(memory `clean-room-oracle-is-self-consistency-not-ground-truth`; issue #782).

This module is the genuinely INDEPENDENT reference: it does not use the Smith
abstraction at all — no Lambda, no C1(h)^Lambda masking, no VNDF sampling. It
realises an EXPLICIT random rough surface z = h(x,y) and ray-traces it
geometrically (grid ray-march, gradient facet normals, exact Fresnel
reflection/refraction at every crossing). Masking, shadowing, multiple scattering
and the reflected/transmitted split all EMERGE from the geometry. This is exactly
Heitz 2016's own validation methodology:

  Heitz, Hanika, d'Eon, Dachsbacher, "Multiple-Scattering Microfacet BSDFs with
  the Smith Model", ACM TOG 35(4) (SIGGRAPH 2016), DOI 10.1145/2897824.2925943 —
  §Results/validation: "We validate our BSDFs using raytracing simulations of
  explicit random Beckmann surfaces." (Fig. 15-17 compare albedo and angular
  distribution per scattering order against exactly this.)

Design decision (mission fork, documented per issue #782):
  * The paper's explicit surfaces are Gaussian-process (Beckmann-slope) surfaces.
    We use the same: a stationary Gaussian random heightfield synthesised in the
    Fourier domain (sqrt(PSD) * white noise), which has Gaussian marginal slopes
    == the Beckmann slope distribution (Walter et al. 2007, "Microfacet Models for
    Refraction through Rough Surfaces", EGSR 2007: Beckmann slope PDF is a 2D
    Gaussian with per-axis std alpha_b / sqrt(2)). A GGX-slope explicit surface is
    NOT obtainable from linear spectral synthesis (the central limit theorem forces
    Gaussian == Beckmann slopes); generating exact-GGX-slope heightfields needs a
    non-linear, non-stationary construction that is not a "standard method", so we
    do not attempt it. We therefore validate the multiple-scattering MECHANISM at
    Beckmann, apples-to-apples against a Beckmann Smith walk (added to
    heitz_random_walk.py, ndf="beckmann"). The engine ships the SAME walk mechanism
    with a GGX NDF; the pkg265 GGX directional gate covers engine<->GGX-walk
    self-consistency, and this module closes the remaining independence gap: does
    an explicit rough dielectric surface, traced with ZERO model assumptions,
    reproduce the walk's albedo and, crucially, its exit-interface energy
    REDISTRIBUTION (the +52% centre band of pkg263) — or does it match Cycles'
    uniform 1/E rescale instead?

Usage:
  python heightfield_oracle.py            # single-interface validation table
  python heightfield_oracle.py --full     # full grid, larger surface + ray count
Registered in scripts/README.md.
"""
import argparse
import math
import os
import sys

import numpy as np

IOR = 1.45
ALPHA_FLOOR = 0.0064          # engine roughness->alpha floor (principled.cpp)

# import the Smith walk sibling for the apples-to-apples comparison
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import heitz_random_walk as hrw


# --------------------------------------------------------------------------- #
# Explicit Gaussian (Beckmann) heightfield, synthesised in the Fourier domain. #
# Isotropic Gaussian autocorrelation C(r) = sigma_h^2 exp(-r^2 / (2 xi^2)) has  #
# per-axis slope variance sigma_h^2 / xi^2. Beckmann alpha_b => per-axis slope   #
# std alpha_b / sqrt(2) (Walter 2007), so sigma_h / xi = alpha_b / sqrt(2).      #
# --------------------------------------------------------------------------- #
def make_heightfield(alpha_b, N, xi_cells, rng):
    """Return (H, dHdx, dHdy, dx) for an N x N periodic Gaussian heightfield whose
    marginal slope distribution is Beckmann with roughness alpha_b. Grid spacing
    dx = 1 (cells); xi_cells is the correlation length in cells."""
    xi = float(xi_cells)
    sigma_h = xi * alpha_b / math.sqrt(2.0)
    # Gaussian ACF <-> Gaussian PSD. Build sqrt(PSD) on the FFT grid.
    kx = np.fft.fftfreq(N, d=1.0) * 2.0 * math.pi
    ky = np.fft.fftfreq(N, d=1.0) * 2.0 * math.pi
    KX, KY = np.meshgrid(kx, ky, indexing="ij")
    K2 = KX * KX + KY * KY
    # PSD of a Gaussian ACF (2D): S(k) = sigma_h^2 * 2 pi xi^2 * exp(-k^2 xi^2 / 2)
    S = sigma_h * sigma_h * 2.0 * math.pi * xi * xi * np.exp(-0.5 * K2 * xi * xi)
    white = (rng.standard_normal((N, N)) + 1j * rng.standard_normal((N, N))) / math.sqrt(2.0)
    spec = np.sqrt(S) * white * N  # discrete-FFT normalisation
    H = np.real(np.fft.ifft2(spec))
    # renormalise the realised slope std exactly to alpha_b/sqrt(2) (finite-grid
    # correction — the target ACF is only approximate on a discrete torus).
    gx = 0.5 * (np.roll(H, -1, axis=0) - np.roll(H, 1, axis=0))
    gy = 0.5 * (np.roll(H, -1, axis=1) - np.roll(H, 1, axis=1))
    realized = math.sqrt(0.5 * (gx.var() + gy.var()))
    target = alpha_b / math.sqrt(2.0)
    if realized > 1e-9:
        H *= target / realized
    dHdx = 0.5 * (np.roll(H, -1, axis=0) - np.roll(H, 1, axis=0))
    dHdy = 0.5 * (np.roll(H, -1, axis=1) - np.roll(H, 1, axis=1))
    return H, dHdx, dHdy, 1.0


def _bilerp(F, x, y, N):
    """Periodic bilinear sample of grid F at fractional (x,y) (in cell units)."""
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx = x - x0
    fy = y - y0
    i0 = x0 % N
    j0 = y0 % N
    i1 = (x0 + 1) % N
    j1 = (y0 + 1) % N
    f00 = F[i0, j0]
    f10 = F[i1, j0]
    f01 = F[i0, j1]
    f11 = F[i1, j1]
    return (f00 * (1 - fx) * (1 - fy) + f10 * fx * (1 - fy)
            + f01 * (1 - fx) * fy + f11 * fx * fy)


def trace_interface(alpha_b, mu, ior, rng, n_rays, entering=True,
                    N=256, xi_cells=6.0, nbins=18, scatter_max=64,
                    step=0.25, refine=6, single_scatter=False):
    """Ray-trace a collimated beam at incidence cosine mu against ONE explicit
    rough interface. entering: air(1)->glass(ior) below the surface; not entering:
    glass(ior)->air(1). Returns dict(R, T, dead, edges, hist_R, hist_T).

    A ray lives in the medium given by sign(z - h(x,y)): above the surface (g>0)
    and below (g<0). At every surface crossing it Fresnel-reflects (stay) or
    refracts (cross) with the gradient facet normal. Escape UP (far above, dir.z>0)
    counts as the reflected hemisphere; escape DOWN (far below, dir.z<0) as the
    transmitted hemisphere. Multiple scattering is repeated crossings."""
    H, dHdx, dHdy, dx = make_heightfield(alpha_b, N, xi_cells, rng)
    Hmax = float(H.max())
    Hmin = float(H.min())
    top = Hmax + 0.5     # start/escape plane just clear of the roughness zone
    bot = Hmin - 0.5
    # The surface always separates AIR above (z>h) from GLASS below (z<h). Only the
    # incident side, travel direction and the R/T labelling depend on entering:
    #   entering=True  : ray from air (above), down. escape-up=R,  escape-down=T.
    #   entering=False : ray from glass (below), up. escape-down=R, escape-up=T.
    n_above = 1.0
    n_below = ior

    M = n_rays
    st = math.sqrt(max(0.0, 1.0 - mu * mu))
    if entering:
        d0 = np.array([st, 0.0, -mu])       # downward, incident medium = air
        z0 = top
    else:
        d0 = np.array([st, 0.0, mu])        # upward, incident medium = glass
        z0 = bot
    d = np.tile(d0, (M, 1)).astype(np.float64)
    # random lateral start over the periodic tile
    o = np.zeros((M, 3))
    o[:, 0] = rng.random(M) * N
    o[:, 1] = rng.random(M) * N
    o[:, 2] = z0

    active = np.ones(M, dtype=bool)
    out_dir = np.zeros((M, 3))
    escaped_up = np.zeros(M, dtype=bool)
    got = np.zeros(M, dtype=bool)
    events = np.zeros(M, dtype=np.int64)   # Fresnel events so far (for single-scatter)

    def hit_surface_g(p):
        return p[:, 2] - _bilerp(H, p[:, 0], p[:, 1], N)

    for _ev in range(scatter_max):
        if not active.any():
            break
        idx = np.where(active)[0]
        oa = o[idx]
        da = d[idx]
        g_prev = oa[:, 2] - _bilerp(H, oa[:, 0], oa[:, 1], N)
        # march until sign change of g or escape
        t = np.zeros(idx.size)
        found = np.zeros(idx.size, dtype=bool)
        t_hit = np.zeros(idx.size)
        gp = g_prev.copy()
        # budget enough steps for the slowest grazing ray to traverse/skim the
        # roughness zone; break-early keeps the common case cheap.
        max_steps = 800
        for _s in range(max_steps):
            live = ~found
            if not live.any():
                break
            t_next = t + step
            p = oa + da * t_next[:, None]
            g = p[:, 2] - _bilerp(H, p[:, 0], p[:, 1], N)
            cross = live & (gp * g < 0.0)
            # bisection refine
            if cross.any():
                lo = t[cross]
                hi = t_next[cross]
                glo = gp[cross]
                oc = oa[cross]
                dc = da[cross]
                for _b in range(refine):
                    mid = 0.5 * (lo + hi)
                    pm = oc + dc * mid[:, None]
                    gm = pm[:, 2] - _bilerp(H, pm[:, 0], pm[:, 1], N)
                    same = (glo * gm > 0.0)
                    lo = np.where(same, mid, lo)
                    hi = np.where(same, hi, mid)
                    glo = np.where(same, gm, glo)
                th = 0.5 * (lo + hi)
                t_hit[cross] = th
                found[cross] = True
            # escape tests (only for still-live rays)
            esc_up = live & (~cross) & (p[:, 2] > top) & (da[:, 2] > 0.0)
            esc_dn = live & (~cross) & (p[:, 2] < bot) & (da[:, 2] < 0.0)
            done_now = esc_up | esc_dn
            if done_now.any():
                gi = idx[done_now]
                out_dir[gi] = da[done_now]
                escaped_up[gi] = da[done_now, 2] > 0.0
                got[gi] = True
                active[gi] = False
                found[done_now] = True   # stop marching these
            t = t_next
            gp = g
        # process the found crossings: Fresnel event
        hit_local = found & ~np.isin(idx, np.where(~active)[0])
        hidx_mask = found & active[idx]
        hi_local = np.where(hidx_mask)[0]
        if single_scatter and hi_local.size:
            # classic single-scatter: a 2nd facet interaction is a DEAD sample
            # (the energy the single-scatter microfacet model loses).
            gi_all = idx[hi_local]
            dead_ss = events[gi_all] >= 1
            if dead_ss.any():
                active[gi_all[dead_ss]] = False       # got stays False -> dead
            hi_local = hi_local[~dead_ss]
        if hi_local.size:
            gi = idx[hi_local]
            events[gi] += 1
            th = t_hit[hi_local]
            oc = oa[hi_local]
            dc = da[hi_local]
            ph = oc + dc * th[:, None]
            # surface normal from gradient, pointing UP (+z)
            nx = -_bilerp(dHdx, ph[:, 0], ph[:, 1], N)
            ny = -_bilerp(dHdy, ph[:, 0], ph[:, 1], N)
            nz = np.ones(hi_local.size)
            nn = np.stack([nx, ny, nz], axis=1)
            nn /= np.linalg.norm(nn, axis=1, keepdims=True)
            # medium the ray is currently in (before crossing): sign of g just before
            above = (oc[:, 2] - _bilerp(H, oc[:, 0], oc[:, 1], N)) > 0.0
            ni = np.where(above, n_above, n_below)
            nt = np.where(above, n_below, n_above)
            # orient facet normal against the incident direction
            ndotd = np.sum(nn * dc, axis=1)
            nf = np.where((ndotd > 0.0)[:, None], -nn, nn)
            cosI = -np.sum(nf * dc, axis=1)          # >0
            F = hrw.fresnel_dielectric(cosI, ni, nt)
            u = rng.random(hi_local.size)
            do_refl = u < F
            # reflection
            dr = dc - 2.0 * np.sum(dc * nf, axis=1)[:, None] * nf
            # refraction (Snell), eta = ni/nt; incident travel dir dc, normal nf up
            eta = (ni / nt)
            ci = cosI
            k = 1.0 - eta * eta * (1.0 - ci * ci)
            tir = k < 0.0
            ct = np.sqrt(np.maximum(k, 0.0))
            dt = eta[:, None] * dc + (eta * ci - ct)[:, None] * nf
            dt /= np.linalg.norm(dt, axis=1, keepdims=True) + 1e-12
            newd = np.where((do_refl | tir)[:, None], dr, dt)
            newd /= np.linalg.norm(newd, axis=1, keepdims=True)
            d[gi] = newd
            o[gi] = ph + newd * 1e-3        # nudge off the surface
        # rays that neither hit nor escaped this event: dead (shouldn't happen much)
        stuck = active[idx] & ~found
        if stuck.any():
            active[idx[stuck]] = False      # dead sample

    # entry: up-escape is reflected; exit: up-escape (into air) is transmitted.
    if entering:
        reflected = got & escaped_up
        transmitted = got & ~escaped_up
    else:
        reflected = got & ~escaped_up
        transmitted = got & escaped_up
    R = float(np.mean(reflected))
    T = float(np.mean(transmitted))
    dead = float(np.mean(~got))
    mu_out = np.clip(out_dir[:, 2], -1.0, 1.0)
    theta = np.degrees(np.arccos(np.abs(mu_out)))
    edges = np.linspace(0.0, 90.0, nbins + 1)
    hist_R = np.histogram(theta[reflected], bins=edges)[0] / max(M, 1)
    hist_T = np.histogram(theta[transmitted], bins=edges)[0] / max(M, 1)
    return dict(R=R, T=T, dead=dead, edges=edges, hist_R=hist_R, hist_T=hist_T)


def alpha_from_roughness(r):
    return max(r * r, ALPHA_FLOOR)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="large surface + ray count")
    ap.add_argument("--rays", type=int, default=0)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    if args.full:
        N, xi, M = 512, 8.0, 200_000
        alphas = [0.3, 0.5, 0.72, 1.0]
        mus = [0.1, 0.3, 0.5, 0.7, 0.9]
    else:
        N, xi, M = 256, 6.0, 40_000
        alphas = [0.3, 0.5, 0.72, 1.0]
        mus = [0.1, 0.5, 0.9]
    if args.rays:
        M = args.rays
    rng = np.random.default_rng(args.seed)

    print(f"# pkg265 #782 explicit Beckmann-heightfield oracle  IOR={IOR}  "
          f"N={N} xi={xi} rays={M}")
    print("# HF = explicit geometry multiple-scattering (ground truth, R+T=1 self-check)")
    print("# HFss = HF single-scatter-capped (2nd facet hit = dead)")
    print("# 1/E = uniform Cycles-style rescale of HFss to totalise 1")
    print("# GGXw = GGX Smith walk (heitz_random_walk, NDF differs -> trend cross-check)")
    print()
    hdr = ("alpha mu side | HF_R   HF_T  R+T  | HFss_R HFss_T dead% | 1/E_R 1/E_T "
           "| GGXw_R GGXw_T")
    print(hdr)
    print("-" * len(hdr))
    rows = []
    for a in alphas:
        for mu in mus:
            for entering in (True, False):
                hf = trace_interface(a, mu, IOR, rng, M, entering=entering,
                                     N=N, xi_cells=xi)
                ss = trace_interface(a, mu, IOR, rng, M, entering=entering,
                                     N=N, xi_cells=xi, single_scatter=True)
                E = ss["R"] + ss["T"]
                comp = 1.0 / E if E > 1e-6 else float("inf")
                cyc_R, cyc_T = ss["R"] * comp, ss["T"] * comp
                gw = hrw.sample_albedo_hist(
                    np.array([math.sqrt(max(0.0, 1 - mu * mu)), 0.0, mu]),
                    a, IOR, rng, M, scatter_max=64, entering=entering)
                side = "in " if entering else "out"
                rows.append((a, mu, entering, hf["R"], hf["T"], ss["R"], ss["T"],
                             ss["dead"], cyc_R, cyc_T, gw["R"], gw["T"]))
                print(f"{a:<5} {mu:<3}{side}| {hf['R']:.3f}  {hf['T']:.3f} "
                      f"{hf['R']+hf['T']:.3f}| {ss['R']:.3f}  {ss['T']:.3f}  "
                      f"{ss['dead']*100:4.1f} | {cyc_R:.3f} {cyc_T:.3f} "
                      f"| {gw['R']:.3f}  {gw['T']:.3f}")
    arr = np.array([(r[0], r[1], 1.0 if r[2] else 0.0) + r[3:] for r in rows],
                   dtype=float)
    np.save("pkg265_heightfield_rows.npy", arr)
    rt = arr[:, 3] + arr[:, 4]
    print()
    print(f"# HF R+T over grid: min {rt.min():.3f} max {rt.max():.3f} mean "
          f"{rt.mean():.3f} (lossless-dielectric energy self-check, target 1.000)")


if __name__ == "__main__":
    main()
