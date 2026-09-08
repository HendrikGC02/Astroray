"""pkg265 numpy oracle: Heitz et al. 2016 multiple-scattering microfacet DIELECTRIC.

Clean-room implementation of the random walk on the Smith microsurface from the
paper equations only (NO code copied from the paper's unstated-licence supplemental
`MicrosurfaceScattering.cpp` or the GPLv3 Mitsuba plugin -- see the research note
.astroray_plan/docs/pkg265-multiscatter-microfacet-research.md licence section and
the lead's 2026-09-09 Option-A decision):

  Heitz, Hanika, d'Eon, Dachsbacher, "Multiple-Scattering Microfacet BSDFs with the
  Smith Model", ACM TOG 35(4) (SIGGRAPH 2016), DOI 10.1145/2897824.2925943.

Equations implemented (all from the paper text):
  - height PDF/CDF P1,C1 standard normal (Sec 5.1, Eq 18-19);
  - signed Smith GGX Lambda (Sec 5.1, Eq 21-22; Appendix B) -> Lambda(w);
  - masking-from-height G1dist = C1(hr)^Lambda(wr) (Eq 25-26);
  - height sampling Alg 1 / Eq 30: hr1 = C1^-1( C1(hr) / (1-U)^(1/Lambda) );
  - dielectric phase function Alg 3 / Eq 34: sample VNDF normal, reflect or refract
    with Fresnel probability, phase weight w = 1 (energy-conserving by construction);
  - random walk Alg 7 (Sec 7) with the dielectric vertical flip of Fig 11;
  - stochastic eval E1..N of Eq 42 (Sec 8.1) for the directional BSDF value.

VNDF sampling is the Heitz JCGT-2018 bounded-VNDF method ("Sampling the GGX
Distribution of Visible Normals"), the same sampler Astroray already ships in
principled.cpp:724 (sampleGgxVNDF). Fresnel / refraction reuse the exact single-
interface math of the pkg264 oracle (.astroray_plan/docs/pkg264/glass_energy_oracle.py).

The model is EXACTLY energy conserving for a lossless dielectric: every phase event
has weight 1, so a walk deposits its full unit of energy on the side it escapes.
R+T == 1 (to MC error) is therefore the built-in self-check of a correct walk.

Usage:
  python heitz_random_walk.py            # prints the divergence table
Registered in scripts/README.md.
"""
import math
import numpy as np
from scipy.special import erf, erfinv

IOR = 1.45
ALPHA_FLOOR = 0.0064          # engine roughness->alpha floor (principled.cpp)
SQRT2 = math.sqrt(2.0)
INF = float("inf")


# --------------------------------------------------------------------------- #
# Smith microsurface height statistics (paper Sec 5.1, Eq 18-19)              #
# Standard-normal microsurface: P1(h)=N(0,1), C1 its CDF, invC1 its quantile. #
# --------------------------------------------------------------------------- #
def C1(h):
    return 0.5 * (1.0 + erf(h / SQRT2))


def invC1(u):
    # clamp away from 0/1 so erfinv stays finite; u>=1 -> +inf (ray escapes up).
    u = np.asarray(u, dtype=np.float64)
    out = np.empty_like(u)
    esc = u >= 1.0
    out[esc] = INF
    uu = np.clip(u[~esc], 1e-12, 1.0 - 1e-12)
    out[~esc] = SQRT2 * erfinv(2.0 * uu - 1.0)
    return out


def Lambda(w, alpha):
    """Signed Smith GGX Lambda (Eq 21-22, Appendix B). Positive for upward rays
    (wz>0, escape possible), <= -1 for downward rays (wz<0, always intersect)."""
    wz = w[:, 2]
    out = np.empty_like(wz)
    up = wz > 0.9999
    dn = wz < -0.9999
    mid = ~(up | dn)
    out[up] = 0.0
    out[dn] = -1.0
    wzm = wz[mid]
    tan2 = (1.0 - wzm * wzm) / (wzm * wzm)          # tan^2(theta)
    out[mid] = 0.5 * (np.sign(wzm) * np.sqrt(1.0 + alpha * alpha * tan2) - 1.0)
    return out


def G1_from_height(w, hr, alpha):
    """Shadowing/masking from a height, Gdist1(wr,hr,inf)=C1(hr)^Lambda(wr) (Eq 26)."""
    L = Lambda(w, alpha)
    return np.power(np.clip(C1(hr), 1e-12, 1.0), L)


def sample_height(wr, hr, U, alpha):
    """Alg 1 / Eq 30, vectorized. Returns next height (+inf == leaves surface)."""
    wz = wr[:, 2]
    out = np.empty_like(hr)
    up = wz > 0.9999
    dn = wz < -0.9999
    flat = (~up) & (~dn) & (np.abs(wz) < 1e-4)
    gen = (~up) & (~dn) & (~flat)
    out[up] = INF                                   # straight up: always leaves
    out[flat] = hr[flat]                            # horizontal: stays (Table 3)
    if dn.any():
        # straight down (Lambda -> -1): hr1 = invC1( C1(hr)*(1-U) )
        out[dn] = invC1(C1(hr[dn]) * (1.0 - U[dn]))
    if gen.any():
        wg = wr[gen]
        L = Lambda(wg, alpha)
        c1 = np.clip(C1(hr[gen]), 1e-12, 1.0)
        Ug = U[gen]
        wzg = wz[gen]
        res = np.empty(wg.shape[0])
        # upward rays can escape when U >= 1 - C1(hr)^L
        upg = wzg > 0.0
        esc = np.zeros(wg.shape[0], dtype=bool)
        esc[upg] = Ug[upg] >= (1.0 - np.power(c1[upg], L[upg]))
        res[esc] = INF
        ok = ~esc
        arg = c1[ok] / np.power(np.clip(1.0 - Ug[ok], 1e-12, 1.0), 1.0 / L[ok])
        res[ok] = invC1(arg)
        out[gen] = res
    return out


# --------------------------------------------------------------------------- #
# GGX VNDF sampling (Heitz JCGT 2018; == principled.cpp:724 sampleGgxVNDF).    #
# Isotropic alpha. wi may point into either hemisphere (walk direction -wr).   #
# --------------------------------------------------------------------------- #
def sample_vndf(wi, alpha, rng):
    M = wi.shape[0]
    Vh = np.stack([alpha * wi[:, 0], alpha * wi[:, 1], wi[:, 2]], axis=1)
    Vh /= np.linalg.norm(Vh, axis=1, keepdims=True)
    lensq = Vh[:, 0] ** 2 + Vh[:, 1] ** 2
    T1 = np.zeros((M, 3))
    big = lensq > 1e-12
    T1[big, 0] = -Vh[big, 1] / np.sqrt(lensq[big])
    T1[big, 1] = Vh[big, 0] / np.sqrt(lensq[big])
    T1[~big, 0] = 1.0
    T2 = np.cross(Vh, T1)
    u1 = rng.random(M)
    u2 = rng.random(M)
    r = np.sqrt(u1)
    phi = 2.0 * math.pi * u2
    t1 = r * np.cos(phi)
    t2 = r * np.sin(phi)
    s = 0.5 * (1.0 + Vh[:, 2])
    t2 = (1.0 - s) * np.sqrt(np.maximum(0.0, 1.0 - t1 * t1)) + s * t2
    t3 = np.sqrt(np.maximum(0.0, 1.0 - t1 * t1 - t2 * t2))
    Nh = t1[:, None] * T1 + t2[:, None] * T2 + t3[:, None] * Vh
    Ne = np.stack([alpha * Nh[:, 0], alpha * Nh[:, 1], np.maximum(1e-6, Nh[:, 2])], axis=1)
    Ne /= np.linalg.norm(Ne, axis=1, keepdims=True)
    return Ne


def fresnel_dielectric(cosThetaI, etaI, etaT):
    """Exact dielectric Fresnel (== pkg264 glass_energy_oracle.fresnel_dielectric),
    per-sample etaI/etaT arrays. cosThetaI >= 0 (incidence on the visible micronormal)."""
    ci = np.clip(np.abs(cosThetaI), 0.0, 1.0)
    sinI = np.sqrt(np.maximum(0.0, 1.0 - ci * ci))
    sinT = etaI / etaT * sinI
    tir = sinT >= 1.0
    cosT = np.sqrt(np.maximum(0.0, 1.0 - sinT * sinT))
    rp = (etaT * ci - etaI * cosT) / (etaT * ci + etaI * cosT + 1e-9)
    rs = (etaI * ci - etaT * cosT) / (etaI * ci + etaT * cosT + 1e-9)
    F = np.clip(0.5 * (rp * rp + rs * rs), 0.0, 1.0)
    return np.where(tir, 1.0, F)


def _refract(wi, wm, eta):
    """Snell refraction of incident travel-reversed direction wi about micronormal
    wm, relative eta = etaI/etaT. Returns (wt, ok). Same construction as the pkg264
    oracle's refraction branch (perp/para split)."""
    c = np.sum(wi * wm, axis=1)                     # dot(wi, wm) > 0
    perp = (wi - wm * c[:, None]) * (-eta[:, None])
    par2 = 1.0 - np.sum(perp * perp, axis=1)
    ok = par2 > 0.0
    wt = perp - wm * np.sqrt(np.maximum(par2, 0.0))[:, None]
    n = np.linalg.norm(wt, axis=1, keepdims=True)
    wt = wt / np.maximum(n, 1e-12)
    return wt, ok


# --------------------------------------------------------------------------- #
# Dielectric random walk (Alg 7 + dielectric flip Fig 11), vectorized over M.  #
# Returns outgoing macro-directions and a reflected/transmitted mask.          #
# scatter_max caps the number of PHASE events (== scatteringOrderMax).         #
# --------------------------------------------------------------------------- #
def walk_dielectric(wo, alpha, ior, rng, M, scatter_max=32, entering=True):
    """wo: macro outgoing (view) direction (3,), wo.z>0. Simulate M walks with the
    initial ray direction w1 = -wo (Alg 7: omega1 = -omega_i, here omega_i := wo).
    entering=True  -> incident side is air (n1=1, n2=ior): the ENTRY interface.
    entering=False -> incident side is glass (n1=ior, n2=1): the EXIT interface
                      (dense->rare, TIR possible), where the engine reroute lives.
    Returns wout (M,3) physical outgoing directions and 'reflected' (M bool);
    'escaped' False for a walk that never left within scatter_max (dead sample)."""
    wr = np.tile(-np.asarray(wo, dtype=np.float64), (M, 1))
    hr = np.full(M, invC1(np.array([0.999999]))[0])   # start just below +inf
    n_i = 1.0 if entering else ior
    n_t = ior if entering else 1.0
    n1 = np.full(M, n_i)                              # incident-side ior
    n2 = np.full(M, n_t)                              # transmit-side ior
    nflip = np.zeros(M, dtype=np.int64)
    active = np.ones(M, dtype=bool)
    escaped = np.zeros(M, dtype=bool)
    order = 0
    while active.any():
        idx = np.where(active)[0]
        # 1. sample next height (escape test -- always runs, even after the last
        #    permitted phase event, so a capped walk still gets its exit chance).
        U = rng.random(idx.size)
        hnew = sample_height(wr[idx], hr[idx], U, alpha)
        hr[idx] = hnew
        left = np.isinf(hnew)
        gone = idx[left]
        escaped[gone] = True
        active[gone] = False
        stay = idx[~left]
        # 2. budget: after scatter_max phase events, any ray still inside is a
        #    DEAD sample (== the single-scatter energy the classic model loses).
        if order >= scatter_max:
            break
        if stay.size == 0:
            order += 1
            continue
        # 2. dielectric phase event (Alg 3)
        wi = -wr[stay]                                # phase incident = -wr
        wm = sample_vndf(wi, alpha, rng)
        c = np.sum(wi * wm, axis=1)
        F = fresnel_dielectric(c, n1[stay], n2[stay])
        u = rng.random(stay.size)
        do_refl = u < F
        # reflection: wo_micro = 2 c wm - wi  (== reflect(wr,wm))
        wnew = 2.0 * c[:, None] * wm - wi
        # refraction for the complement
        it = ~do_refl
        if it.any():
            eta = (n1[stay] / n2[stay])[it]
            wt, ok = _refract(wi[it], wm[it], eta)
            # TIR fallback (should be rare; F already ~1 there) -> reflect
            wt = np.where(ok[:, None], wt, wnew[it])
            wnew[it] = wt
            # vertical flip on genuine transmission (Fig 11): negate hr and z,
            # swap the interface iors, bump the flip parity.
            trans = np.zeros(stay.size, dtype=bool)
            trans[np.where(it)[0][ok]] = True
            sT = stay[trans]
            hr[sT] = -hr[sT]
            wnew[trans, 2] = -wnew[trans, 2]
            n1[sT], n2[sT] = n2[sT].copy(), n1[sT].copy()
            nflip[sT] += 1
        wr[stay] = wnew
        order += 1
    # physical outgoing direction: undo the net vertical flips (z -> (-1)^nflip z)
    wout = wr.copy()
    odd = (nflip % 2) == 1
    wout[odd, 2] = -wout[odd, 2]
    reflected = (nflip % 2) == 0
    return wout, reflected, escaped


# --------------------------------------------------------------------------- #
# Albedo + directional histogram from the sampler (importance sampling, w=1).  #
# --------------------------------------------------------------------------- #
def sample_albedo_hist(wo, alpha, ior, rng, M, nbins=18, scatter_max=32, entering=True):
    wout, reflected, escaped = walk_dielectric(wo, alpha, ior, rng, M, scatter_max, entering)
    R = float(np.mean(escaped & reflected))
    T = float(np.mean(escaped & ~reflected))
    dead = float(np.mean(~escaped))
    # theta histogram (angle from +z normal), phi-averaged, reflection hemisphere.
    mu = np.clip(wout[:, 2], -1.0, 1.0)
    theta = np.degrees(np.arccos(np.abs(mu)))       # [0,90]
    edges = np.linspace(0.0, 90.0, nbins + 1)
    hist_R = np.histogram(theta[escaped & reflected], bins=edges)[0] / max(M, 1)
    hist_T = np.histogram(theta[escaped & ~reflected], bins=edges)[0] / max(M, 1)
    return dict(R=R, T=T, dead=dead, edges=edges, hist_R=hist_R, hist_T=hist_T)


def single_scatter_albedo(wo, alpha, ior, rng, M, scatter_max=1):
    """Single-scatter-only variant: cap the walk at one phase event. A ray that
    fails to escape after the first scatter is a DEAD sample (the energy the
    classic single-scatter microfacet dielectric loses -- exactly what the current
    engine's dead-sample reroute papers over). Returns (R_ss, T_ss, dead)."""
    r = sample_albedo_hist(wo, alpha, ior, rng, M, scatter_max=scatter_max)
    return r["R"], r["T"], r["dead"]


# --------------------------------------------------------------------------- #
# Stochastic eval E1..N (Eq 42) -- unbiased directional BSDF value at (wo,wi).  #
# Used by the directional test as the analytic reference for f (optional; the  #
# sampled histogram above is the primary directional reference).               #
# --------------------------------------------------------------------------- #
def stochastic_eval(wo, wi, alpha, ior, rng, M, scatter_max=32):
    """E[sum_r e_r p(-wr,wi) Gdist1(wi,hr)] for a lossless dielectric (e_r==1).
    Averages the per-bounce phase*shadowing contribution toward the fixed wi over
    M walks started from wo. Returns f(wo,wi)*|cos(wi)| (cosine-weighted)."""
    wr = np.tile(-np.asarray(wo, dtype=np.float64), (M, 1))
    hr = np.full(M, invC1(np.array([0.999999]))[0])
    n1 = np.ones(M)
    n2 = np.full(M, ior)
    nflip = np.zeros(M, dtype=np.int64)
    active = np.ones(M, dtype=bool)
    acc = np.zeros(M)
    wi = np.asarray(wi, dtype=np.float64)
    order = 0
    while active.any() and order < scatter_max:
        idx = np.where(active)[0]
        U = rng.random(idx.size)
        hnew = sample_height(wr[idx], hr[idx], U, alpha)
        hr[idx] = hnew
        left = np.isinf(hnew)
        active[idx[left]] = False
        stay = idx[~left]
        if stay.size == 0:
            order += 1
            continue
        # phase-function value toward wi in the CURRENT (flipped) frame:
        # map the fixed macro wi into the current frame by the same net flip.
        odd = (nflip[stay] % 2) == 1
        wif = np.tile(wi, (stay.size, 1))
        wif[odd, 2] = -wif[odd, 2]
        contrib = _phase_diel_value(wr[stay], wif, alpha, n1[stay], n2[stay])
        # shadowing toward wi from height hr in the current frame
        G = G1_from_height(wif, hr[stay], alpha)
        acc[stay] += contrib * G
        # advance the walk one phase event (same as walk_dielectric)
        wi_in = -wr[stay]
        wm = sample_vndf(wi_in, alpha, rng)
        c = np.sum(wi_in * wm, axis=1)
        F = fresnel_dielectric(c, n1[stay], n2[stay])
        u = rng.random(stay.size)
        do_refl = u < F
        wnew = 2.0 * c[:, None] * wm - wi_in
        itv = ~do_refl
        if itv.any():
            eta = (n1[stay] / n2[stay])[itv]
            wt, ok = _refract(wi_in[itv], wm[itv], eta)
            wt = np.where(ok[:, None], wt, wnew[itv])
            wnew[itv] = wt
            trans = np.zeros(stay.size, dtype=bool)
            trans[np.where(itv)[0][ok]] = True
            sT = stay[trans]
            hr[sT] = -hr[sT]
            wnew[trans, 2] = -wnew[trans, 2]
            n1[sT], n2[sT] = n2[sT].copy(), n1[sT].copy()
            nflip[sT] += 1
        wr[stay] = wnew
        order += 1
    return acc.mean()


def _phase_diel_value(wr, wo_target, alpha, n1, n2):
    """pdiel(-wr, wo_target) from Eq 34 (VNDF form), reflection+transmission halves.
    wr = current travel dir; wi_phase = -wr; wo_target = the queried outgoing dir."""
    wi = -wr
    M = wr.shape[0]
    val = np.zeros(M)
    same = (wi[:, 2] * wo_target[:, 2]) > 0.0        # reflection half
    opp = ~same
    # reflection: half-vector, F * Dwi / (4|wi.wh|)
    if same.any():
        wh = wi[same] + wo_target[same]
        wh /= np.maximum(np.linalg.norm(wh, axis=1, keepdims=True), 1e-12)
        wh[wh[:, 2] < 0] = -wh[wh[:, 2] < 0]
        F = fresnel_dielectric(np.sum(wi[same] * wh, axis=1), n1[same], n2[same])
        Dwi = _vndf_D(wi[same], wh, alpha)
        denom = 4.0 * np.abs(np.sum(wi[same] * wh, axis=1)) + 1e-12
        val[same] = F * Dwi / denom
    # transmission: refractive half-vector wht ~ -(ni wi + no wo)
    if opp.any():
        ni = n1[opp]
        no = n2[opp]
        wht = -(ni[:, None] * wi[opp] + no[:, None] * wo_target[opp])
        wht /= np.maximum(np.linalg.norm(wht, axis=1, keepdims=True), 1e-12)
        wht[wht[:, 2] < 0] = -wht[wht[:, 2] < 0]
        ci = np.sum(wi[opp] * wht, axis=1)
        F = fresnel_dielectric(ci, ni, no)
        Dwi = _vndf_D(wi[opp], wht, alpha)
        num = np.abs(np.sum(wo_target[opp] * wht, axis=1)) * (no * no) * (1.0 - F) * Dwi
        d = ni * ci + no * np.sum(wo_target[opp] * wht, axis=1)
        val[opp] = num / np.maximum(d * d, 1e-12)
    return val


def _vndf_D(wi, wm, alpha):
    """Dwi(wm) = <wi,wm> D(wm) / (cos_i (1+Lambda(wi)))  (Eq 32)."""
    NdotH = np.abs(wm[:, 2])
    a2 = alpha * alpha
    t = 1.0 + (a2 - 1.0) * NdotH * NdotH
    D = a2 / (math.pi * t * t)
    idot = np.maximum(np.sum(wi * wm, axis=1), 0.0)
    cosi = np.abs(wi[:, 2])
    L = Lambda(wi, alpha)
    return idot * D / np.maximum(cosi * (1.0 + L), 1e-12)


# --------------------------------------------------------------------------- #
# Divergence table: multi-scatter walk vs single-scatter vs Cycles 1/E.        #
# --------------------------------------------------------------------------- #
def alpha_from_roughness(r):
    return max(r * r, ALPHA_FLOOR)


def main():
    import sys
    M = 200_000
    if len(sys.argv) > 1:
        M = int(sys.argv[1])
    roughs = [0.3, 0.5, 0.85, 1.0]
    mus = [0.1, 0.3, 0.5, 0.7, 0.9]
    rng = np.random.default_rng(2026)
    print(f"# pkg265 Heitz-2016 dielectric random walk oracle  IOR={IOR}  M={M}")
    print("# MS  = multiple-scattering walk (scatteringOrderMax=32)")
    print("# SS  = single-scatter-only (1 phase event; dead = lost energy)")
    print("# Cyc = Cycles energy_scale = 1/E_ss compensation applied to SS")
    print()
    hdr = ("rough  mu  | MS_R   MS_T   MS_R+T dead% | SS_R   SS_T   SS_dead%"
           " | E_ss  comp=1/E | Cyc_R  Cyc_T")
    print(hdr)
    print("-" * len(hdr))
    rows = []
    for r in roughs:
        a = alpha_from_roughness(r)
        for mu in mus:
            st = math.sqrt(max(0.0, 1.0 - mu * mu))
            wo = np.array([st, 0.0, mu])
            ms = sample_albedo_hist(wo, a, IOR, rng, M, scatter_max=32)
            ss_R, ss_T, ss_dead = single_scatter_albedo(wo, a, IOR, rng, M)
            E_ss = ss_R + ss_T                      # single-scatter efficiency
            comp = 1.0 / E_ss if E_ss > 1e-6 else float("inf")
            cyc_R, cyc_T = ss_R * comp, ss_T * comp  # Cycles 1/E: rescale SS to 1
            rows.append((r, mu, ms["R"], ms["T"], ms["R"] + ms["T"], ms["dead"],
                         ss_R, ss_T, ss_dead, E_ss, comp, cyc_R, cyc_T))
            print(f"{r:<5}  {mu:<3} | {ms['R']:.3f}  {ms['T']:.3f}  "
                  f"{ms['R']+ms['T']:.3f}  {ms['dead']*100:4.1f} | "
                  f"{ss_R:.3f}  {ss_T:.3f}  {ss_dead*100:5.1f} | "
                  f"{E_ss:.3f}  {comp:.3f}  | {cyc_R:.3f}  {cyc_T:.3f}")
    arr = np.array(rows, dtype=float)
    np.save("pkg265_divergence_rows.npy", arr)
    # summary
    msrt = arr[:, 4]
    print()
    print(f"# MS R+T over the grid: min {msrt.min():.3f}  max {msrt.max():.3f}  "
          f"mean {msrt.mean():.3f}  (target 1.000, lossless dielectric energy check)")
    print("# Divergence: Cycles rescales SS by 1/E uniformly (preserves the SS")
    print("#   angular SHAPE); the MS walk redistributes the recovered energy toward")
    print("#   the limb/wide angles where extra bounces exit. Compare MS_R/MS_T vs")
    print("#   Cyc_R/Cyc_T per row: equal totals, different R:T split and angular shape.")


if __name__ == "__main__":
    main()
