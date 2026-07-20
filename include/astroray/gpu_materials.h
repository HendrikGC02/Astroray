#pragma once
// GPU material evaluation — ported from raytracer.h and advanced_features.h.
// All formulas match the CPU reference exactly (same fixes applied).
// Only include this from .cu files compiled by nvcc.

#include "gpu_types.h"
#include "gpu_dispersion.cuh"
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
    // NOTE: eval() returns brdf * NdotL (cosine-weighted), matches CPU
    return F * D * G / (4.f * NdotV + 0.001f);
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
    float h = sqrtf(fmaxf(0.f, 1.f - px*px));
    py = ((1.f + wh.z) / 2.f) * h + (1.f - (1.f + wh.z) / 2.f) * py;

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

// PBRT-v4 DielectricBxDF::f transmission (BSD-3-Clause).
// Walter 2007 "Microfacet Models for Refraction through Rough Surfaces" Eq. 21.
__device__ inline GVec3 gpu_disney_roughTransmissionEval(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    float cosO = rec.normal.dot(wo);
    float cosI = rec.normal.dot(wi);
    if (cosO == 0.f || cosI == 0.f || cosO*cosI >= 0.f) return GVec3(0.f);

    bool entering = cosO > 0.f;
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

    float scale = (1.f - mat.metallic) * mat.transmission * ft;
    GVec3 result = mat.baseColor * scale;
    result.x = fminf(fmaxf(result.x, 0.f), 4.f);
    result.y = fminf(fmaxf(result.y, 0.f), 4.f);
    result.z = fminf(fmaxf(result.z, 0.f), 4.f);
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

    bool entering = cosO > 0.f;
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
    GVec3 diffuse = (1.f / M_PI_F) * Cdlin * FdMixed;

    // Specular — min alpha 0.0064 (roughness 0.08) to prevent numerical collapse
    float a  = fmaxf(mat.roughness*mat.roughness, 0.0064f);
    float Ds = gpu_D_GTR2(NdotH, a);
    float schlickScale = 0.8f + 0.2f * mat.metallic;
    GVec3 F  = gpu_disney_fresnelSchlick(LdotH, F0, schlickScale);
    float Gs = gpu_smithG_GGX(NdotL, a) * gpu_smithG_GGX(NdotV, a);
    GVec3 spec = Ds * F * Gs / (4.f * NdotL * NdotV + 0.001f);

    // Sheen (reduced by 0.5)
    GVec3 Csheen = GVec3(1.f)*(1.f-mat.sheenTint) + Ctint*mat.sheenTint;
    GVec3 Fsheen = mat.sheen * Csheen * powf(1.f - LdotH, 5.f) * 0.5f;

    // Clearcoat (reduced by 0.5)
    float Dr  = gpu_D_GTR2(NdotH, mat.clearcoatGloss * mat.clearcoatGloss);
    float Fr  = 0.04f + (1.f - 0.04f) * powf(1.f - LdotH, 5.f);
    float Gr  = gpu_smithG_GGX(NdotL, 0.25f) * gpu_smithG_GGX(NdotV, 0.25f);
    GVec3 ccTerm = GVec3(mat.clearcoat * Dr * Fr * Gr
                         / (4.f*NdotL*NdotV + 0.001f)) * 0.5f;

    GVec3 result = ((1.f-mat.metallic)*(1.f-mat.transmission)*diffuse
                   + spec
                   + (1.f-mat.metallic)*Fsheen
                   + ccTerm) * NdotL;

    // Clamp per-sample firefly guard
    result.x = fminf(result.x, 10.f);
    result.y = fminf(result.y, 10.f);
    result.z = fminf(result.z, 10.f);
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
        }

        if (cannotRef || gpu_rng_uniform(rng) < fresnel) {
            s.wi  = n * (2.f * wo.dot(n)) - wo;
            s.f   = GVec3(1.f);
            // pkg118 Part A: forced-TIR reflection is deterministic (selection prob 1),
            // so pdf = transmission (not fresnel*transmission). PBRT-v4 §9.5. Mirrors CPU
            // disney.cpp forced-TIR fix; keeps the bespoke RGB GPU path in lockstep.
            s.pdf = cannotRef ? mat.transmission : (fresnel * mat.transmission);
        } else {
            GVec3 perp = (wo - n*cosTheta) * (-eta);
            GVec3 para = n * (-sqrtf(fabsf(1.f - perp.length2())));
            s.wi  = (perp + para).normalized();
            s.f   = mat.baseColor * (eta*eta);
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
        bool entering = rec.normal.dot(wo) > 0.f;
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
// ===  Dispatch: switch on GMaterialType  ====================================
// ===========================================================================

__device__ inline bool gpu_closure_is_sampleable(GClosureType type) {
    return type == GCLOSURE_DIFFUSE ||
           type == GCLOSURE_GGX_CONDUCTOR ||
           type == GCLOSURE_DIELECTRIC_TRANSMISSION ||
           type == GCLOSURE_THIN_GLASS;
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
            tmp.type = GMAT_METAL;
            tmp.metallic = 1.0f;
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

__device__ inline GVec3 gpu_closure_graph_eval(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    GVec3 sum(0.0f);
    int count = mat.closureCount < G_MAX_MATERIAL_CLOSURES ? mat.closureCount : G_MAX_MATERIAL_CLOSURES;
    for (int i = 0; i < count; ++i) {
        const GMaterialClosure& closure = mat.closures[i];
        if (closure.type != GCLOSURE_EMISSION)
            sum += gpu_closure_eval(mat, closure, rec, wo, wi);
    }
    return sum;
}

__device__ inline float gpu_closure_graph_pdf(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
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

template <typename TRng>
__device__ inline GBSDFSample gpu_closure_graph_sample(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, TRng* rng)
{
    GBSDFSample s;
    s.wi = GVec3(0, 1, 0);
    s.f = GVec3(0.0f);
    s.fSpectral = GSampledSpectrum(0.0f);
    s.pdf = 0.0f;
    s.isDelta = false;

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
        s.f = gpu_closure_graph_eval(mat, rec, wo, s.wi);
        s.pdf = gpu_closure_graph_pdf(mat, rec, wo, s.wi);
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
        case GMAT_CLOSURE_GRAPH: return gpu_closure_graph_eval(mat, rec, wo, wi);
        default:                 return GVec3(0.f);
    }
}

__device__ inline GSampledSpectrum gpu_material_eval_spectral(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, const GVec3& wi,
    const GSampledWavelengths& wl)
{
    return gpu_rgbToSampledSpectrum(
        gpu_material_eval(mat, rec, wo, wi), wl, mat.spectralMode);
}

template <typename TRng>
__device__ inline GBSDFSample gpu_material_sample(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, TRng* rng)
{
    switch (mat.type) {
        case GMAT_LAMBERTIAN:    return gpu_lambertian_sample(mat, rec, wo, rng);
        case GMAT_METAL:         return gpu_metal_sample(mat, rec, wo, rng);
        case GMAT_DIELECTRIC:    return gpu_dielectric_sample(mat, rec, wo, rng);
        case GMAT_DISNEY:        return gpu_disney_sample(mat, rec, wo, rng);
        case GMAT_THIN_GLASS:    return gpu_thin_glass_sample(mat, rec, wo, rng);
        case GMAT_CLOSURE_GRAPH: return gpu_closure_graph_sample(mat, rec, wo, rng);
        default: { GBSDFSample s; s.f=GVec3(0); s.fSpectral=GSampledSpectrum(0.f); s.wi=GVec3(0,1,0); s.pdf=0; s.isDelta=false; return s; }
    }
}

template <typename TRng>
__device__ inline GBSDFSample gpu_material_sample_spectral(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo,
    GSampledWavelengths& wl, TRng* rng)
{
    // pkg64-gpu-sellmeier-upload: dispersive dielectrics need the wavelength-aware
    // sampler (it calls wl.terminateSecondary() on refraction — hero collapse).
    GBSDFSample s = (mat.type == GMAT_DIELECTRIC && mat.isDispersive)
        ? gpu_dielectric_sample_spectral(mat, rec, wo, wl, rng)
        : gpu_material_sample(mat, rec, wo, rng);

    // Delta lobes (dielectric reflect/refract, smooth-glass disney/closure-graph
    // closures — a plain "dielectric" material lowers to GMAT_CLOSURE_GRAPH) carry a
    // radiance-TRANSPORT factor in s.f, NOT a [0,1] albedo: the refraction f is
    // baseColor*eta^2 and eta^2 reaches 2.25 @ ior 1.5, 4.0 @ ior 2.0. The ALBEDO
    // upsampler (gpu_rgbToSampledSpectrum) clamps rgb to [0,1], so the exit eta^2 was
    // clipped to 1.0 and the enter(0.44)/exit(2.25) factors no longer cancelled — the
    // white furnace lost energy scaling with IOR (GPU 0.705 @ ior 1.5 vs CPU 0.985).
    // Factor the >1 magnitude out as a flat spectral scalar and upsample only the
    // normalized tint, mirroring CPU dielectric.cpp:72 (tintSpec * eta^2).
    float m = fmaxf(fmaxf(s.f.x, s.f.y), s.f.z);
    if (s.isDelta && m > 1.0f) {
        s.fSpectral = gpu_rgbToSampledSpectrum(s.f * (1.0f / m), wl, mat.spectralMode) * m;
    } else {
        s.fSpectral = gpu_rgbToSampledSpectrum(s.f, wl, mat.spectralMode);
    }
    return s;
}

__device__ inline float gpu_material_pdf(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    switch (mat.type) {
        case GMAT_LAMBERTIAN: return gpu_lambertian_pdf(mat, rec, wo, wi);
        case GMAT_METAL:      return gpu_metal_pdf(mat, rec, wo, wi);
        case GMAT_DISNEY:     return gpu_disney_pdf(mat, rec, wo, wi);
        case GMAT_CLOSURE_GRAPH: return gpu_closure_graph_pdf(mat, rec, wo, wi);
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
