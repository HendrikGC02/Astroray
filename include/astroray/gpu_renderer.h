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
    void uploadScene(const Renderer& cpuRenderer, const Camera& camera);

    // Upload environment map (optional; call after uploadScene).
    void uploadEnvironmentMap(const EnvironmentMap& envMap);

    // Render into a pre-sized pixel buffer (host memory, HxWx3 float, gamma-corrected).
    void render(std::vector<Vec3>& pixels,
                int width, int height,
                int samplesPerPixel, int maxDepth);

    // [0, 1] progress estimate (reserved for async use in Phase 3).
    float getProgress() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl;
};
