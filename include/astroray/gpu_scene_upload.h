#pragma once
// gpu_scene_upload.h — Shared struct for scene upload between .cu files.
// Included by both scene_upload.cu and cuda_renderer.cu.

#include "astroray/gpu_types.h"
#include <vector>

struct SceneUploadResult {
    std::vector<GBVHNode>   nodes;
    std::vector<GPrimitive> prims;
    std::vector<GTriangle>  triangles;
    std::vector<GSphere>    spheres;
    std::vector<GMaterial>  materials;
    std::vector<GLight>     lights;
    float totalLightPower = 0.f;

    // Camera
    GCameraParams camera{};

    // Env map (host arrays — caller uploads with cudaMalloc)
    std::vector<float> envData;
    std::vector<float> envCondCdf;
    std::vector<float> envCondFunc;
    std::vector<float> envMargCdf;
    std::vector<float> envMargFunc;
    int   envWidth = 0, envHeight = 0;
    float envStrength = 1.f, envRotation = 0.f, envTotalPower = 0.f;
    bool  envLoaded = false;
};

// Declared here; defined in scene_upload.cu
class Renderer;
class Camera;
SceneUploadResult buildSceneArrays(const Renderer& cpu, const Camera& cam);
