#pragma once
// gpu_scene_upload.h — Shared struct for scene upload between .cu files.
// Included by both scene_upload.cu and cuda_renderer.cu.

#include "astroray/gpu_types.h"
#include "astroray/shader_vm.h"  // pkg219b — ShaderVMProgram
#include "astroray/manifold/sms_attempt_device.cuh"  // pkg64-gpu Phase 2
#include <vector>

struct SceneUploadResult {
    std::vector<GBVHNode>   nodes;
    std::vector<GPrimitive> prims;
    std::vector<GTriangle>  triangles;
    std::vector<GSphere>    spheres;
    std::vector<GMaterial>  materials;
    // pkg178 Stage-3b D4: true when ANY uploaded material lowers to a
    // closure-graph Principled (mirrors gpu_closure_graph_is_principled:
    // type == GMAT_CLOSURE_GRAPH && closures[0].type == GCLOSURE_PRINCIPLED).
    // The wavefront launchers pick the stageShade*<true/false> instantiation off
    // this flag so non-principled scenes never compile in gpu_principled_* code.
    bool hasPrincipled = false;

    // pkg186 — GPU image textures. `textureTexels` is the flat RGB texel buffer
    // holding ALL uploaded images concatenated; `textures[i]` slices it with an
    // {offset,width,height}. `materialTextureId` is parallel to `materials`
    // (same index) and holds the texture id for each material (-1 = flat albedo,
    // preserving the untextured fast path). `hasTexture` selects the HasTexture
    // shade-kernel instantiation (mirrors hasPrincipled). Only image-textured
    // 'lambertian' materials (TexturedLambertian) populate these today; the
    // procedural-node slice is a follow-up (see pkg186 spec decision 1).
    std::vector<GImageTexture> textures;
    std::vector<GVec3>         textureTexels;
    std::vector<int>           materialTextureId;
    bool                       hasTexture = false;

    // pkg219b — per-texel op-VM programs. `programs` holds each unique compiled
    // ShaderVMProgram (deduped by ProgramTexture*); `materialProgramId` is
    // parallel to `materials` (-1 = no program). `hasProgram` selects the
    // stageShadeBucketedKernel<…,HasProgram=true> instantiation; false keeps the
    // whole fleet on the byte-identical <…,false> kernel (register-probe gate).
    // A program material ALSO carries a materialTextureId (its single ImageTexture
    // input): the shade path samples that image, then runs the VM on the colour.
    std::vector<astroray::svm::ShaderVMProgram> programs;
    std::vector<int>                            materialProgramId;
    bool                                        hasProgram = false;

    // pkg189 — true when ANY uploaded material is dispersive (Sellmeier dielectric
    // → GMAT_DIELECTRIC, or Cauchy Principled glass → GMAT_CLOSURE_GRAPH; both set
    // GMaterial::isDispersive in scene_upload.cu). Selects the
    // stageShadeBucketedKernel<*,*,*,true> instantiation carrying the hero-λ
    // collapse SoA write-back; false keeps the fleet on the byte-identical
    // <*,*,*,false> kernel.
    bool                       hasDispersive = false;

    std::vector<GLight>     lights;
    // pkg89-GPU / GAP 1 — dedicated lights (Blender POINT/SPOT/SUN/AREA lamps
    // routed through astroray::Light). Their cumulativePower continues the
    // unified power CDF past `lights`; totalLightPower spans both kinds.
    std::vector<GDedicatedLight> dedicatedLights;
    float totalLightPower = 0.f;

    // pkg114 — two-level BVH. Populated ONLY when the CPU Renderer has
    // instances (Renderer::hasInstances()); otherwise these stay empty and the
    // device traversal falls back to the single-level `nodes`/`prims` path.
    // When instanced, `nodes`/`prims`/`triangles`/`spheres` hold the CONCATENATED
    // per-mesh BLAS geometry in OBJECT-LOCAL space; `blas[i]` slices into them;
    // `instances[j]` carries the object<->world transforms; `tlas` is the BVH
    // (a single flat leaf for now) whose leaves index `instances`.
    std::vector<GTLASNode>  tlas;
    std::vector<GInstance>  instances;
    std::vector<GBLAS>      blas;

    // pkg55-B' Session N+4: area lights for wavefront NEE
    std::vector<GAreaLight> areaLights;

    // pkg86-B: flattened light tree (empty unless sampler mode is Tree and
    // every emitter has a GLight slot — see scene_upload.cu tree block).
    std::vector<GLightTreeNode>    lightTreeNodes;
    std::vector<GLightTreeEmitter> lightTreeEmitters;
    std::vector<int>               lightToEmitter;  // GLight idx -> emitter idx (-1 absent)

    // pkg64-gpu Phase 2: caustic-caster spheres (flagged + transmissive + IOR > 1)
    std::vector<astroray::manifold::device::GSMSCaster> smsCasters;

    // pkg88-C.0 GPU — verify on RTX. Scene-wide motion vertex buffer for deformation
    // motion blur. Per Cycles: center step reuses triangles[].v0/v1/v2; additional
    // steps stored here. Each triangle's motionOffset indexes into this array.
    std::vector<GVec3> motionVertices;

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

// pkg56 Phase B: camera became optional so the per-domain CUDA uploaders
// (uploadMaterials / uploadLights / uploadEnvironment) can rebuild the host
// SceneUploadResult slice without holding a Camera. When `cam` is nullptr,
// r.camera is left default-initialised; the caller is expected not to
// publish it onto the device.
SceneUploadResult buildSceneArrays(const Renderer& cpu, const Camera* cam);

// Backwards-compatible reference overload used by the existing full-scene
// upload path.
inline SceneUploadResult buildSceneArrays(const Renderer& cpu, const Camera& cam) {
    return buildSceneArrays(cpu, &cam);
}

// pkg114 inc 3d — TLAS-only refit. Rebuilds ONLY r.tlas + r.instances from the
// current instance transforms (no BLAS geometry walk); the caller re-pushes just
// those two device buffers. All other SceneUploadResult fields stay empty.
SceneUploadResult buildTlasOnly(const Renderer& cpu);
