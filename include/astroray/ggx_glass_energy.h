#pragma once
// Cycles MULTI_GGX rough glass: single-scatter GGX glass + albedo-scaling energy
// compensation. Shared by the CPU (plugins/materials/principled.cpp) and the GPU
// (gpu_materials.h via gpu_glass_tables.cuh), so both backends run ONE lookup and
// ONE evaluator.
//
// Source: Blender 5.2 Cycles (tag v5.2.0), BSD-3-Clause / Apache-2.0:
//   intern/cycles/kernel/closure/bsdf_microfacet.h
//     microfacet_ggx_preserve_energy (glass branch), bsdf_microfacet_eval,
//     bsdf_microfacet_sample (pdf_reflect), bsdf_D / bsdf_lambda (GGX)
//   intern/cycles/kernel/util/lookup_table.h  lookup_table_read{,_2D,_3D}
//   intern/cycles/app/cycles_precompute.cpp   (how the glass E tables were made)
// Tables: data/disney_compensation/ggx_glass_{E,Eavg,inv_E,inv_Eavg}.bin, byte-identical
// to intern/cycles/scene/shader.tables at v5.2.0 (checked 2026-10-06).
// Paper: Kulla & Conty 2017, "Revisiting Physically Based Shading at Imageworks"
// (albedo scaling + Fms). Notes: .astroray_plan/docs/cycles-multiggx-glass-research.md
//
// Conventions: Astroray names the view direction wo and the light direction wi (Cycles
// calls them wi and wo). `etap` is the relative IOR of the far side over the view side
// (Cycles bsdf->ior: ior on a front face, 1/ior on a back face).

#include <math.h>

#if defined(__CUDACC__)
#  define AR_GGXG_HD __host__ __device__
#else
#  define AR_GGXG_HD
#endif

namespace astroray {
namespace ggxglass {

constexpr int kTableSize = 16;  // Cycles 16^3 (E) / 16^2 (Eavg)

// Device or host pointers to the four Cycles glass tables (null = not loaded).
struct Tables {
    const float* E;
    const float* Eavg;
    const float* invE;
    const float* invEavg;
};

AR_GGXG_HD inline float saturate(float x) { return fminf(fmaxf(x, 0.0f), 1.0f); }

// lookup_table_read: linear interpolation, x in [0,1] over `size` samples.
AR_GGXG_HD inline float read1D(const float* t, float x, int size) {
    x = saturate(x) * float(size - 1);
    int index = int(x);
    if (index > size - 1) index = size - 1;
    const int nindex = (index + 1 < size - 1) ? index + 1 : size - 1;
    const float f = x - float(index);
    const float d0 = t[index];
    if (f == 0.0f) return d0;
    return (1.0f - f) * d0 + f * t[nindex];
}

// lookup_table_read_2D: x fastest.
AR_GGXG_HD inline float read2D(const float* t, float x, float y, int xs, int ys) {
    y = saturate(y) * float(ys - 1);
    int index = int(y);
    if (index > ys - 1) index = ys - 1;
    const int nindex = (index + 1 < ys - 1) ? index + 1 : ys - 1;
    const float f = y - float(index);
    const float d0 = read1D(t + xs * index, x, xs);
    if (f == 0.0f) return d0;
    return (1.0f - f) * d0 + f * read1D(t + xs * nindex, x, xs);
}

// lookup_table_read_3D: x fastest, then y, then z.
AR_GGXG_HD inline float read3D(const float* t, float x, float y, float z, int xs, int ys, int zs) {
    z = saturate(z) * float(zs - 1);
    int index = int(z);
    if (index > zs - 1) index = zs - 1;
    const int nindex = (index + 1 < zs - 1) ? index + 1 : zs - 1;
    const float f = z - float(index);
    const float d0 = read2D(t + xs * ys * index, x, y, xs, ys);
    if (f == 0.0f) return d0;
    return (1.0f - f) * d0 + f * read2D(t + xs * ys * nindex, x, y, xs, ys);
}

// microfacet_ggx_preserve_energy, CLOSURE_BSDF_MICROFACET_GGX_GLASS_ID branch:
// rough = sqrt(alpha), mu = cos(N, view), ior < 1 reads the _inv_ tables at 1/ior,
// z = sqrt(|ior-1|/(ior+1)). Returns false (E = Eavg = 1, i.e. no compensation) when
// the tables are not loaded.
AR_GGXG_HD inline bool albedo(const Tables& tb, float rough, float mu, float ior,
                              float& E, float& Eavg) {
    if (!tb.E || !tb.Eavg || !tb.invE || !tb.invEavg) {
        E = 1.0f;
        Eavg = 1.0f;
        return false;
    }
    const float* tabE = tb.E;
    const float* tabAvg = tb.Eavg;
    if (ior < 1.0f) {
        ior = 1.0f / ior;
        tabE = tb.invE;
        tabAvg = tb.invEavg;
    }
    const float z = sqrtf(fabsf((ior - 1.0f) / (ior + 1.0f)));
    E = fmaxf(read3D(tabE, rough, mu, z, kTableSize, kTableSize, kTableSize), 1e-4f);
    Eavg = read2D(tabAvg, rough, z, kTableSize, kTableSize);
    return true;
}

// bsdf->energy_scale = 1 + (1-E)/E, applied to eval and sample of both sub-lobes.
AR_GGXG_HD inline float energyScale(float E) { return 1.0f + (1.0f - E) / E; }

// Closure-weight darkening for one channel of Fss (Cycles: Fss = transmission tint for a
// glass closure). Fms = Fss*Eavg/(1 - Fss*(1-Eavg)); darkening = (1 + Fms*missing) /
// energy_scale. Exactly 1 for Fss == 1 (clear glass), < 1 otherwise. Cycles takes
// sqrt(clamped base colour) as Fss, so it is clamped to [0,1] here.
AR_GGXG_HD inline float darkening(float Fss, float E, float Eavg) {
    Fss = saturate(Fss);
    if (Fss == 1.0f) return 1.0f;
    const float missing = (1.0f - E) / E;
    const float Fms = Fss * Eavg / (1.0f - Fss * (1.0f - Eavg));
    return (1.0f + Fms * missing) / energyScale(E);
}

// bsdf_microfacet_sample / _eval: pdf_reflect = average(reflectance) /
// average(reflectance + transmittance), reflectance = F*reflTint, transmittance =
// (1-F)*transTint (tints as channel averages).
AR_GGXG_HD inline float reflectProb(float F, float reflTintAvg, float transTintAvg) {
    const float r = F * reflTintAvg;
    const float s = r + (1.0f - F) * transTintAvg;
    return (s > 0.0f) ? r / s : F;
}

// bsdf_D<GGX> and bsdf_lambda<GGX> (Heitz 2014 Eq. 72); alpha2 = alpha_x*alpha_y.
AR_GGXG_HD inline float ggxD(float alpha2, float cosNH) {
    const float c2 = fminf(cosNH * cosNH, 1.0f);
    const float t = (1.0f - c2) + alpha2 * c2;
    return alpha2 / (3.14159265358979323846f * t * t);
}
AR_GGXG_HD inline float ggxLambda(float alpha2, float cosN) {
    const float c2 = fmaxf(cosN * cosN, 1e-12f);
    return 0.5f * (sqrtf(1.0f + alpha2 * fmaxf(1.0f / c2 - 1.0f, 0.0f)) - 1.0f);
}

// Single-scatter part of bsdf_microfacet_eval for the isotropic GGX glass, without
// Fresnel, tint or energy terms:
//   value: reflect  D*G2/(4 cosO)                                      (= f*|cosI| / F)
//          transmit D*G2*|HO*HI| / (cosO*(HI + HO/etap)^2) / etap^2    (= f*|cosI| / (1-F))
//   pdf:   VNDF density x Jacobian (G1(view) = 1/(1+lambdaO)), without the lobe probability.
// Cycles' transmission eval has no 1/etap^2; Astroray keeps the pbrt-v4 radiance-mode
// factor its delta and walk glass already use. It cancels across a closed object (the
// furnace and every rough-glass gate), so the light leaving a solid is Cycles'.
// H must face N; HO = H.view > 0. cosO > 0 (view above N), cosI = N.light (sign ignored).
struct SingleScatter {
    float value;
    float pdf;
};
AR_GGXG_HD inline SingleScatter evalSingleScatter(bool transmit, float cosO, float cosI,
                                                  float cosNH, float HO, float HI,
                                                  float etap, float alpha2) {
    const float D = ggxD(alpha2, cosNH);
    const float lO = ggxLambda(alpha2, cosO);
    const float lI = ggxLambda(alpha2, cosI);
    float common;
    if (transmit) {
        const float d = HI + HO / etap;
        common = D / cosO * fabsf(HO * HI) / fmaxf(d * d, 1e-20f);
    } else {
        common = D / cosO * 0.25f;
    }
    SingleScatter r;
    r.pdf = common / (1.0f + lO);
    r.value = common / (1.0f + lO + lI);
    if (transmit) r.value /= etap * etap;
    return r;
}

}  // namespace ggxglass
}  // namespace astroray
