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
// ---------------------------------------------------------------------------
// pkg89-GPU / GAP 1 — device sampleLi for a dedicated light (point/spot/
// distant/area). Mirrors the CPU src/lights/{point,spot,distant,area}_light.cpp
// sampleLi() EXACTLY (same geometric sampling, same pdfs, same emission scale)
// so GPU NEE == CPU NEE (parity gate). `selPdf` is the light-selection
// probability; the returned lightPdf folds it in, matching LightList::sample's
// `ls.pdf = liSample.pdf * selPdf`. The emission is carried as a reference RGB
// + a wavelength-independent scale (dedGeoScale); gpu_nee_resolve upsamples it
// via the same RGBIlluminant path the CPU uses. Cite: Cycles kernel/light/
// {point,spot,distant,area}.h (Apache-2.0), via the CPU mirrors.
// ---------------------------------------------------------------------------
template <typename TRng>
__device__ inline GNEESample gpu_dedicated_sample(
    const GDedicatedLight& d, const GVec3& shadingPoint, float selPdf, TRng* rng)
{
    GNEESample s{};
    s.valid       = 0;
    s.isDedicated = 1;
    s.isSphere    = 0;   // occlusion via the "any occluder in [eps,maxDist]" branch
    s.origin      = shadingPoint;
    s.dedEmissionRGB = d.emissionRGB;

    if (d.kind == GDED_POINT || d.kind == GDED_SPOT) {
        GVec3 sampledPos = d.position;
        if (d.radius > 0.f) {
            float u1 = gpu_rng_uniform(rng), u2 = gpu_rng_uniform(rng);
            float z  = 1.f - 2.f * u1;
            float rr = sqrtf(fmaxf(0.f, 1.f - z * z));
            float phi = 2.f * M_PI_F * u2;
            sampledPos = d.position + GVec3(rr * cosf(phi), rr * sinf(phi), z) * d.radius;
        }
        GVec3 lts  = shadingPoint - sampledPos;
        float dist = lts.length();
        if (dist < 1e-6f) return s;
        GVec3 lightDir = lts * (1.f / dist);         // from light toward shading (CPU lightDir)
        float geo = 1.f / (dist * dist);             // 1/r² falloff
        if (d.kind == GDED_SPOT) {
            float cosTheta = lightDir.dot(d.axis);
            if (cosTheta <= d.cosOuter) return s;    // outside outer cone
            float att;
            if (cosTheta >= d.cosInner) att = 1.f;
            else { float t = (cosTheta - d.cosOuter) / (d.cosInner - d.cosOuter);
                   att = t * t * (3.f - 2.f * t); }  // Cycles cubic Hermite smoothstep
            geo *= att;
        }
        // pkg122: point AND spot use the same measure — radius-0 is a delta
        // light (pdf = 1; the 1/d² and, for spot, the cone attenuation are baked
        // into dedGeoScale via staticScale = intensity·1/(4π)); radius>0 uses the
        // sphere-surface pdf 1/(4π·r²). Mirrors the CPU {point,spot}_light.cpp.
        float pdf = (d.radius > 0.f) ? (1.f / (4.f * M_PI_F * d.radius * d.radius)) : 1.f;
        s.wi          = (sampledPos - shadingPoint) * (1.f / dist);
        s.maxDist     = dist - 0.001f;
        s.lightPdf    = pdf * selPdf;
        s.dedGeoScale = d.staticScale * geo;
        s.valid       = 1;
        return s;
    }

    if (d.kind == GDED_AREA) {
        float u1 = gpu_rng_uniform(rng), u2 = gpu_rng_uniform(rng);
        GVec3 sampledPos;
        float area;
        if (d.areaShape == 1) {          // disk (width = radius)
            float rr = sqrtf(u1) * d.width; float phi = 2.f * M_PI_F * u2;
            sampledPos = d.position + d.u * (rr * cosf(phi)) + d.v * (rr * sinf(phi));
            area = M_PI_F * d.width * d.width;
        } else if (d.areaShape == 2) {   // ellipse
            float rr = sqrtf(u1); float phi = 2.f * M_PI_F * u2;
            sampledPos = d.position + d.u * (rr * d.width * cosf(phi))
                                    + d.v * (rr * d.height * sinf(phi));
            area = M_PI_F * d.width * d.height;
        } else {                          // rectangle
            float su = (u1 - 0.5f) * d.width, sv = (u2 - 0.5f) * d.height;
            sampledPos = d.position + d.u * su + d.v * sv;
            area = d.width * d.height;
        }
        GVec3 lts  = shadingPoint - sampledPos;
        float dist = lts.length();
        if (dist < 1e-6f || area < 1e-8f) return s;
        GVec3 dir = lts * (1.f / dist);              // from light toward shading (CPU dir)
        float cosTheta = dir.dot(d.axis);
        // withinSpread: acos(cosTheta) <= spread  <=>  cosTheta >= cos(spread);
        // plus the back-face reject (cosTheta <= 0) from area_light.cpp sampleLi.
        if (cosTheta <= 0.f || cosTheta < cosf(d.spread)) return s;
        s.wi          = (sampledPos - shadingPoint) * (1.f / dist);
        s.maxDist     = dist - 0.001f;
        // pkg122 (Defect 1): plain-radiance emission (staticScale) + SOLID-ANGLE
        // pdf (pdf_A·dist²/cosθ) so the integrator's MIS is measure-consistent.
        // Mirrors the CPU area_light.cpp::sampleLi fix.
        s.lightPdf    = ((dist * dist) / (area * cosTheta)) * selPdf;
        s.dedGeoScale = d.staticScale;
        s.valid       = 1;
        return s;
    }

    if (d.kind == GDED_DISTANT) {
        GVec3 w   = d.axis * -1.f;                    // direction TO light (CPU: -axis_)
        GVec3 dir = w;
        if (d.cosOuter < 1.f) {                       // finite angular diameter
            float u1 = gpu_rng_uniform(rng), u2 = gpu_rng_uniform(rng);
            float sinH = sqrtf(fmaxf(0.f, 1.f - d.cosOuter * d.cosOuter));
            float rr = sqrtf(u1) * sinH; float phi = 2.f * M_PI_F * u2;
            GVec3 tu, tv; gpu_buildONB(w, tu, tv);
            dir = (w + tu * (rr * cosf(phi)) + tv * (rr * sinf(phi))).normalized();
        }
        // pkg122 (Distant): Blender sun strength is IRRADIANCE S; carry radiance
        // L = S/Ω in dedGeoScale so the L/pdf divide reconstructs S. Delta sun
        // (Ω→0) delivers S directly with pdf = 1. Mirrors CPU distant_light.cpp.
        // pkg140: d.spread carries the host-precomputed solid angle (2*sin^2(h/2)
        // identity, distant_light.cpp distantSolidAngle(), uploaded in
        // fillDeviceParams) instead of recomputing 2*pi*(1-cosOuter) here, which
        // would suffer the same cancellation the CPU fix addresses -- cosOuter
        // itself already lost the small-angle precision once rounded to float32,
        // so recomputing on-device can't recover it.
        float solidAngle = d.spread;
        s.wi          = dir;
        s.maxDist     = 1e30f;
        if (solidAngle > 0.f) {
            s.lightPdf    = (1.f / solidAngle) * selPdf;
            s.dedGeoScale = d.staticScale / solidAngle;
        } else {
            // True delta sun: mirrors CPU sampleLi's isDelta branch -- forces
            // gpu_nee_resolve to use MIS weight 1 (pkg140).
            s.lightPdf     = 1.f * selPdf;
            s.dedGeoScale  = d.staticScale;
            s.isDeltaLight = 1;
        }
        s.valid       = 1;
        return s;
    }

    return s;  // kind == -1 (unsupported): no contribution
}

template <typename TRng>
__device__ inline GNEESample gpu_nee_sample(
    const GHitRecord& rec,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GLight*     lights, int numLights, float totalLightPower,
    const GDedicatedLight* dedLights, int numDed,   // pkg89-GPU / GAP 1
    GLightTreeView    lightTree,  // pkg86-B
    TRng*             rng)
{
    GNEESample s{};
    s.valid = 0;
    if (rec.isDelta || (numLights + numDed) <= 0 || totalLightPower <= 0.f) return s;

    // Light selection: tree-importance descent (pkg86-B, Conty 2018 via
    // Cycles kernel/light/tree.h) when the tree is resident, else the
    // power-weighted CDF (mirrors LightList::sample).
    int   li = 0;
    float selPdf;
    if (lightTree.enabled) {
        // Tree mode is enabled only when there are NO dedicated lights (see
        // scene_upload.cu), so this path selects hittable emitters only.
        float treePdf = 0.f;
        int eIdx = gpu_light_tree_pick(lightTree, rec.point, rec.normal,
                                       gpu_rng_uniform(rng), &treePdf);
        if (eIdx < 0 || treePdf <= 0.f) return s;
        li = lightTree.emitters[eIdx].lightIndex;
        selPdf = treePdf;
    } else {
        // Unified power CDF over hittable emitters THEN dedicated lights
        // (mirrors CPU PowerLightSampler's single CDF; dedicated cumulativePower
        // continues past the last GLight entry). This is what lets a dedicated-
        // light-only scene sample on the GPU instead of rendering black.
        float u = gpu_rng_uniform(rng) * totalLightPower;
        int hit = -1;
        for (int i = 0; i < numLights; ++i) { if (u <= lights[i].cumulativePower) { hit = i; break; } }
        if (hit < 0 && numDed > 0) {
            int dj = numDed - 1;
            for (int j = 0; j < numDed; ++j) { if (u <= dedLights[j].cumulativePower) { dj = j; break; } }
            float dselPdf = dedLights[dj].power / totalLightPower;
            return gpu_dedicated_sample(dedLights[dj], rec.point, dselPdf, rng);
        }
        if (hit < 0) hit = numLights - 1;   // fp fallback within hittable range
        li = hit;
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
    // pkg89-GPU / GAP 1 — dedicated lights carry their emission intrinsically
    // (no light material). The reference RGB is upsampled through the SAME
    // RGBIlluminant path the CPU uses (gpu_rgbSpectrumAt == CPU
    // RGBIlluminantSpectrum::sample), scaled by the wavelength-independent
    // dedGeoScale (staticScale · per-sample geometric factor).
    GSampledSpectrum L_spec;
    if (s.isDedicated) {
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
            L_spec[i] = gpu_rgbSpectrumAt(s.dedEmissionRGB, lambdas.lambda[i],
                                          GSPEC_RGB_ILLUMINANT) * s.dedGeoScale;
    } else {
        L_spec = gpu_material_emitted_spectral(materials[s.lightMatId], lightFront, lambdas);
    }
    if (f_spec.maxValue() <= 0.f || L_spec.maxValue() <= 0.f) return direct;

    float bsdfPdf = gpu_material_pdf(mat, rec, wo, s.wi);
    // pkg140: delta-light samples (e.g. GDED_DISTANT angular_diameter == 0)
    // always get full MIS weight -- mirrors CPU pathTraceSpectral's
    // ls.isDelta check (raytracer.h). A BSDF-sampled ray has probability 0
    // of reproducing a delta direction, so power-heuristic-combining against
    // bsdfPdf would incorrectly discount it.
    float wt = s.isDeltaLight ? 1.0f : gpu_mw_powerHeuristic(s.lightPdf, bsdfPdf);
    // color += throughput * f_spec * L_spec * (wt / (ls.pdf + 0.001f))
    return f_spec * L_spec * (wt / (s.lightPdf + 0.001f));
}

