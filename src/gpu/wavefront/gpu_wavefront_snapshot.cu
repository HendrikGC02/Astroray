// gpu_wavefront_snapshot.cu — pkg55-B' Session N+3
//
// GPU wavefront PostInit snapshot download for CPU↔GPU diff harness.
//
// Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §4.2 Session N+3.
// Design: PR #296 §4.1, §4.2 (two-tier gate: CPU↔GPU bounded, not exact).

#include "gpu_wavefront_snapshot.h"
#include "astroray/gpu_wavefront_state.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_scene_upload.h"
#include "raytracer.h"
#include "astroray/spectrum.h"  // Session N+6: SampledSpectrum/XYZ host accumulation
#include <cuda_runtime.h>
#include <cstring>
#include <algorithm>
#include <array>
#include <stdexcept>
#include <cstdio>

// pkg55-B' Session N+6: constant-memory table uploads defined in
// multiwavelength_kernel.cu. Every spectral upsample (ILLUMINANT/ALBEDO)
// routes through the Jakob-Hanika LUT + D65 SPD, and the XYZ conversion
// through the CMF tables — without these uploads the device tables are
// zero and every spectrum evaluates to 0 (black frame).
void uploadCmfTables();
void uploadJakobHanikaLut();

namespace astroray::wavefront {

std::vector<float> cuda_wavefront_snapshot_post_init(
    const Camera& cam,
    int width, int height,
    uint64_t seed)
{
    int total_paths = width * height;
    if (total_paths <= 0) {
        throw std::runtime_error("cuda_wavefront_snapshot_post_init: invalid dimensions");
    }

    // Build GCameraParams from Camera (mirrors production GPU render path).
    // Camera CPU→GPU conversion (mirrors gpu_renderer.cu::upload_camera_params).
    GCameraParams gcam;
    gcam.origin = GVec3(cam.getOrigin().x, cam.getOrigin().y, cam.getOrigin().z);
    gcam.lowerLeft = GVec3(cam.getLowerLeft().x, cam.getLowerLeft().y, cam.getLowerLeft().z);
    gcam.horizontal = GVec3(cam.getHorizontal().x, cam.getHorizontal().y, cam.getHorizontal().z);
    gcam.vertical = GVec3(cam.getVertical().x, cam.getVertical().y, cam.getVertical().z);
    gcam.lensRadius = cam.getLensRadius();
    gcam.width = width;
    gcam.height = height;

    // Camera basis vectors u/v for DOF (right/up in camera space).
    // These are already computed in the Camera object.
    Vec3 u_vec = cam.getU();
    Vec3 v_vec = cam.getV();
    gcam.u = GVec3(u_vec.x, u_vec.y, u_vec.z);
    gcam.v = GVec3(v_vec.x, v_vec.y, v_vec.z);
    gcam.focusDist = cam.getFocusDist();

    // Allocate GPU SoA state.
    GPUWavefrontState state;
    if (!allocateGPUWavefrontState(state, total_paths)) {
        throw std::runtime_error("cuda_wavefront_snapshot_post_init: GPU allocation failed");
    }

    // Launch stage_init kernel.
    try {
        launchStageInit(state, gcam, width, height, seed);
    } catch (...) {
        freeGPUWavefrontState(state);
        throw;
    }

    // Download PostInit snapshot fields.
    // Row format (22 elements per path):
    //   [0..2]:   ray_origin (x,y,z)
    //   [3..5]:   ray_direction (x,y,z)
    //   [6..9]:   lambdas (4 floats)
    //   [10..13]: throughput (4 floats)
    //   [14..15]: pixel_index, sample_index
    //   [16]:     bounce
    //   [17..20]: rng (pixel, sample, dimension, seed_lo, seed_hi) — 5 elements
    //
    // Total: 22 elements per path.
    std::vector<float> snapshot(total_paths * 22);

    // Allocate host-pinned staging buffers for batch download.
    std::vector<float> h_ray_origin_x(total_paths);
    std::vector<float> h_ray_origin_y(total_paths);
    std::vector<float> h_ray_origin_z(total_paths);
    std::vector<float> h_ray_direction_x(total_paths);
    std::vector<float> h_ray_direction_y(total_paths);
    std::vector<float> h_ray_direction_z(total_paths);
    std::vector<float> h_lambda_0(total_paths);
    std::vector<float> h_lambda_1(total_paths);
    std::vector<float> h_lambda_2(total_paths);
    std::vector<float> h_lambda_3(total_paths);
    std::vector<float> h_throughput_0(total_paths);
    std::vector<float> h_throughput_1(total_paths);
    std::vector<float> h_throughput_2(total_paths);
    std::vector<float> h_throughput_3(total_paths);
    std::vector<int> h_pixel_index(total_paths);
    std::vector<int> h_sample_index(total_paths);
    std::vector<int> h_bounce(total_paths);
    std::vector<uint32_t> h_rng_pixel(total_paths);
    std::vector<uint32_t> h_rng_sample(total_paths);
    std::vector<uint32_t> h_rng_dimension(total_paths);
    std::vector<uint64_t> h_rng_seed(total_paths);

    // Download all fields.
    cudaError_t err;
    #define DOWNLOAD(dst, src, count) \
        err = cudaMemcpy((dst).data(), (src), (count) * sizeof((dst)[0]), cudaMemcpyDeviceToHost); \
        if (err != cudaSuccess) { \
            freeGPUWavefrontState(state); \
            throw std::runtime_error(std::string("cudaMemcpy failed: ") + cudaGetErrorString(err)); \
        }

    DOWNLOAD(h_ray_origin_x, state.ray_origin_x, total_paths);
    DOWNLOAD(h_ray_origin_y, state.ray_origin_y, total_paths);
    DOWNLOAD(h_ray_origin_z, state.ray_origin_z, total_paths);
    DOWNLOAD(h_ray_direction_x, state.ray_direction_x, total_paths);
    DOWNLOAD(h_ray_direction_y, state.ray_direction_y, total_paths);
    DOWNLOAD(h_ray_direction_z, state.ray_direction_z, total_paths);
    DOWNLOAD(h_lambda_0, state.lambda_0, total_paths);
    DOWNLOAD(h_lambda_1, state.lambda_1, total_paths);
    DOWNLOAD(h_lambda_2, state.lambda_2, total_paths);
    DOWNLOAD(h_lambda_3, state.lambda_3, total_paths);
    DOWNLOAD(h_throughput_0, state.throughput_0, total_paths);
    DOWNLOAD(h_throughput_1, state.throughput_1, total_paths);
    DOWNLOAD(h_throughput_2, state.throughput_2, total_paths);
    DOWNLOAD(h_throughput_3, state.throughput_3, total_paths);
    DOWNLOAD(h_pixel_index, state.pixel_index, total_paths);
    DOWNLOAD(h_sample_index, state.sample_index, total_paths);
    DOWNLOAD(h_bounce, state.bounce, total_paths);
    DOWNLOAD(h_rng_pixel, state.rng_pixel, total_paths);
    DOWNLOAD(h_rng_sample, state.rng_sample, total_paths);
    DOWNLOAD(h_rng_dimension, state.rng_dimension, total_paths);
    DOWNLOAD(h_rng_seed, state.rng_seed, total_paths);

    #undef DOWNLOAD

    // Free GPU buffers.
    freeGPUWavefrontState(state);

    // Pack into flat snapshot array (22 elements per path).
    for (int i = 0; i < total_paths; ++i) {
        int base = i * 22;
        snapshot[base + 0]  = h_ray_origin_x[i];
        snapshot[base + 1]  = h_ray_origin_y[i];
        snapshot[base + 2]  = h_ray_origin_z[i];
        snapshot[base + 3]  = h_ray_direction_x[i];
        snapshot[base + 4]  = h_ray_direction_y[i];
        snapshot[base + 5]  = h_ray_direction_z[i];
        snapshot[base + 6]  = h_lambda_0[i];
        snapshot[base + 7]  = h_lambda_1[i];
        snapshot[base + 8]  = h_lambda_2[i];
        snapshot[base + 9]  = h_lambda_3[i];
        snapshot[base + 10] = h_throughput_0[i];
        snapshot[base + 11] = h_throughput_1[i];
        snapshot[base + 12] = h_throughput_2[i];
        snapshot[base + 13] = h_throughput_3[i];
        snapshot[base + 14] = static_cast<float>(h_pixel_index[i]);
        snapshot[base + 15] = static_cast<float>(h_sample_index[i]);
        snapshot[base + 16] = static_cast<float>(h_bounce[i]);
        snapshot[base + 17] = static_cast<float>(h_rng_pixel[i]);
        snapshot[base + 18] = static_cast<float>(h_rng_sample[i]);
        snapshot[base + 19] = static_cast<float>(h_rng_dimension[i]);
        // Pack uint64_t seed as two floats (low 32, high 32).
        snapshot[base + 20] = static_cast<float>(h_rng_seed[i] & 0xFFFFFFFF);
        snapshot[base + 21] = static_cast<float>(h_rng_seed[i] >> 32);
    }

    return snapshot;
}

// Helper: upload host vector → device array (local to this TU).
template<typename T>
static void devUpload(const std::vector<T>& src, T** d_ptr) {
    if (*d_ptr) {
        cudaFree(*d_ptr);
        *d_ptr = nullptr;
        cudaGetLastError();  // clear latent error
    }
    if (src.empty()) return;
    cudaError_t err = cudaMalloc(reinterpret_cast<void**>(d_ptr), src.size() * sizeof(T));
    if (err != cudaSuccess) {
        throw std::runtime_error(std::string("cudaMalloc failed: ") + cudaGetErrorString(err));
    }
    err = cudaMemcpy(*d_ptr, src.data(), src.size() * sizeof(T), cudaMemcpyHostToDevice);
    if (err != cudaSuccess) {
        cudaFree(*d_ptr);
        *d_ptr = nullptr;
        throw std::runtime_error(std::string("cudaMemcpy failed: ") + cudaGetErrorString(err));
    }
}

std::vector<float> cuda_wavefront_snapshot_post_intersect(
    Renderer& renderer,
    const Camera& cam,
    int width, int height,
    uint64_t seed)
{
    int total_paths = width * height;
    if (total_paths <= 0) {
        throw std::runtime_error("cuda_wavefront_snapshot_post_intersect: invalid dimensions");
    }

    // Build GCameraParams from Camera.
    GCameraParams gcam;
    gcam.origin = GVec3(cam.getOrigin().x, cam.getOrigin().y, cam.getOrigin().z);
    gcam.lowerLeft = GVec3(cam.getLowerLeft().x, cam.getLowerLeft().y, cam.getLowerLeft().z);
    gcam.horizontal = GVec3(cam.getHorizontal().x, cam.getHorizontal().y, cam.getHorizontal().z);
    gcam.vertical = GVec3(cam.getVertical().x, cam.getVertical().y, cam.getVertical().z);
    gcam.lensRadius = cam.getLensRadius();
    gcam.width = width;
    gcam.height = height;
    Vec3 u_vec = cam.getU();
    Vec3 v_vec = cam.getV();
    gcam.u = GVec3(u_vec.x, u_vec.y, u_vec.z);
    gcam.v = GVec3(v_vec.x, v_vec.y, v_vec.z);
    gcam.focusDist = cam.getFocusDist();

    // Upload scene data to GPU (temporary for this snapshot).
    GBVHNode* d_bvhNodes = nullptr;
    GPrimitive* d_prims = nullptr;
    GTriangle* d_tris = nullptr;
    GSphere* d_spheres = nullptr;

    try {
        SceneUploadResult bvhRes = buildSceneArrays(renderer, &cam);
        devUpload(bvhRes.nodes, &d_bvhNodes);
        devUpload(bvhRes.prims, &d_prims);
        devUpload(bvhRes.triangles, &d_tris);
        devUpload(bvhRes.spheres, &d_spheres);

        // Allocate GPU SoA state + hit buffers.
        GPUWavefrontState state;
        GPUWavefrontHitBuffers hitBufs;
        if (!allocateGPUWavefrontState(state, total_paths)) {
            throw std::runtime_error("cuda_wavefront_snapshot_post_intersect: GPU state allocation failed");
        }
        if (!allocateGPUWavefrontHitBuffers(hitBufs, total_paths)) {
            freeGPUWavefrontState(state);
            throw std::runtime_error("cuda_wavefront_snapshot_post_intersect: GPU hit buffer allocation failed");
        }

        // Launch stage_init + stage_intersect.
        launchStageInit(state, gcam, width, height, seed);
        launchStageIntersect_SessionN3(state, hitBufs, d_bvhNodes, d_prims, d_tris, d_spheres);

        // Download PostIntersect snapshot fields.
        // Row format (23 elements per path):
        //   [0..2]:   ray_origin (x,y,z)
        //   [3..5]:   ray_direction (x,y,z)
        //   [6..9]:   lambdas (4 floats)
        //   [10..13]: throughput (4 floats)
        //   [14]:     hit_valid (0 or 1)
        //   [15]:     hit_t
        //   [16..18]: hit_point (x,y,z)
        //   [19..21]: hit_normal (x,y,z)
        //   [22]:     hit_material_id
        std::vector<float> snapshot(total_paths * 23);

        // Allocate host-pinned staging buffers for batch download.
        std::vector<float> h_ray_origin_x(total_paths);
        std::vector<float> h_ray_origin_y(total_paths);
        std::vector<float> h_ray_origin_z(total_paths);
        std::vector<float> h_ray_direction_x(total_paths);
        std::vector<float> h_ray_direction_y(total_paths);
        std::vector<float> h_ray_direction_z(total_paths);
        std::vector<float> h_lambda_0(total_paths);
        std::vector<float> h_lambda_1(total_paths);
        std::vector<float> h_lambda_2(total_paths);
        std::vector<float> h_lambda_3(total_paths);
        std::vector<float> h_throughput_0(total_paths);
        std::vector<float> h_throughput_1(total_paths);
        std::vector<float> h_throughput_2(total_paths);
        std::vector<float> h_throughput_3(total_paths);
        std::vector<int> h_hit_valid(total_paths);
        std::vector<float> h_hit_t(total_paths);
        std::vector<float> h_hit_point_x(total_paths);
        std::vector<float> h_hit_point_y(total_paths);
        std::vector<float> h_hit_point_z(total_paths);
        std::vector<float> h_hit_normal_x(total_paths);
        std::vector<float> h_hit_normal_y(total_paths);
        std::vector<float> h_hit_normal_z(total_paths);
        std::vector<int> h_hit_material_id(total_paths);

        // Download all fields.
        cudaError_t err;
        #define DOWNLOAD(dst, src, count) \
            err = cudaMemcpy((dst).data(), (src), (count) * sizeof((dst)[0]), cudaMemcpyDeviceToHost); \
            if (err != cudaSuccess) { \
                freeGPUWavefrontHitBuffers(hitBufs); \
                freeGPUWavefrontState(state); \
                throw std::runtime_error(std::string("cudaMemcpy failed: ") + cudaGetErrorString(err)); \
            }

        DOWNLOAD(h_ray_origin_x, state.ray_origin_x, total_paths);
        DOWNLOAD(h_ray_origin_y, state.ray_origin_y, total_paths);
        DOWNLOAD(h_ray_origin_z, state.ray_origin_z, total_paths);
        DOWNLOAD(h_ray_direction_x, state.ray_direction_x, total_paths);
        DOWNLOAD(h_ray_direction_y, state.ray_direction_y, total_paths);
        DOWNLOAD(h_ray_direction_z, state.ray_direction_z, total_paths);
        DOWNLOAD(h_lambda_0, state.lambda_0, total_paths);
        DOWNLOAD(h_lambda_1, state.lambda_1, total_paths);
        DOWNLOAD(h_lambda_2, state.lambda_2, total_paths);
        DOWNLOAD(h_lambda_3, state.lambda_3, total_paths);
        DOWNLOAD(h_throughput_0, state.throughput_0, total_paths);
        DOWNLOAD(h_throughput_1, state.throughput_1, total_paths);
        DOWNLOAD(h_throughput_2, state.throughput_2, total_paths);
        DOWNLOAD(h_throughput_3, state.throughput_3, total_paths);
        DOWNLOAD(h_hit_valid, hitBufs.hit_valid, total_paths);
        DOWNLOAD(h_hit_t, hitBufs.hit_t, total_paths);
        DOWNLOAD(h_hit_point_x, hitBufs.hit_point_x, total_paths);
        DOWNLOAD(h_hit_point_y, hitBufs.hit_point_y, total_paths);
        DOWNLOAD(h_hit_point_z, hitBufs.hit_point_z, total_paths);
        DOWNLOAD(h_hit_normal_x, hitBufs.hit_normal_x, total_paths);
        DOWNLOAD(h_hit_normal_y, hitBufs.hit_normal_y, total_paths);
        DOWNLOAD(h_hit_normal_z, hitBufs.hit_normal_z, total_paths);
        DOWNLOAD(h_hit_material_id, hitBufs.hit_material_id, total_paths);

        #undef DOWNLOAD

        // Free GPU buffers.
        freeGPUWavefrontHitBuffers(hitBufs);
        freeGPUWavefrontState(state);

        // Pack into flat snapshot array (23 elements per path).
        for (int i = 0; i < total_paths; ++i) {
            int base = i * 23;
            snapshot[base + 0]  = h_ray_origin_x[i];
            snapshot[base + 1]  = h_ray_origin_y[i];
            snapshot[base + 2]  = h_ray_origin_z[i];
            snapshot[base + 3]  = h_ray_direction_x[i];
            snapshot[base + 4]  = h_ray_direction_y[i];
            snapshot[base + 5]  = h_ray_direction_z[i];
            snapshot[base + 6]  = h_lambda_0[i];
            snapshot[base + 7]  = h_lambda_1[i];
            snapshot[base + 8]  = h_lambda_2[i];
            snapshot[base + 9]  = h_lambda_3[i];
            snapshot[base + 10] = h_throughput_0[i];
            snapshot[base + 11] = h_throughput_1[i];
            snapshot[base + 12] = h_throughput_2[i];
            snapshot[base + 13] = h_throughput_3[i];
            snapshot[base + 14] = static_cast<float>(h_hit_valid[i]);
            snapshot[base + 15] = h_hit_t[i];
            snapshot[base + 16] = h_hit_point_x[i];
            snapshot[base + 17] = h_hit_point_y[i];
            snapshot[base + 18] = h_hit_point_z[i];
            snapshot[base + 19] = h_hit_normal_x[i];
            snapshot[base + 20] = h_hit_normal_y[i];
            snapshot[base + 21] = h_hit_normal_z[i];
            snapshot[base + 22] = static_cast<float>(h_hit_material_id[i]);
        }

        // Clean up temporary scene data.
        if (d_bvhNodes) cudaFree(d_bvhNodes);
        if (d_prims) cudaFree(d_prims);
        if (d_tris) cudaFree(d_tris);
        if (d_spheres) cudaFree(d_spheres);

        return snapshot;
    } catch (...) {
        // Clean up on exception.
        if (d_bvhNodes) cudaFree(d_bvhNodes);
        if (d_prims) cudaFree(d_prims);
        if (d_tris) cudaFree(d_tris);
        if (d_spheres) cudaFree(d_spheres);
        throw;
    }
}

std::vector<float> cuda_wavefront_snapshot_post_shade(
    Renderer& renderer,
    const Camera& cam,
    int width, int height,
    uint64_t seed)
{
    int total_paths = width * height;
    if (total_paths <= 0) {
        throw std::runtime_error("cuda_wavefront_snapshot_post_shade: invalid dimensions");
    }

    // Build GCameraParams from Camera.
    GCameraParams gcam;
    gcam.origin = GVec3(cam.getOrigin().x, cam.getOrigin().y, cam.getOrigin().z);
    gcam.lowerLeft = GVec3(cam.getLowerLeft().x, cam.getLowerLeft().y, cam.getLowerLeft().z);
    gcam.horizontal = GVec3(cam.getHorizontal().x, cam.getHorizontal().y, cam.getHorizontal().z);
    gcam.vertical = GVec3(cam.getVertical().x, cam.getVertical().y, cam.getVertical().z);
    gcam.lensRadius = cam.getLensRadius();
    gcam.width = width;
    gcam.height = height;
    Vec3 u_vec = cam.getU();
    Vec3 v_vec = cam.getV();
    gcam.u = GVec3(u_vec.x, u_vec.y, u_vec.z);
    gcam.v = GVec3(v_vec.x, v_vec.y, v_vec.z);
    gcam.focusDist = cam.getFocusDist();

    // Upload scene data to GPU (temporary for this snapshot).
    GBVHNode* d_bvhNodes = nullptr;
    GPrimitive* d_prims = nullptr;
    GTriangle* d_tris = nullptr;
    GSphere* d_spheres = nullptr;
    ::GMaterial* d_materials = nullptr;

    try {
        SceneUploadResult bvhRes = buildSceneArrays(renderer, &cam);
        devUpload(bvhRes.nodes, &d_bvhNodes);
        devUpload(bvhRes.prims, &d_prims);
        devUpload(bvhRes.triangles, &d_tris);
        devUpload(bvhRes.spheres, &d_spheres);
        devUpload(bvhRes.materials, &d_materials);

        // Allocate GPU SoA state + hit buffers.
        GPUWavefrontState state;
        GPUWavefrontHitBuffers hitBufs;
        if (!allocateGPUWavefrontState(state, total_paths)) {
            throw std::runtime_error("cuda_wavefront_snapshot_post_shade: GPU state allocation failed");
        }
        if (!allocateGPUWavefrontHitBuffers(hitBufs, total_paths)) {
            freeGPUWavefrontState(state);
            throw std::runtime_error("cuda_wavefront_snapshot_post_shade: GPU hit buffer allocation failed");
        }

        // Launch stage_init + stage_intersect + stage_shade_lambertian.
        launchStageInit(state, gcam, width, height, seed);
        launchStageIntersect_SessionN3(state, hitBufs, d_bvhNodes, d_prims, d_tris, d_spheres);
        launchStageShadeLambertian_SessionN3(state, hitBufs, d_materials, bvhRes.materials.size());

        // Download PostShade snapshot fields.
        // Row format (16 elements per path):
        //   [0..2]:   ray_origin (next bounce origin)
        //   [3..5]:   ray_direction (next bounce direction)
        //   [6..9]:   throughput (4 floats, updated by BSDF)
        //   [10..13]: lambdas (4 floats)
        //   [14]:     bsdf_pdf (TODO: need to store this in kernel)
        //   [15]:     bsdf_is_delta (TODO: need to store this in kernel)
        std::vector<float> snapshot(total_paths * 16);

        // Allocate host-pinned staging buffers for batch download.
        std::vector<float> h_ray_origin_x(total_paths);
        std::vector<float> h_ray_origin_y(total_paths);
        std::vector<float> h_ray_origin_z(total_paths);
        std::vector<float> h_ray_direction_x(total_paths);
        std::vector<float> h_ray_direction_y(total_paths);
        std::vector<float> h_ray_direction_z(total_paths);
        std::vector<float> h_throughput_0(total_paths);
        std::vector<float> h_throughput_1(total_paths);
        std::vector<float> h_throughput_2(total_paths);
        std::vector<float> h_throughput_3(total_paths);
        std::vector<float> h_lambda_0(total_paths);
        std::vector<float> h_lambda_1(total_paths);
        std::vector<float> h_lambda_2(total_paths);
        std::vector<float> h_lambda_3(total_paths);

        // Download all fields.
        cudaError_t err;
        #define DOWNLOAD(dst, src, count) \
            err = cudaMemcpy((dst).data(), (src), (count) * sizeof((dst)[0]), cudaMemcpyDeviceToHost); \
            if (err != cudaSuccess) { \
                freeGPUWavefrontHitBuffers(hitBufs); \
                freeGPUWavefrontState(state); \
                throw std::runtime_error(std::string("cudaMemcpy failed: ") + cudaGetErrorString(err)); \
            }

        DOWNLOAD(h_ray_origin_x, state.ray_origin_x, total_paths);
        DOWNLOAD(h_ray_origin_y, state.ray_origin_y, total_paths);
        DOWNLOAD(h_ray_origin_z, state.ray_origin_z, total_paths);
        DOWNLOAD(h_ray_direction_x, state.ray_direction_x, total_paths);
        DOWNLOAD(h_ray_direction_y, state.ray_direction_y, total_paths);
        DOWNLOAD(h_ray_direction_z, state.ray_direction_z, total_paths);
        DOWNLOAD(h_throughput_0, state.throughput_0, total_paths);
        DOWNLOAD(h_throughput_1, state.throughput_1, total_paths);
        DOWNLOAD(h_throughput_2, state.throughput_2, total_paths);
        DOWNLOAD(h_throughput_3, state.throughput_3, total_paths);
        DOWNLOAD(h_lambda_0, state.lambda_0, total_paths);
        DOWNLOAD(h_lambda_1, state.lambda_1, total_paths);
        DOWNLOAD(h_lambda_2, state.lambda_2, total_paths);
        DOWNLOAD(h_lambda_3, state.lambda_3, total_paths);

        #undef DOWNLOAD

        // Free GPU buffers.
        freeGPUWavefrontHitBuffers(hitBufs);
        freeGPUWavefrontState(state);

        // Pack into flat snapshot array (16 elements per path).
        // For Session N+3 part 2: bsdf_pdf and bsdf_is_delta are TODO placeholders (0.0).
        for (int i = 0; i < total_paths; ++i) {
            int base = i * 16;
            snapshot[base + 0]  = h_ray_origin_x[i];
            snapshot[base + 1]  = h_ray_origin_y[i];
            snapshot[base + 2]  = h_ray_origin_z[i];
            snapshot[base + 3]  = h_ray_direction_x[i];
            snapshot[base + 4]  = h_ray_direction_y[i];
            snapshot[base + 5]  = h_ray_direction_z[i];
            snapshot[base + 6]  = h_throughput_0[i];
            snapshot[base + 7]  = h_throughput_1[i];
            snapshot[base + 8]  = h_throughput_2[i];
            snapshot[base + 9]  = h_throughput_3[i];
            snapshot[base + 10] = h_lambda_0[i];
            snapshot[base + 11] = h_lambda_1[i];
            snapshot[base + 12] = h_lambda_2[i];
            snapshot[base + 13] = h_lambda_3[i];
            snapshot[base + 14] = 0.0f;  // bsdf_pdf TODO: store in kernel
            snapshot[base + 15] = 0.0f;  // bsdf_is_delta TODO: store in kernel
        }

        // Clean up temporary scene data.
        if (d_bvhNodes) cudaFree(d_bvhNodes);
        if (d_prims) cudaFree(d_prims);
        if (d_tris) cudaFree(d_tris);
        if (d_spheres) cudaFree(d_spheres);
        if (d_materials) cudaFree(d_materials);

        return snapshot;
    } catch (...) {
        // Clean up on exception.
        if (d_bvhNodes) cudaFree(d_bvhNodes);
        if (d_prims) cudaFree(d_prims);
        if (d_tris) cudaFree(d_tris);
        if (d_spheres) cudaFree(d_spheres);
        if (d_materials) cudaFree(d_materials);
        throw;
    }
}

std::vector<float> cuda_wavefront_snapshot_post_light_sample(
    Renderer& renderer,
    const Camera& cam,
    int width, int height,
    uint64_t seed)
{
    int total_paths = width * height;
    if (total_paths <= 0) {
        throw std::runtime_error("cuda_wavefront_snapshot_post_light_sample: invalid dimensions");
    }

    // Build GCameraParams from Camera.
    GCameraParams gcam;
    gcam.origin = GVec3(cam.getOrigin().x, cam.getOrigin().y, cam.getOrigin().z);
    gcam.lowerLeft = GVec3(cam.getLowerLeft().x, cam.getLowerLeft().y, cam.getLowerLeft().z);
    gcam.horizontal = GVec3(cam.getHorizontal().x, cam.getHorizontal().y, cam.getHorizontal().z);
    gcam.vertical = GVec3(cam.getVertical().x, cam.getVertical().y, cam.getVertical().z);
    gcam.lensRadius = cam.getLensRadius();
    gcam.width = width;
    gcam.height = height;
    Vec3 u_vec = cam.getU();
    Vec3 v_vec = cam.getV();
    gcam.u = GVec3(u_vec.x, u_vec.y, u_vec.z);
    gcam.v = GVec3(v_vec.x, v_vec.y, v_vec.z);
    gcam.focusDist = cam.getFocusDist();

    // Upload scene data to GPU (temporary for this snapshot).
    GBVHNode* d_bvhNodes = nullptr;
    GPrimitive* d_prims = nullptr;
    GTriangle* d_tris = nullptr;
    GSphere* d_spheres = nullptr;
    ::GMaterial* d_materials = nullptr;
    ::GAreaLight* d_lights = nullptr;

    try {
        SceneUploadResult bvhRes = buildSceneArrays(renderer, &cam);
        devUpload(bvhRes.nodes, &d_bvhNodes);
        devUpload(bvhRes.prims, &d_prims);
        devUpload(bvhRes.triangles, &d_tris);
        devUpload(bvhRes.spheres, &d_spheres);
        devUpload(bvhRes.materials, &d_materials);
        devUpload(bvhRes.areaLights, &d_lights);

        // Allocate GPU SoA state + hit buffers.
        GPUWavefrontState state;
        GPUWavefrontHitBuffers hitBufs;
        if (!allocateGPUWavefrontState(state, total_paths)) {
            throw std::runtime_error("cuda_wavefront_snapshot_post_light_sample: GPU state allocation failed");
        }
        if (!allocateGPUWavefrontHitBuffers(hitBufs, total_paths)) {
            freeGPUWavefrontState(state);
            throw std::runtime_error("cuda_wavefront_snapshot_post_light_sample: GPU hit buffer allocation failed");
        }

        // Launch stage_init + stage_intersect + stage_shade_lambertian + stage_light_sample.
        launchStageInit(state, gcam, width, height, seed);
        launchStageIntersect_SessionN3(state, hitBufs, d_bvhNodes, d_prims, d_tris, d_spheres);
        launchStageShadeLambertian_SessionN3(state, hitBufs, d_materials, bvhRes.materials.size());
        launchStageLightSample_SessionN4(state, hitBufs, d_materials, bvhRes.materials.size(),
                                          d_lights, bvhRes.areaLights.size(),
                                          d_bvhNodes, d_prims, d_tris, d_spheres);

        // Download PostLightSample snapshot fields.
        // Row format (21 elements per path):
        //   [0..2]:   ray_origin (x,y,z) — SEMANTIC: pre-bounce shading point
        //   [3..5]:   ray_direction (x,y,z)
        //   [6..9]:   throughput (4 floats)
        //   [10..13]: lambdas (4 floats)
        //   [14..17]: nee_contribution (4 floats) — TODO placeholder
        //   [18]:     nee_light_pdf — TODO placeholder
        //   [19]:     nee_bsdf_pdf_at_dir — TODO placeholder
        //   [20]:     nee_mis_weight — TODO placeholder
        std::vector<float> snapshot(total_paths * 21);

        // Allocate host-pinned staging buffers for batch download.
        std::vector<float> h_ray_origin_x(total_paths);
        std::vector<float> h_ray_origin_y(total_paths);
        std::vector<float> h_ray_origin_z(total_paths);
        std::vector<float> h_ray_direction_x(total_paths);
        std::vector<float> h_ray_direction_y(total_paths);
        std::vector<float> h_ray_direction_z(total_paths);
        std::vector<float> h_throughput_0(total_paths);
        std::vector<float> h_throughput_1(total_paths);
        std::vector<float> h_throughput_2(total_paths);
        std::vector<float> h_throughput_3(total_paths);
        std::vector<float> h_lambda_0(total_paths);
        std::vector<float> h_lambda_1(total_paths);
        std::vector<float> h_lambda_2(total_paths);
        std::vector<float> h_lambda_3(total_paths);

        // Download all fields.
        // NOTE: ray_origin reads from hitBufs.hit_point_* (shading point), NOT
        // state.ray_origin_* (already overwritten by stage_shade to next-bounce
        // origin). This matches CPU path_kernel.cpp which captures ps.ray_origin
        // before the advance (lines 255-257).
        cudaError_t err;
        #define DOWNLOAD(dst, src, count) \
            err = cudaMemcpy((dst).data(), (src), (count) * sizeof((dst)[0]), cudaMemcpyDeviceToHost); \
            if (err != cudaSuccess) { \
                freeGPUWavefrontHitBuffers(hitBufs); \
                freeGPUWavefrontState(state); \
                throw std::runtime_error(std::string("cudaMemcpy failed: ") + cudaGetErrorString(err)); \
            }

        DOWNLOAD(h_ray_origin_x, hitBufs.hit_point_x, total_paths);
        DOWNLOAD(h_ray_origin_y, hitBufs.hit_point_y, total_paths);
        DOWNLOAD(h_ray_origin_z, hitBufs.hit_point_z, total_paths);
        DOWNLOAD(h_ray_direction_x, state.ray_direction_x, total_paths);
        DOWNLOAD(h_ray_direction_y, state.ray_direction_y, total_paths);
        DOWNLOAD(h_ray_direction_z, state.ray_direction_z, total_paths);
        DOWNLOAD(h_throughput_0, state.throughput_0, total_paths);
        DOWNLOAD(h_throughput_1, state.throughput_1, total_paths);
        DOWNLOAD(h_throughput_2, state.throughput_2, total_paths);
        DOWNLOAD(h_throughput_3, state.throughput_3, total_paths);
        DOWNLOAD(h_lambda_0, state.lambda_0, total_paths);
        DOWNLOAD(h_lambda_1, state.lambda_1, total_paths);
        DOWNLOAD(h_lambda_2, state.lambda_2, total_paths);
        DOWNLOAD(h_lambda_3, state.lambda_3, total_paths);

        #undef DOWNLOAD

        // Free GPU buffers.
        freeGPUWavefrontHitBuffers(hitBufs);
        freeGPUWavefrontState(state);

        // Pack into flat snapshot array (21 elements per path).
        // For Session N+4: nee_* fields are TODO placeholders (0.0).
        for (int i = 0; i < total_paths; ++i) {
            int base = i * 21;
            snapshot[base + 0]  = h_ray_origin_x[i];
            snapshot[base + 1]  = h_ray_origin_y[i];
            snapshot[base + 2]  = h_ray_origin_z[i];
            snapshot[base + 3]  = h_ray_direction_x[i];
            snapshot[base + 4]  = h_ray_direction_y[i];
            snapshot[base + 5]  = h_ray_direction_z[i];
            snapshot[base + 6]  = h_throughput_0[i];
            snapshot[base + 7]  = h_throughput_1[i];
            snapshot[base + 8]  = h_throughput_2[i];
            snapshot[base + 9]  = h_throughput_3[i];
            snapshot[base + 10] = h_lambda_0[i];
            snapshot[base + 11] = h_lambda_1[i];
            snapshot[base + 12] = h_lambda_2[i];
            snapshot[base + 13] = h_lambda_3[i];
            snapshot[base + 14] = 0.0f;  // nee_contribution[0] TODO: store in kernel
            snapshot[base + 15] = 0.0f;  // nee_contribution[1] TODO: store in kernel
            snapshot[base + 16] = 0.0f;  // nee_contribution[2] TODO: store in kernel
            snapshot[base + 17] = 0.0f;  // nee_contribution[3] TODO: store in kernel
            snapshot[base + 18] = 0.0f;  // nee_light_pdf TODO: store in kernel
            snapshot[base + 19] = 0.0f;  // nee_bsdf_pdf_at_dir TODO: store in kernel
            snapshot[base + 20] = 0.0f;  // nee_mis_weight TODO: store in kernel
        }

        // Clean up temporary scene data.
        if (d_bvhNodes) cudaFree(d_bvhNodes);
        if (d_prims) cudaFree(d_prims);
        if (d_tris) cudaFree(d_tris);
        if (d_spheres) cudaFree(d_spheres);
        if (d_materials) cudaFree(d_materials);
        if (d_lights) cudaFree(d_lights);

        return snapshot;
    } catch (...) {
        // Clean up on exception.
        if (d_bvhNodes) cudaFree(d_bvhNodes);
        if (d_prims) cudaFree(d_prims);
        if (d_tris) cudaFree(d_tris);
        if (d_spheres) cudaFree(d_spheres);
        if (d_materials) cudaFree(d_materials);
        if (d_lights) cudaFree(d_lights);
        throw;
    }
}

std::vector<float> cuda_wavefront_snapshot_post_rr(
    Renderer& renderer,
    const Camera& cam,
    int width, int height,
    uint64_t seed)
{
    int total_paths = width * height;
    if (total_paths <= 0) {
        throw std::runtime_error("cuda_wavefront_snapshot_post_rr: invalid dimensions");
    }

    // Build GCameraParams from Camera.
    GCameraParams gcam;
    gcam.origin = GVec3(cam.getOrigin().x, cam.getOrigin().y, cam.getOrigin().z);
    gcam.lowerLeft = GVec3(cam.getLowerLeft().x, cam.getLowerLeft().y, cam.getLowerLeft().z);
    gcam.horizontal = GVec3(cam.getHorizontal().x, cam.getHorizontal().y, cam.getHorizontal().z);
    gcam.vertical = GVec3(cam.getVertical().x, cam.getVertical().y, cam.getVertical().z);
    gcam.lensRadius = cam.getLensRadius();
    gcam.width = width;
    gcam.height = height;
    Vec3 u_vec = cam.getU();
    Vec3 v_vec = cam.getV();
    gcam.u = GVec3(u_vec.x, u_vec.y, u_vec.z);
    gcam.v = GVec3(v_vec.x, v_vec.y, v_vec.z);
    gcam.focusDist = cam.getFocusDist();

    // Upload scene data to GPU (temporary for this snapshot).
    GBVHNode* d_bvhNodes = nullptr;
    GPrimitive* d_prims = nullptr;
    GTriangle* d_tris = nullptr;
    GSphere* d_spheres = nullptr;
    ::GMaterial* d_materials = nullptr;
    ::GAreaLight* d_lights = nullptr;

    try {
        SceneUploadResult bvhRes = buildSceneArrays(renderer, &cam);
        devUpload(bvhRes.nodes, &d_bvhNodes);
        devUpload(bvhRes.prims, &d_prims);
        devUpload(bvhRes.triangles, &d_tris);
        devUpload(bvhRes.spheres, &d_spheres);
        devUpload(bvhRes.materials, &d_materials);
        devUpload(bvhRes.areaLights, &d_lights);

        // Allocate GPU SoA state + hit buffers.
        GPUWavefrontState state;
        GPUWavefrontHitBuffers hitBufs;
        if (!allocateGPUWavefrontState(state, total_paths)) {
            throw std::runtime_error("cuda_wavefront_snapshot_post_rr: GPU state allocation failed");
        }
        if (!allocateGPUWavefrontHitBuffers(hitBufs, total_paths)) {
            freeGPUWavefrontState(state);
            throw std::runtime_error("cuda_wavefront_snapshot_post_rr: GPU hit buffer allocation failed");
        }

        // Launch stage_init + stage_intersect + stage_shade_lambertian + stage_light_sample + stage_russian_roulette.
        launchStageInit(state, gcam, width, height, seed);
        launchStageIntersect_SessionN3(state, hitBufs, d_bvhNodes, d_prims, d_tris, d_spheres);
        launchStageShadeLambertian_SessionN3(state, hitBufs, d_materials, bvhRes.materials.size());
        launchStageLightSample_SessionN4(state, hitBufs, d_materials, bvhRes.materials.size(),
                                          d_lights, bvhRes.areaLights.size(),
                                          d_bvhNodes, d_prims, d_tris, d_spheres);
        launchStageRussianRoulette_SessionN4(state);

        // Download PostRR snapshot fields.
        // Row format (16 elements per path):
        //   [0..2]:   ray_origin (x,y,z) — SEMANTIC: pre-bounce shading point
        //   [3..5]:   ray_direction (x,y,z)
        //   [6..9]:   throughput (4 floats, scaled by 1/p if survived)
        //   [10..13]: lambdas (4 floats)
        //   [14]:     rr_prob (continuation probability) — TODO placeholder
        //   [15]:     rr_survived (0 or 1) — TODO placeholder
        std::vector<float> snapshot(total_paths * 16);

        // Allocate host-pinned staging buffers for batch download.
        std::vector<float> h_ray_origin_x(total_paths);
        std::vector<float> h_ray_origin_y(total_paths);
        std::vector<float> h_ray_origin_z(total_paths);
        std::vector<float> h_ray_direction_x(total_paths);
        std::vector<float> h_ray_direction_y(total_paths);
        std::vector<float> h_ray_direction_z(total_paths);
        std::vector<float> h_throughput_0(total_paths);
        std::vector<float> h_throughput_1(total_paths);
        std::vector<float> h_throughput_2(total_paths);
        std::vector<float> h_throughput_3(total_paths);
        std::vector<float> h_lambda_0(total_paths);
        std::vector<float> h_lambda_1(total_paths);
        std::vector<float> h_lambda_2(total_paths);
        std::vector<float> h_lambda_3(total_paths);

        // Download all fields.
        // NOTE: ray_origin reads from hitBufs.hit_point_* (shading point), NOT
        // state.ray_origin_* (already overwritten by stage_shade to next-bounce
        // origin). This matches CPU path_kernel.cpp which captures ps.ray_origin
        // before the advance (lines 289-291).
        cudaError_t err;
        #define DOWNLOAD(dst, src, count) \
            err = cudaMemcpy((dst).data(), (src), (count) * sizeof((dst)[0]), cudaMemcpyDeviceToHost); \
            if (err != cudaSuccess) { \
                freeGPUWavefrontHitBuffers(hitBufs); \
                freeGPUWavefrontState(state); \
                throw std::runtime_error(std::string("cudaMemcpy failed: ") + cudaGetErrorString(err)); \
            }

        DOWNLOAD(h_ray_origin_x, hitBufs.hit_point_x, total_paths);
        DOWNLOAD(h_ray_origin_y, hitBufs.hit_point_y, total_paths);
        DOWNLOAD(h_ray_origin_z, hitBufs.hit_point_z, total_paths);
        DOWNLOAD(h_ray_direction_x, state.ray_direction_x, total_paths);
        DOWNLOAD(h_ray_direction_y, state.ray_direction_y, total_paths);
        DOWNLOAD(h_ray_direction_z, state.ray_direction_z, total_paths);
        DOWNLOAD(h_throughput_0, state.throughput_0, total_paths);
        DOWNLOAD(h_throughput_1, state.throughput_1, total_paths);
        DOWNLOAD(h_throughput_2, state.throughput_2, total_paths);
        DOWNLOAD(h_throughput_3, state.throughput_3, total_paths);
        DOWNLOAD(h_lambda_0, state.lambda_0, total_paths);
        DOWNLOAD(h_lambda_1, state.lambda_1, total_paths);
        DOWNLOAD(h_lambda_2, state.lambda_2, total_paths);
        DOWNLOAD(h_lambda_3, state.lambda_3, total_paths);

        #undef DOWNLOAD

        // Free GPU buffers.
        freeGPUWavefrontHitBuffers(hitBufs);
        freeGPUWavefrontState(state);

        // Pack into flat snapshot array (16 elements per path).
        // For Session N+4: rr_* fields are TODO placeholders (0.0).
        for (int i = 0; i < total_paths; ++i) {
            int base = i * 16;
            snapshot[base + 0]  = h_ray_origin_x[i];
            snapshot[base + 1]  = h_ray_origin_y[i];
            snapshot[base + 2]  = h_ray_origin_z[i];
            snapshot[base + 3]  = h_ray_direction_x[i];
            snapshot[base + 4]  = h_ray_direction_y[i];
            snapshot[base + 5]  = h_ray_direction_z[i];
            snapshot[base + 6]  = h_throughput_0[i];
            snapshot[base + 7]  = h_throughput_1[i];
            snapshot[base + 8]  = h_throughput_2[i];
            snapshot[base + 9]  = h_throughput_3[i];
            snapshot[base + 10] = h_lambda_0[i];
            snapshot[base + 11] = h_lambda_1[i];
            snapshot[base + 12] = h_lambda_2[i];
            snapshot[base + 13] = h_lambda_3[i];
            snapshot[base + 14] = 0.0f;  // rr_prob TODO: store in kernel
            snapshot[base + 15] = 0.0f;  // rr_survived TODO: store in kernel
        }

        // Clean up temporary scene data.
        if (d_bvhNodes) cudaFree(d_bvhNodes);
        if (d_prims) cudaFree(d_prims);
        if (d_tris) cudaFree(d_tris);
        if (d_spheres) cudaFree(d_spheres);
        if (d_materials) cudaFree(d_materials);
        if (d_lights) cudaFree(d_lights);

        return snapshot;
    } catch (...) {
        // Clean up on exception.
        if (d_bvhNodes) cudaFree(d_bvhNodes);
        if (d_prims) cudaFree(d_prims);
        if (d_tris) cudaFree(d_tris);
        if (d_spheres) cudaFree(d_spheres);
        if (d_materials) cudaFree(d_materials);
        if (d_lights) cudaFree(d_lights);
        throw;
    }
}

// ---------------------------------------------------------------------------
// pkg55-B' Session N+6 — end-to-end GPU wavefront render.
//
// Host driver for the stage_advance kernel: init -> advance x max_depth per
// sample round, then host-side XYZ accumulation mirroring the CPU wavefront
// driver (src/cpu/wavefront/cpu_wavefront_driver.cpp: per-sample toXYZ, the
// lum > 20 firefly clamp, /samples, filmExposure, xyzToLinearSRGB,
// finiteOrZero). This unlocks the final-image gate the per-stage harness
// explicitly defers ("until end-to-end GPU wavefront pipeline").
//
// Session N+6 capacity model: one SoA slot per pixel; samples run as
// sequential rounds (sample_index keys the RNG per round). Queue compaction
// and per-material sort are the N+7 perf session.
// ---------------------------------------------------------------------------
std::vector<float> cuda_wavefront_render(
    Renderer& renderer,
    const Camera& cam,
    int width, int height,
    int samples, int max_depth,
    uint64_t seed)
{
    int total_paths = width * height;
    if (total_paths <= 0 || samples <= 0) {
        throw std::runtime_error("cuda_wavefront_render: invalid dimensions");
    }

    // Build GCameraParams from Camera (same block as the snapshot entries).
    GCameraParams gcam;
    gcam.origin = GVec3(cam.getOrigin().x, cam.getOrigin().y, cam.getOrigin().z);
    gcam.lowerLeft = GVec3(cam.getLowerLeft().x, cam.getLowerLeft().y, cam.getLowerLeft().z);
    gcam.horizontal = GVec3(cam.getHorizontal().x, cam.getHorizontal().y, cam.getHorizontal().z);
    gcam.vertical = GVec3(cam.getVertical().x, cam.getVertical().y, cam.getVertical().z);
    gcam.lensRadius = cam.getLensRadius();
    gcam.width = width;
    gcam.height = height;
    {
        Vec3 u_vec = cam.getU();
        Vec3 v_vec = cam.getV();
        gcam.u = GVec3(u_vec.x, u_vec.y, u_vec.z);
        gcam.v = GVec3(v_vec.x, v_vec.y, v_vec.z);
    }
    gcam.focusDist = cam.getFocusDist();

    // Upload the FULL scene slice set (geometry + materials + lights + light
    // tree + env), unlike the per-stage snapshot entries which only need
    // geometry/materials.
    GBVHNode* d_bvhNodes = nullptr;
    GPrimitive* d_prims = nullptr;
    GTriangle* d_tris = nullptr;
    GSphere* d_spheres = nullptr;
    ::GMaterial* d_materials = nullptr;
    ::GLight* d_lights = nullptr;
    GLightTreeNode* d_treeNodes = nullptr;
    GLightTreeEmitter* d_treeEmitters = nullptr;
    int* d_lightToEmitter = nullptr;
    float* d_envData = nullptr;
    float* d_envCondCdf = nullptr;
    float* d_envCondFunc = nullptr;
    float* d_envMargCdf = nullptr;
    float* d_envMargFunc = nullptr;

    auto freeAllLocal = [&]() {
        if (d_bvhNodes) cudaFree(d_bvhNodes);
        if (d_prims) cudaFree(d_prims);
        if (d_tris) cudaFree(d_tris);
        if (d_spheres) cudaFree(d_spheres);
        if (d_materials) cudaFree(d_materials);
        if (d_lights) cudaFree(d_lights);
        if (d_treeNodes) cudaFree(d_treeNodes);
        if (d_treeEmitters) cudaFree(d_treeEmitters);
        if (d_lightToEmitter) cudaFree(d_lightToEmitter);
        if (d_envData) cudaFree(d_envData);
        if (d_envCondCdf) cudaFree(d_envCondCdf);
        if (d_envCondFunc) cudaFree(d_envCondFunc);
        if (d_envMargCdf) cudaFree(d_envMargCdf);
        if (d_envMargFunc) cudaFree(d_envMargFunc);
        cudaGetLastError();
    };

    GPUWavefrontState state;
    bool stateAllocated = false;

    try {
        SceneUploadResult res = buildSceneArrays(renderer, &cam);
        devUpload(res.nodes, &d_bvhNodes);
        devUpload(res.prims, &d_prims);
        devUpload(res.triangles, &d_tris);
        devUpload(res.spheres, &d_spheres);
        devUpload(res.materials, &d_materials);
        devUpload(res.lights, &d_lights);
        devUpload(res.lightTreeNodes, &d_treeNodes);
        devUpload(res.lightTreeEmitters, &d_treeEmitters);
        devUpload(res.lightToEmitter, &d_lightToEmitter);

        GLightTreeView treeView{d_treeNodes, d_treeEmitters, d_lightToEmitter,
                                (int)res.lightTreeNodes.size(),
                                (int)res.lightTreeNodes.size() > 0 ? 1 : 0};

        GEnvMap envMap{};
        if (res.envLoaded) {
            devUpload(res.envData,     &d_envData);
            devUpload(res.envCondCdf,  &d_envCondCdf);
            devUpload(res.envCondFunc, &d_envCondFunc);
            devUpload(res.envMargCdf,  &d_envMargCdf);
            devUpload(res.envMargFunc, &d_envMargFunc);
            envMap.data            = d_envData;
            envMap.conditionalCdf  = d_envCondCdf;
            envMap.conditionalFunc = d_envCondFunc;
            envMap.marginalCdf     = d_envMargCdf;
            envMap.marginalFunc    = d_envMargFunc;
            envMap.width           = res.envWidth;
            envMap.height          = res.envHeight;
            envMap.strength        = res.envStrength;
            std::memcpy(envMap.rotMat, res.envRotMat, 9 * sizeof(float));
            std::memcpy(envMap.colorTint, res.envColorTint, 3 * sizeof(float));
            envMap.totalPower      = res.envTotalPower;
            envMap.loaded          = true;
        }

        Vec3 bg = renderer.getBackgroundColor();
        bool hasBg = bg.x >= 0.f;
        GVec3 gbg = hasBg ? GVec3(bg.x, bg.y, bg.z) : GVec3(0.f);
        int worldMaxBounces = renderer.getWorldMaxBounces();

        if (!allocateGPUWavefrontState(state, total_paths)) {
            throw std::runtime_error("cuda_wavefront_render: SoA allocation failed");
        }
        stateAllocated = true;

        // Constant-memory spectral tables (JH LUT + D65 + CMF) — required by
        // every gpu_rgbToSampledSpectrum / gpu_spectrum_to_xyz call in the
        // advance kernel. Mirrors CUDARenderer::render's pre-launch uploads.
        uploadCmfTables();
        uploadJakobHanikaLut();

        // Host-side per-pixel XYZ accumulator (mirrors cpu_wavefront_driver).
        std::vector<double> accX(total_paths, 0.0), accY(total_paths, 0.0),
                            accZ(total_paths, 0.0);
        std::vector<float> h_c0(total_paths), h_c1(total_paths),
                           h_c2(total_paths), h_c3(total_paths);
        std::vector<float> h_l0(total_paths), h_l1(total_paths),
                           h_l2(total_paths), h_l3(total_paths);
        std::vector<float> h_p0(total_paths), h_p1(total_paths),
                           h_p2(total_paths), h_p3(total_paths);

        auto dl = [&](const float* d, std::vector<float>& h) {
            cudaError_t e = cudaMemcpy(h.data(), d, total_paths * sizeof(float),
                                       cudaMemcpyDeviceToHost);
            if (e != cudaSuccess)
                throw std::runtime_error(cudaGetErrorString(e));
        };

        for (int s = 0; s < samples; ++s) {
            launchStageInit(state, gcam, width, height, seed, s);
            for (int b = 0; b < max_depth; ++b) {
                launchStageAdvance(state, d_bvhNodes, d_prims, d_tris, d_spheres,
                                   d_materials, d_lights,
                                   (int)res.lights.size(), res.totalLightPower,
                                   treeView, envMap, gbg, hasBg,
                                   worldMaxBounces, max_depth);
            }
            dl(state.color_0, h_c0); dl(state.color_1, h_c1);
            dl(state.color_2, h_c2); dl(state.color_3, h_c3);
            dl(state.lambda_0, h_l0); dl(state.lambda_1, h_l1);
            dl(state.lambda_2, h_l2); dl(state.lambda_3, h_l3);
            dl(state.lambda_pdf_0, h_p0); dl(state.lambda_pdf_1, h_p1);
            dl(state.lambda_pdf_2, h_p2); dl(state.lambda_pdf_3, h_p3);

            for (int i = 0; i < total_paths; ++i) {
                SampledSpectrum rad(std::array<float, 4>{
                    h_c0[i], h_c1[i], h_c2[i], h_c3[i]});
                SampledWavelengths lambdas = SampledWavelengths::fromLambdas(
                    std::array<float, 4>{h_l0[i], h_l1[i], h_l2[i], h_l3[i]},
                    std::array<float, 4>{h_p0[i], h_p1[i], h_p2[i], h_p3[i]});
                XYZ xyz = rad.toXYZ(lambdas);
                // Per-sample firefly clamp on XYZ.Y (mirrors CPU driver).
                float lum = xyz.Y;
                if (lum > 20.0f) {
                    xyz.X *= (20.0f / lum);
                    xyz.Y = 20.0f;
                    xyz.Z *= (20.0f / lum);
                }
                accX[i] += xyz.X; accY[i] += xyz.Y; accZ[i] += xyz.Z;
            }
        }

        // Final conversion (mirrors cpu_wavefront_driver lines 100-113).
        std::vector<float> rgb(total_paths * 3);
        float exposure = renderer.getFilmExposure();
        for (int i = 0; i < total_paths; ++i) {
            Vec3 colorXYZ(float(accX[i] / samples), float(accY[i] / samples),
                          float(accZ[i] / samples));
            colorXYZ *= exposure;
            Vec3 colorSRGB = xyzToLinearSRGB(colorXYZ);
            rgb[i * 3 + 0] = std::max(Renderer::finiteOrZero(colorSRGB.x), 0.0f);
            rgb[i * 3 + 1] = std::max(Renderer::finiteOrZero(colorSRGB.y), 0.0f);
            rgb[i * 3 + 2] = std::max(Renderer::finiteOrZero(colorSRGB.z), 0.0f);
        }

        freeGPUWavefrontState(state);
        freeAllLocal();
        return rgb;
    } catch (...) {
        if (stateAllocated) freeGPUWavefrontState(state);
        freeAllLocal();
        throw;
    }
}

}  // namespace astroray::wavefront
