// stage_shade_lambertian.cu — pkg55 Phase B
//
// Shade kernel for GMAT_LAMBERTIAN surfaces. Reads hit record SoA,
// evaluates Lambertian BSDF, samples next bounce direction, emits NEE shadow
// ray, writes updated throughput + next ray to SoA.
//
// Architecture: Cycles (blender/cycles @ c9227ff, Apache-2.0)
//   intern/cycles/kernel/integrator/shade_surface.h — per-material shade
//   dispatch after sort (wavefront-gpu-research.md §4 "Sort-by-material").
//
// BSDF implementation: Astroray megakernel (path_trace_kernel.cu)
//   The Lambertian BSDF is inlined in tracePathGPU() at line 316-322.
//   This kernel mirrors that exact math — bit-identical by construction.
//
// BSDF paper: Lambertian reflectance is undergraduate-textbook material
//   (no citation needed per CLAUDE.md §6 "trivial" exemption).

#include "astroray/integrator_state_soa.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_materials.h"
#include "astroray/gpu_bvh.h"
#include "../profile.h"

#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <cstdio>

namespace astroray::wavefront {

namespace {

// Forward declare NEE helper from the megakernel
__device__ inline float powerHeuristic(float a, float b) {
    float a2 = a*a, b2 = b*b;
    float d = a2 + b2;
    return (d < 1e-8f) ? 0.5f : a2 / d;
}

__global__ void shadeLambertianKernel(
    // SoA input: all arrays sized by num_active
    const float4*  hit_point,
    const float4*  hit_normal,
    const float4*  hit_tangent,
    const float4*  hit_bitangent,
    const int*     hit_mat,
    const uint8_t* hit_flags,
    const int*     pixel_index,
    const int*     depth,
    const float4*  ray_direction_in,
    const float4*  lambda_in,
    const float4*  lambda_pdf_in,
    const float4*  throughput_in,
    const float4*  throughput_sp_in,
    const uint8_t* path_alive,
    // SoA output: next bounce
    float4*  ray_origin_out,
    float4*  ray_direction_out,
    float4*  throughput_out,
    float4*  throughput_sp_out,
    float*   pdf_out,
    uint8_t* was_specular_out,
    int*     depth_out,
    // SoA output: NEE shadow ray
    float4*  shadow_origin,
    float4*  shadow_dir,
    float*   shadow_tmax,
    float4*  nee_contrib,
    uint8_t* nee_active,
    // RNG
    curandState* rng_state,
    // Scene data
    const GMaterial* materials,
    const GLight* lights,
    int numLights,
    float totalLightPower,
    const GPrimitive* prims,
    const GTriangle* tris,
    const GSphere* spheres,
    const GEnvMap envMap,
    GVec3 bgColor,
    bool hasBg,
    int num_active,
    int maxDepth)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= num_active) return;
    if (path_alive[idx] == 0) return;  // skip dead paths

    // Material-type guard: only process GMAT_LAMBERTIAN
    const GMaterial& mat = materials[hit_mat[idx]];
    if (mat.type != GMAT_LAMBERTIAN) return;

    // Reconstruct hit record from SoA
    GHitRecord rec;
    rec.point.x = hit_point[idx].x;
    rec.point.y = hit_point[idx].y;
    rec.point.z = hit_point[idx].z;
    rec.normal.x = hit_normal[idx].x;
    rec.normal.y = hit_normal[idx].y;
    rec.normal.z = hit_normal[idx].z;
    rec.tangent.x = hit_tangent[idx].x;
    rec.tangent.y = hit_tangent[idx].y;
    rec.tangent.z = hit_tangent[idx].z;
    rec.bitangent.x = hit_bitangent[idx].x;
    rec.bitangent.y = hit_bitangent[idx].y;
    rec.bitangent.z = hit_bitangent[idx].z;
    rec.materialId = hit_mat[idx];
    rec.frontFace = (hit_flags[idx] & 0x1) != 0;
    rec.isDelta = (hit_flags[idx] & 0x2) != 0;

    // Reconstruct wo (negative of ray direction)
    GVec3 wo;
    wo.x = -ray_direction_in[idx].x;
    wo.y = -ray_direction_in[idx].y;
    wo.z = -ray_direction_in[idx].z;
    wo = wo.normalized();

    // Reconstruct spectral state
    GSampledWavelengths lambdas;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
        lambdas.lambda[i] = reinterpret_cast<const float*>(&lambda_in[idx])[i];
        lambdas.pdf[i] = reinterpret_cast<const float*>(&lambda_pdf_in[idx])[i];
    }

    GVec3 throughput(throughput_in[idx].x, throughput_in[idx].y, throughput_in[idx].z);
    GSampledSpectrum throughputSpectral;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
        throughputSpectral[i] = reinterpret_cast<const float*>(&throughput_sp_in[idx])[i];
    }

    // Sample BSDF for next bounce (exact math from path_trace_kernel.cu:317)
    curandState localRng = rng_state[idx];
    GBSDFSample bs = gpu_material_sample_spectral(mat, rec, wo, lambdas, &localRng);
    rng_state[idx] = localRng;

    if (bs.pdf <= 0.f) {
        // Terminate this path
        depth_out[idx] = maxDepth + 1;  // sentinel
        return;
    }

    // Update throughput (megakernel line 321-322)
    throughput *= bs.f / (bs.pdf + 0.001f);
    throughputSpectral *= bs.fSpectral * (1.f / (bs.pdf + 0.001f));

    // Firefly suppression (megakernel line 325-328)
    float maxC = throughput.maxComponent();
    if (maxC > 10.f) throughput *= 10.f / maxC;
    float maxS = throughputSpectral.maxValue();
    if (maxS > 10.f) throughputSpectral *= 10.f / maxS;

    // Write next bounce ray
    ray_origin_out[idx] = make_float4(rec.point.x, rec.point.y, rec.point.z, 0.f);
    ray_direction_out[idx] = make_float4(bs.wi.x, bs.wi.y, bs.wi.z, 0.f);
    throughput_out[idx] = make_float4(throughput.x, throughput.y, throughput.z, 0.f);

    float4 tspec;
    reinterpret_cast<float*>(&tspec)[0] = throughputSpectral[0];
    reinterpret_cast<float*>(&tspec)[1] = throughputSpectral[1];
    reinterpret_cast<float*>(&tspec)[2] = throughputSpectral[2];
    reinterpret_cast<float*>(&tspec)[3] = throughputSpectral[3];
    throughput_sp_out[idx] = tspec;

    pdf_out[idx] = bs.pdf;
    was_specular_out[idx] = bs.isDelta ? 1 : 0;
    depth_out[idx] = depth[idx] + 1;

    // NEE: Lambertian is non-delta, so emit shadow ray
    // Simplified NEE (full MIS in Phase C): sample one light source
    bool hasLights = (numLights > 0 && totalLightPower > 0.f);
    if (hasLights && !rec.isDelta) {
        // Power-weighted light selection
        float u = curand_uniform(&localRng) * totalLightPower;
        int li = 0;
        for (int i = 0; i < numLights; ++i) {
            if (u <= lights[i].cumulativePower) { li = i; break; }
            li = i;
        }
        float selPdf = lights[li].power / totalLightPower;
        int primIdx = lights[li].primitiveIndex;
        if (primIdx >= 0) {
            const GPrimitive& lp = prims[primIdx];
            GVec3 wi_light;
            float dist = 0.f;
            float lightPdf = 0.f;
            int lightMatId = -1;

            if (lp.type == GPRIM_SPHERE) {
                const GSphere& s = spheres[lp.index];
                GVec3 dir = (s.center - rec.point).normalized();
                float distSq = (s.center - rec.point).length2();
                float cosTM = sqrtf(fmaxf(0.f, 1.f - s.radius*s.radius / distSq));
                float z = 1.f + curand_uniform(&localRng) * (cosTM - 1.f);
                float phi = 2.f * M_PI_F * curand_uniform(&localRng);
                GVec3 tu, tv;
                gpu_buildONB(dir, tu, tv);
                float sinTh = sqrtf(fmaxf(0.f, 1.f - z*z));
                wi_light = (tu*cosf(phi)*sinTh + tv*sinf(phi)*sinTh + dir*z).normalized();
                lightPdf = (cosTM < 1.f) ? 1.f / (2.f*M_PI_F*(1.f - cosTM)) : 0.f;
                lightPdf *= selPdf;
                dist = 1e30f;
                lightMatId = s.materialId;
            } else {
                const GTriangle& t = tris[lp.index];
                float r1 = curand_uniform(&localRng), r2 = curand_uniform(&localRng);
                if (r1 + r2 > 1.f) { r1 = 1.f-r1; r2 = 1.f-r2; }
                GVec3 lightPos = t.v0 + (t.v1 - t.v0)*r1 + (t.v2 - t.v0)*r2;
                wi_light = (lightPos - rec.point).normalized();
                dist = (lightPos - rec.point).length();

                // Area PDF to solid angle PDF
                GVec3 e1 = t.v1 - t.v0, e2 = t.v2 - t.v0;
                float area = e1.cross(e2).length() * 0.5f;
                float NdotWi = fabsf(t.n0.dot(wi_light));
                lightPdf = (dist*dist) / (NdotWi * area + 0.001f);
                lightPdf *= selPdf;
                lightMatId = t.materialId;
            }

            shadow_origin[idx] = make_float4(rec.point.x, rec.point.y, rec.point.z, 0.f);
            shadow_dir[idx] = make_float4(wi_light.x, wi_light.y, wi_light.z, 0.f);
            shadow_tmax[idx] = dist;

            // Compute NEE contribution: f * Le / pdf (shadow stage multiplies by visibility)
            GVec3 wo_out(-ray_direction_in[idx].x, -ray_direction_in[idx].y, -ray_direction_in[idx].z);
            wo_out = wo_out.normalized();
            GVec3 f = gpu_material_eval(mat, rec, wo_out, wi_light);
            const GMaterial& lightMat = materials[lightMatId];
            GVec3 Le = gpu_material_emitted(lightMat, true);
            GVec3 contrib = f * Le / (lightPdf + 0.001f);

            nee_contrib[idx] = make_float4(contrib.x, contrib.y, contrib.z, 0.f);
            nee_active[idx] = 1;
        }
    }
}

}  // namespace

void launchShadeLambertian(
    IntegratorStateSoA& state,
    const GMaterial* d_mats,
    const GLight* d_lights, int numLights, float totalLightPower,
    const GPrimitive* d_prims, const GTriangle* d_tris, const GSphere* d_spheres,
    const GEnvMap& envMap, GVec3 bgColor, bool hasBg,
    const GBVHNode* d_bvhNodes, int maxDepth)
{
    int n = state.num_active;
    if (n <= 0) return;

    int threads = 256;
    int blocks = (n + threads - 1) / threads;

    shadeLambertianKernel<<<blocks, threads>>>(
        reinterpret_cast<const float4*>(state.hit_point),
        reinterpret_cast<const float4*>(state.hit_normal),
        reinterpret_cast<const float4*>(state.hit_tangent),
        reinterpret_cast<const float4*>(state.hit_bitangent),
        state.hit_mat,
        state.hit_flags,
        state.pixel_index,
        state.depth,
        reinterpret_cast<const float4*>(state.ray_direction),
        reinterpret_cast<const float4*>(state.lambda),
        reinterpret_cast<const float4*>(state.lambda_pdf),
        reinterpret_cast<const float4*>(state.throughput),
        reinterpret_cast<const float4*>(state.throughput_sp),
        state.path_alive,
        reinterpret_cast<float4*>(state.ray_origin),
        reinterpret_cast<float4*>(state.ray_direction),
        reinterpret_cast<float4*>(state.throughput),
        reinterpret_cast<float4*>(state.throughput_sp),
        state.pdf,
        state.was_specular,
        state.depth,
        reinterpret_cast<float4*>(state.shadow_origin),
        reinterpret_cast<float4*>(state.shadow_dir),
        state.shadow_tmax,
        reinterpret_cast<float4*>(state.nee_contrib),
        state.nee_active,
        reinterpret_cast<curandState*>(state.rng_state),
        d_mats,
        d_lights, numLights, totalLightPower,
        d_prims, d_tris, d_spheres,
        envMap, bgColor, hasBg,
        state.num_active, maxDepth);

    cudaError_t err = cudaGetLastError();
    if (err != cudaSuccess) {
        std::fprintf(stderr, "shade_lambertian launch error: %s\n",
                     cudaGetErrorString(err));
    }
    cudaDeviceSynchronize();
}

}  // namespace astroray::wavefront
