#pragma once
// pkg64-gpu Phase 1 — device-side Specular Manifold Sampling attempt.
//
// This is a __device__ port of include/astroray/manifold/sms_attempt.h
// (CPU pkg64 Phase 3, PR #230). It is a port of the *math*, not of any
// existing CUDA implementation: the upstream Mitsuba 2 reference runs on
// Enoki/Dr.Jit (JIT-vectorized), not hand-written CUDA, and ships no
// megakernel port. CLAUDE.md §6 is satisfied because the algorithm
// citations are identical to the CPU header — see pkg64-gpu spec
// "Fork-point decision 2".
//
// PORTING NOTES (host-only constructs the CPU header uses, and how the
// device port re-expresses them — pkg64-gpu Non-goal: "only port, do
// not re-implement"; any divergence from the CPU algorithm is a bug):
//   * std::mt19937 / std::uniform_real_distribution → the two uniform
//     seed samples (r1, r2) are passed in explicitly. The megakernel
//     call site (Phase 2) draws them from curand; the Phase 1 unit test
//     injects the *same* (r1, r2) the CPU mt19937 produced so the
//     comparison isolates the Newton + refraction math (not RNG noise).
//   * std::function ConstraintFn/ReprojectFn (newton_iterate.h) → the
//     Newton solve is monomorphized here for the sphere caster (the
//     only caster shape pkg64 Phases 1-3 support, on CPU and GPU). The
//     constraint and reprojection are inlined; the numeric Jacobian /
//     dp = -J^{-1} c / tangent-walk loop is byte-for-byte the same math
//     as newton_iterate.h::solve().
//   * dynamic_cast<const Sphere*> / virtual evalSpectral / getBVH() →
//     the caster is passed as GSMSCaster (built at upload from flagged
//     spheres, Phase 2); BSDF eval uses gpu_material_eval_spectral;
//     visibility uses gpu_bvh_hit. Caster identity is checked via the
//     hit's primId (CPU compares the Hittable* against C.sphere).
//
// References (CLAUDE.md §6, identical to sms_attempt.h /
// half_vector_constraint.h / newton_iterate.h):
//   Zeltner, Georgiev, Jakob, "Specular Manifold Sampling for Rendering
//     High-Frequency Caustics and Glints", SIGGRAPH 2020,
//     DOI 10.1145/3386569.3392408.
//       §4.2 Eq. 4-6  — generalized half-vector constraint.
//       §4.3          — Newton solver loop (numeric Jacobian skeleton).
//       §4.4          — uniform-on-sphere seeding.
//     Mitsuba 2 SMS reference, BSD-3-Clause:
//       https://github.com/tizian/specular-manifold-sampling
//       commit 1f0e40342a8760450d5aa6202ea096feaa70256a (2021-06-27),
//       src/librender/manifold_ss.cpp. No source lines copied; the
//       public-paper math is re-expressed (same as the CPU header).
//   Hanika, Droske, Fascione, "Manifold Next Event Estimation",
//     EGSR 2015, DOI 10.1111/cgf.12681. §4 — wavelength-dependent
//     residual h(λ) = ω_i + η(λ)·ω_o (linear in η, so one Newton solve
//     at λ_hero; the caller passes eta = 1/iorAt(λ_hero)).
//
// Caustic-caster opt-in pattern mirrors Cycles' behavior only
// (intern/cycles/scene/object.h is_caustics_caster); no GPL source.

#include "../gpu_types.h"
#include "../gpu_bvh.h"
#include "../gpu_materials.h"   // gpu_buildONB, gpu_material_eval_spectral

namespace astroray { namespace manifold { namespace device {

// π as a float constant — std::M_PI is host-only; matches the CPU
// header's `2.0f * M_PI` / `M_PI * radius * radius` usage exactly.
__device__ __constant__ constexpr float SMS_PI = 3.14159265358979323846f;

// Device mirror of astroray::manifold::SMSCaster. The CPU struct also
// carries the Sphere* / Material* (for dynamic_cast + identity checks);
// on device the caster is identified by its primitive index (primId,
// the value gpu_bvh_hit writes into GHitRecord) — see runSMSAttempt's
// `vrec.hitObject != C.sphere` check, ported to `vrec.primId != C.primId`.
//
// PHASE 2 UPLOAD CONTRACT (load-bearing — single most likely Phase 2
// latent bug): `primId` MUST be set to the caster sphere's index in
// the SAME d_prims[] array gpu_bvh_hit traverses and writes back into
// GHitRecord.primId (gpu_types.h: GHitRecord::primId "index into
// d_prims[] — set by gpu_bvh_hit"). Phase 2 builds the caster list by
// scanning d_spheres for GSphere::isCausticCaster and recording the
// owning GPrimitive index (NOT the d_spheres index, NOT addObject
// order). If these indices disagree the identity check silently
// rejects every path and SMS contributes nothing — verify against
// scene_upload.cu's gp.index / r.prims ordering.
struct GSMSCaster {
    GVec3 center;
    float radius;
    int   primId;     // index into d_prims[]; identifies the caster sphere
};

// Device mirror of astroray::manifold::SMSConfig (sms_attempt.h:47-52).
struct GSMSConfig {
    int   seeds         = 1;
    int   maxIterations = 20;
    float tolerance     = 1e-4f;
    float contribClamp  = 4.0f;
};

// Device mirror of the CPU LightSample fields runSMSAttempt reads
// (ls.position / ls.normal / ls.emission / ls.pdf). The megakernel
// builds this from the same area/sphere light sampler the spectral
// kernel's NEE uses; the unit test constructs it explicitly.
struct GLightSample {
    GVec3 position;
    GVec3 normal;
    GVec3 emission;
    float pdf;
};

// --- Newton / half-vector helpers (monomorphized) ----------------------

// generalizedHalfVector — half_vector_constraint.h:38-44.
// Zeltner 2020 Eq. 4 (refraction: h = ω_i + η·ω_o).
__device__ inline GVec3 gpu_generalizedHalfVector(
    const GVec3& x0, const GVec3& x1, const GVec3& x2, float eta)
{
    GVec3 wi = (x0 - x1).normalized();
    GVec3 wo = (x2 - x1).normalized();
    return wi + wo * eta;   // refraction == true (sphere caster, pkg64)
}

// halfVectorResidual — half_vector_constraint.h:52-61.
// Zeltner 2020 Eq. 5 / Hanika 2015 Eq. 8: project the normalized
// half-vector onto the tangent frame (s1, t1).
__device__ inline void gpu_halfVectorResidual(
    const GVec3& x0, const GVec3& x1, const GVec3& x2,
    const GVec3& s1, const GVec3& t1, float eta,
    float& cu, float& cv)
{
    GVec3 h = gpu_generalizedHalfVector(x0, x1, x2, eta);
    float len = sqrtf(h.length2());
    if (len > 1e-12f) h = h * (1.0f / len);
    cu = h.dot(s1);
    cv = h.dot(t1);
}

// Sphere reprojection — the `reproject` lambda in sms_attempt.h:131-143.
// Tangent-plane offset (du,dv) → nearest point back on the caster sphere.
__device__ inline bool gpu_sphereReproject(
    const GVec3& center, float radius,
    const GVec3& p, const GVec3& sIn, const GVec3& tIn,
    float du, float dv,
    GVec3& outX, GVec3& outN, GVec3& outS, GVec3& outT)
{
    GVec3 q = p + sIn * du + tIn * dv;
    GVec3 d = q - center;
    float len2 = d.length2();
    if (len2 < 1e-12f) return false;
    GVec3 nNew = d * (1.0f / sqrtf(len2));
    outX = center + nNew * radius;
    outN = nNew;
    gpu_buildONB(nNew, outS, outT);
    return true;
}

struct GNewtonResult {
    GVec3 x1, n1, s1, t1;
    bool  converged;
};

// Monomorphized port of newton_iterate.h::solve() — the constraint is
// the half-vector residual at fixed (x0, x2=light, eta) and the
// reprojection is onto the caster sphere. The numeric central-difference
// 2×2 Jacobian, det guard, dp = -J^{-1}·c and tangent-walk step are the
// same arithmetic as newton_iterate.h:76-115 (Zeltner 2020 §4.3).
__device__ inline GNewtonResult gpu_smsNewtonSolve(
    const GVec3& x1Init, const GVec3& n1Init,
    const GVec3& s1Init, const GVec3& t1Init,
    const GVec3& x0, const GVec3& xLight, float eta,
    const GVec3& center, float radius,
    int maxIterations, float tolerance)
{
    const float step    = 1e-3f;   // newton_iterate.h NewtonConfig::step
    const float damping = 1.0f;    // newton_iterate.h NewtonConfig::damping

    GNewtonResult R;
    R.x1 = x1Init; R.n1 = n1Init; R.s1 = s1Init; R.t1 = t1Init;
    R.converged = false;

    for (int it = 0; it < maxIterations; ++it) {
        float cu, cv;
        gpu_halfVectorResidual(x0, R.x1, xLight, R.s1, R.t1, eta, cu, cv);
        float rn = sqrtf(cu * cu + cv * cv);
        if (rn < tolerance) { R.converged = true; break; }

        const float h = step;
        GVec3 xP, nP, sP, tP;
        float cup_u, cup_v, cum_u, cum_v, cvp_u, cvp_v, cvm_u, cvm_v;
        if (!gpu_sphereReproject(center, radius, R.x1, R.s1, R.t1,  h, 0, xP, nP, sP, tP)) break;
        gpu_halfVectorResidual(x0, xP, xLight, sP, tP, eta, cup_u, cup_v);
        if (!gpu_sphereReproject(center, radius, R.x1, R.s1, R.t1, -h, 0, xP, nP, sP, tP)) break;
        gpu_halfVectorResidual(x0, xP, xLight, sP, tP, eta, cum_u, cum_v);
        if (!gpu_sphereReproject(center, radius, R.x1, R.s1, R.t1, 0,  h, xP, nP, sP, tP)) break;
        gpu_halfVectorResidual(x0, xP, xLight, sP, tP, eta, cvp_u, cvp_v);
        if (!gpu_sphereReproject(center, radius, R.x1, R.s1, R.t1, 0, -h, xP, nP, sP, tP)) break;
        gpu_halfVectorResidual(x0, xP, xLight, sP, tP, eta, cvm_u, cvm_v);

        const float inv2h = 0.5f / h;
        float J00 = (cup_u - cum_u) * inv2h;
        float J10 = (cup_v - cum_v) * inv2h;
        float J01 = (cvp_u - cvm_u) * inv2h;
        float J11 = (cvp_v - cvm_v) * inv2h;

        float det = J00 * J11 - J01 * J10;
        if (fabsf(det) < 1e-12f) break;
        float invDet = 1.0f / det;

        float du = -invDet * ( J11 * cu - J01 * cv) * damping;
        float dv = -invDet * (-J10 * cu + J00 * cv) * damping;

        GVec3 xNew, nNew, sNew, tNew;
        if (!gpu_sphereReproject(center, radius, R.x1, R.s1, R.t1, du, dv, xNew, nNew, sNew, tNew)) break;
        R.x1 = xNew; R.n1 = nNew; R.s1 = sNew; R.t1 = tNew;
    }
    return R;
}

// --- Device runSMSAttempt ---------------------------------------------
//
// Arg-for-arg mirror of astroray::manifold::runSMSAttempt
// (sms_attempt.h:87-202). `renderer` → BVH/prim/material device arrays;
// `std::mt19937& gen` → explicit (r1, r2); SMSCaster → GSMSCaster;
// LightSample → GLightSample. Outputs identical: hero-aware fSpec,
// scalar weight (G·seedArea)/(pdf·pick·seeds), light colour, Schlick
// transmittance, and wi at x0.
__device__ inline bool runSMSAttemptDevice(
    const GBVHNode*   nodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GMaterial*  materials,
    const GHitRecord& x0Rec,
    const GRay&       primary,
    const GSampledWavelengths& lambdas,
    float r1, float r2,
    const GSMSCaster& C,
    float eta,
    float casterPickPdf,
    const GLightSample& ls,
    const GSMSConfig& cfg,
    GSampledSpectrum& outFSpec,
    float& outScalarWeight,
    GVec3& outLeRGB,
    float& outTr,
    GVec3& outWiX0)
{
    GVec3 wo_eye = (-primary.direction).normalized();

    // Uniform seed on the side of the sphere facing x0 (Zeltner 2020 §4.4).
    GVec3 dirToX0 = (x0Rec.point - C.center).normalized();
    GVec3 sphU, sphV;
    gpu_buildONB(dirToX0, sphU, sphV);
    float phi  = 2.0f * SMS_PI * r1;
    float cosT = sqrtf(1.0f - r2);
    float sinT = sqrtf(r2);
    GVec3 nSeed = (sphU * (sinT * cosf(phi)) +
                   sphV * (sinT * sinf(phi)) +
                   dirToX0 * cosT).normalized();
    GVec3 x1 = C.center + nSeed * C.radius;
    GVec3 t1, b1; gpu_buildONB(nSeed, t1, b1);

    // Hanika 2015 §4 half-vector residual at η(λ_hero); the residual
    // decouples per-wavelength because h(λ) = ω_i + η(λ)·ω_o is linear
    // in the wavelength-dependent η.
    GNewtonResult R = gpu_smsNewtonSolve(
        x1, nSeed, t1, b1, x0Rec.point, ls.position, eta,
        C.center, C.radius, cfg.maxIterations, cfg.tolerance);
    if (!R.converged) return false;

    GVec3 dirToX1 = R.x1 - x0Rec.point;
    float distX0X1_2 = dirToX1.length2();
    if (distX0X1_2 < 1e-8f) return false;
    float distX0X1 = sqrtf(distX0X1_2);
    GVec3 wi_x0 = dirToX1 * (1.0f / distX0X1);

    GHitRecord vrec;
    if (!gpu_bvh_hit(nodes, prims, tris, spheres,
                     GRay(x0Rec.point, wi_x0), 0.001f,
                     distX0X1 + 1e-2f, vrec))
        return false;
    // CPU: `vrec.hitObject != static_cast<const Hittable*>(C.sphere)`.
    // Device identity is the primitive index gpu_bvh_hit records.
    if (vrec.primId != C.primId)
        return false;

    GVec3 wi_in = -wi_x0;
    GVec3 nEntry = R.n1;
    float cosI = -wi_in.dot(nEntry);
    float sin2T = eta * eta * fmaxf(0.0f, 1.0f - cosI * cosI);
    if (sin2T >= 1.0f) return false;  // TIR (wavelength-specific)
    GVec3 refracted = wi_in * eta + nEntry * (eta * cosI - sqrtf(1.0f - sin2T));
    refracted = refracted.normalized();

    GVec3 toLight = ls.position - R.x1;
    float distLight2 = toLight.length2();
    float distLight = sqrtf(distLight2);
    GVec3 dirLight = toLight * (1.0f / distLight);
    GVec3 exitOrigin = R.x1 + refracted * (2.0f * C.radius + 1e-3f);
    GHitRecord lrec;
    bool hitOcc = gpu_bvh_hit(nodes, prims, tris, spheres,
                              GRay(exitOrigin, dirLight), 0.001f,
                              distLight + 1e-2f, lrec);
    // CPU allows the occluder through iff it is an infinite light
    // (lrec.hitObject->isInfiniteLight()). On the GPU scene, infinite
    // lights (distant/env) are GPRIM_SKIP / the env map — gpu_bvh_hit
    // never returns them as a real primitive hit — so a real hit here
    // is always a finite occluder. Faithful device equivalent of
    // sms_attempt.h:178-181; documented CPU↔GPU semantic note.
    if (hitOcc) return false;

    float F0 = (1.0f - eta) / (1.0f + eta);
    F0 *= F0;
    float fresnel = F0 + (1.0f - F0) * powf(fmaxf(0.0f, 1.0f - cosI), 5.0f);
    outTr = 1.0f - fresnel;

    outFSpec = gpu_material_eval_spectral(
        materials[x0Rec.materialId], const_cast<GHitRecord&>(x0Rec),
        wo_eye, wi_x0, lambdas);

    float cosSeed = fmaxf(1e-3f, nSeed.dot(dirToX0));
    float seedAreaWeight = (SMS_PI * C.radius * C.radius) / cosSeed;

    float cosX0 = fmaxf(0.0f, x0Rec.normal.dot(wi_x0));
    float cosLight = fmaxf(0.0f, ls.normal.dot(-dirLight));
    float G = cosX0 * cosLight / fmaxf(distX0X1_2 * distLight2, 1e-6f);

    outLeRGB = ls.emission;
    outScalarWeight = (G * seedAreaWeight) /
                      (ls.pdf * casterPickPdf * static_cast<float>(cfg.seeds));
    outWiX0 = wi_x0;
    return true;
}

}}}  // namespace astroray::manifold::device
