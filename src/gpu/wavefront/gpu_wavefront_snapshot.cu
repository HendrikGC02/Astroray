// gpu_wavefront_snapshot.cu — pkg55-B' Session N+3
//
// GPU wavefront PostInit snapshot download for CPU↔GPU diff harness.
//
// Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §4.2 Session N+3.
// Design: PR #296 §4.1, §4.2 (two-tier gate: CPU↔GPU bounded, not exact).

#include "gpu_wavefront_snapshot.h"
#include "astroray/gpu_wavefront_state.h"
#include "astroray/gpu_types.h"
#include "raytracer.h"
#include <cuda_runtime.h>
#include <stdexcept>
#include <cstdio>

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
        const auto& bvhRes = renderer.getBVHAsGPUData();
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
    GMaterial* d_materials = nullptr;

    try {
        const auto& bvhRes = renderer.getBVHAsGPUData();
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

}  // namespace astroray::wavefront
