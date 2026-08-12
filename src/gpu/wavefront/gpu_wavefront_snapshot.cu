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
#include "astroray/cryptomatte.h"  // pkg159: crypto_sort_ranks for the copy-back post
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
// pkg55-C7 (megakernel removal): these uploads previously happened only in
// the megakernel render entries (cuda_renderer.cu); the wavefront is now the
// production route and must own them. Defined in gpu_glass_tables.cu (pkg151
// rough-transmission multiscatter compensation) / gpu_spectral_tables.cu
// (pkg54a per-material spectral profiles).
void uploadGgxGlassTables();
void uploadProfileTable(const float* host, int count);
// pkg152 (#523, rebased into C7): reflection-lobe multi-scatter/layering
// compensation tables (gpu_ggx_tables.cu) — required by gpu_disney_eval's
// gpu_ggxCompensationFactor/DirectionalAlbedo/sheen/clearcoat lookups.
void uploadGgxTables();

// pkg178 Stage 4 PR-3: thin-film CIE sensitivity LUT (gpu_thin_film_table.cu) —
// required by the principled thin-film RGB legs (gpu_pr_thinFilm*RGB / conductor
// spectral). No-op unless a principled material has thin_film_thickness > 0.1nm.
void uploadThinFilmTable();

// pkg55-C5 / pkg113: photon caustic grid structures.
#include "astroray/gpu_photon_caustic.h"
#include "astroray/gpu_photon_store.h"

namespace astroray::wavefront {

// Forward declarations for stage launch functions from stage_advance.cu + stage_init.cu
// (pkg55-C3: added useLuminanceOutput, enableNEE, lambdaMin/Max params)

// pkg162: the private re-declaration of launchStageInit that used to sit here
// is GONE. It existed only to shadow a phantom 6-parameter declaration in
// gpu_wavefront_state.h that no definition matched. That header declaration is
// now correct (8 params, matching stage_init.cu), so this file's `#include` of
// it suffices — as it always should have. pkg157 removed three duplicates of
// this same pattern; this was the fourth and last.

void launchStageRegen(
    GPUWavefrontState& state,
    float* d_accum,
    int* d_work, int total_work, int capacity,
    const GCameraParams& cam,
    int width, int height,
    uint64_t seed,
    float lambdaMin,
    float lambdaMax,
    int* d_count_out,       // pkg55-C7: fused per-pass counter zeroing
    int* d_shade_counts,
    int* d_shadow_count,
    bool useLuminanceOutput);  // pkg55-C7: grey band-mean accumulation

// pkg157: the private re-declarations of launchStageIntersectQueued,
// launchStageShadeBucketed and launchStageShadeNeeMis that used to live here
// are DELETED. They duplicated declarations this TU already gets from
// "astroray/gpu_wavefront_state.h" (included above), and duplication is what
// broke the pkg157 build: the ShadeBucketed copy here was the only one that
// matched the definition (the header's was missing the photon params), so
// adding the clamp params to the header + definition left the call below
// matching NEITHER overload. The header now matches the definition exactly,
// so these copies are redundant AND dangerous — a stale copy silently
// declares a phantom overload that fails at link time rather than compile
// time. Keep the header as the single source of truth.

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
        launchStageInit(state, gcam, width, height, seed, 0,
                        G_LAMBDA_MIN, G_LAMBDA_MAX);
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
        launchStageInit(state, gcam, width, height, seed, 0,
                        G_LAMBDA_MIN, G_LAMBDA_MAX);
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
        launchStageInit(state, gcam, width, height, seed, 0,
                        G_LAMBDA_MIN, G_LAMBDA_MAX);
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
        launchStageInit(state, gcam, width, height, seed, 0,
                        G_LAMBDA_MIN, G_LAMBDA_MAX);
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
        launchStageInit(state, gcam, width, height, seed, 0,
                        G_LAMBDA_MIN, G_LAMBDA_MAX);
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
// ---------------------------------------------------------------------------
// pkg55-B' viewport-parity: persistent device context.
//
// The first viewport A/B (2026-06-12, 100k tris, 1-spp chunks) measured the
// stateless driver at ~105 ms/frame vs the megakernel's ~78 ms — the gap is
// the ~60 cudaMalloc/cudaFree pairs per call (state SoA + hit buffers +
// queues + NEE park + scene arrays), not the kernels. The megakernel keeps
// its per-path state alive across frames and re-uploads scene DATA only.
// This context mirrors that: grow-only device allocations reused across
// calls; scene data re-uploaded (memcpy into existing buffers) every call —
// the same unconditional-upload policy the megakernel viewport uses today
// (pkg56 Phase C depsgraph-selective upload remains the shared follow-up).
//
// Single render thread assumed (matches CUDARenderer's implicit contract).
// Allocations live for the process; freed by the driver at context teardown.
// ---------------------------------------------------------------------------
namespace {

struct WfDeviceBuf {
    void*  ptr = nullptr;
    size_t bytes = 0;
};

// Grow-only ensure. Returns the typed pointer.
template <typename T>
T* wfEnsure(WfDeviceBuf& b, size_t count) {
    size_t need = count * sizeof(T);
    if (need == 0) return reinterpret_cast<T*>(b.ptr);
    if (need > b.bytes) {
        if (b.ptr) cudaFree(b.ptr);
        b.ptr = nullptr;
        b.bytes = 0;
        cudaError_t e = cudaMalloc(&b.ptr, need);
        if (e != cudaSuccess)
            throw std::runtime_error(cudaGetErrorString(e));
        b.bytes = need;
    }
    return reinterpret_cast<T*>(b.ptr);
}

template <typename T>
T* wfUpload(WfDeviceBuf& b, const std::vector<T>& src) {
    if (src.empty()) return nullptr;
    T* p = wfEnsure<T>(b, src.size());
    cudaError_t e = cudaMemcpy(p, src.data(), src.size() * sizeof(T),
                               cudaMemcpyHostToDevice);
    if (e != cudaSuccess)
        throw std::runtime_error(cudaGetErrorString(e));
    return p;
}

struct WfContext {
    // Scene slices.
    WfDeviceBuf nodes, prims, tris, spheres, materials, lights;
    WfDeviceBuf dedLights;                    // pkg89-wavefront (C7)
    WfDeviceBuf textures, textureTexels, materialTextureId;  // pkg186 image textures
    WfDeviceBuf tlas, instances, blas;        // pkg55-C4 / pkg114
    WfDeviceBuf motionVertices;               // pkg55-C4 / pkg88-C.0
    WfDeviceBuf treeNodes, treeEmitters, lightToEmitter;
    WfDeviceBuf envData, envCondCdf, envCondFunc, envMargCdf, envMargFunc;
    // Per-path state (grow-only via the existing allocators).
    GPUWavefrontState state{};
    GPUWavefrontHitBuffers hitBufs{};
    int stateCapacity = 0;
    // Driver buffers.
    WfDeviceBuf accum, queueA, queueB, counts, shadeQueues, shadeCounts;
    WfDeviceBuf neeF, neeI, shadowQueue, shadowCount, work;
    // pkg159: per-pixel cryptomatte rank arrays (numPixels*depth*2 floats
    // each). Grow-only like the rest; only allocated once a render actually
    // enables cryptomatte, so default renders pay nothing.
    WfDeviceBuf cryptoObj, cryptoMat;
    // pkg55-C6b / pkg24: ReSTIR reservoir SoA, double-buffered + persistent
    // across frames (render calls) so temporal reuse can read the previous
    // frame. resNumPixels tracks the allocated resolution; restirFrame counts
    // completed ReSTIR frames (reuse enabled once >= 1 prior frame exists).
    GPUReservoirSoA resA{};
    GPUReservoirSoA resB{};
    int resNumPixels = 0;
    int restirFrame  = 0;
    bool resCurIsA   = true;   // which of resA/resB is "current" this frame
    uint64_t restirSessionId = 0;  // pkg55-C6b: temporal-history session (reset key)
};

WfContext& wfCtx() {
    static WfContext ctx;
    return ctx;
}

}  // namespace

// pkg55-C2 MIS audit: run stage_init + the PRODUCTION intersect+shade (deferred
// NEE parking) for one bounce and download the shade-time MIS pdfs the wavefront
// used. Row format (3 floats per path):
//   [0]: path_light_pdf  — NEE selection×solid-angle pdf (incl. light-tree pick)
//   [1]: path_mis_pdf    — BSDF pdf at the NEE direction
//   [2]: path_mis_weight — resulting power-heuristic weight (Veach 1997)
// Sentinel: path_light_pdf == 0.0 means "no NEE fired at this slot" (delta lobe,
// no lights, occlusion-independent zero-f_spec, or an env/emissive path that
// died before shade). The gate masks those rows out.
std::vector<float> cuda_wavefront_snapshot_post_nee_mis(
    Renderer& renderer,
    const Camera& cam,
    int width, int height,
    uint64_t seed)
{
    int total_paths = width * height;
    if (total_paths <= 0) {
        throw std::runtime_error("cuda_wavefront_snapshot_post_nee_mis: invalid dimensions");
    }

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

    // Scene upload (mirrors cuda_wavefront_render: GLight + light tree + env).
    GBVHNode* d_bvhNodes = nullptr;
    GPrimitive* d_prims = nullptr;
    GTriangle* d_tris = nullptr;
    GSphere* d_spheres = nullptr;
    // pkg55-C4: TLAS/instances/blas + motionVerts
    GTLASNode* d_tlas = nullptr;
    GInstance* d_instances = nullptr;
    GBLAS* d_blas = nullptr;
    GVec3* d_motionVerts = nullptr;
    ::GMaterial* d_materials = nullptr;
    ::GLight* d_lights = nullptr;
    GDedicatedLight* d_dedLights = nullptr;  // pkg89-wavefront (C7)
    GLightTreeNode* d_treeNodes = nullptr;
    GLightTreeEmitter* d_treeEmitters = nullptr;
    int* d_lightToEmitter = nullptr;
    float* d_envData = nullptr;
    float* d_envCondCdf = nullptr;
    float* d_envCondFunc = nullptr;
    float* d_envMargCdf = nullptr;
    float* d_envMargFunc = nullptr;
    float* d_nee_f = nullptr;
    int* d_nee_i = nullptr;
    int* d_shadow_queue = nullptr;
    int* d_shadow_count = nullptr;

    GPUWavefrontState state{};
    GPUWavefrontHitBuffers hitBufs{};
    bool stateAllocated = false, hitAllocated = false;

    auto cleanup = [&]() {
        if (stateAllocated) freeGPUWavefrontState(state);
        if (hitAllocated) freeGPUWavefrontHitBuffers(hitBufs);
        cudaFree(d_bvhNodes); cudaFree(d_prims); cudaFree(d_tris);
        cudaFree(d_spheres);
        cudaFree(d_tlas); cudaFree(d_instances); cudaFree(d_blas); cudaFree(d_motionVerts);  // pkg55-C4
        cudaFree(d_materials); cudaFree(d_lights);
        cudaFree(d_dedLights);  // pkg89-wavefront (C7)
        cudaFree(d_treeNodes); cudaFree(d_treeEmitters); cudaFree(d_lightToEmitter);
        cudaFree(d_envData); cudaFree(d_envCondCdf); cudaFree(d_envCondFunc);
        cudaFree(d_envMargCdf); cudaFree(d_envMargFunc);
        cudaFree(d_nee_f); cudaFree(d_nee_i);
        cudaFree(d_shadow_queue); cudaFree(d_shadow_count);
    };

    try {
        SceneUploadResult res = buildSceneArrays(renderer, &cam);
        devUpload(res.nodes, &d_bvhNodes);
        devUpload(res.prims, &d_prims);
        devUpload(res.triangles, &d_tris);
        devUpload(res.spheres, &d_spheres);
        // pkg55-C4: TLAS/instances/blas + motionVerts for MIS audit snapshot
        devUpload(res.tlas, &d_tlas);
        devUpload(res.instances, &d_instances);
        devUpload(res.blas, &d_blas);
        devUpload(res.motionVertices, &d_motionVerts);
        devUpload(res.materials, &d_materials);
        devUpload(res.lights, &d_lights);
        devUpload(res.dedicatedLights, &d_dedLights);  // pkg89-wavefront (C7)
        devUpload(res.lightTreeNodes, &d_treeNodes);
        devUpload(res.lightTreeEmitters, &d_treeEmitters);
        devUpload(res.lightToEmitter, &d_lightToEmitter);

        GLightTreeView treeView{d_treeNodes, d_treeEmitters, d_lightToEmitter,
                                (int)res.lightTreeNodes.size(),
                                (int)res.lightTreeNodes.size() > 0 ? 1 : 0};

        GEnvMap envMap{};
        if (res.envLoaded) {
            devUpload(res.envData, &d_envData);
            devUpload(res.envCondCdf, &d_envCondCdf);
            devUpload(res.envCondFunc, &d_envCondFunc);
            devUpload(res.envMargCdf, &d_envMargCdf);
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

        if (!allocateGPUWavefrontState(state, total_paths))
            throw std::runtime_error("cuda_wavefront_snapshot_post_nee_mis: state alloc failed");
        stateAllocated = true;
        if (!allocateGPUWavefrontHitBuffers(hitBufs, total_paths))
            throw std::runtime_error("cuda_wavefront_snapshot_post_nee_mis: hit buffer alloc failed");
        hitAllocated = true;

        // Deferred-NEE parking scratch (G_WF_NEE_F_LANES floats +
        // G_WF_NEE_I_LANES ints per slot, per the stage_advance.cu parking
        // layout); shadow queue is unused output.
        auto mallocOrThrow = [](void** p, size_t bytes) {
            if (cudaMalloc(p, bytes) != cudaSuccess)
                throw std::runtime_error("cuda_wavefront_snapshot_post_nee_mis: scratch alloc failed");
        };
        mallocOrThrow((void**)&d_nee_f, size_t(G_WF_NEE_F_LANES) * total_paths * sizeof(float));
        mallocOrThrow((void**)&d_nee_i, size_t(G_WF_NEE_I_LANES) * total_paths * sizeof(int));
        mallocOrThrow((void**)&d_shadow_queue, size_t(total_paths) * sizeof(int));
        mallocOrThrow((void**)&d_shadow_count, sizeof(int));
        cudaMemset(d_shadow_count, 0, sizeof(int));

        // Sentinel-zero the MIS instrumentation arrays: only NEE-firing slots
        // overwrite them, so "path_light_pdf == 0" marks "no NEE at this slot".
        cudaMemset(state.path_light_pdf,  0, total_paths * sizeof(float));
        cudaMemset(state.path_mis_pdf,    0, total_paths * sizeof(float));
        cudaMemset(state.path_mis_weight, 0, total_paths * sizeof(float));

        // Spectral tables: gpu_material_eval_spectral gates NEE on f_spec>0, so
        // without the JH LUT + D65 + CMF uploads every f_spec is 0 and NEE never
        // fires (the black-frame failure mode; see cuda_wavefront_render).
        uploadCmfTables();
        uploadJakobHanikaLut();

        launchStageInit(state, gcam, width, height, seed, 0,
                        G_LAMBDA_MIN, G_LAMBDA_MAX);
        launchStageShadeNeeMis(state, hitBufs, d_nee_f, d_nee_i,
                               d_shadow_queue, d_shadow_count, total_paths,
                               d_tlas, d_instances, d_blas,  // pkg55-C4
                               d_bvhNodes, d_prims, d_tris, d_spheres,
                               d_motionVerts, d_materials,  // pkg55-C4
                               d_lights, (int)res.lights.size(),
                               res.totalLightPower,
                               d_dedLights, (int)res.dedicatedLights.size(),  // pkg89-wavefront
                               treeView, envMap, gbg, hasBg,
                               worldMaxBounces, /*max_depth=*/8,
                               /*useLuminanceOutput=*/false, /*enableNEE=*/true,
                               renderer.getClampDirect(), renderer.getClampIndirect(),  // pkg157
                               res.hasPrincipled);  // pkg178 Stage-3b D4

        cudaError_t se = cudaDeviceSynchronize();
        if (se != cudaSuccess)
            throw std::runtime_error(std::string("cuda_wavefront_snapshot_post_nee_mis sync: ")
                                     + cudaGetErrorString(se));

        std::vector<float> h_light_pdf(total_paths);
        std::vector<float> h_mis_pdf(total_paths);
        std::vector<float> h_mis_weight(total_paths);
        cudaError_t err;
        #define DL(dst, src) \
            err = cudaMemcpy((dst).data(), (src), total_paths * sizeof(float), cudaMemcpyDeviceToHost); \
            if (err != cudaSuccess) throw std::runtime_error(std::string("cudaMemcpy failed: ") + cudaGetErrorString(err));
        DL(h_light_pdf, state.path_light_pdf);
        DL(h_mis_pdf, state.path_mis_pdf);
        DL(h_mis_weight, state.path_mis_weight);
        #undef DL

        std::vector<float> snapshot(size_t(total_paths) * 3);
        for (int i = 0; i < total_paths; ++i) {
            snapshot[i * 3 + 0] = h_light_pdf[i];
            snapshot[i * 3 + 1] = h_mis_pdf[i];
            snapshot[i * 3 + 2] = h_mis_weight[i];
        }
        cleanup();
        return snapshot;
    } catch (...) {
        cleanup();
        throw;
    }
}

// pkg55-C5 / pkg113: build photon caustic aim from the scene (mirrors
// cuda_renderer.cu:662 `buildCausticAim`).
static astroray::photon::gpu::PhotonCausticAim buildCausticAim(
    const Renderer& scene, int maxDepth) {
    astroray::photon::gpu::PhotonCausticAim aim{};
    aim.valid = false;
    aim.lambdaMin = 380.0f;
    aim.lambdaMax = 720.0f;
    aim.maxDepth  = maxDepth;
    aim.boost     = 1.2f;   // CPU caustic_boost default (spectral_path_tracer.cpp:499)
    aim.photonCount = 4000000;  // forward photons (≈2000² lattice); CPU traces 3e6

    // Union AABB of all flagged caustic-caster objects.
    AABB casterBounds; bool any = false;
    for (const auto& obj : scene.getScene()) {
        if (!obj || !obj->isCausticCaster()) continue;
        AABB ob;
        if (!obj->boundingBox(ob)) continue;
        casterBounds = any ? casterBounds.merge(ob) : ob;
        any = true;
    }
    if (!any) return aim;

    const Vec3 casterC = casterBounds.centroid();
    const float crad = (casterBounds.max - casterBounds.min).length() * 0.55f + 1e-3f;

    const auto& lights = scene.getLights();
    if (lights.empty()) return aim;

    // Probe one light sample toward the caster centroid to get the sun direction
    // (CPU :356-362). A fixed seed keeps the aim deterministic frame-to-frame.
    std::mt19937 gen(12345u);
    astroray::SampledWavelengths probe = astroray::SampledWavelengths::sampleUniform(0.5f);
    LightSample ls;
    lights.sample(ls, casterC, Vec3(0, 1, 0), probe, gen);
    Vec3 sunDir = (casterC - ls.position).normalized();
    if (sunDir.length2() < 1e-6f) return aim;

    Vec3 origin0 = casterC - sunDir * (crad + 2.0f);
    aim.sunDir         = GVec3(sunDir.x, sunDir.y, sunDir.z);
    aim.apertureOrigin = GVec3(origin0.x, origin0.y, origin0.z);
    aim.apertureRadius = crad;
    aim.valid = true;
    return aim;
}

std::vector<float> cuda_wavefront_render(
    Renderer& renderer,
    const Camera& cam,
    int width, int height,
    int samples, int max_depth,
    uint64_t seed,
    float lambdaMin, float lambdaMax,
    bool useLuminanceOutput,
    bool enableNEE,
    float* cryptoObjectOut,    // pkg159
    float* cryptoMaterialOut,  // pkg159
    int cryptoDepth)           // pkg159
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

    // Persistent context: scene DATA re-uploaded every call into grow-only
    // device buffers (megakernel-parity policy); per-path state reused.
    WfContext& C = wfCtx();
    SceneUploadResult res = buildSceneArrays(renderer, &cam);
    GBVHNode*   d_bvhNodes  = wfUpload(C.nodes, res.nodes);
    GPrimitive* d_prims     = wfUpload(C.prims, res.prims);
    GTriangle*  d_tris      = wfUpload(C.tris, res.triangles);
    GSphere*    d_spheres   = wfUpload(C.spheres, res.spheres);
    // pkg55-C4 / pkg114: TLAS/instances/blas for instancing support (empty unless
    // scene has instances; null-TLAS path in gpu_tlas_hit falls back to single-level).
    GTLASNode*  d_tlas      = wfUpload(C.tlas, res.tlas);
    GInstance*  d_instances = wfUpload(C.instances, res.instances);
    GBLAS*      d_blas      = wfUpload(C.blas, res.blas);
    // pkg55-C4 / pkg88-C.0: deformation-motion vertices (nullptr for static scenes).
    GVec3*      d_motionVerts = wfUpload(C.motionVertices, res.motionVertices);
    ::GMaterial* d_materials = wfUpload(C.materials, res.materials);
    // pkg186 — image-texture device arrays. All null for untextured scenes
    // (wfUpload returns nullptr on empty), and res.hasTexture=false then selects
    // the <*,false> shade kernel, so untextured renders pay nothing. The three
    // pointers are published ONCE per frame into the shade kernel's __constant__
    // binding (setWavefrontTextureBinding) — NOT threaded through the per-launch
    // signature — so the untextured fleet kernel keeps its pre-pkg186 footprint.
    GImageTexture* d_textures  = wfUpload(C.textures, res.textures);
    GVec3*         d_texelBuf  = wfUpload(C.textureTexels, res.textureTexels);
    int*           d_matTexId  = wfUpload(C.materialTextureId, res.materialTextureId);
    if (res.hasTexture)
        setWavefrontTextureBinding(GWavefrontTextureBinding{d_textures, d_texelBuf, d_matTexId});
    ::GLight*   d_lights    = wfUpload(C.lights, res.lights);
    // pkg89-wavefront (C7): dedicated lights join wavefront NEE (unified
    // power CDF continues past the GLight entries; see gpu_nee.cuh).
    GDedicatedLight* d_dedLights = wfUpload(C.dedLights, res.dedicatedLights);
    GLightTreeNode* d_treeNodes = wfUpload(C.treeNodes, res.lightTreeNodes);
    GLightTreeEmitter* d_treeEmitters = wfUpload(C.treeEmitters, res.lightTreeEmitters);
    int* d_lightToEmitter = wfUpload(C.lightToEmitter, res.lightToEmitter);

    GLightTreeView treeView{d_treeNodes, d_treeEmitters, d_lightToEmitter,
                            (int)res.lightTreeNodes.size(),
                            (int)res.lightTreeNodes.size() > 0 ? 1 : 0};

    GEnvMap envMap{};
    if (res.envLoaded) {
        envMap.data            = wfUpload(C.envData, res.envData);
        envMap.conditionalCdf  = wfUpload(C.envCondCdf, res.envCondCdf);
        envMap.conditionalFunc = wfUpload(C.envCondFunc, res.envCondFunc);
        envMap.marginalCdf     = wfUpload(C.envMargCdf, res.envMargCdf);
        envMap.marginalFunc    = wfUpload(C.envMargFunc, res.envMargFunc);
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
    // pkg157: wavefront twin of the deleted megakernels' clampDirect/
    // clampIndirect wiring (cuda_renderer.cu, pre-C7). Defaults 0/off unless
    // the host set them via set_clamp_direct/set_clamp_indirect.
    float clampDirect = renderer.getClampDirect();
    float clampIndirect = renderer.getClampIndirect();

    // pkg55-C5 / pkg113: scene-driven photon-map caustic pre-pass. Mirrors the MW
    // megakernel path (multiwavelength_kernel.cu:936-962, cuda_renderer.cu:848-862).
    // When the scene has flagged caustic-caster glass and the renderer enables photon
    // caustics, forward-trace photons through the glass, build a resident hash grid,
    // and hand the grid + calibrated brightness scale to the shade stage (it gathers
    // at primary receiver hits). Gated on the OPT-IN usePhotonCaustics flag (pkg113
    // Phase-3 transition-clean policy).
    astroray::photon::gpu::GPhotonCausticResult caustic{};
    caustic.ready = false;
    if (renderer.getUsePhotonCaustics()) {
        astroray::photon::gpu::PhotonCausticAim aim =
            buildCausticAim(renderer, max_depth);
        if (aim.valid) {
            caustic = astroray::photon::gpu::cuda_photon_caustic_build(
                d_bvhNodes, d_prims, d_tris, d_spheres, d_materials, aim);
            if (caustic.ready) {
                printf("[CUDA wavefront] pkg113 photon caustic: %d photons, scale %g\n",
                       caustic.numPhotons, caustic.scale);
            }
        }
    }

    // Per-path state: grow-only.
    if (C.stateCapacity < total_paths) {
        if (C.stateCapacity > 0) {
            freeGPUWavefrontState(C.state);
            freeGPUWavefrontHitBuffers(C.hitBufs);
        }
        if (!allocateGPUWavefrontState(C.state, total_paths))
            throw std::runtime_error("cuda_wavefront_render: SoA allocation failed");
        if (!allocateGPUWavefrontHitBuffers(C.hitBufs, total_paths)) {
            freeGPUWavefrontState(C.state);
            C.stateCapacity = 0;
            throw std::runtime_error("cuda_wavefront_render: hit buffer allocation failed");
        }
        C.stateCapacity = total_paths;
    }
    GPUWavefrontState& state = C.state;
    GPUWavefrontHitBuffers& hitBufs = C.hitBufs;

    constexpr int kNumMatTypes = 7;  // GMAT_LAMBERTIAN..GMAT_CLOSURE_GRAPH
    float* d_accum       = wfEnsure<float>(C.accum, size_t(total_paths) * 3);
    int*   d_queueA      = wfEnsure<int>(C.queueA, total_paths);
    int*   d_queueB      = wfEnsure<int>(C.queueB, total_paths);
    int*   d_counts      = wfEnsure<int>(C.counts, 2);
    int*   d_shadeQueues = wfEnsure<int>(C.shadeQueues, size_t(kNumMatTypes) * total_paths);
    int*   d_shadeCounts = wfEnsure<int>(C.shadeCounts, kNumMatTypes);
    float* d_neeF        = wfEnsure<float>(C.neeF, size_t(G_WF_NEE_F_LANES) * total_paths);
    int*   d_neeI        = wfEnsure<int>(C.neeI, size_t(G_WF_NEE_I_LANES) * total_paths);
    int*   d_shadowQueue = wfEnsure<int>(C.shadowQueue, total_paths);
    int*   d_shadowCount = wfEnsure<int>(C.shadowCount, 1);
    int*   d_work        = wfEnsure<int>(C.work, 1);

    {
        cudaError_t ae = cudaMemset(d_accum, 0,
                                    size_t(total_paths) * 3 * sizeof(float));
        if (ae != cudaSuccess)
            throw std::runtime_error(cudaGetErrorString(ae));
    }

    // pkg159: cryptomatte rank buffers. Gated on BOTH the renderer flag and
    // caller-supplied output pointers, so a render with cryptomatte off never
    // allocates, never memsets, and passes nullptr into the shade stage.
    const bool cryptoOn = renderer.getCryptomatteEnabled() &&
                          cryptoObjectOut != nullptr &&
                          cryptoMaterialOut != nullptr &&
                          cryptoDepth > 0;
    const size_t cryptoFloats =
        cryptoOn ? size_t(total_paths) * size_t(cryptoDepth) * 2 : 0;
    float* d_cryptoObj = nullptr;
    float* d_cryptoMat = nullptr;
    if (cryptoOn) {
        d_cryptoObj = wfEnsure<float>(C.cryptoObj, cryptoFloats);
        d_cryptoMat = wfEnsure<float>(C.cryptoMat, cryptoFloats);
        // Zero at render start: CRYPTO_ID_NONE is 0.0f, so a memset both
        // empties every slot and resets every weight (Cycles zeroes the
        // cryptomatte pass region of the render buffer the same way).
        cudaError_t ce = cudaMemset(d_cryptoObj, 0, cryptoFloats * sizeof(float));
        if (ce == cudaSuccess)
            ce = cudaMemset(d_cryptoMat, 0, cryptoFloats * sizeof(float));
        if (ce != cudaSuccess)
            throw std::runtime_error(cudaGetErrorString(ce));
    }

    // Constant-memory spectral tables (JH LUT + D65 + CMF) — required by
    // every spectral upsample / XYZ conversion in the kernels. Cheap
    // memcpyToSymbol, called per render like the megakernel path. (The N+6
    // bring-up black-frame bug; reintroduced once in the persistent-context
    // rewrite and caught by the image gate — keep these with the render.)
    uploadCmfTables();
    uploadJakobHanikaLut();
    // pkg55-C7: table uploads the deleted megakernel entries used to own.
    // Without these the wavefront read zeroed device tables whenever no
    // megakernel render preceded it in-process (pkg151 glass compensation
    // silently off; pkg54a NIR/UV profile override broken).
    uploadGgxGlassTables();
    uploadGgxTables();  // pkg152 (#523) — re-homed from the deleted render()
    uploadThinFilmTable();  // pkg178 Stage 4 PR-3 — thin-film CIE sensitivity LUT
    if (res.profileCount > 0)
        uploadProfileTable(res.profileTable.data(), res.profileCount);

    {
        const long long total_work = (long long)total_paths * samples;
        const long long counter_slack =
            (long long)total_paths * (16 + max_depth + 2);
        if (total_work + counter_slack > 0x7FFFFFFFLL)
            throw std::runtime_error(
                "cuda_wavefront_render: width*height*samples exceeds "
                "the overshoot-safe 32-bit work-counter range");
        cudaMemset(d_work, 0, sizeof(int));
        cudaMemset(state.path_alive, 0, total_paths * sizeof(int));
        cudaMemset(state.color_0, 0, total_paths * sizeof(float));
        cudaMemset(state.color_1, 0, total_paths * sizeof(float));
        cudaMemset(state.color_2, 0, total_paths * sizeof(float));
        cudaMemset(state.color_3, 0, total_paths * sizeof(float));
        // pkg55-C5 / pkg113: zero photon XYZ accumulators.
        cudaMemset(state.photon_xyz_x, 0, total_paths * sizeof(float));
        cudaMemset(state.photon_xyz_y, 0, total_paths * sizeof(float));
        cudaMemset(state.photon_xyz_z, 0, total_paths * sizeof(float));
        state.num_active = total_paths;

        launchStageQueueIota(d_queueA, d_counts + 0, total_paths);
        int* cout = d_counts + 1;

        // Pass-count planning. waves = how many full pools the work needs.
        // SINGLE-WAVE renders (1-spp viewport chunks: total_work <= pool)
        // need NO counter readbacks at all: every path is claimed by the
        // first regen and bounce-capped within max_depth passes, so exactly
        // max_depth passes + the final accumulating regen finish the frame
        // (each readback is a 4-byte D2H sync = a pipeline stall per pass —
        // measured as the dominant 1-spp overhead, 2026-06-12). Multi-wave
        // renders keep the every-16 counter cadence.
        const long long waves =
            (total_work + total_paths - 1) / total_paths;
        const int kCheckEvery = 16;
        const long long kMaxPasses = (waves == 1)
            ? max_depth
            : (long long)samples * max_depth + max_depth + 64;
        bool workExhausted = false;
        int drainLeft = max_depth;
        for (long long pass = 0; pass < kMaxPasses; ++pass) {
            // pkg55-C7 perf: the per-pass counter zeroing (cout/shadeCounts/
            // shadowCount) is fused into stageRegenKernel thread 0 — same
            // same-stream ordering as the 3 cudaMemsetAsync launches it
            // replaces (~3.6k launches saved per 512-spp render).
            launchStageRegen(state, d_accum, d_work, (int)total_work,
                             total_paths, gcam, width, height, seed,
                             lambdaMin, lambdaMax,
                             cout, d_shadeCounts, d_shadowCount,
                             useLuminanceOutput);
            launchStageIntersectQueued(state, hitBufs, d_queueA, d_counts + 0,
                                       d_shadeQueues, d_shadeCounts,
                                       total_paths,
                                       d_tlas, d_instances, d_blas,  // pkg55-C4
                                       d_bvhNodes, d_prims, d_tris,
                                       d_spheres, d_motionVerts, d_materials,  // pkg55-C4
                                       envMap, gbg, hasBg,
                                       worldMaxBounces,
                                       useLuminanceOutput, enableNEE,
                                       clampDirect, clampIndirect,  // pkg157
                                       d_lights,                     // pkg120
                                       (int)res.lights.size(),
                                       res.totalLightPower,
                                       d_dedLights,                  // pkg181
                                       (int)res.dedicatedLights.size(),
                                       treeView);
            launchStageShadeBucketed(state, hitBufs,
                                     d_shadeQueues, d_shadeCounts,
                                     total_paths, d_queueB, cout,
                                     d_neeF, d_neeI, d_shadowQueue,
                                     d_shadowCount,
                                     d_tlas, d_instances, d_blas,  // pkg55-C4
                                     d_bvhNodes, d_prims, d_tris,
                                     d_spheres, d_motionVerts, d_materials,  // pkg55-C4
                                     d_lights,
                                     (int)res.lights.size(),
                                     res.totalLightPower,
                                     d_dedLights,  // pkg89-wavefront (C7)
                                     (int)res.dedicatedLights.size(),
                                     treeView, max_depth,
                                     useLuminanceOutput, enableNEE,
                                     clampDirect, clampIndirect,  // pkg157
                                     caustic.grid, caustic.ready,  // pkg55-C5 / pkg113
                                     caustic.scale,
                                     d_cryptoObj, d_cryptoMat,     // pkg159
                                     cryptoOn ? cryptoDepth : 0,
                                     res.hasPrincipled,  // pkg178 Stage-3b D4
                                     res.hasTexture);     // pkg186 (data via c_wfTexBinding)
            launchStageShadow(state, hitBufs, d_neeF, d_neeI,
                              d_shadowQueue, d_shadowCount, total_paths,
                              d_tlas, d_instances, d_blas,  // pkg55-C4
                              d_bvhNodes, d_prims, d_tris, d_spheres,
                              d_motionVerts, d_materials,  // pkg55-C4
                              useLuminanceOutput,
                              clampDirect, clampIndirect);  // pkg157
            if (waves == 1) continue;  // fixed pass count, no readbacks
            if (workExhausted) {
                if (--drainLeft <= 0) break;
            } else if ((pass + 1) % kCheckEvery == 0) {
                int scheduled = 0;
                cudaError_t ce = cudaMemcpy(&scheduled, d_work, sizeof(int),
                                            cudaMemcpyDeviceToHost);
                if (ce != cudaSuccess)
                    throw std::runtime_error(cudaGetErrorString(ce));
                if ((long long)scheduled >= total_work) workExhausted = true;
            }
        }
        launchStageRegen(state, d_accum, d_work, (int)total_work,
                         total_paths, gcam, width, height, seed,
                         lambdaMin, lambdaMax,
                         /*d_count_out=*/nullptr, nullptr, nullptr,
                         useLuminanceOutput);

        cudaError_t syncErr = cudaDeviceSynchronize();
        if (syncErr != cudaSuccess)
            throw std::runtime_error(
                std::string("cuda_wavefront_render kernel error: ") +
                cudaGetErrorString(syncErr));
    }

    std::vector<float> h_accum(size_t(total_paths) * 3);
    cudaError_t de = cudaMemcpy(h_accum.data(), d_accum,
                                size_t(total_paths) * 3 * sizeof(float),
                                cudaMemcpyDeviceToHost);
    if (de != cudaSuccess)
        throw std::runtime_error(cudaGetErrorString(de));

    // pkg159: cryptomatte copy-back + post. Runs ONCE, after every sample has
    // resolved — never concurrently with the atomic inserts (the
    // cudaDeviceSynchronize above is the barrier).
    //
    // Post = sort weight-descending, then per-pixel weight normalisation. That
    // is the CPU CryptomattePass (plugins/passes/cryptomatte_pass.cpp), which
    // mirrors Cycles film_cryptomatte_post (sort, Apache-2.0) + Psyop spec
    // v1.2.0 §2 (normalise). It is reproduced here rather than reused because
    // the GPU render route in blender_module.cpp does not run the pass
    // pipeline (only Renderer::renderFrame does), and the addon always enables
    // cryptomatte and adds the "cryptomatte" pass together (__init__.py:1104-1106),
    // so the CPU leg is always sorted+normalised. Both steps are idempotent,
    // so wiring the pass pipeline into the GPU route later stays correct.
    if (cryptoOn) {
        cudaError_t ce = cudaMemcpy(cryptoObjectOut, d_cryptoObj,
                                    cryptoFloats * sizeof(float),
                                    cudaMemcpyDeviceToHost);
        if (ce == cudaSuccess)
            ce = cudaMemcpy(cryptoMaterialOut, d_cryptoMat,
                            cryptoFloats * sizeof(float),
                            cudaMemcpyDeviceToHost);
        if (ce != cudaSuccess)
            throw std::runtime_error(cudaGetErrorString(ce));

        for (int p = 0; p < total_paths; ++p) {
            float* obj = cryptoObjectOut + size_t(p) * cryptoDepth * 2;
            float* mat = cryptoMaterialOut + size_t(p) * cryptoDepth * 2;
            crypto_sort_ranks(obj, cryptoDepth);
            crypto_sort_ranks(mat, cryptoDepth);
            float objSum = 0.f, matSum = 0.f;
            for (int rank = 0; rank < cryptoDepth; ++rank) {
                objSum += obj[rank * 2 + 1];
                matSum += mat[rank * 2 + 1];
            }
            if (objSum > 0.f)
                for (int rank = 0; rank < cryptoDepth; ++rank) obj[rank * 2 + 1] /= objSum;
            if (matSum > 0.f)
                for (int rank = 0; rank < cryptoDepth; ++rank) mat[rank * 2 + 1] /= matSum;
        }
    }

    // pkg55-C5 / pkg113: release the resident photon grid after the render
    // (mirrors cuda_renderer.cu:888).
    astroray::photon::gpu::cuda_photon_caustic_free(caustic);

    // Final conversion (mirrors cpu_wavefront_driver lines 100-113).
    std::vector<float> rgb(size_t(total_paths) * 3);
    float exposure = renderer.getFilmExposure();
    for (int i = 0; i < total_paths; ++i) {
        Vec3 colorXYZ(h_accum[i * 3 + 0] / samples,
                      h_accum[i * 3 + 1] / samples,
                      h_accum[i * 3 + 2] / samples);
        colorXYZ *= exposure;
        Vec3 colorSRGB = xyzToLinearSRGB(colorXYZ);
        rgb[i * 3 + 0] = std::max(Renderer::finiteOrZero(colorSRGB.x), 0.0f);
        rgb[i * 3 + 1] = std::max(Renderer::finiteOrZero(colorSRGB.y), 0.0f);
        rgb[i * 3 + 2] = std::max(Renderer::finiteOrZero(colorSRGB.z), 0.0f);
    }
    return rgb;
}

// ---------------------------------------------------------------------------
// pkg55-C6b / pkg24: GPU ReSTIR-DI wavefront render.
//
// A dedicated direct-illumination driver: per frame (render call) it processes
// `samples` primary passes, each running RIS -> [temporal] -> [spatial] ->
// resolve at the primary/bounce-0 shading point, accumulating direct light +
// primary env/emissive radiance. The per-pixel reservoir SoA is double-buffered
// and PERSISTED across render calls in the singleton WfContext so temporal reuse
// can read the previous frame (mirrors the CPU FrameState double-buffer,
// frame_state.h). This is deliberately NOT the multi-bounce path-regeneration
// loop of cuda_wavefront_render: ReSTIR-DI reuses per-pixel reservoirs at the
// primary hit, which requires a race-free 1-thread-per-pixel schedule.
//
// Scope: direct illumination + emission + environment (ReSTIR-DI). Indirect GI
// and dedicated lights are out of the DI-gate scope (documented in the PR).
// ---------------------------------------------------------------------------
std::vector<float> cuda_wavefront_render_restir(
    Renderer& renderer,
    const Camera& cam,
    int width, int height,
    int samples, int max_depth,
    uint64_t seed,
    int numCandidates, int mCap,
    bool useTemporal, bool useSpatial,
    int spatialRadius, int spatialNeighbors,
    uint64_t sessionId)
{
    (void)max_depth;  // DI-only: no indirect bounces.
    int numPixels = width * height;
    if (numPixels <= 0 || samples <= 0)
        throw std::runtime_error("cuda_wavefront_render_restir: invalid dimensions");

    GCameraParams gcam;
    gcam.origin     = GVec3(cam.getOrigin().x, cam.getOrigin().y, cam.getOrigin().z);
    gcam.lowerLeft  = GVec3(cam.getLowerLeft().x, cam.getLowerLeft().y, cam.getLowerLeft().z);
    gcam.horizontal = GVec3(cam.getHorizontal().x, cam.getHorizontal().y, cam.getHorizontal().z);
    gcam.vertical   = GVec3(cam.getVertical().x, cam.getVertical().y, cam.getVertical().z);
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

    WfContext& C = wfCtx();
    SceneUploadResult res = buildSceneArrays(renderer, &cam);
    GBVHNode*   d_bvhNodes  = wfUpload(C.nodes, res.nodes);
    GPrimitive* d_prims     = wfUpload(C.prims, res.prims);
    GTriangle*  d_tris      = wfUpload(C.tris, res.triangles);
    GSphere*    d_spheres   = wfUpload(C.spheres, res.spheres);
    GTLASNode*  d_tlas      = wfUpload(C.tlas, res.tlas);
    GInstance*  d_instances = wfUpload(C.instances, res.instances);
    GBLAS*      d_blas      = wfUpload(C.blas, res.blas);
    GVec3*      d_motionVerts = wfUpload(C.motionVertices, res.motionVertices);
    ::GMaterial* d_materials = wfUpload(C.materials, res.materials);
    ::GLight*   d_lights    = wfUpload(C.lights, res.lights);
    GLightTreeNode* d_treeNodes = wfUpload(C.treeNodes, res.lightTreeNodes);
    GLightTreeEmitter* d_treeEmitters = wfUpload(C.treeEmitters, res.lightTreeEmitters);
    int* d_lightToEmitter = wfUpload(C.lightToEmitter, res.lightToEmitter);

    GLightTreeView treeView{d_treeNodes, d_treeEmitters, d_lightToEmitter,
                            (int)res.lightTreeNodes.size(),
                            (int)res.lightTreeNodes.size() > 0 ? 1 : 0};

    GEnvMap envMap{};
    if (res.envLoaded) {
        envMap.data            = wfUpload(C.envData, res.envData);
        envMap.conditionalCdf  = wfUpload(C.envCondCdf, res.envCondCdf);
        envMap.conditionalFunc = wfUpload(C.envCondFunc, res.envCondFunc);
        envMap.marginalCdf     = wfUpload(C.envMargCdf, res.envMargCdf);
        envMap.marginalFunc    = wfUpload(C.envMargFunc, res.envMargFunc);
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
    // pkg157: see cuda_wavefront_render's identical note.
    float clampDirect = renderer.getClampDirect();
    float clampIndirect = renderer.getClampIndirect();

    // Per-path state: grow-only (1 slot per pixel; DI = single bounce).
    if (C.stateCapacity < numPixels) {
        if (C.stateCapacity > 0) {
            freeGPUWavefrontState(C.state);
            freeGPUWavefrontHitBuffers(C.hitBufs);
        }
        if (!allocateGPUWavefrontState(C.state, numPixels))
            throw std::runtime_error("cuda_wavefront_render_restir: SoA allocation failed");
        if (!allocateGPUWavefrontHitBuffers(C.hitBufs, numPixels)) {
            freeGPUWavefrontState(C.state);
            C.stateCapacity = 0;
            throw std::runtime_error("cuda_wavefront_render_restir: hit buffer allocation failed");
        }
        C.stateCapacity = numPixels;
    }
    GPUWavefrontState& state = C.state;
    GPUWavefrontHitBuffers& hitBufs = C.hitBufs;
    state.num_active = numPixels;

    // Reservoir buffers: (re)allocate on a resolution change, which also resets
    // the temporal history (a resized/replaced scene has no valid prior frame).
    if (C.resNumPixels != numPixels) {
        if (C.resNumPixels > 0) {
            freeGPUReservoirSoA(C.resA);
            freeGPUReservoirSoA(C.resB);
        }
        if (!allocateGPUReservoirSoA(C.resA, numPixels) ||
            !allocateGPUReservoirSoA(C.resB, numPixels))
            throw std::runtime_error("cuda_wavefront_render_restir: reservoir allocation failed");
        C.resNumPixels = numPixels;
        C.restirFrame  = 0;
        C.resCurIsA    = true;
        C.restirSessionId = sessionId;
    }

    // A new integrator session (new integrator instance / renderer) resets the
    // temporal history: the CPU restir_di owns frameState_ per-instance, so a
    // fresh session must not read a stale previous frame from the global
    // WfContext (the TestDeterminism isolation requirement). A persistent
    // renderer rendering a sequence WITHOUT recreating its integrator keeps the
    // same sessionId and thus keeps accumulating.
    if (C.restirSessionId != sessionId) {
        C.restirFrame     = 0;
        C.restirSessionId = sessionId;
    }

    // Frame swap (FrameState::advanceFrame): current <-> previous, clear current.
    C.resCurIsA = !C.resCurIsA;
    GPUReservoirSoA& curRes  = C.resCurIsA ? C.resA : C.resB;
    GPUReservoirSoA& prevRes = C.resCurIsA ? C.resB : C.resA;
    clearGPUReservoirSoA(curRes);

    // Reuse is enabled once a previous frame exists (mirrors the CPU
    // frameState_.frameIndex >= 2 gate, restir_di.cpp:215).
    bool reuseReady = (C.restirFrame >= 1);
    int effectiveMCap = (mCap > 0) ? mCap : (20 * numCandidates);

    float* d_accum = wfEnsure<float>(C.accum, size_t(numPixels) * 3);
    cudaMemset(d_accum, 0, size_t(numPixels) * 3 * sizeof(float));

    // Constant-memory spectral tables (JH LUT + D65 + CMF) required by every
    // spectral upsample / XYZ conversion (same per-render upload as the path).
    uploadCmfTables();
    uploadJakobHanikaLut();
    uploadGgxGlassTables();  // pkg55-C7: see cuda_wavefront_render note
    uploadGgxTables();       // pkg152 (#523)
    uploadThinFilmTable();   // pkg178 Stage 4 PR-3 — thin-film CIE sensitivity LUT

    // ReSTIR-DI is visible-band spectral (matches the CPU restir_di).
    const float lambdaMin = 380.0f, lambdaMax = 780.0f;
    const bool useLuminanceOutput = false;

    for (int s = 0; s < samples; ++s) {
        launchStageRestirPrimary(
            state, hitBufs, gcam, width, height, s, seed, lambdaMin, lambdaMax,
            d_tlas, d_instances, d_blas, d_bvhNodes, d_prims, d_tris, d_spheres,
            d_motionVerts, d_materials, envMap, gbg, hasBg, worldMaxBounces,
            useLuminanceOutput, clampDirect, clampIndirect);  // pkg157

        launchStageRestirInitialRIS(
            state, hitBufs, curRes, d_prims, d_tris, d_spheres, d_materials,
            d_lights, (int)res.lights.size(), res.totalLightPower, treeView,
            numCandidates, effectiveMCap, numPixels);

        if (reuseReady && useTemporal)
            launchStageRestirTemporalReuse(state, curRes, prevRes,
                                           effectiveMCap, numPixels);

        if (reuseReady && useSpatial && spatialNeighbors > 0)
            launchStageRestirSpatialReuse(state, curRes, prevRes, width, height,
                                          spatialRadius, spatialNeighbors,
                                          effectiveMCap, numPixels);

        launchStageRestirResolve(
            state, hitBufs, curRes, d_accum, d_tlas, d_instances, d_blas,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_motionVerts, d_materials,
            numPixels, useLuminanceOutput, clampDirect, clampIndirect);  // pkg157
    }

    cudaError_t syncErr = cudaDeviceSynchronize();
    if (syncErr != cudaSuccess)
        throw std::runtime_error(
            std::string("cuda_wavefront_render_restir kernel error: ") +
            cudaGetErrorString(syncErr));

    ++C.restirFrame;

    std::vector<float> h_accum(size_t(numPixels) * 3);
    cudaError_t de = cudaMemcpy(h_accum.data(), d_accum,
                                size_t(numPixels) * 3 * sizeof(float),
                                cudaMemcpyDeviceToHost);
    if (de != cudaSuccess)
        throw std::runtime_error(cudaGetErrorString(de));

    std::vector<float> rgb(size_t(numPixels) * 3);
    float exposure = renderer.getFilmExposure();
    for (int i = 0; i < numPixels; ++i) {
        Vec3 colorXYZ(h_accum[i * 3 + 0] / samples,
                      h_accum[i * 3 + 1] / samples,
                      h_accum[i * 3 + 2] / samples);
        colorXYZ *= exposure;
        Vec3 colorSRGB = xyzToLinearSRGB(colorXYZ);
        rgb[i * 3 + 0] = std::max(Renderer::finiteOrZero(colorSRGB.x), 0.0f);
        rgb[i * 3 + 1] = std::max(Renderer::finiteOrZero(colorSRGB.y), 0.0f);
        rgb[i * 3 + 2] = std::max(Renderer::finiteOrZero(colorSRGB.z), 0.0f);
    }
    return rgb;
}

}  // namespace astroray::wavefront
