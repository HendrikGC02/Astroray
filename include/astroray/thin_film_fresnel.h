#pragma once
// ===========================================================================
// pkg178 Stage 4 — Shared thin-film (iridescence) Fresnel utility.
//
// Belcour & Barla 2017, "A Practical Extension to Microfacet Theory for the
// Modeling of Varying Iridescence", ACM TOG 36(4):65, DOI
// 10.1145/3072959.3073620 (project page:
// https://belcour.github.io/blog/research/publication/2017/05/01/brdf-thin-film.html).
//
// VERBATIM math port (CLAUDE.md §6) from blender/blender `main` (2026-08-10),
// BSD-3-Clause:
//   intern/cycles/kernel/closure/bsdf_util.h
//     fresnel_dielectric_polarized              :47  -> fresnelDielectricPolarized
//     fresnel_conductor_polarized               :200 -> fresnelConductorPolarized
//     iridescence_lookup_sensitivity_channel    :456 -> sensitivityRGB
//     iridescence_airy_summation_channel        :468 -> airySummationChannel
//     fresnel_iridescence_channel               :499 -> fresnelIridescenceChannel
//   intern/cycles/kernel/closure/bsdf_microfacet.h
//     adjust_thin_film_ior_at_backface          :86  -> adjustThinFilmIorAtBackface
//   intern/cycles/kernel/util/lookup_table.h
//     lookup_table_read                              -> (clamped linear interp in sensitivityRGB)
//   intern/cycles/kernel/svm/types.h              :577 THINFILM_THICKNESS_CUTOFF
//   intern/cycles/kernel/types.h                  :37  THIN_FILM_TABLE_SIZE
//
// Design (pkg178-stage4-plan.md §0-1):
//   * Single-source, host+device (ASTRORAY_TF_FN). No tables INSIDE the core —
//     the RGB sensitivity LUT is passed in (CPU: thin_film_cie_table.h; GPU:
//     device upload, PR-3). The spectral leg needs NO table — per sampled λ the
//     CIE sensitivity degenerates to the exact analytic phasor
//     exp(i·2π·m·OPD/λ) (pkg128 per-λ design; Belcour §4 RGB projection is
//     intentionally omitted on the spectral path).
//   * Sensitivity is a functor S(argOPD) -> TFComplex; both legs share the SAME
//     truncated m≤3 Airy series (structural parity with Cycles).
//
// PR-1 uses only the dielectric substrate path (<conductive=false>). The
// conductor path (<conductive=true>) + fresnelConductorPolarized are the shared
// library entry PR-2 (CPU metallic) rides — kept here so PR-2/PR-3 add call
// sites only, never touch this core (plan decision #1: one utility, zero
// duplication).
// ===========================================================================

#include <cmath>

#if defined(__CUDACC__)
#define ASTRORAY_TF_FN __host__ __device__ inline
#else
#define ASTRORAY_TF_FN inline
#endif

namespace astroray {
namespace thinfilm {

// svm/types.h:577 — film active iff thickness (nm) > this.
inline constexpr float kThinFilmThicknessCutoff = 0.1f;
// kernel/types.h:37 — CIE sensitivity LUT row count.
inline constexpr int kThinFilmTableSize = 512;
inline constexpr float kTwoPi = 6.28318530717958647692f;

// bsdf_util.h:25 — complex<float>.
struct TFComplex {
    float re;
    float im;
};

// complex multiply: (a.re + i·a.im)·(b.re + i·b.im).
ASTRORAY_TF_FN TFComplex tfMul(TFComplex a, TFComplex b) {
    return {a.re * b.re - a.im * b.im, a.re * b.im + a.im * b.re};
}
// complex·scalar (bsdf_util.h:37 operator*(float)).
ASTRORAY_TF_FN TFComplex tfScale(TFComplex a, float s) {
    return {a.re * s, a.im * s};
}

ASTRORAY_TF_FN float tfSaturate(float x) {
    return x < 0.0f ? 0.0f : (x > 1.0f ? 1.0f : x);
}

// bsdf_microfacet.h:86 — the backface IOR stack (bulk|film|air) is optically
// equivalent to (air | film/bulk | 1/bulk), so divide film_ior by bulk_ior.
ASTRORAY_TF_FN void adjustThinFilmIorAtBackface(float& filmIor, float invBulkIor) {
    filmIor *= invBulkIor;
}

// bsdf_util.h:47 — polarized dielectric Fresnel. Returns the squared amplitudes
// (energy) Rs, Rp; the (negative) refracted cosine relative to the normal; and
// the reflection-phase signs cosPhiS/cosPhiP (±1; for a dielectric the phase is
// 0 or π). tir=true is total internal reflection (Rs=Rp=1).
struct TFDielectric {
    float Rs;
    float Rp;
    float cosThetaT;
    float cosPhiS;
    float cosPhiP;
    bool tir;
};
ASTRORAY_TF_FN TFDielectric fresnelDielectricPolarized(float cosThetaI, float eta) {
    TFDielectric r;
    // Snell: squared cosine of the transmitted angle (×η²).
    const float etaCosThetaTSq = eta * eta - (1.0f - cosThetaI * cosThetaI);
    if (etaCosThetaTSq <= 0.0f) {
        r.Rs = 1.0f;
        r.Rp = 1.0f;
        r.cosThetaT = 0.0f;
        r.cosPhiS = 1.0f;  // one_float2() (TIR phase omitted — see Cycles :60-67)
        r.cosPhiP = 1.0f;
        r.tir = true;
        return r;
    }
    cosThetaI = std::fabs(cosThetaI);
    const float cosThetaT = -std::sqrt(etaCosThetaTSq) / eta;  // relative to normal
    r.cosThetaT = cosThetaT;
    const float rs = (cosThetaI + eta * cosThetaT) / (cosThetaI - eta * cosThetaT);
    const float rp = (cosThetaT + eta * cosThetaI) / (eta * cosThetaI - cosThetaT);
    r.cosPhiS = (rs >= 0.0f) ? 1.0f : -1.0f;  // 2*(rs>=0)-1
    r.cosPhiP = (rp >= 0.0f) ? 1.0f : -1.0f;
    r.Rs = rs * rs;
    r.Rp = rp * rp;
    r.tir = false;
    return r;
}

// bsdf_util.h:186 — scalar F82 evaluation (used by the conductor phase branch).
ASTRORAY_TF_FN float fresnelF82(float cosi, float F0, float B) {
    const float s = tfSaturate(1.0f - cosi);
    const float s5 = (s * s) * (s * s) * s;
    const float fSchlick = F0 + (1.0f - F0) * s5;  // mix(F0, 1, s5)
    const float v = fSchlick - B * cosi * s5 * s;
    return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v);
}
// bsdf_util.h:169 — scalar F82 B term from (F0, F82).
ASTRORAY_TF_FN float fresnelF82B(float F0, float F82) {
    const float f = 6.0f / 7.0f;
    const float f5 = (f * f) * (f * f) * f;
    const float fSchlick = F0 + (1.0f - F0) * f5;  // mix(F0, 1, f5)
    return (7.0f / (f5 * f)) * (fSchlick - F82);
}

// bsdf_util.h:200 — polarized conductor Fresnel (Born & Wolf §14.4.1, n+ik).
// F82>=0 selects the F82-model reflectance magnitude with the PHYSICAL phase.
// (Shared library entry — used by PR-2's metallic lobe / PR-3 GPU twin.)
ASTRORAY_TF_FN void fresnelConductorPolarized(float cosi, float ambientIor,
                                              TFComplex conductorIor, float F82,
                                              float& rRs, float& rRp,
                                              TFComplex* rPhasorS, TFComplex* rPhasorP) {
    const float eta1 = ambientIor;
    const float eta2 = conductorIor.re;
    const float k2 = conductorIor.im;

    const float eta1Sq = eta1 * eta1;
    const float eta2Sq = eta2 * eta2;
    const float k2Sq = k2 * k2;
    const float twoEta2K2 = 2.0f * eta2 * k2;

    const float t1 = eta2Sq - k2Sq - eta1Sq * (1.0f - cosi * cosi);
    const float t2 = std::sqrt(t1 * t1 + twoEta2K2 * twoEta2K2);

    const float uSq = std::fmax(0.5f * (t2 + t1), 0.0f);
    const float vSq = std::fmax(0.5f * (t2 - t1), 0.0f);
    const float u = std::sqrt(uSq);
    const float v = std::sqrt(vSq);

    if (F82 >= 0.0f) {
        const float n = eta2 / eta1;
        const float kSq = (k2 / eta1) * (k2 / eta1);
        const float F0 = ((n - 1.0f) * (n - 1.0f) + kSq) / ((n + 1.0f) * (n + 1.0f) + kSq);
        rRs = fresnelF82(cosi, F0, fresnelF82B(F0, F82));
        rRp = rRs;
    } else {
        const float denomS = (eta1 * cosi + u) * (eta1 * cosi + u) + vSq;
        rRs = denomS != 0.0f ? ((eta1 * cosi - u) * (eta1 * cosi - u) + vSq) / denomS : 0.0f;
        const float t3 = (eta2Sq - k2Sq) * cosi;
        const float t4 = twoEta2K2 * cosi;
        const float denomP = (t3 + eta1 * u) * (t3 + eta1 * u) + (t4 + eta1 * v) * (t4 + eta1 * v);
        rRp = denomP != 0.0f
                  ? ((t3 - eta1 * u) * (t3 - eta1 * u) + (t4 - eta1 * v) * (t4 - eta1 * v)) / denomP
                  : 0.0f;
    }

    if (rPhasorS && rPhasorP) {
        const float reS = -uSq - vSq + (eta1 * cosi) * (eta1 * cosi);
        const float imS = -2.0f * eta1 * cosi * v;
        const float magS = std::sqrt(reS * reS + imS * imS);
        rPhasorS->re = (magS == 0.0f) ? 1.0f : reS / magS;
        rPhasorS->im = (magS == 0.0f) ? 0.0f : imS / magS;

        const float reP = ((eta2Sq + k2Sq) * cosi) * ((eta2Sq + k2Sq) * cosi) - eta1Sq * (uSq + vSq);
        const float imP = 2.0f * eta1 * cosi * (twoEta2K2 * u - (eta2Sq - k2Sq) * v);
        const float magP = std::sqrt(reP * reP + imP * imP);
        rPhasorP->re = (magP == 0.0f) ? 1.0f : reP / magP;
        rPhasorP->im = (magP == 0.0f) ? 0.0f : imP / magP;
    }
}

// -------------------------------------------------------------------------
// Sensitivity providers S(argOPD) -> TFComplex, argOPD = m·OPD (nm).
// -------------------------------------------------------------------------
// Spectral leg (Astroray simplification, pkg128): the exact single-λ CMF is a
// delta, whose Fourier transform (DC-normalized to 1) is exp(i·2π·argOPD/λ).
ASTRORAY_TF_FN TFComplex sensitivitySpectral(float argOPD, float lambdaNm) {
    const float a = kTwoPi * argOPD / lambdaNm;
    return {std::cos(a), std::sin(a)};
}
// RGB leg (bsdf_util.h:456 + lookup_table.h): clamped linear interp of the
// Rec.709-baked CIE sensitivity LUT. `table` is [kThinFilmTableSize][6] with
// columns {re_R, re_G, re_B, im_R, im_G, im_B} (see thin_film_cie_table.h). The
// LUT domain covers OPD 0..60µm via x = 2π·argOPD/60000.
ASTRORAY_TF_FN TFComplex sensitivityRGB(float argOPD, int channel, const float (*table)[6]) {
    float x = kTwoPi * argOPD / 60000.0f;
    x = tfSaturate(x) * float(kThinFilmTableSize - 1);
    int idx = int(x);
    if (idx > kThinFilmTableSize - 1) idx = kThinFilmTableSize - 1;
    int nidx = (idx + 1 < kThinFilmTableSize) ? idx + 1 : kThinFilmTableSize - 1;
    const float t = x - float(idx);
    const float re = (1.0f - t) * table[idx][channel] + t * table[nidx][channel];
    const float im = (1.0f - t) * table[idx][channel + 3] + t * table[nidx][channel + 3];
    return {re, im};
}

// bsdf_util.h:468 — Airy summation (paper Eq. 10), truncated at m=3. SensFn is
// S(float argOPD)->TFComplex (argOPD = m·OPD).
template <typename SensFn>
ASTRORAY_TF_FN float airySummationChannel(float R12, float R23, float OPD, TFComplex phasor,
                                          SensFn&& S) {
    const float T121 = 1.0f - R12;
    const float R123 = R12 * R23;
    const float r123 = std::sqrt(R123);
    const float Rs = (T121 * T121) * R23 / (1.0f - R123);

    TFComplex accumulator = phasor;  // exp(i·φ)^m, incremental
    float R = Rs + R12;              // C0
    float Cm = Rs - T121;

    for (int m = 1; m < 4; ++m) {
        Cm *= r123;
        const TFComplex Sv = S(float(m) * OPD);
        R += Cm * 2.0f * (accumulator.re * Sv.re + accumulator.im * Sv.im);
        accumulator = tfMul(accumulator, phasor);
    }
    return R;
}

// bsdf_util.h:499 — per-channel / per-λ iridescence driver. `S` supplies the
// sensitivity (RGB LUT or analytic spectral). For the dielectric path
// (<conductive=false>), substrateK/F82 are ignored and rCosTheta3 (if non-null)
// receives the substrate refraction cosine.
template <bool conductive, typename SensFn>
ASTRORAY_TF_FN float fresnelIridescenceChannel(float ambientIor, float thicknessNm,
                                               float filmIorIn, float substrateN,
                                               float substrateK, float F82, float cosTheta1,
                                               float* rCosTheta3, SensFn&& S) {
    // Sub-1nm blend towards the film-free case (wave-optics cutoff).
    float filmIor = filmIorIn;
    if (thicknessNm < 1.0f) {
        float t = thicknessNm;
        t = t < 0.0f ? 0.0f : (t > 1.0f ? 1.0f : t);
        const float ss = t * t * (3.0f - 2.0f * t);  // smoothstep(0,1,thickness)
        filmIor = ambientIor + (filmIor - ambientIor) * ss;
    }

    // Top interface (ambient -> film).
    const TFDielectric R12 = fresnelDielectricPolarized(cosTheta1, filmIor / ambientIor);
    if (R12.tir) return 1.0f;
    const float cosTheta2 = R12.cosThetaT;

    // Bottom interface (film -> substrate).
    float R23s, R23p;
    TFComplex phasor23s, phasor23p;
    if (conductive) {
        fresnelConductorPolarized(-cosTheta2, filmIor, {substrateN, substrateK}, F82, R23s, R23p,
                                  &phasor23s, &phasor23p);
    } else {
        const TFDielectric R23 = fresnelDielectricPolarized(-cosTheta2, substrateN / filmIor);
        if (R23.tir) return 1.0f;  // Airy math simplifies to 1 at bottom TIR
        if (rCosTheta3) *rCosTheta3 = R23.cosThetaT;
        R23s = R23.Rs;
        R23p = R23.Rp;
        phasor23s = {R23.cosPhiS, 0.0f};
        phasor23p = {R23.cosPhiP, 0.0f};
    }

    // Optical path difference inside the film (positive; cosTheta2 < 0).
    const float OPD = -2.0f * filmIor * thicknessNm * cosTheta2;

    // Full reflection phase per polarization: exp(i·(φ23 + φ21)).
    const TFComplex phasorS = tfScale(phasor23s, -R12.cosPhiS);
    const float Rs = airySummationChannel(R12.Rs, R23s, OPD, phasorS, S);
    const TFComplex phasorP = tfScale(phasor23p, -R12.cosPhiP);
    const float Rp = airySummationChannel(R12.Rp, R23p, OPD, phasorP, S);

    return tfSaturate(0.5f * (Rs + Rp));
}

}  // namespace thinfilm
}  // namespace astroray
