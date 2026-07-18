// multiwavelength_kernel.cu — pkg54 / pkg54a / pkg54b
// GPU port of multiwavelength_path_tracer.
//
// Megakernel that mirrors the CPU integrator
// (plugins/integrators/multiwavelength_path_tracer.cpp): naive spectral path
// tracing with sampled wavelengths in a configurable [lambdaMin, lambdaMax]
// band, no NEE, emissive-on-hit termination. Output is either:
//   * luminance-grey (mean of the 4 sampled radiances) for non-visible bands,
//   * linear sRGB derived from CIE 1964 10° XYZ for bands inside the visible
//     range. The CMF tables are the same baked data the CPU integrator uses
//     (data/spectra/cie_cmf.inc), uploaded once to constant memory — this is
//     the pkg54b parity fix that replaced an earlier Wyman/Sloan/Shirley 2013
//     1931 2° analytic fit.
//
// Spectral profile dispatch (pkg54a) honours `Material::setSpectralProfile`
// on-device: per-material profileIndex into a constant-memory reflectance
// table populated by scene_upload.cu; the spectral evaluation step mirrors
// `Material::evalSpectralExt` (visible λ → RGB-to-spectrum; non-visible λ →
// profile.reflectance(λ)·cosθ/π, or 0 when no profile is attached).

#include "astroray/gpu_types.h"
#include "astroray/gpu_materials.h"
#include "astroray/gpu_bvh.h"
#include "light_tree_device.cuh"  // pkg86-B: gpu_light_tree_pick
#include "gpu_nee.cuh"  // pkg55-B': shared NEE thirds (sample/occlude/resolve)
#include "astroray/gpu_env_spectral.cuh"  // pkg55-B' N+6: shared env-miss eval
#include "astroray/spectrum.h"  // jhEvalSpectrumF + JH LUT accessors (pkg54c)
#include "astroray/manifold/sms_attempt_device.cuh"  // pkg64-gpu Phase 2
#include "astroray/gpu_photon_store.h"  // pkg113 Phase 3: GPhotonGrid + photonGridGather
#include "profile.h"  // pkg55-A: env-gated CUDA-event + NVTX instrumentation
#include "gpu_spectral_tables.h"  // pkg55-C1: shared spectral tables (CMF/D65/JH/profile) + gpu_spectrum_to_xyz

#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <cstdio>
#include <stdexcept>

#ifndef M_PI_F
#  define M_PI_F 3.14159265358979323846f
#endif

// ---------------------------------------------------------------------------
// Sampled wavelengths in [lmin, lmax] — stratified hero-wavelength sampler,
// matches the CPU SampledWavelengths::sampleUniform(u, lmin, lmax) layout.
// ---------------------------------------------------------------------------
__device__ inline GSampledWavelengths gpu_sampleBandWavelengths(
    curandState* rng, float lmin, float lmax)
{
    // Hero-wavelength layout MUST match CPU SampledWavelengths::sampleUniform
    // (src/spectrum.cpp:82) and the wavefront sampler (stage_init.cu:64):
    //   hero    = lmin + u*span          (hero spans the FULL band)
    //   lam[i]  = hero + i*step          (stratified secondaries)
    //   lam[i] -= span  if lam[i] > lmax (wrap into range)
    // The previous `(u+i)/N` form confined the hero lam[0] to the first 1/N of
    // the band (violet/blue with a [380,780] prism band) — the SMS caustic
    // colorizes off lam[0], so that produced a violet caustic instead of a
    // full rainbow. See pkg64-gpu-session2-research.md (afternoon update).
    GSampledWavelengths wl;
    float u    = curand_uniform(rng);
    float span = lmax - lmin;
    float step = span / float(G_SPECTRUM_SAMPLES);
    float hero = lmin + u * span;
    float pdf  = 1.f / span;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
        float lam = hero + float(i) * step;
        if (lam > lmax) lam -= span;
        wl.lambda[i] = lam;
        wl.pdf[i]    = pdf;
    }
    return wl;
}

// ---------------------------------------------------------------------------
// Rayleigh sky scale — λ^-4 relative to 550 nm, matches CPU integrator.
// ---------------------------------------------------------------------------
__device__ inline float rayleighScale(float lambda_nm) {
    float r = 550.f / lambda_nm;
    return r * r * r * r;
}

__device__ inline bool isInsideVisible(float lmin, float lmax) {
    return lmin >= 380.f - 0.5f && lmax <= 780.f + 0.5f;
}

__device__ GSampledSpectrum sampleDirectSpectralMW(
    const GHitRecord& rec, const GVec3& wo,
    const GSampledWavelengths& lambdas,
    const GTLASNode*  tlas,        // pkg114
    const GInstance*  instances,   // pkg114
    const GBLAS*      blas,        // pkg114
    const GBVHNode*  bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GMaterial*  materials,
    const GLight*     lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,  // pkg86-B
    float             time,         // pkg88-C.0: path shutter time for shadow rays
    const GVec3*      motionVerts,  // pkg88-C.0 (nullptr = static)
    curandState*      rng)
{
    // Recomposition of the factored halves in the original order
    // (sample -> trace -> lazy material evals). Identical results.
    GSampledSpectrum direct(0.f);
    GNEESample s = gpu_nee_sample(rec, prims, tris, spheres,
                                  lights, numLights, totalLightPower,
                                  lightTree, rng);
    if (!s.valid) return direct;
    GNEEOcclusion occ = gpu_nee_occlude(s, tlas, instances, blas, bvhNodes,
                                        prims, tris, spheres, time, motionVerts);
    if (occ.occluded) return direct;
    return gpu_nee_resolve(rec, wo, lambdas, materials, s,
                           s.isSphere ? (occ.frontFace != 0) : true);
}

// ---------------------------------------------------------------------------
// Spectral path trace — area-light NEE + MIS, mirroring the CPU
// Renderer::pathTraceSpectral integrator (the CPU `path_tracer` selects this;
// see plugins/integrators/spectral_path_tracer.cpp). The emissive-on-hit term
// stays gated by (bounce==0 || wasSpecular) — the BSDF-sampling half of MIS —
// while sampleDirectSpectralMW supplies the area-light direct term.
// Returns raw per-sample SampledSpectrum radiance.
// ---------------------------------------------------------------------------
__device__ GSampledSpectrum tracePathMW(
    GRay ray, int maxDepth,
    int worldMaxBounces,  // pkg55-B' N+6 follow-up: env gate, raytracer.h:2412
    GSampledWavelengths& lambdas,
    bool useLuminanceOutput,
    bool enableNEE,
    bool useCaustics,  // pkg64-gpu Phase 2
    const GTLASNode*  tlas,        // pkg114
    const GInstance*  instances,   // pkg114
    const GBLAS*      blas,        // pkg114
    const GBVHNode*  bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GMaterial*  materials,
    const GLight*     lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,  // pkg86-B
    const astroray::manifold::device::GSMSCaster* smsCasters, int numSMSCasters,  // pkg64-gpu Phase 2
    const GEnvMap&    envMap,
    const GVec3&      backgroundColor,
    bool              hasBackgroundColor,
    GRay              primaryRay,  // pkg64-gpu Phase 2: needed for SMS wo_eye
    const GVec3*      motionVerts,  // pkg88-C.0 (nullptr = static)
    curandState*      rng)
{
    const int rrDepth = 3;
    GSampledSpectrum color(0.f);
    GSampledSpectrum throughput(1.f);
    bool wasSpecular = true;

    for (int bounce = 0; bounce < maxDepth; ++bounce) {
        GHitRecord rec;
        if (!gpu_tlas_hit(tlas, instances, blas, bvhNodes, prims, tris, spheres,
                         ray, 0.001f, 1e30f, rec, motionVerts)) {
            // Environment / background contribution. The bg/envmap/sky chain
            // is factored into gpu_env_miss_spectral (gpu_env_spectral.cuh,
            // pkg55-B' Session N+6) so the wavefront stage_advance shares ONE
            // implementation; the luminance-band Rayleigh fallback stays here
            // (needs this TU's rayleighScale, no CPU-wavefront twin).
            //
            // Gated by worldMaxBounces (pkg55-B' N+6 follow-up): mirrors CPU
            // pathTraceSpectral (raytracer.h:2412) and the CPU/GPU wavefront
            // (path_kernel.cpp:192) — the path dies on miss either way; env
            // radiance is only accumulated for bounce <= gate.
            if (bounce > worldMaxBounces) break;
            GSampledSpectrum envSpec(0.f);
            GVec3 dir = ray.direction.normalized();
            if (useLuminanceOutput && !hasBackgroundColor && !envMap.loaded) {
                // Rayleigh sky fallback for outside-visible bands.
                for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
                    float scale = rayleighScale(lambdas.lambda[i]);
                    float horizonFade = 0.5f * (dir.y + 1.f);
                    envSpec.v[i] = 0.08f * scale * (0.5f + horizonFade);
                }
            } else {
                envSpec = gpu_env_miss_spectral(
                    envMap, backgroundColor, hasBackgroundColor, dir, lambdas);
            }
            color += throughput * envSpec;
            break;
        }

        const GMaterial& mat = materials[rec.materialId];

        // Emission — mirrors CPU path: terminates path on emissive hit.
        GSampledSpectrum Le = gpu_material_emitted_spectral(mat, rec.frontFace, lambdas);
        if (Le.maxValue() > 0.f) {
            if (bounce == 0 || wasSpecular)
                color += throughput * Le;
            break;
        }

        GVec3 wo = -ray.direction.normalized();

        // Area-light NEE (MIS via power heuristic). Skipped on delta lobes.
        // Mirrors CPU pathTraceSpectral (include/raytracer.h:2405-2424).
        // enableNEE is false when the kernel mirrors the naive no-NEE
        // MultiwavelengthPathTracer (gated by integrator name in
        // module/blender_module.cpp).
        if (enableNEE && !rec.isDelta && numLights > 0) {
            color += throughput * sampleDirectSpectralMW(
                rec, wo, lambdas, tlas, instances, blas, bvhNodes, prims, tris, spheres, materials,
                lights, numLights, totalLightPower, lightTree,
                ray.time, motionVerts,  // pkg88-C.0
                rng);
        }

        // pkg64-gpu Phase 2: SMS caustic attempt at non-delta vertices.
        // Mirrors CPU pathTraceSpectral (include/raytracer.h:2427-2437):
        // disjoint-strategy additive MIS (w_sms ≈ 1, w_nee ≈ 1 for their
        // respective sample sets; balance heuristic reduction).
        if (useCaustics && !rec.isDelta && numSMSCasters > 0 && numLights > 0) {
            // Sample one caster uniformly (mirrors CPU gatherSphereCasters + pick).
            int cIdx = (int)(curand_uniform(rng) * numSMSCasters);
            if (cIdx >= numSMSCasters) cIdx = numSMSCasters - 1;
            const auto& C = smsCasters[cIdx];
            float casterPickPdf = 1.0f / float(numSMSCasters);

            // Sample one light (mirrors CPU hook's light sampling).
            // Power-weighted selection via CDF (same pattern as sampleDirectSpectralMW).
            float u = curand_uniform(rng) * totalLightPower;
            int lIdx = numLights - 1;
            for (int li = 0; li < numLights; ++li) {
                if (u < lights[li].cumulativePower) { lIdx = li; break; }
            }
            const GLight& lt = lights[lIdx];
            int primIdx = lt.primitiveIndex;
            if (primIdx < 0 || primIdx >= (int)~0u) {
                // Invalid light index; skip SMS.
            } else {
                const GPrimitive& lp = prims[primIdx];
                astroray::manifold::device::GLightSample ls;
                ls.pdf = 0.0f;

                if (lp.type == GPRIM_SPHERE) {
                    const GSphere& lsph = spheres[lp.index];
                    // Uniform sphere surface sample
                    float u1 = curand_uniform(rng);
                    float u2 = curand_uniform(rng);
                    float z = 1.0f - 2.0f * u1;
                    float r = sqrtf(fmaxf(0.0f, 1.0f - z * z));
                    float phi = 2.0f * M_PI_F * u2;
                    GVec3 localP(r * cosf(phi), r * sinf(phi), z);
                    ls.position = lsph.center + localP * lsph.radius;
                    ls.normal = localP;
                    ls.pdf = 1.0f / (4.0f * M_PI_F * lsph.radius * lsph.radius);
                    // Emission
                    const GMaterial& lmat = materials[lsph.materialId];
                    GSampledSpectrum emitSpec = gpu_material_emitted_spectral(lmat, true, lambdas);
                    GVec3 xyz = spectrumToXYZ(emitSpec, lambdas);
                    // Convert XYZ to linear sRGB for GLightSample.emission
                    float r_ =  3.2406f * xyz.x - 1.5372f * xyz.y - 0.4986f * xyz.z;
                    float g_ = -0.9689f * xyz.x + 1.8758f * xyz.y + 0.0415f * xyz.z;
                    float b_ =  0.0557f * xyz.x - 0.2040f * xyz.y + 1.0570f * xyz.z;
                    ls.emission = GVec3(r_, g_, b_);
                } else {
                    // Triangle or other primitive — skip for Phase 2 (sphere caster only).
                    ls.pdf = 0.0f;
                }

                if (ls.pdf > 0.0f) {
                    // Get caster material IOR at hero wavelength.
                    // C.primId is index into prims[]; prims[C.primId].index is the sphere index.
                    float eta = 1.0f;
                    const GPrimitive& casterPrim = prims[C.primId];
                    if (casterPrim.type == GPRIM_SPHERE) {
                        const GSphere& casterSph = spheres[casterPrim.index];
                        const GMaterial& casterMat = materials[casterSph.materialId];
                        if (casterMat.type == GMAT_DIELECTRIC) {
                            eta = 1.0f / casterMat.ior;
                        }
                    }

                    astroray::manifold::device::GSMSConfig cfg;
                    cfg.seeds = 1;
                    cfg.maxIterations = 20;
                    cfg.tolerance = 1e-4f;
                    cfg.contribClamp = 4.0f;

                    float r1 = curand_uniform(rng);
                    float r2 = curand_uniform(rng);

                    GSampledSpectrum fSpec;
                    float w = 0.0f, Tr = 0.0f;
                    GVec3 Le(0.0f), wi(0.0f);

                    if (astroray::manifold::device::runSMSAttemptDevice(
                            bvhNodes, prims, tris, spheres, materials,
                            rec, primaryRay, lambdas, r1, r2, C, eta, casterPickPdf,
                            ls, cfg, fSpec, w, Le, Tr, wi)) {
                        // Clamp and accumulate hero-channel contribution
                        float fHero = fSpec.v[0];
                        // Convert Le (linear sRGB) to spectral
                        GSampledSpectrum LeSpec = gpu_rgbToSampledSpectrum(Le, lambdas, GSPEC_RGB_ILLUMINANT);
                        float LeHero = LeSpec.v[0];
                        float sampleHero = fHero * LeHero * Tr * w;
                        if (sampleHero > cfg.contribClamp) sampleHero = cfg.contribClamp;
                        if (sampleHero < 0.0f) sampleHero = 0.0f;

                        // Additive MIS: write contribution to hero channel only (matches CPU hook).
                        GSampledSpectrum smsContrib(0.0f);
                        smsContrib.v[0] = sampleHero;
                        color += throughput * smsContrib;
                    }
                }
            }
        }

        // Russian roulette
        if (bounce > rrDepth) {
            float p;
            if (useLuminanceOutput) {
                float avg = 0.f;
                for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) avg += throughput.v[i];
                p = fminf(0.95f, fmaxf(0.f, avg / float(G_SPECTRUM_SAMPLES)));
            } else {
                GVec3 thrXYZ = spectrumToXYZ(throughput, lambdas);
                p = fminf(0.95f, fmaxf(0.f, thrXYZ.y));
            }
            if (curand_uniform(rng) > p) break;
            if (p > 0.f) throughput *= (1.f / p);
        }

        // BSDF sample.
        GBSDFSample bs = gpu_material_sample_spectral(mat, rec, wo, lambdas, rng);
        if (bs.pdf <= 0.f) break;
        wasSpecular = bs.isDelta;

        // pkg54a: profile-aware spectral override for non-delta paths.
        // Mirrors CPU `Material::evalSpectralExt`:
        //   * visible λ → keep gpu_rgbToSampledSpectrum result (bs.fSpectral),
        //   * non-visible λ + profile → reflectance(λ) * cosθ / π,
        //   * non-visible λ + no profile → 0.
        // Delta materials (specular) keep the RGB-derived spectrum unchanged.
        if (!bs.isDelta) {
            float cosTheta = fmaxf(0.f, rec.normal.dot(bs.wi));
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
                float lam = lambdas.lambda[i];
                if (lam < 380.f || lam > 780.f) {
                    if (mat.profileIndex >= 0) {
                        bs.fSpectral.v[i] =
                            gpu_profile_reflectance(mat.profileIndex, lam)
                            * cosTheta / M_PI_F;
                    } else {
                        bs.fSpectral.v[i] = 0.f;
                    }
                }
            }
        }

        throughput *= bs.fSpectral * (1.f / (bs.pdf + 0.001f));

        // Throughput clamp (firefly guard, matches CPU).
        float maxC = throughput.maxValue();
        if (maxC > 10.f) throughput *= (10.f / maxC);

        // pkg88-C.0: bounce rays inherit the path's shutter time.
        ray = GRay(rec.point, bs.wi, ray.time);
    }

    return color;
}

// ---------------------------------------------------------------------------
// Multiwavelength megakernel
// ---------------------------------------------------------------------------
// pkg88-C.0: base-2 radical inverse for the per-spp shutter time. Same
// sampler as the RGB megakernel's Phase-A camera time (path_trace_kernel.cu
// haltonBase2) — TU-local copy because both kernels keep device helpers
// file-static.
__device__ inline float gpu_mw_haltonBase2(int index) {
    float result = 0.0f;
    float f = 1.0f;
    int i = index;
    while (i > 0) {
        f = f / 2.0f;
        result += f * (i % 2);
        i = i / 2;
    }
    return result;
}

__global__ void multiwavelengthKernel(
    float* framebuffer, int width, int height,
    int samplesPerPixel, int maxDepth,
    int worldMaxBounces,  // pkg55-B' N+6 follow-up: env gate, raytracer.h:2412
    float lambdaMin, float lambdaMax,
    bool  useLuminanceOutput,
    bool  enableNEE,
    bool  useCaustics,  // pkg64-gpu Phase 2
    const GTLASNode*  tlas,        // pkg114
    const GInstance*  instances,   // pkg114
    const GBLAS*      blas,        // pkg114
    const GBVHNode*  bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GMaterial*  materials,
    const GLight*     lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,  // pkg86-B
    const astroray::manifold::device::GSMSCaster* smsCasters, int numSMSCasters,  // pkg64-gpu Phase 2
    GEnvMap envMap,
    GCameraParams cam,
    GVec3 backgroundColor, bool hasBackgroundColor,
    astroray::photon::gpu::GPhotonGrid photonGrid, bool hasPhotonGrid,  // pkg113 Phase 3
    float photonScale,                                                   // pkg113 Phase 3
    const GVec3* d_motionVertices,  // pkg88-C.0 (nullptr = static scene)
    curandState* rngStates)
{
    int pixelIdx = blockIdx.x * blockDim.x + threadIdx.x;
    int totalPixels = width * height;
    if (pixelIdx >= totalPixels) return;

    int px = pixelIdx % width;
    int py = pixelIdx / width;

    curandState localRng = rngStates[pixelIdx];

    // pkg85-D: accumulate in XYZ (or luminance-triplet) across SPP, then convert
    // to linear sRGB ONCE at the end. The CPU integrator does the same:
    //   raytracer.h:2548  sCol = finiteVecOrZero(XYZ)
    //   raytracer.h:2550  firefly clamp on XYZ.Y > 20
    //   raytracer.h:2552  color += sCol     (XYZ accumulation)
    //   raytracer.h:2579  color /= samples
    //   raytracer.h:2595  color = xyzToLinearSRGB(color)   (single conversion)
    // The prior order (per-sample xyzToLinearSRGB → average) does not commute
    // with averaging because xyzToLinearSRGB's negative-channel lift is
    // non-linear; bluish HDRI samples produce negative R that the lift adds
    // to G/B every sample, biasing green/blue upward. SSIM-killer.
    GVec3 colorAccum(0.f);
    for (int s = 0; s < samplesPerPixel; ++s) {
        float u = (px + curand_uniform(&localRng)) / (width  - 1);
        float v = 1.f - (py + curand_uniform(&localRng)) / (height - 1);

        GVec3 rd     = gpu_randomInUnitDisk(&localRng) * cam.lensRadius;
        GVec3 offset = cam.u * rd.x + cam.v * rd.y;
        GVec3 dir    = cam.lowerLeft + cam.horizontal*u + cam.vertical*v
                       - cam.origin - offset;
        GRay ray(cam.origin + offset, dir);
        // pkg88-C.0: per-spp shutter time for deformation motion (independent
        // Halton base-2, same policy as the RGB megakernel / Phase A; spec
        // Q-Owner-4: ONE consistent policy). NOTE: the MW kernel's camera is
        // not shutter-interpolated (Phase-A camera MB lives in the RGB kernel
        // only) — geometry motion works here, camera motion is a known gap.
        ray.time = gpu_mw_haltonBase2(s + 1);

        GSampledWavelengths lambdas =
            gpu_sampleBandWavelengths(&localRng, lambdaMin, lambdaMax);

        GSampledSpectrum rad = tracePathMW(
            ray, maxDepth, worldMaxBounces,
            lambdas, useLuminanceOutput, enableNEE, useCaustics,
            tlas, instances, blas,  // pkg114
            bvhNodes, prims, tris, spheres, materials,
            lights, numLights, totalLightPower,
            lightTree,  // pkg86-B
            smsCasters, numSMSCasters,
            envMap, backgroundColor, hasBackgroundColor,
            ray,  // primaryRay for SMS wo_eye
            d_motionVertices,  // pkg88-C.0
            &localRng);

        GVec3 sample;
        if (useLuminanceOutput) {
            float L = 0.f;
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) L += rad.v[i];
            L = fmaxf(0.f, L / float(G_SPECTRUM_SAMPLES));
            sample = GVec3(L, L, L);
        } else {
            // XYZ tristimulus (linear, additive, matches CPU sCol).
            sample = spectrumToXYZ(rad, lambdas);
        }

        // pkg113 Phase 3: photon-map caustic gather at the primary first hit,
        // added in XYZ space — the device twin of spectral_path_tracer.cpp::
        // sampleFull (l.207-221), which re-hits the first surface after the
        // spectral path trace and adds albedo·E·causticScale to the XYZ. The grid
        // gather returns E = (1/πr²)Σpower (Jensen 2000 Eq. 8); causticScale folds
        // the Lambertian 1/π. Only meaningful for the visible-band (XYZ) output.
        if (hasPhotonGrid && !useLuminanceOutput && photonGrid.numPhotons > 0) {
            GHitRecord pr;
            // pkg88-C.0: re-hit the primary at its shutter time (ray carries it).
            if (gpu_tlas_hit(tlas, instances, blas, bvhNodes, prims, tris, spheres,
                            ray, 0.001f, 1e30f, pr, d_motionVertices)) {
                const GMaterial& pmat = materials[pr.materialId];
                if (pmat.emissionIntensity <= 0.0f) {
                    int found = 0;
                    GVec3 E = astroray::photon::gpu::photonGridGatherKnn(
                        photonGrid, pr.point, 50, 1.1f, found);
                    if (found > 0) {
                        GVec3 alb = pmat.baseColor;
                        sample += GVec3(alb.x * E.x, alb.y * E.y, alb.z * E.z)
                                  * photonScale;
                    }
                }
            }
        }

        // finiteVecOrZero — replace NaN/Inf with zero (matches CPU).
        sample.x = isfinite(sample.x) ? sample.x : 0.f;
        sample.y = isfinite(sample.y) ? sample.y : 0.f;
        sample.z = isfinite(sample.z) ? sample.z : 0.f;

        // Per-sample firefly clamp on XYZ.Y (photometric luminance, matches CPU
        // raytracer.h:2550). For useLuminanceOutput the triplet is (L,L,L) so
        // .y == L; same clamp applies.
        float sLum = sample.y;
        if (sLum > 20.f) sample *= (20.f / sLum);

        colorAccum += sample;
    }

    colorAccum /= float(samplesPerPixel);

    // Single XYZ→sRGB conversion (skipped for useLuminanceOutput — already
    // luminance triplet). Mirrors CPU raytracer.h:2595.
    GVec3 colorRGB = useLuminanceOutput ? colorAccum
                                        : xyzToLinearSRGB_dev(colorAccum);
    colorRGB.x = fmaxf(colorRGB.x, 0.f);
    colorRGB.y = fmaxf(colorRGB.y, 0.f);
    colorRGB.z = fmaxf(colorRGB.z, 0.f);

    framebuffer[pixelIdx*3 + 0] = colorRGB.x;
    framebuffer[pixelIdx*3 + 1] = colorRGB.y;
    framebuffer[pixelIdx*3 + 2] = colorRGB.z;

    rngStates[pixelIdx] = localRng;
}

// ---------------------------------------------------------------------------
// Launcher — called from cuda_renderer.cu
// ---------------------------------------------------------------------------
void launchMultiwavelengthKernel(
    float* d_framebuffer, int width, int height,
    int samplesPerPixel, int maxDepth,
    int worldMaxBounces,  // pkg55-B' N+6 follow-up: env gate, raytracer.h:2412
    float lambdaMin, float lambdaMax, bool useLuminanceOutput,
    bool enableNEE,
    bool useCaustics,  // pkg64-gpu Phase 2
    const GTLASNode*  d_tlas, const GInstance* d_instances, const GBLAS* d_blas,  // pkg114
    const GBVHNode*  d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GMaterial*  d_materials,
    const GLight*     d_lights, int numLights, float totalLightPower,
    GLightTreeView lightTree,  // pkg86-B
    const astroray::manifold::device::GSMSCaster* d_smsCasters, int numSMSCasters,  // pkg64-gpu Phase 2
    GEnvMap envMap,
    GCameraParams cam,
    GVec3 backgroundColor, bool hasBackgroundColor,
    astroray::photon::gpu::GPhotonGrid photonGrid, bool hasPhotonGrid,  // pkg113 Phase 3
    float photonScale,                                                   // pkg113 Phase 3
    const GVec3* d_motionVertices,  // pkg88-C.0
    curandState* d_rngStates)
{
    int totalPixels    = width * height;
    int threadsPerBlock = 256;
    int blocks         = (totalPixels + threadsPerBlock - 1) / threadsPerBlock;

    {
        astroray::gpu_profile::ScopedTimer _t(
            "multiwavelength_megakernel",
            (const void*)multiwavelengthKernel, blocks, threadsPerBlock);
        multiwavelengthKernel<<<blocks, threadsPerBlock>>>(
            d_framebuffer, width, height, samplesPerPixel, maxDepth,
            worldMaxBounces,
            lambdaMin, lambdaMax, useLuminanceOutput, enableNEE, useCaustics,
            d_tlas, d_instances, d_blas,  // pkg114
            d_bvhNodes, d_prims, d_tris, d_spheres, d_materials,
            d_lights, numLights, totalLightPower,
            lightTree,  // pkg86-B
            d_smsCasters, numSMSCasters,
            envMap, cam, backgroundColor, hasBackgroundColor,
            photonGrid, hasPhotonGrid, photonScale,  // pkg113 Phase 3
            d_motionVertices,  // pkg88-C.0
            d_rngStates);

        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            fprintf(stderr, "MW kernel launch error: %s\n", cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
        // pkg85-B: check the post-launch sync. A discarded error here (e.g.
        // illegal memory access surfaced asynchronously) becomes latent
        // device state that contaminates the next test/renderer.
        cudaError_t syncErr = cudaDeviceSynchronize();
        if (syncErr != cudaSuccess) {
            fprintf(stderr, "MW kernel runtime error: %s\n",
                    cudaGetErrorString(syncErr));
            throw std::runtime_error(cudaGetErrorString(syncErr));
        }
    }
}
