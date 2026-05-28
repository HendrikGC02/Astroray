#pragma once
// pkg106 Chunk D (radiance) — multi-vertex mesh MNEE connection for the live
// SMS integrator. Gathers triangle-mesh caustic casters, seeds the specular
// chain from the receiver->light ray (mesh_caustic.h), solves the CHROMATIC
// chain (per-ray hero-wavelength IOR -> per-wavelength bend -> spatial rainbow),
// and returns the hero-wavelength path contribution.
//
// Mirrors Cycles mnee.h mnee_path_contribution (lines 790+) evaluated at the
// hero wavelength: receiver BSDF * product of per-face transmittances * a
// clamped generalized-geometry term * Le / pdf. The chromatic spread is the
// same hero-wavelength mechanism as the CPU dielectric (dielectric.cpp:181-188)
// and the GPU dispersion (pkg64-gpu Session 2): different rays sample different
// hero lambda -> different Sellmeier IOR -> different specular vertex positions
// -> the rainbow emerges over many rays.
//
// First-version geometry term is a clamped solid-angle factor (Cycles clamps G
// to 2.0 for stability); the full block-tridiagonal transfer matrix
// (mnee_compute_transfer_matrix) is a refinement if the caustic brightness
// needs it. The SPATIAL spread (what hue_spread measures) comes from the
// chromatic chain solve, not the geometry-term magnitude.

#include "../../raytracer.h"
#include "../shapes.h"
#include "../spectrum.h"
#include "mesh_caustic.h"
#include "sms_attempt.h"   // SMSConfig, SMSCaster (sphere path lives alongside)
#include <cmath>
#include <vector>

namespace astroray::manifold {

// Gather flat triangle caustic-casters (flagged via setCausticCaster) into
// CausticTri, and return a representative dispersive Material* (for iorAt(lambda)).
inline const Material* gatherTriangleCasters(const Renderer& renderer,
                                             std::vector<CausticTri>& out) {
    out.clear();
    const Material* mat = nullptr;
    for (const auto& obj : renderer.getScene()) {
        if (!obj || !obj->isCausticCaster()) continue;
        const auto* tri = dynamic_cast<const Triangle*>(obj.get());
        if (!tri) continue;
        const auto& m = tri->getMaterial();
        if (!m || !m->isTransmissive()) continue;
        out.push_back(CausticTri{tri->getV0(), tri->getV1(), tri->getV2()});
        if (!mat) mat = m.get();
    }
    return mat;
}

// One chromatic mesh-MNEE connection attempt. Returns the hero-channel
// contribution (>= 0), or 0 on miss / non-convergence / occlusion.
inline float runMeshSMSAttempt(const Renderer& renderer,
                               const HitRecord& x0Rec, const Ray& primary,
                               const astroray::SampledWavelengths& lambdas,
                               const std::vector<CausticTri>& tris,
                               const Material* casterMat, float casterPickPdf,
                               const LightSample& ls, const SMSConfig& cfg) {
    const auto& bvh = renderer.getBVH();
    if (!bvh || tris.empty() || ls.pdf <= 0.0f) return 0.0f;

    // Hero-wavelength Sellmeier IOR — the only place wavelength enters the solve.
    const float lambdaHero = lambdas.lambda(0);
    const float iorHero = casterMat ? casterMat->iorAt(lambdaHero) : 1.5f;
    if (iorHero <= 1.0f) return 0.0f;

    ChainVertex v[kMaxChainVertices];
    int N = seedChainFromRay(tris.data(), (int)tris.size(),
                             x0Rec.point, ls.position, iorHero, v, kMaxChainVertices);
    if (N == 0) return 0.0f;

    NewtonConfig ncfg;
    ncfg.maxIterations = cfg.maxIterations;
    ncfg.tolerance = cfg.tolerance;
    ChainResult r = solveChain(v, N, x0Rec.point, ls.position, /*refraction=*/true,
                               makeFlatReproject(), ncfg, /*maxStep=*/0.1f);
    if (!r.converged) return 0.0f;

    // Visibility x0 -> v[0]: must reach a caustic-caster face (the prism).
    Vec3 wi_x0 = v[0].p - x0Rec.point;
    float distX0 = std::sqrt(wi_x0.length2());
    if (distX0 < 1e-5f) return 0.0f;
    wi_x0 = wi_x0 * (1.0f / distX0);
    {
        HitRecord vr;
        if (!bvh->hit(Ray(x0Rec.point, wi_x0), 1e-3f, distX0 + 1e-2f, vr)) return 0.0f;
        if (!(vr.hitObject && vr.hitObject->isCausticCaster())) return 0.0f;
    }
    // Visibility last-vertex -> light: only the caster (glass) may lie between.
    Vec3 toLight = ls.position - v[N - 1].p;
    float distL = std::sqrt(toLight.length2());
    if (distL < 1e-5f) return 0.0f;
    Vec3 dirL = toLight * (1.0f / distL);
    {
        HitRecord lr;
        bool occ = bvh->hit(Ray(v[N - 1].p + dirL * 1e-3f, dirL), 1e-3f, distL - 1e-2f, lr);
        if (occ && lr.hitObject &&
            !lr.hitObject->isInfiniteLight() && !lr.hitObject->isCausticCaster())
            return 0.0f;
    }

    // Per-face Schlick transmittance at the hero eta.
    float Tr = 1.0f;
    Vec3 segIn = wi_x0;
    for (int i = 0; i < N; ++i) {
        const float cosI = std::fabs(segIn.dot(v[i].n));
        const float eta = iorHero;
        float F0 = (1.0f - eta) / (1.0f + eta); F0 *= F0;
        const float fres = F0 + (1.0f - F0) * std::pow(std::max(0.0f, 1.0f - cosI), 5.0f);
        Tr *= (1.0f - fres);
        const Vec3 nxt = (i < N - 1) ? v[i + 1].p : ls.position;
        segIn = (nxt - v[i].p).normalized();
    }

    // Receiver BSDF (hero channel) + light emission (hero channel).
    const Vec3 wo_eye = -primary.direction.normalized();
    const float fHero = x0Rec.material->evalSpectral(x0Rec, wo_eye, wi_x0, lambdas)[0];
    const float LeHero = astroray::RGBIlluminantSpectrum(
        {ls.emission.x, ls.emission.y, ls.emission.z}).sample(lambdas)[0];

    // Clamped generalized-geometry term (first version).
    const float cosX0 = std::max(0.0f, x0Rec.normal.dot(wi_x0));
    const float cosL = std::max(0.0f, ls.normal.dot(-dirL));
    float G = cosX0 * cosL / std::max(distX0 * distX0, 1e-4f);
    if (G > 2.0f) G = 2.0f;

    float contrib = fHero * LeHero * Tr * G / std::max(ls.pdf * casterPickPdf, 1e-6f);
    if (contrib < 0.0f) contrib = 0.0f;
    if (contrib > cfg.contribClamp) contrib = cfg.contribClamp;
    return contrib;
}

}  // namespace astroray::manifold
