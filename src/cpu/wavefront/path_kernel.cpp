// pkg55 Phase B' Session 2c/3/4/5/6/7 — Shared per-bounce path kernel implementation.
//
// This is THE single generator of the per-bounce arithmetic. The body of
// advance_one_bounce() is the loop body of the (now-deleted)
// reference_pt_wavefront::tracePathSpectral, moved here verbatim — same
// operations, same order, same RNG draws. Both the oracle and the wavefront
// driver call this exact compiled function, so the snapshot streams are
// bit-identical by construction.
//
// Cite: Laine 2013 §3; Cycles shade_surface.h (Apache-2.0);
//       PBRT-v4 wavefront/integrator.cpp (Apache-2.0);
//       production Renderer::pathTraceSpectral (raytracer.h).

#include "raytracer.h"
#include "path_kernel.h"
#include <random>
#include <cmath>
#include <algorithm>
#include <limits>
#include <cstdio>

namespace astroray {
namespace cpu_wavefront {

namespace {

// Per-bounce constants (mirror the oracle exactly).
constexpr int   kRRDepth         = 3;

// Box filter: returns uniform [-0.5, 0.5]. Mirrors the GPU stage_init.cu
// filterSample exactly so PostInit / PostIntersect agree CPU↔GPU within
// bounded ULP (spec §4.2 two-tier gate).
//
// HISTORY: this previously used `std::uniform_real_distribution<float>`. That
// preserves CPU↔CPU bit-identity (both call sites compile the same libstdc++
// adaptor bytes), but breaks CPU↔GPU agreement because libstdc++ calls the
// engine's `operator()` MULTIPLE times per float draw (it builds a double from
// two uint32s, then casts), while the GPU does one `Uniform()` = one uint32 ->
// `u * 2^-32` clamp. After init_path, CPU rng.dimension() was 6-7 while GPU's
// was 4 — every subsequent stage's RNG state was therefore mis-keyed against
// the GPU. Caught in pkg64-gpu Phase 2 HW verify (PostInit ULP measured at
// 8.7M vs placeholder 4). Diagnostic 2026-05-23 §"pkg55 GPU stage_init
// CPU/GPU RNG-adaptor mismatch" in standup.
//
// FIX: call rng.Uniform() directly. Both `WavefrontRNG::Uniform()` (CPU,
// include/astroray/sampling/wavefront_rng.h:69) and the device twin
// (wavefront_rng_device.h:78) use the same `u * 2^-32` + OneMinusEpsilon
// clamp, so this makes CPU and GPU byte-identical at PostInit by construction
// (not bounded drift — the bit-identity guarantee design decision #9 wanted).
template <typename RNG>
inline float filterSample(RNG& gen) {
    return gen.Uniform() - 0.5f;
}

// Session 8 scope enforcement: Lambertian + metal + dielectric + disney + thin_glass + diffuse_light + closure_graph.
void assertMaterialInScope(const Material* mat) {
    if (!mat) return;
    // Use backendCapabilities().gpuType to catch both explicit GPU type names
    // (lambertian, metal, dielectric, disney, thin_glass) AND closure-graph-based
    // materials (closure_matte, which has gpuType="closure_graph" via closureGraph()).
    std::string gpuType = mat->backendCapabilities().gpuType;
    if (gpuType != "lambertian" && gpuType != "metal" && gpuType != "dielectric" &&
        gpuType != "disney" && gpuType != "thin_glass" && gpuType != "closure_graph" &&
        !mat->isEmissive()) {
        fprintf(stderr,
                "[pkg55-B-Session8] ERROR: material '%s' is out of scope "
                "(Lambertian + metal + dielectric + disney + thin_glass + diffuse_light + closure_graph only). Aborting.\n", gpuType.c_str());
        std::abort();
    }
}

}  // anonymous namespace

void init_path(PathState& ps, const Camera& cam, int x, int y,
                int width, int height, SnapshotSink* sink) {
    // RNG draw order — the single generator of init outputs. Identical to
    // the original reference_pt_wavefront per-sample loop AND to the GPU
    // stage_init.cu kernel:
    //   1. filter u  2. filter v  3. lens seed  4. lambda u.
    // Each is one WavefrontRNG::Uniform() / UniformUInt32() call → one PCG32
    // dimension, byte-identical to the GPU sampler. See the filterSample
    // history comment above.

    float u = (x + filterSample(ps.rng)) / (width - 1);
    float v = 1.0f - (y + filterSample(ps.rng)) / (height - 1);

    // Lens sampling via a temporary mt19937 seeded from the live RNG. This
    // consumes exactly one WavefrontRNG draw (dimension auto-increments).
    // pkg88 added `time`; 0.0f matches no-motion-blur production.
    uint32_t lens_seed = ps.rng.UniformUInt32();
    std::mt19937 mt_gen(lens_seed);
    Ray primaryRay = cam.getRay(u, v, 0.0f, mt_gen);

    ps.lambdas = SampledWavelengths::sampleUniform(ps.rng.Uniform());

    // Store the already-normalized direction directly. Camera::getRay's Ray
    // ctor already normalized it; we keep that exact bit pattern and never
    // renormalize at a stage boundary (Phase A.1 ulp-bug fix).
    ps.ray_origin    = primaryRay.origin;
    ps.ray_direction = primaryRay.direction;
    ps.throughput    = SampledSpectrum(1.0f);
    ps.color         = SampledSpectrum(0.0f);
    ps.wasSpecular   = true;
    ps.alive         = true;
    ps.bounce        = 0;

    if (sink) {
        WavefrontSnapshot snap{};
        snap.pixel_index  = ps.pixel_index;
        snap.sample_index = ps.sample_index;
        snap.bounce       = 0;
        snap.stage        = SnapshotStage::PostInit;
        snap.ray_origin[0] = ps.ray_origin.x;
        snap.ray_origin[1] = ps.ray_origin.y;
        snap.ray_origin[2] = ps.ray_origin.z;
        snap.ray_direction[0] = ps.ray_direction.x;
        snap.ray_direction[1] = ps.ray_direction.y;
        snap.ray_direction[2] = ps.ray_direction.z;
        for (int i = 0; i < 4; ++i) {
            snap.throughput[i] = 1.0f;
            snap.lambdas[i]    = ps.lambdas.lambda(i);
        }
        sink->record(snap);
    }
}

bool advance_one_bounce(PathState& ps, HitRecord& rec,
                        Renderer& renderer, int max_depth,
                        SnapshotSink* sink) {
    const auto& bvh    = renderer.getBVH();
    const auto& lights = renderer.getLights();

    const int bounce = ps.bounce;

    // ---- Intersect.
    //
    // Phase A.1 ulp-bug fix (re-applied on CPU). The original oracle carried
    // a `Ray` object across bounces: it built `Ray next(rec.point, bss.wi)`
    // (ONE normalization of bss.wi by the Ray ctor) and fed that SAME object
    // straight into the NEXT bvh->hit() without re-wrapping. The primary ray
    // likewise came from cam.getRay() already normalized ONCE. So the BVH
    // always saw the path direction normalized EXACTLY ONCE.
    //
    // ps.ray_direction stores that already-normalized direction (from
    // getRay for bounce 0, from bss.wi.normalized() at advance for bounce
    // N). We must NOT let Ray's ctor normalize it a SECOND time (double-
    // normalize of a unit vector = ulp perturbation = the Phase A.1 bug).
    // So we build the Ray WITHOUT the normalizing ctor and assign the
    // already-unit direction verbatim. Identical bit pattern for both the
    // oracle-call and the wavefront-call (same shared code), and identical
    // to the pre-refactor oracle (single normalization total).
    Ray ray;
    ray.origin    = ps.ray_origin;
    ray.direction = ps.ray_direction;   // already unit; do NOT renormalize.
    bool hit = bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec);

    // ---- PostIntersect snapshot.
    if (sink) {
        WavefrontSnapshot s{};
        s.pixel_index  = ps.pixel_index;
        s.sample_index = ps.sample_index;
        s.bounce       = bounce;
        s.stage        = SnapshotStage::PostIntersect;
        s.ray_origin[0] = ps.ray_origin.x;
        s.ray_origin[1] = ps.ray_origin.y;
        s.ray_origin[2] = ps.ray_origin.z;
        s.ray_direction[0] = ps.ray_direction.x;
        s.ray_direction[1] = ps.ray_direction.y;
        s.ray_direction[2] = ps.ray_direction.z;
        for (int i = 0; i < 4; ++i) {
            s.throughput[i] = ps.throughput[i];
            s.lambdas[i]    = ps.lambdas.lambda(i);
        }
        s.hit_valid = hit ? 1 : 0;
        if (hit) {
            s.hit_t = rec.t;
            s.hit_point[0] = rec.point.x; s.hit_point[1] = rec.point.y; s.hit_point[2] = rec.point.z;
            s.hit_normal[0] = rec.normal.x; s.hit_normal[1] = rec.normal.y; s.hit_normal[2] = rec.normal.z;
            s.hit_material_id = rec.material ? 1 : -1;
        } else {
            s.hit_t = 0; s.hit_material_id = -1;
            for (int i = 0; i < 3; ++i) { s.hit_point[i] = 0; s.hit_normal[i] = 0; }
        }
        sink->record(s);
    }

    if (!hit) {
        // Session N+1: env-map miss handling. Match production
        // pathTraceSpectral lines 2339-2356 exactly — evaluate env map /
        // backgroundColor / default sky gradient and accumulate, subject to
        // worldMaxBounces gate.
        if (bounce <= renderer.getWorldMaxBounces()) {
            const auto& envMap = renderer.getEnvironmentMap();
            const Vec3& backgroundColor = renderer.getBackgroundColor();
            SampledSpectrum envSpec(0.0f);
            if (envMap && envMap->loaded()) {
                envSpec = envMap->evalSpectral(ps.ray_direction, ps.lambdas);
            } else if (backgroundColor.x >= 0) {
                envSpec = RGBIlluminantSpectrum(
                    {backgroundColor.x, backgroundColor.y, backgroundColor.z}).sample(ps.lambdas);
            } else {
                // Default sky gradient (matches production line 2350-2352).
                float t = 0.5f * (ps.ray_direction.y + 1.0f);
                Vec3 bg = (Vec3(1) * (1 - t) + Vec3(0.5f, 0.7f, 1.0f) * t) * 0.2f;
                envSpec = RGBIlluminantSpectrum({bg.x, bg.y, bg.z}).sample(ps.lambdas);
            }
            ps.color += ps.throughput * envSpec;
        }
        ps.alive = false;
        return false;
    }

    assertMaterialInScope(rec.material.get());

    if (!rec.material) { ps.alive = false; return false; }

    // ---- Emission (gated on camera ray or post-specular bounce).
    SampledSpectrum Le_spec = rec.material->emittedSpectral(rec, ps.lambdas);
    if (!Le_spec.isZero()) {
        if (bounce == 0 || ps.wasSpecular) {
            ps.color += ps.throughput * Le_spec;
        }
        ps.alive = false;
        return false;
    }

    Vec3 wo = -ps.ray_direction.normalized();

    // ---- Area-light NEE (MIS via power heuristic). Skipped on delta lobes.
    if (!rec.isDelta && !lights.empty()) {
        uint32_t light_seed = ps.rng.UniformUInt32();
        std::mt19937 light_gen(light_seed);
        LightSample ls;
        lights.sample(ls, rec.point, rec.normal, ps.lambdas, light_gen);
        if (ls.pdf > 0) {
            Vec3 wi = (ls.position - rec.point).normalized();
            HitRecord shadow;
            bool hitOccluder = bvh->hit(Ray(rec.point, wi), 0.001f, ls.distance - 0.001f, shadow);
            bool occluded = hitOccluder && !(shadow.hitObject && shadow.hitObject->isInfiniteLight());
            if (!occluded) {
                SampledSpectrum f_spec = rec.material->evalSpectral(rec, wo, wi, ps.lambdas);
                SampledSpectrum L_spec = ls.emission_spec;
                float bsdfPdf = rec.material->pdf(rec, wo, wi);
                float a = ls.pdf, b = bsdfPdf;
                // pkg140: see raytracer.h pathTraceSpectral's identical comment
                // -- delta-light NEE samples always get full MIS weight.
                float wt = ls.isDelta ? 1.0f : (a * a) / (a * a + b * b + 1e-8f);
                SampledSpectrum nee_contribution = f_spec * L_spec * (wt / (ls.pdf + 0.001f));
                ps.color += ps.throughput * nee_contribution;

                if (sink) {
                    WavefrontSnapshot s{};
                    s.pixel_index  = ps.pixel_index;
                    s.sample_index = ps.sample_index;
                    s.bounce       = bounce;
                    s.stage        = SnapshotStage::PostLightSample;
                    // Capture shading point (rec.point), not incoming ray origin.
                    // This matches GPU snapshot which downloads hitBufs.hit_point_*
                    // (Session N+4 part 2 snapshot-semantics alignment).
                    s.ray_origin[0] = rec.point.x;
                    s.ray_origin[1] = rec.point.y;
                    s.ray_origin[2] = rec.point.z;
                    s.ray_direction[0] = ps.ray_direction.x;
                    s.ray_direction[1] = ps.ray_direction.y;
                    s.ray_direction[2] = ps.ray_direction.z;
                    for (int i = 0; i < 4; ++i) {
                        s.throughput[i]       = ps.throughput[i];
                        s.lambdas[i]          = ps.lambdas.lambda(i);
                        s.nee_contribution[i] = nee_contribution[i];
                    }
                    s.nee_light_pdf       = ls.pdf;
                    s.nee_bsdf_pdf_at_dir = bsdfPdf;
                    s.nee_mis_weight      = wt;
                    sink->record(s);
                }
            }
        }
    }

    // ---- Russian roulette on luminance of throughput's XYZ.
    if (bounce > kRRDepth) {
        XYZ thrXYZ = ps.throughput.toXYZ(ps.lambdas);
        float p = std::min(0.95f, std::max(0.0f, thrXYZ.Y));
        // Single PCG32 dimension — matches GPU stage_rr.cu (when ported).
        float rr_u = ps.rng.Uniform();
        bool survived = (rr_u <= p);

        if (sink) {
            WavefrontSnapshot s{};
            s.pixel_index  = ps.pixel_index;
            s.sample_index = ps.sample_index;
            s.bounce       = bounce;
            s.stage        = SnapshotStage::PostRR;
            // Capture shading point (rec.point), not incoming ray origin.
            // This matches GPU snapshot which downloads hitBufs.hit_point_*
            // (Session N+4 part 2 snapshot-semantics alignment).
            s.ray_origin[0] = rec.point.x;
            s.ray_origin[1] = rec.point.y;
            s.ray_origin[2] = rec.point.z;
            s.ray_direction[0] = ps.ray_direction.x;
            s.ray_direction[1] = ps.ray_direction.y;
            s.ray_direction[2] = ps.ray_direction.z;
            for (int i = 0; i < 4; ++i) {
                s.throughput[i] = ps.throughput[i];
                s.lambdas[i]    = ps.lambdas.lambda(i);
            }
            s.rr_prob     = p;
            s.rr_survived = survived ? 1 : 0;
            sink->record(s);
        }

        if (!survived) { ps.alive = false; return false; }
        if (p > 0.0f) ps.throughput = ps.throughput * (1.0f / p);
    }

    // ---- BSDF sampling.
    uint32_t bsdf_seed = ps.rng.UniformUInt32();
    std::mt19937 bsdf_gen(bsdf_seed);
    BSDFSampleSpectral bss = rec.material->sampleSpectral(rec, wo, bsdf_gen, ps.lambdas);
    if (bss.pdf <= 0.0f) { ps.alive = false; return false; }
    ps.wasSpecular = bss.isDelta;
    ps.throughput *= bss.f_spectral * (1.0f / (bss.pdf + 0.001f));

    // ---- PostShade snapshot.
    if (sink) {
        WavefrontSnapshot s{};
        s.pixel_index  = ps.pixel_index;
        s.sample_index = ps.sample_index;
        s.bounce       = bounce;
        s.stage        = SnapshotStage::PostShade;
        Vec3 next_origin    = rec.point;
        Vec3 next_direction = bss.wi;
        s.ray_origin[0] = next_origin.x;
        s.ray_origin[1] = next_origin.y;
        s.ray_origin[2] = next_origin.z;
        s.ray_direction[0] = next_direction.x;
        s.ray_direction[1] = next_direction.y;
        s.ray_direction[2] = next_direction.z;
        for (int i = 0; i < 4; ++i) {
            s.throughput[i] = ps.throughput[i];
            s.lambdas[i]    = ps.lambdas.lambda(i);
        }
        s.bsdf_pdf      = bss.pdf;
        s.bsdf_is_delta = bss.isDelta ? 1 : 0;
        sink->record(s);
    }

    // ---- Advance ray. Store the already-normalized BSDF direction
    // directly. The original oracle constructed `Ray next(rec.point,
    // bss.wi, ...)` which renormalizes bss.wi; we replicate that single
    // normalization HERE inside the shared kernel (so both callers get the
    // identical bit pattern) and then store the result raw — the wavefront
    // never renormalizes again at the SoA boundary.
    ps.ray_origin    = rec.point;
    ps.ray_direction = bss.wi.normalized();  // matches Ray ctor's d.normalized()

    // ---- Throughput clamp.
    float maxC = ps.throughput.maxValue();
    if (maxC > 10.0f) ps.throughput = ps.throughput * (10.0f / maxC);

    ps.bounce = bounce + 1;
    if (ps.bounce >= max_depth) { ps.alive = false; return false; }
    return true;
}

}  // namespace cpu_wavefront
}  // namespace astroray
