#pragma once
// Pure C++ interface for the CUDA renderer.
// This header MUST NOT include any CUDA headers — it is included by
// pybind11 translation units (blender_module.cpp) that nvcc never sees.

#include <memory>
#include <vector>
#include <string>

// Forward declarations to avoid pulling in CUDA types here.
// The implementations live in cuda_renderer.cu / scene_upload.cu.
class Renderer;
class Camera;
class EnvironmentMap;
struct SceneUploadResult;  // pkg86-B: host-side upload slices (gpu_scene_upload.h)

// Vec3 is needed for the render() output buffer type.
// Include raytracer.h here (it is pure C++, no CUDA).
#include "raytracer.h"

class CUDARenderer {
public:
    CUDARenderer();
    ~CUDARenderer();

    // Returns true when at least one CUDA-capable device is present.
    bool isAvailable() const;

    // Name of the first CUDA device, or "none" / "CUDA not compiled".
    std::string deviceName() const;

    // Upload the scene from a CPU renderer and camera.
    // Must be called before render().
    //
    // pkg56 Phase B: this is a thin sequenced wrapper over the four per-domain
    // uploaders below. The CPU Renderer must have a built BVH (call
    // Renderer::buildAcceleration() first). Mirrors Cycles BlenderSync's
    // per-domain upload pattern (intern/cycles/blender/sync.cpp, Apache-2.0).
    void uploadScene(const Renderer& cpuRenderer, const Camera& camera);

    // pkg56 Phase B — per-domain incremental uploaders.
    //
    // Each uploader pushes only its slice of the scene to device memory,
    // leaving the other slices' device buffers untouched. They share the
    // same SceneUploadResult host build (buildSceneArrays); Phase C will
    // dispatch them based on bpy.types.Depsgraph.updates. See research note
    // .astroray_plan/docs/blender-depsgraph-sync-research.md §3, §5, §6.
    //
    // All four are order-independent for state — partial uploads are safe
    // (e.g. materials before geometry yields a black image, not a crash).
    // The CPU Renderer must have a built BVH before uploadGeometry() is
    // called; the others do not require a BVH.
    void uploadGeometry(const Renderer& cpuRenderer, const Camera& camera);
    void uploadMaterials(const Renderer& cpuRenderer);
    void uploadLights(const Renderer& cpuRenderer);
    void uploadEnvironment(const Renderer& cpuRenderer);

    // pkg114 inc 3d — TLAS-only refit: re-push ONLY the instance transforms + TLAS
    // (d_instances / d_tlas) from the current CPU instance list, leaving all BLAS
    // geometry on the device untouched. The cheap path for a transform-only
    // viewport edit of an instanced object (pkg56 <=50%-baseline budget).
    void uploadInstanceTransforms(const Renderer& cpuRenderer);

    // pkg86-B: wall-clock cost of the most recent light-tree upload (ms).
    // 0 when no tree was uploaded. Spec gates <= 10 ms on 10k lights.
    float lightTreeUploadMs() const;

    // pkg86-B: batch debug probe — runs gpu_light_tree_pick for each
    // (point, normal, u) triple on the device and writes the picked GLight
    // index + selection pdf. Used by the CPU<->GPU parity gate
    // (tests/test_pkg86_B_gpu_parity.py). Requires a prior uploadScene()
    // with the Tree sampler active; returns false when no tree is resident.
    bool debugLightTreePick(const std::vector<Vec3>& points,
                            const std::vector<Vec3>& normals,
                            const std::vector<float>& us,
                            std::vector<int>& outLightIndex,
                            std::vector<float>& outPdf);

    // Upload environment map (optional; call after uploadScene).
    void uploadEnvironmentMap(const EnvironmentMap& envMap);

    // pkg55-C7: the megakernel render entries (render / renderMultiwavelength)
    // and the pkg87b GPU-cryptomatte surface were deleted with the megakernels
    // (src/gpu/path_trace_kernel.cu + multiwavelength_kernel.cu). The
    // production GPU render path is the wavefront:
    // astroray::wavefront::cuda_wavefront_render (gpu_wavefront_snapshot.h).
    // CUDARenderer remains the owner of the uploaded-device-state surfaces
    // (probes, refit, profile lookup).

    // pkg64-gpu Phase 1 probe (moved from the deleted render()): run the SMS
    // device-attempt probe against the uploaded scene. Requires uploadScene().
    void runSmsProbe();

    // pkg54d: test hook for the profile table uploaded by the latest
    // uploadScene() call.
    float lookupProfileReflectance(int profileIndex, float lambda) const;

    // [0, 1] progress estimate (reserved for async use in Phase 3).
    float getProgress() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl;

    // pkg86-B: shared by uploadScene/uploadLights — pushes (or clears) the
    // flattened light-tree slice and records the upload time.
    void uploadLightTree(const SceneUploadResult& r);
};
