// path_trace_kernel.cu — CUDA megakernel for path tracing.
// One thread per pixel; each thread loops over samplesPerPixel.
// Directly ports Renderer::pathTrace() and Renderer::sampleDirect()
// using the GPU-side material/BVH headers.

#include "astroray/gpu_types.h"
#include "astroray/gpu_materials.h"
#include "astroray/gpu_bvh.h"

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
    const GBVHNode*  bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GMaterial*  materials,
    const GLight*     lights, int numLights, float totalLightPower,
    const GEnvMap&    envMap,
    const GVec3&      backgroundColor,
    bool              hasBackgroundColor,
    curandState*      rng)
{
    const int rrDepth = 3;
    GVec3 color(0.f), throughput(1.f);
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
            break;
        }

        // Emissive surface
        const GMaterial& mat = materials[rec.materialId];
        GVec3 emitted = gpu_material_emitted(mat, rec.frontFace);
        if (emitted != GVec3(0.f)) {
            if (bounce == 0 || wasSpecular)
                color += throughput * emitted;
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

        // Russian Roulette
        if (bounce > rrDepth) {
            float p = fminf(0.95f, luminance(throughput));
            if (curand_uniform(rng) > p) break;
            throughput /= p;
        }

        // Sample BSDF for next bounce
        GVec3 wo = -ray.direction.normalized();
        GBSDFSample bs = gpu_material_sample(mat, rec, wo, rng);
        if (bs.pdf <= 0.f) break;

        wasSpecular = bs.isDelta;
        throughput *= bs.f / (bs.pdf + 0.001f);

        // Throughput clamp (firefly suppression, same as CPU)
        float maxC = throughput.maxComponent();
        if (maxC > 10.f) throughput *= 10.f / maxC;

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
    const GBVHNode*  bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GMaterial*  materials,
    const GLight*     lights, int numLights, float totalLightPower,
    GEnvMap envMap,
    GCameraParams cam,
    float filmExposure,
    GVec3 backgroundColor, bool hasBackgroundColor,
    curandState* rngStates)
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

        GVec3 rd     = gpu_randomInUnitDisk(&localRng) * cam.lensRadius;
        GVec3 offset = cam.u * rd.x + cam.v * rd.y;
        GVec3 dir    = cam.lowerLeft + cam.horizontal*u + cam.vertical*v
                       - cam.origin - offset;
        GRay ray(cam.origin + offset, dir);

        GVec3 sample = tracePathGPU(
            ray, maxDepth, bvhNodes, prims, tris, spheres,
            materials, lights, numLights, totalLightPower,
            envMap, backgroundColor, hasBackgroundColor, &localRng);

        // Per-sample firefly clamp (matches CPU: lum > 20 → scale down)
        float lum = luminance(sample);
        if (lum > 20.f) sample *= (20.f / lum);

        color += sample;
    }

    color /= (float)samplesPerPixel;
    color *= filmExposure;

    // Gamma correction + clamp
    color.x = powf(fminf(fmaxf(color.x, 0.f), 1.f), 1.f/2.2f);
    color.y = powf(fminf(fmaxf(color.y, 0.f), 1.f), 1.f/2.2f);
    color.z = powf(fminf(fmaxf(color.z, 0.f), 1.f), 1.f/2.2f);

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
    const GBVHNode*  d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GMaterial*  d_materials,
    const GLight*     d_lights, int numLights, float totalLightPower,
    GEnvMap envMap,
    GCameraParams cam,
    float filmExposure,
    GVec3 backgroundColor, bool hasBackgroundColor,
    curandState* d_rngStates)
{
    int totalPixels    = width * height;
    int threadsPerBlock = 256;
    int blocks         = (totalPixels + threadsPerBlock - 1) / threadsPerBlock;

    pathTraceKernel<<<blocks, threadsPerBlock>>>(
        d_framebuffer, width, height, samplesPerPixel, maxDepth,
        d_bvhNodes, d_prims, d_tris, d_spheres, d_materials,
        d_lights, numLights, totalLightPower,
        envMap, cam, filmExposure, backgroundColor, hasBackgroundColor,
        d_rngStates);

    cudaError_t err = cudaGetLastError();
    if (err != cudaSuccess) {
        fprintf(stderr, "Kernel launch error: %s\n", cudaGetErrorString(err));
        throw std::runtime_error(cudaGetErrorString(err));
    }
    cudaDeviceSynchronize();
}

void launchInitRNG(curandState* d_states, int n, unsigned long long seed) {
    int blocks = (n + 255) / 256;
    initRNGKernel<<<blocks, 256>>>(d_states, n, seed);
    cudaDeviceSynchronize();
}
