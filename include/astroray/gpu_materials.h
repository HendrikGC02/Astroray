#pragma once
// GPU material evaluation — ported from raytracer.h and advanced_features.h.
// All formulas match the CPU reference exactly (same fixes applied).
// Only include this from .cu files compiled by nvcc.

#include "gpu_types.h"
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
// Sampling helpers
// ---------------------------------------------------------------------------
__device__ inline GVec3 gpu_randomCosineDir(curandState* rng) {
    float r1 = curand_uniform(rng);
    float r2 = curand_uniform(rng);
    float z   = sqrtf(1.f - r2);
    float phi = 2.f * M_PI_F * r1;
    return GVec3(cosf(phi)*sqrtf(r2), sinf(phi)*sqrtf(r2), z);
}

__device__ inline GVec3 gpu_randomInUnitDisk(curandState* rng) {
    GVec3 p;
    do {
        p.x = curand_uniform(rng)*2.f - 1.f;
        p.y = curand_uniform(rng)*2.f - 1.f;
        p.z = 0.f;
    } while (p.length2() >= 1.f);
    return p;
}

// ---------------------------------------------------------------------------
// Camera ray generation (with DOF)
// ---------------------------------------------------------------------------
__device__ inline GRay gpu_generateCameraRay(
    const GCameraParams& cam, int px, int py, curandState* rng)
{
    float u = (px + curand_uniform(rng)) / (cam.width  - 1);
    float v = 1.f - (py + curand_uniform(rng)) / (cam.height - 1);

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
    const GMaterial& mat, const GHitRecord& rec, const GVec3& /*wo*/, const GVec3& wi)
{
    float NdotL = rec.normal.dot(wi);
    if (NdotL <= 0.f) return GVec3(0.f);
    return mat.baseColor * (1.f / M_PI_F) * NdotL;
}

__device__ inline GBSDFSample gpu_lambertian_sample(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& /*wo*/, curandState* rng)
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

__device__ inline GBSDFSample gpu_metal_sample(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, curandState* rng)
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
    float r1  = curand_uniform(rng);
    float r2  = curand_uniform(rng);
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

__device__ inline GBSDFSample gpu_dielectric_sample(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, curandState* rng)
{
    GBSDFSample s;
    s.isDelta = true;
    rec.isDelta = true;

    float cosTheta = wo.dot(rec.normal);
    float etaI = 1.f, etaT = mat.ior;
    GVec3 n = rec.normal;
    if (cosTheta < 0.f) { cosTheta = -cosTheta; float tmp=etaI; etaI=etaT; etaT=tmp; n = -n; }

    float eta      = etaI / etaT;
    float sinTheta = sqrtf(fmaxf(0.f, 1.f - cosTheta*cosTheta));
    bool  tir      = eta * sinTheta > 1.f;

    float fresnel = gpu_fresnelDielectric(cosTheta, etaI, etaT);

    if (tir || curand_uniform(rng) < fresnel) {
        // Reflect: wi = 2*(wo·n)*n - wo
        s.wi  = n * (2.f * wo.dot(n)) - wo;
        s.f   = GVec3(1.f);
        s.pdf = 1.f;
    } else {
        GVec3 wt_perp   = (wo - n*cosTheta) * (-eta);
        GVec3 wt_para   = n * (-sqrtf(fabsf(1.f - wt_perp.length2())));
        s.wi  = (wt_perp + wt_para).normalized();
        s.f   = GVec3(eta * eta);
        s.pdf = 1.f;
    }
    return s;
}

// ===========================================================================
// ===  Thin glass / architectural glazing  ===================================
// ===========================================================================

__device__ inline GVec3 gpu_sampleCone(const GVec3& dir, float roughness, curandState* rng) {
    GVec3 w = dir.normalized();
    if (roughness <= 0.001f) return w;

    GVec3 a = fabsf(w.x) > 0.9f ? GVec3(0.f, 1.f, 0.f) : GVec3(1.f, 0.f, 0.f);
    GVec3 u = (a - w * a.dot(w)).normalized();
    GVec3 v = w.cross(u);
    float maxAngle = fminf(fmaxf(roughness, 0.f), 1.f) * 0.35f;
    float cosMax = cosf(maxAngle);
    float cosTheta = 1.f - curand_uniform(rng) * (1.f - cosMax);
    float sinTheta = sqrtf(fmaxf(0.f, 1.f - cosTheta * cosTheta));
    float phi = 2.f * M_PI_F * curand_uniform(rng);
    return (u * (cosf(phi) * sinTheta) +
            v * (sinf(phi) * sinTheta) +
            w * cosTheta).normalized();
}

__device__ inline GBSDFSample gpu_thin_glass_sample(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, curandState* rng)
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
    if (curand_uniform(rng) < reflectProb) {
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

__device__ inline float gpu_D_GTR2(float NdotH, float a) {
    float a2 = a*a;
    float t  = 1.f + (a2 - 1.f) * NdotH*NdotH;
    return a2 / (M_PI_F * t*t + 0.001f);
}

__device__ inline float gpu_smithG_GGX(float NdotV, float alphaG) {
    float a = alphaG*alphaG;
    float b = NdotV*NdotV;
    return 1.f / (NdotV + sqrtf(a + b - a*b) + 0.001f);
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

__device__ inline GVec3 gpu_disney_sampleGgxMicroNormal(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, curandState* rng)
{
    float a = fmaxf(mat.roughness*mat.roughness, 0.0064f);
    float r1 = curand_uniform(rng);
    float r2 = curand_uniform(rng);
    float phi = 2.f * M_PI_F * r1;
    float cosT = sqrtf((1.f - r2) / (1.f + (a*a - 1.f)*r2));
    float sinT = sqrtf(fmaxf(0.f, 1.f - cosT*cosT));
    GVec3 h(cosf(phi)*sinT, sinf(phi)*sinT, cosT);
    h = (rec.tangent*h.x + rec.bitangent*h.y + rec.normal*h.z).normalized();
    return h.dot(wo) < 0.f ? -h : h;
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

__device__ inline float gpu_disney_microfacetReflectionPdf(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    if (rec.normal.dot(wo) * rec.normal.dot(wi) <= 0.f) return 0.f;
    GVec3 h = (wo + wi).normalized();
    if (h.length2() <= 1e-10f) return 0.f;
    if (h.dot(rec.normal) < 0.f) h = -h;
    float NdotH = fabsf(rec.normal.dot(h));
    float HdotV = fabsf(h.dot(wo));
    if (NdotH <= 0.f || HdotV <= 0.f) return 0.f;
    float a = fmaxf(mat.roughness*mat.roughness, 0.0064f);
    float D = gpu_D_GTR2(NdotH, a);
    return D * NdotH / (4.f * HdotV + 1e-6f);
}

__device__ inline GVec3 gpu_disney_roughTransmissionEval(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    float cosO = rec.normal.dot(wo);
    float cosI = rec.normal.dot(wi);
    if (cosO == 0.f || cosI == 0.f || cosO*cosI >= 0.f) return GVec3(0.f);
    bool entering = cosO > 0.f;
    float etaI = entering ? 1.f : mat.ior;
    float etaT = entering ? mat.ior : 1.f;
    float eta = etaI / etaT;
    GVec3 h = (wo + wi*eta).normalized();
    if (h.length2() <= 1e-10f) return GVec3(0.f);
    if (h.dot(rec.normal) < 0.f) h = -h;

    float HdotO = wo.dot(h);
    float HdotI = wi.dot(h);
    if (HdotO * HdotI >= 0.f) return GVec3(0.f);
    float NdotH = fabsf(rec.normal.dot(h));
    float absCosO = fabsf(cosO);
    float denom = etaI*HdotO + etaT*HdotI;
    float denom2 = denom*denom;
    if (NdotH <= 0.f || absCosO <= 0.f || denom2 <= 1e-10f) return GVec3(0.f);

    float a = fmaxf(mat.roughness*mat.roughness, 0.0064f);
    float D = gpu_D_GTR2(NdotH, a);
    float G = gpu_smithG_GGX(absCosO, a) * gpu_smithG_GGX(fabsf(cosI), a);
    float F = gpu_disney_fresnelDielectric(HdotO, etaI, etaT);
    float jacobianAndCos = fabsf(HdotO * HdotI) * (etaT * etaT) /
                           (absCosO * denom2 + 1e-6f);
    float scale = (1.f - mat.metallic) * mat.transmission * (1.f - F) * D * G * jacobianAndCos;
    GVec3 result = mat.baseColor * scale;
    result.x = fminf(fmaxf(result.x, 0.f), 4.f);
    result.y = fminf(fmaxf(result.y, 0.f), 4.f);
    result.z = fminf(fmaxf(result.z, 0.f), 4.f);
    return result;
}

__device__ inline float gpu_disney_roughTransmissionPdf(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    float cosO = rec.normal.dot(wo);
    float cosI = rec.normal.dot(wi);
    if (cosO == 0.f || cosI == 0.f || cosO*cosI >= 0.f) return 0.f;
    bool entering = cosO > 0.f;
    float etaI = entering ? 1.f : mat.ior;
    float etaT = entering ? mat.ior : 1.f;
    float eta = etaI / etaT;
    GVec3 h = (wo + wi*eta).normalized();
    if (h.length2() <= 1e-10f) return 0.f;
    if (h.dot(rec.normal) < 0.f) h = -h;

    float HdotO = wo.dot(h);
    float HdotI = wi.dot(h);
    if (HdotO * HdotI >= 0.f) return 0.f;
    float NdotH = fabsf(rec.normal.dot(h));
    float denom = etaI*HdotO + etaT*HdotI;
    float denom2 = denom*denom;
    if (NdotH <= 0.f || denom2 <= 1e-10f) return 0.f;

    float a = fmaxf(mat.roughness*mat.roughness, 0.0064f);
    float D = gpu_D_GTR2(NdotH, a);
    float dwhDwi = fabsf((etaT * etaT * HdotI) / (denom2 + 1e-6f));
    float F = gpu_disney_fresnelDielectric(HdotO, etaI, etaT);
    return mat.transmission * (1.f - F) * D * NdotH * dwhDwi;
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
    GVec3 diffuse = (1.f / M_PI_F) * Cdlin * Fd;

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

__device__ inline GBSDFSample gpu_disney_sample(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, curandState* rng)
{
    GBSDFSample s;
    s.f   = GVec3(0.f);
    s.pdf = 0.f;
    s.isDelta = false;

    // Transmission lobe
    if (mat.transmission > 0.f && curand_uniform(rng) < mat.transmission) {
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
            GVec3 m = gpu_disney_sampleGgxMicroNormal(mat, rec, wo, rng);
            float microCos = fabsf(wo.dot(m));
            float microFresnel = gpu_disney_fresnelDielectric(microCos, etaI, etaT);
            if (cannotRef || curand_uniform(rng) < microFresnel) {
                s.wi = (m * (2.f * wo.dot(m)) - wo).normalized();
                if (s.wi.dot(rec.normal) * wo.dot(rec.normal) > 0.f) {
                    s.f = gpu_disney_eval(mat, rec, wo, s.wi);
                    s.pdf = mat.transmission * microFresnel *
                            gpu_disney_microfacetReflectionPdf(mat, rec, wo, s.wi);
                }
            } else if (gpu_disney_refractMicro(wo, m, eta, s.wi)) {
                s.f = gpu_disney_roughTransmissionEval(mat, rec, wo, s.wi);
                s.pdf = gpu_disney_roughTransmissionPdf(mat, rec, wo, s.wi);
            }
            if (s.pdf > 0.f && s.f.length2() > 0.f) {
                s.isDelta = false;
                rec.isDelta = false;
                return s;
            }
        }

        if (cannotRef || curand_uniform(rng) < fresnel) {
            s.wi  = n * (2.f * wo.dot(n)) - wo;
            s.f   = GVec3(1.f);
            s.pdf = fresnel * mat.transmission;
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

    if (curand_uniform(rng) * total < diffW) {
        GVec3 lw = gpu_randomCosineDir(rng);
        s.wi = rec.tangent*lw.x + rec.bitangent*lw.y + rec.normal*lw.z;
        s.f  = gpu_disney_eval(mat, rec, wo, s.wi);
        s.pdf = rec.normal.dot(s.wi) / M_PI_F * (diffW / total);
    } else {
        float a   = fmaxf(mat.roughness*mat.roughness, 0.0064f);
        float r1  = curand_uniform(rng);
        float r2  = curand_uniform(rng);
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
            s.pdf = D * NdotH / (4.f*HdotV + 0.001f) * (specW / total);
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
    float p = 0.f;
    if (diffW > 0.f)
        p += (rec.normal.dot(wi) / M_PI_F) * (diffW / total);
    if (specW > 0.f) {
        float a     = mat.roughness * mat.roughness;
        float NdotH = rec.normal.dot(H);
        float HdotV = H.dot(wo);
        float D     = gpu_D_GTR2(NdotH, a);
        p += (D * NdotH / (4.f*HdotV + 0.001f)) * (specW / total);
    }
    if (mat.transmission > 0.f && mat.roughness > 0.03f) {
        bool entering = rec.normal.dot(wo) > 0.f;
        float etaI = entering ? 1.f : mat.ior;
        float etaT = entering ? mat.ior : 1.f;
        float F = gpu_disney_fresnelDielectric(wo.dot(H), etaI, etaT);
        p += mat.transmission * F * gpu_disney_microfacetReflectionPdf(mat, rec, wo, wi);
    }
    return p;
}

// ===========================================================================
// ===  Dispatch: switch on GMaterialType  ====================================
// ===========================================================================

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
        default:                 return GVec3(0.f);
    }
}

__device__ inline GBSDFSample gpu_material_sample(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, curandState* rng)
{
    switch (mat.type) {
        case GMAT_LAMBERTIAN:    return gpu_lambertian_sample(mat, rec, wo, rng);
        case GMAT_METAL:         return gpu_metal_sample(mat, rec, wo, rng);
        case GMAT_DIELECTRIC:    return gpu_dielectric_sample(mat, rec, wo, rng);
        case GMAT_DISNEY:        return gpu_disney_sample(mat, rec, wo, rng);
        case GMAT_THIN_GLASS:    return gpu_thin_glass_sample(mat, rec, wo, rng);
        default: { GBSDFSample s; s.f=GVec3(0); s.wi=GVec3(0,1,0); s.pdf=0; s.isDelta=false; return s; }
    }
}

__device__ inline float gpu_material_pdf(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi)
{
    switch (mat.type) {
        case GMAT_LAMBERTIAN: return gpu_lambertian_pdf(mat, rec, wo, wi);
        case GMAT_METAL:      return gpu_metal_pdf(mat, rec, wo, wi);
        case GMAT_DISNEY:     return gpu_disney_pdf(mat, rec, wo, wi);
        default:              return 0.f;
    }
}

__device__ inline GVec3 gpu_material_emitted(
    const GMaterial& mat, bool frontFace)
{
    if (mat.type == GMAT_DIFFUSE_LIGHT && frontFace)
        return mat.baseColor * mat.emissionIntensity;
    return GVec3(0.f);
}
