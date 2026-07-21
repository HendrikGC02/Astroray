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
// The geometry term is the full MNEE block-tridiagonal transfer matrix
// (manifold_chain.h::chainGeometryTerm, ported from Cycles
// mnee_compute_transfer_matrix) clamped to 2.0 — it concentrates energy at the
// caustic (near-singular chain Jacobian) and ~0 elsewhere. Combined with the
// in-triangle validity check on the converged vertices, this localizes the
// chromatic caustic into a continuous rainbow band instead of frame-wide noise.

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

    // Aim the seed at the caster centroid (NOT the light): a real prism deviates
    // the path so the straight x0->light seed misses the prism for the receiver
    // points the dispersed beam illuminates (mesh_caustic.h::seedChainTowardCaster).
    Vec3 centroid(0.0f);
    for (const auto& tr : tris) centroid = centroid + (tr.v0 + tr.v1 + tr.v2) * (1.0f / 3.0f);
    centroid = centroid * (1.0f / (float)tris.size());

    ChainVertex v[kMaxChainVertices];
    int triIdx[kMaxChainVertices];
    int N = seedChainTowardCaster(tris.data(), (int)tris.size(),
                                  x0Rec.point, centroid, iorHero, v, kMaxChainVertices, triIdx);
    if (N == 0) return 0.0f;

    NewtonConfig ncfg;
    ncfg.maxIterations = cfg.maxIterations;
    ncfg.tolerance = cfg.tolerance;
    ChainResult r = solveChain(v, N, x0Rec.point, ls.position, /*refraction=*/true,
                               makeFlatReproject(), ncfg, /*maxStep=*/0.1f);
    if (!r.converged) return 0.0f;

    // In-triangle validity: the converged vertex must land inside the FINITE
    // prism (any caster triangle — a face is several triangles and the Newton
    // can slide the vertex onto a neighbour). Rejecting off-prism vertices is
    // what carves the caustic into a localized band instead of filling the whole
    // frame with chromatic noise (pkg106 research note, failure mode #2).
    (void)triIdx;
    for (int i = 0; i < N; ++i) {
        bool onPrism = false;
        for (int j = 0; j < (int)tris.size() && !onPrism; ++j)
            if (pointInTriangle(v[i].p, tris[j])) onPrism = true;
        if (!onPrism) return 0.0f;
    }

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
    // pkg142 (Defect 4): UNBOUNDED (no-D65) emission lift, with the
    // photometric anchor (pkg142 hardware-verifier fix).
    const float LeHero = astroray::sampleUnboundedEmission(
        {ls.emission.x, ls.emission.y, ls.emission.z}, lambdas)[0];

    // Generalized geometry term (Cycles mnee_path_contribution l.836-841):
    //   G = clamp(dw0_dx1 * dx1_dxlight, 2)
    // dw0_dx1 converts the receiver's outgoing solid angle to area at the first
    // specular vertex (cosine at v[0]'s normal — the receiver's own |n.wo| is
    // already in evalSpectral); dx1_dxlight is the MNEE transfer-matrix Jacobian.
    // A distant (collimated sun) light — required for a prism rainbow, since only
    // a fixed direction selects one wavelength per receiver point — uses the
    // fixed-direction branch (per solid angle), matching its solid-angle pdf.
    const bool fixedDir = (ls.distance > 1.0e5f);
    const Vec3 sunDir = (ls.position - v[N - 1].p).normalized();
    const float dw0_dx1 = std::fabs(wi_x0.dot(v[0].n)) / std::max(distX0 * distX0, 1e-6f);
    const float dx1_dxlight = chainGeometryTerm(v, N, x0Rec.point, ls.position,
                                                ls.normal, nullptr, fixedDir, sunDir);
    if (dx1_dxlight <= 0.0f) return 0.0f;
    float G = dw0_dx1 * dx1_dxlight;
    if (G > 2.0f) G = 2.0f;

    float contrib = fHero * LeHero * Tr * G / std::max(ls.pdf * casterPickPdf, 1e-6f);
    if (contrib < 0.0f) contrib = 0.0f;
    if (contrib > cfg.contribClamp) contrib = cfg.contribClamp;
    return contrib;
}

}  // namespace astroray::manifold
