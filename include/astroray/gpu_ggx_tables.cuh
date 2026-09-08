#pragma once
// pkg152 — GPU mirror of DisneyEnergyCompensationTables' REFLECTION-lobe
// (metal / dielectric-specular / sheen / clearcoat) multi-scatter tables.
//
// gpu_disney_eval (gpu_materials.h) never applied any of the CPU
// disney.cpp::eval() compensation/layering terms this header backs
// (ggxCompensationFactor, ggxDirectionalAlbedo, layeringWeightAfter,
// diffuseFurnaceScale, the sheen/clearcoat table lookups) -- confirmed
// absent by grep of gpu_materials.h prior to this package. Leading
// hypothesis for the pkg141-adjudicated residual GPU-dim Disney-metal
// parity ratios (0.60-0.77 near-delta, per pkg152 spec); measured effect
// recorded in .astroray_plan/docs/pkg152-gpu-twin-parity-research.md.
//
// Same data/citations as include/astroray/energy_compensation.h /
// data/disney_compensation/{ggx,sheen,clearcoat}_E*.bin — ported from
// Blender Cycles intern/cycles/scene/shader.tables (Apache-2.0,
// table_ggx_E/table_ggx_Eavg etc.) and
// intern/cycles/kernel/closure/bsdf_microfacet.h
// microfacet_ggx_preserve_energy (BSD-3-Clause); Kulla & Conty 2017,
// "Revisiting Physically Based Shading at Imageworks" (the darkening-
// factor derivation CPU disney.cpp::ggxDarkeningChannel already cites).
//
// Tables live in device GLOBAL memory (not __constant__), uploaded once by
// uploadGgxTables() -- mirrors the pkg151 glass-table pattern in
// gpu_glass_tables.cuh/.cu exactly (same rationale: gpu_materials.h is
// included by many .cu translation units, so a single extern global
// pointer avoids constant-memory duplication / device-linker
// multiple-definition errors).
//
// Only include this from .cu files compiled by nvcc.

#include "gpu_types.h"
#include <cuda_runtime.h>

static constexpr int G_GGX_TABLE_SIZE       = 32;  // DisneyEnergyCompensationTables::kGgxSize
static constexpr int G_SHEEN_TABLE_SIZE     = 32;  // kSheenSize
static constexpr int G_CLEARCOAT_TABLE_SIZE = 32;  // kClearcoatSize
static constexpr int G_GEN_SCHLICK_SIZE     = 16;  // kGenSchlickSize (pkg261)

// Defined once in gpu_ggx_tables.cu; populated by uploadGgxTables().
extern __device__ const float* g_ggxE;         // [32*32]
extern __device__ const float* g_ggxEavg;      // [32]
extern __device__ const float* g_sheenE;       // [32*32]
extern __device__ const float* g_clearcoatE;   // [32]
extern __device__ const float* g_ggxGenSchlickIorS;  // pkg261 [16*16*16]

// Host-callable one-time upload (defined in gpu_ggx_tables.cu); copies the
// same host-side DisneyEnergyCompensationTables data CPU disney.cpp uses.
void uploadGgxTables();

// ---------------------------------------------------------------------------
// Device-side lookups — mirror
// astroray::DisneyEnergyCompensationTables::sample2D/sample1D exactly.
// ---------------------------------------------------------------------------

__device__ inline float gpu_ggx_sample2D(
        const float* table, int size, float roughness, float mu)
{
    roughness = fminf(fmaxf(roughness, 0.f), 1.f);
    mu        = fminf(fmaxf(mu, 0.f), 1.f);

    float fx = roughness * float(size - 1);
    float fy = mu * float(size - 1);
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

__device__ inline float gpu_ggx_sample1D(const float* table, int size, float x) {
    x = fminf(fmaxf(x, 0.f), 1.f);
    float fx = x * float(size - 1);
    int x0 = min(max((int)fx, 0), size - 1);
    int x1 = min(x0 + 1, size - 1);
    float t = fx - float(x0);
    return table[x0] * (1.f - t) + table[x1] * t;
}

__device__ inline float gpu_ggxE(float roughness, float mu) {
    return gpu_ggx_sample2D(g_ggxE, G_GGX_TABLE_SIZE, roughness, mu);
}

__device__ inline float gpu_ggxEavg(float roughness) {
    return gpu_ggx_sample1D(g_ggxEavg, G_GGX_TABLE_SIZE, roughness);
}

__device__ inline float gpu_sheenAlbedo(float roughness, float mu) {
    return gpu_ggx_sample2D(g_sheenE, G_SHEEN_TABLE_SIZE, roughness, mu);
}

__device__ inline float gpu_clearcoatE(float mu) {
    return gpu_ggx_sample1D(g_clearcoatE, G_CLEARCOAT_TABLE_SIZE, mu);
}

// Cycles bsdf_microfacet.h microfacet_ggx_preserve_energy (BSD-3-Clause):
// per-channel darkening factor "1 + Fms*(1-E)/E". Mirrors CPU
// disney.cpp::ggxDarkeningChannel exactly (see that function's comment for
// the full derivation).
__device__ inline float gpu_ggxDarkeningChannel(float f, float E, float Eavg) {
    f = fminf(fmaxf(f, 0.f), 0.999f);
    float missing = (1.f - E) / E;
    float denom = fmaxf(1.f - f * (1.f - Eavg), 1e-4f);
    float Fms = f * Eavg / denom;
    return 1.f + Fms * missing;
}

// Mirrors CPU disney.cpp::ggxCompensationFactor. `Fss` is the layer's own
// (achromatic-per-channel) Fresnel reflectance channel, evaluated at the
// half-vector/light angle by the caller (fresnelSchlick(LdotH, F0, ...) on
// the CPU side).
__device__ inline GVec3 gpu_ggxCompensationFactor(
        const GVec3& Fss, float roughness, float mu)
{
    if (!g_ggxE || !g_ggxEavg) return GVec3(1.f, 1.f, 1.f);

    float E = fmaxf(gpu_ggxE(roughness, mu), 1e-4f);
    float Eavg = fminf(fmaxf(gpu_ggxEavg(roughness), 0.f), 0.999f);
    return GVec3(gpu_ggxDarkeningChannel(Fss.x, E, Eavg),
                 gpu_ggxDarkeningChannel(Fss.y, E, Eavg),
                 gpu_ggxDarkeningChannel(Fss.z, E, Eavg));
}

// Mirrors CPU disney.cpp::ggxDirectionalAlbedo -- the compensated GGX
// specular layer's own directional-hemispherical reflectance at wo, used to
// attenuate whatever layer sits below it (Kulla & Conty 2017 layering).
__device__ inline GVec3 gpu_ggxDirectionalAlbedo(
        const GVec3& Fview, float roughness, float mu)
{
    if (!g_ggxE || !g_ggxEavg) return Fview;

    float E = fmaxf(gpu_ggxE(roughness, mu), 1e-4f);
    float Eavg = fminf(fmaxf(gpu_ggxEavg(roughness), 0.f), 0.999f);
    auto channel = [=] __device__ (float f) {
        float fc = fminf(fmaxf(f, 0.f), 0.999f);
        return E * fc * gpu_ggxDarkeningChannel(fc, E, Eavg);
    };
    return GVec3(channel(Fview.x), channel(Fview.y), channel(Fview.z));
}

// Mirrors CPU disney.cpp::layeringWeightAfter (Kulla & Conty 2017 Eq. 6-9
// layering; Cycles closure_layering_weight, bsdf_util.h, Apache-2.0).
__device__ inline GVec3 gpu_layeringWeightAfter(const GVec3& weight, const GVec3& albedo) {
    GVec3 clampedAlbedo(fminf(albedo.x, 0.999f), fminf(albedo.y, 0.999f), fminf(albedo.z, 0.999f));
    return GVec3(weight.x * (1.f - clampedAlbedo.x),
                 weight.y * (1.f - clampedAlbedo.y),
                 weight.z * (1.f - clampedAlbedo.z));
}

// pkg261: Cycles bsdf_microfacet_estimate_albedo (bsdf_microfacet.h:405-475,
// BSD-3-Clause) generalized-Schlick / dielectric specular-layer albedo. The
// lobe-averaged blend factor s = ggx_gen_schlick_ior_s[rough, cos_NI, z]
// (16^3 trilinear, z = sqrt(|ior-1|/(ior+1))), then albedo = mix(f0, f90=1, s).
// Replaces the pre-pkg261 gpu_ggxDirectionalAlbedo(Fview,...) layering estimate
// in the Principled (gpu_pr_assembleLobes) path only; mirrors CPU
// principled.cpp::ggxLayeringAlbedo byte-for-byte. Trilinear axis order matches
// gpu_glass_sample3D / DisneyEnergyCompensationTables::sample3D (rough fastest,
// then cos_NI, then z).
__device__ inline float gpu_gen_schlick_sample3D(
        const float* table, float roughness, float mu, float z)
{
    const int size = G_GEN_SCHLICK_SIZE;
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

// mix(f0, f90=1, s) directional-albedo estimate for the rough dielectric
// specular/coat layer. `f0` = Fresnel-at-normal reflectance, `mu` = view cosine
// N.wo, `ior` = the layer ior (specular ior_ or coat_ior). Graceful f0 passthrough
// if the table failed to upload (mirrors CPU's `tables.loaded()` guard).
__device__ inline GVec3 gpu_ggxLayeringAlbedo(
        const GVec3& f0, float roughness, float mu, float ior)
{
    if (!g_ggxGenSchlickIorS) return f0;
    float z = sqrtf(fabsf((ior - 1.f) / (ior + 1.f)));
    float s = fminf(fmaxf(gpu_gen_schlick_sample3D(g_ggxGenSchlickIorS, roughness, mu, z), 0.f), 1.f);
    return GVec3(f0.x * (1.f - s) + s, f0.y * (1.f - s) + s, f0.z * (1.f - s) + s);
}

// Mirrors CPU disney.cpp::diffuseFurnaceScale (pkg60 grazing-incidence
// Burley-diffuse furnace normalization). Table-independent, kept here
// alongside the other eval() compensation terms this header ports.
__device__ inline float gpu_diffuseFurnaceScale(float roughness, float mu) {
    float grazing = 1.f - fminf(fmaxf(mu, 0.f), 1.f);
    float excess = roughness * (0.055f + 0.40f * grazing * grazing);
    return 1.f / (1.f + excess);
}
