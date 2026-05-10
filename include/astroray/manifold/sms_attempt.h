#pragma once
// pkg64 Phase 3 — shared SMS connection helper.
//
// Factored out of plugins/integrators/sms_caustic_path_tracer.cpp so the
// default `path_tracer` (plugins/integrators/spectral_path_tracer.cpp)
// can MIS-combine an SMS connection attempt with NEE direct light, and
// the opt-in `sms_caustic_path_tracer` can keep emitting the same Phase
// 1+2 contribution. Both integrators share runSMSAttempt() — there is
// only one Newton + refraction + visibility code path.
//
// References (CLAUDE.md §6, identical to sms_caustic_path_tracer.cpp):
//   Zeltner et al., SIGGRAPH 2020 "Specular Manifold Sampling",
//     DOI 10.1145/3386569.3392408. §4.2 Newton on the half-vector
//     constraint; §4.4 uniform-on-sphere seeding.
//   Hanika et al., EGSR 2015 "Manifold Next Event Estimation",
//     DOI 10.1111/cgf.12681. §4 — wavelength-dependent residual
//     h(λ) = ω_i + η(λ)·ω_o (re-derived from the paper, no Cycles
//     code consulted).
//   Mitsuba 2 SMS reference, BSD-3-Clause:
//     https://github.com/tizian/specular-manifold-sampling
//     commit 1f0e40342a8760450d5aa6202ea096feaa70256a (2021-06-27).
//
// Caustic-caster opt-in pattern is Cycles' (intern/cycles/scene/object.h
// `is_caustics_caster`); only the *behavior* is mirrored, no GPL source.

#include "../../raytracer.h"
#include "../shapes.h"
#include "../spectrum.h"
#include "half_vector_constraint.h"
#include "newton_iterate.h"

#include <algorithm>
#include <cmath>
#include <random>
#include <vector>

namespace astroray::manifold {

struct SMSCaster {
    const Sphere*   sphere;
    float           radius;
    Vec3            center;
    const Material* mat;
    float           iorFlat;
};

struct SMSConfig {
    int   seeds         = 1;
    int   maxIterations = 20;
    float tolerance     = 1e-4f;
    float contribClamp  = 4.0f;
};

// Walk the scene and collect refractive sphere casters. When
// `requireFlag` is true (Phase 3 default integrator path) only objects
// the caller marked with Hittable::setCausticCaster(true) are returned;
// when false (sms_caustic_path_tracer back-compat path) every
// transmissive sphere with IOR > 1 is a candidate.
inline void gatherSphereCasters(const Renderer& renderer,
                                std::vector<SMSCaster>& out,
                                bool requireFlag) {
    out.clear();
    for (const auto& obj : renderer.getScene()) {
        if (requireFlag && !obj->isCausticCaster()) continue;
        const auto* sph = dynamic_cast<const Sphere*>(obj.get());
        if (!sph) continue;
        const auto& mat = sph->getMaterial();
        if (!mat || !mat->isTransmissive()) continue;
        float ior = mat->getIOR();
        if (ior <= 1.0f) continue;
        out.push_back(SMSCaster{sph, sph->getRadius(), sph->getCenter(),
                                 mat.get(), ior});
    }
}

// One Newton seed → optional valid SMS path. ok=false on miss / TIR /
// occlusion. The geometric pieces (residual, refraction, Fresnel) are
// wavelength-aware via `eta`; callers pass either the flat IOR ratio
// (Phase 1) or 1/iorAt(λ_hero) (Phase 2/3).
//
// Outputs on ok=true:
//   outFSpec        BSDF at x0 toward x1, queried on the caller's lambdas
//   outScalarWeight (G · seedAreaWeight) / (ls.pdf · casterPickPdf · seeds)
//   outLeRGB        emitter colour at the sampled light point
//   outTr           Schlick transmittance with hero-η at the entry vertex
//   outWiX0         direction at x0 toward the converged x1 (for MIS pdf)
inline bool runSMSAttempt(const Renderer& renderer,
                          const HitRecord& x0Rec,
                          const Ray& primary,
                          const astroray::SampledWavelengths& lambdas,
                          std::mt19937& gen,
                          const SMSCaster& C,
                          float eta,
                          float casterPickPdf,
                          const LightSample& ls,
                          const SMSConfig& cfg,
                          astroray::SampledSpectrum& outFSpec,
                          float& outScalarWeight,
                          Vec3& outLeRGB,
                          float& outTr,
                          Vec3& outWiX0) {
    std::uniform_real_distribution<float> u01(0.0f, 1.0f);
    Vec3 wo_eye = -primary.direction.normalized();
    const auto& bvh = renderer.getBVH();
    if (!bvh) return false;

    // Uniform seed on the side of the sphere facing x0 (Zeltner 2020 §4.4).
    Vec3 dirToX0 = (x0Rec.point - C.center).normalized();
    Vec3 sphU, sphV;
    buildOrthonormalBasis(dirToX0, sphU, sphV);
    float r1 = u01(gen), r2 = u01(gen);
    float phi = 2.0f * M_PI * r1;
    float cosT = std::sqrt(1.0f - r2);
    float sinT = std::sqrt(r2);
    Vec3 nSeed = (sphU * (sinT * std::cos(phi)) +
                  sphV * (sinT * std::sin(phi)) +
                  dirToX0 * cosT).normalized();
    Vec3 x1 = C.center + nSeed * C.radius;
    Vec3 t1, b1; buildOrthonormalBasis(nSeed, t1, b1);

    // Hanika 2015 §4 half-vector residual at η(λ_hero); the residual
    // decouples per-wavelength because h(λ) = ω_i + η(λ)·ω_o is linear
    // in the wavelength-dependent η.
    auto constraint = [&](const Vec3& p, const Vec3& /*n*/,
                          const Vec3& s, const Vec3& t) {
        return halfVectorResidual(x0Rec.point, p, ls.position,
                                  s, t, eta, /*refraction=*/true);
    };
    const float radius = C.radius;
    const Vec3& centerRef = C.center;
    auto reproject = [&](const Vec3& p, const Vec3& sIn, const Vec3& tIn,
                         float du, float dv,
                         Vec3& outX, Vec3& outN, Vec3& outS, Vec3& outT) {
        Vec3 q = p + sIn * du + tIn * dv;
        Vec3 d = q - centerRef;
        float len2 = d.length2();
        if (len2 < 1e-12f) return false;
        Vec3 nNew = d * (1.0f / std::sqrt(len2));
        outX = centerRef + nNew * radius;
        outN = nNew;
        buildOrthonormalBasis(nNew, outS, outT);
        return true;
    };

    NewtonConfig ncfg;
    ncfg.maxIterations = cfg.maxIterations;
    ncfg.tolerance     = cfg.tolerance;
    NewtonResult R = solve(x1, nSeed, t1, b1, constraint, reproject, ncfg);
    if (!R.converged) return false;

    Vec3 dirToX1 = R.x1 - x0Rec.point;
    float distX0X1_2 = dirToX1.length2();
    if (distX0X1_2 < 1e-8f) return false;
    float distX0X1 = std::sqrt(distX0X1_2);
    Vec3 wi_x0 = dirToX1 * (1.0f / distX0X1);
    HitRecord vrec;
    if (!bvh->hit(Ray(x0Rec.point, wi_x0), 0.001f, distX0X1 + 1e-2f, vrec))
        return false;
    if (vrec.hitObject != static_cast<const Hittable*>(C.sphere))
        return false;

    Vec3 wi_in = -wi_x0;
    Vec3 nEntry = R.n1;
    float cosI = -wi_in.dot(nEntry);
    float sin2T = eta * eta * std::max(0.0f, 1.0f - cosI * cosI);
    if (sin2T >= 1.0f) return false;  // TIR (wavelength-specific)
    Vec3 refracted = wi_in * eta + nEntry * (eta * cosI - std::sqrt(1.0f - sin2T));
    refracted = refracted.normalized();

    Vec3 toLight = ls.position - R.x1;
    float distLight2 = toLight.length2();
    float distLight = std::sqrt(distLight2);
    Vec3 dirLight = toLight * (1.0f / distLight);
    Vec3 exitOrigin = R.x1 + refracted * (2.0f * radius + 1e-3f);
    HitRecord lrec;
    bool hitOcc = bvh->hit(Ray(exitOrigin, dirLight), 0.001f,
                           distLight + 1e-2f, lrec);
    if (hitOcc && !(lrec.hitObject &&
                    lrec.hitObject->isInfiniteLight())) {
        return false;
    }

    float F0 = (1.0f - eta) / (1.0f + eta);
    F0 *= F0;
    float fresnel = F0 + (1.0f - F0) * std::pow(std::max(0.0f, 1.0f - cosI), 5.0f);
    outTr = 1.0f - fresnel;

    outFSpec = x0Rec.material->evalSpectral(x0Rec, wo_eye, wi_x0, lambdas);

    float cosSeed = std::max(1e-3f, nSeed.dot(dirToX0));
    float seedAreaWeight = (M_PI * radius * radius) / cosSeed;

    float cosX0 = std::max(0.0f, x0Rec.normal.dot(wi_x0));
    float cosLight = std::max(0.0f, ls.normal.dot(-dirLight));
    float G = cosX0 * cosLight / std::max(distX0X1_2 * distLight2, 1e-6f);

    outLeRGB = ls.emission;
    outScalarWeight = (G * seedAreaWeight) /
                      (ls.pdf * casterPickPdf * static_cast<float>(cfg.seeds));
    outWiX0 = wi_x0;
    return true;
}

}  // namespace astroray::manifold
