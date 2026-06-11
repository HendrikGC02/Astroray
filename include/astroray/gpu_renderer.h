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

    // Render into a pre-sized pixel buffer (host memory, HxWx3 float, linear).
    // pkg64-gpu Phase 3: use_refractive_caustics/use_reflective_caustics gate
    // the SMS attempt inside the megakernel (both must be true to enable).
    void render(std::vector<Vec3>& pixels,
                int width, int height, int seed,
                int samplesPerPixel, int maxDepth,
                bool use_refractive_caustics = true,
                bool use_reflective_caustics = true);

    // pkg54: GPU port of the multi-wavelength path tracer. Same scene state as
    // render(); accepts a configurable wavelength band and luminance/visible
    // output mode. lambdaMin/lambdaMax are nm; when useLuminanceOutput is true
    // the kernel stores the per-band mean radiance as neutral grey RGB,
    // otherwise it projects the spectrum to linear sRGB via Wyman 2013 CMFs.
    // pkg64-gpu Phase 3: use_refractive_caustics/use_reflective_caustics gate
    // the SMS attempt inside the megakernel (both must be true to enable).
    void renderMultiwavelength(std::vector<Vec3>& pixels,
                               int width, int height, int seed,
                               int samplesPerPixel, int maxDepth,
                               float lambdaMin, float lambdaMax,
                               bool useLuminanceOutput,
                               bool enableNEE = true,
                               bool use_refractive_caustics = true,
                               bool use_reflective_caustics = true);

    // pkg54d: test hook for the profile table uploaded by the latest
    // uploadScene() call.
    float lookupProfileReflectance(int profileIndex, float lambda) const;

    // [0, 1] progress estimate (reserved for async use in Phase 3).
    float getProgress() const;

    // pkg87b: Cryptomatte control + retrieval
    void setCryptomatteEnabled(bool enabled);
    bool getCryptomatteEnabled() const;
    void copyCryptoBuffersToHost(std::vector<float>& objectBuffer,
                                  std::vector<float>& materialBuffer,
                                  int width, int height, int depth);

private:
    struct Impl;
    std::unique_ptr<Impl> impl;

    // pkg86-B: shared by uploadScene/uploadLights — pushes (or clears) the
    // flattened light-tree slice and records the upload time.
    void uploadLightTree(const SceneUploadResult& r);
};
