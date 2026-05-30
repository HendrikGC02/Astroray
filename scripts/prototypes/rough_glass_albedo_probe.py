"""Numpy replication of disney.cpp glass BSDF (metallic=0, transmission=1, ior=1.5)
to localize the CPU rough-glass furnace energy loss WITHOUT C++ rebuilds.

Two independent measurements for a fixed wo:
  (A) Directional albedo by BRUTE-FORCE sphere integration of the actual
      BRDF/BTDF (PBRT f, NOT pre-multiplied by cos):  A = sum f * |cosI| * dOmega.
      A ~= 1  => BSDF is physically lossless; loss is in sampling/convention.
      A  < 1  => the eval itself loses energy.
  (B) MC estimator using the EXACT sample()/integrator convention the C++ uses
      (throughput = s.f / s.pdf).  If (A)~1 but (B)<1, the bug is the convention.

Mirrors plugins/materials/disney.cpp lines ~95-540 exactly.
"""
import numpy as np

IOR = 1.5
EPS = 1e-10


def normalize(v):
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def fresnel_dielectric(cosThetaI, etaI, etaT):
    cosThetaI = np.clip(cosThetaI, -1.0, 1.0)
    if cosThetaI <= 0.0:
        etaI, etaT = etaT, etaI
        cosThetaI = abs(cosThetaI)
    sinI = np.sqrt(max(0.0, 1 - cosThetaI**2))
    sinT = etaI / etaT * sinI
    if sinT >= 1.0:
        return 1.0
    cosT = np.sqrt(max(0.0, 1 - sinT**2))
    rPar = (etaT*cosThetaI - etaI*cosT) / (etaT*cosThetaI + etaI*cosT + 1e-6)
    rPer = (etaI*cosThetaI - etaT*cosT) / (etaI*cosThetaI + etaT*cosT + 1e-6)
    return float(np.clip(0.5*(rPar**2 + rPer**2), 0.0, 1.0))


def fresnel_schlick(cosTheta, F0, scale=0.8):
    c = np.clip(1 - cosTheta, 0.0, 1.0)
    return F0 + (1 - F0) * c**5 * scale


def D_GTR2(NdotH, a):
    a2 = a*a
    t = 1 + (a2 - 1) * NdotH*NdotH
    return a2 / (np.pi * t*t + 0.001)


def smithG_GGX(NdotV, a):       # combined visibility form (eval reflection)
    aa = a*a
    b = NdotV*NdotV
    return 1.0 / (NdotV + np.sqrt(aa + b - aa*b) + 0.001)


def smithG1_GGX(NdotV, a):      # true Smith G1 (transmission)
    aa = a*a
    b = NdotV*NdotV
    return 2.0*NdotV / (NdotV + np.sqrt(aa + b - aa*b) + 0.001)


def alpha_of(rough):
    return max(rough*rough, 0.0064)


# ---- reflection BRDF (glass: metallic=0, transmission=1) -> eval() spec*NdotL ----
def eval_reflection_fcos(N, wo, wi, rough):
    """Returns spec*NdotL  == f_r * cosI  (the C++ eval() convention)."""
    NdotL = N @ wi
    NdotV = N @ wo
    if NdotL <= 0 or NdotV <= 0:
        return 0.0
    H = normalize(wi + wo)
    NdotH = N @ H
    LdotH = wi @ H
    F0 = 0.5 * 0.08  # specular_=0.5 default -> Cspec0 = 0.04
    a = alpha_of(rough)
    Ds = D_GTR2(NdotH, a)
    F = fresnel_schlick(LdotH, F0, 0.8)
    Gs = smithG_GGX(NdotL, a) * smithG_GGX(NdotV, a)
    spec = Ds * F * Gs
    return spec * NdotL


# ---- transmission BTDF -> roughTransmissionEval (NO cosI) ----
def eval_transmission_f(N, wo, wi, rough):
    cosO = N @ wo
    cosI = N @ wi
    if cosO == 0 or cosI == 0 or cosO*cosI >= 0:
        return 0.0
    entering = cosO > 0
    etaI = 1.0 if entering else IOR
    etaT = IOR if entering else 1.0
    etap = IOR if entering else 1.0/IOR
    wm = normalize(wi*etap + wo)
    if (N @ wm) < 0:
        wm = -wm
    if (wm @ wi)*cosI < 0 or (wm @ wo)*cosO < 0:
        return 0.0
    a = alpha_of(rough)
    D = D_GTR2(abs(N @ wm), a)
    G = smithG1_GGX(abs(cosO), a) * smithG1_GGX(abs(cosI), a)
    F = fresnel_dielectric(abs(wo @ wm), etaI, etaT)
    denom = (wi @ wm) + (wo @ wm)/etap
    denom = denom*denom * cosI * cosO
    ft = D * (1-F) * G * abs((wi @ wm)*(wo @ wm) / (denom + EPS))
    ft /= etap*etap
    return ft  # baseColor=1


def directional_albedo_bruteforce(wo, rough, ntheta=400, nphi=400):
    """A(wo) = integral over full sphere of [f_r*|cosI| + f_t*|cosI|] dOmega.
    f_r here = eval_reflection_fcos / cosI (strip the cos), then * |cosI| again
    => just eval_reflection_fcos.  For transmission f_t * |cosI|."""
    N = np.array([0.0, 0.0, 1.0])
    A_refl = 0.0
    A_tran = 0.0
    thetas = (np.arange(ntheta) + 0.5) * np.pi / ntheta      # 0..pi full sphere
    phis = (np.arange(nphi) + 0.5) * 2*np.pi / nphi
    dtheta = np.pi/ntheta
    dphi = 2*np.pi/nphi
    for th in thetas:
        st, ct = np.sin(th), np.cos(th)
        dOmega = st * dtheta * dphi
        for ph in phis:
            wi = np.array([st*np.cos(ph), st*np.sin(ph), ct])
            cosI = N @ wi
            if cosI > 0:    # reflection hemisphere
                A_refl += eval_reflection_fcos(N, wo, wi, rough) * dOmega
            elif cosI < 0:  # transmission hemisphere
                A_tran += eval_transmission_f(N, wo, wi, rough) * abs(cosI) * dOmega
    return A_refl, A_tran


def main():
    N = np.array([0.0, 0.0, 1.0])
    print(f"ior={IOR}  brute-force directional albedo (A_refl + A_tran should = 1)")
    print(f"{'rough':>6} {'incid':>6} | {'A_refl':>8} {'A_tran':>8} {'total':>8}")
    print("-"*50)
    for rough in [0.05, 0.1, 0.3, 0.6, 1.0]:
        for cosO in [0.95, 0.7, 0.4, 0.15]:
            sinO = np.sqrt(1 - cosO**2)
            wo = np.array([sinO, 0.0, cosO])
            Ar, At = directional_albedo_bruteforce(wo, rough, 300, 300)
            ang = np.degrees(np.arccos(cosO))
            print(f"{rough:>6.2f} {ang:>5.0f}d | {Ar:>8.4f} {At:>8.4f} {Ar+At:>8.4f}")
        print()


if __name__ == "__main__":
    main()
