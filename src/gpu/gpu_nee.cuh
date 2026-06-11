#pragma once
// gpu_nee.cuh — shared NEE thirds (pkg55-B' shadow stage / template-RNG arc).
//
// MOVED VERBATIM from multiwavelength_kernel.cu (where they were rdc-exported
// TU functions) so both the megakernel and the wavefront stages compile the
// same inline implementations, and so gpu_nee_sample can become a template
// over the RNG type (templates cannot be rdc-exported). Blueprint:
// .astroray_plan/docs/pkg55-nee-shadow-stage-blueprint.md.
//
// Only include from .cu files compiled by nvcc.

#include "astroray/gpu_types.h"
#include "astroray/gpu_materials.h"
#include "astroray/gpu_bvh.h"
#include "light_tree_device.cuh"  // gpu_light_tree_pick (pkg86-B)

#include <curand_kernel.h>

#ifndef M_PI_F
#  define M_PI_F 3.14159265358979323846f
#endif

// ---------------------------------------------------------------------------
// MIS power heuristic — mirrors CPU pathTraceSpectral (raytracer.h:2420)
//   wt = a*a / (a*a + b*b + 1e-8) ; and path_trace_kernel.cu::powerHeuristic.
// ---------------------------------------------------------------------------
__device__ inline float gpu_mw_powerHeuristic(float a, float b) {
    return (a * a) / (a * a + b * b + 1e-8f);
}

// ---------------------------------------------------------------------------
// Spectral next-event estimation — mirrors CPU Renderer::pathTraceSpectral
// area-light NEE (include/raytracer.h:2405-2424): power-weighted light
// selection, area-light point/solid-angle sampling, occlusion test, spectral
// f * L, and an MIS power heuristic against the BSDF pdf. The area-light
// geometric sampling (sphere solid angle, triangle area->solid-angle pdf)
// reuses the exact construction already validated in
// src/gpu/path_trace_kernel.cu::sampleDirectGPU (same codebase, CPU-faithful
// port of Renderer::sampleDirect). CLAUDE.md §6 — no new algorithm.
//
// This closes the ~2x deficit caused by the previous "no NEE" megakernel:
// the emissive-on-hit term is gated by (bounce==0 || wasSpecular) exactly
// like the CPU, so without NEE all diffuse->emitter direct light was dropped.
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// pkg55-B' shadow stage: sampleDirectSpectralMW factored into three
// non-inline (rdc-exported) device functions per the blueprint
// (.astroray_plan/docs/pkg55-nee-shadow-stage-blueprint.md):
//   A gpu_nee_sample  — light selection + point sampling. ALL RNG draws,
//                       in the original order. No material evals, no trace.
//   B gpu_nee_occlude — the shadow trace only.
//   C gpu_nee_resolve — material evals + MIS + contribution (the original's
//                       lazy post-trace ordering preserved).
// sampleDirectSpectralMW recomposes A->B->C below: identical results, with
// one strictly-work-saving difference (the lightPdf<=0 reject now happens
// before the trace instead of after; output unchanged). The wavefront runs
// A in the shade stage and B->C in a dedicated lean shadow stage.
// All sampling/eval lines are MOVED verbatim from the original function.
// ---------------------------------------------------------------------------
template <typename TRng>
__device__ inline GNEESample gpu_nee_sample(
    const GHitRecord& rec,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GLight*     lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,  // pkg86-B
    TRng*             rng)
{
    GNEESample s{};
    s.valid = 0;
    if (rec.isDelta || numLights <= 0 || totalLightPower <= 0.f) return s;

    // Light selection: tree-importance descent (pkg86-B, Conty 2018 via
    // Cycles kernel/light/tree.h) when the tree is resident, else the
    // power-weighted CDF (mirrors LightList::sample).
    int   li = 0;
    float selPdf;
    if (lightTree.enabled) {
        float treePdf = 0.f;
        int eIdx = gpu_light_tree_pick(lightTree, rec.point, rec.normal,
                                       gpu_rng_uniform(rng), &treePdf);
        if (eIdx < 0 || treePdf <= 0.f) return s;
        li = lightTree.emitters[eIdx].lightIndex;
        selPdf = treePdf;
    } else {
        float u = gpu_rng_uniform(rng) * totalLightPower;
        for (int i = 0; i < numLights; ++i) { if (u <= lights[i].cumulativePower) { li = i; break; } li = i; }
        selPdf = lights[li].power / totalLightPower;
    }
    int primIdx  = lights[li].primitiveIndex;
    if (primIdx < 0) return s;

    const GPrimitive& lp = prims[primIdx];
    if (lp.type == GPRIM_SKIP) return s;

    GVec3 wi;
    float lightPdf;     // solid-angle pdf (incl. selPdf), mirrors LightList::sample s.pdf
    float maxDist;      // shadow-ray extent
    int   lightMatId;

    if (lp.type == GPRIM_SPHERE) {
        const GSphere& sp = spheres[lp.index];
        GVec3 toC    = sp.center - rec.point;
        float distSq = toC.length2();
        if (distSq <= sp.radius * sp.radius + 1e-8f) return s;
        GVec3 dir   = toC.normalized();
        float cosTM = sqrtf(fmaxf(0.f, 1.f - sp.radius * sp.radius / distSq));
        if (cosTM >= 1.f) return s;
        float z   = 1.f + gpu_rng_uniform(rng) * (cosTM - 1.f);
        float phi = 2.f * M_PI_F * gpu_rng_uniform(rng);
        GVec3 tu, tv; gpu_buildONB(dir, tu, tv);
        float sinTh = sqrtf(fmaxf(0.f, 1.f - z * z));
        wi          = (tu * cosf(phi) * sinTh + tv * sinf(phi) * sinTh + dir * z).normalized();
        lightPdf    = (1.f / (2.f * M_PI_F * (1.f - cosTM))) * selPdf;
        maxDist     = 1e30f;       // hit-the-sphere check in gpu_nee_occlude bounds it
        lightMatId  = sp.materialId;
        s.isSphere  = 1;
    } else {
        const GTriangle& t = tris[lp.index];
        float r1 = gpu_rng_uniform(rng), r2 = gpu_rng_uniform(rng);
        if (r1 + r2 > 1.f) { r1 = 1.f - r1; r2 = 1.f - r2; }
        GVec3 lpos = t.v0 + (t.v1 - t.v0) * r1 + (t.v2 - t.v0) * r2;
        GVec3 d    = lpos - rec.point;
        float dist = d.length();
        wi         = d * (1.f / fmaxf(dist, 1e-8f));
        GVec3 e1   = t.v1 - t.v0, e2 = t.v2 - t.v0;
        float area = e1.cross(e2).length() * 0.5f;
        float NdotWi = fabsf(t.n0.dot(wi));
        if (NdotWi < 1e-8f || area < 1e-8f) return s;
        lightPdf   = (dist * dist) / (NdotWi * area) * selPdf;
        maxDist    = dist - 0.001f;
        lightMatId = t.materialId;
        s.isSphere = 0;
    }

    // Originally checked after the trace; moved pre-trace (pure math, no
    // draws) — identical output, strictly less work on the reject path.
    if (lightPdf <= 0.f) return s;

    s.origin     = rec.point;
    s.wi         = wi;
    s.maxDist    = maxDist;
    s.lightPdf   = lightPdf;
    s.lightMatId = lightMatId;
    s.valid      = 1;
    return s;
}

__device__ inline GNEEOcclusion gpu_nee_occlude(
    const GNEESample& s,
    const GTLASNode*  tlas,        // pkg114
    const GInstance*  instances,   // pkg114
    const GBLAS*      blas,        // pkg114
    const GBVHNode*  bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    float             time,         // pkg88-C.0: path shutter time for shadow rays
    const GVec3*      motionVerts)  // pkg88-C.0 (nullptr = static)
{
    GNEEOcclusion occ{};
    occ.occluded = 1;
    occ.frontFace = 1;
    GHitRecord sh;
    if (s.isSphere) {
        // Sphere sources: the ray must REACH the light (hit it, with the
        // light's own material) — miss or a different material = occluded.
        if (!gpu_tlas_hit(tlas, instances, blas, bvhNodes, prims, tris, spheres,
                         GRay(s.origin, s.wi, time), 0.001f, s.maxDist, sh, motionVerts) ||
            sh.materialId != s.lightMatId)
            return occ;
        occ.frontFace = sh.frontFace ? 1 : 0;
    } else {
        // Triangle sources: any hit inside [0.001, maxDist] occludes;
        // lightFront is hardcoded true (original behavior asymmetry).
        // pkg55-B' any-hit: boolean-identical to the previous closest-hit
        // query, but the walk exits at the FIRST occluder (PBRT IntersectP /
        // Cycles scene_intersect_shadow).
        if (gpu_tlas_occluded(tlas, instances, blas, bvhNodes, prims, tris,
                              spheres, GRay(s.origin, s.wi, time), 0.001f,
                              s.maxDist, motionVerts))
            return occ;
    }
    occ.occluded = 0;
    return occ;
}

__device__ inline GSampledSpectrum gpu_nee_resolve(
    const GHitRecord& rec, const GVec3& wo,
    const GSampledWavelengths& lambdas,
    const GMaterial*  materials,
    const GNEESample& s,
    bool              lightFront)
{
    GSampledSpectrum direct(0.f);
    const GMaterial& mat = materials[rec.materialId];

    // Spectral BSDF and emission — mirrors CPU pathTraceSpectral lines
    // 2414-2421:  f_spec = evalSpectral ; L_spec = emission_spec (illuminant).
    GSampledSpectrum f_spec =
        gpu_material_eval_spectral(mat, const_cast<GHitRecord&>(rec), wo, s.wi, lambdas);
    GSampledSpectrum L_spec =
        gpu_material_emitted_spectral(materials[s.lightMatId], lightFront, lambdas);
    if (f_spec.maxValue() <= 0.f || L_spec.maxValue() <= 0.f) return direct;

    float bsdfPdf = gpu_material_pdf(mat, rec, wo, s.wi);
    float wt      = gpu_mw_powerHeuristic(s.lightPdf, bsdfPdf);
    // color += throughput * f_spec * L_spec * (wt / (ls.pdf + 0.001f))
    return f_spec * L_spec * (wt / (s.lightPdf + 0.001f));
}

