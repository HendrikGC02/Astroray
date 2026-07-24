#pragma once
// pkg151 — GPU mirror of DisneyEnergyCompensationTables' glass (rough
// dielectric transmission) multi-scatter tables.
//
// Same data as include/astroray/energy_compensation.h /
// data/disney_compensation/ggx_glass_{E,Eavg,inv_E,inv_Eavg}.bin — ported
// from Blender Cycles intern/cycles/scene/shader.tables (Apache-2.0,
// table_ggx_glass_E[4096]/_Eavg[256]/_inv_E[4096]/_inv_Eavg[256]) and
// intern/cycles/kernel/closure/bsdf_microfacet.h
// microfacet_ggx_preserve_energy + bsdf_util.h fresnel_dielectric_Fss
// (BSD-3-Clause). See data/disney_compensation/README.md and
// .astroray_plan/docs/pkg151-cycles-glass-tables-research.md for the full
// citation trail.
//
// The tables are kept in device GLOBAL memory (not __constant__) and
// accessed via extern __device__ pointers populated once by
// uploadGgxGlassTables() — mirrors the Jakob-Hanika LUT pattern in
// src/gpu/gpu_spectral_tables.cu (g_jhLutScale/g_jhLutCoeffs), chosen here
// specifically because gpu_materials.h (which needs these tables inside
// gpu_disney_roughTransmissionEval) is included by many .cu translation
// units — declaring the data as per-TU __constant__ arrays directly in a
// widely-included header risks either N-way duplication of the 64KB
// constant-memory budget or device-linker multiple-definition errors under
// this project's relocatable-device-code build; a single extern global
// pointer, defined once in gpu_glass_tables.cu, avoids both.
//
// Only include this from .cu files compiled by nvcc.

#include "gpu_types.h"
#include <cuda_runtime.h>

static constexpr int G_GLASS_TABLE_SIZE = 16;  // Cycles' 16^3 / 16^2 resolution.

// Defined once in gpu_glass_tables.cu; populated by uploadGgxGlassTables().
extern __device__ const float* g_ggxGlassE;         // [16*16*16]
extern __device__ const float* g_ggxGlassEavg;      // [16*16]
extern __device__ const float* g_ggxGlassInvE;      // [16*16*16]
extern __device__ const float* g_ggxGlassInvEavg;   // [16*16]

// Host-callable one-time upload (defined in gpu_glass_tables.cu); copies the
// same host-side DisneyEnergyCompensationTables data CPU disney.cpp uses.
void uploadGgxGlassTables();

// ---------------------------------------------------------------------------
// Device-side lookups — mirror
// astroray::DisneyEnergyCompensationTables::sample3D/sample2D/ggxGlassE/
// ggxGlassEavg exactly (same axis order: roughness fastest, then mu, then z).
// ---------------------------------------------------------------------------

__device__ inline float gpu_glass_sample3D(
        const float* table, float roughness, float mu, float z)
{
    const int size = G_GLASS_TABLE_SIZE;
    roughness = fminf(fmaxf(roughness, 0.f), 1.f);
    mu        = fminf(fmaxf(mu, 0.f), 1.f);
    z         = fminf(fmaxf(z, 0.f), 1.f);

    float fx = roughness * float(size - 1);
    float fy = mu * float(size - 1);
    float fz = z * float(size - 1);
    int x0 = min(max((int)fx, 0), size - 1);
    int y0 = min(max((int)fy, 0), size - 1);
    int z0 = min(max((int)fz, 0), size - 1);
    int x1 = min(x0 + 1, size - 1);
    int y1 = min(y0 + 1, size - 1);
    int z1 = min(z0 + 1, size - 1);
    float tx = fx - float(x0);
    float ty = fy - float(y0);
    float tz = fz - float(z0);

    auto at = [&] __device__ (int xi, int yi, int zi) {
        return table[(zi * size + yi) * size + xi];
    };
    float c00 = at(x0, y0, z0) * (1.f - tx) + at(x1, y0, z0) * tx;
    float c10 = at(x0, y1, z0) * (1.f - tx) + at(x1, y1, z0) * tx;
    float c01 = at(x0, y0, z1) * (1.f - tx) + at(x1, y0, z1) * tx;
    float c11 = at(x0, y1, z1) * (1.f - tx) + at(x1, y1, z1) * tx;
    float c0 = c00 * (1.f - ty) + c10 * ty;
    float c1 = c01 * (1.f - ty) + c11 * ty;
    return c0 * (1.f - tz) + c1 * tz;
}

__device__ inline float gpu_glass_sample2D(
        const float* table, float roughness, float z)
{
    const int size = G_GLASS_TABLE_SIZE;
    roughness = fminf(fmaxf(roughness, 0.f), 1.f);
    z         = fminf(fmaxf(z, 0.f), 1.f);

    float fx = roughness * float(size - 1);
    float fy = z * float(size - 1);
    int x0 = min(max((int)fx, 0), size - 1);
    int y0 = min(max((int)fy, 0), size - 1);
    int x1 = min(x0 + 1, size - 1);
    int y1 = min(y0 + 1, size - 1);
    float tx = fx - float(x0);
    float ty = fy - float(y0);

    float v00 = table[y0 * size + x0];
    float v10 = table[y0 * size + x1];
    float v01 = table[y1 * size + x0];
    float v11 = table[y1 * size + x1];
    float vx0 = v00 * (1.f - tx) + v10 * tx;
    float vx1 = v01 * (1.f - tx) + v11 * tx;
    return vx0 * (1.f - ty) + vx1 * ty;
}

// Cycles bsdf_microfacet.h microfacet_ggx_preserve_energy glass branch
// (BSD-3-Clause): z = sqrt(|ior-1|/(ior+1)), swap to the _inv_ tables when
// ior < 1 (looked up at ior'=1/ior).
__device__ inline float gpu_ggxGlassE(float roughness, float mu, float ior) {
    bool inv = ior < 1.f;
    float iorEff = inv ? (1.f / ior) : ior;
    float z = sqrtf(fabsf((iorEff - 1.f) / (iorEff + 1.f)));
    return gpu_glass_sample3D(inv ? g_ggxGlassInvE : g_ggxGlassE, roughness, mu, z);
}

__device__ inline float gpu_ggxGlassEavg(float roughness, float ior) {
    bool inv = ior < 1.f;
    float iorEff = inv ? (1.f / ior) : ior;
    float z = sqrtf(fabsf((iorEff - 1.f) / (iorEff + 1.f)));
    return gpu_glass_sample2D(inv ? g_ggxGlassInvEavg : g_ggxGlassEavg, roughness, z);
}

// Kulla & Conty 2017 hemispherical-average Fresnel reflectance fit, ported
// from Cycles bsdf_util.h fresnel_dielectric_Fss (BSD-3-Clause) — same
// formula as CPU disney.cpp::fresnelDielectricFss.
__device__ inline float gpu_fresnelDielectricFss(float eta) {
    if (eta < 1.f) {
        return 0.997118f + eta * (0.1014f - eta * (0.965241f + eta * 0.130607f));
    }
    return (eta - 1.f) / (4.08567f + 1.00071f * eta);
}

// Net compensation factor, mirroring CPU disney.cpp::ggxGlassCompensationFactor
// / ggxDarkeningChannel (Cycles microfacet_ggx_preserve_energy:
// missing_factor = (1-E)/E; Fms = Fss*Eavg/(1-Fss*(1-Eavg));
// factor = 1 + Fms*missing_factor).
__device__ inline float gpu_ggxGlassCompensationFactor(
        float roughness, float etap, float muAbs)
{
    // Graceful no-op if uploadGgxGlassTables() hasn't run or the host-side
    // .bin files failed to load — mirrors CPU disney.cpp's
    // `tables.loaded()` guard in ggxGlassCompensationFactor.
    if (!g_ggxGlassE || !g_ggxGlassEavg || !g_ggxGlassInvE || !g_ggxGlassInvEavg) {
        return 1.f;
    }

    float E = fmaxf(gpu_ggxGlassE(roughness, muAbs, etap), 1e-4f);
    float Eavg = fminf(fmaxf(gpu_ggxGlassEavg(roughness, etap), 0.f), 0.999f);
    float Fss = fminf(fmaxf(gpu_fresnelDielectricFss(etap), 0.f), 0.999f);

    float missing = (1.f - E) / E;
    float denom = fmaxf(1.f - Fss * (1.f - Eavg), 1e-4f);
    float Fms = Fss * Eavg / denom;
    return 1.f + Fms * missing;
}
