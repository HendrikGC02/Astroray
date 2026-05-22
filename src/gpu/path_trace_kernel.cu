// path_trace_kernel.cu — CUDA megakernel for path tracing.
// One thread per pixel; each thread loops over samplesPerPixel.
// Directly ports Renderer::pathTrace() and Renderer::sampleDirect()
// using the GPU-side material/BVH headers.

#include "astroray/gpu_types.h"
#include "astroray/gpu_materials.h"
#include "astroray/gpu_bvh.h"
#include "astroray/manifold/sms_attempt_device.cuh"  // pkg64-gpu Phase 2
#include "astroray/cryptomatte.h"  // pkg87b
#include "profile.h"  // pkg55-A: env-gated CUDA-event + NVTX instrumentation

#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <cstdio>
#include <stdexcept>

#define CUDA_CHECK(call) do {                                           \
    cudaError_t _e = (call);                                           \
    if (_e != cudaSuccess) {                                           \
        fprintf(stderr, "CUDA error at %s:%d: %s\n",                  \
                __FILE__, __LINE__, cudaGetErrorString(_e));           \
        throw std::runtime_error(cudaGetErrorString(_e));             \
    }                                                                   \
} while(0)

// ---------------------------------------------------------------------------
// pkg88-A: device-side quaternion slerp and camera interpolation
// Mirrored from PBRT-v4 Quaternion::Slerp and AnimatedTransform::Interpolate (Apache-2.0).
// ---------------------------------------------------------------------------
struct GQuaternion {
    float w, x, y, z;
    __device__ GQuaternion(float w, float x, float y, float z) : w(w), x(x), y(y), z(z) {}
    __device__ float dot(const GQuaternion& q) const { return w*q.w + x*q.x + y*q.y + z*q.z; }
    __device__ float length() const { return sqrtf(w*w + x*x + y*y + z*z); }
    __device__ GQuaternion normalized() const {
        float len = length();
        return (len > 0) ? GQuaternion(w/len, x/len, y/len, z/len) : GQuaternion(1,0,0,0);
    }
    __device__ GQuaternion operator+(const GQuaternion& q) const {
        return GQuaternion(w+q.w, x+q.x, y+q.y, z+q.z);
    }
    __device__ GQuaternion operator-(const GQuaternion& q) const {
        return GQuaternion(w-q.w, x-q.x, y-q.y, z-q.z);
    }
    __device__ GQuaternion operator*(float s) const {
        return GQuaternion(w*s, x*s, y*s, z*s);
    }
    __device__ void toMatrix(GVec3& outU, GVec3& outV, GVec3& outW) const {
        float xx = x*x, yy = y*y, zz = z*z;
        float xy = x*y, xz = x*z, yz = y*z;
        float wx = w*x, wy = w*y, wz = w*z;
        outU = GVec3(1 - 2*(yy + zz), 2*(xy + wz), 2*(xz - wy));
        outV = GVec3(2*(xy - wz), 1 - 2*(xx + zz), 2*(yz + wx));
        outW = GVec3(2*(xz + wy), 2*(yz - wx), 1 - 2*(xx + yy));
    }
};

__device__ inline GQuaternion slerp(float t, const GQuaternion& q1, const GQuaternion& q2) {
    float cosTheta = q1.dot(q2);
    if (cosTheta > 0.9995f) {
        return ((q1 * (1 - t)) + (q2 * t)).normalized();
    }
    float theta = acosf(fminf(fmaxf(cosTheta, -1.0f), 1.0f));
    float thetap = theta * t;
    GQuaternion qperp = (q2 - (q1 * cosTheta)).normalized();
    return (q1 * cosf(thetap)) + (qperp * sinf(thetap));
}

__device__ inline float haltonBase2(int index) {
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

// ---------------------------------------------------------------------------
// MIS power heuristic (balance: a²/(a²+b²))
// ---------------------------------------------------------------------------
__device__ inline float powerHeuristic(float a, float b) {
    float a2 = a*a, b2 = b*b;
    float d = a2 + b2;
    return (d < 1e-8f) ? 0.5f : a2 / d;
}

// ---------------------------------------------------------------------------
// gpu_light_pdf — total light PDF for a given wi direction (mirrors LightList::pdfValue)
// Computes combined solid-angle PDF across all lights, scaled by pArea.
// ---------------------------------------------------------------------------
__device__ inline float gpu_light_pdf(
    const GVec3& origin, const GVec3& wi,
    const GPrimitive* prims, const GTriangle* tris, const GSphere* spheres,
    const GLight* lights, int numLights, float totalLightPower,
    int hitPrimId,  // primId from the BSDF-ray hit record
    float hitDist,  // distance to the hit surface
    float pArea)
{
    if (numLights == 0 || totalLightPower <= 0.f) return 0.f;
    float pdf = 0.f;
    for (int i = 0; i < numLights; ++i) {
        const GLight& l = lights[i];
        float selPdf = l.power / totalLightPower;
        int primIdx = l.primitiveIndex;
        if (primIdx < 0) continue;
        const GPrimitive& lp = prims[primIdx];
        // pkg85-C: CPU-only light primitives (DistantLight, etc.) are
        // GPRIM_SKIP on the GPU; they contribute no area-light PDF here.
        if (lp.type == GPRIM_SKIP) continue;
        if (lp.type == GPRIM_SPHERE) {
            const GSphere& s = spheres[lp.index];
            float dist2 = (s.center - origin).length2();
            if (dist2 <= s.radius * s.radius + 1e-8f) continue;
            float cosTM = sqrtf(fmaxf(0.f, 1.f - s.radius*s.radius / dist2));
            if (cosTM >= 1.f) continue;
            pdf += selPdf / (2.f * M_PI_F * (1.f - cosTM));
        } else {
            // Triangle: only contributes if this was the hit primitive
            if (primIdx != hitPrimId) continue;
            const GTriangle& t = tris[lp.index];
            GVec3 e1 = t.v1 - t.v0, e2 = t.v2 - t.v0;
            float area = e1.cross(e2).length() * 0.5f;
            float NdotWi = fabsf(t.n0.dot(wi));
            if (NdotWi < 1e-8f || area < 1e-8f) continue;
            pdf += selPdf * hitDist*hitDist / (NdotWi * area);
        }
    }
    return pdf * pArea;
}

// ---------------------------------------------------------------------------
// sampleDirectGPU — port of Renderer::sampleDirect()
// ---------------------------------------------------------------------------
__device__ GVec3 sampleDirectGPU(
    const GHitRecord& rec,
    const GVec3& wo,
    const GBVHNode*  bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GMaterial*  materials,
    const GLight*     lights, int numLights, float totalLightPower,
    const GEnvMap&    envMap,
    curandState*      rng)
{
    const GMaterial& mat = materials[rec.materialId];
    if (rec.isDelta) return GVec3(0.f);
    // No direct illumination sources at all
    bool hasLights = (numLights > 0 && totalLightPower > 0.f);
    bool hasEnv    = envMap.loaded;
    if (!hasLights && !hasEnv) return GVec3(0.f);

    GVec3 direct(0.f);

    // Selection probability for env vs area lights (mirrors CPU envSelectProb())
    float pEnv = 0.f;
    if (hasEnv && !hasLights) pEnv = 1.f;
    else if (hasEnv && hasLights) pEnv = 0.5f;

    bool sampleEnv = hasEnv && (curand_uniform(rng) < pEnv);

    // ---- Environment map light sample ----
    if (sampleEnv) {
        GEnvSample es = gpu_envmap_sample(envMap, rng);
        if (es.pdf > 1e-8f) {
            GHitRecord shadow;
            bool occluded = gpu_bvh_hit(bvhNodes, prims, tris, spheres,
                                        GRay(rec.point, es.direction),
                                        0.001f, 1e30f, shadow);
            if (!occluded) {
                GVec3 f       = gpu_material_eval(mat, const_cast<GHitRecord&>(rec), wo, es.direction);
                float bsdfPdf = gpu_material_pdf(mat, rec, wo, es.direction);
                float combPdf = pEnv * es.pdf;
                float wt      = powerHeuristic(combPdf, bsdfPdf);
                direct += f * es.radiance * wt / (combPdf + 0.001f);
            }
        }
    }
    // ---- Area light sample ----
    else if (hasLights) {
        float pArea = 1.f - pEnv;

        // Power-weighted light selection via CDF
        float u = curand_uniform(rng) * totalLightPower;
        int   li = 0;
        for (int i = 0; i < numLights; ++i) {
            if (u <= lights[i].cumulativePower) { li = i; break; }
            li = i;
        }
        float selPdf = lights[li].power / totalLightPower;

        // Sample a point on the chosen light primitive
        int primIdx = lights[li].primitiveIndex;
        if (primIdx < 0) goto bsdf_mis;

        {
            const GPrimitive& lp = prims[primIdx];
            // pkg85-C: CPU-only light primitives are GPRIM_SKIP on the GPU.
            // No GPU area-light sample is possible — fall through to BSDF MIS.
            if (lp.type == GPRIM_SKIP) goto bsdf_mis;
            GVec3 lightPoint, lightNormal;
            if (lp.type == GPRIM_SPHERE) {
                const GSphere& s = spheres[lp.index];
                // Sample solid angle subtended by sphere (same as CPU Sphere::random)
                GVec3 dir    = (s.center - rec.point).normalized();
                float distSq = (s.center - rec.point).length2();
                float cosTM  = sqrtf(1.f - s.radius*s.radius / distSq);
                float z      = 1.f + curand_uniform(rng) * (cosTM - 1.f);
                float phi    = 2.f * M_PI_F * curand_uniform(rng);
                GVec3 tu, tv;
                gpu_buildONB(dir, tu, tv);
                float sinTh  = sqrtf(fmaxf(0.f, 1.f - z*z));
                GVec3 wi     = (tu*cosf(phi)*sinTh + tv*sinf(phi)*sinTh + dir*z).normalized();

                // Solid-angle PDF for sphere: 1 / (2π(1-cosThetaMax))
                float lightPdf = (cosTM < 1.f) ? 1.f / (2.f*M_PI_F*(1.f - cosTM)) : 0.f;
                lightPdf *= selPdf;

                GHitRecord shadow;
                if (!gpu_bvh_hit(bvhNodes, prims, tris, spheres,
                                 GRay(rec.point, wi), 0.001f, 1e30f, shadow) ||
                    shadow.materialId != spheres[lp.index].materialId)
                    goto bsdf_mis;

                const GMaterial& lm = materials[shadow.materialId];
                GVec3 Le = gpu_material_emitted(lm, shadow.frontFace);
                if (Le == GVec3(0.f)) goto bsdf_mis;

                float combinedPdf = pArea * lightPdf;
                GVec3 f = gpu_material_eval(mat, const_cast<GHitRecord&>(rec), wo, wi);
                float bsdfPdf = gpu_material_pdf(mat, rec, wo, wi);
                float wt = powerHeuristic(combinedPdf, bsdfPdf);
                direct += f * Le * wt / (combinedPdf + 0.001f);

            } else {
                // Triangle light — random point on triangle
                const GTriangle& t = tris[lp.index];
                float r1 = curand_uniform(rng), r2 = curand_uniform(rng);
                if (r1 + r2 > 1.f) { r1 = 1.f-r1; r2 = 1.f-r2; }
                GVec3 lpos = t.v0 + (t.v1 - t.v0)*r1 + (t.v2 - t.v0)*r2;
                GVec3 wi   = (lpos - rec.point).normalized();
                float dist = (lpos - rec.point).length();

                // Area PDF → solid angle PDF
                GVec3 e1 = t.v1 - t.v0, e2 = t.v2 - t.v0;
                float area = e1.cross(e2).length() * 0.5f;
                float NdotWi = fabsf(t.n0.dot(wi));
                float lightPdf = (dist*dist) / (NdotWi * area + 0.001f);
                lightPdf *= selPdf;

                GHitRecord shadow;
                bool occ = gpu_bvh_hit(bvhNodes, prims, tris, spheres,
                                       GRay(rec.point, wi), 0.001f, dist - 0.001f, shadow);
                if (occ) goto bsdf_mis;

                const GMaterial& lm = materials[t.materialId];
                GVec3 Le = gpu_material_emitted(lm, true);
                if (Le == GVec3(0.f)) goto bsdf_mis;

                float combinedPdf = pArea * lightPdf;
                GVec3 f = gpu_material_eval(mat, const_cast<GHitRecord&>(rec), wo, wi);
                float bsdfPdf = gpu_material_pdf(mat, rec, wo, wi);
                float wt = powerHeuristic(combinedPdf, bsdfPdf);
                direct += f * Le * wt / (combinedPdf + 0.001f);
            }
        }
    }

bsdf_mis:
    // ---- BSDF sample — MIS against lights AND environment ----
    {
        GHitRecord tmpRec = rec;
        GBSDFSample bs = gpu_material_sample(mat, tmpRec, wo, rng);
        if (bs.pdf > 1e-8f && !bs.isDelta) {
            GHitRecord bRec;
            bRec.primId = -1;
            if (gpu_bvh_hit(bvhNodes, prims, tris, spheres,
                            GRay(rec.point, bs.wi), 0.001f, 1e30f, bRec)) {
                const GMaterial& lm = materials[bRec.materialId];
                GVec3 Le = gpu_material_emitted(lm, bRec.frontFace);
                if (Le != GVec3(0.f)) {
                    float pArea   = 1.f - pEnv;
                    float lightPdf = gpu_light_pdf(rec.point, bs.wi,
                                                   prims, tris, spheres,
                                                   lights, numLights, totalLightPower,
                                                   bRec.primId, bRec.t, pArea);
                    direct += bs.f * Le * powerHeuristic(bs.pdf, lightPdf) / (bs.pdf + 0.001f);
                }
            } else if (hasEnv) {
                GVec3 Le       = gpu_envmap_lookup(envMap, bs.wi.normalized());
                float lightPdf = pEnv * gpu_envmap_pdf(envMap, bs.wi.normalized());
                direct += bs.f * Le * powerHeuristic(bs.pdf, lightPdf) / (bs.pdf + 0.001f);
            }
        }
    }

    return direct;
}

// ---------------------------------------------------------------------------
// tracePathGPU — port of Renderer::pathTrace()
// ---------------------------------------------------------------------------
__device__ GVec3 tracePathGPU(
    GRay ray, int maxDepth,
    bool useCaustics,  // pkg64-gpu Phase 2
    const GBVHNode*  bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GMaterial*  materials,
    const GLight*     lights, int numLights, float totalLightPower,
    const astroray::manifold::device::GSMSCaster* smsCasters, int numSMSCasters,  // pkg64-gpu Phase 2
    const GEnvMap&    envMap,
    const GVec3&      backgroundColor,
    bool              hasBackgroundColor,
    GRay              primaryRay,  // pkg64-gpu Phase 2
    curandState*      rng,
    float*            cryptoObjectRanks = nullptr,    // pkg87b
    float*            cryptoMaterialRanks = nullptr,  // pkg87b
    int               cryptoDepth = 6,                 // pkg87b
    bool              cryptomatteEnabled = false)      // pkg87b
{
    const int rrDepth = 3;
    GVec3 color(0.f), throughput(1.f);
    GSampledWavelengths lambdas = gpu_sampleUniformWavelengths(rng);
    GSampledSpectrum colorSpectral(0.f), throughputSpectral(1.f);
    bool  wasSpecular = true;

    for (int bounce = 0; bounce < maxDepth; ++bounce) {
        GHitRecord rec;
        if (!gpu_bvh_hit(bvhNodes, prims, tris, spheres,
                         ray, 0.001f, 1e30f, rec)) {
            // Miss — environment / background
            GVec3 envColor(0.f);
            if (envMap.loaded) {
                envColor = gpu_envmap_lookup(envMap, ray.direction.normalized());
            } else if (hasBackgroundColor) {
                envColor = backgroundColor;
            } else {
                // Default sky gradient (same as CPU fallback)
                float t = 0.5f * (ray.direction.normalized().y + 1.f);
                envColor = GVec3(1.f)*(1.f-t) + GVec3(0.5f, 0.7f, 1.f)*t;
                envColor *= 0.2f;
            }
            if (bounce == 0 || wasSpecular)
                color += throughput * envColor;
            if (bounce == 0 || wasSpecular)
                colorSpectral += throughputSpectral *
                    gpu_rgbToSampledSpectrum(envColor, lambdas, GSPEC_RGB_ILLUMINANT);
            break;
        }

        // Emissive surface
        const GMaterial& mat = materials[rec.materialId];
        GVec3 emitted = gpu_material_emitted(mat, rec.frontFace);
        GSampledSpectrum emittedSpectral = gpu_material_emitted_spectral(mat, rec.frontFace, lambdas);
        if (emitted != GVec3(0.f)) {
            if (bounce == 0 || wasSpecular) {
                color += throughput * emitted;
                colorSpectral += throughputSpectral * emittedSpectral;
            }
            break;
        }

        // NEE direct lighting
        if (!rec.isDelta) {
            GVec3 wo = -ray.direction.normalized();
            color += throughput * sampleDirectGPU(
                rec, wo, bvhNodes, prims, tris, spheres,
                materials, lights, numLights, totalLightPower,
                envMap, rng);
        }

        // pkg64-gpu Phase 2: SMS caustic attempt (RGB path mirrors spectral MW path).
        // The SMS attempt writes hero-channel contribution; the CPU hook converts to RGB via XYZ.
        // Here, we mirror that: get SMS hero contrib, convert via RGBIlluminantSpectrum→XYZ→sRGB.
        if (useCaustics && !rec.isDelta && numSMSCasters > 0 && numLights > 0) {
            int cIdx = (int)(curand_uniform(rng) * numSMSCasters);
            if (cIdx >= numSMSCasters) cIdx = numSMSCasters - 1;
            const auto& C = smsCasters[cIdx];
            float casterPickPdf = 1.0f / float(numSMSCasters);

            float u = curand_uniform(rng) * totalLightPower;
            int lIdx = numLights - 1;
            for (int li = 0; li < numLights; ++li) {
                if (u < lights[li].cumulativePower) { lIdx = li; break; }
            }
            const GLight& lt = lights[lIdx];
            int primIdx = lt.primitiveIndex;
            if (primIdx >= 0 && primIdx < (int)~0u) {
                const GPrimitive& lp = prims[primIdx];
                astroray::manifold::device::GLightSample ls;
                ls.pdf = 0.0f;

                if (lp.type == GPRIM_SPHERE) {
                    const GSphere& lsph = spheres[lp.index];
                    float u1 = curand_uniform(rng);
                    float u2 = curand_uniform(rng);
                    float z = 1.0f - 2.0f * u1;
                    float r = sqrtf(fmaxf(0.0f, 1.0f - z * z));
                    float phi = 2.0f * 3.14159265358979323846f * u2;
                    GVec3 localP(r * cosf(phi), r * sinf(phi), z);
                    ls.position = lsph.center + localP * lsph.radius;
                    ls.normal = localP;
                    ls.pdf = 1.0f / (4.0f * 3.14159265358979323846f * lsph.radius * lsph.radius);
                    const GMaterial& lmat = materials[lsph.materialId];
                    GVec3 emitRGB = gpu_material_emitted(lmat, true);
                    ls.emission = emitRGB;
                } else {
                    ls.pdf = 0.0f;
                }

                if (ls.pdf > 0.0f) {
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
                        // Convert hero contribution to RGB via XYZ (mirrors CPU hook).
                        float fHero = fSpec.v[0];
                        GSampledSpectrum LeSpec = gpu_rgbToSampledSpectrum(Le, lambdas, GSPEC_RGB_ILLUMINANT);
                        float LeHero = LeSpec.v[0];
                        float sampleHero = fHero * LeHero * Tr * w;
                        if (sampleHero > cfg.contribClamp) sampleHero = cfg.contribClamp;
                        if (sampleHero < 0.0f) sampleHero = 0.0f;

                        // Build a 1-channel spectral sample and convert to RGB via XYZ.
                        GSampledSpectrum smsSpec(0.0f);
                        smsSpec.v[0] = sampleHero;
                        GVec3 xyz = gpu_sampledSpectrumToXYZ(smsSpec, lambdas);
                        float r_ =  3.2406f * xyz.x - 1.5372f * xyz.y - 0.4986f * xyz.z;
                        float g_ = -0.9689f * xyz.x + 1.8758f * xyz.y + 0.0415f * xyz.z;
                        float b_ =  0.0557f * xyz.x - 0.2040f * xyz.y + 1.0570f * xyz.z;
                        GVec3 smsRGB(r_, g_, b_);
                        color += throughput * smsRGB;
                    }
                }
            }
        }

        // Russian Roulette
        if (bounce > rrDepth) {
            float p = fminf(0.95f, luminance(throughput));
            if (curand_uniform(rng) > p) break;
            throughput /= p;
        }

        // Sample BSDF for next bounce
        GVec3 wo = -ray.direction.normalized();
        GBSDFSample bs = gpu_material_sample_spectral(mat, rec, wo, lambdas, rng);
        if (bs.pdf <= 0.f) break;

        // pkg87b: Cryptomatte accumulation at shade point (before throughput update).
        // Weight = average(throughput · bsdf_eval), per Cycles.
        if (cryptomatteEnabled && cryptoObjectRanks && cryptoMaterialRanks) {
            GSampledSpectrum contrib = throughputSpectral * bs.fSpectral;
            // Convert spectral to XYZ, then to sRGB for weight computation
            GVec3 xyz = gpu_sampledSpectrumToXYZ(contrib, lambdas);
            float r =  3.2406f * xyz.x - 1.5372f * xyz.y - 0.4986f * xyz.z;
            float g = -0.9689f * xyz.x + 1.8758f * xyz.y + 0.0415f * xyz.z;
            float b =  0.0557f * xyz.x - 0.2040f * xyz.y + 1.0570f * xyz.z;
            float weight = (r + g + b) / 3.0f;

            // Extract object/material hash from GPU primitive data
            float objectId = CRYPTO_ID_NONE, materialId = CRYPTO_ID_NONE;
            if (rec.primType == GPRIM_TRIANGLE) {
                const GTriangle& tri = tris[rec.primIndex];
                objectId = tri.objectHash;
                materialId = tri.materialHash;
            } else if (rec.primType == GPRIM_SPHERE) {
                const GSphere& sph = spheres[rec.primIndex];
                objectId = sph.objectHash;
                materialId = sph.materialHash;
            }
            // crypto_accumulate_shade_point is __host__ __device__, pixelIndex already encoded in pointer offset
            crypto_accumulate_shade_point(cryptoObjectRanks, cryptoMaterialRanks,
                                           0, cryptoDepth, objectId, materialId, weight);
        }

        wasSpecular = bs.isDelta;
        throughput *= bs.f / (bs.pdf + 0.001f);
        throughputSpectral *= bs.fSpectral * (1.f / (bs.pdf + 0.001f));

        // Throughput clamp (firefly suppression, same as CPU)
        float maxC = throughput.maxComponent();
        if (maxC > 10.f) throughput *= 10.f / maxC;
        float maxS = throughputSpectral.maxValue();
        if (maxS > 10.f) throughputSpectral *= 10.f / maxS;

        ray = GRay(rec.point, bs.wi);
    }
    return color;
}

// ---------------------------------------------------------------------------
// RNG initialisation kernel
// ---------------------------------------------------------------------------
__global__ void initRNGKernel(curandState* states, int n, unsigned long long seed) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < n) curand_init(seed, idx, 0, &states[idx]);
}

// ---------------------------------------------------------------------------
// Path tracing megakernel
// ---------------------------------------------------------------------------
__global__ void pathTraceKernel(
    float* framebuffer, int width, int height,
    int samplesPerPixel, int maxDepth,
    bool useCaustics,  // pkg64-gpu Phase 2
    const GBVHNode*  bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GMaterial*  materials,
    const GLight*     lights, int numLights, float totalLightPower,
    const astroray::manifold::device::GSMSCaster* smsCasters, int numSMSCasters,  // pkg64-gpu Phase 2
    GEnvMap envMap,
    GCameraParams cam,
    float filmExposure,
    GVec3 backgroundColor, bool hasBackgroundColor,
    curandState* rngStates,
    float* cryptoObjectBuffer = nullptr,      // pkg87b
    float* cryptoMaterialBuffer = nullptr,    // pkg87b
    int cryptoDepth = 6,                       // pkg87b
    bool cryptomatteEnabled = false)           // pkg87b
{
    int pixelIdx = blockIdx.x * blockDim.x + threadIdx.x;
    int totalPixels = width * height;
    if (pixelIdx >= totalPixels) return;

    int px = pixelIdx % width;
    int py = pixelIdx / width;

    curandState localRng = rngStates[pixelIdx];

    GVec3 color(0.f);
    for (int s = 0; s < samplesPerPixel; ++s) {
        // Generate camera ray
        float u = (px + curand_uniform(&localRng)) / (width  - 1);
        float v = 1.f - (py + curand_uniform(&localRng)) / (height - 1);

        // pkg88-A: sample time from Halton base-2 (independent per spp)
        float time = haltonBase2(s + 1);

        GVec3 origin_cam, lowerLeft_cam, horizontal_cam, vertical_cam, u_cam, v_cam;

        // pkg88-A: if shutter is off, use current camera basis (pre-pkg88 path)
        if (cam.shutter <= 0.0f) {
            origin_cam = cam.origin;
            lowerLeft_cam = cam.lowerLeft;
            horizontal_cam = cam.horizontal;
            vertical_cam = cam.vertical;
            u_cam = cam.u;
            v_cam = cam.v;
        } else {
            // pkg88-A: interpolate camera transform at sampled time (T/R/S decomp + slerp)
            GVec3 T_interp = cam.shutterStartT * (1 - time) + cam.shutterEndT * time;
            GQuaternion startR(cam.shutterStartR[0], cam.shutterStartR[1],
                               cam.shutterStartR[2], cam.shutterStartR[3]);
            GQuaternion endR(cam.shutterEndR[0], cam.shutterEndR[1],
                             cam.shutterEndR[2], cam.shutterEndR[3]);
            GQuaternion R_interp = slerp(time, startR, endR);
            GVec3 S_interp = cam.shutterStartS * (1 - time) + cam.shutterEndS * time;

            GVec3 u_interp, v_interp, w_interp;
            R_interp.toMatrix(u_interp, v_interp, w_interp);
            u_interp = u_interp * S_interp.x;
            v_interp = v_interp * S_interp.y;
            w_interp = w_interp * S_interp.z;

            origin_cam = T_interp;
            horizontal_cam = u_interp * cam.vw;
            vertical_cam = v_interp * cam.vh;
            lowerLeft_cam = origin_cam - horizontal_cam * (0.5f - cam.shiftX)
                                        - vertical_cam * (0.5f - cam.shiftY)
                                        - w_interp * cam.focusDist;
            u_cam = u_interp;
            v_cam = v_interp;
        }

        GVec3 rd     = gpu_randomInUnitDisk(&localRng) * cam.lensRadius;
        GVec3 offset = u_cam * rd.x + v_cam * rd.y;
        GVec3 dir    = lowerLeft_cam + horizontal_cam*u + vertical_cam*v
                       - origin_cam - offset;
        GRay ray(origin_cam + offset, dir);

        // pkg87b: compute per-pixel crypto buffer offset
        float* pixelCryptoObj = nullptr;
        float* pixelCryptoMat = nullptr;
        if (cryptomatteEnabled && cryptoObjectBuffer && cryptoMaterialBuffer) {
            int offset = pixelIdx * cryptoDepth * 2;
            pixelCryptoObj = cryptoObjectBuffer + offset;
            pixelCryptoMat = cryptoMaterialBuffer + offset;
        }

        GVec3 sample = tracePathGPU(
            ray, maxDepth, useCaustics,
            bvhNodes, prims, tris, spheres,
            materials, lights, numLights, totalLightPower,
            smsCasters, numSMSCasters,
            envMap, backgroundColor, hasBackgroundColor,
            ray,  // primaryRay for SMS
            &localRng,
            pixelCryptoObj, pixelCryptoMat, cryptoDepth, cryptomatteEnabled);

        // Per-sample firefly clamp (matches CPU: lum > 20 → scale down)
        float lum = luminance(sample);
        if (lum > 20.f) sample *= (20.f / lum);

        color += sample;
    }

    color /= (float)samplesPerPixel;

    // Store linear scene-referred radiance (non-negative, unclamped above 1.0)
    color.x = fmaxf(color.x, 0.f);
    color.y = fmaxf(color.y, 0.f);
    color.z = fmaxf(color.z, 0.f);

    framebuffer[pixelIdx*3 + 0] = color.x;
    framebuffer[pixelIdx*3 + 1] = color.y;
    framebuffer[pixelIdx*3 + 2] = color.z;

    rngStates[pixelIdx] = localRng;
}

// ---------------------------------------------------------------------------
// Launcher — called from cuda_renderer.cu
// ---------------------------------------------------------------------------
void launchPathTraceKernel(
    float* d_framebuffer, int width, int height,
    int samplesPerPixel, int maxDepth,
    bool useCaustics,  // pkg64-gpu Phase 2
    const GBVHNode*  d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GMaterial*  d_materials,
    const GLight*     d_lights, int numLights, float totalLightPower,
    const astroray::manifold::device::GSMSCaster* d_smsCasters, int numSMSCasters,  // pkg64-gpu Phase 2
    GEnvMap envMap,
    GCameraParams cam,
    float filmExposure,
    GVec3 backgroundColor, bool hasBackgroundColor,
    curandState* d_rngStates,
    float* d_cryptoObjectBuffer = nullptr,      // pkg87b
    float* d_cryptoMaterialBuffer = nullptr,    // pkg87b
    int cryptoDepth = 6,                         // pkg87b
    bool cryptomatteEnabled = false)             // pkg87b
{
    int totalPixels    = width * height;
    int threadsPerBlock = 256;
    int blocks         = (totalPixels + threadsPerBlock - 1) / threadsPerBlock;

    {
        astroray::gpu_profile::ScopedTimer _t(
            "path_trace_megakernel",
            (const void*)pathTraceKernel, blocks, threadsPerBlock);
        pathTraceKernel<<<blocks, threadsPerBlock>>>(
            d_framebuffer, width, height, samplesPerPixel, maxDepth, useCaustics,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_materials,
            d_lights, numLights, totalLightPower,
            d_smsCasters, numSMSCasters,
            envMap, cam, filmExposure, backgroundColor, hasBackgroundColor,
            d_rngStates, d_cryptoObjectBuffer, d_cryptoMaterialBuffer,
            cryptoDepth, cryptomatteEnabled);

        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            fprintf(stderr, "Kernel launch error: %s\n", cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
        // pkg85-B: check post-launch sync — async errors (illegal memory
        // access, etc.) surface here and must not be discarded.
        cudaError_t syncErr = cudaDeviceSynchronize();
        if (syncErr != cudaSuccess) {
            fprintf(stderr, "Path-trace kernel runtime error: %s\n",
                    cudaGetErrorString(syncErr));
            throw std::runtime_error(cudaGetErrorString(syncErr));
        }
    }
}

void launchInitRNG(curandState* d_states, int n, unsigned long long seed) {
    int blocks = (n + 255) / 256;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "init_rng", (const void*)initRNGKernel, blocks, 256);
        initRNGKernel<<<blocks, 256>>>(d_states, n, seed);
        // pkg85-B: was previously discarding both the launch error and the
        // sync result. Check both.
        cudaError_t launchErr = cudaGetLastError();
        if (launchErr != cudaSuccess) {
            fprintf(stderr, "initRNG launch error: %s\n",
                    cudaGetErrorString(launchErr));
            throw std::runtime_error(cudaGetErrorString(launchErr));
        }
        cudaError_t syncErr = cudaDeviceSynchronize();
        if (syncErr != cudaSuccess) {
            fprintf(stderr, "initRNG runtime error: %s\n",
                    cudaGetErrorString(syncErr));
            throw std::runtime_error(cudaGetErrorString(syncErr));
        }
    }
}
