// scene_upload.cu — Host → Device scene transfer for CUDARenderer.
// Converts CPU scene data (BVH nodes, triangles, spheres, materials, lights,
// env map) into flat GPU arrays via cudaMalloc / cudaMemcpy.

#include "astroray/gpu_scene_upload.h"
#include "astroray/gpu_types.h"
#include "astroray/shapes.h"
#include "astroray/spectral_profile.h"
#include "raytracer.h"
#include "astroray/light_tree.h"   // pkg86-B: LightTree flattening (needs raytracer.h's Vec3/AABB)
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
#include <cmath>
#include <functional>
#include <stdexcept>
#include <unordered_map>
#include <array>

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
        case astroray::MaterialClosureType::Principled: return GCLOSURE_PRINCIPLED;  // pkg178 Stage 2
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
        // pkg108 BUG-16: the diffuse closure applies the Hanrahan-Krueger
        // subsurface mix (gpu_lambertian_eval); carry the weight across.
        g.subsurface = mat->getSubsurface();
        // pkg141: stamp the native plugin type so gpu_closure_as_material's
        // GCLOSURE_GGX_CONDUCTOR case (gpu_materials.h) can tell a
        // DisneyPlugin-originated conductor lobe (continuous alpha-floored
        // GGX, no near-delta shortcut) apart from a MetalPlugin-originated
        // one (legitimate near-delta perfect-mirror shortcut) -- see the
        // GMaterial::disneyMetalConductor comment in gpu_types.h. Reads the
        // already-public Material::getGPUTypeName(); does not touch
        // plugins/materials/disney.cpp.
        g.disneyMetalConductor = (mat->getGPUTypeName() == "disney");
        // pkg187: dispersive Principled glass lowers to GMAT_CLOSURE_GRAPH, so the
        // dispersion flag/data must ride the closure-graph path too (the dielectric
        // branch below only fires for GMAT_DIELECTRIC). For the closure-graph path
        // GDispersion carries the OpenPBR Cauchy fit (b1=A, b2=B) -- NOT Sellmeier
        // coefficients -- read on device by gpu_cauchy_ior in the dispersive-
        // Principled spectral sampler. No new GMaterial fields: reuses the existing
        // isDispersive/dispersion members already copied by-value on every path.
        if (mat->isDispersive()) {
            Vec3 ab = mat->getCauchyAB();
            g.dispersion.b1 = ab.x;  // Cauchy A
            g.dispersion.b2 = ab.y;  // Cauchy B
            g.isDispersive = true;
        }
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
            // pkg178 Stage-3b perf: the Principled advanced params (Stage-2
            // specular* + Stage-3 coat/sheen/subsurface/emission) no longer ride
            // on every GMaterialClosure — that inflated closures[8] and the
            // by-value GMaterial temp on the shared non-Principled shade path.
            // A Principled material is a single GCLOSURE_PRINCIPLED closure, so
            // its advanced block is written ONCE into g.principled (read only by
            // the gpu_principled_* twin). See gpu_types.h.
            if (gc.type == GCLOSURE_PRINCIPLED) {
                GPrincipledClosure& gp = g.principled;
                gp.color = GVec3(c.color.x, c.color.y, c.color.z);
                gp.roughness = c.roughness;
                gp.metallic = c.metallic;
                gp.ior = c.ior;
                gp.transmission = c.transmission;
                gp.specularTint = GVec3(c.specularTint.x, c.specularTint.y, c.specularTint.z);
                gp.specularIorLevel = c.specularIorLevel;
                gp.diffuseRoughness = c.diffuseRoughness;
                gp.coatTint = GVec3(c.coatTint.x, c.coatTint.y, c.coatTint.z);
                gp.coatWeight = c.coatWeight;
                gp.coatRoughness = c.coatRoughness;
                gp.coatIor = c.coatIor;
                gp.sheenTint = GVec3(c.sheenTint.x, c.sheenTint.y, c.sheenTint.z);
                gp.sheenWeight = c.sheenWeight;
                gp.sheenRoughness = c.sheenRoughness;
                gp.subsurfaceRadius = GVec3(c.subsurfaceRadius.x, c.subsurfaceRadius.y, c.subsurfaceRadius.z);
                gp.subsurfaceWeight = c.subsurfaceWeight;
                gp.subsurfaceScale = c.subsurfaceScale;
                gp.emissionColor = GVec3(c.emissionColor.x, c.emissionColor.y, c.emissionColor.z);
                gp.emissionStrength = c.emissionStrength;
                gp.anisotropic = c.anisotropic;                 // pkg178 PR-4b
                gp.anisotropicRotation = c.anisotropicRotation;
                gp.alpha = c.alpha;                             // pkg178 PR-6
                // pkg178 Stage 4 PR-3 — thin-film iridescence params. Only the two
                // scalars are uploaded; the metallic-lobe conductor (n,k,g) are
                // recomputed ON-DEVICE per hit inside gpu_pr_thinFilmConductorRGB
                // (<true> only) rather than stored in GPrincipledClosure — storing
                // them inflated GMaterial and leaked +320 B STACK into the shared
                // non-principled <false> kernel via its by-value copy. See the
                // GPrincipledClosure comment in gpu_types.h.
                gp.thinFilmThickness = c.thinFilmThickness;
                gp.thinFilmIor = c.thinFilmIor;
                // pkg178 Stage 4 PR-4 — thin_wall + subsurface_anisotropy packed into
                // ONE float to keep GMaterial at 640 B (a second field rounds it to
                // 704 B and leaks +STACK into the shared <false> by-value copy; see
                // GPrincipledClosure comment). thin_wall=false → -8 sentinel.
                gp.thinWallAniso = c.thinWall ? c.subsurfaceAnisotropy : -8.f;
            }
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
// Convert ONE CPU Hittable (Triangle/Sphere) → GPrimitive (+ GTriangle/GSphere)
// appended to the target arrays. Factored from the single-level prim walk so
// the per-mesh BLAS (pkg114) reuses the identical conversion. Materials are
// deduplicated via getOrAddMat. NOTE: does NOT do pkg64 SMS-caster gathering —
// that stays in the single-level walk (SMS is not instancing-aware yet).
// ---------------------------------------------------------------------------
static void appendOnePrim(
    const std::shared_ptr<Hittable>& hittable, SceneUploadResult& r,
    const std::function<int(const std::shared_ptr<Material>&)>& getOrAddMat)
{
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
            gt.flat_shaded = false;
        } else {
            gt.n0 = gt.n1 = gt.n2 = GVec3(n.x, n.y, n.z);
            gt.flat_shaded = true;
        }
        gt.materialId = getOrAddMat(tri->getMaterial());
        // pkg178 Stage-3b PR-4b — upload the active-UV-layer texcoords ONLY when
        // the triangle's material is an anisotropic Principled AND it carries a UV
        // parameterization. hasUV gates the device UV-tangent computation, so
        // non-aniso scenes leave every triangle hasUV=false → zero shade cost and
        // zero UV upload (memory is the GTriangle field footprint only).
        {
            const auto& mtl = tri->getMaterial();
            // pkg178 aniso-Principled UV-tangent OR pkg186 image-textured
            // lambertian both need the active-layer UVs on the device. hasUV
            // stays false (zero shade cost / zero upload) for every other
            // triangle. The two consumers are independent branches in the shade
            // kernel (HasPrincipled aniso-tangent vs HasTexture image fetch).
            const bool anisoPrincipled =
                mtl && mtl->getGPUTypeName() == "principled" &&
                mtl->getAnisotropic() > 0.0f;
            const bool imageTextured =
                mtl && dynamic_cast<TexturedLambertian*>(mtl.get()) != nullptr;
            if ((anisoPrincipled || imageTextured) && tri->hasUVLayers()) {
                Vec2 t0 = tri->getUV0(), t1 = tri->getUV1(), t2 = tri->getUV2();
                gt.uv0 = GVec2(t0.u, t0.v);
                gt.uv1 = GVec2(t1.u, t1.v);
                gt.uv2 = GVec2(t2.u, t2.v);
                gt.hasUV = true;
            }
        }
        // pkg88-C.0: defaults — the BVH primitive walk in buildSceneArrays
        // resolves real offsets for motion triangles via motionPtrToOffset
        // (per-batch stable pointers; see Renderer::motionVertexBatches_).
        gt.motionOffset = -1;
        gt.motionSteps = 1;
        r.triangles.push_back(gt);
        std::string objName = tri->getName();
        if (objName.empty()) objName = "Unnamed_Triangle_" + std::to_string(r.triangles.size() - 1);
        MurmurHash3_x86_32(objName.c_str(), static_cast<int>(objName.length()), 0, &r.triangles.back().objectHash);
        std::string matName = tri->getMaterial()->getName();
        if (matName.empty()) matName = "Unnamed_Material_" + std::to_string(gt.materialId);
        MurmurHash3_x86_32(matName.c_str(), static_cast<int>(matName.length()), 0, &r.triangles.back().materialHash);
    } else if (auto* sph = dynamic_cast<Sphere*>(hittable.get())) {
        gp.type  = GPRIM_SPHERE;
        gp.index = (int)r.spheres.size();
        GSphere gs;
        Vec3 c = sph->getCenter();
        gs.center     = GVec3(c.x, c.y, c.z);
        gs.radius     = sph->getRadius();
        gs.materialId = getOrAddMat(sph->getMaterial());
        gs.isCausticCaster = sph->isCausticCaster();
        std::string objName = sph->getName();
        if (objName.empty()) objName = "Unnamed_Sphere_" + std::to_string(r.spheres.size());
        MurmurHash3_x86_32(objName.c_str(), static_cast<int>(objName.length()), 0, &gs.objectHash);
        std::string matName = sph->getMaterial()->getName();
        if (matName.empty()) matName = "Unnamed_Material_" + std::to_string(gs.materialId);
        MurmurHash3_x86_32(matName.c_str(), static_cast<int>(matName.length()), 0, &gs.materialHash);
        r.spheres.push_back(gs);
    } else {
        // pkg85-C: GPRIM_SKIP placeholder keeps prims index-aligned within a BLAS.
        gp.type  = GPRIM_SKIP;
        gp.index = -1;
    }
    r.prims.push_back(gp);
}

// ---------------------------------------------------------------------------
// pkg114 — invert a row-major affine 4x4 (assumes last row [0,0,0,1]). Returns
// false if the upper-left 3x3 is singular (|det| < 1e-12). Inverse of an affine
// is [[R^-1, -R^-1 t]] (standard; used to map the world ray into object space).
// ---------------------------------------------------------------------------
static bool affineInverse4x4(const float M[16], float Minv[16]) {
    float a=M[0], b=M[1], c=M[2];
    float d=M[4], e=M[5], f=M[6];
    float g=M[8], h=M[9], i=M[10];
    float A =  (e*i - f*h);
    float B = -(d*i - f*g);
    float C =  (d*h - e*g);
    float det = a*A + b*B + c*C;
    if (std::fabs(det) < 1e-12f) return false;
    float invDet = 1.0f / det;
    float r00 =  A*invDet;
    float r01 = -(b*i - c*h)*invDet;
    float r02 =  (b*f - c*e)*invDet;
    float r10 =  B*invDet;
    float r11 =  (a*i - c*g)*invDet;
    float r12 = -(a*f - c*d)*invDet;
    float r20 =  C*invDet;
    float r21 = -(a*h - b*g)*invDet;
    float r22 =  (a*e - b*d)*invDet;
    float tx=M[3], ty=M[7], tz=M[11];
    Minv[0]=r00; Minv[1]=r01; Minv[2]=r02;  Minv[3]=-(r00*tx + r01*ty + r02*tz);
    Minv[4]=r10; Minv[5]=r11; Minv[6]=r12;  Minv[7]=-(r10*tx + r11*ty + r12*tz);
    Minv[8]=r20; Minv[9]=r21; Minv[10]=r22; Minv[11]=-(r20*tx + r21*ty + r22*tz);
    Minv[12]=0;  Minv[13]=0;  Minv[14]=0;   Minv[15]=1;
    return true;
}

// ---------------------------------------------------------------------------
// pkg114 — build the two-level (TLAS-over-BLAS) GPU arrays from the Renderer's
// registered meshes + instances. Each unique mesh's BLAS nodes + OBJECT-LOCAL
// prims are concatenated into the global r.nodes/r.prims/r.triangles/r.spheres
// (each BLAS flattened independently from node 0; r.blas[m] records the offsets).
// Instances carry M (object->world) + Minv; the TLAS is a single flat leaf over
// all instances (a SAH TLAS is a later perf win — a flat leaf is correct).
// ---------------------------------------------------------------------------
// Append the non-instanced "flat" scene (cpu.getBVH()) into r.nodes/prims with
// pkg88 motion-offset wiring + pkg64 SMS caster gather. Shared by the single-
// level path and the pkg114 MIXED path (where the flat scene is wrapped as an
// identity-transform BLAS so it coexists with instanced meshes). Callers append
// it FIRST (node/prim offset 0) so the pkg64 SMS primIdx convention and the
// light emitter→prim search (both keyed on the ordered-prim index) stay valid.
// Returns the number of ordered prims appended (0 if the flat scene is empty).
static size_t appendFlatScene(
    const Renderer& cpu, const BVHAccel* cpuBvh, SceneUploadResult& r,
    const std::function<int(const std::shared_ptr<Material>&)>& getOrAddMat)
{
    if (!cpuBvh) return 0;
    for (auto& n : cpuBvh->getNodes())
        r.nodes.push_back(convertNode(n));
    const auto& orderedPrims = cpuBvh->getPrimitives();
    // pkg88-C.0: map CPU Triangle motion pointers → offsets in the concatenated
    // GPU buffer (stable per-batch pointers; pkg98 review fix).
    std::unordered_map<const Vec3*, size_t> motionPtrToOffset;
    {
        size_t batchBase = 0;
        for (const auto& batch : cpu.getMotionVertexBatches()) {
            for (size_t i = 0; i < batch.size(); ++i)
                motionPtrToOffset[batch.data() + i] = batchBase + i;
            batchBase += batch.size();
        }
    }
    for (auto& hittable : orderedPrims) {
        appendOnePrim(hittable, r, getOrAddMat);
        if (auto* tri = dynamic_cast<Triangle*>(hittable.get())) {
            const Vec3* motionBuf = tri->getMotionVertexBuffer();
            if (motionBuf != nullptr) {
                auto it = motionPtrToOffset.find(motionBuf);
                if (it != motionPtrToOffset.end()) {
                    r.triangles.back().motionOffset = static_cast<int>(it->second);
                    r.triangles.back().motionSteps = tri->getMotionSteps();
                }
            }
        }
        // pkg64-gpu Phase 2: gather caustic-caster spheres inline (single-level
        // only — SMS is not instancing-aware). primIdx preserves the prior
        // (orderedPrims.size()-1) convention to keep pkg64 acceptance stable.
        if (auto* sph = dynamic_cast<Sphere*>(hittable.get())) {
            const GSphere& gs = r.spheres.back();
            if (gs.isCausticCaster) {
                const auto& mat = sph->getMaterial();
                if (mat && mat->isTransmissive()) {
                    float ior = mat->getIOR();
                    if (ior > 1.0f) {
                        int primIdx = (int)orderedPrims.size() - 1;
                        astroray::manifold::device::GSMSCaster gc;
                        gc.center = gs.center;
                        gc.radius = gs.radius;
                        gc.primId = primIdx;
                        r.smsCasters.push_back(gc);
                    }
                }
            }
        }
    }
    return orderedPrims.size();
}

// Merge an object-space AABB transformed by a row-major 4x4 into tlasBounds.
static void mergeWorldAABB(const float* M, const AABB& lb,
                           AABB& tlasBounds, bool& haveBounds) {
    for (int cx = 0; cx < 2; ++cx)
    for (int cy = 0; cy < 2; ++cy)
    for (int cz = 0; cz < 2; ++cz) {
        float x = cx ? lb.max.x : lb.min.x;
        float y = cy ? lb.max.y : lb.min.y;
        float z = cz ? lb.max.z : lb.min.z;
        Vec3 w(M[0]*x + M[1]*y + M[2]*z + M[3],
               M[4]*x + M[5]*y + M[6]*z + M[7],
               M[8]*x + M[9]*y + M[10]*z + M[11]);
        if (!haveBounds) { tlasBounds = AABB(w, w); haveBounds = true; }
        else tlasBounds = tlasBounds.merge(AABB(w, w));
    }
}

// Build r.instances + r.tlas from the CPU instance list + per-mesh local bounds.
// Shared by the full geometry build (buildTwoLevelArrays) and the pkg114 inc 3d
// TLAS-only refit (buildTlasArraysOnly) so a transform-only re-upload produces
// instances/TLAS byte-identical to a full rebuild. Does NOT touch nodes/prims/
// triangles/blas — pure transform + AABB work.
static void buildInstancesAndTlas(
    const Renderer& cpu, const std::vector<AABB>& meshLocalBounds,
    bool haveFlat, int flatBlasIndex, const AABB& flatBounds, SceneUploadResult& r)
{
    const auto& meshBlas  = cpu.getMeshBlas();
    const auto& instances = cpu.getInstances();

    AABB tlasBounds; bool haveBounds = false;
    r.instances.reserve(instances.size() + 1);
    for (size_t j = 0; j < instances.size(); ++j) {
        int meshId = instances[j].meshId;
        if (meshId < 0 || (size_t)meshId >= meshBlas.size()) continue;
        const float* M = instances[j].transform.data();
        float Minv[16];
        if (!affineInverse4x4(M, Minv)) {
            fprintf(stderr, "[pkg114] instance %zu has a singular transform; skipped\n", j);
            continue;
        }
        GInstance gi;
        for (int k = 0; k < 16; ++k) gi.worldFromObject.m[k] = M[k];
        for (int k = 0; k < 16; ++k) gi.objectFromWorld.m[k] = Minv[k];
        gi.blasIndex  = meshId;
        gi.instanceId = (int)r.instances.size();
        r.instances.push_back(gi);
        mergeWorldAABB(M, meshLocalBounds[meshId], tlasBounds, haveBounds);
    }

    // The flat scene as an identity-transform instance (world == object space).
    if (haveFlat) {
        static const float kIdentity[16] = {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
        GInstance gi;
        gi.worldFromObject = GMat4::identity();
        gi.objectFromWorld = GMat4::identity();
        gi.blasIndex  = flatBlasIndex;
        gi.instanceId = (int)r.instances.size();
        r.instances.push_back(gi);
        mergeWorldAABB(kIdentity, flatBounds, tlasBounds, haveBounds);
    }

    if (!r.instances.empty()) {
        GTLASNode leaf;
        leaf.bounds.min = GVec3(tlasBounds.min.x, tlasBounds.min.y, tlasBounds.min.z);
        leaf.bounds.max = GVec3(tlasBounds.max.x, tlasBounds.max.y, tlasBounds.max.z);
        leaf.primitivesOffset = 0;
        leaf.nPrimitives = (uint16_t)r.instances.size();
        leaf.axis = 0;
        leaf.pad  = 0;
        r.tlas.push_back(leaf);
    }
}

static void buildTwoLevelArrays(
    const Renderer& cpu, const BVHAccel* cpuBvh, SceneUploadResult& r,
    const std::function<int(const std::shared_ptr<Material>&)>& getOrAddMat)
{
    const auto& meshBlas  = cpu.getMeshBlas();

    // pkg114 inc 3b — MIXED scenes: the non-instanced "flat" scene is uploaded
    // FIRST (node/prim offset 0) and exposed to the device as ONE extra BLAS
    // reached through an IDENTITY-transform instance. The flat scene is then
    // "just another instance" and the existing gpu_tlas_hit traverses it
    // alongside the real instanced meshes (the inc-1 identity-parity test proved
    // the identity instance path is byte-exact). This is what lets a scene with
    // a static floor + instanced props render correctly; without it, enabling
    // any instance dropped all non-instanced geometry from the GPU upload.
    AABB flatBounds; bool haveFlat = false;
    int  flatBlasIndex = -1;
    if (cpuBvh && !cpuBvh->getPrimitives().empty()) {
        // nodeOffset/primOffset are 0 because the flat scene is appended first.
        appendFlatScene(cpu, cpuBvh, r, getOrAddMat);
        cpuBvh->boundingBox(flatBounds); haveFlat = true;
    }

    // Registered-mesh BLASes follow the flat scene; their offsets advance past it.
    std::vector<AABB> meshLocalBounds(meshBlas.size());
    r.blas.resize(meshBlas.size());
    for (size_t m = 0; m < meshBlas.size(); ++m) {
        r.blas[m].nodeOffset = (int)r.nodes.size();
        r.blas[m].primOffset = (int)r.prims.size();
        const auto& blasAccel = meshBlas[m];
        if (!blasAccel || blasAccel->getNodes().empty()) { meshLocalBounds[m] = AABB(); continue; }
        for (const auto& n : blasAccel->getNodes()) r.nodes.push_back(convertNode(n));
        for (const auto& hittable : blasAccel->getPrimitives()) appendOnePrim(hittable, r, getOrAddMat);
        AABB b; blasAccel->boundingBox(b); meshLocalBounds[m] = b;
    }
    // The flat scene's BLAS record (nodeOffset/primOffset 0) goes at the END so
    // real instance.blasIndex == meshId stays a direct index into r.blas[0..M).
    if (haveFlat) {
        GBLAS fb; fb.nodeOffset = 0; fb.primOffset = 0;
        flatBlasIndex = (int)r.blas.size();
        r.blas.push_back(fb);
    }

    buildInstancesAndTlas(cpu, meshLocalBounds, haveFlat, flatBlasIndex, flatBounds, r);
}

// pkg114 inc 3d — TLAS-only refit: rebuild ONLY r.instances + r.tlas from the
// current CPU instance transforms, WITHOUT re-walking any BLAS geometry. Per-mesh
// local bounds come from each cached BLAS's O(1) boundingBox() (the geometry on
// the device is unchanged), and the flat scene's identity-instance bounds from
// the scene BVH. The flat BLAS index matches the full build (it is appended last,
// at index == meshBlas.size()), so the device d_blas (untouched) still resolves.
static void buildTlasArraysOnly(const Renderer& cpu, const BVHAccel* cpuBvh,
                                SceneUploadResult& r)
{
    const auto& meshBlas = cpu.getMeshBlas();
    std::vector<AABB> meshLocalBounds(meshBlas.size());
    for (size_t m = 0; m < meshBlas.size(); ++m) {
        if (meshBlas[m] && !meshBlas[m]->getNodes().empty()) {
            AABB b; meshBlas[m]->boundingBox(b); meshLocalBounds[m] = b;
        } else {
            meshLocalBounds[m] = AABB();
        }
    }
    AABB flatBounds; bool haveFlat = false; int flatBlasIndex = -1;
    if (cpuBvh && !cpuBvh->getPrimitives().empty()) {
        cpuBvh->boundingBox(flatBounds);
        haveFlat = true;
        flatBlasIndex = (int)meshBlas.size();   // flat BLAS is appended last
    }
    buildInstancesAndTlas(cpu, meshLocalBounds, haveFlat, flatBlasIndex, flatBounds, r);
}

// Public entry for the TLAS-only refit (declared in gpu_scene_upload.h). Only
// r.tlas + r.instances are populated; the caller re-pushes just those two device
// buffers (cuda_renderer.cu CUDARenderer::uploadInstanceTransforms).
SceneUploadResult buildTlasOnly(const Renderer& cpu) {
    SceneUploadResult r;
    auto& cpuBvh = cpu.getBVH();
    buildTlasArraysOnly(cpu, cpuBvh.get(), r);
    return r;
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

    // --- Materials: unique ID per shared_ptr (shared by single-level + pkg114 instanced) ---
    std::unordered_map<Material*, int> matIdx;
    // pkg186 — texture dedup: one flat-buffer slice per unique image Texture*.
    std::unordered_map<Texture*, int> texIdx;
    auto getOrAddMat = [&](const std::shared_ptr<Material>& m) -> int {
        auto it = matIdx.find(m.get());
        if (it != matIdx.end()) return it->second;
        int id = (int)r.materials.size();
        matIdx[m.get()] = id;
        r.materials.push_back(convertMaterial(m));
        // pkg178 Stage-3b D4: flag scenes carrying a closure-graph Principled
        // material so the wavefront launchers select the <true> shade-kernel
        // instantiation. The predicate mirrors gpu_closure_graph_is_principled
        // (gpu_materials.h) exactly.
        const GMaterial& g = r.materials.back();
        if (g.type == GMAT_CLOSURE_GRAPH && g.closureCount >= 1 &&
            g.closures[0].type == GCLOSURE_PRINCIPLED)
            r.hasPrincipled = true;
        // pkg189: flag scenes carrying ANY dispersive material so the wavefront
        // launcher selects the <*,*,*,true> shade kernel (hero-λ collapse
        // write-back). Set for both the Sellmeier dielectric (GMAT_DIELECTRIC)
        // and the Cauchy Principled glass (GMAT_CLOSURE_GRAPH) paths above.
        if (g.isDispersive)
            r.hasDispersive = true;
        // pkg186 — bake an image-texture base color (TexturedLambertian holding
        // an ImageTexture) into the flat device texel buffer and record its id in
        // the per-material parallel array. Keeps materialTextureId[] index-aligned
        // with materials[] (a -1 sentinel for every non-image material preserves
        // the untextured flat-albedo fast path). pkg190 extends this to bake
        // PROCEDURAL textures (also TexturedLambertian, non-ImageTexture) into the
        // same buffer — 3D voxel for Generated coords, 2D for UV.
        int texId = -1;
        if (auto* tl = dynamic_cast<TexturedLambertian*>(m.get())) {
            std::shared_ptr<Texture> tex = tl->getTexture();
            if (auto img = std::dynamic_pointer_cast<ImageTexture>(tex)) {
                if (!img->getData().empty()) {
                    auto tit = texIdx.find(img.get());
                    if (tit != texIdx.end()) {
                        texId = tit->second;
                    } else {
                        texId = (int)r.textures.size();
                        texIdx[img.get()] = texId;
                        GImageTexture desc;
                        desc.offset = (int)r.textureTexels.size();
                        desc.width  = img->getWidth();
                        desc.height = img->getHeight();
                        const std::vector<Vec3>& px = img->getData();
                        r.textureTexels.reserve(r.textureTexels.size() + px.size());
                        for (const Vec3& c : px)
                            r.textureTexels.push_back(GVec3(c.x, c.y, c.z));
                        r.textures.push_back(desc);
                    }
                    r.hasTexture = true;
                }
            } else if (tex) {
                // pkg190 — bake a PROCEDURAL base-colour texture (checker / brick /
                // wave / magic / …) into the flat device texel buffer, then reuse
                // the pkg186 fetch machinery. Two domains, matching how the CPU
                // Texture evaluates the node (include/advanced_features.h
                // Texture::textureCoordinates):
                //   * Generated coord mode → the node is a 3D field over
                //     the object's normalized bbox → bake a res^3 VOXEL grid in
                //     [0,1]^3 (the same space the CPU passes as `p`), sampled on the
                //     GPU by the Generated coordinate (gpu_sampleProcedural3D).
                //   * UV coord mode → the node is a 2D field of (u,v) → bake a res^2
                //     grid sampled by the pkg186 2D UV path (depth == 1).
                // The bake calls the material's OWN CPU evaluator, so parity is
                // exact-by-construction modulo grid resolution (no procedural math
                // is re-derived on the device — cite-algorithm safe).
                Texture* key = tex.get();
                // pkg190 follow-up (PR #612 review) — COORD-MODE CONVENTION:
                // the 3D voxel bake below stores the field over the NORMALIZED
                // Generated domain ([0,1]^3 over genMin/genSize) and the shade
                // path rebuilds g = clamp((p - genMin)/genSize, 0, 1) to sample
                // it. Only CoordMode::Generated evaluates in that space on the
                // CPU. CoordMode::Object passes the RAW unnormalized
                // objectPoint (include/advanced_features.h CoordMode::Object),
                // so an Object bake would diverge CPU<->GPU by construction —
                // bake Object only if the CPU side gains the identical bbox
                // normalization in lockstep. Object/Camera/Normal/Reflection/
                // Window therefore stay UNBAKED: texId stays -1 and the GPU
                // shades the flat baseColor (the pre-pkg190 degradation; CPU
                // remains the reference — test_pkg190 test_object_mode_*).
                const Texture::CoordMode cmode = tex->getCoordMode();
                const bool uvMode  = cmode == Texture::CoordMode::UV;
                const bool bakeable =
                    uvMode || cmode == Texture::CoordMode::Generated;
                auto tit = texIdx.find(key);
                if (!bakeable) {
                    // guarded fallback — no bake (see convention above)
                } else if (tit != texIdx.end()) {
                    texId = tit->second;
                    r.hasTexture = true;
                } else {
                    // pkg190 default bake resolution; escalate a specific high-
                    // frequency node only if its parity/SSIM gate demands it.
                    int res = 64;
                    GImageTexture desc;
                    desc.offset = (int)r.textureTexels.size();
                    desc.width  = res;
                    desc.height = res;
                    if (uvMode) {
                        desc.depth = 1;  // 2D UV field → pkg186 image path verbatim
                        r.textureTexels.reserve(r.textureTexels.size() +
                                                (size_t)res * res);
                        // Bake row j at v = 1 - (j+0.5)/res so the GPU 2D fetch
                        // (which v-flips, mirroring CPU ImageTexture::value) round-
                        // trips to value(u, v) exactly.
                        for (int j = 0; j < res; ++j) {
                            float v = 1.0f - (j + 0.5f) / res;
                            for (int i = 0; i < res; ++i) {
                                float u = (i + 0.5f) / res;
                                Vec3 c = tex->value(Vec2(u, v), Vec3(u, v, 0.0f));
                                r.textureTexels.push_back(GVec3(c.x, c.y, c.z));
                            }
                        }
                    } else {
                        // Generated 3D voxel bake. genMin/genSize come from
                        // the CPU texture's baked object bbox so the GPU rebuilds
                        // the identical normalized coordinate.
                        desc.depth = res;
                        Vec3 gmin  = tex->hasGeneratedBBox() ? tex->getGeneratedMin()
                                                             : Vec3(0.f, 0.f, 0.f);
                        Vec3 gsize = tex->hasGeneratedBBox() ? tex->getGeneratedSize()
                                                             : Vec3(1.f, 1.f, 1.f);
                        desc.genMin  = GVec3(gmin.x,  gmin.y,  gmin.z);
                        desc.genSize = GVec3(gsize.x, gsize.y, gsize.z);
                        r.textureTexels.reserve(r.textureTexels.size() +
                                                (size_t)res * res * res);
                        // Bake cell CENTERS over the normalized [0,1]^3 domain the
                        // CPU passes as `p` (= g) in CoordMode::Generated. Storage
                        // is k-major: idx = (k*res + j)*res + i.
                        for (int k = 0; k < res; ++k) {
                            float pz = (k + 0.5f) / res;
                            for (int j = 0; j < res; ++j) {
                                float py = (j + 0.5f) / res;
                                for (int i = 0; i < res; ++i) {
                                    float px = (i + 0.5f) / res;
                                    Vec3 c = tex->value(Vec2(px, py),
                                                        Vec3(px, py, pz));
                                    r.textureTexels.push_back(GVec3(c.x, c.y, c.z));
                                }
                            }
                        }
                    }
                    texId = (int)r.textures.size();
                    texIdx[key] = texId;
                    r.textures.push_back(desc);
                    r.hasTexture = true;
                }
            }
            // pkg190 fold-guard exactness (advisory #1, PR #590): a textured
            // lambertian's flat baseColor is only a fallback. Neutralize it so the
            // shade-path albedo swap (throughput *= texUp / upsample(baseColor))
            // divides by a FIXED neutral reference (upsample(1,1,1)) independent of
            // the material's own base chroma — an exact, unbiased swap even for a
            // saturated base. Net reflectance stays texUp, so the pkg186 image path
            // (previously dividing by a near-gray base) is unchanged.
            if (texId >= 0)
                r.materials[id].baseColor = GVec3(1.f, 1.f, 1.f);
        }
        r.materialTextureId.push_back(texId);
        return id;
    };

    // --- Geometry: pkg114 two-level (TLAS/BLAS) when the Renderer has instances,
    // else the existing single-level BVH. Both fill r.nodes/prims/triangles/spheres;
    // when instanced, r.tlas/instances/blas are also populated so the device
    // engages gpu_tlas_hit (otherwise it falls back to gpu_bvh_hit, unchanged). ---
    auto& cpuBvh = cpu.getBVH();
    if (cpu.hasInstances()) {
        // pkg114 inc 3b — mixed: flat scene (cpuBvh) folded in as an identity BLAS.
        buildTwoLevelArrays(cpu, cpuBvh.get(), r, getOrAddMat);
    } else {
        if (!cpuBvh) throw std::runtime_error("BVH not built — call buildAcceleration() first");
        appendFlatScene(cpu, cpuBvh.get(), r, getOrAddMat);
    }

    // --- Lights ---
    const LightList& ll2 = cpu.getLights();
    const auto& lightPtrs  = ll2.getLights();
    const auto& powerDist  = ll2.getPowerDist();
    r.totalLightPower      = ll2.getTotalPower();

    // Emitter→prim search list = the flat-scene ordered prims, which always
    // occupy global prim offset 0 (single-level AND pkg114 mixed, where the flat
    // scene is appended first). So flat-scene area lights resolve correctly even
    // in a mixed scene. Emitters that live on an INSTANCED mesh are deferred (a
    // follow-up): registered-mesh prims are not in this list, so their primIdx
    // stays -1 (GLight unwired).
    static const std::vector<std::shared_ptr<Hittable>> kNoPrims;
    const auto& orderedPrims = cpuBvh ? cpuBvh->getPrimitives() : kNoPrims;

    // pkg202: legacy hittable suns (add_sun_light / .blend importer) detected in
    // the loop below are converted to dedicated distant lights (appended to
    // r.dedicatedLights after this loop) instead of dead hittable GLights.
    std::vector<GDedicatedLight> convertedSuns;
    bool convertedLegacySun = false;

    // Find each light's primitive index in r.prims
    for (size_t i = 0; i < lightPtrs.size(); ++i) {
        // pkg202: the legacy hittable DistantLight contributes EXACTLY zero on
        // GPU — it maps to GPRIM_SKIP (scene_upload.cu prim walk) and its GLight
        // CDF slot returns an empty NEE sample (gpu_nee.cuh primIdx<0 guard),
        // wasting selection mass. Convert it here to the verified pkg89 dedicated
        // distant light instead of pushing a dead hittable GLight.
        //
        // Units are lossless. The legacy sun delivers irradiance
        //   S = RGBIlluminant(emittedRadiance())            (spectral)
        // because the CPU sampler multiplies emission by directionFalloff (=1/Ω
        // for a finite disk, =1 for a delta sun) and then divides by the
        // solid-angle pdf (=1/Ω, or =1 for delta), so the 1/Ω factors cancel and
        // the surface sees exactly S (light_sampler.cpp:79-85). The dedicated
        // distant delivers RGBIlluminant(emissionRGB)·staticScale (gpu_nee.cuh
        // gpu_nee_resolve:561, gpu_rgbSpectrumAt == CPU RGBIlluminant, linear in
        // magnitude). Setting emissionRGB = S and staticScale = 1 reproduces S
        // exactly. See the PR body for the full derivation.
        if (auto* sun = dynamic_cast<DistantLight*>(lightPtrs[i].get())) {
            float prevP = (i == 0) ? 0.f : powerDist[i-1];
            GDedicatedLight gd{};
            gd.power = powerDist[i] - prevP;   // sun's individual CDF weight (preserved)
            gd.kind  = GDED_DISTANT;
            Vec3 dir = sun->getDirection();    // axis points FROM the light
            gd.axis  = GVec3(dir.x, dir.y, dir.z);
            float ang = sun->getAngularDiameter();
            gd.cosOuter = std::cos(ang * 0.5f);
            // Solid angle via the 2*sin^2(h/2) identity (distant_light.cpp
            // distantSolidAngle / pkg140) so the device radiometry matches the
            // dedicated distant exactly; ang==0 -> spread 0 -> device delta branch.
            float sHalfHalf = std::sin(ang * 0.25f);
            gd.spread = 4.0f * float(M_PI) * sHalfHalf * sHalfHalf;
            Vec3 E = sun->emittedRadiance();   // irradiance S (RGB)
            gd.emissionRGB = GVec3(E.x, E.y, E.z);
            gd.staticScale = 1.0f;             // magnitude carried in emissionRGB
            convertedSuns.push_back(gd);
            convertedLegacySun = true;
            continue;                          // NO hittable GLight / no dead CDF slot
        }
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

    // --- pkg89-GPU / GAP 1: dedicated lights (point/spot/distant/area) ---
    // Mirror the CPU PowerLightSampler unified CDF: dedicated lights occupy the
    // CDF slots AFTER the hittable emitters (powerDist spans both — see
    // light_sampler.cpp PowerLightSampler::pdfValue). Their cumulativePower
    // continues from the last hittable entry so the device NEE selects across
    // both arrays with the same probabilities as the CPU sampler. This is what
    // makes a dedicated-light-only scene (Blender lamp, no emissive geometry)
    // render on the GPU instead of black (pkg86-B deferred this).
    {
        const auto& dedLightPtrs = ll2.getDedicatedLights();
        const size_t numHittable = lightPtrs.size();
        for (size_t j = 0; j < dedLightPtrs.size(); ++j) {
            const astroray::Light* L = dedLightPtrs[j].get();
            size_t k = numHittable + j;  // index into the unified powerDist CDF
            float prev = (k == 0) ? 0.f : powerDist[k - 1];
            GDedicatedLight gd{};
            gd.power           = powerDist[k] - prev;
            gd.cumulativePower = powerDist[k];
            astroray::DeviceLightParams p;
            if (L && L->fillDeviceParams(p)) {
                gd.kind        = p.kind;
                gd.position    = GVec3(p.position.x, p.position.y, p.position.z);
                gd.axis        = GVec3(p.axis.x, p.axis.y, p.axis.z);
                gd.u           = GVec3(p.u.x, p.u.y, p.u.z);
                gd.v           = GVec3(p.v.x, p.v.y, p.v.z);
                gd.width       = p.width;
                gd.height      = p.height;
                gd.areaShape   = p.areaShape;
                gd.radius      = p.radius;
                gd.spread      = p.spread;
                gd.cosInner    = p.cosInner;
                gd.cosOuter    = p.cosOuter;
                gd.emissionRGB = GVec3(p.emissionRGB.x, p.emissionRGB.y, p.emissionRGB.z);
                gd.staticScale = p.staticScale;
            } else {
                // Unsupported type (e.g. Background): keep the CDF slot aligned
                // but flag invalid so the device sampler yields no contribution.
                gd.kind = -1;
            }
            r.dedicatedLights.push_back(gd);
        }
    }

    // pkg202: fold the converted legacy suns in as dedicated distant lights and
    // rebuild the unified cumulative CDF. Removing each sun from the hittable
    // array shifted every following cumulativePower, so recompute the whole CDF
    // from the per-light powers (order-independent). totalLightPower is
    // UNCHANGED — the sun's power merely moved from the hittable array to the
    // dedicated array — so the final cumulative still lands on totalLightPower.
    // Net: the sun appears in the CDF exactly once, as a dedicated light, with
    // correct cumulative power and no dead GPRIM_SKIP selection mass.
    if (convertedLegacySun) {
        for (const auto& gd : convertedSuns) r.dedicatedLights.push_back(gd);
        float cum = 0.f;
        for (auto& gl : r.lights)          { cum += gl.power; gl.cumulativePower = cum; }
        for (auto& gd : r.dedicatedLights) { cum += gd.power; gd.cumulativePower = cum; }
    }

    // (pkg64-gpu Phase 2 caster gathering moved inline during sphere loop above)

    // --- pkg86-B: Light tree (Tree sampler mode only) ---
    // Flatten the CPU LightTree into GLightTreeNode/GLightTreeEmitter arrays
    // and precompute per-emitter bit trails (root->leaf path, bit i = level-i
    // branch, 0 = left) for the device-side pdf walk — mirrors Cycles'
    // bit_trail (kernel/light/tree.h, Apache-2.0, commit e52e5eb0).
    if (ll2.samplerMode() == LightList::SamplerMode::Tree) {
        const astroray::LightTree* tree = ll2.lightTree();
        if (tree != nullptr && !tree->empty()) {
            const auto& tnodes    = tree->getNodes();
            const auto& temitters = tree->getEmitters();

            // Dedicated lights have no GLight slot on the GPU yet — if the
            // tree contains one, skip the upload and warn (the kernels fall
            // back to power-CDF selection; spec: warn, don't error).
            // pkg202: a converted legacy sun reindexes r.lights (the sun no
            // longer occupies a hittable slot), so the CPU tree's per-emitter
            // lightIndex values no longer map onto r.lights. Fall back to the
            // power-CDF selection (the documented behavior whenever the tree is
            // not uploadable) rather than upload a mis-indexed tree.
            bool uploadable = !convertedLegacySun;
            for (const auto& e : temitters) {
                if (e.isDedicated || e.lightIndex < 0 ||
                    e.lightIndex >= (int)r.lights.size()) {
                    uploadable = false;
                    break;
                }
            }
            if (!uploadable) {
                fprintf(stderr, "[CUDA] light tree not uploadable (dedicated "
                                "lights present) - GPU NEE falls back to "
                                "power-CDF selection\n");
            } else {
                r.lightTreeNodes.reserve(tnodes.size());
                for (const auto& n : tnodes) {
                    GLightTreeNode g;
                    g.bboxMin   = GVec3(n.bbox.min.x, n.bbox.min.y, n.bbox.min.z);
                    g.bboxMax   = GVec3(n.bbox.max.x, n.bbox.max.y, n.bbox.max.z);
                    g.bconeAxis = GVec3(n.bcone.axis.x, n.bcone.axis.y, n.bcone.axis.z);
                    g.thetaO    = n.bcone.theta_o;
                    g.thetaE    = n.bcone.theta_e;
                    g.energy    = n.energy;
                    g.leftChild    = n.leftChild;
                    g.rightChild   = n.rightChild;
                    g.firstEmitter = n.firstEmitter;
                    g.numEmitters  = n.numEmitters;
                    r.lightTreeNodes.push_back(g);
                }

                // Bit trails via an explicit-stack walk (depth-capped at 32,
                // far above the ~log2(n) depth of an SAOH build).
                r.lightTreeEmitters.assign(temitters.size(), GLightTreeEmitter{-1, 0u});
                struct StackEntry { int node; unsigned int trail; int depth; };
                std::vector<StackEntry> st;
                st.push_back({0, 0u, 0});
                bool trailOk = true;
                while (!st.empty()) {
                    StackEntry se = st.back();
                    st.pop_back();
                    const astroray::LightTreeNode& n = tnodes[se.node];
                    if (n.isLeaf()) {
                        for (int k = 0; k < n.numEmitters; ++k) {
                            r.lightTreeEmitters[n.firstEmitter + k] = GLightTreeEmitter{
                                temitters[n.firstEmitter + k].lightIndex, se.trail};
                        }
                        continue;
                    }
                    if (se.depth >= 32) { trailOk = false; break; }
                    st.push_back({n.leftChild,  se.trail, se.depth + 1});
                    st.push_back({n.rightChild, se.trail | (1u << se.depth), se.depth + 1});
                }

                if (!trailOk) {
                    fprintf(stderr, "[CUDA] light tree deeper than 32 levels - "
                                    "GPU NEE falls back to power-CDF selection\n");
                    r.lightTreeNodes.clear();
                    r.lightTreeEmitters.clear();
                } else {
                    r.lightToEmitter.assign(r.lights.size(), -1);
                    for (size_t ei = 0; ei < r.lightTreeEmitters.size(); ++ei)
                        r.lightToEmitter[r.lightTreeEmitters[ei].lightIndex] = (int)ei;
                }
            }
        }
    }

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

    // --- pkg88-C.0: motion vertices for deformation motion blur ---
    // The GPU buffer is the concatenation of the CPU per-batch storage, in
    // batch order — matching the motionPtrToOffset mapping built during the
    // primitive walk above (each GTriangle::motionOffset indexes into this).
    for (const auto& batch : cpu.getMotionVertexBatches()) {
        for (const auto& v : batch)
            r.motionVertices.push_back(GVec3(v.x, v.y, v.z));
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
