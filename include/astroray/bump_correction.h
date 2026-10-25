#pragma once
// #1154 - Cycles bump-map correction, shared by the CPU (plugins/materials/normal_mapped.cpp,
// principled.cpp) and the GPU (src/gpu/wavefront/stage_advance_device.cuh HasNormalPerturb).
//
// Source: Blender Cycles v5.2.0 (Apache-2.0):
//   intern/cycles/kernel/closure/bsdf_util.h:319-395  ensure_valid_specular_reflection
//   intern/cycles/kernel/closure/bsdf_util.h:397-409  maybe_ensure_valid_specular_reflection
//   intern/cycles/kernel/closure/bsdf.h:81-146        bump_shadowing_term
//   intern/cycles/kernel/closure/bsdf_microfacet.h:597-634  bsdf_lambda / bsdf_G (GGX)
// Paper (shadowing term): A. Conty Estevez, P. Lecocq, C. Stein, "A Microfacet-Based Shadowing
//   Function to Solve the Bump Terminator Problem", Ray Tracing Gems (2019) ch. 12,
//   DOI:10.1007/978-1-4842-4427-2_12. GGX Lambda: Heitz 2014 JCGT 3(2) Eq. 72.
// Notes: .astroray_plan/docs/issue1154-bump-correction-research.md
//
// Conventions: Astroray's view direction is wo (Cycles sd->wi) and its light direction wi
// (Cycles wo). `Ns` is the shading normal before the Bump / Normal Map (Cycles sd->N,
// HitRecord::svmNormal). Deviation: Cycles lifts toward the facet normal sd->Ng; Astroray's
// hit record has no facet normal, so both backends lift toward Ns (identical on flat
// geometry; on smooth-shaded meshes Cycles also corrects unbumped glossy lobes, not ported).
// ensure_valid_specular_reflection is a heuristic (not energy-derived); it is switched by the
// material's Cycles "Bump Map Correction" flag, like Cycles.

#include <math.h>

#if defined(__CUDACC__)
#  define AR_BUMPC_HD __host__ __device__
#else
#  define AR_BUMPC_HD
#endif

namespace astroray {
namespace bumpcorr {

// Per-material mode (Material::bumpCorrectionMode, uploaded to the GPU side table): the
// closure class of the decorated material, OR kCorrectionBit when the material's Cycles
// "Bump Map Correction" is on. 0 = no Bump / Normal Map.
enum Mode : int {
    kGlossy = 1,   // glossy / glass / mixed material: N lifted (correction), shadowing test only
    kDiffuse = 2,  // diffuse material: shadowing test + GGX terminator softening (correction)
    kPerLobe = 3,  // Principled: the CPU applies both per closure; the GPU treats it as kGlossy
    kClassMask = 3,
    kCorrectionBit = 4,
    // An Output Displacement (Bump method) bump: Cycles bump_from_displacement sets sd->N to the
    // bumped normal (scene/shader_graph.cpp:1092-1100, svm/closure.h:1519-1525), so
    // bump_shadowing_term sees sc->N == sd->N and returns 1 (bsdf.h:91-93): no hemisphere test,
    // no softening. The glossy lift still applies (toward Ng; here the pre-bump normal).
    kSetsSdNBit = 8,
};

// Cycles ensure_valid_specular_reflection (bsdf_util.h:322-395): if the reflection of I about
// N falls below Ng (threshold min(0.9 Iz, 0.01)), rotate N toward Ng in the N-Ng plane just
// enough to lift it to the threshold (the quartic's single valid root).
template<class V>
AR_BUMPC_HD inline V ensureValidSpecularReflection(const V& Ng, const V& I, const V& N) {
    const V R = N * (2.0f * N.dot(I)) - I;
    const float Iz = I.dot(Ng);
    if (Iz <= 0.0f) return N;  // Cycles' facet Ng always faces wi; a smooth Ns may not (silhouettes)
    const float threshold = fminf(0.9f * Iz, 0.01f);
    if (Ng.dot(R) >= threshold) return N;
    V X = N - Ng * N.dot(Ng);  // safe_normalize_fallback(N - dot(N, Ng) Ng, N)
    const float xl = X.length();
    X = (xl != 0.0f) ? X * (1.0f / xl) : N;
    const float Ix = I.dot(X);
    const float a = Ix * Ix + Iz * Iz;
    if (!(a > 0.0f)) return N;  // I orthogonal to the N-Ng plane: no lift defined (Cycles divides by 0)
    const float b = 2.0f * (a + Iz * threshold);
    const float c = (threshold + Iz) * (threshold + Iz);
    const float disc = sqrtf(fmaxf(b * b - 4.0f * a * c, 0.0f));
    const float Nz2 = (Ix < 0.0f) ? 0.25f * (b + disc) / a : 0.25f * (b - disc) / a;
    const float Nx = sqrtf(fmaxf(1.0f - Nz2, 0.0f));
    const float Nz = sqrtf(fmaxf(Nz2, 0.0f));
    return X * Nx + Ng * Nz;
}

// Cycles bump_shadowing_term (bsdf.h:86-146). I = light direction. Zero when I and N lie on
// opposite sides of Ns (all closures on eval, diffuse closures on sample); with the correction
// on, diffuse closures are softened by the GGX G1 of alpha^2 = 0.125 tan^2(N, Ns).
// Sample path (Cycles bsdf.h:297-315): a delta sample is never zeroed (transmission labels skip
// the term; a reflection uses is_eval = false, which only touches diffuse closures). A non-delta
// sample takes the eval rule (isEval = true): Astroray's spectral sample re-evaluates f through
// evalSpectral, so a sampled glossy direction crossing Ns is zeroed too (Cycles keeps it).
// CPU and GPU agree.
template<class V>
AR_BUMPC_HD inline float bumpShadowingTerm(const V& Ns, const V& N, const V& I, bool isEval,
                                           bool isDiffuse, bool correction) {
    const float cosNsI = Ns.dot(I);
    const float cosNsN = Ns.dot(N);
    const float cosNI = N.dot(I);
    if (cosNsI * cosNsN * cosNI < 0.0f && (isEval || isDiffuse)) return 0.0f;
    if (!isDiffuse || !correction) return 1.0f;
    const float cos_i = fabsf(cosNsI);
    const float cos_d = fabsf(cosNsN);
    if (cos_d >= 1.0f || cos_i >= 1.0f) return 1.0f;
    if (cos_i < 1e-6f) return 0.0f;
    const float tan2_d = 1.0f / (cos_d * cos_d) - 1.0f;
    const float alpha2 = fminf(fmaxf(0.125f * tan2_d, 0.0f), 1.0f);
    // bsdf_G<GGX>(alpha2, cos_i) = 1 / (1 + Lambda), Lambda = (sqrt(1 + alpha2 tan^2) - 1) / 2
    const float tan2_i = fmaxf(1.0f / (cos_i * cos_i) - 1.0f, 0.0f);
    const float lambda = 0.5f * (sqrtf(1.0f + alpha2 * tan2_i) - 1.0f);
    return 1.0f / (1.0f + lambda);
}

}  // namespace bumpcorr
}  // namespace astroray
