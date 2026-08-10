#pragma once
// GPU material evaluation — ported from raytracer.h and advanced_features.h.
// All formulas match the CPU reference exactly (same fixes applied).
// Only include this from .cu files compiled by nvcc.

#include "gpu_types.h"
#include "gpu_dispersion.cuh"
#include "gpu_glass_tables.cuh"  // pkg151: rough-transmission multiscatter compensation
#include "gpu_ggx_tables.cuh"    // pkg152: reflection-lobe multiscatter/layering compensation
#include "sheen_ltc_table.h"     // pkg178 Stage 3: sheen LTC table (host/device)
#include "thin_film_fresnel.h"       // pkg178 Stage 4: shared Belcour-Barla iridescence core
#include "gpu_thin_film_table.cuh"   // pkg178 Stage 4 PR-3: device CIE sensitivity LUT + gpu_pr_sensitivityRGB
#include <curand_kernel.h>

#ifndef M_PI_F
#  define M_PI_F 3.14159265358979323846f
#endif

// ---------------------------------------------------------------------------
// Utility: orthonormal basis from normal
// ---------------------------------------------------------------------------
__device__ inline void gpu_buildONB(const GVec3& n, GVec3& t, GVec3& b) {
    t = (fabsf(n.x) > 0.9f) ? GVec3(0,1,0) : GVec3(1,0,0);
    t = (t - n * n.dot(t)).normalized();
    b = n.cross(t);
}

// ---------------------------------------------------------------------------
// RNG dispatch (pkg55-B' template-RNG arc): the sampling functions below are
// templates over the RNG type so the megakernel keeps curandState (XORWOW,
// identical codegen) while the wavefront draws directly from its per-path
// WavefrontRNG (PCG32) stream — eliminating its 2x-per-bounce curand_init
// cost. Additional RNG types provide an overload of gpu_rng_uniform (found
// by ADL at instantiation; see stage_advance.cu for the WavefrontRNG one).
// ---------------------------------------------------------------------------
__device__ inline float gpu_rng_uniform(curandState* rng) {
    return curand_uniform(rng);
}

// ---------------------------------------------------------------------------
// Sampling helpers
// ---------------------------------------------------------------------------
template <typename TRng>
__device__ inline GVec3 gpu_randomCosineDir(TRng* rng) {
    float r1 = gpu_rng_uniform(rng);
    float r2 = gpu_rng_uniform(rng);
    float z   = sqrtf(1.f - r2);
    float phi = 2.f * M_PI_F * r1;
    return GVec3(cosf(phi)*sqrtf(r2), sinf(phi)*sqrtf(r2), z);
}

template <typename TRng>
__device__ inline GVec3 gpu_randomInUnitDisk(TRng* rng) {
    GVec3 p;
    do {
        p.x = gpu_rng_uniform(rng)*2.f - 1.f;
        p.y = gpu_rng_uniform(rng)*2.f - 1.f;
        p.z = 0.f;
    } while (p.length2() >= 1.f);
    return p;
}

template <typename TRng>
__device__ inline GSampledWavelengths gpu_sampleUniformWavelengths(TRng* rng) {
    // Hero layout must match CPU sampleUniform (src/spectrum.cpp:82): hero spans
    // the full band, secondaries are stratified offsets with wrap-around. The
    // prior `(u+i)/N` form confined lam[0] to the first 1/N of the band — see
    // pkg64-gpu-session2-research.md (afternoon update) and stage_init.cu:64.
    GSampledWavelengths wl;
    float u    = gpu_rng_uniform(rng);
    float span = G_LAMBDA_MAX - G_LAMBDA_MIN;
    float step = span / float(G_SPECTRUM_SAMPLES);
    float hero = G_LAMBDA_MIN + u * span;
    float pdf  = 1.f / span;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
        float lam = hero + float(i) * step;
        if (lam > G_LAMBDA_MAX) lam -= span;
        wl.lambda[i] = lam;
        wl.pdf[i] = pdf;
    }
    return wl;
}

// Forward declaration — defined in src/gpu/multiwavelength_kernel.cu.
// Mirrors astroray::sampleD65 (src/spectrum.cpp) via the same baked SPD
// table, normalized so unit white emission integrates to Y = 1.
__device__ float gpu_sampleD65(float lambda);

// Forward declaration — defined in src/gpu/multiwavelength_kernel.cu (pkg54c).
// Jakob & Hanika 2019 sigmoid-coefficient lookup; mirrors CPU
// RGBAlbedoSpectrum::sample() at single wavelength so visible-band SSIM
// reaches parity with the CPU integrator. Requires uploadJakobHanikaLut().
__device__ float gpu_jhEvalSpectrum(const GVec3& rgb, float lambda);

__device__ inline float gpu_rgbSpectrumAt(const GVec3& rgb, float lambda, GSpectralMode mode) {
    if (mode == GSPEC_NONE) return luminance(rgb);
    // pkg54c: JH 2019 sigmoid upsampling replaces the earlier 3-Gaussian
    // RGB-basis stand-in. ILLUMINANT mode mirrors CPU
    // RGBIlluminantSpectrum (src/spectrum.cpp:464-491): renormalize by
    // 2*max(rgb) before the JH lookup, then scale-back and multiply by
    // the normalized D65 SPD (pkg54a/b fix preserved). Without the
    // renormalization the LUT is queried at the wrong location and the
    // visible-band CPU<->GPU SSIM gate (>=0.999) cannot be hit.
    if (mode == GSPEC_RGB_ILLUMINANT) {
        float m = fmaxf(fmaxf(rgb.x, rgb.y), rgb.z);
        if (m <= 0.f) return 0.f;
        float scale = 2.f * m;
        GVec3 normalized{ rgb.x / scale, rgb.y / scale, rgb.z / scale };
        return fmaxf(scale * gpu_jhEvalSpectrum(normalized, lambda)
                           * gpu_sampleD65(lambda), 0.f);
    }
    // ALBEDO: gpu_jhLookupCoeffs already clamps rgb to [0,1].
    return fmaxf(gpu_jhEvalSpectrum(rgb, lambda), 0.f);
}

__device__ inline GSampledSpectrum gpu_rgbToSampledSpectrum(
    const GVec3& rgb, const GSampledWavelengths& wl, GSpectralMode mode)
{
    GSampledSpectrum s;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
        s[i] = gpu_rgbSpectrumAt(rgb, wl.lambda[i], mode);
    return s;
}

// ---------------------------------------------------------------------------
// Camera ray generation (with DOF)
// ---------------------------------------------------------------------------
template <typename TRng>
__device__ inline GRay gpu_generateCameraRay(
    const GCameraParams& cam, int px, int py, TRng* rng)
{
    float u = (px + gpu_rng_uniform(rng)) / (cam.width  - 1);
    float v = 1.f - (py + gpu_rng_uniform(rng)) / (cam.height - 1);

    GVec3 rd     = gpu_randomInUnitDisk(rng) * cam.lensRadius;
    GVec3 offset = cam.u * rd.x + cam.v * rd.y;
    GVec3 dir    = cam.lowerLeft + cam.horizontal*u + cam.vertical*v
                   - cam.origin - offset;
    return GRay(cam.origin + offset, dir);
}

// ===========================================================================
// ===  Lambertian  ===========================================================
// ===========================================================================

__device__ inline GVec3 gpu_lambertian_eval(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    float NdotL = rec.normal.dot(wi);
    if (NdotL <= 0.f) return GVec3(0.f);
    // pkg108 BUG-16 (closure path): Disney materials lower their diffuse lobe
    // to GCLOSURE_DIFFUSE which shades here, so subsurface_weight was a silent
    // no-op on the CUDA backend. Apply the Burley 2012 "Physically-Based
    // Shading at Disney" §5.3 Hanrahan-Krueger mix, mirroring the CPU fix in
    // plugins/materials/disney.cpp::eval (PR #375). Gated on subsurface > 0:
    // plain Lambertian renders stay bit-identical.
    if (mat.subsurface > 0.f) {
        float NdotV = rec.normal.dot(wo);
        if (NdotV > 0.f) {
            GVec3 H = (wi + wo).normalized();
            float LdotH = wi.dot(H);
            float FL = powf(1.f - NdotL, 5.f);
            float FV = powf(1.f - NdotV, 5.f);
            float Fd90 = 0.5f + 2.f * LdotH*LdotH * mat.roughness;
            float Fd = (1.f + (Fd90-1.f)*FL) * (1.f + (Fd90-1.f)*FV);
            float Fss90 = LdotH*LdotH * mat.roughness;
            float Fss = (1.f + (Fss90-1.f)*FL) * (1.f + (Fss90-1.f)*FV);
            float ss = 1.25f * (Fss * (1.f / fmaxf(NdotL + NdotV, 1e-4f) - 0.5f) + 0.5f);
            float FdMixed = (1.f - mat.subsurface) * Fd + mat.subsurface * ss;
            return mat.baseColor * (1.f / M_PI_F) * FdMixed * NdotL;
        }
    }
    return mat.baseColor * (1.f / M_PI_F) * NdotL;
}

// pkg168 Step 2: build the diffuse lobe's spectrum by upsampling the reflectance
// COLOUR per-lambda, then applying the wavelength-flat geometric factor
// (cos/pi, plus the Hanrahan-Krueger subsurface mix) as a scalar — mirroring CPU
// Lambertian::evalSpectral (albedoSpec.sample(lambdas) * cos/pi, raytracer.h).
// Upsampling the pre-scaled RGB eval instead (gpu_rgbToSampledSpectrum of
// baseColor*cos/pi) is WRONG: Jakob-Hanika upsampling is nonlinear in magnitude,
// upsample(k*c) != k*upsample(c), so the pre-scaled form yields a different
// spectrum SHAPE. Both integrate to the same XYZ, but the shape mismatch bites
// once the throughput is MULTIPLIED by the next factor (albedo/illuminant) and
// integrated — a chroma-dependent, per-bounce-compounding divergence
// (pkg156's [1.014,1.007,1.014] bounce-2-onset residual). Same bug class the
// pkg163 metal fix addressed for the conductor lobe.
// gpu_lambertian_eval returns baseColor (x) scalar with the scalar identical
// across channels, so recover it from the largest baseColor channel.
__device__ inline GSampledSpectrum gpu_lambertian_eval_spectral(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi,
    const GSampledWavelengths& wl)
{
    float NdotL = rec.normal.dot(wi);
    if (NdotL <= 0.f) return GSampledSpectrum(0.f);
    GVec3 e = gpu_lambertian_eval(mat, rec, wo, wi);  // baseColor (x) scalar
    float bx = mat.baseColor.x, by = mat.baseColor.y, bz = mat.baseColor.z;
    float scalar;
    if (bx >= by && bx >= bz)      scalar = (bx > 1e-8f) ? e.x / bx : 0.f;
    else if (by >= bz)             scalar = (by > 1e-8f) ? e.y / by : 0.f;
    else                           scalar = (bz > 1e-8f) ? e.z / bz : 0.f;
    return gpu_rgbToSampledSpectrum(mat.baseColor, wl, mat.spectralMode) * scalar;
}

template <typename TRng>
__device__ inline GBSDFSample gpu_lambertian_sample(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& /*wo*/, TRng* rng)
{
    GBSDFSample s;
    GVec3 localWi = gpu_randomCosineDir(rng);
    s.wi = rec.tangent   * localWi.x
         + rec.bitangent * localWi.y
         + rec.normal    * localWi.z;
    float NdotL = rec.normal.dot(s.wi);
    s.f       = mat.baseColor * (1.f / M_PI_F) * NdotL;
    s.pdf     = NdotL / M_PI_F;
    s.isDelta = false;
    return s;
}

__device__ inline float gpu_lambertian_pdf(
    const GMaterial& /*mat*/, const GHitRecord& rec, const GVec3& /*wo*/, const GVec3& wi)
{
    float c = rec.normal.dot(wi);
    return c > 0.f ? c / M_PI_F : 0.f;
}

// ===========================================================================
// ===  Metal (GGX microfacet)  ===============================================
// ===========================================================================

__device__ inline GVec3 gpu_fresnelSchlick3(float cosTheta, const GVec3& F0) {
    float c = fminf(fmaxf(cosTheta, 0.f), 1.f);
    float t = powf(1.f - c, 5.f);
    return F0 + (GVec3(1.f) - F0) * t;
}

__device__ inline GVec3 gpu_metal_eval(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    // roughness <= 0.1: near-delta path — eval approximates a narrow lobe
    if (mat.roughness <= 0.1f) {
        GVec3 perfectRefl = rec.normal * (2.f * wo.dot(rec.normal)) - wo;
        float dev = (wi - perfectRefl).length();
        return (dev < 0.1f) ? mat.baseColor * expf(-dev * 100.f) : GVec3(0.f);
    }

    float NdotL = rec.normal.dot(wi);
    float NdotV = rec.normal.dot(wo);
    if (NdotL <= 0.f || NdotV <= 0.f) return GVec3(0.f);

    GVec3 h    = (wo + wi).normalized();
    float NdotH = fmaxf(rec.normal.dot(h), 0.001f);
    float a     = mat.roughness * mat.roughness;
    float a2    = a * a;
    float denom = NdotH * NdotH * (a2 - 1.f) + 1.f;
    float D     = a2 / (M_PI_F * denom * denom + 0.001f);
    GVec3 F    = gpu_fresnelSchlick3(wo.dot(h), mat.baseColor);
    float k    = (mat.roughness + 1.f) * (mat.roughness + 1.f) / 8.f;
    float G    = (NdotL / (NdotL*(1.f-k)+k)) * (NdotV / (NdotV*(1.f-k)+k));
    // eval() returns brdf * NdotL (cosine-weighted), as on the CPU.
    GVec3 singleScatter = F * D * G / (4.f * NdotV + 0.001f);

    // pkg160: GGX multiple-scattering energy compensation, net factor
    // "1 + Fms*(1-E)/E" (Kulla & Conty 2017 Eq. 6-9; Cycles
    // bsdf_microfacet.h:389-436 microfacet_ggx_preserve_energy, BSD-3-Clause).
    // Mirrors CPU MetalPlugin::ggxCompensationFactor (plugins/materials/
    // metal.cpp) term for term, off the SAME table: g_ggxE/g_ggxEavg are
    // uploaded from DisneyEnergyCompensationTables::ggxEData()/ggxEavgData()
    // (src/gpu/gpu_ggx_tables.cu), which is the array the CPU reads directly.
    //
    // `Fss` = mat.baseColor: for a conductor the Schlick F0 IS the reflectance
    // colour (the gpu_fresnelSchlick3 call above passes it as F0), matching
    // how gpu_disney_eval passes its own F0 at :928. Multiplicative, so the
    // NdotL already folded into singleScatter's Cook-Torrance denominator
    // carries through untouched, and the null-table fallback is the 1.0
    // identity gpu_ggxCompensationFactor already returns.
    //
    // Before pkg160 this function returned singleScatter alone while the CPU
    // added a (differently-tabulated, cosine-free, hand-weighted) term:
    // measured GPU/CPU per-channel mean ratio 0.279/0.286/0.316, median 0.141
    // on the disney_contact_sheet plain-metal patch. pkg160 fixed the CPU
    // rather than mirroring its term; both sides now read the shipped Cycles
    // table. Gate: tests/test_pkg160_plain_metal_gpu_cpu_parity.py.
    return singleScatter *
           gpu_ggxCompensationFactor(mat.baseColor, mat.roughness, NdotV);
}

// pkg163: native per-wavelength metal BSDF, the device mirror of CPU
// MetalPlugin::evalSpectral (plugins/materials/metal.cpp:106-146). Its purpose
// is CPU<->GPU colour-space parity: gpu_metal_eval builds f in RGB and the
// spectral wrappers upsample the sum ONCE through the Jakob-Hanika LUT (Jakob &
// Hanika 2019, "A Low-Dimensional Function Space for Efficient Spectral
// Upsampling"), whereas the CPU is natively per-lambda. The JH upsample is
// nonlinear and not scalar-homogeneous (JH(a+b) != JH(a)+JH(b),
// JH(c*a) != c*JH(a)), so the two constructions agree only for a flat albedo;
// for a chromatic albedo they diverge, worst at high roughness + grazing angle
// (measured B=1.0722 at r=0.9, the pkg160 gate exception this package retires).
//
// Mirrors the WHOLE evalSpectral construction (spec §"The seam" binding
// consequence 1: no term-level patch): per-lambda F0 from the same albedo
// upsampler, per-lambda Schlick Fresnel, and the multiplicative Kulla & Conty
// 2017 (Eq. 6-9) / Cycles microfacet_ggx_preserve_energy (bsdf_microfacet.h,
// BSD-3-Clause) compensation via gpu_ggxDarkeningChannel, all off the same
// achromatic scalar E/Eavg tables gpu_metal_eval reads. Sampling/pdf logic is
// unchanged; only the f-spectral construction moves per-lambda.
__device__ inline GSampledSpectrum gpu_metal_eval_spectral(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi,
    const GSampledWavelengths& wl)
{
    // Near-delta path mirrors MetalPlugin::evalSpectral lines 109-114:
    // albedo spectrum * exp(-deviation) narrow lobe.
    if (mat.roughness <= 0.1f) {
        GVec3 perfectRefl = rec.normal * (2.f * wo.dot(rec.normal)) - wo;
        float dev = (wi - perfectRefl).length();
        float factor = (dev < 0.1f) ? expf(-dev * 100.f) : 0.f;
        return gpu_rgbToSampledSpectrum(mat.baseColor, wl, mat.spectralMode) * factor;
    }

    float NdotL = rec.normal.dot(wi);
    float NdotV = rec.normal.dot(wo);
    if (NdotL <= 0.f || NdotV <= 0.f) return GSampledSpectrum(0.f);

    GVec3 h    = (wo + wi).normalized();
    float NdotH = fmaxf(rec.normal.dot(h), 0.001f);
    float a     = mat.roughness * mat.roughness;
    float a2    = a * a;
    float denom = NdotH * NdotH * (a2 - 1.f) + 1.f;
    float D     = a2 / (M_PI_F * denom * denom + 0.001f);
    // Per-wavelength F0 = albedo spectrum, upsampled the same way the CPU's
    // albedo_spec_.sample(lambdas) does (RGBAlbedoSpectrum -> JH), then per-
    // lambda Schlick Fresnel.
    GSampledSpectrum F0 = gpu_rgbToSampledSpectrum(mat.baseColor, wl, mat.spectralMode);
    float fresnelPow5 = powf(1.f - fminf(fmaxf(h.dot(wo), 0.f), 1.f), 5.f);
    GSampledSpectrum F = F0 + (GSampledSpectrum(1.f) - F0) * fresnelPow5;
    float k = (mat.roughness + 1.f) * (mat.roughness + 1.f) / 8.f;
    float G = (NdotL / (NdotL * (1.f - k) + k)) * (NdotV / (NdotV * (1.f - k) + k));
    GSampledSpectrum singleScatter = F * (D * G / (4.f * NdotV + 0.001f));

    // Multiplicative Kulla & Conty compensation, per wavelength: Fss is the
    // conductor's reflectance F0 (= albedo spectrum at these lambdas), E/Eavg
    // are achromatic geometry and stay scalar. Null-table fallback is the 1.0
    // identity (single-scatter lobe), matching gpu_ggxCompensationFactor.
    if (!g_ggxE || !g_ggxEavg) return singleScatter;
    float E = fmaxf(gpu_ggxE(mat.roughness, NdotV), 1e-4f);
    float Eavg = fminf(fmaxf(gpu_ggxEavg(mat.roughness), 0.f), 0.999f);
    GSampledSpectrum result = singleScatter;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
        result[i] *= gpu_ggxDarkeningChannel(F0[i], E, Eavg);
    return result;
}

template <typename TRng>
__device__ inline GBSDFSample gpu_metal_sample(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, TRng* rng)
{
    GBSDFSample s;
    if (mat.roughness <= 0.1f) {
        // Perfect mirror: wi = 2*(wo·n)*n - wo
        s.wi      = rec.normal * (2.f * wo.dot(rec.normal)) - wo;
        s.f       = mat.baseColor;
        s.pdf     = 1.f;
        s.isDelta = true;
        rec.isDelta = true;
        return s;
    }

    float a   = mat.roughness * mat.roughness;
    float r1  = gpu_rng_uniform(rng);
    float r2  = gpu_rng_uniform(rng);
    float phi = 2.f * M_PI_F * r1;
    float cosTheta = sqrtf((1.f - r2) / (1.f + (a*a - 1.f)*r2));
    float sinTheta = sqrtf(1.f - cosTheta*cosTheta);
    GVec3 h(cosf(phi)*sinTheta, sinf(phi)*sinTheta, cosTheta);
    h = rec.tangent * h.x + rec.bitangent * h.y + rec.normal * h.z;
    s.wi = (h * (2.f * wo.dot(h)) - wo).normalized();
    s.f   = GVec3(0.f);
    s.pdf = 0.f;
    if (s.wi.dot(rec.normal) > 0.f) {
        s.f = gpu_metal_eval(mat, rec, wo, s.wi);
        float NdotH = fmaxf(rec.normal.dot(h), 0.001f);
        float HdotV = fmaxf(h.dot(wo), 0.001f);
        float a2    = a*a;
        float d     = NdotH*NdotH*(a2-1.f)+1.f;
        float D     = a2 / (M_PI_F * d*d + 0.001f);
        s.pdf = D * NdotH / (4.f * HdotV);
    }
    s.isDelta = false;
    return s;
}

__device__ inline float gpu_metal_pdf(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    if (mat.roughness <= 0.1f) return 0.f;
    GVec3 h    = (wo + wi).normalized();
    float NdotH = fmaxf(rec.normal.dot(h), 0.001f);
    float HdotV = fmaxf(h.dot(wo), 0.001f);
    float a     = mat.roughness * mat.roughness;
    float a2    = a*a;
    float d     = NdotH*NdotH*(a2-1.f)+1.f;
    float D     = a2 / (M_PI_F * d*d + 0.001f);
    return D * NdotH / (4.f * HdotV);
}

// ===========================================================================
// ===  Dielectric  ===========================================================
// ===========================================================================

__device__ inline float gpu_fresnelDielectric(float cosThetaI, float etaI, float etaT) {
    cosThetaI = fminf(fmaxf(cosThetaI, -1.f), 1.f);
    bool entering = cosThetaI > 0.f;
    if (!entering) {
        float tmp = etaI; etaI = etaT; etaT = tmp;
        cosThetaI = fabsf(cosThetaI);
    }
    float sinThetaI = sqrtf(fmaxf(0.f, 1.f - cosThetaI*cosThetaI));
    float sinThetaT = etaI / etaT * sinThetaI;
    if (sinThetaT >= 1.f) return 1.f;
    float cosThetaT = sqrtf(fmaxf(0.f, 1.f - sinThetaT*sinThetaT));
    float Rparl = ((etaT*cosThetaI) - (etaI*cosThetaT)) / ((etaT*cosThetaI) + (etaI*cosThetaT));
    float Rperp = ((etaI*cosThetaI) - (etaT*cosThetaT)) / ((etaI*cosThetaI) + (etaT*cosThetaT));
    return (Rparl*Rparl + Rperp*Rperp) * 0.5f;
}

template <typename TRng>
__device__ inline GBSDFSample gpu_dielectric_sample(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, TRng* rng)
{
    GBSDFSample s;
    s.isDelta = true;
    rec.isDelta = true;

    // Enter/exit from rec.frontFace, not sign(wo·rec.normal): rec.normal is the
    // front-facing normal (gpu_bvh.h sets rec.normal = frontFace?out:-out), so the
    // sign test always read "entering" -> eta = 1/ior at BOTH surfaces -> the eta^2
    // radiance factor never cancelled across the glass -> too dark. Mirrors the CPU
    // DielectricPlugin fix.
    float cosTheta = wo.dot(rec.normal);
    float etaI = rec.frontFace ? 1.f : mat.ior;
    float etaT = rec.frontFace ? mat.ior : 1.f;
    GVec3 n = rec.normal;
    if (cosTheta < 0.f) { cosTheta = -cosTheta; n = -n; }

    float eta      = etaI / etaT;
    float sinTheta = sqrtf(fmaxf(0.f, 1.f - cosTheta*cosTheta));
    bool  tir      = eta * sinTheta > 1.f;

    float fresnel = gpu_fresnelDielectric(cosTheta, etaI, etaT);

    if (tir || gpu_rng_uniform(rng) < fresnel) {
        // Reflect: wi = 2*(wo·n)*n - wo
        s.wi  = n * (2.f * wo.dot(n)) - wo;
        s.f   = GVec3(1.f);
        s.pdf = 1.f;
    } else {
        GVec3 wt_perp   = (wo - n*cosTheta) * (-eta);
        GVec3 wt_para   = n * (-sqrtf(fabsf(1.f - wt_perp.length2())));
        s.wi  = (wt_perp + wt_para).normalized();
        // pkg108 BUG-14 (GPU half): refraction carries the glass tint.
        // Mirrors CPU DielectricPlugin::sample (dielectric.cpp: s.f =
        // tint_ * eta^2) and the GPU disney delta branch. baseColor is the
        // closure color when this material was lowered from a closure graph,
        // so tinted glass was rendering clear on the CUDA backend only.
        s.f   = mat.baseColor * (eta * eta);
        s.pdf = 1.f;
    }
    return s;
}

// pkg64-gpu-sellmeier-upload: wavelength-aware dielectric sampler for dispersive
// materials. Uses hero wavelength (lambdas.lambda[0]) to evaluate Sellmeier IOR.
// Mirrors CPU DielectricPlugin::sampleSpectral() hero-channel path.
//
// pkg64-gpu Session 2: on a dispersive REFRACTION the per-wavelength bend angles
// differ, so the path can only follow the hero's direction — mirror CPU
// dielectric.cpp:181-188 and terminate the secondary wavelengths. This is the
// delta-dispersive collapse of Wilkie 2014 hero-wavelength MIS (CGF 33(4),
// DOI:10.1111/cgf.12419): at a perfectly-specular interface only the hero's pdf
// is nonzero at the sampled direction, so the MIS weights are [1,0,0,...].
// `lambdas` is non-const so this terminate is visible to the downstream toXYZ.
template <typename TRng>
__device__ inline GBSDFSample gpu_dielectric_sample_spectral(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo,
    GSampledWavelengths& lambdas, TRng* rng)
{
    GBSDFSample s;
    s.isDelta = true;
    rec.isDelta = true;

    // Hero-wavelength IOR: evaluate Sellmeier at lambda[0] if dispersive
    float ior = mat.isDispersive
        ? gpu_sellmeier_ior(mat.dispersion, lambdas.lambda[0])
        : mat.ior;

    // Enter/exit from rec.frontFace (see gpu_dielectric_sample above) — the wo·n
    // sign test always read "entering" because rec.normal is front-facing.
    float cosTheta = wo.dot(rec.normal);
    float etaI = rec.frontFace ? 1.f : ior;
    float etaT = rec.frontFace ? ior : 1.f;
    GVec3 n = rec.normal;
    if (cosTheta < 0.f) { cosTheta = -cosTheta; n = -n; }

    float eta      = etaI / etaT;
    float sinTheta = sqrtf(fmaxf(0.f, 1.f - cosTheta*cosTheta));
    bool  tir      = eta * sinTheta > 1.f;

    float fresnel = gpu_fresnelDielectric(cosTheta, etaI, etaT);

    if (tir || gpu_rng_uniform(rng) < fresnel) {
        // Reflect: wi = 2*(wo·n)*n - wo
        s.wi  = n * (2.f * wo.dot(n)) - wo;
        s.f   = GVec3(1.f);
        s.pdf = 1.f;
    } else {
        GVec3 wt_perp   = (wo - n*cosTheta) * (-eta);
        GVec3 wt_para   = n * (-sqrtf(fabsf(1.f - wt_perp.length2())));
        s.wi  = (wt_perp + wt_para).normalized();
        // pkg108 BUG-14 (GPU half): tinted refraction — see gpu_dielectric_sample.
        s.f   = mat.baseColor * (eta * eta);
        s.pdf = 1.f;
        // Dispersive refraction: only the hero wavelength follows this bend.
        // Mirror CPU dielectric.cpp:188 — terminate the secondary wavelengths.
        if (mat.isDispersive) lambdas.terminateSecondary();
    }
    return s;
}

// ===========================================================================
// ===  Thin glass / architectural glazing  ===================================
// ===========================================================================

template <typename TRng>
__device__ inline GVec3 gpu_sampleCone(const GVec3& dir, float roughness, TRng* rng) {
    GVec3 w = dir.normalized();
    if (roughness <= 0.001f) return w;

    GVec3 a = fabsf(w.x) > 0.9f ? GVec3(0.f, 1.f, 0.f) : GVec3(1.f, 0.f, 0.f);
    GVec3 u = (a - w * a.dot(w)).normalized();
    GVec3 v = w.cross(u);
    float maxAngle = fminf(fmaxf(roughness, 0.f), 1.f) * 0.35f;
    float cosMax = cosf(maxAngle);
    float cosTheta = 1.f - gpu_rng_uniform(rng) * (1.f - cosMax);
    float sinTheta = sqrtf(fmaxf(0.f, 1.f - cosTheta * cosTheta));
    float phi = 2.f * M_PI_F * gpu_rng_uniform(rng);
    return (u * (cosf(phi) * sinTheta) +
            v * (sinf(phi) * sinTheta) +
            w * cosTheta).normalized();
}

template <typename TRng>
__device__ inline GBSDFSample gpu_thin_glass_sample(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, TRng* rng)
{
    GBSDFSample s;
    s.isDelta = mat.roughness < 0.02f;
    rec.isDelta = s.isDelta;

    float cosTheta = fabsf(wo.normalized().dot(rec.normal));
    float F = gpu_fresnelDielectric(cosTheta, 1.f, mat.ior);
    float reflectProb = fminf(fmaxf(F, 0.f), 1.f);
    float transmitProb = fmaxf(0.f, (1.f - reflectProb) * fminf(fmaxf(mat.transmission, 0.f), 1.f));
    float totalProb = reflectProb + transmitProb;
    if (totalProb <= 1e-5f) {
        s.wi = gpu_sampleCone(rec.normal * (2.f * wo.dot(rec.normal)) - wo, mat.roughness, rng);
        s.f = GVec3(0.f);
        s.pdf = 1.f;
        return s;
    }

    reflectProb /= totalProb;
    transmitProb /= totalProb;
    if (gpu_rng_uniform(rng) < reflectProb) {
        s.wi = gpu_sampleCone(rec.normal * (2.f * wo.dot(rec.normal)) - wo, mat.roughness, rng);
        s.f = GVec3(reflectProb);
        s.pdf = fmaxf(reflectProb, 1e-4f);
    } else {
        s.wi = gpu_sampleCone(-wo, mat.roughness, rng);
        s.f = mat.baseColor * transmitProb;
        s.pdf = fmaxf(transmitProb, 1e-4f);
    }
    return s;
}

// ===========================================================================
// ===  Disney BRDF  ==========================================================
// ===========================================================================

// GGX/Trowbridge-Reitz NDF (Walter 2007 Eq. 33, pbrt-v4 §9.6).
// D(wm) = α² / (π (1 + (α²-1)·cos²θm)²)
__device__ inline float gpu_D_GTR2(float NdotH, float a) {
    float a2 = a*a;
    float t  = 1.f + (a2 - 1.f) * NdotH*NdotH;
    return a2 / (M_PI_F * t*t);
}

__device__ inline float gpu_smithG_GGX(float NdotV, float alphaG) {
    float a = alphaG*alphaG;
    float b = NdotV*NdotV;
    return 1.f / (NdotV + sqrtf(a + b - a*b) + 0.001f);
}

// True Smith G1 in [0,1] (Walter 2007 Eq. 34) = 2*NdotV*gpu_smithG_GGX. gpu_smithG_GGX
// is the combined visibility form G1/(2*NdotV); the rough-transmission estimator needs
// the true G1 or a spurious 1/(4*cosO*cosI) survives -> ~70% energy loss (CPU mirror).
__device__ inline float gpu_smithG1_GGX(float NdotV, float alphaG) {
    float a = alphaG*alphaG;
    float b = NdotV*NdotV;
    return 2.f * NdotV / (NdotV + sqrtf(a + b - a*b) + 0.001f);
}

__device__ inline GVec3 gpu_disney_fresnelSchlick(float cosTheta, const GVec3& F0, float scale = 0.8f) {
    float c = fminf(fmaxf(1.f - cosTheta, 0.f), 1.f);
    // Reduced Fresnel for dielectric Disney lobes; metallic lobes approach full conductor Schlick.
    float t5 = c*c*c*c*c;
    return F0 + (GVec3(1.f) - F0) * t5 * scale;
}

__device__ inline float gpu_disney_fresnelDielectric(float cosThetaI, float etaI, float etaT) {
    cosThetaI = fminf(fmaxf(cosThetaI, -1.f), 1.f);
    bool entering = cosThetaI > 0.f;
    if (!entering) {
        float tmp = etaI; etaI = etaT; etaT = tmp;
        cosThetaI = fabsf(cosThetaI);
    }
    float sinThetaI = sqrtf(fmaxf(0.f, 1.f - cosThetaI*cosThetaI));
    float sinThetaT = etaI / etaT * sinThetaI;
    if (sinThetaT >= 1.f) return 1.f;
    float cosThetaT = sqrtf(fmaxf(0.f, 1.f - sinThetaT*sinThetaT));
    float rPar = ((etaT*cosThetaI) - (etaI*cosThetaT)) /
                 ((etaT*cosThetaI) + (etaI*cosThetaT) + 1e-6f);
    float rPerp = ((etaI*cosThetaI) - (etaT*cosThetaT)) /
                  ((etaI*cosThetaI) + (etaT*cosThetaT) + 1e-6f);
    return fminf(fmaxf(0.5f * (rPar*rPar + rPerp*rPerp), 0.f), 1.f);
}

// Heitz 2018 "Sampling the GGX Distribution of Visible Normals", JCGT 7(4).
// Ported from PBRT-v4 TrowbridgeReitzDistribution::Sample_wm (BSD-3-Clause).
template <typename TRng>
__device__ inline GVec3 gpu_disney_sampleGgxVNDF(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, TRng* rng)
{
    float a = fmaxf(mat.roughness*mat.roughness, 0.0064f);
    float u1 = gpu_rng_uniform(rng), u2 = gpu_rng_uniform(rng);

    // Transform wo to local tangent space
    GVec3 wo_local(wo.dot(rec.tangent), wo.dot(rec.bitangent), wo.dot(rec.normal));
    // Transform to hemispherical configuration
    GVec3 wh = GVec3(a*wo_local.x, a*wo_local.y, wo_local.z).normalized();
    if (wh.z < 0.f) wh = -wh;

    // Orthonormal basis for visible normal sampling
    GVec3 T1 = (wh.z < 0.99999f) ? GVec3(0.f, 0.f, 1.f).cross(wh).normalized() : GVec3(1.f, 0.f, 0.f);
    GVec3 T2 = wh.cross(T1);

    // Sample uniform disk (polar)
    float r = sqrtf(u1);
    float phi = 2.f * M_PI_F * u2;
    float px = r * cosf(phi);
    float py = r * sinf(phi);

    // Warp hemispherical projection for visible normal sampling
    // pkg149: mirrors the CPU fix in plugins/materials/disney.cpp
    // sampleGgxVNDF -- pbrt-v4's `p.y = Lerp((1+wh.z)/2, h, p.y)` (Lerp(t,a,b)
    // = (1-t)*a + t*b) had `h` and `py` swapped here, biasing the sampled
    // half-vector azimuth to the side opposite wo and causing the measured
    // ~16-18 deg transmission sample/pdf peak offset (glass[0.3-45]).
    float h = sqrtf(fmaxf(0.f, 1.f - px*px));
    float t = (1.f + wh.z) / 2.f;
    py = (1.f - t) * h + t * py;

    // Reproject to hemisphere and transform normal to ellipsoid configuration
    float pz = sqrtf(fmaxf(0.f, 1.f - px*px - py*py));
    GVec3 nh = T1*px + T2*py + wh*pz;
    GVec3 m_local = GVec3(a*nh.x, a*nh.y, fmaxf(1e-6f, nh.z)).normalized();

    // Transform back to world space
    GVec3 m = rec.tangent*m_local.x + rec.bitangent*m_local.y + rec.normal*m_local.z;
    return m.normalized();
}

__device__ inline bool gpu_disney_refractMicro(
    const GVec3& wo, const GVec3& m, float eta, GVec3& wi)
{
    float cosTheta = fminf(fmaxf(wo.dot(m), -1.f), 1.f);
    if (cosTheta <= 0.f) return false;
    GVec3 wtPerp = (wo - m*cosTheta) * (-eta);
    float parallel2 = 1.f - wtPerp.length2();
    if (parallel2 <= 0.f) return false;
    GVec3 wtParallel = m * (-sqrtf(parallel2));
    wi = (wtPerp + wtParallel).normalized();
    return wi.length2() > 1e-10f;
}

// Forward decl — defined below (used by gpu_disney_microfacetReflectionPdf).
__device__ inline float gpu_disney_vndfPdf(
    const GMaterial& mat, const GVec3& rec_normal, const GVec3& wo, const GVec3& wm);

// VNDF reflection PDF (PBRT-v4 DielectricBxDF::PDF reflection branch).
__device__ inline float gpu_disney_microfacetReflectionPdf(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    if (rec.normal.dot(wo) * rec.normal.dot(wi) <= 0.f) return 0.f;
    GVec3 wm = (wo + wi).normalized();
    if (wm.length2() <= 1e-10f) return 0.f;
    if (wm.dot(rec.normal) < 0.f) wm = -wm;

    float HdotO = fabsf(wo.dot(wm));
    if (HdotO <= 1e-10f) return 0.f;

    // PBRT-v4: reflection PDF = VNDF_PDF / (4 * |HdotO|)
    // (pbrt-v4 DielectricBxDF, Walter 2007 §5.3 Jacobian).
    return gpu_disney_vndfPdf(mat, rec.normal, wo, wm) / (4.f * HdotO);
}

// pkg138: rough dielectric reflection BRDF (PBRT-v4 DielectricBxDF::f
// reflection branch, BSD-3-Clause; Walter et al. 2007 EGSR "Microfacet
// Models for Refraction through Rough Surfaces" §5.1 Eq. 20). CPU twin:
// plugins/materials/disney.cpp::roughReflectionEval -- see that comment for
// the full rationale (Cspec0-collapsed reflection lobe vs pdf()'s continuous
// VNDF term, chi²=143M at glass[0.3-45]). This closure is reached via the
// GCLOSURE_DIELECTRIC_TRANSMISSION -> GMAT_DISNEY lowering in
// gpu_closure_as_material (roughness > 0.03f), so the GPU has its own copy
// of the same bug and needs its own copy of the fix.
//
// HW-verifier finding on PR #522 (2026-07-25): the Fresnel here was hardcoded
// to the air-entering convention (etaI=1, etaT=mat.ior) regardless of
// rec.frontFace, misweighting TRUE INTERNAL reflection events at a solid
// sphere's second (interior) surface. Physically: for an internal-reflection
// event, `HdotO = wo.dot(wm)` is always >0 here (the early-return above
// already guarantees it) and rec.normal is always the front-facing
// (ray-oriented) normal -- so gpu_disney_fresnelDielectric's own sign-based
// entering/exiting auto-swap NEVER fires, and the passed-in etaI=1/etaT=ior
// is used as-is even for an internal event. That is backwards: for light
// already inside the glass hitting the interior surface, Snell's law must be
// evaluated as etaI=ior (the medium the ray is currently in), etaT=1 (the
// medium beyond) -- with the WRONG (entering) convention,
// `sinThetaT = sinThetaI/ior` NEVER exceeds 1, so total internal reflection
// (F=1) can never trigger for this formula, no matter how far past the
// critical angle. Low roughness concentrates internal-reflection probability
// mass beyond the critical angle (a smooth surface's reflected lobe is
// narrow/peaked there), so under-computing F there disproportionately
// darkens LOW-roughness internal reflections -- matching the measured GPU
// furnace shape (worst at R=0.1, improving toward R=1.0). Same bug class as
// pkg154's frontFace fix for roughTransmissionEval/Pdf (entering must come
// from rec.frontFace, not a cosine/dot-product sign that this front-facing
// normal convention forces to be one-sided always); this is the reflection
// lobe's own copy, never previously fixed on either CPU or GPU.
//
// GPU-ONLY fix (do not port to CPU roughReflectionEval without independent
// sign-off, per the HW-verifier's re-gate process, memory
// hw-verify-branch-freeze / pkg98 adjudication discipline) -- CPU's
// disney.cpp::roughReflectionEval keeps its identical hardcoded convention
// unchanged; CPU's furnace test passes at 0.997-0.999 with it in place, so
// whether the same fix is warranted there is an open question for a
// follow-up investigation, not assumed here.
__device__ inline GVec3 gpu_disney_roughReflectionEval(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    float cosO = rec.normal.dot(wo);
    float cosI = rec.normal.dot(wi);
    if (cosO <= 0.f || cosI <= 0.f) return GVec3(0.f);

    GVec3 wm = (wo + wi).normalized();
    if (wm.length2() <= 1e-10f) return GVec3(0.f);
    if (wm.dot(rec.normal) < 0.f) wm = -wm;

    float HdotO = wo.dot(wm);
    if (HdotO <= 1e-10f) return GVec3(0.f);

    float a = fmaxf(mat.roughness*mat.roughness, 0.0064f);
    float NdotH = wm.dot(rec.normal);
    float D = gpu_D_GTR2(NdotH, a);
    float G = gpu_smithG1_GGX(cosO, a) * gpu_smithG1_GGX(cosI, a);
    float etaI = rec.frontFace ? 1.f : mat.ior;
    float etaT = rec.frontFace ? mat.ior : 1.f;
    float F = gpu_disney_fresnelDielectric(HdotO, etaI, etaT);

    float fr = D * G * F / (4.f * cosO * cosI + 1e-8f);

    // pkg167: reflection-lobe multi-scatter compensation, exact twin of CPU
    // disney.cpp::roughReflectionEval (see the citation/composition comment
    // there: Turquin 2019 IOR-dependent term; Cycles combined-glass-closure
    // compensation split across the reflection + transmission eval branches;
    // etap = ior on entry / 1/ior on exit; throughput magnitude only). This is
    // the same gpu_ggxGlassCompensationFactor the transmission twin applies at
    // gpu_disney_roughTransmissionEval; mirrors it byte-for-byte so CPU/GPU
    // rough-dielectric furnace + parity stay in band.
    float etap = rec.frontFace ? mat.ior : (1.f / mat.ior);
    fr *= gpu_ggxGlassCompensationFactor(mat.roughness, etap, fabsf(cosO));

    return GVec3(fr);
}

// PBRT-v4 DielectricBxDF::f transmission (BSD-3-Clause).
// Walter 2007 "Microfacet Models for Refraction through Rough Surfaces" Eq. 21.
__device__ inline GVec3 gpu_disney_roughTransmissionEval(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    float cosO = rec.normal.dot(wo);
    float cosI = rec.normal.dot(wi);
    if (cosO == 0.f || cosI == 0.f || cosO*cosI >= 0.f) return GVec3(0.f);

    // pkg154: entering/exiting MUST come from rec.frontFace, not sign(cosO) --
    // rec.normal is the front-facing normal (gpu_bvh.h sets rec.normal =
    // frontFace?out:-out, mirroring the CPU HitRecord::setFaceNormal
    // convention), so cosO = rec.normal.dot(wo) is always >= 0 regardless of
    // enter/exit. Both transmission events computed etap = mat.ior (never
    // 1/mat.ior), so the radiance-compression factor 1/etap^2 never cancelled
    // over a round trip -- (1/ior^2)^2 = 0.1975 at ior=1.5, matching the
    // measured CPU furnace floor. Same fix already applied to the smooth GPU
    // dielectric path (gpu_dielectric_sample) and disney.cpp's CPU twin. See
    // .astroray_plan/docs/pkg154-furnace-deficit-findings.md.
    bool entering = rec.frontFace;
    float etaI = entering ? 1.f : mat.ior;
    float etaT = entering ? mat.ior : 1.f;
    float etap = entering ? mat.ior : (1.f / mat.ior);  // etaT/etaI
    GVec3 wm = (wi*etap + wo).normalized();
    if (wm.length2() <= 1e-10f) return GVec3(0.f);
    // Face forward (PBRT-v4 FaceForward)
    if (wm.dot(rec.normal) < 0.f) wm = -wm;

    // Discard backfacing microfacets
    if (wm.dot(wi)*cosI < 0.f || wm.dot(wo)*cosO < 0.f) return GVec3(0.f);

    float a = fmaxf(mat.roughness*mat.roughness, 0.0064f);
    float D = gpu_D_GTR2(fabsf(wm.dot(rec.normal)), a);
    // PBRT-v4: G(wo, wi) = 1 / (1 + Lambda(wo) + Lambda(wi))
    float G = gpu_smithG1_GGX(fabsf(cosO), a) * gpu_smithG1_GGX(fabsf(cosI), a);
    float F = gpu_disney_fresnelDielectric(fabsf(wo.dot(wm)), etaI, etaT);

    // PBRT-v4 transmission eval: D * (1-F) * G * |HdotI * HdotO / denom|
    float denom = (wi.dot(wm) + wo.dot(wm) / etap);
    denom = denom*denom * cosI * cosO;
    float ft = D * (1.f - F) * G * fabsf(wi.dot(wm) * wo.dot(wm) / (denom + 1e-10f));

    // PBRT-v4: radiance transport correction (Astroray is a radiance path tracer)
    ft /= (etap * etap);

    // pkg169: fold in the incident cosine |N.wi| (CPU twin: disney.cpp
    // roughTransmissionEval). The integrator forms throughput as f/pdf with no
    // separate cosine multiply; the reflection lobes supply it via `* NdotL` in
    // eval(), but this transmission branch never gets one and `ft` is the
    // per-steradian PBRT-v4 BTDF (no cosine). Omitting |cosI| inflated rough
    // transmission by 1/|cosI| (energy gain; gamma clamped it). With it, the
    // weight collapses to the Heitz-2018 VNDF form G1(cosI)/etap^2.
    float scale = (1.f - mat.metallic) * mat.transmission * ft * fabsf(cosI);
    GVec3 result = mat.baseColor * scale;

    // pkg151: rough-transmission multi-scatter compensation (Cycles glass
    // tables via gpu_glass_tables.cuh), CPU twin: disney.cpp
    // ggxGlassCompensationFactor / roughTransmissionEval. Throughput
    // magnitude only — does not touch gpu_disney_roughTransmissionPdf or
    // gpu_disney_sampleGgxVNDF.
    result = result * gpu_ggxGlassCompensationFactor(mat.roughness, etap, fabsf(cosO));

    // pkg154: removed the closure-level clamp(0,4) -- CPU twin: disney.cpp
    // roughTransmissionEval (see the comment there for the measured furnace
    // numbers and the pkg123 metal-reflection precedent this mirrors).
    result.x = fmaxf(result.x, 0.f);
    result.y = fmaxf(result.y, 0.f);
    result.z = fmaxf(result.z, 0.f);
    return result;
}

// VNDF PDF including half-vector Jacobian (PBRT-v4 DielectricBxDF::PDF).
__device__ inline float gpu_disney_vndfPdf(
    const GMaterial& mat, const GVec3& rec_normal, const GVec3& wo, const GVec3& wm)
{
    float absCosO = fabsf(wo.dot(rec_normal));
    if (absCosO <= 1e-10f) return 0.f;
    float HdotO = fabsf(wo.dot(wm));
    float NdotH = fabsf(wm.dot(rec_normal));
    if (HdotO <= 1e-10f || NdotH <= 1e-10f) return 0.f;

    float a = fmaxf(mat.roughness*mat.roughness, 0.0064f);
    float D = gpu_D_GTR2(NdotH, a);
    float G1 = gpu_smithG1_GGX(absCosO, a);
    // PBRT-v4: VNDF PDF = D(wo, wm) = G1(wo) / absCosO * D(wm) * absDot(wo, wm)
    return G1 / absCosO * D * HdotO;
}

__device__ inline float gpu_disney_roughTransmissionPdf(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    float cosO = rec.normal.dot(wo);
    float cosI = rec.normal.dot(wi);
    if (cosO == 0.f || cosI == 0.f || cosO*cosI >= 0.f) return 0.f;

    // pkg154: mirrors gpu_disney_roughTransmissionEval's fix (see comment there).
    bool entering = rec.frontFace;
    float etap = entering ? mat.ior : (1.f / mat.ior);
    GVec3 wm = (wi*etap + wo).normalized();
    if (wm.length2() <= 1e-10f) return 0.f;
    if (wm.dot(rec.normal) < 0.f) wm = -wm;

    float HdotO = wo.dot(wm);
    float HdotI = wi.dot(wm);
    if (HdotO * HdotI >= 0.f) return 0.f;

    // PBRT-v4: dwm_dwi Jacobian
    float denom = (HdotI + HdotO / etap);
    float denom2 = denom*denom;
    if (denom2 <= 1e-10f) return 0.f;
    float dwm_dwi = fabsf(HdotI) / denom2;

    // VNDF PDF * Jacobian * transmission probability
    float etaI = entering ? 1.f : mat.ior;
    float etaT = entering ? mat.ior : 1.f;
    float F = gpu_disney_fresnelDielectric(fabsf(HdotO), etaI, etaT);
    return mat.transmission * (1.f - F) * gpu_disney_vndfPdf(mat, rec.normal, wo, wm) * dwm_dwi;
}

__device__ inline GVec3 gpu_disney_eval(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    GVec3 N = rec.normal;
    float NdotL = N.dot(wi);
    float NdotV = N.dot(wo);
    if (mat.transmission > 0.f && mat.roughness > 0.03f && NdotL*NdotV < 0.f)
        return gpu_disney_roughTransmissionEval(mat, rec, wo, wi);
    if (NdotL <= 0.f || NdotV <= 0.f) return GVec3(0.f);

    GVec3 H    = (wi + wo).normalized();
    float NdotH = N.dot(H);
    float LdotH = wi.dot(H);

    GVec3 Cdlin = mat.baseColor;
    float Cdlum = luminance(Cdlin);
    GVec3 Ctint = Cdlum > 0.f ? Cdlin / Cdlum : GVec3(1.f);
    GVec3 Cspec0 = GVec3(mat.specular * 0.08f)
                   * (GVec3(1.f) * (1.f - mat.specularTint) + Ctint * mat.specularTint);
    GVec3 F0 = Cspec0 * (1.f - mat.metallic) + Cdlin * mat.metallic;
    F0 = gvec3_min(F0, GVec3(1.f));

    // Diffuse
    float FL  = powf(1.f - NdotL, 5.f);
    float FV  = powf(1.f - NdotV, 5.f);
    float Fd90 = 0.5f + 2.f * LdotH*LdotH * mat.roughness;
    float Fd  = (1.f + (Fd90-1.f)*FL) * (1.f + (Fd90-1.f)*FV);
    // pkg108 BUG-16 (GPU half): Burley 2012 "Physically-Based Shading at
    // Disney" §5.3 Hanrahan-Krueger subsurface approximation. Mirrors the
    // CPU fix in plugins/materials/disney.cpp::eval (PR #375); without this
    // mix mat.subsurface was uploaded but never read, so subsurface_weight
    // was a silent no-op on the CUDA backend only.
    float Fss90 = LdotH*LdotH * mat.roughness;
    float Fss = (1.f + (Fss90-1.f)*FL) * (1.f + (Fss90-1.f)*FV);
    float ss = 1.25f * (Fss * (1.f / fmaxf(NdotL + NdotV, 1e-4f) - 0.5f) + 0.5f);
    float FdMixed = (1.f - mat.subsurface) * Fd + mat.subsurface * ss;
    // pkg152: pkg60 grazing-incidence Burley-diffuse furnace normalization --
    // mirrors CPU disney.cpp::diffuseFurnaceScale (see energy_compensation
    // citation trail there: Kulla & Conty 2017 layering measurement, pkg145
    // grid sweep). gpu_disney_eval never applied this; confirmed absent by
    // grep prior to this package (.astroray_plan/packages/
    // pkg152-gpu-disney-metal-residual-dimness.md).
    GVec3 diffuse = (1.f / M_PI_F) * Cdlin * FdMixed * gpu_diffuseFurnaceScale(mat.roughness, NdotV);

    // Specular — min alpha 0.0064 (roughness 0.08) to prevent numerical collapse
    float a  = fmaxf(mat.roughness*mat.roughness, 0.0064f);
    float Ds = gpu_D_GTR2(NdotH, a);
    float schlickScale = 0.8f + 0.2f * mat.metallic;
    GVec3 F  = gpu_disney_fresnelSchlick(LdotH, F0, schlickScale);
    // gpu_smithG_GGX is the COMBINED visibility form G1/(2*NdotV) (see its
    // comment above): Gs = smithG_GGX(NdotL,a)*smithG_GGX(NdotV,a) already
    // equals G/(4*NdotL*NdotV) (Walter 2007 Eq.34 masking-shadowing G folded
    // into the Cook-Torrance 1/(4*cosO*cosI) denominator, matching Kulla &
    // Conty 2017's "Vis" term / Cycles bsdf_microfacet.h). pkg141: an extra
    // `/(4*NdotL*NdotV+0.001f)` divide here double-counted that factor
    // (spec = D*F*G/(4NdotLNdotV)^2 instead of D*F*G/(4NdotLNdotV)),
    // amplifying the specular term by 1/(4*NdotL*NdotV) at any NdotL*NdotV <
    // 0.25 (grazing/off-normal hits) -- part of the mechanism behind the
    // measured 2.7-4.0x GPU/CPU metal over-brightness (pkg123 parity xfails).
    // CPU disney.cpp removed the identical stale divide in pkg60/PR #178
    // ("Correct the Disney specular/clearcoat Smith-G denominator bug found
    // by the furnace grid", commit 1df244f) -- disney.cpp:463 has been
    // `spec = Ds * F * Gs;` (no divide) ever since; this GPU mirror
    // (gpu_materials.h) was never updated to match. Fixed here to restore
    // CPU/GPU term-for-term parity (disney.cpp is Lane A's exclusive file
    // and is not touched by this change).
    float Gs = gpu_smithG_GGX(NdotL, a) * gpu_smithG_GGX(NdotV, a);
    GVec3 spec = Ds * F * Gs;

    // pkg138: blend in the rough dielectric reflection lobe -- mirrors CPU
    // disney.cpp eval() (see the pkg138 comment there for the mixture-
    // probability rationale: sample()'s dielectric branch picks this
    // reflection direction with probability mat.transmission, matching
    // gpu_disney_pdf's mat.transmission*F*gpu_disney_microfacetReflectionPdf
    // term). Gated by the same mat.roughness > 0.03f threshold as
    // gpu_disney_sample's/gpu_disney_pdf's VNDF reflection branch; smooth
    // glass is unaffected.
    if (mat.transmission > 0.f && mat.roughness > 0.03f) {
        float dielectricWeight = (1.f - mat.metallic) * mat.transmission;
        spec = spec * (1.f - dielectricWeight) +
               dielectricWeight * gpu_disney_roughReflectionEval(mat, rec, wo, wi);
    }

    // Sheen (reduced by 0.5)
    GVec3 Csheen = GVec3(1.f)*(1.f-mat.sheenTint) + Ctint*mat.sheenTint;
    GVec3 Fsheen = mat.sheen * Csheen * powf(1.f - LdotH, 5.f) * 0.5f;

    // pkg152: layering stack (Kulla & Conty 2017 Eq. 6-9; Cycles
    // src/kernel/svm/closure.h:208-211 and bsdf_sheen.h:40-51,
    // closure_layering_weight in bsdf_util.h, Apache-2.0). Mirrors CPU
    // disney.cpp::eval() exactly -- gpu_disney_eval previously had NONE of
    // this stack (sheen/clearcoat never attenuated anything below them, the
    // GGX specular layer never attenuated diffuse). See
    // .astroray_plan/packages/pkg152-gpu-disney-metal-residual-dimness.md.
    GVec3 lowerLayerWeight(1.f, 1.f, 1.f);
    if (g_sheenE && mat.sheen > 0.f) {
        float sheenAlbedo = gpu_sheenAlbedo(mat.roughness, NdotV) * mat.sheen;
        Fsheen = Fsheen * sheenAlbedo;
        lowerLayerWeight = gpu_layeringWeightAfter(lowerLayerWeight, Csheen * sheenAlbedo);
    }

    // Clearcoat (reduced by 0.5 -- CPU disney.cpp: `* 0.25f`, no divide).
    // pkg152: this GPU twin previously carried a stale extra
    // `/(4*NdotL*NdotV+0.001f)` divide AND a wrong 0.5 (should be 0.25)
    // constant -- the same double-divide bug class pkg141 already fixed for
    // the `spec` term a few lines above (Gs, the combined-visibility Smith-G
    // form, already folds in the 1/(4*cosO*cosI) factor; Gr uses the
    // identical gpu_smithG_GGX combined form, so no second divide is needed).
    // Harmless in isolation for mat.clearcoat==0 (the pkg123 metal-parity
    // scene's default), found via the pkg152 spec's hypothesis-3 sweep for
    // "any OTHER stale denominator/epsilon" in this newly-reachable
    // function; fixed here to restore CPU/GPU term-for-term parity.
    float Dr  = gpu_D_GTR2(NdotH, mat.clearcoatGloss * mat.clearcoatGloss);
    float Fr  = 0.04f + (1.f - 0.04f) * powf(1.f - LdotH, 5.f);
    float Gr  = gpu_smithG_GGX(NdotL, 0.25f) * gpu_smithG_GGX(NdotV, 0.25f);
    GVec3 ccTerm = GVec3(mat.clearcoat * Dr * Fr * Gr) * 0.25f;
    if (g_clearcoatE && mat.clearcoat > 0.f) {
        float clearE = fmaxf(gpu_clearcoatE(NdotV), 1e-4f);
        ccTerm = ccTerm * fminf(1.f / clearE, 1.25f);
        lowerLayerWeight = gpu_layeringWeightAfter(
            lowerLayerWeight, GVec3(mat.clearcoat * (1.f - clearE)));
    }

    // Kulla & Conty 2017 Eq. 6-9 / Cycles microfacet_ggx_preserve_energy:
    // net "1 + Fms*(1-E)/E" compensation on the GGX specular lobe (metal AND
    // the blended dielectric-reflection lobe above). This is the term the
    // pkg141 adjudication's Lessons flagged as never mirrored to the GPU --
    // its absence predicts exactly the observed GPU-dim (not GPU-bright)
    // residual (a missing >=1 multiplier).
    spec = spec * gpu_ggxCompensationFactor(F0, mat.roughness, NdotV);

    // pkg145: diffuse-under-dielectric-specular layering -- the specular
    // lobe's own directional albedo AT THE VIEW ANGLE attenuates whatever
    // sits below it (diffuse). Fview uses schlickScale like the raw `F`
    // above, matching Cycles' cos_NI convention (not the material's
    // normal-incidence F0).
    GVec3 Fview = gpu_disney_fresnelSchlick(NdotV, F0, schlickScale);
    GVec3 specAlbedo = gpu_ggxDirectionalAlbedo(Fview, mat.roughness, NdotV);
    GVec3 diffuseLayerWeight = gpu_layeringWeightAfter(lowerLayerWeight, specAlbedo);

    GVec3 baseLayer = (1.f-mat.metallic)*(1.f-mat.transmission)*diffuse*diffuseLayerWeight
                     + spec * lowerLayerWeight;
    GVec3 result = (baseLayer
                   + (1.f-mat.metallic)*Fsheen
                   + ccTerm) * NdotL;

    // pkg123: floor at 0 only — NO upper cap (byte-mirrors CPU clampColor,
    // plugins/materials/disney.cpp). A finite cap clips the near-delta GGX
    // specular peak while gpu_disney_pdf carries the uncapped gpu_D_GTR2 (now
    // epsilon-free), so the importance-sampled f/pdf ratio stops cancelling D
    // and metal collapses to black. The previous asymmetric caps (CPU 4.0 vs
    // GPU 10.0) never fired pre-pkg123 because the D_GTR2 `+0.001f` epsilon
    // deflated D to <=~0.32; with the epsilon gone the cap must go too. Firefly
    // control is the integrator's job, mirroring Cycles kernel_accum_clamp
    // (clamp_direct/clamp_indirect), not the closure.
    result.x = fmaxf(result.x, 0.f);
    result.y = fmaxf(result.y, 0.f);
    result.z = fmaxf(result.z, 0.f);
    return result;
}

template <typename TRng>
__device__ inline GBSDFSample gpu_disney_sample(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, TRng* rng)
{
    GBSDFSample s;
    s.f   = GVec3(0.f);
    s.pdf = 0.f;
    s.isDelta = false;

    // Transmission lobe
    if (mat.transmission > 0.f && gpu_rng_uniform(rng) < mat.transmission) {
        float etaI = rec.frontFace ? 1.f : mat.ior;
        float etaT = rec.frontFace ? mat.ior : 1.f;
        float eta  = etaI / etaT;
        GVec3 n   = rec.normal;
        float cosTheta = wo.dot(n);
        if (cosTheta < 0.f) { cosTheta = -cosTheta; n = -n; }

        float sinTheta  = sqrtf(fmaxf(0.f, 1.f - cosTheta*cosTheta));
        bool  cannotRef = eta * sinTheta > 1.f;

        float f0 = (etaI - etaT) / (etaI + etaT);
        f0 = f0*f0;
        float fresnel = f0 + (1.f-f0)*powf(1.f-cosTheta, 5.f);

        if (mat.roughness > 0.03f) {
            // Sample VNDF microfacet normal (Heitz 2018, PBRT-v4)
            GVec3 wm = gpu_disney_sampleGgxVNDF(mat, rec, wo, rng);
            float HdotO = wo.dot(wm);
            float F = gpu_disney_fresnelDielectric(fabsf(HdotO), etaI, etaT);

            // Sample reflection or transmission based on Fresnel
            float R = F, T = 1.f - F;
            bool sampleReflection = cannotRef || gpu_rng_uniform(rng) < R / (R + T);

            if (sampleReflection) {
                // Reflect off microfacet
                s.wi = (wm * (2.f * HdotO) - wo).normalized();
                if (s.wi.dot(rec.normal) * wo.dot(rec.normal) > 0.f) {
                    // Evaluate reflection (specular lobe contribution)
                    s.f = gpu_disney_eval(mat, rec, wo, s.wi);
                    // PDF = VNDF_PDF / (4 * |HdotO|) * R / (R + T)
                    // NOTE: unlike D_GTR2/specular-pdf, this site is outside the
                    // adjudicated pkg123 scope (transmission Fresnel-selection
                    // branch, not the reflection-lobe NDF density) — left matching
                    // CPU disney.cpp:445 (both epsilons retained) for CPU/GPU parity.
                    float vndfPdfVal = gpu_disney_vndfPdf(mat, rec.normal, wo, wm);
                    s.pdf = mat.transmission * vndfPdfVal / (4.f * fabsf(HdotO) + 1e-10f) * R / (R + T + 1e-10f);
                }
            } else {
                // Refract through microfacet
                if (gpu_disney_refractMicro(wo, wm, eta, s.wi)) {
                    s.f = gpu_disney_roughTransmissionEval(mat, rec, wo, s.wi);
                    s.pdf = gpu_disney_roughTransmissionPdf(mat, rec, wo, s.wi);
                }
            }
            if (s.pdf > 0.f && s.f.length2() > 0.f) {
                s.isDelta = false;
                rec.isDelta = false;
                return s;
            }
            // pkg138 investigation note: a PBRT-v4-faithful "return a dead
            // (pdf=0) sample instead of falling through to the smooth delta
            // below" was tried and MEASURED to regress energy conservation
            // severely (white-furnace collapsed to ~0.0). CPU twin: plugins/
            // materials/disney.cpp::sample -- see that comment for the full
            // rationale. Reverted; kept as the pre-existing behavior.
        }

        if (cannotRef || gpu_rng_uniform(rng) < fresnel) {
            s.wi  = n * (2.f * wo.dot(n)) - wo;
            // pkg169: the delta-reflection BSDF value must carry the Fresnel
            // reflectance R so it cancels the R in the pdf (PBRT-v4 §9.5
            // DielectricBxDF::Sample_f). Setting f = 1 dropped R from f while the
            // pdf kept it, over-counting reflection by 1/R. This delta branch is
            // the fallthrough target for rough-glass VNDF samples that fail (near
            // 100% at high roughness -- pkg138), so the omission created energy in
            // the GPU rough furnace, rising with roughness. TIR is deterministic
            // (R=1), so f = 1 there. CPU twin: disney.cpp sample() delta branch.
            s.f   = GVec3(cannotRef ? 1.f : fresnel);
            // pkg118 Part A: forced-TIR reflection is deterministic (selection prob 1),
            // so pdf = transmission (not fresnel*transmission). PBRT-v4 §9.5. Mirrors CPU
            // disney.cpp forced-TIR fix; keeps the bespoke RGB GPU path in lockstep.
            s.pdf = cannotRef ? mat.transmission : (fresnel * mat.transmission);
        } else {
            GVec3 perp = (wo - n*cosTheta) * (-eta);
            GVec3 para = n * (-sqrtf(fabsf(1.f - perp.length2())));
            s.wi  = (perp + para).normalized();
            // pkg169: delta-transmission f must carry T = (1 - fresnel) so it
            // cancels the T in the pdf (PBRT-v4 §9.5; eta*eta is the radiance
            // factor 1/etap^2). CPU twin: disney.cpp sample() delta branch.
            s.f   = mat.baseColor * (eta*eta) * (1.f - fresnel);
            s.pdf = (1.f - fresnel) * mat.transmission;
        }
        s.isDelta = true;
        rec.isDelta = true;
        return s;
    }

    // Diffuse / specular lobe
    float diffW = (1.f - mat.metallic) * (1.f - mat.transmission);
    float specW = 1.f;
    float total = diffW + specW;

    if (gpu_rng_uniform(rng) * total < diffW) {
        GVec3 lw = gpu_randomCosineDir(rng);
        s.wi = rec.tangent*lw.x + rec.bitangent*lw.y + rec.normal*lw.z;
        s.f  = gpu_disney_eval(mat, rec, wo, s.wi);
        s.pdf = rec.normal.dot(s.wi) / M_PI_F * (diffW / total);
    } else {
        float a   = fmaxf(mat.roughness*mat.roughness, 0.0064f);
        float r1  = gpu_rng_uniform(rng);
        float r2  = gpu_rng_uniform(rng);
        float phi = 2.f * M_PI_F * r1;
        float cosT = sqrtf((1.f - r2) / (1.f + (a*a-1.f)*r2));
        float sinT = sqrtf(1.f - cosT*cosT);
        GVec3 h(cosf(phi)*sinT, sinf(phi)*sinT, cosT);
        h = rec.tangent*h.x + rec.bitangent*h.y + rec.normal*h.z;
        s.wi = (h*(2.f*wo.dot(h)) - wo).normalized();
        if (rec.normal.dot(s.wi) > 0.f) {
            s.f = gpu_disney_eval(mat, rec, wo, s.wi);
            float NdotH = rec.normal.dot(h);
            float HdotV = h.dot(wo);
            float D = gpu_D_GTR2(NdotH, a);
            // GGX reflection PDF: p(wi) = D(wm)·(wm·n) / (4·(wo·wm))
            // (Walter 2007 §5.3, pbrt-v4 §9.6 Eq. 9.24).
            s.pdf = D * NdotH / (4.f*HdotV) * (specW / total);
        }
    }
    s.isDelta = false;
    return s;
}

__device__ inline float gpu_disney_pdf(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    if (mat.transmission > 0.f && mat.roughness > 0.03f &&
        rec.normal.dot(wo) * rec.normal.dot(wi) < 0.f) {
        return gpu_disney_roughTransmissionPdf(mat, rec, wo, wi);
    }

    GVec3 H = (wo + wi).normalized();
    float diffW = (1.f - mat.metallic) * (1.f - mat.transmission);
    float specW = 1.f;
    float total = diffW + specW;
    // Mirrors CPU pdf() (disney.cpp ~527): the diffuse+plain-NDF-specular block
    // is only reached by gpu_disney_sample when the top-level transmission
    // roulette selects the NON-transmissive branch (probability
    // 1-mat.transmission); must gate by that factor or double-count against
    // the VNDF reflection term below for mat.transmission > 0 (glass).
    float mixScale = 1.f - mat.transmission;
    float p = 0.f;
    if (diffW > 0.f)
        p += (rec.normal.dot(wi) / M_PI_F) * (diffW / total) * mixScale;
    if (specW > 0.f) {
        // Alpha floor must match gpu_disney_sample (line 836) and CPU pdf()
        // (disney.cpp:530) — without it, D_GTR2 at NdotH=1 is 0/0=NaN as
        // roughness->0, and sample()/pdf() disagree on alpha near the floor.
        float a     = fmaxf(mat.roughness * mat.roughness, 0.0064f);
        float NdotH = rec.normal.dot(H);
        float HdotV = H.dot(wo);
        // Guard mirrors CPU pdf() (disney.cpp:533): with the epsilon removed
        // from gpu_D_GTR2/the 4*HdotV divide, NdotH<=0 or HdotV<=0 would
        // otherwise divide by zero or evaluate D outside its valid domain.
        if (NdotH > 0.f && HdotV > 0.f) {
            float D = gpu_D_GTR2(NdotH, a);
            // GGX reflection PDF: p(wi) = D(wm)·(wm·n) / (4·(wo·wm))
            // (Walter 2007 §5.3, pbrt-v4 §9.6 Eq. 9.24).
            p += (D * NdotH / (4.f*HdotV)) * (specW / total) * mixScale;
        }
    }
    if (mat.transmission > 0.f && mat.roughness > 0.03f) {
        // pkg169: entering MUST come from rec.frontFace, not sign(rec.normal.dot(wo))
        // (which is always > 0 -- rec.normal is the front-facing normal). For an
        // EXIT event (frontFace=false) the old test computed the air->glass Fresnel
        // (small) instead of glass->air (~1 near TIR), so this reflection-branch pdf
        // was far too small for internal reflections. The delta/eval path already
        // uses frontFace (sample()'s etaI/etaT; roughTransmission{Eval,Pdf} per
        // pkg154). The closure-graph sampler OVERWRITES the correct sampler pdf with
        // this gpu_disney_pdf, so the too-small internal-reflection pdf inflated
        // f/pdf up to ~20x per event -> the GPU rough-glass furnace energy gain.
        // CPU twin: disney.cpp pdf().
        bool entering = rec.frontFace;
        float etaI = entering ? 1.f : mat.ior;
        float etaT = entering ? mat.ior : 1.f;
        // fabsf() matches gpu_disney_sample's inline computation and CPU pdf()
        // (disney.cpp: fresnelDielectric(std::abs(wo.dot(H)), ...)) -- defensive
        // hardening, NOT the root cause of the glass chi² residual (Opus
        // re-review, 2026-07-20: the actual mechanism is a delta-vs-continuous
        // sample/pdf type mismatch, see pkg121-disney-pdf-finding.md "Round 2d").
        float F = gpu_disney_fresnelDielectric(fabsf(wo.dot(H)), etaI, etaT);
        p += mat.transmission * F * gpu_disney_microfacetReflectionPdf(mat, rec, wo, wi);
    }
    return p;
}

// ===========================================================================
// ===  Principled (pkg178 Stage 2 — GPU twin of the CPU core lobes)  =========
// ===========================================================================
// EXACT device mirror of plugins/materials/principled.cpp (the Stage-1 CPU
// scaffold, merged a2ae80a). A "principled" material lowers to
// GMAT_CLOSURE_GRAPH carrying a SINGLE GCLOSURE_PRINCIPLED closure that holds
// the raw core-lobe params; the code below reproduces, line-for-line:
//   PrincipledPlugin::assembleLobes           -> gpu_pr_assembleLobes
//   ::evalLobeRGB / ::eval                     -> gpu_pr_evalLobe / gpu_principled_eval
//   ::evalLobeSpectral / ::evalSpectral        -> gpu_pr_evalLobeSpectral / _eval_spectral
//   ::pdfLobe / ::pdf                          -> gpu_pr_pdfLobe / gpu_principled_pdf
//   ::chooseAndSampleDir / ::sample            -> gpu_pr_chooseAndSampleDir / gpu_principled_sample
//   ::ggxReflectRGB/Spectral, ::transmission*  -> gpu_pr_ggxReflect*, gpu_pr_transmission*
//   ::eonSetup/eonChannel/orenNayarG           -> gpu_pr_eon*/gpu_pr_orenNayarG
//   ::sampleGgxVNDF/vndfPdf/refractMicro       -> gpu_pr_sampleGgxVNDF/vndfPdf/refractMicro
// The GGX/glass energy-compensation and layering come from the SAME shipped
// tables the CPU reads (gpu_ggx_tables.cuh gpu_ggx{E,Eavg,DarkeningChannel,
// CompensationFactor,DirectionalAlbedo}, gpu_layeringWeightAfter;
// gpu_glass_tables.cuh gpu_ggxGlassCompensationFactor) — no term is re-derived.
// Cited Cycles sources / papers are those principled.cpp lists at its top
// (Cycles @main bsdf_util.h / bsdf_microfacet.h / bsdf_oren_nayar.h; Kulla &
// Conty 2017; Fujii/OpenPBR EON; Heitz 2018 VNDF; Kutz/Hoffman F82; Walter
// 2007; Veach 1997 §9.2.4 / PBRT-v4 §9.5 one-sample MIS).
//
// WHY MONOLITHIC (one closure, not four): assembleLobes is VIEW-DEPENDENT — the
// per-lobe selection weight `sel` is Fresnel/luminance-weighted (uses wo) and
// the diffuse layering weight is gpu_layeringWeightAfter(gpu_ggxDirectionalAlbedo
// (Fview, roughness, nv)) — a function of the view direction. Static per-lobe
// closures assembled once at upload time cannot reproduce that, so a decomposed
// graph could never be the byte-twin the spec requires; the assembly must run on
// device per shade. This is why a Principled material emits exactly ONE closure
// and G_MAX_MATERIAL_CLOSURES stays 8 (no cap bump).
//
// REGISTER-PRESSURE PROTOCOL (Stage-2 acceptance — MEASUREMENT DEFERRED TO THE
// LEAD, who alone can build CUDA on this machine): every function here is
// __device__ inline and, via gpu_closure_graph_* -> gpu_material_{eval,sample,
// pdf}{,_spectral}, lands INSIDE the already register-saturated wavefront
// shade/advance kernels (stageAdvance/stageShadeBucketed pinned REG:254 —
// memory `wavefront-shade-kernels-register-saturated`). The largest added
// live-state block is the on-stack GPrincipledLobe[kMaxPrincipledLobes] array
// assembled by gpu_pr_assembleLobes and re-read by eval/pdf/sample; expect the
// dominant delta to be STACK/spill, not just REG (pkg168 lesson: a REG-only
// check is blind). The lead MUST run cuobjdump per-kernel REG *and* STACK
// before/after and keep the non-principled wavefront perf gate green. If it does
// not fit even absorbed here, that is the D4 fork (absorb vs pkg174
// per-material-kernel dispatch) — an OWNER decision, never taken silently. A
// candidate lever short of D4 is __noinline__ on gpu_principled_sample/eval
// (measure first — memory `gpu-perf-ab-clock-drift`: a noinline "win" was a
// clock artifact).

// --- Fresnel / GGX / F82 primitives (principled.cpp:65-136) ----------------
__device__ inline float gpu_pr_D_GTR2(float NdotH, float a) {
    float a2 = a * a;
    float t = 1.f + (a2 - 1.f) * NdotH * NdotH;
    return a2 / (M_PI_F * t * t);
}
__device__ inline float gpu_pr_smithG1(float NdotV, float alphaG) {
    float a = alphaG * alphaG;
    float b = NdotV * NdotV;
    return 2.f * NdotV / (NdotV + sqrtf(a + b - a * b) + 0.001f);
}
// Height-correlated Smith masking-shadowing (pkg178 Stage-3b PR-4a) — GPU twin of
// principled.cpp smithLambda/smithG2_GGX. Replaces the former Disney/UE4 Schlick-k
// approximation with the EXACT Cycles form (Heitz 2014, JCGT Vol.3 No.2 §3.2
// Eq. 72; Cycles intern/cycles/kernel/closure/bsdf_microfacet.h, BSD-3-Clause:
// bsdf_lambda_from_sqr_alpha_tan_n / bsdf_lambda / bsdf_microfacet_eval). ISOTROPIC
// only (αx=αy → α=roughness²); anisotropy is PR-4b.
__device__ inline float gpu_pr_smithLambda(float cosTheta, float alpha) {
    float a2 = alpha * alpha;  // sqr_alpha (Cycles alpha2)
    float c2 = fmaxf(cosTheta * cosTheta, 1e-7f);
    float t = a2 * fmaxf(1.f / c2 - 1.f, 0.f);  // sqr_alpha * tan^2
    return 0.5f * (sqrtf(1.f + t) - 1.f);
}
__device__ inline float gpu_pr_smithG2(float NdotL, float NdotV, float alpha) {
    return 1.f / (1.f + gpu_pr_smithLambda(NdotV, alpha) + gpu_pr_smithLambda(NdotL, alpha));
}
// ---- pkg178 Stage-3b PR-4b — anisotropic GGX (GPU twin of principled.cpp) ----
// Byte-mirror of the CPU helpers; see .astroray_plan/docs/anisotropic-ggx-research.md
// and Cycles bsdf_microfacet.h / svm/closure.h (Apache-2.0 / BSD-3-Clause). At
// anisotropic==0 the reflect lobes take the iso branch (bit-identical to PR-4a).
__device__ inline void gpu_pr_anisoAlphas(float roughness, float anisotropic,
                                          float& ax, float& ay) {
    float a = fmaxf(roughness * roughness, 0.0064f);
    float aspect = sqrtf(fmaxf(1.f - anisotropic * 0.9f, 1e-4f));
    ax = fmaxf(a / aspect, 0.0064f);
    ay = fmaxf(a * aspect, 0.0064f);
}
__device__ inline GVec3 gpu_pr_rotateAroundAxis(const GVec3& T, const GVec3& N, float angle) {
    return T * cosf(angle) + N.cross(T) * sinf(angle);  // T⊥N Rodrigues
}
__device__ inline void gpu_pr_anisoFrame(const GHitRecord& rec, float anisoRotation,
                                         GVec3& X, GVec3& Y) {
    GVec3 T = rec.uvTangent;
    if (anisoRotation != 0.f)
        T = gpu_pr_rotateAroundAxis(T, rec.normal, anisoRotation * 2.f * M_PI_F);
    GVec3 b = rec.normal.cross(T);
    float bl2 = b.length2();
    if (bl2 < 1e-12f) { X = rec.tangent; Y = rec.bitangent; return; }
    Y = b * (1.f / sqrtf(bl2));
    X = Y.cross(rec.normal);
}
__device__ inline float gpu_pr_smithLambdaAniso(const GVec3& V, float ax, float ay) {
    float vz2 = fmaxf(V.z * V.z, 1e-7f);
    float t = ((ax * V.x) * (ax * V.x) + (ay * V.y) * (ay * V.y)) / vz2;
    return 0.5f * (sqrtf(1.f + t) - 1.f);
}
__device__ inline float gpu_pr_smithG2Aniso(const GVec3& I, const GVec3& O, float ax, float ay) {
    return 1.f / (1.f + gpu_pr_smithLambdaAniso(O, ax, ay) + gpu_pr_smithLambdaAniso(I, ax, ay));
}
// alpha2/(π·(alpha2·len2)² + reg): at ax==ay reduces exactly to a²/(π·denom²+reg)
// (the iso forms). reg is now 1e-12 everywhere (eval + pdf) so eval and pdf share
// the same D (pkg182); ~0 recovers the pure D_GTR2 form.
__device__ inline float gpu_pr_ggxAnisoD(const GVec3& H, float ax, float ay, float reg) {
    float hx = H.x / ax, hy = H.y / ay, hz = H.z;
    float len2 = hx * hx + hy * hy + hz * hz;
    float alpha2 = ax * ay;
    float denomA = alpha2 * len2;
    return alpha2 / (M_PI_F * denomA * denomA + reg);
}
// Per-triangle UV-aligned tangent (mirror of manifold::uvAlignedTangent, Lengyel
// 2001). Uses only the triangle's world-space verts + active-layer UVs + N (no
// barycentric); returns false + leaves outT/outSign untouched on a degenerate
// UV/projection so the caller keeps its arbitrary-frame fallback.
__device__ inline bool gpu_pr_uvAlignedTangent(const GVec3& p0, const GVec3& p1, const GVec3& p2,
                                               const GVec2& w0, const GVec2& w1, const GVec2& w2,
                                               const GVec3& N, GVec3& outT, float& outSign) {
    GVec3 dp_du = p1 - p0, dp_dv = p2 - p0;
    float du1 = w1.x - w0.x, dv1 = w1.y - w0.y;
    float du2 = w2.x - w0.x, dv2 = w2.y - w0.y;
    float det = du1 * dv2 - du2 * dv1;
    if (fabsf(det) <= 1e-12f) return false;
    float invDet = 1.f / det;
    GVec3 T  = (dp_du * dv2 - dp_dv * dv1) * invDet;
    GVec3 Bt = (dp_dv * du1 - dp_du * du2) * invDet;
    GVec3 Tortho = T - N * N.dot(T);
    float tlen2 = Tortho.length2();
    if (tlen2 <= 1e-12f) return false;
    outT = Tortho * (1.f / sqrtf(tlen2));
    outSign = (N.cross(outT).dot(Bt) < 0.f) ? -1.f : 1.f;
    return true;
}
__device__ inline float gpu_pr_F0_from_ior(float ior) {
    float f = (ior - 1.f) / (ior + 1.f);
    return f * f;
}
__device__ inline float gpu_pr_fresnelDielectricCos(float cosi, float eta) {
    float c = fabsf(cosi);
    float g = eta * eta - 1.f + c * c;
    if (g > 0.f) {
        g = sqrtf(g);
        float A = (g - c) / (g + c);
        float B = (c * (g + c) - 1.f) / (c * (g - c) + 1.f);
        return 0.5f * A * A * (1.f + B * B);
    }
    return 1.f;
}
__device__ inline float gpu_pr_generalizedSchlickS(float cosThetaI, float ior) {
    float Fr = gpu_pr_fresnelDielectricCos(cosThetaI, ior);
    float F0r = gpu_pr_F0_from_ior(ior);
    float denom = 1.f - F0r;
    if (denom < 1e-6f) return 0.f;
    return fminf(fmaxf((Fr - F0r) / denom, 0.f), 1.f);
}
__device__ inline float gpu_pr_f82BChannel(float f0, float tint) {
    const float f = 6.f / 7.f;
    const float f5 = (f * f) * (f * f) * f;  // f^5
    float Fs = f0 + (1.f - f0) * f5;
    return Fs * (7.f / (f5 * f)) * (1.f - tint);
}
__device__ inline float gpu_pr_f82Channel(float cosi, float f0, float tint) {
    float B = gpu_pr_f82BChannel(f0, tint);
    float s = fminf(fmaxf(1.f - cosi, 0.f), 1.f);
    float s5 = (s * s) * (s * s) * s;  // s^5
    float Fs = f0 + (1.f - f0) * s5;
    return fminf(fmaxf(Fs - B * cosi * s5 * s, 0.f), 1.f);
}
// principled.cpp:126 fresnelDielectric — mirrored exactly (its own +1e-6 denom
// guard and final clamp differ subtly from gpu_fresnelDielectric, so keep a
// dedicated copy to stay byte-for-byte with the CPU transmission lobe).
__device__ inline float gpu_pr_fresnelDielectric(float cosThetaI, float etaI, float etaT) {
    cosThetaI = fminf(fmaxf(cosThetaI, -1.f), 1.f);
    if (cosThetaI <= 0.f) { float t = etaI; etaI = etaT; etaT = t; cosThetaI = fabsf(cosThetaI); }
    float sinI = sqrtf(fmaxf(0.f, 1.f - cosThetaI * cosThetaI));
    float sinT = etaI / etaT * sinI;
    if (sinT >= 1.f) return 1.f;
    float cosT = sqrtf(fmaxf(0.f, 1.f - sinT * sinT));
    float rp = (etaT * cosThetaI - etaI * cosT) / (etaT * cosThetaI + etaI * cosT + 1e-6f);
    float rs = (etaI * cosThetaI - etaT * cosT) / (etaI * cosThetaI + etaT * cosT + 1e-6f);
    return fminf(fmaxf(0.5f * (rp * rp + rs * rs), 0.f), 1.f);
}
__device__ inline GVec3 gpu_pr_sqrtColor(const GVec3& c) {
    return GVec3(sqrtf(fmaxf(0.f, c.x)), sqrtf(fmaxf(0.f, c.y)), sqrtf(fmaxf(0.f, c.z)));
}

// ==========================================================================
// pkg178 Stage 4 PR-3 — thin-film iridescence (GPU twin of principled.cpp
// PR-1/PR-2). SAME shared core (thin_film_fresnel.h fresnelIridescenceChannel)
// as the CPU — byte-identical math, one body, two legs. The film only OVERRIDES
// the single-scatter Fresnel F at the specular/transmission/metallic eval sites,
// gated on gpu_pr_filmActive; thickness ≤ cutoff → these are NEVER called, so
// thickness-0 renders are byte-identical to PR-6 (the load-bearing no-op).
// energy-comp (compFss) stays FILM-FREE (no double-count), exactly as CPU/Cycles.
// ==========================================================================
__device__ inline bool gpu_pr_filmActive(const GPrincipledClosure& c) {
    return c.thinFilmThickness > astroray::thinfilm::kThinFilmThicknessCutoff;
}
// principled.cpp::thinFilmFresnelRGB — per-RGB-channel dielectric iridescence F,
// RGB sensitivity via the device CIE LUT (gpu_pr_sensitivityRGB).
__device__ inline GVec3 gpu_pr_thinFilmFresnelRGB(const GPrincipledClosure& c, float cosI,
                                                  float iorArg, float filmIor) {
    namespace tf = astroray::thinfilm;
    GVec3 out;
    for (int ch = 0; ch < 3; ++ch) {
        auto S = [ch](float argOPD) { return gpu_pr_sensitivityRGB(argOPD, ch); };
        (&out.x)[ch] = tf::fresnelIridescenceChannel<false>(
            1.f, c.thinFilmThickness, filmIor, iorArg, 0.f, -1.f, cosI, nullptr, S);
    }
    return out;
}
// principled.cpp::thinFilmFresnelSpectral — per-λ analytic sensitivity (no LUT).
__device__ inline GSampledSpectrum gpu_pr_thinFilmFresnelSpectral(
        const GPrincipledClosure& c, float cosI, float iorArg, float filmIor,
        const GSampledWavelengths& wl) {
    namespace tf = astroray::thinfilm;
    GSampledSpectrum out(0.f);
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
        float lambda = wl.lambda[i];
        auto S = [lambda](float argOPD) { return tf::sensitivitySpectral(argOPD, lambda); };
        out[i] = tf::fresnelIridescenceChannel<false>(
            1.f, c.thinFilmThickness, filmIor, iorArg, 0.f, -1.f, cosI, nullptr, S);
    }
    return out;
}
// principled.cpp::thinFilmF0RescaleChannel / thinFilmF0RescaleRGB — Cycles
// generalized_schlick_fresnel thin-film F0-rescale (bsdf_microfacet.h:284-297).
__device__ inline float gpu_pr_thinFilmF0RescaleChannel(float Fc, float f0c, float F0real) {
    float s = fminf(fmaxf((Fc - 1.f) / (F0real - 1.f), 0.f), 1.f);
    float factor = f0c / F0real;
    return Fc * (1.f + (factor - 1.f) * s);
}
__device__ inline GVec3 gpu_pr_thinFilmF0RescaleRGB(GVec3 F, const GVec3& f0, float iorArg) {
    float F0real = gpu_pr_F0_from_ior(iorArg);
    if (F0real <= 1e-5f || (F.x == 1.f && F.y == 1.f && F.z == 1.f)) return F;
    return GVec3(gpu_pr_thinFilmF0RescaleChannel(F.x, f0.x, F0real),
                 gpu_pr_thinFilmF0RescaleChannel(F.y, f0.y, F0real),
                 gpu_pr_thinFilmF0RescaleChannel(F.z, f0.z, F0real));
}
// Per-channel Gulbrandsen conductor (n,k) + F82 value g from (f0, specular_tint) —
// exact mirror of principled.cpp::precomputeConductorNK ("Artist Friendly Metallic
// Fresnel", Gulbrandsen JCGT 2014; Cycles bsdf_microfacet.h:365-383). On the CPU
// this is a per-material ctor precompute; on the GPU it is recomputed PER HIT here
// (only reached on the metallic thin-film path, <true> only) so the 9 floats do
// NOT bloat GPrincipledClosure/GMaterial and leak STACK into the shared <false>
// kernel via its by-value copy (see gpu_types.h). g reuses the metallic lobe's own
// F82 eval at cosθ=1/7 (gpu_pr_f82Channel == principled.cpp::f82Channel).
__device__ inline void gpu_pr_conductorNK(float f0, float tint, float& n, float& k, float& g) {
    const float r = fminf(f0, 0.999f);
    g = gpu_pr_f82Channel(1.f / 7.f, f0, tint);
    const float sqrtR = sqrtf(r);
    const float nLo = (1.f + sqrtR) / (1.f - sqrtR);
    const float nHi = (1.f - r) / (1.f + r);
    n = nLo + (nHi - nLo) * g;
    const float kNum = r * (n + 1.f) * (n + 1.f) - (n - 1.f) * (n - 1.f);
    k = sqrtf(fmaxf(0.f, kNum / (1.f - r)));
}
// principled.cpp::thinFilmConductorRGB — per-RGB-channel conductor iridescence F
// with the PER-HIT-computed (n,k,g) + the CIE LUT.
__device__ inline GVec3 gpu_pr_thinFilmConductorRGB(const GPrincipledClosure& c, float cosI) {
    namespace tf = astroray::thinfilm;
    GVec3 out;
    for (int ch = 0; ch < 3; ++ch) {
        float n, k, g;
        gpu_pr_conductorNK((&c.color.x)[ch], (&c.specularTint.x)[ch], n, k, g);
        auto S = [ch](float argOPD) { return gpu_pr_sensitivityRGB(argOPD, ch); };
        (&out.x)[ch] = tf::fresnelIridescenceChannel<true>(
            1.f, c.thinFilmThickness, c.thinFilmIor, n, k, g, cosI, nullptr, S);
    }
    return out;
}
// principled.cpp::thinFilmConductorSpectral — RGB-channel conductor F upsampled
// to spectral (Cycles has no spectral n,k; plan §0.5 APPROXIMATED-equal-to-Cycles).
__device__ inline GSampledSpectrum gpu_pr_thinFilmConductorSpectral(
        const GPrincipledClosure& c, float cosI, const GSampledWavelengths& wl) {
    GVec3 rgb = gpu_pr_thinFilmConductorRGB(c, cosI);
    float maxc = fmaxf(fmaxf(fmaxf(rgb.x, rgb.y), rgb.z), 1.f);
    GVec3 tint = rgb * (1.f / maxc);
    return gpu_rgbToSampledSpectrum(tint, wl, GSPEC_RGB_ALBEDO) * maxc;
}

// ==========================================================================
// pkg178 Stage 4 PR-4 — THIN WALL (GPU twin of principled.cpp). thin_wall +
// subsurface_anisotropy are decoded from the ONE packed float thinWallAniso
// (see gpu_types.h): thin_wall=false → -8 sentinel; else the value is aniso.
// ==========================================================================
__device__ inline bool gpu_pr_thinWall(const GPrincipledClosure& c) {
    return c.thinWallAniso > -2.f;
}
__device__ inline float gpu_pr_subsurfaceAniso(const GPrincipledClosure& c) {
    return c.thinWallAniso > -2.f ? c.thinWallAniso : 0.f;
}
// Kulla-Conty roughened alpha for the mirrored-transmission lobe (the slide's 3.7
// is a typo for 3.4; Cycles bsdf_thin_glass_transmission_roughness :1307). `alpha`
// = GGX alpha (roughness²).
__device__ inline float gpu_pr_thinGlassTransmissionRoughness(float alpha, float eta) {
    float k = 3.4f * (eta - 1.f) * (eta - 0.5f) * (eta - 0.5f) / (eta * eta * eta);
    float aT = alpha * sqrtf(fmaxf(0.f, k));
    return aT < 0.f ? 0.f : (aT > 1.f ? 1.f : aT);
}
// One-channel generalized-Schlick Fresnel (r,t) — twin of thinGlassSchlickChannel.
__device__ inline void gpu_pr_thinGlassSchlickChannel(const GPrincipledClosure& c,
                                                      float iorParam, float filmIor,
                                                      float cosThetaI, int ch,
                                                      float& r, float& t, float* rCosThetaT) {
    namespace tf = astroray::thinfilm;
    const float f0c = gpu_pr_F0_from_ior(c.ior) * (&c.specularTint.x)[ch];
    float F;
    if (gpu_pr_filmActive(c)) {
        auto S = [ch](float argOPD) { return gpu_pr_sensitivityRGB(argOPD, ch); };
        F = tf::fresnelIridescenceChannel<false>(1.f, c.thinFilmThickness, filmIor, iorParam,
                                                 0.f, -1.f, cosThetaI, rCosThetaT, S);
        const float F0real = gpu_pr_F0_from_ior(iorParam);
        if (F0real > 1e-5f && F != 1.f) F = gpu_pr_thinFilmF0RescaleChannel(F, f0c, F0real);
    } else {
        tf::TFDielectric d = tf::fresnelDielectricPolarized(cosThetaI, iorParam);
        if (rCosThetaT) *rCosThetaT = d.cosThetaT;
        const float Freal = 0.5f * (d.Rs + d.Rp);
        const float F0real = gpu_pr_F0_from_ior(iorParam);
        const float s = fminf(fmaxf((Freal - F0real) / (1.f - F0real), 0.f), 1.f);
        F = f0c + (1.f - f0c) * s;
    }
    r = F;
    t = 1.f - F;
}
// Combined thin-glass R', T' per RGB channel (twin of thinGlassFresnelRGB;
// Cycles bsdf_thin_glass_fresnel :1236).
__device__ inline void gpu_pr_thinGlassFresnelRGB(const GPrincipledClosure& c, float cosThetaI,
                                                  GVec3& Rp, GVec3& Tp) {
    namespace tf = astroray::thinfilm;
    float cosThetaT = 0.f;
    for (int ch = 0; ch < 3; ++ch) {
        float r1, t1, ct;
        gpu_pr_thinGlassSchlickChannel(c, c.ior, c.thinFilmIor, cosThetaI, ch, r1, t1, &ct);
        if (ch == 0) cosThetaT = ct;
        float r2 = r1, t2 = t1;
        if (gpu_pr_filmActive(c)) {
            float filmIorBack = c.thinFilmIor;
            tf::adjustThinFilmIorAtBackface(filmIorBack, 1.f / c.ior);
            float unused;
            gpu_pr_thinGlassSchlickChannel(c, 1.f / c.ior, filmIorBack, -cosThetaT, ch, r2, t2, &unused);
        }
        const float base = fminf(fmaxf((&c.color.x)[ch], 0.f), 1.f);
        const float cc = (cosThetaT == 0.f) ? 0.f : powf(base, -1.f / cosThetaT);
        const float denom = 1.f - (r2 * cc) * (r2 * cc);
        const float Tc = (fabsf(denom) > 1e-12f) ? (cc * t1 * t2 / denom) : 0.f;
        const float Rc = r1 + Tc * r2 * cc;
        (&Rp.x)[ch] = Rc;
        (&Tp.x)[ch] = Tc;
    }
}

// --- VNDF sampling + micro-refraction (principled.cpp:187-229) -------------
__device__ inline float gpu_pr_vndfPdf(const GVec3& N, const GVec3& wo, const GVec3& wm, float roughness) {
    float absCosO = fabsf(wo.dot(N));
    if (absCosO <= 1e-10f) return 0.f;
    float HdotO = fabsf(wo.dot(wm));
    float NdotH = fabsf(wm.dot(N));
    if (HdotO <= 1e-10f || NdotH <= 1e-10f) return 0.f;
    float alpha = fmaxf(roughness * roughness, 0.0064f);
    float D = gpu_pr_D_GTR2(NdotH, alpha);
    float G1 = gpu_pr_smithG1(absCosO, alpha);
    return G1 / absCosO * D * HdotO;
}
template <typename TRng>
__device__ inline GVec3 gpu_pr_sampleGgxVNDF(const GHitRecord& rec, const GVec3& wo,
                                             float roughness, TRng* rng) {
    float alpha = fmaxf(roughness * roughness, 0.0064f);
    float u1 = gpu_rng_uniform(rng), u2 = gpu_rng_uniform(rng);
    GVec3 wo_l(wo.dot(rec.tangent), wo.dot(rec.bitangent), wo.dot(rec.normal));
    GVec3 wh = GVec3(alpha * wo_l.x, alpha * wo_l.y, wo_l.z).normalized();
    if (wh.z < 0.f) wh = -wh;
    GVec3 T1 = (wh.z < 0.99999f) ? GVec3(0, 0, 1).cross(wh).normalized() : GVec3(1, 0, 0);
    GVec3 T2 = wh.cross(T1);
    float r = sqrtf(u1);
    float phi = 2.f * M_PI_F * u2;
    float px = r * cosf(phi);
    float py = r * sinf(phi);
    float h = sqrtf(fmaxf(0.f, 1.f - px * px));
    float t = (1.f + wh.z) / 2.f;
    py = (1.f - t) * h + t * py;
    float pz = sqrtf(fmaxf(0.f, 1.f - px * px - py * py));
    GVec3 nh = T1 * px + T2 * py + wh * pz;
    GVec3 m_l = GVec3(alpha * nh.x, alpha * nh.y, fmaxf(1e-6f, nh.z)).normalized();
    GVec3 m = rec.tangent * m_l.x + rec.bitangent * m_l.y + rec.normal * m_l.z;
    return m.normalized();
}
__device__ inline bool gpu_pr_refractMicro(const GVec3& wo, const GVec3& m, float eta, GVec3& wi) {
    float cc = fminf(fmaxf(wo.dot(m), -1.f), 1.f);
    if (cc <= 0.f) return false;
    GVec3 perp = (wo - m * cc) * (-eta);
    float par2 = 1.f - perp.length2();
    if (par2 <= 0.f) return false;
    wi = (perp + m * (-sqrtf(par2))).normalized();
    return wi.length2() > 1e-10f;
}

// --- EON diffuse (Fujii ON + OpenPBR multiscatter; principled.cpp:321-350) --
__device__ inline float gpu_pr_orenNayarG(float cosTheta) {
    if (cosTheta < 1e-6f) return (M_PI_F * 0.5f - 2.f / 3.f) - cosTheta;
    float sinT = sqrtf(fmaxf(0.f, 1.f - cosTheta * cosTheta));
    float theta = acosf(fminf(fmaxf(cosTheta, -1.f), 1.f));
    return sinT * (theta - 2.f / 3.f - sinT * cosTheta) +
           2.f / 3.f * (sinT / cosTheta) * (1.f - sinT * sinT * sinT);
}
struct GPrincipledEON { float a, b, Ev, El, Eavg, single, nl; };
__device__ inline GPrincipledEON gpu_pr_eonSetup(float sigma, float nl, float nv, float LdotV) {
    GPrincipledEON e;
    e.nl = nl;
    e.a = 1.f / (M_PI_F + sigma * (M_PI_F * 0.5f - 2.f / 3.f));
    e.b = sigma * e.a;
    float s = LdotV - nl * nv;
    float t = s > 0.f ? s / fmaxf(nl, nv) : s;
    e.single = e.a + e.b * t;
    e.Eavg = e.a * M_PI_F + ((2.f * M_PI_F - 5.6f) / 3.f) * e.b;
    e.El = e.a * M_PI_F + e.b * gpu_pr_orenNayarG(nl);
    e.Ev = e.a * M_PI_F + e.b * gpu_pr_orenNayarG(nv);
    return e;
}
__device__ inline float gpu_pr_eonChannel(const GPrincipledEON& e, float c) {
    float Eavg = fminf(fmaxf(e.Eavg, 0.f), 0.999f);
    float denom = fmaxf(1.f - c * (1.f - Eavg), 1e-4f);
    float Ems = (1.f / M_PI_F) * c * c * (Eavg / fmaxf(1.f - Eavg, 1e-4f)) / denom;
    float multi = Ems * (1.f - e.Ev) * (1.f - e.El);
    return e.nl * (e.single + multi);
}

// --- pkg178 Stage 3 Coat / Sheen helpers (principled.cpp ports) ------------
// Coat Beer absorption: weight *= mix(1, coat_tint^(1/cosNT), coat_weight),
// cosNT = sqrt(1 - (1/coat_ior)^2 (1-cosNI^2)) (Cycles svm/closure.h coat layer).
__device__ inline GVec3 gpu_pr_coatBeerFactor(const GPrincipledClosure& c, float nv) {
    if (c.coatWeight <= 1e-4f) return GVec3(1.f);
    if (c.coatTint.x >= 0.999f && c.coatTint.y >= 0.999f && c.coatTint.z >= 0.999f)
        return GVec3(1.f);
    float cosNI = fminf(fmaxf(nv, 1e-3f), 1.f);
    float inv = 1.f / c.coatIor;
    float cosNT = sqrtf(fmaxf(1e-4f, 1.f - inv * inv * (1.f - cosNI * cosNI)));
    float od = 1.f / cosNT;
    GVec3 tintPow(powf(fminf(fmaxf(c.coatTint.x, 0.f), 1.f), od),
                  powf(fminf(fmaxf(c.coatTint.y, 0.f), 1.f), od),
                  powf(fminf(fmaxf(c.coatTint.z, 0.f), 1.f), od));
    return GVec3(1.f) * (1.f - c.coatWeight) + tintPow * c.coatWeight;
}
// Sheen view-dependent frame: make_orthonormals_safe_tangent(N, wo).
__device__ inline void gpu_pr_sheenFrame(const GVec3& N, const GVec3& wo, GVec3& T, GVec3& B) {
    GVec3 t = wo - N * N.dot(wo);
    if (t.length2() > 1e-8f) {
        T = t.normalized();
    } else {
        T = (fabsf(N.x) < 0.99f) ? GVec3(1, 0, 0).cross(N).normalized()
                                 : GVec3(0, 1, 0).cross(N).normalized();
    }
    B = N.cross(T);
}
// Cycles bsdf_sheen_eval: 1/pi * max(localO.z,0) * (a/lenSqr)^2.
__device__ inline float gpu_pr_sheenValue(float a, float b, const GVec3& localO) {
    float lenSqr = (a * localO.x + b * localO.z) * (a * localO.x + b * localO.z) +
                   (a * localO.y) * (a * localO.y) + localO.z * localO.z;
    float lo = fmaxf(localO.z, 0.f);
    float t = a / fmaxf(lenSqr, 1e-12f);
    return (1.f / M_PI_F) * lo * t * t;
}

// --- Lobe representation + view-dependent assembly (principled.cpp:50-314) --
// pkg178 Stage 3 adds Coat / Sheen / Subsurface (principled.cpp LobeKind).
enum GPrincipledLobeKind {
    GPR_DIFFUSE = 0, GPR_SPECULAR = 1, GPR_METALLIC = 2, GPR_TRANSMISSION = 3,
    GPR_COAT = 4, GPR_SHEEN = 5, GPR_SUBSURFACE = 6,
    GPR_TRANSPARENT = 7,  // pkg178 PR-6 alpha delta lobe (assembled first)
    // pkg178 Stage 4 PR-4 Thin Wall (principled.cpp LobeKind twins):
    GPR_THINGLASS_REFLECT = 8, GPR_THINGLASS_TRANSMIT = 9, GPR_TRANSLUCENT = 10
};
struct GPrincipledLobe {
    int   kind;
    GVec3 weight;
    GVec3 color;
    float roughness;
    float ior;
    float sel;
    bool  isDelta;
    float sheenA;  // Sheen LTC aInv (view-dependent)
    float sheenB;  // Sheen LTC bInv
    // pkg178 PR-4b (specular/metallic; 0 → isotropic). Default-initialized so the
    // uninitialized on-stack lobes[] array reads 0 for every non-aniso lobe (the
    // iso branch); assembleLobes overrides only metallic/specular.
    float anisotropic   = 0.f;
    float anisoRotation = 0.f;
};
// pkg178 Stage 3: the full stack can allocate sheen+coat+metallic+transmission+
// specular+subsurface+diffuse = 7 on-stack lobes. pkg178 PR-6 adds the alpha
// transparent lobe (assembled first) → 8. This on-stack array is the dominant added
// live state in the register-saturated shade kernels — LEAD MUST remeasure cuobjdump
// REG *and* STACK for the wavefront shade/advance kernels; the +1 slot lives only in
// the <true> (HasPrincipled) instantiation, so non-principled scenes are unaffected.
// pkg178 Stage 4 PR-4: Thin Wall can add TWO thin-glass lobes (reflect+transmit)
// AND TWO thin-subsurface lobes (front diffuse + back translucent) on top of the
// existing 8, so the worst-case stack is transparent+sheen+coat+metallic+
// thinglass(2)+specular+thinsubsurface(2)+diffuse = 10. This on-stack array lives
// ONLY in the <true> (HasPrincipled) instantiation, so the non-principled <false>
// kernel is unaffected; the +2 slots grow the <true> stack only (LEAD remeasures
// cuobjdump REG/STACK for the principled shade kernel).
static constexpr int   kMaxPrincipledLobes  = 10;
static constexpr float kPrincipledDeltaGlassRoughness = 0.03f;  // principled.cpp:43

__device__ inline int gpu_pr_assembleLobes(const GPrincipledClosure& c, const GHitRecord& rec,
                                           const GVec3& wo, GPrincipledLobe lobes[kMaxPrincipledLobes]) {
    float nv = fminf(fmaxf(rec.normal.dot(wo), 1e-4f), 1.f);
    GVec3 weight(1.f, 1.f, 1.f);  // W₀ = 1
    GVec3 baseColor = c.color;
    int n = 0;
    // 1. Transparent (alpha) — Cycles svm/closure.h transparency-FIRST ordering:
    //    bsdf_transparent_setup(sd, weight*(1-alpha)); weight *= alpha; before every
    //    other closure. Delta lobe (Cycles bsdf_transparent.h: wo=-wi, matched
    //    pdf==eval, zero eval/pdf outside sampling). At alpha==1 NO lobe assembled →
    //    byte-identical to PR-4b (delta-glass safety property). Mirrors principled.cpp.
    if (c.alpha < 1.f) {
        GPrincipledLobe& L = lobes[n++];
        L.kind = GPR_TRANSPARENT; L.weight = weight * (1.f - c.alpha); L.color = GVec3(1.f);
        L.roughness = 0.f; L.ior = 1.f; L.isDelta = true;
        L.sheenA = 0.f; L.sheenB = 0.f;
        L.sel = fmaxf(luminance(L.weight), 1e-4f);
        weight = weight * c.alpha;
    }
    // 2. Sheen (LTC microfiber) — principled.cpp assembleLobes
    if (c.sheenWeight > 1e-4f) {
        astroray::SheenLtcCoeffs sc =
            astroray::sheenLtcFetch(fminf(fmaxf(c.sheenRoughness, 1e-3f), 1.f), nv);
        if (fabsf(sc.aInv) >= 1e-5f && sc.albedo >= 1e-5f) {
            GVec3 sheenW = weight * c.sheenTint * (c.sheenWeight * sc.albedo);
            GPrincipledLobe& L = lobes[n++];
            L.kind = GPR_SHEEN; L.weight = sheenW; L.color = c.sheenTint;
            L.roughness = c.sheenRoughness; L.ior = c.ior; L.isDelta = false;
            L.sheenA = sc.aInv; L.sheenB = sc.bInv;
            L.sel = fmaxf(luminance(sheenW), 1e-4f);
            weight = gpu_layeringWeightAfter(weight, c.sheenTint * (c.sheenWeight * sc.albedo));
        }
    }
    // 3. Coat (clear GGX dielectric, coat_ior) + Beer absorption + layering
    if (c.coatWeight > 1e-4f) {
        float f0c = gpu_pr_F0_from_ior(c.coatIor);
        float sView = gpu_pr_generalizedSchlickS(nv, c.coatIor);
        float Fview = f0c + (1.f - f0c) * sView;
        GPrincipledLobe& L = lobes[n++];
        L.kind = GPR_COAT; L.weight = weight * c.coatWeight; L.color = GVec3(f0c);
        L.roughness = c.coatRoughness; L.ior = c.coatIor; L.isDelta = false;
        L.sheenA = 0.f; L.sheenB = 0.f;
        L.sel = fmaxf(luminance(weight * c.coatWeight) * Fview, 1e-4f);
        weight = gpu_layeringWeightAfter(
            weight, gpu_ggxDirectionalAlbedo(GVec3(Fview), c.coatRoughness, nv) * c.coatWeight);
        weight = weight * gpu_pr_coatBeerFactor(c, nv);
    }
    // 4. Metallic (GGX + F82-tint)
    if (c.metallic > 1e-4f) {
        GPrincipledLobe& L = lobes[n++];
        L.kind = GPR_METALLIC; L.weight = weight * c.metallic; L.color = baseColor;
        L.roughness = c.roughness; L.ior = c.ior; L.isDelta = false;
        L.anisotropic = c.anisotropic; L.anisoRotation = c.anisotropicRotation;  // PR-4b
        L.sel = fmaxf(luminance(L.weight * baseColor), 1e-4f);
        weight = weight * (1.f - c.metallic);
    }
    // 5. Transmission. thin_wall=false → rough glass (PR-1..3). thin_wall=true →
    //    analytic thin-glass R'+T' split (Cycles bsdf_thin_glass_setup :1392).
    if (c.transmission > 1e-4f && luminance(weight) > 1e-4f) {
        if (gpu_pr_thinWall(c)) {
            GVec3 Rp, Tp;
            gpu_pr_thinGlassFresnelRGB(c, nv, Rp, Tp);  // per-channel R', T' at the view angle
            GVec3 baseW = weight * c.transmission;
            if (luminance(Rp) > 1e-6f) {
                GPrincipledLobe& L = lobes[n++];
                L.kind = GPR_THINGLASS_REFLECT; L.weight = baseW * Rp; L.color = c.specularTint;
                L.roughness = c.roughness; L.ior = c.ior; L.isDelta = false;
                L.sheenA = 0.f; L.sheenB = 0.f; L.anisotropic = 0.f; L.anisoRotation = 0.f;
                L.sel = fmaxf(luminance(L.weight), 1e-4f);
            }
            if (luminance(Tp) > 1e-6f) {
                float aReflect = c.roughness * c.roughness;
                float aT = gpu_pr_thinGlassTransmissionRoughness(aReflect, c.ior);
                GPrincipledLobe& L = lobes[n++];
                L.kind = GPR_THINGLASS_TRANSMIT; L.weight = baseW * Tp; L.color = GVec3(1.f);
                L.ior = c.ior; L.isDelta = (aT * aT) <= 2e-10f;
                L.roughness = sqrtf(fmaxf(0.f, aT));  // ggxReflect squares → aT
                L.sheenA = 0.f; L.sheenB = 0.f; L.anisotropic = 0.f; L.anisoRotation = 0.f;
                L.sel = fmaxf(luminance(L.weight), 1e-4f);
            }
        } else {
            GPrincipledLobe& L = lobes[n++];
            L.kind = GPR_TRANSMISSION; L.weight = weight * c.transmission; L.color = baseColor;
            L.roughness = c.roughness; L.ior = c.ior;
            L.isDelta = c.roughness <= kPrincipledDeltaGlassRoughness;
            L.sel = fmaxf(luminance(L.weight), 1e-4f);
        }
        weight = weight * (1.f - c.transmission);
    }
    // 6. Specular dielectric (generalized-Schlick, exponent = -ior)
    if (luminance(weight) > 1e-4f) {
        float f0s = gpu_pr_F0_from_ior(c.ior) * 2.f * c.specularIorLevel;
        GVec3 specF0 = GVec3(f0s) * c.specularTint;
        float sView = gpu_pr_generalizedSchlickS(nv, c.ior);
        GVec3 Fview = specF0 + (GVec3(1.f) - specF0) * sView;
        GPrincipledLobe& L = lobes[n++];
        L.kind = GPR_SPECULAR; L.weight = weight; L.color = specF0;
        L.roughness = c.roughness; L.ior = c.ior; L.isDelta = false;
        L.anisotropic = c.anisotropic; L.anisoRotation = c.anisotropicRotation;  // PR-4b
        L.sel = fmaxf(luminance(weight * Fview), 1e-4f);
        weight = gpu_layeringWeightAfter(weight, gpu_ggxDirectionalAlbedo(Fview, c.roughness, nv));
    }
    // 7. Subsurface — APPROXIMATE (D2=a): Lambertian base-colour stand-in for the
    //    Cycles random-walk Bssrdf (see principled.cpp for the seam/citation).
    if (c.subsurfaceWeight > 1e-4f && luminance(weight) > 1e-4f) {
        if (gpu_pr_thinWall(c)) {
            // Thin subsurface (Cycles bsdf_thin_subsurface_setup :169): diffuse(+N) +
            // translucent(-N) split by subsurface_anisotropy g.
            GVec3 ssW = weight * baseColor * c.subsurfaceWeight;
            float g = gpu_pr_subsurfaceAniso(c);
            float wr = fminf(fmaxf(0.5f * (1.f - g), 0.f), 1.f);
            float wt = fminf(fmaxf(0.5f * (1.f + g), 0.f), 1.f);
            if (wr > 1e-6f) {
                GPrincipledLobe& L = lobes[n++];
                L.kind = GPR_DIFFUSE; L.weight = ssW * wr; L.color = baseColor;
                L.roughness = c.diffuseRoughness; L.ior = c.ior; L.isDelta = false;
                L.sel = fmaxf(luminance(L.weight), 1e-4f);
            }
            if (wt > 1e-6f) {
                GPrincipledLobe& L = lobes[n++];
                L.kind = GPR_TRANSLUCENT; L.weight = ssW * wt; L.color = baseColor;
                L.roughness = c.diffuseRoughness; L.ior = c.ior; L.isDelta = false;
                L.sel = fmaxf(luminance(L.weight), 1e-4f);
            }
        } else {
            GPrincipledLobe& L = lobes[n++];
            L.kind = GPR_SUBSURFACE; L.weight = weight * baseColor * c.subsurfaceWeight;
            L.color = baseColor; L.roughness = 0.f; L.ior = c.ior; L.isDelta = false;
            L.sel = fmaxf(luminance(L.weight), 1e-4f);
        }
    }
    // 8. Diffuse (Lambert / EON), weight * (1 - subsurface_weight)
    if (luminance(weight) > 1e-4f) {
        GPrincipledLobe& L = lobes[n++];
        L.kind = GPR_DIFFUSE; L.weight = weight * baseColor * (1.f - c.subsurfaceWeight);
        L.color = baseColor;
        L.roughness = c.diffuseRoughness; L.ior = c.ior; L.isDelta = false;
        L.sel = fmaxf(luminance(L.weight), 1e-4f);
    }
    if (n == 0) {  // degenerate guard (principled.cpp:305-312)
        GPrincipledLobe& L = lobes[0];
        L.kind = GPR_DIFFUSE; L.weight = baseColor; L.color = baseColor;
        L.roughness = 0.f; L.ior = c.ior; L.isDelta = false;
        L.sel = fmaxf(luminance(baseColor), 1e-4f);
        n = 1;
    }
    return n;
}

// --- GGX reflection BRDF*cos with multiscatter comp (principled.cpp:389-401,677-698) ---
__device__ inline GVec3 gpu_pr_ggxReflect(const GVec3& Fhalf, const GVec3& compFss, float roughness,
                                          float anisotropic, float anisoRotation,
                                          const GHitRecord& rec, const GVec3& wo, const GVec3& wi) {
    float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
    if (nl <= 0.f || nv <= 0.f) return GVec3(0.f);
    GVec3 h = (wo + wi).normalized();
    float D, G, roughComp;
    if (anisotropic <= 0.f) {  // PR-4a isotropic (bit-identical)
        float NdotH = fmaxf(rec.normal.dot(h), 1e-4f);
        float a = fmaxf(roughness * roughness, 0.0064f);
        // pkg182: eval D must EQUAL the NDF-sampling pdf's D (gpu_pr_pdfLobe:
        // gpu_pr_D_GTR2). The former a2/(π·denom²+1e-4) collapsed eval D ~1e4×
        // below the pdf D at low roughness → f/pdf→0 → metal/specular near-black.
        D = gpu_pr_D_GTR2(NdotH, a);
        G = gpu_pr_smithG2(nl, nv, a);  // height-correlated Smith (Cycles parity)
        roughComp = roughness;
    } else {  // PR-4b anisotropic (Cycles bsdf_aniso_D / bsdf_aniso_lambda)
        float ax, ay; gpu_pr_anisoAlphas(roughness, anisotropic, ax, ay);
        GVec3 X, Y; gpu_pr_anisoFrame(rec, anisoRotation, X, Y);
        GVec3 Hl(X.dot(h), Y.dot(h), fmaxf(rec.normal.dot(h), 1e-4f));
        GVec3 Il(X.dot(wi), Y.dot(wi), nl);
        GVec3 Ol(X.dot(wo), Y.dot(wo), nv);
        D = gpu_pr_ggxAnisoD(Hl, ax, ay, 1e-12f);  // pkg182: match aniso pdf reg
        G = gpu_pr_smithG2Aniso(Il, Ol, ax, ay);
        roughComp = sqrtf(sqrtf(ax * ay));
    }
    GVec3 single = Fhalf * (D * G / (4.f * nv + 1e-4f));
    return single * gpu_ggxCompensationFactor(compFss, roughComp, nv);
}
__device__ inline GSampledSpectrum gpu_pr_ggxReflectSpectral(const GSampledSpectrum& Fhalf,
                                                             const GSampledSpectrum& compFss, float roughness,
                                                             float anisotropic, float anisoRotation,
                                                             const GHitRecord& rec, const GVec3& wo, const GVec3& wi) {
    float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
    if (nl <= 0.f || nv <= 0.f) return GSampledSpectrum(0.f);
    GVec3 h = (wo + wi).normalized();
    float D, G, roughComp;
    if (anisotropic <= 0.f) {  // PR-4a isotropic (bit-identical)
        float NdotH = fmaxf(rec.normal.dot(h), 1e-4f);
        float a = fmaxf(roughness * roughness, 0.0064f);
        // pkg182: eval D == pdf D (gpu_pr_D_GTR2); see gpu_pr_ggxReflect rationale.
        D = gpu_pr_D_GTR2(NdotH, a);
        G = gpu_pr_smithG2(nl, nv, a);  // height-correlated Smith (Cycles parity)
        roughComp = roughness;
    } else {  // PR-4b anisotropic
        float ax, ay; gpu_pr_anisoAlphas(roughness, anisotropic, ax, ay);
        GVec3 X, Y; gpu_pr_anisoFrame(rec, anisoRotation, X, Y);
        GVec3 Hl(X.dot(h), Y.dot(h), fmaxf(rec.normal.dot(h), 1e-4f));
        GVec3 Il(X.dot(wi), Y.dot(wi), nl);
        GVec3 Ol(X.dot(wo), Y.dot(wo), nv);
        D = gpu_pr_ggxAnisoD(Hl, ax, ay, 1e-12f);  // pkg182: match aniso pdf reg
        G = gpu_pr_smithG2Aniso(Il, Ol, ax, ay);
        roughComp = sqrtf(sqrtf(ax * ay));
    }
    GSampledSpectrum single = Fhalf * (D * G / (4.f * nv + 1e-4f));
    if (!g_ggxE || !g_ggxEavg) return single;
    float E = fmaxf(gpu_ggxE(roughComp, nv), 1e-4f);
    float Eavg = fminf(fmaxf(gpu_ggxEavg(roughComp), 0.f), 0.999f);
    GSampledSpectrum out = single;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
        out[i] *= gpu_ggxDarkeningChannel(compFss[i], E, Eavg);
    return out;
}

// pkg178 Stage 4 PR-4 — isotropic GGX reflection whose eval D matches the pdf's D
// EXACTLY (both D_GTR2), for the thin-glass lobes only (iso). gpu_pr_ggxReflect
// above now shares the same D-consistency (pkg182 fixed its former +1e-4 eval
// regularizer, which had collapsed the metallic/specular lobes at low roughness).
// Twin of principled.cpp::ggxReflectConsistent; kept as the lean iso-only entry.
__device__ inline GVec3 gpu_pr_ggxReflectConsistent(const GVec3& Fhalf, const GVec3& compFss,
                                                    float roughness, const GHitRecord& rec,
                                                    const GVec3& wo, const GVec3& wi) {
    float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
    if (nl <= 0.f || nv <= 0.f) return GVec3(0.f);
    GVec3 h = (wo + wi).normalized();
    float NdotH = fmaxf(rec.normal.dot(h), 1e-4f);
    float a = fmaxf(roughness * roughness, 0.0064f);
    float D = gpu_pr_D_GTR2(NdotH, a);  // UNregularized — matches gpu_pr_pdfLobe
    float G = gpu_pr_smithG2(nl, nv, a);
    GVec3 single = Fhalf * (D * G / (4.f * nv + 1e-4f));
    return single * gpu_ggxCompensationFactor(compFss, roughness, nv);
}
__device__ inline GSampledSpectrum gpu_pr_ggxReflectConsistentSpectral(
        const GSampledSpectrum& Fhalf, const GSampledSpectrum& compFss, float roughness,
        const GHitRecord& rec, const GVec3& wo, const GVec3& wi) {
    float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
    if (nl <= 0.f || nv <= 0.f) return GSampledSpectrum(0.f);
    GVec3 h = (wo + wi).normalized();
    float NdotH = fmaxf(rec.normal.dot(h), 1e-4f);
    float a = fmaxf(roughness * roughness, 0.0064f);
    float D = gpu_pr_D_GTR2(NdotH, a);
    float G = gpu_pr_smithG2(nl, nv, a);
    GSampledSpectrum single = Fhalf * (D * G / (4.f * nv + 1e-4f));
    if (!g_ggxE || !g_ggxEavg) return single;
    float E = fmaxf(gpu_ggxE(roughness, nv), 1e-4f);
    float Eavg = fminf(fmaxf(gpu_ggxEavg(roughness), 0.f), 0.999f);
    GSampledSpectrum out = single;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
        out[i] *= gpu_ggxDarkeningChannel(compFss[i], E, Eavg);
    return out;
}

// --- pkg178 Stage 4 PR-4 thin-glass transmission lobe (mirrored GGX) --------
// Twin of principled.cpp thinGlassTransmitEvalRGB/Pdf. The double refraction
// through a thin sheet does not bend the ray → modeled as a GGX reflection whose
// peak is the straight-through direction −wo (mirror the light to the front
// hemisphere, then evaluate a standard GGX reflection about N). Constant white
// Fresnel; T' lives in the weight; reflection ggx_E energy tables (Cycles :1348).
__device__ inline GVec3 gpu_pr_thinGlassTransmitEval(const GPrincipledLobe& L, const GHitRecord& rec,
                                                     const GVec3& wo, const GVec3& wi) {
    if (L.isDelta) return GVec3(0.f);
    float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
    if (nv <= 0.f || nl >= 0.f) return GVec3(0.f);
    GVec3 wiM = wi - rec.normal * (2.f * nl);
    return L.weight * gpu_pr_ggxReflectConsistent(GVec3(1.f), GVec3(1.f), L.roughness, rec, wo, wiM);
}
__device__ inline GSampledSpectrum gpu_pr_thinGlassTransmitEvalSpectral(
        const GPrincipledLobe& L, const GHitRecord& rec, const GVec3& wo, const GVec3& wi,
        const GSampledWavelengths& wl) {
    if (L.isDelta) return GSampledSpectrum(0.f);
    float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
    if (nv <= 0.f || nl >= 0.f) return GSampledSpectrum(0.f);
    GVec3 wiM = wi - rec.normal * (2.f * nl);
    GSampledSpectrum wSpec = gpu_rgbToSampledSpectrum(L.weight, wl, GSPEC_RGB_ALBEDO);
    return wSpec * gpu_pr_ggxReflectConsistentSpectral(GSampledSpectrum(1.f), GSampledSpectrum(1.f),
                                                       L.roughness, rec, wo, wiM);
}
__device__ inline float gpu_pr_thinGlassTransmitPdf(const GPrincipledLobe& L, const GHitRecord& rec,
                                                    const GVec3& wo, const GVec3& wi) {
    if (L.isDelta) return 0.f;
    float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
    if (nv <= 0.f || nl >= 0.f) return 0.f;
    GVec3 wiM = wi - rec.normal * (2.f * nl);
    GVec3 h = (wo + wiM).normalized();
    float NdotH = rec.normal.dot(h), HdotV = h.dot(wo);
    if (NdotH <= 0.f || HdotV <= 0.f) return 0.f;
    float a = fmaxf(L.roughness * L.roughness, 0.0064f);
    return gpu_pr_D_GTR2(NdotH, a) * NdotH / (4.f * HdotV);
}

// --- Transmission rough glass (principled.cpp:406-488) ---------------------
__device__ inline GVec3 gpu_pr_transmissionEval(const GPrincipledClosure& c, const GPrincipledLobe& L,
                                                const GHitRecord& rec, const GVec3& wo, const GVec3& wi) {
    if (L.isDelta) return GVec3(0.f);  // delta handled in sampling
    float cosO = rec.normal.dot(wo), cosI = rec.normal.dot(wi);
    bool entering = rec.frontFace;
    float etaI = entering ? 1.f : L.ior, etaT = entering ? L.ior : 1.f;
    float alpha = fmaxf(L.roughness * L.roughness, 0.0064f);
    if (cosO > 0.f && cosI > 0.f) {  // reflection lobe (specular_tint)
        GVec3 wm = (wo + wi).normalized();
        if (wm.dot(rec.normal) < 0.f) wm = -wm;
        float HdotO = wo.dot(wm);
        if (HdotO <= 1e-10f) return GVec3(0.f);
        float D = gpu_pr_D_GTR2(wm.dot(rec.normal), alpha);
        // Height-correlated Smith G2 for the external-reflection sub-lobe (Cycles).
        float G = gpu_pr_smithG2(cosI, cosO, alpha);
        if (gpu_pr_filmActive(c)) {
            // pkg178 Stage 4 PR-3: thin-film iridescence F (Cycles single
            // microfacet_fresnel at bsdf->ior = etap; specular_tint folded into f0
            // via the F0-rescale, not a post-multiply).
            float etapR = entering ? L.ior : (1.f / L.ior);
            float filmIor = entering ? c.thinFilmIor : c.thinFilmIor / L.ior;
            GVec3 F = gpu_pr_thinFilmFresnelRGB(c, HdotO, etapR, filmIor);
            F = gpu_pr_thinFilmF0RescaleRGB(F, GVec3(gpu_pr_F0_from_ior(etapR)) * c.specularTint, etapR);
            float geom = D * G / (4.f * cosO * cosI + 1e-8f) * cosI;
            return L.weight * F * geom;
        }
        float F = gpu_pr_fresnelDielectric(HdotO, 1.f, L.ior);
        float fr = D * G * F / (4.f * cosO * cosI + 1e-8f) * cosI;
        return L.weight * c.specularTint * fr;
    }
    if (cosO * cosI >= 0.f) return GVec3(0.f);
    float etap = entering ? L.ior : (1.f / L.ior);
    GVec3 wm = (wi * etap + wo).normalized();
    if (wm.dot(rec.normal) < 0.f) wm = -wm;
    if (wm.dot(wi) * cosI < 0.f || wm.dot(wo) * cosO < 0.f) return GVec3(0.f);
    float D = gpu_pr_D_GTR2(fabsf(wm.dot(rec.normal)), alpha);
    // Height-correlated Smith G2 for the refraction sub-lobe (Cycles parity).
    float G = gpu_pr_smithG2(fabsf(cosI), fabsf(cosO), alpha);
    if (gpu_pr_filmActive(c)) {
        // pkg178 Stage 4 PR-3: transmittance = (1-F)·transmission_tint with the
        // same iridescence F; film IOR backface-adjusted (÷bulk IOR).
        float filmIor = entering ? c.thinFilmIor : c.thinFilmIor / L.ior;
        GVec3 Fv = gpu_pr_thinFilmFresnelRGB(c, fabsf(wo.dot(wm)), etap, filmIor);
        Fv = gpu_pr_thinFilmF0RescaleRGB(Fv, GVec3(gpu_pr_F0_from_ior(etap)) * c.specularTint, etap);
        float den = wi.dot(wm) + wo.dot(wm) / etap;
        den = den * den * cosI * cosO;
        float ft = D * G * fabsf(wi.dot(wm) * wo.dot(wm) / (den + 1e-10f));
        ft /= (etap * etap);
        float scale = ft * fabsf(cosI) * gpu_ggxGlassCompensationFactor(L.roughness, etap, fabsf(cosO));
        GVec3 res = L.weight * gpu_pr_sqrtColor(c.color) * (GVec3(1.f) - Fv) * scale;
        return gvec3_max(res, GVec3(0.f));
    }
    float F = gpu_pr_fresnelDielectric(fabsf(wo.dot(wm)), etaI, etaT);
    float den = wi.dot(wm) + wo.dot(wm) / etap;
    den = den * den * cosI * cosO;
    float ft = D * (1.f - F) * G * fabsf(wi.dot(wm) * wo.dot(wm) / (den + 1e-10f));
    ft /= (etap * etap);
    float scale = ft * fabsf(cosI) * gpu_ggxGlassCompensationFactor(L.roughness, etap, fabsf(cosO));
    GVec3 res = L.weight * gpu_pr_sqrtColor(c.color) * scale;
    return gvec3_max(res, GVec3(0.f));
}
__device__ inline float gpu_pr_transmissionPdf(const GPrincipledLobe& L, const GHitRecord& rec,
                                               const GVec3& wo, const GVec3& wi) {
    float cosO = rec.normal.dot(wo), cosI = rec.normal.dot(wi);
    bool entering = rec.frontFace;
    float etaI = entering ? 1.f : L.ior, etaT = entering ? L.ior : 1.f;
    if (cosO > 0.f && cosI > 0.f) {  // reflection
        GVec3 wm = (wo + wi).normalized();
        if (wm.dot(rec.normal) < 0.f) wm = -wm;
        float HdotO = fabsf(wo.dot(wm));
        if (HdotO <= 1e-10f) return 0.f;
        float F = gpu_pr_fresnelDielectric(HdotO, etaI, etaT);
        return F * gpu_pr_vndfPdf(rec.normal, wo, wm, L.roughness) / (4.f * HdotO);
    }
    if (cosO * cosI >= 0.f) return 0.f;  // transmission
    float etap = entering ? L.ior : (1.f / L.ior);
    GVec3 wm = (wi * etap + wo).normalized();
    if (wm.dot(rec.normal) < 0.f) wm = -wm;
    float HdotO = wo.dot(wm), HdotI = wi.dot(wm);
    if (HdotO * HdotI >= 0.f) return 0.f;
    float d = HdotI + HdotO / etap;
    float d2 = d * d;
    if (d2 <= 1e-10f) return 0.f;
    float F = gpu_pr_fresnelDielectric(fabsf(HdotO), etaI, etaT);
    return (1.f - F) * gpu_pr_vndfPdf(rec.normal, wo, wm, L.roughness) * fabsf(HdotI) / d2;
}

// pkg178 Stage 4 PR-3 — per-λ native thin-film glass eval (film ONLY; the film-
// free spectral path stays the Stage-3b upsample-of-RGB in gpu_pr_evalLobeSpectral).
// Achromatic geometry × per-λ iridescence F (both faces; backface film-IOR adjust
// ÷ bulk IOR). Exact mirror of principled.cpp::transmissionEvalSpectral.
__device__ inline GSampledSpectrum gpu_pr_transmissionEvalSpectral(
        const GPrincipledClosure& c, const GPrincipledLobe& L, const GHitRecord& rec,
        const GVec3& wo, const GVec3& wi, const GSampledWavelengths& wl) {
    if (L.isDelta) return GSampledSpectrum(0.f);
    float cosO = rec.normal.dot(wo), cosI = rec.normal.dot(wi);
    bool entering = rec.frontFace;
    float alpha = fmaxf(L.roughness * L.roughness, 0.0064f);
    float etap = entering ? L.ior : (1.f / L.ior);
    float filmIor = entering ? c.thinFilmIor : c.thinFilmIor / L.ior;
    float F0real = gpu_pr_F0_from_ior(etap);
    GSampledSpectrum wSpec = gpu_rgbToSampledSpectrum(L.weight, wl, GSPEC_RGB_ALBEDO);
    GSampledSpectrum tintSpec = gpu_rgbToSampledSpectrum(c.specularTint, wl, GSPEC_RGB_ALBEDO);
    if (cosO > 0.f && cosI > 0.f) {  // reflection sub-lobe
        GVec3 wm = (wo + wi).normalized();
        if (wm.dot(rec.normal) < 0.f) wm = -wm;
        float HdotO = wo.dot(wm);
        if (HdotO <= 1e-10f) return GSampledSpectrum(0.f);
        float D = gpu_pr_D_GTR2(wm.dot(rec.normal), alpha);
        float G = gpu_pr_smithG2(cosI, cosO, alpha);
        float geom = D * G / (4.f * cosO * cosI + 1e-8f) * cosI;
        GSampledSpectrum F = gpu_pr_thinFilmFresnelSpectral(c, HdotO, etap, filmIor, wl);
        GSampledSpectrum out(0.f);
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
            float Fi = (F0real > 1e-5f)
                           ? gpu_pr_thinFilmF0RescaleChannel(F[i], F0real * tintSpec[i], F0real)
                           : F[i];
            out[i] = wSpec[i] * Fi * geom;
        }
        return out;
    }
    if (cosO * cosI >= 0.f) return GSampledSpectrum(0.f);
    // transmission sub-lobe
    GVec3 wm = (wi * etap + wo).normalized();
    if (wm.dot(rec.normal) < 0.f) wm = -wm;
    if (wm.dot(wi) * cosI < 0.f || wm.dot(wo) * cosO < 0.f) return GSampledSpectrum(0.f);
    float D = gpu_pr_D_GTR2(fabsf(wm.dot(rec.normal)), alpha);
    float G = gpu_pr_smithG2(fabsf(cosI), fabsf(cosO), alpha);
    float den = wi.dot(wm) + wo.dot(wm) / etap;
    den = den * den * cosI * cosO;
    float ft = D * G * fabsf(wi.dot(wm) * wo.dot(wm) / (den + 1e-10f));
    ft /= (etap * etap);
    float scale = ft * fabsf(cosI) * gpu_ggxGlassCompensationFactor(L.roughness, etap, fabsf(cosO));
    GSampledSpectrum F = gpu_pr_thinFilmFresnelSpectral(c, fabsf(wo.dot(wm)), etap, filmIor, wl);
    GSampledSpectrum baseSpec = gpu_rgbToSampledSpectrum(gpu_pr_sqrtColor(c.color), wl, GSPEC_RGB_ALBEDO);
    GSampledSpectrum out(0.f);
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
        float Fi = (F0real > 1e-5f)
                       ? gpu_pr_thinFilmF0RescaleChannel(F[i], F0real * tintSpec[i], F0real)
                       : F[i];
        float v = wSpec[i] * baseSpec[i] * (1.f - Fi) * scale;
        out[i] = v > 0.f ? v : 0.f;
    }
    return out;
}

// --- Per-lobe eval / pdf (principled.cpp:355-461) --------------------------
__device__ inline GVec3 gpu_pr_evalLobe(const GPrincipledClosure& c, const GPrincipledLobe& L,
                                        const GHitRecord& rec, const GVec3& wo, const GVec3& wi) {
    float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
    switch (L.kind) {
        case GPR_SUBSURFACE:  // approximate SSS = Lambert (D2=a)
        case GPR_DIFFUSE: {
            if (nl <= 0.f || nv <= 0.f) return GVec3(0.f);
            if (L.roughness <= 1e-4f) return L.weight * (nl / M_PI_F);  // Lambert
            GPrincipledEON e = gpu_pr_eonSetup(fminf(fmaxf(L.roughness, 0.f), 1.f), nl, nv, wi.dot(wo));
            return GVec3(L.weight.x * gpu_pr_eonChannel(e, L.color.x),
                         L.weight.y * gpu_pr_eonChannel(e, L.color.y),
                         L.weight.z * gpu_pr_eonChannel(e, L.color.z));
        }
        case GPR_SHEEN: {  // Cycles bsdf_sheen_eval
            if (nl <= 0.f || nv <= 0.f) return GVec3(0.f);
            GVec3 T, B;
            gpu_pr_sheenFrame(rec.normal, wo, T, B);
            GVec3 localO(wi.dot(T), wi.dot(B), wi.dot(rec.normal));
            return L.weight * gpu_pr_sheenValue(L.sheenA, L.sheenB, localO);
        }
        case GPR_COAT:      // clear GGX dielectric — same eval as specular
        case GPR_SPECULAR: {
            if (nl <= 0.f || nv <= 0.f) return GVec3(0.f);
            GVec3 h = (wo + wi).normalized();
            // Film-OFF statements FIRST, textually unchanged (byte-identical
            // codegen + thickness-0 render); the film only OVERRIDES F afterward.
            float sHalf = gpu_pr_generalizedSchlickS(fabsf(wo.dot(h)), L.ior);
            GVec3 F = L.color + (GVec3(1.f) - L.color) * sHalf;
            if (L.kind == GPR_SPECULAR && gpu_pr_filmActive(c)) {
                // pkg178 Stage 4 PR-3: thin-film iridescence replaces the single-
                // scatter Fresnel (Cycles generalized_schlick_fresnel thin-film
                // branch). compFss stays FILM-FREE (L.color = specF0).
                GVec3 Fraw = gpu_pr_thinFilmFresnelRGB(c, fabsf(wo.dot(h)), L.ior, c.thinFilmIor);
                F = gpu_pr_thinFilmF0RescaleRGB(Fraw, L.color, L.ior);
            }
            return L.weight * gpu_pr_ggxReflect(F, L.color, L.roughness,
                                                L.anisotropic, L.anisoRotation, rec, wo, wi);
        }
        case GPR_METALLIC: {
            if (nl <= 0.f || nv <= 0.f) return GVec3(0.f);
            GVec3 h = (wo + wi).normalized();
            float ci = fminf(fmaxf(wo.dot(h), 0.f), 1.f);
            // Film-OFF statements FIRST, textually unchanged (thickness-0 bit-
            // equality); the film only OVERRIDES F.
            GVec3 F(gpu_pr_f82Channel(ci, L.color.x, c.specularTint.x),
                    gpu_pr_f82Channel(ci, L.color.y, c.specularTint.y),
                    gpu_pr_f82Channel(ci, L.color.z, c.specularTint.z));
            if (gpu_pr_filmActive(c)) {
                // pkg178 Stage 4 PR-3: thin-film iridescence over the conductor
                // substrate replaces the single-scatter F82. compFss (L.color)
                // stays FILM-FREE.
                F = gpu_pr_thinFilmConductorRGB(c, ci);
            }
            return L.weight * gpu_pr_ggxReflect(F, L.color, L.roughness,
                                                L.anisotropic, L.anisoRotation, rec, wo, wi);
        }
        case GPR_TRANSMISSION:
            return gpu_pr_transmissionEval(c, L, rec, wo, wi);
        case GPR_THINGLASS_REFLECT: {  // GGX reflection, constant F=R' (in weight)
            if (nl <= 0.f || nv <= 0.f) return GVec3(0.f);
            return L.weight * gpu_pr_ggxReflectConsistent(GVec3(1.f), L.color, L.roughness, rec, wo, wi);
        }
        case GPR_THINGLASS_TRANSMIT:
            return gpu_pr_thinGlassTransmitEval(L, rec, wo, wi);
        case GPR_TRANSLUCENT: {  // back-hemisphere diffuse (thin subsurface)
            if (nl >= 0.f || nv <= 0.f) return GVec3(0.f);
            if (L.roughness <= 1e-4f) return L.weight * (-nl / M_PI_F);  // Lambert
            GVec3 wiM = wi - rec.normal * (2.f * nl);
            GPrincipledEON e = gpu_pr_eonSetup(fminf(fmaxf(L.roughness, 0.f), 1.f), -nl, nv, wiM.dot(wo));
            return GVec3(L.weight.x * gpu_pr_eonChannel(e, L.color.x),
                         L.weight.y * gpu_pr_eonChannel(e, L.color.y),
                         L.weight.z * gpu_pr_eonChannel(e, L.color.z));
        }
    }
    return GVec3(0.f);
}
__device__ inline float gpu_pr_pdfLobe(const GPrincipledLobe& L, const GHitRecord& rec,
                                       const GVec3& wo, const GVec3& wi) {
    float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
    switch (L.kind) {
        case GPR_SUBSURFACE:
        case GPR_DIFFUSE:
            return (nl > 0.f && nv > 0.f) ? nl / M_PI_F : 0.f;
        case GPR_SHEEN: {  // Cycles bsdf_sheen_sample: *pdf = val
            if (nl <= 0.f || nv <= 0.f) return 0.f;
            GVec3 T, B;
            gpu_pr_sheenFrame(rec.normal, wo, T, B);
            GVec3 localO(wi.dot(T), wi.dot(B), wi.dot(rec.normal));
            return gpu_pr_sheenValue(L.sheenA, L.sheenB, localO);
        }
        case GPR_COAT:
        case GPR_SPECULAR:
        case GPR_METALLIC: {
            if (nl <= 0.f || nv <= 0.f) return 0.f;
            GVec3 h = (wo + wi).normalized();
            float NdotH = rec.normal.dot(h), HdotV = h.dot(wo);
            if (NdotH <= 0.f || HdotV <= 0.f) return 0.f;
            if (L.anisotropic <= 0.f) {
                float a = fmaxf(L.roughness * L.roughness, 0.0064f);
                return gpu_pr_D_GTR2(NdotH, a) * NdotH / (4.f * HdotV);
            }
            float ax, ay; gpu_pr_anisoAlphas(L.roughness, L.anisotropic, ax, ay);  // PR-4b
            GVec3 X, Y; gpu_pr_anisoFrame(rec, L.anisoRotation, X, Y);
            GVec3 Hl(X.dot(h), Y.dot(h), NdotH);
            return gpu_pr_ggxAnisoD(Hl, ax, ay, 1e-12f) * NdotH / (4.f * HdotV);
        }
        case GPR_TRANSMISSION:
            return L.isDelta ? 0.f : gpu_pr_transmissionPdf(L, rec, wo, wi);
        case GPR_THINGLASS_REFLECT: {  // iso GGX NDF pdf
            if (nl <= 0.f || nv <= 0.f) return 0.f;
            GVec3 h = (wo + wi).normalized();
            float NdotH = rec.normal.dot(h), HdotV = h.dot(wo);
            if (NdotH <= 0.f || HdotV <= 0.f) return 0.f;
            float a = fmaxf(L.roughness * L.roughness, 0.0064f);
            return gpu_pr_D_GTR2(NdotH, a) * NdotH / (4.f * HdotV);
        }
        case GPR_THINGLASS_TRANSMIT:
            return gpu_pr_thinGlassTransmitPdf(L, rec, wo, wi);
        case GPR_TRANSLUCENT:  // back-hemisphere cosine
            return (nl < 0.f && nv > 0.f) ? -nl / M_PI_F : 0.f;
    }
    return 0.f;
}
__device__ inline GSampledSpectrum gpu_pr_evalLobeSpectral(const GPrincipledClosure& c, const GPrincipledLobe& L,
                                                           const GHitRecord& rec, const GVec3& wo, const GVec3& wi,
                                                           const GSampledWavelengths& wl) {
    float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
    GSampledSpectrum wSpec = gpu_rgbToSampledSpectrum(L.weight, wl, GSPEC_RGB_ALBEDO);
    switch (L.kind) {
        case GPR_SUBSURFACE:  // approximate SSS = Lambert (D2=a)
        case GPR_DIFFUSE: {
            if (nl <= 0.f || nv <= 0.f) return GSampledSpectrum(0.f);
            if (L.roughness <= 1e-4f) return wSpec * (nl / M_PI_F);  // Lambert
            GPrincipledEON e = gpu_pr_eonSetup(fminf(fmaxf(L.roughness, 0.f), 1.f), nl, nv, wi.dot(wo));
            GSampledSpectrum cSpec = gpu_rgbToSampledSpectrum(L.color, wl, GSPEC_RGB_ALBEDO);
            GSampledSpectrum out(0.f);
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
                out[i] = wSpec[i] * gpu_pr_eonChannel(e, cSpec[i]);
            return out;
        }
        case GPR_SHEEN: {  // achromatic LTC scalar; tinted weight upsampled
            if (nl <= 0.f || nv <= 0.f) return GSampledSpectrum(0.f);
            GVec3 T, B;
            gpu_pr_sheenFrame(rec.normal, wo, T, B);
            GVec3 localO(wi.dot(T), wi.dot(B), wi.dot(rec.normal));
            return wSpec * gpu_pr_sheenValue(L.sheenA, L.sheenB, localO);
        }
        case GPR_COAT:      // clear GGX dielectric — same spectral eval
        case GPR_SPECULAR: {
            if (nl <= 0.f || nv <= 0.f) return GSampledSpectrum(0.f);
            GVec3 h = (wo + wi).normalized();
            // Film-OFF statements FIRST, textually unchanged; the film only OVERRIDES F.
            float sHalf = gpu_pr_generalizedSchlickS(fabsf(wo.dot(h)), L.ior);
            GSampledSpectrum f0 = gpu_rgbToSampledSpectrum(L.color, wl, GSPEC_RGB_ALBEDO);
            GSampledSpectrum F = f0 + (GSampledSpectrum(1.f) - f0) * sHalf;
            if (L.kind == GPR_SPECULAR && gpu_pr_filmActive(c)) {
                // pkg178 Stage 4 PR-3: per-λ native thin-film iridescence (analytic
                // sensitivity, no LUT). compFss (f0) stays film-free.
                F = gpu_pr_thinFilmFresnelSpectral(c, fabsf(wo.dot(h)), L.ior, c.thinFilmIor, wl);
                float F0real = gpu_pr_F0_from_ior(L.ior);
                if (F0real > 1e-5f)
                    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
                        F[i] = gpu_pr_thinFilmF0RescaleChannel(F[i], f0[i], F0real);
            }
            return wSpec * gpu_pr_ggxReflectSpectral(F, f0, L.roughness,
                                                     L.anisotropic, L.anisoRotation, rec, wo, wi);
        }
        case GPR_METALLIC: {
            if (nl <= 0.f || nv <= 0.f) return GSampledSpectrum(0.f);
            GVec3 h = (wo + wi).normalized();
            float ci = fminf(fmaxf(wo.dot(h), 0.f), 1.f);
            GSampledSpectrum f0 = gpu_rgbToSampledSpectrum(L.color, wl, GSPEC_RGB_ALBEDO);
            // Film-OFF statements FIRST, textually unchanged; the film only OVERRIDES F.
            GSampledSpectrum tint = gpu_rgbToSampledSpectrum(c.specularTint, wl, GSPEC_RGB_ALBEDO);
            GSampledSpectrum F(0.f);
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
                F[i] = gpu_pr_f82Channel(ci, f0[i], tint[i]);
            if (gpu_pr_filmActive(c)) {
                // pkg178 Stage 4 PR-3: conductor thin-film F (RGB-channel n,k
                // upsampled — plan §0.5 APPROXIMATED-equal-to-Cycles). compFss
                // (f0) stays film-free.
                F = gpu_pr_thinFilmConductorSpectral(c, ci, wl);
            }
            return wSpec * gpu_pr_ggxReflectSpectral(F, f0, L.roughness,
                                                     L.anisotropic, L.anisoRotation, rec, wo, wi);
        }
        case GPR_TRANSMISSION: {
            // pkg178 Stage 4 PR-3: with the film ON, evaluate F per-λ natively
            // (pkg163 discipline); OFF path is the exact Stage-3b upsample hack.
            if (gpu_pr_filmActive(c)) return gpu_pr_transmissionEvalSpectral(c, L, rec, wo, wi, wl);
            // Colour upsampled; achromatic geometry/Fresnel scalar per-λ (principled.cpp:664-672).
            GVec3 rgb = gpu_pr_transmissionEval(c, L, rec, wo, wi);
            if (rgb.x <= 0.f && rgb.y <= 0.f && rgb.z <= 0.f) return GSampledSpectrum(0.f);
            float maxc = fmaxf(fmaxf(fmaxf(rgb.x, rgb.y), rgb.z), 1.f);
            GVec3 tint = rgb * (1.f / maxc);
            return gpu_rgbToSampledSpectrum(tint, wl, GSPEC_RGB_ALBEDO) * maxc;
        }
        case GPR_THINGLASS_REFLECT: {  // GGX reflection, constant F=R' (in weight)
            if (nl <= 0.f || nv <= 0.f) return GSampledSpectrum(0.f);
            GSampledSpectrum comp = gpu_rgbToSampledSpectrum(L.color, wl, GSPEC_RGB_ALBEDO);
            return wSpec * gpu_pr_ggxReflectConsistentSpectral(GSampledSpectrum(1.f), comp,
                                                               L.roughness, rec, wo, wi);
        }
        case GPR_THINGLASS_TRANSMIT:
            return gpu_pr_thinGlassTransmitEvalSpectral(L, rec, wo, wi, wl);
        case GPR_TRANSLUCENT: {  // back-hemisphere diffuse (thin subsurface)
            if (nl >= 0.f || nv <= 0.f) return GSampledSpectrum(0.f);
            if (L.roughness <= 1e-4f) return wSpec * (-nl / M_PI_F);  // Lambert
            GVec3 wiM = wi - rec.normal * (2.f * nl);
            GPrincipledEON e = gpu_pr_eonSetup(fminf(fmaxf(L.roughness, 0.f), 1.f), -nl, nv, wiM.dot(wo));
            GSampledSpectrum cSpec = gpu_rgbToSampledSpectrum(L.color, wl, GSPEC_RGB_ALBEDO);
            GSampledSpectrum out(0.f);
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
                out[i] = wSpec[i] * gpu_pr_eonChannel(e, cSpec[i]);
            return out;
        }
    }
    return GSampledSpectrum(0.f);
}

// --- Mixture eval / pdf / spectral eval (principled.cpp:611-709) -----------
__device__ inline GVec3 gpu_principled_eval(const GPrincipledClosure& c, const GHitRecord& rec,
                                            const GVec3& wo, const GVec3& wi) {
    GPrincipledLobe lobes[kMaxPrincipledLobes];
    int n = gpu_pr_assembleLobes(c, rec, wo, lobes);
    GVec3 sum(0.f);
    for (int i = 0; i < n; ++i)
        if (!lobes[i].isDelta) sum += gpu_pr_evalLobe(c, lobes[i], rec, wo, wi);
    return gvec3_max(sum, GVec3(0.f));
}
__device__ inline float gpu_principled_pdf(const GPrincipledClosure& c, const GHitRecord& rec,
                                           const GVec3& wo, const GVec3& wi) {
    GPrincipledLobe lobes[kMaxPrincipledLobes];
    int n = gpu_pr_assembleLobes(c, rec, wo, lobes);
    float W = 0.f;
    for (int i = 0; i < n; ++i) W += lobes[i].sel;
    if (W <= 0.f) return 0.f;
    float p = 0.f;
    for (int i = 0; i < n; ++i)
        if (!lobes[i].isDelta) p += (lobes[i].sel / W) * gpu_pr_pdfLobe(lobes[i], rec, wo, wi);
    return p;
}
__device__ inline GSampledSpectrum gpu_principled_eval_spectral(const GPrincipledClosure& c, const GHitRecord& rec,
                                                                const GVec3& wo, const GVec3& wi,
                                                                const GSampledWavelengths& wl) {
    GPrincipledLobe lobes[kMaxPrincipledLobes];
    int n = gpu_pr_assembleLobes(c, rec, wo, lobes);
    GSampledSpectrum sum(0.f);
    for (int i = 0; i < n; ++i)
        if (!lobes[i].isDelta) sum += gpu_pr_evalLobeSpectral(c, lobes[i], rec, wo, wi, wl);
    return sum;
}

// --- Direction sampling + BSDF sample (principled.cpp:493-576,711-776) ------
struct GPrincipledDir {
    bool  ok;
    GVec3 wi;
    bool  isDelta;
    int   lobe;
    float pdfInternal;
    bool  deltaRefract;
    float eta;
};
template <typename TRng>
__device__ inline GPrincipledDir gpu_pr_chooseAndSampleDir(const GHitRecord& rec, const GVec3& wo,
                                                           TRng* rng, const GPrincipledLobe lobes[kMaxPrincipledLobes],
                                                           int n, float W) {
    GPrincipledDir ds;
    ds.ok = false; ds.wi = GVec3(0, 1, 0); ds.isDelta = false; ds.lobe = -1;
    ds.pdfInternal = 1.f; ds.deltaRefract = false; ds.eta = 1.f;
    float xi = gpu_rng_uniform(rng) * W, acc = 0.f;
    int j = n - 1;
    for (int i = 0; i < n; ++i) { acc += lobes[i].sel; if (xi <= acc) { j = i; break; } }
    ds.lobe = j;
    const GPrincipledLobe& L = lobes[j];
    // Transparent (alpha) — Cycles bsdf_transparent.h: wo = -wi, delta, matched
    // pdf==eval → pdfInternal=1, eta=1 (no medium change). Zero rng draws (CPU/GPU
    // aligned). Mirrors principled.cpp chooseAndSampleDir.
    if (L.kind == GPR_TRANSPARENT) {
        ds.wi = -wo;
        ds.isDelta = true;
        ds.pdfInternal = 1.f;
        ds.deltaRefract = false;
        ds.eta = 1.f;
        ds.ok = true;
        return ds;
    }
    if (L.kind == GPR_DIFFUSE || L.kind == GPR_SUBSURFACE) {
        GVec3 local = gpu_randomCosineDir(rng);
        ds.wi = rec.tangent * local.x + rec.bitangent * local.y + rec.normal * local.z;
        ds.ok = rec.normal.dot(ds.wi) > 0.f;
        return ds;
    }
    if (L.kind == GPR_SHEEN) {  // Cycles bsdf_sheen_sample (disk -> LTC)
        float u1 = gpu_rng_uniform(rng), u2 = gpu_rng_uniform(rng);
        float r = sqrtf(u1), phi = 2.f * M_PI_F * u2;
        float dx = r * cosf(phi), dy = r * sinf(phi);
        float diskZ = sqrtf(fmaxf(0.f, 1.f - dx * dx - dy * dy));
        GVec3 localO = GVec3(dx - diskZ * L.sheenB, dy, diskZ * L.sheenA).normalized();
        GVec3 T, B;
        gpu_pr_sheenFrame(rec.normal, wo, T, B);
        ds.wi = (T * localO.x + B * localO.y + rec.normal * localO.z).normalized();
        ds.ok = rec.normal.dot(ds.wi) > 0.f;
        return ds;
    }
    if (L.kind == GPR_SPECULAR || L.kind == GPR_METALLIC || L.kind == GPR_COAT) {
        float r1 = gpu_rng_uniform(rng), r2 = gpu_rng_uniform(rng);  // 2 draws both branches
        float phi = 2.f * M_PI_F * r1;
        if (L.anisotropic <= 0.f) {
            float a = fmaxf(L.roughness * L.roughness, 0.0064f);
            float cosT = sqrtf((1.f - r2) / (1.f + (a * a - 1.f) * r2));
            float sinT = sqrtf(fmaxf(0.f, 1.f - cosT * cosT));
            GVec3 hh(cosf(phi) * sinT, sinf(phi) * sinT, cosT);
            hh = rec.tangent * hh.x + rec.bitangent * hh.y + rec.normal * hh.z;
            ds.wi = (hh * (2.f * wo.dot(hh)) - wo).normalized();
            ds.ok = rec.normal.dot(ds.wi) > 0.f;
            return ds;
        }
        // PR-4b anisotropic NDF half-vector via slope stretch (reduces to iso).
        float ax, ay; gpu_pr_anisoAlphas(L.roughness, L.anisotropic, ax, ay);
        GVec3 X, Y; gpu_pr_anisoFrame(rec, L.anisoRotation, X, Y);
        float rr = sqrtf(r2 / fmaxf(1.f - r2, 1e-6f));
        float sx = ax * rr * cosf(phi);
        float sy = ay * rr * sinf(phi);
        GVec3 hl = GVec3(-sx, -sy, 1.f).normalized();
        GVec3 hh = X * hl.x + Y * hl.y + rec.normal * hl.z;
        ds.wi = (hh * (2.f * wo.dot(hh)) - wo).normalized();
        ds.ok = rec.normal.dot(ds.wi) > 0.f;
        return ds;
    }
    if (L.kind == GPR_TRANSLUCENT) {  // cosine on the BACK hemisphere (-N)
        GVec3 local = gpu_randomCosineDir(rng);
        ds.wi = rec.tangent * local.x + rec.bitangent * local.y - rec.normal * local.z;
        ds.ok = rec.normal.dot(ds.wi) < 0.f;
        return ds;
    }
    if (L.kind == GPR_THINGLASS_REFLECT) {  // iso GGX half-vector (like Specular)
        float r1 = gpu_rng_uniform(rng), r2 = gpu_rng_uniform(rng);
        float phi = 2.f * M_PI_F * r1;
        float a = fmaxf(L.roughness * L.roughness, 0.0064f);
        float cosT = sqrtf((1.f - r2) / (1.f + (a * a - 1.f) * r2));
        float sinT = sqrtf(fmaxf(0.f, 1.f - cosT * cosT));
        GVec3 hh(cosf(phi) * sinT, sinf(phi) * sinT, cosT);
        hh = rec.tangent * hh.x + rec.bitangent * hh.y + rec.normal * hh.z;
        ds.wi = (hh * (2.f * wo.dot(hh)) - wo).normalized();
        ds.ok = rec.normal.dot(ds.wi) > 0.f;
        return ds;
    }
    if (L.kind == GPR_THINGLASS_TRANSMIT) {
        if (L.isDelta) {  // near-specular sheet → straight-through passthrough (wo=-wi)
            ds.wi = -wo;
            ds.isDelta = true; ds.pdfInternal = 1.f; ds.deltaRefract = false; ds.eta = 1.f;
            ds.ok = true;
            return ds;
        }
        float r1 = gpu_rng_uniform(rng), r2 = gpu_rng_uniform(rng);
        float phi = 2.f * M_PI_F * r1;
        float a = fmaxf(L.roughness * L.roughness, 0.0064f);
        float cosT = sqrtf((1.f - r2) / (1.f + (a * a - 1.f) * r2));
        float sinT = sqrtf(fmaxf(0.f, 1.f - cosT * cosT));
        GVec3 hh(cosf(phi) * sinT, sinf(phi) * sinT, cosT);
        hh = rec.tangent * hh.x + rec.bitangent * hh.y + rec.normal * hh.z;
        GVec3 wiM = (hh * (2.f * wo.dot(hh)) - wo).normalized();  // front-hemisphere reflect
        float m = rec.normal.dot(wiM);
        ds.wi = (wiM - rec.normal * (2.f * m)).normalized();      // mirror to back
        ds.ok = rec.normal.dot(ds.wi) < 0.f;
        return ds;
    }
    // Transmission
    float etaI = rec.frontFace ? 1.f : L.ior;
    float etaT = rec.frontFace ? L.ior : 1.f;
    float eta = etaI / etaT;
    ds.eta = eta;
    GVec3 nn = rec.normal;
    float cosTheta = wo.dot(nn);
    if (cosTheta < 0.f) { cosTheta = -cosTheta; nn = -nn; }
    float sinT = sqrtf(fmaxf(0.f, 1.f - cosTheta * cosTheta));
    bool cannotRefract = eta * sinT > 1.f;
    if (!L.isDelta) {
        GVec3 wm = gpu_pr_sampleGgxVNDF(rec, wo, L.roughness, rng);
        float HdotO = wo.dot(wm);
        float F = gpu_pr_fresnelDielectric(fabsf(HdotO), etaI, etaT);
        bool refl = cannotRefract || gpu_rng_uniform(rng) < F;
        if (refl) {
            ds.wi = (wm * (2.f * HdotO) - wo).normalized();
            ds.ok = ds.wi.dot(rec.normal) * wo.dot(rec.normal) > 0.f;
        } else {
            ds.ok = gpu_pr_refractMicro(wo, wm, eta, ds.wi);
        }
        ds.isDelta = false;
        return ds;
    }
    // delta (smooth) glass
    float f0 = (etaI - etaT) / (etaI + etaT);
    f0 = f0 * f0;
    float fresnel = f0 + (1.f - f0) * powf(fminf(fmaxf(1.f - cosTheta, 0.f), 1.f), 5.f);
    ds.isDelta = true;
    if (cannotRefract || gpu_rng_uniform(rng) < fresnel) {
        ds.wi = nn * (2.f * wo.dot(nn)) - wo;
        ds.deltaRefract = false;
        ds.pdfInternal = cannotRefract ? 1.f : fresnel;
    } else {
        GVec3 perp = (wo - nn * cosTheta) * (-eta);
        GVec3 para = nn * (-sqrtf(fabsf(1.f - perp.length2())));
        ds.wi = (perp + para).normalized();
        ds.deltaRefract = true;
        ds.pdfInternal = 1.f - fresnel;
    }
    ds.ok = true;
    return ds;
}
template <typename TRng>
__device__ inline GBSDFSample gpu_principled_sample(const GPrincipledClosure& c, GHitRecord& rec,
                                                    const GVec3& wo, TRng* rng) {
    GBSDFSample s;
    s.wi = rec.normal; s.f = GVec3(0.f); s.fSpectral = GSampledSpectrum(0.f); s.pdf = 0.f; s.isDelta = false;
    GPrincipledLobe lobes[kMaxPrincipledLobes];
    int n = gpu_pr_assembleLobes(c, rec, wo, lobes);
    float W = 0.f;
    for (int i = 0; i < n; ++i) W += lobes[i].sel;
    if (W <= 0.f) return s;
    GPrincipledDir ds = gpu_pr_chooseAndSampleDir(rec, wo, rng, lobes, n, W);
    if (!ds.ok) return s;
    s.wi = ds.wi;
    if (ds.isDelta) {
        const GPrincipledLobe& L = lobes[ds.lobe];
        float qj = L.sel / W;
        if (L.kind == GPR_TRANSPARENT || L.kind == GPR_THINGLASS_TRANSMIT)
            // Straight-through: f = weight (weight_T carries T' for thin glass),
            // pdf = qj → f/pdf = weight/qj (Cycles bsdf_transparent.h /
            // bsdf_thin_glass_transmission_sample passthrough; W cancels).
            s.f = L.weight;
        else if (ds.deltaRefract)
            s.f = L.weight * gpu_pr_sqrtColor(c.color) * (ds.eta * ds.eta * ds.pdfInternal);
        else
            s.f = L.weight * c.specularTint * ds.pdfInternal;
        s.pdf = qj * ds.pdfInternal;
        s.isDelta = true;
        rec.isDelta = true;
    } else {
        // one-sample-MIS mixture: overwrite f/pdf with the full mixture at s.wi,
        // exactly as PrincipledPlugin::sample does (principled.cpp:736-738).
        s.f = gpu_principled_eval(c, rec, wo, s.wi);
        s.pdf = gpu_principled_pdf(c, rec, wo, s.wi);
        s.isDelta = false;
    }
    return s;
}

// A principled material lowers to a single-closure graph whose sole closure is
// GCLOSURE_PRINCIPLED (index 0). Used by the graph dispatch + the spectral
// wrappers to route to the monolithic twin above.
__device__ inline bool gpu_closure_graph_is_principled(const GMaterial& mat) {
    return mat.closureCount >= 1 && mat.closures[0].type == GCLOSURE_PRINCIPLED;
}

// ===========================================================================
// ===  Dispatch: switch on GMaterialType  ====================================
// ===========================================================================

__device__ inline bool gpu_closure_is_sampleable(GClosureType type) {
    return type == GCLOSURE_DIFFUSE ||
           type == GCLOSURE_GGX_CONDUCTOR ||
           type == GCLOSURE_DIELECTRIC_TRANSMISSION ||
           type == GCLOSURE_THIN_GLASS ||
           type == GCLOSURE_PRINCIPLED;  // pkg178 Stage 2
}

__device__ inline GMaterial gpu_closure_as_material(const GMaterial& parent, const GMaterialClosure& closure) {
    GMaterial tmp = parent;
    tmp.type = GMAT_LAMBERTIAN;
    tmp.baseColor = closure.color;
    tmp.roughness = closure.roughness;
    tmp.metallic = closure.metallic;
    tmp.ior = closure.ior;
    tmp.transmission = fminf(fmaxf(closure.transmission, 0.0f), 1.0f);
    tmp.clearcoat = 0.0f;
    tmp.clearcoatGloss = closure.clearcoatGloss;
    tmp.emissionIntensity = 0.0f;
    tmp.specular = 0.5f;
    tmp.specularTint = 0.0f;
    tmp.sheen = 0.0f;
    tmp.sheenTint = 0.5f;
    tmp.subsurface = 0.0f;
    tmp.anisotropic = 0.0f;
    tmp.anisotropicRotation = 0.0f;

    switch (closure.type) {
        case GCLOSURE_DIFFUSE:
            tmp.type = GMAT_LAMBERTIAN;
            // pkg108 BUG-16 (closure path): the Disney plugin lowers its
            // diffuse lobe to GCLOSURE_DIFFUSE, so the subsurface mix must
            // ride along. The HK formula needs the Disney roughness, which
            // lives on the parent (the diffuse closure's own roughness is 0).
            tmp.subsurface = parent.subsurface;
            tmp.roughness  = parent.roughness;
            break;
        case GCLOSURE_GGX_CONDUCTOR:
            // pkg141: DisneyPlugin::closureGraph() (plugins/materials/disney.cpp,
            // Lane A's exclusive file -- not edited here) emits the SAME
            // GGXConductor closure shape as the standalone MetalPlugin, but the
            // two plugins need DIFFERENT GPU models. gpu_metal_eval/sample below
            // 0.1 roughness returns an unconditional full-albedo mirror
            // (s.f = baseColor, no Fresnel/D/G shaping) -- correct for
            // MetalPlugin (its own CPU eval()/sample() has the identical
            // shortcut, metal.cpp:33,94), but wrong for a Disney metallic
            // lobe: DisneyPlugin's CPU eval()/sample()/pdf() never special-
            // cases low roughness (alpha floors at max(roughness^2, 0.0064)
            // and stays a continuous Fresnel-Schlick/D_GTR2/Smith-G lobe, see
            // disney.cpp sample()'s specular branch calling eval()/pdf()
            // unconditionally). Routing Disney's conductor closure through
            // gpu_metal_eval instead of gpu_disney_eval measured GPU/CPU
            // metal-at-roughness->0 brightness ratios of 2.7-4.0x (pkg123
            // parity xfails, tests/test_pkg123_disney_metal_gpu_cpu_parity.py).
            // parent.disneyMetalConductor is stamped by scene_upload.cu from
            // Material::getGPUTypeName() at closure-graph upload time.
            if (parent.disneyMetalConductor) {
                tmp.type = GMAT_DISNEY;
                tmp.metallic = 1.0f;
                tmp.transmission = 0.0f;
                // Disney's closure-graph lowering does not carry clearcoat/
                // sheen through the closure system at all (DisneyPlugin::
                // closureGraph() only ever emits Diffuse/GGXConductor/
                // DielectricTransmission closures -- a pre-existing, documented
                // approximation, see disney.cpp backendCapabilities() notes).
                // The specular/specularTint/sheen/clearcoat defaults set above
                // (0.5/0/0/0) already match DisneyPlugin's own eval() defaults
                // for a plain metallic lobe (F0 = baseColor when metallic=1,
                // Cspec0's specular/specularTint terms are scaled by
                // (1-metallic) = 0 and drop out).
            } else {
                tmp.type = GMAT_METAL;
                tmp.metallic = 1.0f;
            }
            break;
        case GCLOSURE_DIELECTRIC_TRANSMISSION:
            tmp.type = closure.roughness > 0.03f ? GMAT_DISNEY : GMAT_DIELECTRIC;
            tmp.metallic = 0.0f;
            break;
        case GCLOSURE_THIN_GLASS:
            tmp.type = GMAT_THIN_GLASS;
            break;
        default:
            tmp.type = GMAT_LAMBERTIAN;
            break;
    }
    return tmp;
}

__device__ inline GVec3 gpu_closure_eval(
    const GMaterial& parent, const GMaterialClosure& closure,
    GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    if (closure.weight <= 0.0f) return GVec3(0.0f);
    GMaterial tmp = gpu_closure_as_material(parent, closure);
    GVec3 result(0.0f);
    switch (tmp.type) {
        case GMAT_LAMBERTIAN: result = gpu_lambertian_eval(tmp, rec, wo, wi); break;
        case GMAT_METAL: result = gpu_metal_eval(tmp, rec, wo, wi); break;
        case GMAT_DISNEY: result = gpu_disney_eval(tmp, rec, wo, wi); break;
        default: result = GVec3(0.0f); break;
    }
    return result * closure.weight;
}

__device__ inline float gpu_closure_pdf(
    const GMaterial& parent, const GMaterialClosure& closure,
    const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    if (!gpu_closure_is_sampleable(closure.type) || closure.weight <= 0.0f)
        return 0.0f;
    GMaterial tmp = gpu_closure_as_material(parent, closure);
    switch (tmp.type) {
        case GMAT_LAMBERTIAN: return gpu_lambertian_pdf(tmp, rec, wo, wi);
        case GMAT_METAL: return gpu_metal_pdf(tmp, rec, wo, wi);
        case GMAT_DISNEY: return gpu_disney_pdf(tmp, rec, wo, wi);
        default: return 0.0f;
    }
}

// pkg178 Stage-3b D4: HasPrincipled compile-time isolation. Non-principled
// scenes launch the <false> instantiation, in which the Principled arm and all
// gpu_principled_* codegen are compiled out (if constexpr) — restoring main's
// non-principled shade-kernel footprint. Default = true so every OTHER caller
// (restir, snapshot intersect, sms, CPU-reachable) keeps today's behavior
// verbatim. See .astroray_plan/docs/pkg178-stage3-d4-and-forks-decision.md §2b.
template<bool HasPrincipled = true>
__device__ inline GVec3 gpu_closure_graph_eval(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    // pkg178 Stage 2: the Principled material is a monolithic single closure whose
    // eval IS its own view-dependent lobe mixture (gpu_principled_eval), not a sum
    // over independent graph closures — route it straight there.
    if constexpr (HasPrincipled) {
        if (gpu_closure_graph_is_principled(mat))
            return gpu_principled_eval(mat.principled, rec, wo, wi);
    }
    // pkg170: weight each lobe by its SELECTION probability (weight_i / totalWeight),
    // matching gpu_closure_graph_pdf's normalization, so the closure-graph sampler's
    // overwrite s.f = eval, s.pdf = pdf forms a correct one-sample-MIS estimator of
    // the MIXTURE BSDF (Veach 1997 thesis Eq. 9.15 one-sample model / balance
    // heuristic; PBRT-v4 §9.5 & §14.3.4 "BSDF::Sample_f" mixture sampling). The eval
    // previously summed RAW weights (Sum w_i f_i) while the pdf summed NORMALIZED
    // weights (Sum (w_i/W) pdf_i); f_total/pdf_total then estimated a W-inflated
    // integrand. For opaque Disney (diffuse w=1 + GGX-conductor w=1, W=2, each lobe
    // ~unit albedo in a white furnace) that is a flat ~1.975 energy gain across
    // roughness (measured 78218f6 RTX 5070 Ti), while CPU's monolithic Disney
    // conserves (~0.95). This is the opaque twin of pkg169's transmission-path
    // recombination fix (which corrected the overwritten pdf's Fresnel orientation;
    // this corrects the overwritten eval's lobe weighting). Single-lobe graphs
    // (plain metal/dielectric, Disney glass, metallic=1 Disney) have W = weight_1 so
    // (w_1/W) = 1 -> byte-unchanged. Normalize over the SAME sampleable set the pdf
    // uses so the two are consistent.
    float totalWeight = 0.0f;
    int count = mat.closureCount < G_MAX_MATERIAL_CLOSURES ? mat.closureCount : G_MAX_MATERIAL_CLOSURES;
    for (int i = 0; i < count; ++i) {
        const GMaterialClosure& closure = mat.closures[i];
        if (gpu_closure_is_sampleable(closure.type))
            totalWeight += fmaxf(closure.weight, 0.0f);
    }
    if (totalWeight <= 0.0f) return GVec3(0.0f);

    GVec3 sum(0.0f);
    for (int i = 0; i < count; ++i) {
        const GMaterialClosure& closure = mat.closures[i];
        if (closure.type != GCLOSURE_EMISSION)
            sum += gpu_closure_eval(mat, closure, rec, wo, wi);
    }
    return sum * (1.0f / totalWeight);
}

// pkg163: does this closure graph carry a metal (non-Disney) conductor lobe?
// Only those lobes lower to gpu_metal_eval and therefore have the CPU-per-lambda
// vs GPU-RGB colour-space seam. A Disney-originated conductor closure lowers to
// gpu_disney_eval (per-RGB on both sides, consistent twins) and is out of scope.
__device__ inline bool gpu_closure_graph_has_metal(const GMaterial& mat) {
    if (mat.disneyMetalConductor) return false;
    int count = mat.closureCount < G_MAX_MATERIAL_CLOSURES ? mat.closureCount : G_MAX_MATERIAL_CLOSURES;
    for (int i = 0; i < count; ++i)
        if (mat.closures[i].type == GCLOSURE_GGX_CONDUCTOR) return true;
    return false;
}

// pkg168 Step 2 (perf-lean rev): true for a plain diffuse material — native
// GMAT_LAMBERTIAN or the plain-Lambertian upload path, which lowers to a closure
// graph with a SINGLE GCLOSURE_DIFFUSE lobe (Lambertian::closureGraph() emits
// exactly one makeDiffuseClosure). For these, and only these, the RGB BSDF value
// is colour*cos/pi, so the spectral path can recover the pure colour and upsample
// it (pkg168 correctness fix). This is a compile-cheap field check — NO loop over
// closures — deliberately: the earlier loop form (checking "every sampleable lobe
// is diffuse") tipped the already-register-maxed wavefront shade/advance kernels
// into heavy stack spill (STK +~2000B) and cost the perf gate ~1.5x. A multi-
// diffuse-lobe-only graph is not produced by any current plugin and would simply
// fall through to the generic (unchanged) upsample-of-f path, exactly as before
// #541 — no regression there. Anything carrying a glass/transmission/Disney/metal
// lobe is excluded, so the eta^2>1 factoring (pkg118/pkg152) and the metal path
// (pkg163) are untouched.
__device__ inline bool gpu_is_plain_diffuse(const GMaterial& mat) {
    if (mat.type == GMAT_LAMBERTIAN) return true;
    return mat.type == GMAT_CLOSURE_GRAPH && mat.closureCount == 1 &&
           mat.closures[0].type == GCLOSURE_DIFFUSE;
}

// pkg163: per-wavelength closure-graph eval, used only when the graph carries a
// metal conductor lobe (gpu_closure_graph_has_metal). The metal lobe is built
// per-lambda via gpu_metal_eval_spectral (CPU-canonical colour space); any other
// lobe keeps its existing per-lobe RGB eval then upsample. Non-metal graphs
// never reach here, so their summed-then-upsampled behaviour is unchanged.
template<bool HasPrincipled = true>  // pkg178 Stage-3b D4 (see gpu_closure_graph_eval)
__device__ inline GSampledSpectrum gpu_closure_graph_eval_spectral(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, const GVec3& wi,
    const GSampledWavelengths& wl)
{
    // pkg178 Stage 2: native per-λ Principled mixture (per-lobe spectral eval,
    // NOT upsample-of-RGB — the pkg163/168 nonlinearity lesson is built into
    // gpu_pr_evalLobeSpectral, which upsamples reflectance colours only).
    if constexpr (HasPrincipled) {
        if (gpu_closure_graph_is_principled(mat))
            return gpu_principled_eval_spectral(mat.principled, rec, wo, wi, wl);
    }
    // pkg170: same selection-probability normalization as the RGB
    // gpu_closure_graph_eval (see there) so f_total/pdf_total is a one-sample-MIS
    // estimator of the mixture BSDF. This spectral path is only reached for
    // metal-carrying graphs (gpu_closure_graph_has_metal); those are single-lobe
    // today (W = weight_1 -> unchanged), but the normalization is kept in lockstep
    // with the RGB twin so a future multi-lobe metal graph cannot re-open this
    // bug class.
    float totalWeight = 0.0f;
    int count = mat.closureCount < G_MAX_MATERIAL_CLOSURES ? mat.closureCount : G_MAX_MATERIAL_CLOSURES;
    for (int i = 0; i < count; ++i) {
        const GMaterialClosure& closure = mat.closures[i];
        if (gpu_closure_is_sampleable(closure.type))
            totalWeight += fmaxf(closure.weight, 0.0f);
    }
    if (totalWeight <= 0.0f) return GSampledSpectrum(0.0f);

    GSampledSpectrum sum(0.0f);
    for (int i = 0; i < count; ++i) {
        const GMaterialClosure& closure = mat.closures[i];
        if (closure.type == GCLOSURE_EMISSION || closure.weight <= 0.0f) continue;
        GMaterial tmp = gpu_closure_as_material(mat, closure);
        if (tmp.type == GMAT_METAL)
            sum += gpu_metal_eval_spectral(tmp, rec, wo, wi, wl) * closure.weight;
        else if (tmp.type == GMAT_LAMBERTIAN)
            // pkg168: upsample the diffuse colour per-lambda, not the pre-scaled
            // RGB eval (JH upsampling is nonlinear in magnitude).
            sum += gpu_lambertian_eval_spectral(tmp, rec, wo, wi, wl) * closure.weight;
        else
            sum += gpu_rgbToSampledSpectrum(
                gpu_closure_eval(mat, closure, rec, wo, wi), wl, mat.spectralMode);
    }
    return sum * (1.0f / totalWeight);
}

template<bool HasPrincipled = true>  // pkg178 Stage-3b D4 (see gpu_closure_graph_eval)
__device__ inline float gpu_closure_graph_pdf(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    // pkg178 Stage 2: monolithic Principled mixture pdf (see gpu_closure_graph_eval).
    if constexpr (HasPrincipled) {
        if (gpu_closure_graph_is_principled(mat))
            return gpu_principled_pdf(mat.principled, rec, wo, wi);
    }
    float totalWeight = 0.0f;
    int count = mat.closureCount < G_MAX_MATERIAL_CLOSURES ? mat.closureCount : G_MAX_MATERIAL_CLOSURES;
    for (int i = 0; i < count; ++i) {
        const GMaterialClosure& closure = mat.closures[i];
        if (gpu_closure_is_sampleable(closure.type))
            totalWeight += fmaxf(closure.weight, 0.0f);
    }
    if (totalWeight <= 0.0f) return 0.0f;

    float sum = 0.0f;
    for (int i = 0; i < count; ++i) {
        const GMaterialClosure& closure = mat.closures[i];
        if (!gpu_closure_is_sampleable(closure.type)) continue;
        float selectionPdf = fmaxf(closure.weight, 0.0f) / totalWeight;
        sum += selectionPdf * gpu_closure_pdf(mat, closure, rec, wo, wi);
    }
    return sum;
}

template <bool HasPrincipled = true, typename TRng>  // pkg178 Stage-3b D4
__device__ inline GBSDFSample gpu_closure_graph_sample(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, TRng* rng)
{
    GBSDFSample s;
    s.wi = GVec3(0, 1, 0);
    s.f = GVec3(0.0f);
    s.fSpectral = GSampledSpectrum(0.0f);
    s.pdf = 0.0f;
    s.isDelta = false;

    // pkg178 Stage 2: the Principled closure runs its own complete one-sample-MIS
    // sample (internal lobe choice + delta handling + mixture f/pdf recombination),
    // mirroring PrincipledPlugin::sample — do NOT route it through the generic
    // per-lobe switch + recompute below (its assembly is view-dependent).
    if constexpr (HasPrincipled) {
        if (gpu_closure_graph_is_principled(mat))
            return gpu_principled_sample(mat.principled, rec, wo, rng);
    }

    float totalWeight = 0.0f;
    int count = mat.closureCount < G_MAX_MATERIAL_CLOSURES ? mat.closureCount : G_MAX_MATERIAL_CLOSURES;
    for (int i = 0; i < count; ++i) {
        const GMaterialClosure& closure = mat.closures[i];
        if (gpu_closure_is_sampleable(closure.type))
            totalWeight += fmaxf(closure.weight, 0.0f);
    }
    if (totalWeight <= 0.0f) return s;

    float xi = gpu_rng_uniform(rng) * totalWeight;
    int chosen = -1;
    float accum = 0.0f;
    for (int i = 0; i < count; ++i) {
        const GMaterialClosure& closure = mat.closures[i];
        if (!gpu_closure_is_sampleable(closure.type)) continue;
        accum += fmaxf(closure.weight, 0.0f);
        if (xi <= accum) {
            chosen = i;
            break;
        }
    }
    if (chosen < 0) return s;

    const GMaterialClosure& closure = mat.closures[chosen];
    GMaterial tmp = gpu_closure_as_material(mat, closure);
    switch (tmp.type) {
        case GMAT_LAMBERTIAN: s = gpu_lambertian_sample(tmp, rec, wo, rng); break;
        case GMAT_METAL: s = gpu_metal_sample(tmp, rec, wo, rng); break;
        case GMAT_DIELECTRIC: s = gpu_dielectric_sample(tmp, rec, wo, rng); break;
        case GMAT_DISNEY: s = gpu_disney_sample(tmp, rec, wo, rng); break;
        case GMAT_THIN_GLASS: s = gpu_thin_glass_sample(tmp, rec, wo, rng); break;
        default: return s;
    }

    if (s.pdf <= 0.0f || s.f.length2() <= 0.0f) return s;
    if (s.isDelta) {
        s.f *= closure.weight;
    } else {
        s.f = gpu_closure_graph_eval<HasPrincipled>(mat, rec, wo, s.wi);
        s.pdf = gpu_closure_graph_pdf<HasPrincipled>(mat, rec, wo, s.wi);
    }
    return s;
}

__device__ inline GVec3 gpu_closure_graph_emitted(const GMaterial& mat, bool frontFace) {
    GVec3 sum(0.0f);
    int count = mat.closureCount < G_MAX_MATERIAL_CLOSURES ? mat.closureCount : G_MAX_MATERIAL_CLOSURES;
    for (int i = 0; i < count; ++i) {
        const GMaterialClosure& closure = mat.closures[i];
        if (closure.type == GCLOSURE_EMISSION && (frontFace || closure.twoSidedEmission))
            sum += closure.color * closure.transmission * closure.weight;
    }
    return sum;
}

template<bool HasPrincipled = true>  // pkg178 Stage-3b D4 (see gpu_closure_graph_eval)
__device__ inline GVec3 gpu_material_eval(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    switch (mat.type) {
        case GMAT_LAMBERTIAN:    return gpu_lambertian_eval(mat, rec, wo, wi);
        case GMAT_METAL:         return gpu_metal_eval(mat, rec, wo, wi);
        case GMAT_DIELECTRIC:    return GVec3(0.f); // delta — no direct eval
        case GMAT_DIFFUSE_LIGHT: return GVec3(0.f); // emissive only
        case GMAT_DISNEY:        return gpu_disney_eval(mat, rec, wo, wi);
        case GMAT_THIN_GLASS:    return GVec3(0.f); // mostly-delta pane
        case GMAT_CLOSURE_GRAPH: return gpu_closure_graph_eval<HasPrincipled>(mat, rec, wo, wi);
        default:                 return GVec3(0.f);
    }
}

template<bool HasPrincipled = true>  // pkg178 Stage-3b D4 (see gpu_closure_graph_eval)
__device__ inline GSampledSpectrum gpu_material_eval_spectral(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, const GVec3& wi,
    const GSampledWavelengths& wl)
{
    // pkg163: metal is natively per-lambda on the CPU (MetalPlugin::evalSpectral);
    // build its spectrum per-lambda here too instead of upsampling the RGB eval,
    // so the CPU/GPU colour spaces match. Plain `metal` uploads as a closure
    // graph (its GGXConductor lobe validates), so both entry points are covered.
    if (mat.type == GMAT_METAL)
        return gpu_metal_eval_spectral(mat, rec, wo, wi, wl);
    // pkg178 Stage 2: native per-λ Principled (its own spectral mixture path).
    if constexpr (HasPrincipled) {
        if (mat.type == GMAT_CLOSURE_GRAPH && gpu_closure_graph_is_principled(mat))
            return gpu_closure_graph_eval_spectral<HasPrincipled>(mat, rec, wo, wi, wl);
    }
    if (mat.type == GMAT_CLOSURE_GRAPH && gpu_closure_graph_has_metal(mat))
        return gpu_closure_graph_eval_spectral<HasPrincipled>(mat, rec, wo, wi, wl);
    // pkg168 Step 2: plain diffuse (native GMAT_LAMBERTIAN or a diffuse-only
    // closure graph — the plain-Lambertian upload path) must upsample the pure
    // reflectance COLOUR, not the pre-scaled RGB eval baseColor*cos/pi. Jakob-
    // Hanika upsampling is nonlinear in magnitude (upsample(k*c) != k*upsample(c)),
    // so upsampling the pre-scaled value yields a wrong spectrum SHAPE (same XYZ,
    // but the mismatch compounds once throughput is multiplied and integrated —
    // pkg163 bug class). The eval for these lobes is colour*cos/pi, so recover the
    // colour = eval / (cos/pi) and feed it to the SAME single upsample below,
    // re-applying cos/pi as a wavelength-flat scalar. This adds no new upsample
    // call or helper body to the register-maxed shade kernel — a separately
    // inlined per-lambda helper spilled the kernel's stack and cost the wavefront
    // perf gate ~1.6x (pkg168 perf-fix). These routes never carry subsurface, so
    // no Hanrahan-Krueger mix is needed; the CPU oracle (Lambertian::evalSpectral)
    // applies none. The Disney diffuse lobe inside a metal-carrying graph keeps its
    // HK mix via gpu_closure_graph_eval_spectral above, unchanged.
    GVec3 e = gpu_material_eval<HasPrincipled>(mat, rec, wo, wi);
    float diffuseScale = 1.0f;
    if (gpu_is_plain_diffuse(mat)) {
        float NdotL = rec.normal.dot(wi);
        if (NdotL > 1e-8f) {
            diffuseScale = NdotL * (1.0f / M_PI_F);
            e = e * (1.0f / diffuseScale);
        }
    }
    return gpu_rgbToSampledSpectrum(e, wl, mat.spectralMode) * diffuseScale;
}

template <bool HasPrincipled = true, typename TRng>  // pkg178 Stage-3b D4
__device__ inline GBSDFSample gpu_material_sample(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, TRng* rng)
{
    switch (mat.type) {
        case GMAT_LAMBERTIAN:    return gpu_lambertian_sample(mat, rec, wo, rng);
        case GMAT_METAL:         return gpu_metal_sample(mat, rec, wo, rng);
        case GMAT_DIELECTRIC:    return gpu_dielectric_sample(mat, rec, wo, rng);
        case GMAT_DISNEY:        return gpu_disney_sample(mat, rec, wo, rng);
        case GMAT_THIN_GLASS:    return gpu_thin_glass_sample(mat, rec, wo, rng);
        case GMAT_CLOSURE_GRAPH: return gpu_closure_graph_sample<HasPrincipled>(mat, rec, wo, rng);
        default: { GBSDFSample s; s.f=GVec3(0); s.fSpectral=GSampledSpectrum(0.f); s.wi=GVec3(0,1,0); s.pdf=0; s.isDelta=false; return s; }
    }
}

template <bool HasPrincipled = true, typename TRng>  // pkg178 Stage-3b D4
__device__ inline GBSDFSample gpu_material_sample_spectral(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo,
    GSampledWavelengths& wl, TRng* rng)
{
    // pkg64-gpu-sellmeier-upload: dispersive dielectrics need the wavelength-aware
    // sampler (it calls wl.terminateSecondary() on refraction — hero collapse).
    GBSDFSample s = (mat.type == GMAT_DIELECTRIC && mat.isDispersive)
        ? gpu_dielectric_sample_spectral(mat, rec, wo, wl, rng)
        : gpu_material_sample<HasPrincipled>(mat, rec, wo, rng);

    // Delta lobes (dielectric reflect/refract, smooth-glass disney/closure-graph
    // closures — a plain "dielectric" material lowers to GMAT_CLOSURE_GRAPH) carry a
    // radiance-TRANSPORT factor in s.f, NOT a [0,1] albedo: the refraction f is
    // baseColor*eta^2 and eta^2 reaches 2.25 @ ior 1.5, 4.0 @ ior 2.0. The ALBEDO
    // upsampler (gpu_rgbToSampledSpectrum) clamps rgb to [0,1], so the exit eta^2 was
    // clipped to 1.0 and the enter(0.44)/exit(2.25) factors no longer cancelled — the
    // white furnace lost energy scaling with IOR (GPU 0.705 @ ior 1.5 vs CPU 0.985).
    // Factor the >1 magnitude out as a flat spectral scalar and upsample only the
    // normalized tint, mirroring CPU dielectric.cpp:72 (tintSpec * eta^2).
    //
    // pkg152: this guard was DELTA-ONLY (`s.isDelta && m > 1.0f`) -- CPU's
    // Material::sampleSpectral (raytracer.h) applies the identical factoring
    // to the NON-DELTA (rough) branch too, with the explicit comment "Same
    // eta^2-clamp guard for the rough (non-delta) glass lobe: the rough
    // transmission eval also exceeds 1 on exit, and the albedo LUT would
    // clip it." (pkg118/#404 lineage). Without it, a rough Disney-glass
    // transmission exit event's legitimate >1 exit-eta^2 magnitude (up to
    // eta^2=2.25 at ior=1.5, e.g. once pkg154's closure-level-clamp removal
    // makes it reachable) is silently clipped back to 1.0 by the ALBEDO
    // Jakob-Hanika LUT (gpu_jhLookupCoeffs clamps rgb to [0,1]) on every
    // ROUGH transmission exit event -- convicted as the pkg152 spec's #522
    // GPU-only, low-roughness-dominant furnace deficit (measured on the
    // #522 stack: R=0.1 -> 0.130, R=0.3 -> 0.283 pre-fix; the eval()/pdf()/
    // sample() functions themselves are already byte-identical to CPU
    // there, confirmed by direct comparison, so this multi-wavelength
    // upsampling wrapper was the only remaining divergence -- see
    // .astroray_plan/packages/pkg152-gpu-disney-metal-residual-dimness.md).
    // Mirrors CPU's non-delta branch exactly (same maxc computation, same
    // threshold, same tint-then-rescale structure); CPU additionally
    // re-evaluates via evalSpectral() in the maxc<=1 case where GPU reuses
    // the already-computed `s.f` -- numerically equivalent (same underlying
    // eval dispatch for the same (wo,wi)) and avoids a redundant device-side
    // re-eval.
    // pkg163: metal is natively per-lambda on the CPU. For a non-delta metal
    // bounce, build fSpectral per-lambda (gpu_metal_eval_spectral) rather than
    // upsampling the RGB s.f, matching gpu_material_eval_spectral and the CPU
    // oracle. The near-delta metal branch (s.isDelta, s.f = albedo mirror) keeps
    // the plain albedo upsample below -- MetalPlugin::sample()'s delta lobe does
    // not apply the eval factor either. Plain `metal` uploads as a closure graph
    // (its GGXConductor lobe validates), so both entry points are covered; the
    // closure-graph sampler has already recomputed s.wi's f for non-delta lobes.
    bool metalSpectral = (mat.type == GMAT_METAL) ||
        (mat.type == GMAT_CLOSURE_GRAPH && gpu_closure_graph_has_metal(mat));
    if (metalSpectral && !s.isDelta && s.pdf > 0.0f && s.f.length2() > 0.0f) {
        s.fSpectral = (mat.type == GMAT_METAL)
            ? gpu_metal_eval_spectral(mat, rec, wo, s.wi, wl)
            : gpu_closure_graph_eval_spectral<HasPrincipled>(mat, rec, wo, s.wi, wl);
        return s;
    }

    // pkg178 Stage 2: Principled is natively per-λ (like metal). For a NON-DELTA
    // bounce build fSpectral from the per-lobe spectral mixture, mirroring
    // PrincipledPlugin::sampleSpectral's `f_spectral = evalSpectral(...)`
    // (principled.cpp:771). DELTA (smooth-glass) principled events fall through to
    // the generic eta²-clamp guard below, which factors the >1 magnitude and
    // upsamples the normalized tint — exactly PrincipledPlugin::sampleSpectral's
    // delta branch (principled.cpp:762-766, upsample(rgb/maxc)*maxc).
    if constexpr (HasPrincipled) {
        if (mat.type == GMAT_CLOSURE_GRAPH && gpu_closure_graph_is_principled(mat) &&
            !s.isDelta && s.pdf > 0.0f && s.f.length2() > 0.0f) {
            s.fSpectral = gpu_closure_graph_eval_spectral<HasPrincipled>(mat, rec, wo, s.wi, wl);
            return s;
        }
    }

    // pkg168 Step 2: plain diffuse lobes (native GMAT_LAMBERTIAN or the plain-
    // Lambertian upload path — a single-GCLOSURE_DIFFUSE closure graph) must
    // upsample the pure reflectance COLOUR, not the pre-scaled RGB f = colour*cos/pi.
    // Jakob-Hanika upsampling is nonlinear in magnitude (upsample(k*c) !=
    // k*upsample(c)), so upsampling the pre-scaled f gives a wrong spectrum SHAPE
    // (same XYZ, but the mismatch compounds once throughput is multiplied and
    // integrated — pkg163 bug class). f = colour*cos/pi for these lobes, so recover
    // the colour = f / (cos/pi) and feed it to the SAME single upsample below,
    // re-applying cos/pi as a wavelength-flat scalar. This reuses the existing
    // upsample (no extra JH call / per-lambda helper body) and drops #541's
    // gpu_lambertian_eval scalar-recovery + closure loop. These routes never carry
    // subsurface, so no Hanrahan-Krueger mix is needed; the CPU oracle
    // (Lambertian::evalSpectral) applies none. Glass/Disney/dielectric graphs are
    // excluded so the eta^2>1 magnitude factoring below (pkg118/pkg152) is untouched.
    GVec3 upColor = s.f;
    float diffuseScale = 1.0f;
    if (!s.isDelta && s.pdf > 0.0f && s.f.length2() > 0.0f && gpu_is_plain_diffuse(mat)) {
        float NdotL = rec.normal.dot(s.wi);
        if (NdotL > 1e-8f) {
            diffuseScale = NdotL * (1.0f / M_PI_F);
            upColor = s.f * (1.0f / diffuseScale);
        }
    }

    float m = fmaxf(fmaxf(upColor.x, upColor.y), upColor.z);
    if (m > 1.0f) {
        s.fSpectral = gpu_rgbToSampledSpectrum(upColor * (1.0f / m), wl, mat.spectralMode) * (m * diffuseScale);
    } else {
        s.fSpectral = gpu_rgbToSampledSpectrum(upColor, wl, mat.spectralMode) * diffuseScale;
    }
    return s;
}

template<bool HasPrincipled = true>  // pkg178 Stage-3b D4 (see gpu_closure_graph_eval)
__device__ inline float gpu_material_pdf(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    switch (mat.type) {
        case GMAT_LAMBERTIAN: return gpu_lambertian_pdf(mat, rec, wo, wi);
        case GMAT_METAL:      return gpu_metal_pdf(mat, rec, wo, wi);
        case GMAT_DISNEY:     return gpu_disney_pdf(mat, rec, wo, wi);
        case GMAT_CLOSURE_GRAPH: return gpu_closure_graph_pdf<HasPrincipled>(mat, rec, wo, wi);
        default:              return 0.f;
    }
}

__device__ inline GVec3 gpu_material_emitted(
    const GMaterial& mat, bool frontFace)
{
    if (mat.type == GMAT_DIFFUSE_LIGHT && frontFace)
        return mat.baseColor * mat.emissionIntensity;
    if (mat.type == GMAT_CLOSURE_GRAPH)
        return gpu_closure_graph_emitted(mat, frontFace);
    return GVec3(0.f);
}

__device__ inline GSampledSpectrum gpu_material_emitted_spectral(
    const GMaterial& mat, bool frontFace, const GSampledWavelengths& wl)
{
    return gpu_rgbToSampledSpectrum(
        gpu_material_emitted(mat, frontFace), wl, mat.spectralMode);
}
