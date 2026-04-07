// scene_upload.cu — Host → Device scene transfer for CUDARenderer.
// Converts CPU scene data (BVH nodes, triangles, spheres, materials, lights,
// env map) into flat GPU arrays via cudaMalloc / cudaMemcpy.

#include "astroray/gpu_types.h"
#include "raytracer.h"
#include "advanced_features.h"

#include <cuda_runtime.h>
#include <vector>
#include <memory>
#include <cstdio>
#include <stdexcept>

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
static GMaterial convertMaterial(const std::shared_ptr<Material>& mat) {
    GMaterial g{};
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

    if (auto* l = dynamic_cast<Lambertian*>(mat.get())) {
        g.type = GMAT_LAMBERTIAN;
        Vec3 a = l->getAlbedo();
        g.baseColor = GVec3(a.x, a.y, a.z);
    } else if (auto* dl = dynamic_cast<DiffuseLight*>(mat.get())) {
        g.type = GMAT_DIFFUSE_LIGHT;
        Vec3 em = dl->getEmission();
        // Store color and intensity separately: emissionIntensity=1, baseColor=full emission
        g.baseColor = GVec3(em.x, em.y, em.z);
        g.emissionIntensity = 1.f;
    } else if (auto* dis = dynamic_cast<DisneyBRDF*>(mat.get())) {
        g.type          = GMAT_DISNEY;
        Vec3 bc         = dis->getBaseColor();
        g.baseColor     = GVec3(bc.x, bc.y, bc.z);
        g.roughness     = dis->getRoughness();
        g.metallic      = dis->getMetallic();
        g.ior           = dis->getIOR();
        g.transmission  = dis->getTransmission();
        g.clearcoat     = dis->getClearcoat();
        g.clearcoatGloss = dis->getClearcoatGloss();
        g.specular      = dis->getSpecular();
        g.specularTint  = dis->getSpecularTint();
        g.sheen         = dis->getSheen();
        g.sheenTint     = dis->getSheenTint();
        g.subsurface    = dis->getSubsurface();
        g.anisotropic   = dis->getAnisotropic();
        g.anisotropicRotation = dis->getAnisotropicRotation();
    } else if (auto* m = dynamic_cast<Metal*>(mat.get())) {
        g.type = GMAT_METAL;
        Vec3 a = m->getAlbedo();
        g.baseColor = GVec3(a.x, a.y, a.z);
        g.roughness = m->getRoughness();
    } else if (auto* d = dynamic_cast<Dielectric*>(mat.get())) {
        g.type = GMAT_DIELECTRIC;
        g.baseColor = GVec3(1.f);
        g.ior = d->getIOR();
    } else {
        // Unknown: treat as grey Lambertian
        g.type = GMAT_LAMBERTIAN;
        g.baseColor = GVec3(0.5f);
    }
    return g;
}

// ---------------------------------------------------------------------------
// Public entry point called from cuda_renderer.cu
// ---------------------------------------------------------------------------
struct SceneUploadResult {
    std::vector<GBVHNode>   nodes;
    std::vector<GPrimitive> prims;
    std::vector<GTriangle>  triangles;
    std::vector<GSphere>    spheres;
    std::vector<GMaterial>  materials;
    std::vector<GLight>     lights;
    float totalLightPower;

    // Camera
    GCameraParams camera;

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

// Builds host-side flat arrays from the CPU Renderer + Camera.
// The caller (cuda_renderer.cu) then cudaMalloc/cudaMemcpy them.
SceneUploadResult buildSceneArrays(const Renderer& cpu, const Camera& cam) {
    SceneUploadResult r;

    // --- Camera ---
    Vec3 o   = cam.getOrigin();
    Vec3 ll  = cam.getLowerLeft();
    Vec3 h   = cam.getHorizontal();
    Vec3 v   = cam.getVertical();
    Vec3 cu  = cam.getU();
    Vec3 cv  = cam.getV();
    r.camera.origin     = GVec3(o.x,  o.y,  o.z);
    r.camera.lowerLeft  = GVec3(ll.x, ll.y, ll.z);
    r.camera.horizontal = GVec3(h.x,  h.y,  h.z);
    r.camera.vertical   = GVec3(v.x,  v.y,  v.z);
    r.camera.u          = GVec3(cu.x, cu.y, cu.z);
    r.camera.v          = GVec3(cv.x, cv.y, cv.z);
    r.camera.lensRadius = cam.getLensRadius();
    r.camera.width      = cam.width;
    r.camera.height     = cam.height;

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
            gt.n0 = gt.n1 = gt.n2 = GVec3(n.x, n.y, n.z);
            gt.materialId = getOrAddMat(tri->getMaterial());
            r.triangles.push_back(gt);
        } else if (auto* sph = dynamic_cast<Sphere*>(hittable.get())) {
            gp.type  = GPRIM_SPHERE;
            gp.index = (int)r.spheres.size();
            GSphere gs;
            Vec3 c = sph->getCenter();
            gs.center     = GVec3(c.x, c.y, c.z);
            gs.radius     = sph->getRadius();
            gs.materialId = getOrAddMat(sph->getMaterial());
            r.spheres.push_back(gs);
        } else {
            // Skip unknown types (BVHAccel, etc.)
            continue;
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
    }

    // --- Environment map ---
    auto& em = cpu.getEnvironmentMap();
    if (em && em->loaded()) {
        r.envLoaded     = true;
        r.envWidth      = em->getWidth();
        r.envHeight     = em->getHeight();
        r.envStrength   = em->getStrength();
        r.envRotation   = em->getRotation();
        r.envTotalPower = em->getTotalPower();
        r.envData       = em->getData();
        r.envCondCdf    = em->getConditionalCdf();
        r.envCondFunc   = em->getConditionalFunc();
        r.envMargCdf    = em->getMarginalCdf();
        r.envMargFunc   = em->getMarginalFunc();
    }

    return r;
}
