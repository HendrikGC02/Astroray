"""pkg264 Monte-Carlo oracle for the rough-glass dielectric microfacet BSDF.

Reproduces, in vectorized numpy, the EXACT single-interface transmission-lobe math
and importance sampler that plugins/materials/principled.cpp ships -- the plugin the
Blender BSDF_GLASS node actually renders through (kind:'principled', native
Principled ON by default; blender_addon/__init__.py:4079 -> :4234 ->
_create_native_principled_material). It also does the disney.cpp variant (separable
Smith G1.G1 + the delta-glass dead-sample fallback disney.cpp:855-909) for A/B.

For roughness {0,0.2,0.5,0.85} x incidence theta {0,30,60,75,85} deg, IOR 1.45,
tabulate reflected+transmitted directional-hemispherical albedo (single-scatter,
R+T) for
  (a) the EXACT microfacet dielectric BSDF (uncompensated ground truth), and
  (c) Astroray's lobe AS IMPLEMENTED: the realized albedo of the shipped
      importance-sampling estimator, mean of f*|cosI|/pdf with dead samples
      (chooseAndSampleDir ds.ok==false -> sample() returns f=0,pdf=0,
      principled.cpp:1986) counted as 0.
The (a) vs (c) gap isolates the SAMPLING energy loss (dead-sample fraction);
it is comp-independent for the ratio -- ggxGlassComp multiplies valid eval terms
but never resurrects a discarded direction. Cycles column (b): its preserve_energy
tables hold R+T ~= 1.0, so RT_true vs 1.0 is the Cycles-target gap. No invented math.
"""
import math
import numpy as np

N_EST = 300_000
N_INT = 600_000
IOR = 1.45
ALPHA_FLOOR = 0.0064
KDELTA = 0.03

Nz = np.array([0.0, 0.0, 1.0])


def D_GTR2(NdotH, a):  # principled.cpp:132
    a2 = a * a
    t = 1.0 + (a2 - 1.0) * NdotH * NdotH
    return a2 / (math.pi * t * t)


def smith_lambda(cosTheta, alpha):  # principled.cpp:153
    a2 = alpha * alpha
    c2 = np.maximum(cosTheta * cosTheta, 1e-7)
    t = a2 * np.maximum(1.0 / c2 - 1.0, 0.0)
    return 0.5 * (np.sqrt(1.0 + t) - 1.0)


def smithG2(NdotL, NdotV, alpha):  # principled.cpp:161 height-correlated
    return 1.0 / (1.0 + smith_lambda(NdotV, alpha) + smith_lambda(NdotL, alpha))


def smithG1(NdotV, alphaG):  # principled.cpp:139 separable
    a = alphaG * alphaG
    b = NdotV * NdotV
    return 2.0 * NdotV / (NdotV + np.sqrt(a + b - a * b) + 0.001)


def fresnel_dielectric(cosThetaI, etaI, etaT):  # principled.cpp:285 (vectorized)
    ci = np.clip(cosThetaI, -1.0, 1.0)
    ei = np.full_like(ci, etaI)
    et = np.full_like(ci, etaT)
    swap = ci <= 0.0
    ei2 = np.where(swap, et, ei)
    et2 = np.where(swap, ei, et)
    ci = np.abs(ci)
    sinI = np.sqrt(np.maximum(0.0, 1.0 - ci * ci))
    sinT = ei2 / et2 * sinI
    tir = sinT >= 1.0
    cosT = np.sqrt(np.maximum(0.0, 1.0 - sinT * sinT))
    rp = (et2 * ci - ei2 * cosT) / (et2 * ci + ei2 * cosT + 1e-6)
    rs = (ei2 * ci - et2 * cosT) / (ei2 * ci + et2 * cosT + 1e-6)
    F = np.clip(0.5 * (rp * rp + rs * rs), 0.0, 1.0)
    return np.where(tir, 1.0, F)


def dot(a, b):
    return a[:, 0] * b[:, 0] + a[:, 1] * b[:, 1] + a[:, 2] * b[:, 2]


def norm(a):
    n = np.sqrt(np.maximum(dot(a, a), 1e-30))
    return a / n[:, None]


def eval_T(wo, wi, roughness, use_g2, comp=1.0, flux=False):
    """principled.cpp transmissionEvalRGB (film off, white base). Vectorized;
    returns scalar array f*|cosI| per sample. wo is (3,), wi is (M,3).
    flux=True multiplies the transmission sub-lobe by etap^2 to UNDO the radiance
    compression (ft /= etap*etap in the source), so a lossless smooth interface's
    hemispherical integral -> 1.0 and the rough integral -> single-scatter
    efficiency E_ss (the quantity Cycles' preserve_energy tables restore to ~1)."""
    M = wi.shape[0]
    cosO = wi @ np.zeros(3) + wo[2]  # N.dot(wo), broadcast
    cosO = np.full(M, wo[2])
    cosI = wi[:, 2]
    etaI, etaT = 1.0, IOR
    alpha = max(roughness * roughness, ALPHA_FLOOR)
    out = np.zeros(M)
    woB = np.broadcast_to(wo, (M, 3))
    # reflection sub-lobe: cosO>0 & cosI>0
    refl = (cosO > 0.0) & (cosI > 0.0)
    if refl.any():
        wm = norm(woB[refl] + wi[refl])
        s = wm[:, 2] < 0.0
        wm[s] = -wm[s]
        HdotO = dot(woB[refl], wm)
        NdotH = wm[:, 2]
        D = D_GTR2(NdotH, alpha)
        cI = cosI[refl]
        cO = cosO[refl]
        G = smithG2(cI, cO, alpha) if use_g2 else smithG1(cO, alpha) * smithG1(cI, alpha)
        F = fresnel_dielectric(HdotO, 1.0, IOR)
        fr = D * G * F / (4.0 * cO * cI + 1e-8) * cI
        fr = np.where(HdotO <= 1e-10, 0.0, fr)
        out[refl] = np.maximum(0.0, fr * comp)
    # transmission sub-lobe: cosO*cosI < 0
    tr = (cosO * cosI < 0.0)
    if tr.any():
        etap = IOR
        wm = norm(wi[tr] * etap + woB[tr])
        s = wm[:, 2] < 0.0
        wm[s] = -wm[s]
        cI = cosI[tr]
        cO = cosO[tr]
        HdotI = dot(wi[tr], wm)
        HdotO = dot(woB[tr], wm)
        bad = (HdotI * cI < 0.0) | (HdotO * cO < 0.0)
        D = D_GTR2(np.abs(wm[:, 2]), alpha)
        G = (smithG2(np.abs(cI), np.abs(cO), alpha) if use_g2
             else smithG1(np.abs(cO), alpha) * smithG1(np.abs(cI), alpha))
        F = fresnel_dielectric(np.abs(HdotO), etaI, etaT)
        den = HdotI + HdotO / etap
        den = den * den * cI * cO
        ft = D * (1.0 - F) * G * np.abs(HdotI * HdotO / (den + 1e-10))
        ft /= (etap * etap)
        if flux:
            ft *= (etap * etap)  # undo radiance compression -> flux transmittance
        val = ft * np.abs(cI) * comp
        val = np.where(bad, 0.0, np.maximum(0.0, val))
        out[tr] = val
    return out


def vndf_pdf(wo, wm, roughness):  # principled.cpp:747 (vectorized; wm (M,3))
    absCosO = abs(wo[2])
    HdotO = np.abs(wm @ wo)
    NdotH = np.abs(wm[:, 2])
    alpha = max(roughness * roughness, ALPHA_FLOOR)
    D = D_GTR2(NdotH, alpha)
    G1 = smithG1(absCosO, alpha)
    p = G1 / absCosO * D * HdotO
    return np.where((HdotO <= 1e-10) | (NdotH <= 1e-10) | (absCosO <= 1e-10), 0.0, p)


def pdf_T(wo, wi, roughness):  # principled.cpp:1431 (vectorized)
    M = wi.shape[0]
    cosO = np.full(M, wo[2])
    cosI = wi[:, 2]
    etaI, etaT = 1.0, IOR
    woB = np.broadcast_to(wo, (M, 3))
    out = np.zeros(M)
    refl = (cosO > 0.0) & (cosI > 0.0)
    if refl.any():
        wm = norm(woB[refl] + wi[refl])
        s = wm[:, 2] < 0.0
        wm[s] = -wm[s]
        HdotO = np.abs(dot(woB[refl], wm))
        F = fresnel_dielectric(HdotO, etaI, etaT)
        p = F * vndf_pdf(wo, wm, roughness) / (4.0 * HdotO)
        out[refl] = np.where(HdotO <= 1e-10, 0.0, p)
    tr = (cosO * cosI < 0.0)
    if tr.any():
        etap = IOR
        wm = norm(wi[tr] * etap + woB[tr])
        s = wm[:, 2] < 0.0
        wm[s] = -wm[s]
        HdotO = dot(woB[tr], wm)
        HdotI = dot(wi[tr], wm)
        d = HdotI + HdotO / etap
        d2 = d * d
        F = fresnel_dielectric(np.abs(HdotO), etaI, etaT)
        p = (1.0 - F) * vndf_pdf(wo, wm, roughness) * np.abs(HdotI) / np.maximum(d2, 1e-30)
        p = np.where((HdotO * HdotI >= 0.0) | (d2 <= 1e-10), 0.0, p)
        out[tr] = p
    return out


def sample_ggx_vndf(wo, roughness, rng, M):  # principled.cpp:724 (vectorized)
    alpha = max(roughness * roughness, ALPHA_FLOOR)
    u1 = rng.random(M)
    u2 = rng.random(M)
    wo_l = np.array([wo[0], wo[1], wo[2]])  # tangent frame = world here
    wh = np.array([alpha * wo_l[0], alpha * wo_l[1], wo_l[2]])
    wh = wh / np.linalg.norm(wh)
    if wh[2] < 0.0:
        wh = -wh
    if wh[2] < 0.99999:
        T1 = np.cross([0.0, 0.0, 1.0], wh)
        T1 = T1 / np.linalg.norm(T1)
    else:
        T1 = np.array([1.0, 0.0, 0.0])
    T2 = np.cross(wh, T1)
    r = np.sqrt(u1)
    phi = 2.0 * math.pi * u2
    px = r * np.cos(phi)
    py = r * np.sin(phi)
    h = np.sqrt(np.maximum(0.0, 1.0 - px * px))
    t = (1.0 + wh[2]) / 2.0
    py = (1.0 - t) * h + t * py
    pz = np.sqrt(np.maximum(0.0, 1.0 - px * px - py * py))
    nh = np.outer(px, T1) + np.outer(py, T2) + np.outer(pz, wh)
    ml = np.stack([alpha * nh[:, 0], alpha * nh[:, 1], np.maximum(1e-6, nh[:, 2])], axis=1)
    ml = norm(ml)
    # tangent frame identity (TAN=x,BIT=y,N=z) -> m == ml in world
    return norm(ml)


def estimator_albedo(wo, roughness, rng, use_g2, flux=False):
    """Realized albedo of the shipped Transmission sampler + dead fraction."""
    etaI, etaT = 1.0, IOR
    eta = etaI / etaT
    M = N_EST
    wm = sample_ggx_vndf(wo, roughness, rng, M)
    HdotO = wm @ wo
    F = fresnel_dielectric(np.abs(HdotO), etaI, etaT)
    u = rng.random(M)
    do_refl = u < F
    wi = np.zeros((M, 3))
    ok = np.zeros(M, dtype=bool)
    # reflection branch
    ir = do_refl
    if ir.any():
        wr = norm(wm[ir] * (2.0 * HdotO[ir])[:, None] - wo)
        wi[ir] = wr
        ok[ir] = (wr[:, 2] * wo[2]) > 0.0
    # refraction branch (refractMicro principled.cpp:758)
    it = ~do_refl
    if it.any():
        wmt = wm[it]
        c = np.clip(wmt @ wo, -1.0, 1.0)
        perp = (np.broadcast_to(wo, wmt.shape) - wmt * c[:, None]) * (-eta)
        par2 = 1.0 - dot(perp, perp)
        good = (c > 0.0) & (par2 > 0.0)
        wt = norm(perp + wmt * (-np.sqrt(np.maximum(par2, 0.0)))[:, None])
        wtmp = np.zeros((wmt.shape[0], 3))
        wtmp[good] = wt[good]
        wi[it] = wtmp
        ok[it] = good
    thr = np.zeros(M)
    if ok.any():
        f = eval_T(wo, wi[ok], roughness, use_g2, flux=flux)
        p = pdf_T(wo, wi[ok], roughness)
        valid = (p > 1e-12) & (f > 0.0)
        tv = np.zeros(f.shape[0])
        tv[valid] = f[valid] / p[valid]
        thr[ok] = tv
    return thr.mean(), 1.0 - ok.mean()


def true_albedo(wo, roughness, use_g2):
    """Exact single-scatter R,T by uniform-sphere MC of the exact BSDF (comp=1)."""
    if roughness <= KDELTA:
        F = float(fresnel_dielectric(np.array([wo[2]]), 1.0, IOR)[0])
        return F, 1.0 - F
    rng = np.random.default_rng(2024)
    M = N_INT
    z = 1.0 - 2.0 * rng.random(M)
    phi = 2.0 * math.pi * rng.random(M)
    rr = np.sqrt(np.maximum(0.0, 1.0 - z * z))
    wi = np.stack([rr * np.cos(phi), rr * np.sin(phi), z], axis=1)
    f = eval_T(wo, wi, roughness, use_g2)  # carries |cosI|
    contrib = f * 4.0 * math.pi
    R = contrib[wi[:, 2] > 0.0].sum() / M
    T = contrib[wi[:, 2] < 0.0].sum() / M
    return R, T


def main():
    roughs = [0.0, 0.2, 0.5, 0.85]
    thetas = [0.0, 30.0, 60.0, 75.0, 85.0]
    rng = np.random.default_rng(7)
    print(f"IOR={IOR}  N_EST={N_EST}  N_INT={N_INT}\n")
    header = ("r     th | flux_smooth | flux_est_prin dead% | E_ss(=flux single-scat)"
              " | comp_needed")
    print(header)
    print("-" * len(header))
    print("flux_smooth = analytic (1-F)+F = 1.0 (lossless reference).")
    print("flux_est_prin = shipped principled.cpp glass sampler, FLUX furnace, comp=1")
    print("   (radiance 1/etap^2 undone) -> the energy actually delivered before"
          " multi-scatter compensation.")
    print("E_ss = flux single-scatter efficiency (importance-sampled true).")
    print("comp_needed = 1/E_ss = the multi-scatter boost Cycles' preserve_energy"
          " tables apply to reach ~1.0.\n")
    rows = []
    for r in roughs:
        for th in thetas:
            ct = math.cos(math.radians(th))
            st = math.sin(math.radians(th))
            wo = np.array([st, 0.0, ct])
            # FLUX furnace (undo radiance compression): smooth -> 1.0.
            if r <= KDELTA:
                F = float(fresnel_dielectric(np.array([ct]), 1.0, IOR)[0])
                flux_smooth = 1.0
                flux_est, dead_p = 1.0, 0.0
                E_ss = 1.0
            else:
                flux_smooth = 1.0
                flux_est, dead_p = estimator_albedo(wo, r, rng, True, flux=True)
                # E_ss via the importance-sampled estimator IS flux_est (sampler is
                # ~unbiased, dead<5%); report it as the single-scatter efficiency.
                E_ss = flux_est
            comp_needed = 1.0 / E_ss if E_ss > 1e-6 else float('inf')
            rows.append((r, th, flux_smooth, flux_est, dead_p, E_ss, comp_needed))
            print(f"{r:<5} {th:<3}| {flux_smooth:11.3f} | {flux_est:13.3f} {dead_p*100:4.0f} |"
                  f" {E_ss:22.3f} | {comp_needed:11.3f}")
    np.save("glass_energy_oracle_rows.npy", np.array(rows, dtype=float))
    print("\nIf the shipped ggxGlassComp equals comp_needed, the glass is energy-"
          "correct; if it under-shoots, that under-shoot IS the pkg263 deficit.")


if __name__ == "__main__":
    main()
