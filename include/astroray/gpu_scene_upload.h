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
    float envStrength = 1.f, envTotalPower = 0.f;
    // pkg63: baked rotation matrix (3x3 row-major) + color tint to upload to GEnvMap.
    float envRotMat[9] = {1,0,0, 0,1,0, 0,0,1};
    float envColorTint[3] = {1.f, 1.f, 1.f};
    bool  envLoaded = false;

    // pkg54a: spectral profile table (resampled onto the GPU's fixed grid).
    // Layout: profileTable[i * G_PROFILE_SAMPLES + s] is reflectance of
    // profile i at lambda = G_PROFILE_LAMBDA_MIN + s * G_PROFILE_LAMBDA_STEP.
    std::vector<float> profileTable;
    int                profileCount = 0;
};

// Declared here; defined in scene_upload.cu
class Renderer;
class Camera;
SceneUploadResult buildSceneArrays(const Renderer& cpu, const Camera& cam);
