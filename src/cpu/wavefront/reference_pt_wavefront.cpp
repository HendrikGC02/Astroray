// pkg55 Phase B' Session 2b — Wavefront-side reference path tracer implementation.
//
// Per-path RNG keying: mt19937(FNV-1a-32(pixel_index, sample_index, rng_offset)).
// Draw order matches production exactly (filter, lens, lambda, then path-trace loop).
// Only the seeding scheme differs from reference_pt_production.
//
// Cite: Laine 2013 §3 (per-path keying for wavefront path tracers),
//       Cycles intern/cycles/kernel/random.h (rng_pixel + rng_offset convention, Apache-2.0),
//       production pathTraceSpectral for per-bounce loop logic.

#include "reference_pt_wavefront.h"
#include "reference_pt_production.h"  // for ReferencePTResult
#include "raytracer.h"
#include "astroray/spectrum.h"
#include <random>
#include <cmath>
#include <algorithm>
#include <limits>
#include <cassert>

namespace astroray {
namespace cpu_wavefront {

namespace {

// Session 2 scope enforcement: Lambertian + area lights only.
void assertMaterialInScope(const Material* mat) {
    if (!mat) return;
    std::string gpuType = mat->getGPUTypeName();
    if (gpuType != "lambertian" && !mat->isEmissive()) {
        fprintf(stderr, "[pkg55-B-Session2b] ERROR: material '%s' is out of scope "
                        "(Lambertian-Cornell only). Aborting.\n", gpuType.c_str());
        std::abort();
    }
}

// FNV-1a-32 hash over 3 uint32 inputs.
// Cite: FNV-1a spec (public domain), Laine 2013 §3 (wavefront RNG keying).
uint32_t fnv1a_hash(uint32_t a, uint32_t b, uint32_t c) {
    constexpr uint32_t FNV_PRIME = 16777619u;
    constexpr uint32_t FNV_OFFSET = 2166136261u;
    uint32_t h = FNV_OFFSET;
    auto mix = [&](uint32_t x) {
        h ^= (x >>  0) & 0xFF; h *= FNV_PRIME;
        h ^= (x >>  8) & 0xFF; h *= FNV_PRIME;
        h ^= (x >> 16) & 0xFF; h *= FNV_PRIME;
        h ^= (x >> 24) & 0xFF; h *= FNV_PRIME;
    };
    mix(a); mix(b); mix(c);
    return h;
}

// Per-bounce path trace (identical to reference_pt_production tracePathSpectral).
SampledSpectrum tracePathSpectral(
        Renderer& renderer, const Ray& r, int maxDepth,
        SampledWavelengths& lambdas, std::mt19937& gen,
        int pixel_index, int sample_index,
        SnapshotSink* sink) {
    const int rrDepth = 3;
    SampledSpectrum color(0.0f);
    SampledSpectrum throughput(1.0f);
    Ray ray = r;
    bool wasSpecular = true;
    std::uniform_real_distribution<float> dist01(0.0f, 1.0f);

    const auto& bvh = renderer.getBVH();
    const auto& lights = renderer.getLights();
    const int worldMaxBounces = 1024;

    for (int bounce = 0; bounce < maxDepth; ++bounce) {
        HitRecord rec;
        bool hit = bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec);

        // PostIntersect snapshot.
        if (sink) {
            WavefrontSnapshot s{};
            s.pixel_index = pixel_index;
            s.sample_index = sample_index;
            s.bounce = bounce;
            s.stage = SnapshotStage::PostIntersect;
            s.ray_origin[0] = ray.origin.x; s.ray_origin[1] = ray.origin.y; s.ray_origin[2] = ray.origin.z;
            s.ray_direction[0] = ray.direction.x; s.ray_direction[1] = ray.direction.y; s.ray_direction[2] = ray.direction.z;
            for (int i = 0; i < 4; ++i) {
                s.throughput[i] = throughput[i];
                s.lambdas[i] = lambdas.lambda(i);
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
            if (bounce <= worldMaxBounces) {
                // Lambertian-Cornell: no env map, background = [0,0,0].
            }
            break;
        }

        assertMaterialInScope(rec.material.get());

        if (!rec.material) break;

        // Emission (gated on camera ray or post-specular bounce).
        SampledSpectrum Le_spec = rec.material->emittedSpectral(rec, lambdas);
        if (!Le_spec.isZero()) {
            if (bounce == 0 || wasSpecular) {
                color += throughput * Le_spec;
            }
            break;
        }

        Vec3 wo = -ray.direction.normalized();

        // Area-light NEE (MIS via power heuristic). Skipped on delta lobes.
        if (!rec.isDelta && !lights.empty()) {
            LightSample ls = lights.sample(rec.point, gen);
            if (ls.pdf > 0) {
                Vec3 wi = (ls.position - rec.point).normalized();
                HitRecord shadow;
                bool hitOccluder = bvh->hit(Ray(rec.point, wi), 0.001f, ls.distance - 0.001f, shadow);
                bool occluded = hitOccluder && !(shadow.hitObject && shadow.hitObject->isInfiniteLight());
                if (!occluded) {
                    SampledSpectrum f_spec = rec.material->evalSpectral(rec, wo, wi, lambdas);
                    SampledSpectrum L_spec = RGBIlluminantSpectrum({ls.emission.x, ls.emission.y, ls.emission.z}).sample(lambdas);
                    float bsdfPdf = rec.material->pdf(rec, wo, wi);
                    float a = ls.pdf, b = bsdfPdf;
                    float wt = (a * a) / (a * a + b * b + 1e-8f);
                    SampledSpectrum nee_contribution = f_spec * L_spec * (wt / (ls.pdf + 0.001f));
                    color += throughput * nee_contribution;

                    // PostLightSample snapshot.
                    if (sink) {
                        WavefrontSnapshot s{};
                        s.pixel_index = pixel_index;
                        s.sample_index = sample_index;
                        s.bounce = bounce;
                        s.stage = SnapshotStage::PostLightSample;
                        s.ray_origin[0] = ray.origin.x; s.ray_origin[1] = ray.origin.y; s.ray_origin[2] = ray.origin.z;
                        s.ray_direction[0] = ray.direction.x; s.ray_direction[1] = ray.direction.y; s.ray_direction[2] = ray.direction.z;
                        for (int i = 0; i < 4; ++i) {
                            s.throughput[i] = throughput[i];
                            s.lambdas[i] = lambdas.lambda(i);
                            s.nee_contribution[i] = nee_contribution[i];
                        }
                        s.nee_light_pdf = ls.pdf;
                        s.nee_bsdf_pdf_at_dir = bsdfPdf;
                        s.nee_mis_weight = wt;
                        sink->record(s);
                    }
                }
            }
        }

        // Russian roulette on luminance of throughput's XYZ.
        if (bounce > rrDepth) {
            XYZ thrXYZ = throughput.toXYZ(lambdas);
            float p = std::min(0.95f, std::max(0.0f, thrXYZ.Y));
            float rr_u = dist01(gen);
            bool survived = (rr_u <= p);

            // PostRR snapshot.
            if (sink) {
                WavefrontSnapshot s{};
                s.pixel_index = pixel_index;
                s.sample_index = sample_index;
                s.bounce = bounce;
                s.stage = SnapshotStage::PostRR;
                s.ray_origin[0] = ray.origin.x; s.ray_origin[1] = ray.origin.y; s.ray_origin[2] = ray.origin.z;
                s.ray_direction[0] = ray.direction.x; s.ray_direction[1] = ray.direction.y; s.ray_direction[2] = ray.direction.z;
                for (int i = 0; i < 4; ++i) {
                    s.throughput[i] = throughput[i];
                    s.lambdas[i] = lambdas.lambda(i);
                }
                s.rr_prob = p;
                s.rr_survived = survived ? 1 : 0;
                sink->record(s);
            }

            if (!survived) break;
            if (p > 0.0f) throughput = throughput * (1.0f / p);
        }

        // BSDF sampling.
        BSDFSampleSpectral bss = rec.material->sampleSpectral(rec, wo, gen, lambdas);
        if (bss.pdf <= 0.0f) break;
        wasSpecular = bss.isDelta;
        throughput *= bss.f_spectral * (1.0f / (bss.pdf + 0.001f));

        // PostShade snapshot.
        if (sink) {
            WavefrontSnapshot s{};
            s.pixel_index = pixel_index;
            s.sample_index = sample_index;
            s.bounce = bounce;
            s.stage = SnapshotStage::PostShade;
            Vec3 next_origin = rec.point;
            Vec3 next_direction = bss.wi;
            s.ray_origin[0] = next_origin.x; s.ray_origin[1] = next_origin.y; s.ray_origin[2] = next_origin.z;
            s.ray_direction[0] = next_direction.x; s.ray_direction[1] = next_direction.y; s.ray_direction[2] = next_direction.z;
            for (int i = 0; i < 4; ++i) {
                s.throughput[i] = throughput[i];
                s.lambdas[i] = lambdas.lambda(i);
            }
            s.bsdf_pdf = bss.pdf;
            s.bsdf_is_delta = bss.isDelta ? 1 : 0;
            sink->record(s);
        }

        // Advance ray.
        Ray next(rec.point, bss.wi, ray.time, ray.screenU, ray.screenV);
        next.hasCameraFrame = ray.hasCameraFrame;
        next.cameraOrigin = ray.cameraOrigin;
        next.cameraU = ray.cameraU;
        next.cameraV = ray.cameraV;
        next.cameraW = ray.cameraW;
        ray = next;

        // Throughput clamping.
        float maxC = throughput.maxValue();
        if (maxC > 10.0f) throughput = throughput * (10.0f / maxC);
    }

    return color;
}

}  // anonymous namespace

ReferencePTResult reference_pt_wavefront_render(
        Renderer& renderer,
        const Camera& cam,
        int samples,
        int max_depth,
        uint64_t seed,
        bool record_snapshots) {
    ReferencePTResult result;
    result.rgb.resize(static_cast<size_t>(cam.width) * cam.height * 3, 0.0f);

    VectorSink snapSink;
    SnapshotSink* sink = record_snapshots ? &snapSink : nullptr;

    // Per-path RNG keying. Seed is used as an XOR mask (0 = no mask).
    uint32_t seed_mask = static_cast<uint32_t>(seed);

    for (int y = 0; y < cam.height; ++y) {
        for (int x = 0; x < cam.width; ++x) {
            int pixel_index = y * cam.width + x;
            Vec3 colorXYZ(0);

            for (int s = 0; s < samples; ++s) {
                // RNG keying: hash(pixel_index, sample_index, rng_offset).
                // rng_offset = 0 for integrator-frontend draws.
                uint32_t h = fnv1a_hash(static_cast<uint32_t>(pixel_index), static_cast<uint32_t>(s), 0u);
                h ^= seed_mask;
                std::mt19937 gen(h);
                std::uniform_real_distribution<float> dist(0, 1);

                // RNG draw order (matches production exactly):
                // 1. filterSample(gen, dist) — 2 draws (box filter).
                // 2. filterSample(gen, dist) — 2 draws.
                // 3. cam.getRay(u, v, time, gen) — randomInUnitDisk (variable).
                //    pkg88 added `time` as required; 0.0f matches no-motion-blur production.
                // 4. dist01(gen) — 1 draw for lambda sampling.
                float u = (x + renderer.filterSample(gen, dist)) / (cam.width - 1);
                float v = 1.0f - (y + renderer.filterSample(gen, dist)) / (cam.height - 1);
                Ray primaryRay = cam.getRay(u, v, 0.0f, gen);

                std::uniform_real_distribution<float> dist01(0.0f, 1.0f);
                SampledWavelengths lambdas = SampledWavelengths::sampleUniform(dist01(gen));

                // PostInit snapshot.
                if (sink) {
                    WavefrontSnapshot snap{};
                    snap.pixel_index = pixel_index;
                    snap.sample_index = s;
                    snap.bounce = 0;
                    snap.stage = SnapshotStage::PostInit;
                    snap.ray_origin[0] = primaryRay.origin.x; snap.ray_origin[1] = primaryRay.origin.y; snap.ray_origin[2] = primaryRay.origin.z;
                    snap.ray_direction[0] = primaryRay.direction.x; snap.ray_direction[1] = primaryRay.direction.y; snap.ray_direction[2] = primaryRay.direction.z;
                    for (int i = 0; i < 4; ++i) {
                        snap.throughput[i] = 1.0f;
                        snap.lambdas[i] = lambdas.lambda(i);
                    }
                    sink->record(snap);
                }

                SampledSpectrum rad = tracePathSpectral(renderer, primaryRay, max_depth, lambdas, gen, pixel_index, s, sink);
                XYZ xyz = rad.toXYZ(lambdas);

                // Per-sample firefly suppression.
                float lum = xyz.Y;
                if (lum > 20.0f) {
                    xyz.X *= (20.0f / lum);
                    xyz.Y = 20.0f;
                    xyz.Z *= (20.0f / lum);
                }

                colorXYZ += Vec3(xyz.X, xyz.Y, xyz.Z);
            }

            colorXYZ = colorXYZ / float(samples);

            // pkg55-B' Session 2b — equivalence-test parity fix:
            // Mirror reference_pt_production's post-processing exactly so the
            // two oracles produce output in the same color space (linear sRGB,
            // not XYZ). The buffer is named `rgb`, and the equivalence-test
            // compares it against reference_pt_production.rgb which IS in
            // linear sRGB after commit 3164f4d. Codex (2026-05-15) caught
            // that this block was the missing matrix multiply and the cause
            // of the stable per-channel mean ratios (R=0.896, G=1.033,
            // B=1.081) that originally looked like mt19937 startup bias.
            // Post-processing pipeline (production lines 2580, 2595, 2601-2603):
            // 1. Film exposure multiplication (XYZ space).
            colorXYZ *= renderer.getFilmExposure();

            // 2. XYZ → linear sRGB conversion (astroray/spectral.h:137-148).
            Vec3 colorSRGB = xyzToLinearSRGB(colorXYZ);

            // 3. finiteOrZero clamping (production raytracer.h:2601-2603, apply_gamma=False path).
            colorSRGB.x = std::max(Renderer::finiteOrZero(colorSRGB.x), 0.0f);
            colorSRGB.y = std::max(Renderer::finiteOrZero(colorSRGB.y), 0.0f);
            colorSRGB.z = std::max(Renderer::finiteOrZero(colorSRGB.z), 0.0f);

            int idx = pixel_index * 3;
            result.rgb[idx + 0] = colorSRGB.x;
            result.rgb[idx + 1] = colorSRGB.y;
            result.rgb[idx + 2] = colorSRGB.z;
        }
    }

    if (record_snapshots) {
        result.snapshots = snapSink.snapshots();
    }

    return result;
}

}  // namespace cpu_wavefront
}  // namespace astroray
