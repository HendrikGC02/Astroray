// scene_upload.cu — Host → Device scene transfer for CUDARenderer.
// Converts CPU scene data (BVH nodes, triangles, spheres, materials, lights,
// env map) into flat GPU arrays via cudaMalloc / cudaMemcpy.

#include "astroray/gpu_scene_upload.h"
#include "astroray/gpu_types.h"
#include "astroray/shapes.h"
#include "astroray/spectral_profile.h"
#include "raytracer.h"
#include "advanced_features.h"
// pkg87a — Cryptomatte hash function.
// Path is `src/util/...` (not `util/...`) because astroray_cuda's include
// search has `${CMAKE_SOURCE_DIR}` private — not `${CMAKE_SOURCE_DIR}/src`.
// CI runs on Ubuntu without CUDA so this never failed there; only the RTX
// hardware build hit it (memory: ci_has_no_gpu_runtime_blindspot).
#include "src/util/murmurhash3.h"

#include <cuda_runtime.h>
#include <vector>
#include <memory>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <unordered_map>

#define CUDA_CHECK(call) do {                                               \
    cudaError_t _e = (call);                                                \
    if (_e != cudaSuccess) {                                                \
        fprintf(stderr, "CUDA error at %s:%d: %s\n",                       \
                __FILE__, __LINE__, cudaGetErrorString(_e));                \
        throw std::runtime_error(cudaGetErrorString(_e));                   \
    }                                                                       \
} while(0)

// ---------------------------------------------------------------------------
// Helper: upload a host vector to a newly-allocated device array
// ---------------------------------------------------------------------------
template<typename T>
static void uploadVector(const std::vector<T>& src, T** d_ptr) {
    if (src.empty()) { *d_ptr = nullptr; return; }
    CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(d_ptr), src.size() * sizeof(T)));
    CUDA_CHECK(cudaMemcpy(*d_ptr, src.data(), src.size() * sizeof(T), cudaMemcpyHostToDevice));
}

// ---------------------------------------------------------------------------
// Convert CPU LinearBVHNode → GBVHNode
// ---------------------------------------------------------------------------
static GBVHNode convertNode(const LinearBVHNode& n) {
    GBVHNode g;
    g.bounds.min = GVec3(n.bounds.min.x, n.bounds.min.y, n.bounds.min.z);
    g.bounds.max = GVec3(n.bounds.max.x, n.bounds.max.y, n.bounds.max.z);
    g.primitivesOffset = n.primitivesOffset; // union — covers both fields
    g.nPrimitives      = n.nPrimitives;
    g.axis             = n.axis;
    g.pad              = 0;
    return g;
}

// ---------------------------------------------------------------------------
// Convert a CPU Material shared_ptr → GMaterial flat struct
// ---------------------------------------------------------------------------
static GClosureType convertClosureType(astroray::MaterialClosureType type) {
    switch (type) {
        case astroray::MaterialClosureType::Diffuse: return GCLOSURE_DIFFUSE;
        case astroray::MaterialClosureType::GGXConductor: return GCLOSURE_GGX_CONDUCTOR;
        case astroray::MaterialClosureType::DielectricTransmission: return GCLOSURE_DIELECTRIC_TRANSMISSION;
        case astroray::MaterialClosureType::Clearcoat: return GCLOSURE_CLEARCOAT;
        case astroray::MaterialClosureType::Sheen: return GCLOSURE_SHEEN;
        case astroray::MaterialClosureType::Emission: return GCLOSURE_EMISSION;
        case astroray::MaterialClosureType::ThinGlass: return GCLOSURE_THIN_GLASS;
        case astroray::MaterialClosureType::None:
        default:
            return GCLOSURE_NONE;
    }
}

static GMaterial convertMaterial(const std::shared_ptr<Material>& mat) {
    MaterialBackendCapabilities caps = mat->backendCapabilities();
    if (!caps.gpu) {
        throw std::runtime_error("Material cannot be uploaded to GPU: " + caps.notes);
    }

    GMaterial g{};
    g.spectralMode     = GSPEC_RGB_ALBEDO;
    g.spectralGpu      = caps.gpuSpectral;
    g.profileIndex     = -1;   // populated by buildSceneArrays after conversion
    g.roughness        = 0.5f;
    g.metallic         = 0.f;
    g.ior              = 1.5f;
    g.transmission     = 0.f;
    g.clearcoat        = 0.f;
    g.clearcoatGloss   = 1.f;
    g.emissionIntensity = 0.f;
    g.specular         = 0.5f;
    g.specularTint     = 0.f;
    g.sheen            = 0.f;
    g.sheenTint        = 0.5f;
    g.subsurface       = 0.f;
    g.anisotropic      = 0.f;
    g.anisotropicRotation = 0.f;
    g.isDispersive     = false;
    g.dispersion       = GDispersion{0.f, 0.f, 0.f, 0.f, 0.f, 0.f};

    astroray::MaterialClosureGraph graph = mat->closureGraph();
    std::string graphReason;
    if (!graph.empty() && astroray::validateClosureGraph(graph, &graphReason)) {
        g.type = GMAT_CLOSURE_GRAPH;
        g.spectralMode = GSPEC_RGB_ALBEDO;
        Vec3 a = mat->getAlbedo();
        g.baseColor = GVec3(a.x, a.y, a.z);
        g.roughness = mat->getRoughness();
        g.ior = mat->getIOR();
        g.transmission = mat->getTransmission();
        g.closureCount = static_cast<uint8_t>(
            std::min(graph.count(), G_MAX_MATERIAL_CLOSURES));

        for (int i = 0; i < g.closureCount; ++i) {
            const astroray::MaterialClosure& c = graph.closure(i);
            GMaterialClosure gc{};
            gc.type = convertClosureType(c.type);
            gc.twoSidedEmission = c.twoSidedEmission ? 1 : 0;
            gc.color = GVec3(c.color.x, c.color.y, c.color.z);
            gc.weight = c.weight;
            gc.roughness = c.roughness;
            gc.metallic = c.metallic;
            gc.ior = c.ior;
            gc.transmission = c.transmission;
            gc.clearcoatGloss = c.clearcoatGloss;
            g.closures[i] = gc;
        }
        return g;
    }

    std::string gpuType = caps.gpuType.empty() ? mat->getGPUTypeName() : caps.gpuType;
    if (gpuType == "disney") {
        g.type = GMAT_DISNEY;
        g.spectralMode = GSPEC_RGB_ALBEDO;
        Vec3 a = mat->getAlbedo();
        g.baseColor = GVec3(a.x, a.y, a.z);
        g.roughness = mat->getRoughness();
        g.metallic = mat->getMetallic();
        g.ior = mat->getIOR();
        g.transmission = mat->getTransmission();
        g.clearcoat = mat->getClearcoat();
        g.clearcoatGloss = mat->getClearcoatGloss();
        g.specular = mat->getSpecular();
        g.specularTint = mat->getSpecularTint();
        g.sheen = mat->getSheen();
        g.sheenTint = mat->getSheenTint();
        g.subsurface = mat->getSubsurface();
        g.anisotropic = mat->getAnisotropic();
        g.anisotropicRotation = mat->getAnisotropicRotation();
    } else if (gpuType == "metal") {
        g.type = GMAT_METAL;
        g.spectralMode = GSPEC_RGB_ALBEDO;
        Vec3 a = mat->getAlbedo();
        g.baseColor = GVec3(a.x, a.y, a.z);
        g.roughness = mat->getRoughness();
    } else if (gpuType == "dielectric") {
        g.type = GMAT_DIELECTRIC;
        g.spectralMode = GSPEC_RGB_ALBEDO;
        g.baseColor = GVec3(1.f);
        g.ior = mat->getIOR();
        // pkg64-gpu-sellmeier-upload: populate Sellmeier dispersion if present
        if (mat->isDispersive()) {
            Vec3 B = mat->getSellmeierB();
            Vec3 C = mat->getSellmeierC();
            g.dispersion.b1 = B.x; g.dispersion.b2 = B.y; g.dispersion.b3 = B.z;
            g.dispersion.c1 = C.x; g.dispersion.c2 = C.y; g.dispersion.c3 = C.z;
            g.isDispersive = true;
        }
    } else if (gpuType == "thin_glass") {
        g.type = GMAT_THIN_GLASS;
        g.spectralMode = GSPEC_RGB_ALBEDO;
        Vec3 a = mat->getAlbedo();
        g.baseColor = GVec3(a.x, a.y, a.z);
        g.ior = mat->getIOR();
        g.roughness = mat->getRoughness();
        g.transmission = mat->getTransmission();
    } else if (gpuType == "lambertian") {
        g.type = GMAT_LAMBERTIAN;
        g.spectralMode = GSPEC_RGB_ALBEDO;
        Vec3 a = mat->getAlbedo();
        g.baseColor = GVec3(a.x, a.y, a.z);
    } else if (gpuType == "diffuse_light") {
        g.type = GMAT_DIFFUSE_LIGHT;
        g.spectralMode = GSPEC_RGB_ILLUMINANT;
        Vec3 em = mat->getEmission();
        // Store color and intensity separately: emissionIntensity=1, baseColor=full emission
        g.baseColor = GVec3(em.x, em.y, em.z);
        g.emissionIntensity = 1.f;
    } else {
        throw std::runtime_error("Material declares unsupported GPU type: " + gpuType);
    }
    return g;
}

// ---------------------------------------------------------------------------
// Public entry point called from cuda_renderer.cu (struct defined in gpu_scene_upload.h)
// ---------------------------------------------------------------------------

// Builds host-side flat arrays from the CPU Renderer + Camera.
// The caller (cuda_renderer.cu) then cudaMalloc/cudaMemcpy them.
SceneUploadResult buildSceneArrays(const Renderer& cpu, const Camera* cam) {
    SceneUploadResult r;

    // --- Camera (optional in pkg56 Phase B; the per-domain materials /
    // lights / environment uploaders pass nullptr because they don't need
    // to republish the camera state to the device on a non-geometry edit).
    if (cam) {
        Vec3 o   = cam->getOrigin();
        Vec3 ll  = cam->getLowerLeft();
        Vec3 h   = cam->getHorizontal();
        Vec3 v   = cam->getVertical();
        Vec3 cu  = cam->getU();
        Vec3 cv  = cam->getV();
        r.camera.origin     = GVec3(o.x,  o.y,  o.z);
        r.camera.lowerLeft  = GVec3(ll.x, ll.y, ll.z);
        r.camera.horizontal = GVec3(h.x,  h.y,  h.z);
        r.camera.vertical   = GVec3(v.x,  v.y,  v.z);
        r.camera.u          = GVec3(cu.x, cu.y, cu.z);
        r.camera.v          = GVec3(cv.x, cv.y, cv.z);
        r.camera.lensRadius = cam->getLensRadius();
        r.camera.width      = cam->width;
        r.camera.height     = cam->height;

        // pkg88-A: upload motion blur shutter keyframes (T/R/S decomposed)
        Vec3 startT = cam->getShutterStartT();
        Vec3 endT   = cam->getShutterEndT();
        Quaternion startR = cam->getShutterStartR();
        Quaternion endR   = cam->getShutterEndR();
        Vec3 startS = cam->getShutterStartS();
        Vec3 endS   = cam->getShutterEndS();
        r.camera.shutterStartT = GVec3(startT.x, startT.y, startT.z);
        r.camera.shutterEndT   = GVec3(endT.x, endT.y, endT.z);
        r.camera.shutterStartR[0] = startR.w; r.camera.shutterStartR[1] = startR.x;
        r.camera.shutterStartR[2] = startR.y; r.camera.shutterStartR[3] = startR.z;
        r.camera.shutterEndR[0] = endR.w; r.camera.shutterEndR[1] = endR.x;
        r.camera.shutterEndR[2] = endR.y; r.camera.shutterEndR[3] = endR.z;
        r.camera.shutterStartS = GVec3(startS.x, startS.y, startS.z);
        r.camera.shutterEndS   = GVec3(endS.x, endS.y, endS.z);
        r.camera.shutter = cam->getShutter();
        r.camera.shutterPosition = static_cast<int>(cam->getShutterPosition());
        r.camera.vw = cam->getVw();
        r.camera.vh = cam->getVh();
        r.camera.focusDist = cam->getFocusDist();
        r.camera.shiftX = cam->getShiftX();
        r.camera.shiftY = cam->getShiftY();
    }

    // --- BVH nodes ---
    auto& cpuBvh = cpu.getBVH();
    if (!cpuBvh) throw std::runtime_error("BVH not built — call buildAcceleration() first");
    for (auto& n : cpuBvh->getNodes())
        r.nodes.push_back(convertNode(n));

    // --- Materials: build a unique ID per shared_ptr ---
    // Walk ordered primitives from BVH to collect materials.
    std::unordered_map<Material*, int> matIdx;
    auto getOrAddMat = [&](const std::shared_ptr<Material>& m) -> int {
        auto it = matIdx.find(m.get());
        if (it != matIdx.end()) return it->second;
        int id = (int)r.materials.size();
        matIdx[m.get()] = id;
        r.materials.push_back(convertMaterial(m));
        return id;
    };

    // --- Primitives (ordered as BVH expects) ---
    auto& orderedPrims = cpuBvh->getPrimitives();
    for (auto& hittable : orderedPrims) {
        GPrimitive gp;
        if (auto* tri = dynamic_cast<Triangle*>(hittable.get())) {
            gp.type  = GPRIM_TRIANGLE;
            gp.index = (int)r.triangles.size();
            GTriangle gt;
            Vec3 v0 = tri->getV0(), v1 = tri->getV1(), v2 = tri->getV2();
            Vec3 n = tri->getFaceNormal();
            gt.v0 = GVec3(v0.x, v0.y, v0.z);
            gt.v1 = GVec3(v1.x, v1.y, v1.z);
            gt.v2 = GVec3(v2.x, v2.y, v2.z);
            Vec3 n0, n1, n2;
            if (tri->getVertexNormals(n0, n1, n2)) {
                gt.n0 = GVec3(n0.x, n0.y, n0.z);
                gt.n1 = GVec3(n1.x, n1.y, n1.z);
                gt.n2 = GVec3(n2.x, n2.y, n2.z);
                gt.flat_shaded = false;  // per-vertex normals present
            } else {
                gt.n0 = gt.n1 = gt.n2 = GVec3(n.x, n.y, n.z);
                gt.flat_shaded = true;   // n0==n1==n2, shortcut eligible
            }
            gt.materialId = getOrAddMat(tri->getMaterial());
            // pkg87a — Cryptomatte: hash object and material names
            std::string objName = tri->getName();
            if (objName.empty()) objName = "Unnamed_Triangle_" + std::to_string(r.triangles.size());
            MurmurHash3_x86_32(objName.c_str(), static_cast<int>(objName.length()), 0, &gt.objectHash);
            std::string matName = tri->getMaterial()->getName();
            if (matName.empty()) matName = "Unnamed_Material_" + std::to_string(gt.materialId);
            MurmurHash3_x86_32(matName.c_str(), static_cast<int>(matName.length()), 0, &gt.materialHash);
            r.triangles.push_back(gt);
        } else if (auto* sph = dynamic_cast<Sphere*>(hittable.get())) {
            gp.type  = GPRIM_SPHERE;
            gp.index = (int)r.spheres.size();
            GSphere gs;
            Vec3 c = sph->getCenter();
            gs.center     = GVec3(c.x, c.y, c.z);
            gs.radius     = sph->getRadius();
            gs.materialId = getOrAddMat(sph->getMaterial());
            // pkg64-gpu Phase 1 — mirror the CPU per-object caustic-caster
            // opt-in (Hittable::isCausticCaster, set via
            // Renderer::setObjectCausticCaster / the
            // set_object_caustic_caster binding) across the GPU scene
            // boundary so the megakernel SMS dispatch (Phase 2) gates on
            // the same flag as the CPU path.
            gs.isCausticCaster = sph->isCausticCaster();
            // pkg87a — Cryptomatte: hash object and material names
            std::string objName = sph->getName();
            if (objName.empty()) objName = "Unnamed_Sphere_" + std::to_string(r.spheres.size());
            MurmurHash3_x86_32(objName.c_str(), static_cast<int>(objName.length()), 0, &gs.objectHash);
            std::string matName = sph->getMaterial()->getName();
            if (matName.empty()) matName = "Unnamed_Material_" + std::to_string(gs.materialId);
            MurmurHash3_x86_32(matName.c_str(), static_cast<int>(matName.length()), 0, &gs.materialHash);
            r.spheres.push_back(gs);

            // pkg64-gpu Phase 2: gather caustic-caster spheres inline.
            // Check if this sphere is flagged + transmissive + IOR > 1.
            if (gs.isCausticCaster) {
                const auto& mat = sph->getMaterial();
                if (mat && mat->isTransmissive()) {
                    float ior = mat->getIOR();
                    if (ior > 1.0f) {
                        // primId is the index into r.prims that will be assigned next.
                        int primIdx = (int)orderedPrims.size() - 1;
                        astroray::manifold::device::GSMSCaster gc;
                        gc.center = gs.center;
                        gc.radius = gs.radius;
                        gc.primId = primIdx;
                        r.smsCasters.push_back(gc);
                    }
                }
            }
        } else {
            // pkg85-C: keep r.prims index-aligned with the BVH's orderedPrims
            // by pushing a GPRIM_SKIP placeholder for non-{Triangle,Sphere}
            // primitives (e.g., DistantLight). Without this, BVH leaves
            // built from a 2-prim CPU scene whose centroids collide can
            // produce a single leaf with nPrimitives=2, and gpu_bvh_hit
            // reads prims[1] past the end of the uploaded r.prims array,
            // crashing the path-trace kernel with cudaErrorIllegalAddress.
            gp.type  = GPRIM_SKIP;
            gp.index = -1;
        }
        r.prims.push_back(gp);
    }

    // --- Lights ---
    const LightList& ll2 = cpu.getLights();
    const auto& lightPtrs  = ll2.getLights();
    const auto& powerDist  = ll2.getPowerDist();
    r.totalLightPower      = ll2.getTotalPower();

    // Find each light's primitive index in r.prims
    for (size_t i = 0; i < lightPtrs.size(); ++i) {
        // Search ordered primitives for matching raw pointer
        int primIdx = -1;
        for (size_t j = 0; j < orderedPrims.size(); ++j) {
            if (orderedPrims[j].get() == lightPtrs[i].get()) {
                primIdx = (int)j; break;
            }
        }
        GLight gl;
        gl.primitiveIndex = primIdx;
        float prev = (i == 0) ? 0.f : powerDist[i-1];
        gl.power          = powerDist[i] - prev;
        gl.cumulativePower = powerDist[i];
        r.lights.push_back(gl);

        // pkg55-B' Session N+4: populate GAreaLight for wavefront NEE
        // For Session N+4 (Lambertian-only Cornell), we assume each light is a single
        // triangle emitter. Extract vertices + emission from the Triangle primitive.
        if (primIdx >= 0 && primIdx < (int)r.prims.size()) {
            const GPrimitive& gp = r.prims[primIdx];
            if (gp.type == GPRIM_TRIANGLE) {
                const GTriangle& tri = r.triangles[gp.index];
                GAreaLight al;
                al.v0 = tri.v0;
                al.v1 = tri.v1;
                al.v2 = tri.v2;
                al.normal = tri.n0;  // flat shading: use first normal (all equal for flat tri)
                // Emission: get from material
                if (tri.materialId >= 0 && tri.materialId < (int)r.materials.size()) {
                    const GMaterial& mat = r.materials[tri.materialId];
                    al.emission = GVec3(mat.baseColor.x * mat.emissionIntensity,
                                        mat.baseColor.y * mat.emissionIntensity,
                                        mat.baseColor.z * mat.emissionIntensity);
                } else {
                    al.emission = GVec3(0, 0, 0);
                }
                al.power = gl.power;  // copy from GLight
                r.areaLights.push_back(al);
            }
        }
    }

    // (pkg64-gpu Phase 2 caster gathering moved inline during sphere loop above)

    // --- pkg54a: Spectral profile table for the multi-wavelength kernel ---
    // Walk uploaded materials in order; assign each a profileIndex if its CPU
    // counterpart carries a non-null SpectralProfile. Profiles are deduplicated
    // by pointer (the CPU SpectralProfileDatabase is the single owner) and
    // resampled onto the fixed [G_PROFILE_LAMBDA_MIN, _MAX] @ _STEP grid.
    {
        std::unordered_map<const astroray::SpectralProfile*, int> profIdx;
        // matIdx maps Material* → uploaded GMaterial index. Walk it to attach
        // profile indices in the correct slot.
        for (auto& kv : matIdx) {
            const Material* cpuMat = kv.first;
            int gMatId             = kv.second;
            const astroray::SpectralProfile* prof = cpuMat->getSpectralProfile();
            if (!prof || !prof->valid()) continue;

            auto it = profIdx.find(prof);
            int idx;
            if (it == profIdx.end()) {
                if ((int)profIdx.size() >= G_MAX_PROFILES) {
                    fprintf(stderr,
                            "[CUDA] WARNING: more than %d unique spectral profiles; "
                            "extra profiles will not dispatch on GPU\n",
                            G_MAX_PROFILES);
                    continue;
                }
                idx = (int)profIdx.size();
                profIdx[prof] = idx;
                // Resample onto the GPU grid.
                size_t baseOffset = r.profileTable.size();
                r.profileTable.resize(baseOffset + G_PROFILE_SAMPLES);
                for (int s = 0; s < G_PROFILE_SAMPLES; ++s) {
                    float lam = G_PROFILE_LAMBDA_MIN + s * G_PROFILE_LAMBDA_STEP;
                    r.profileTable[baseOffset + s] = prof->reflectance(lam);
                }
            } else {
                idx = it->second;
            }
            r.materials[gMatId].profileIndex = idx;
        }
        r.profileCount = (int)profIdx.size();
    }

    // --- Environment map ---
    auto& em = cpu.getEnvironmentMap();
    if (em && em->loaded()) {
        r.envLoaded     = true;
        r.envWidth      = em->getWidth();
        r.envHeight     = em->getHeight();
        r.envStrength   = em->getStrength();
        // pkg63: copy baked rotation matrix + color tint instead of single rotation float.
        std::memcpy(r.envRotMat, em->getRotationMatrix(), 9 * sizeof(float));
        std::memcpy(r.envColorTint, em->getColorTint(), 3 * sizeof(float));
        r.envTotalPower = em->getTotalPower();
        r.envData       = em->getData();
        r.envCondCdf    = em->getConditionalCdf();
        r.envCondFunc   = em->getConditionalFunc();
        r.envMargCdf    = em->getMarginalCdf();
        r.envMargFunc   = em->getMarginalFunc();
    }

    return r;
}
