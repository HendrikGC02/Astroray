// scene_upload.cu — Host → Device scene transfer for CUDARenderer.
// Converts CPU scene data (BVH nodes, triangles, spheres, materials, lights,
// env map) into flat GPU arrays via cudaMalloc / cudaMemcpy.

#include "astroray/gpu_scene_upload.h"
#include "astroray/gpu_types.h"
#include "astroray/shapes.h"
#include "astroray/curves.h"   // pkg225 Stage 3 — CurveSegment (dynamic_cast in appendOnePrim)
#include "astroray/spectral_profile.h"
#include "raytracer.h"
#include "astroray/light_tree.h"   // pkg86-B: LightTree flattening (needs raytracer.h's Vec3/AABB)
#include "advanced_features.h"
#include "astroray/light_path_mix.h"  // #991 Mix Shader with a Light Path Fac
#include "astroray/add_material.h"    // #1072 Add Shader partner upload
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
#include <string>    // pkg242 — procedural-bake dedup key
#include <cstdint>   // pkg242 — uintptr_t for the transform-aware bake key

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

// pkg291 (#875): GTriangle geometry fields, shared by appendOnePrim and the
// wavefront in-place object-move patch (gpu_wavefront_snapshot.cu).
void fillTriangleGeometry(const Triangle& tri, GTriangle& gt) {
    Vec3 v0 = tri.getV0(), v1 = tri.getV1(), v2 = tri.getV2();
    Vec3 n = tri.getFaceNormal();
    gt.v0 = GVec3(v0.x, v0.y, v0.z);
    gt.v1 = GVec3(v1.x, v1.y, v1.z);
    gt.v2 = GVec3(v2.x, v2.y, v2.z);
    Vec3 n0, n1, n2;
    if (tri.getVertexNormals(n0, n1, n2)) {
        gt.n0 = GVec3(n0.x, n0.y, n0.z);
        gt.n1 = GVec3(n1.x, n1.y, n1.z);
        gt.n2 = GVec3(n2.x, n2.y, n2.z);
        gt.flat_shaded = false;
    } else {
        gt.n0 = gt.n1 = gt.n2 = GVec3(n.x, n.y, n.z);
        gt.flat_shaded = true;
    }
}

std::vector<GBVHNode> convertBvhNodes(const BVHAccel& bvh) {
    std::vector<GBVHNode> out;
    out.reserve(bvh.getNodes().size());
    for (const auto& n : bvh.getNodes()) out.push_back(convertNode(n));
    return out;
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
        if (g.disneyMetalConductor) {
            // #876/pkg292: an opaque Disney single-closure graph evaluates the
            // monolithic gpu_disney_eval, which reads these parent fields.
            g.specular = mat->getSpecular();
            g.specularTint = mat->getSpecularTint();
            g.sheen = mat->getSheen();
            g.sheenTint = mat->getSheenTint();
            g.clearcoat = mat->getClearcoat();
            g.clearcoatGloss = mat->getClearcoatGloss();
            g.anisotropic = mat->getAnisotropic();
            g.anisotropicRotation = mat->getAnisotropicRotation();
        }
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
        // #1099: both-face emitter (Cycles Emission shader / EmissivePlugin), read by
        // gpu_material_emitted via the Disney-only anisotropicRotation slot.
        if (mat->emitsFromBothFaces()) g.anisotropicRotation = 1.f;
    } else if (gpuType == "principled_hair") {
        // pkg225 Stage 4 — standalone Chiang 2016 hair BSDF. No GMaterial growth
        // (640 B lock): the hair params reuse existing scalar fields, filled from
        // the plugin's OWN ctor-resolved values (hairGPUParams()), so all three
        // sigma_a parametrizations are already resolved host-side and CPU/GPU are
        // per-construction identical. The device BSDF (gpu_hair.cuh) recomputes
        // v/s/tilt from these each hit; sigma_a rides baseColor.
        //   baseColor=sigma_a  roughness=beta_m  clearcoatGloss=beta_n
        //   transmission=coat  clearcoat=alpha(tilt)  ior=eta
        HairGPUParams h = mat->hairGPUParams();
        g.type = GMAT_HAIR_PRINCIPLED;
        g.spectralMode = GSPEC_RGB_ALBEDO;
        g.baseColor = GVec3(h.sigmaA.x, h.sigmaA.y, h.sigmaA.z);
        g.roughness = h.betaM;
        g.clearcoatGloss = h.betaN;
        g.transmission = h.coat;
        g.clearcoat = h.alpha;
        g.ior = h.eta;
        // pkg225 Stage 5 — spectral melanin rides hair-unused scalar fields so
        // GMaterial stays 640 B (gpu_hair.cuh gpu_hair_unpack reads these back):
        //   specular = melaninMode flag   metallic = eumelanin   subsurface = pheomelanin
        g.specular = h.melaninMode ? 1.0f : 0.0f;
        g.metallic = h.eumelanin;
        g.subsurface = h.pheomelanin;
        // pkg316 — reflectance mode: specular = 2 flags the per-lambda inversion of
        // the colour's JH sigmoid (coefficients in metallic/subsurface/specularTint).
        if (h.reflectanceJH) {
            g.specular = 2.0f;
            g.metallic = h.jh[0];
            g.subsurface = h.jh[1];
            g.specularTint = h.jh[2];
        }
    } else {
        throw std::runtime_error("Material declares unsupported GPU type: " + gpuType);
    }
    return g;
}

// #990 / #1047 — append triangle `tri`'s corners (uploaded triangle index
// `triIndex`) to attribute-layer slots [firstSlot, attrLayers.size()), lazily
// padding earlier triangles with the slot's missing value (like triGenerated).
static void appendAttrCorners(const Triangle& tri, size_t triIndex, size_t firstSlot,
                              SceneUploadResult& r)
{
    for (size_t k = firstSlot; k < r.attrLayers.size(); ++k) {
        Vec3 c0, c1, c2;
        if (!tri.attributeCorners(r.attrLayers[k], c0, c1, c2)) continue;
        const float m = r.attrMissing[k];
        auto& v = r.attrCorners[k];
        v.resize(triIndex * 3, GVec3(m, m, m));
        v.push_back(GVec3(c0.x, c0.y, c0.z));
        v.push_back(GVec3(c1.x, c1.y, c1.z));
        v.push_back(GVec3(c2.x, c2.y, c2.z));
    }
}

// pkg315 (#1067): the per-MATERIAL half of the per-triangle UV-upload gate that
// appendOnePrim applies (the aniso case also needs the triangle's own
// hasUVLayers). Factored out so the material-only replay (buildMaterialDomain)
// compares the same classification the full flatten stamped on the triangles.
struct UvGate { bool textureUVConsumer = false; bool anisoPrincipled = false; };
static UvGate classifyUvGate(const std::shared_ptr<Material>& mtl) {
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
    // #962 — a textured emitter (non-SolidColor TexturedLight) needs the
    // UVs for its per-hit / per-NEE-sample emission fetch.
    const auto* telMtl = mtl ? dynamic_cast<const TexturedLight*>(mtl.get()) : nullptr;
    const bool emissionTextured =
        telMtl && !std::dynamic_pointer_cast<SolidColor>(telMtl->getTexture());
    // pkg223 — a normal-mapped material needs the active-layer UVs on the
    // device for the tangent-space decode (HasNormalPerturb). Checked on the
    // DECORATOR (mtl is the NormalMapped wrapper, whose inner TexturedLambertian
    // the imageTextured cast above cannot see) — this also restores the base-
    // colour texture UVs for a NormalMapped(TexturedLambertian).
    const bool normalMapped =
        mtl && mtl->normalMapTexture() != nullptr;
    // pkg223b — a bump-mapped material likewise needs the active-layer UVs
    // on the device: the shade path's HasNormalPerturb bump branch samples
    // the height texture at the hit UV (and ±eps). Without this a bump-ONLY
    // material's triangle uploads no UVs (hasUV=0) and the bump branch skips.
    const bool bumpMapped =
        mtl && mtl->bumpMapTexture() != nullptr;
    // pkg219d — a scalar-parameter op-VM material (roughness/metallic/etc.
    // driven by an image) needs the active-layer UVs on the device: the
    // shade path fetches the scalar program's OWN source texel at the hit
    // UV. Without this a scalar-ONLY material (no base-colour/normal/bump
    // texture) uploads UV-less (hasUV=0) and the scalar override reads
    // garbage → silently no-ops (same class as the pkg223b bump-only gate).
    // Checked on the inner material so a NormalMapped(disney) also qualifies.
    const auto& scalarMtl =
        (mtl && mtl->normalMapInner()) ? mtl->normalMapInner() : mtl;
    const bool scalarProgrammed =
        scalarMtl &&
        (scalarMtl->scalarProgram(astroray::svm::SCALAR_ROUGHNESS) ||
         scalarMtl->scalarProgram(astroray::svm::SCALAR_METALLIC) ||
         scalarMtl->scalarProgram(astroray::svm::SCALAR_TRANSMISSION) ||
         scalarMtl->scalarProgram(astroray::svm::SCALAR_IOR) ||
         // #988 — textured Principled Base Color (image / 2D bake input).
         scalarMtl->scalarProgram(astroray::svm::SCALAR_BASE_COLOR));
    // pkg242 Phase 0 -- UV-less fallback contract. The CPU Triangle ALWAYS
    // defines (uv0,uv1,uv2): authored layer 0 when present, else the
    // implicit default domain uv0=(0,0),uv1=(1,0),uv2=(0,1)
    // (include/astroray/shapes.h ctors), so shapes.h interpolates a valid
    // rec.uv even for a UV-less triangle and the CPU procedural/image
    // sampler shades correctly (the reproduced checker-binding baseline:
    // CPU luminance std 0.4182 vs GPU 0.0330). getUV0/1/2 returns exactly
    // that CPU fallback domain, so upload it for the 2D texture-sampling
    // consumers regardless of authored layers -- this mirrors CPU byte-
    // for-byte. The UV-ALIGNED-FRAME recomputes (anisotropy tangent,
    // normal-map decode, bump frame) instead gate on gt.uvAuthored =
    // tri->hasUVLayers(), because the CPU only computes a UV-aligned
    // tangent when !uvLayers.empty() (shapes.h); a UV-less
    // aniso/normal/bump surface keeps the arbitrary frame on both
    // backends. The anisotropic-Principled UV-tangent path is ALSO only
    // uploaded for authored layers (nothing to sample otherwise).
    const bool textureUVConsumer =
        imageTextured || emissionTextured || normalMapped || bumpMapped ||
        scalarProgrammed;
    return UvGate{textureUVConsumer, anisoPrincipled};
}

// pkg315: GTriangle/GSphere::materialHash of a material uploaded at `materialId`
// (Cryptomatte; unnamed materials hash their slot).
static uint32_t materialNameHash(const Material& m, int materialId) {
    std::string n = m.getName();
    if (n.empty()) n = "Unnamed_Material_" + std::to_string(materialId);
    uint32_t h = 0;
    MurmurHash3_x86_32(n.c_str(), static_cast<int>(n.length()), 0, &h);
    return h;
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
    const std::function<int(const std::shared_ptr<Material>&)>& getOrAddMat,
    // pkg225 Stage 3 — scene-wide GPU curve mode (Renderer::getCurveThickMode()),
    // written onto every emitted GCurveSegment. Ignored for non-curve prims.
    bool curveThick = false)
{
    GPrimitive gp;
    if (auto* tri = dynamic_cast<Triangle*>(hittable.get())) {
        gp.type  = GPRIM_TRIANGLE;
        gp.index = (int)r.triangles.size();
        GTriangle gt;
        fillTriangleGeometry(*tri, gt);  // pkg291: shared with the refit patch
        gt.materialId = getOrAddMat(tri->getMaterial());
        // pkg178 Stage-3b PR-4b / pkg186 / pkg242 Phase 0 — upload per-triangle
        // texcoords for every 2D texture-sampling consumer (image / normal /
        // bump / scalar) plus authored anisotropic-Principled triangles, and set
        // two bits: `hasUV` = "UVs uploaded, safe to sample" (gates the device
        // base-colour/height/scalar fetch), and `uvAuthored` = tri->hasUVLayers()
        // = "the mesh carries a real UV layer" (gates the UV-ALIGNED-FRAME
        // recomputes in stage_advance.cu). pkg242 uploads the CPU implicit
        // fallback domain (uv0=(0,0),uv1=(1,0),uv2=(0,1)) for UV-less consumers so
        // the device fetch matches the CPU; those UV-less triangles get hasUV=true
        // but uvAuthored=false, so the anisotropy/normal-map/bump frame recomputes
        // stay off (arbitrary frame kept — CPU↔GPU agree). Non-consumer triangles
        // leave both bits false → zero shade cost and zero UV upload.
        {
            const UvGate gate = classifyUvGate(tri->getMaterial());
            const bool textureUVConsumer = gate.textureUVConsumer;
            const bool anisoPrincipled = gate.anisoPrincipled;
            if (textureUVConsumer || (anisoPrincipled && tri->hasUVLayers())) {
                Vec2 t0 = tri->getUV0(), t1 = tri->getUV1(), t2 = tri->getUV2();
                gt.uv0 = GVec2(t0.u, t0.v);
                gt.uv1 = GVec2(t1.u, t1.v);
                gt.uv2 = GVec2(t2.u, t2.v);
                gt.hasUV = true;
                gt.uvAuthored = tri->hasUVLayers();
            }
        }
        // pkg88-C.0: defaults — the BVH primitive walk in buildSceneArrays
        // resolves real offsets for motion triangles via motionPtrToOffset
        // (per-batch stable pointers; see Renderer::motionVertexBatches_).
        gt.motionOffset = -1;
        gt.motionSteps = 1;
        // #847 — per-vertex Generated coords, lazily padded with the NaN
        // "none" sentinel so the array stays parallel to r.triangles.
        {
            Vec3 g0, g1, g2;
            if (tri->getGenerated(g0, g1, g2)) {
                const float nan = std::numeric_limits<float>::quiet_NaN();
                r.triGenerated.resize((size_t)gp.index * 3, GVec3(nan, nan, nan));
                r.triGenerated.push_back(GVec3(g0.x, g0.y, g0.z));
                r.triGenerated.push_back(GVec3(g1.x, g1.y, g1.z));
                r.triGenerated.push_back(GVec3(g2.x, g2.y, g2.z));
            }
        }
        // #1006 — per-vertex OBJECT-local positions, same NaN-padded layout.
        {
            Vec3 o0, o1, o2;
            if (tri->getObjectLocal(o0, o1, o2)) {
                const float nan = std::numeric_limits<float>::quiet_NaN();
                r.triObjectLocal.resize((size_t)gp.index * 3, GVec3(nan, nan, nan));
                r.triObjectLocal.push_back(GVec3(o0.x, o0.y, o0.z));
                r.triObjectLocal.push_back(GVec3(o1.x, o1.y, o1.z));
                r.triObjectLocal.push_back(GVec3(o2.x, o2.y, o2.z));
            }
        }
        // #990 — corners of every attribute layer a GPU descriptor reads,
        // padded with the layer's missing value (Cycles' not-found attribute:
        // 0, or 1 for the Attribute node's Alpha) for triangles without it.
        appendAttrCorners(*tri, (size_t)gp.index, 0, r);
        r.triangles.push_back(gt);
        std::string objName = tri->getName();
        if (objName.empty()) objName = "Unnamed_Triangle_" + std::to_string(r.triangles.size() - 1);
        MurmurHash3_x86_32(objName.c_str(), static_cast<int>(objName.length()), 0, &r.triangles.back().objectHash);
        r.triangles.back().materialHash = materialNameHash(*tri->getMaterial(), gt.materialId);
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
        gs.materialHash = materialNameHash(*sph->getMaterial(), gs.materialId);
        r.spheres.push_back(gs);
    } else if (auto* curve = dynamic_cast<CurveSegment*>(hittable.get())) {
        // pkg225 Stage 3 — one CPU CurveSegment → one GCurveSegment + GPRIM_CURVE
        // leaf. The Catmull-Rom→Bezier conversion already happened in the CPU
        // CurveSegment ctor; bezierHull() is the world-space cubic-Bezier control
        // hull, uploaded verbatim so the device leaf runs the same pbrt math.
        gp.type  = GPRIM_CURVE;
        gp.index = (int)r.curveSegments.size();
        GCurveSegment gc;
        const Vec3* hull = curve->bezierHull();
        gc.bezier0 = GVec3(hull[0].x, hull[0].y, hull[0].z);
        gc.bezier1 = GVec3(hull[1].x, hull[1].y, hull[1].z);
        gc.bezier2 = GVec3(hull[2].x, hull[2].y, hull[2].z);
        gc.bezier3 = GVec3(hull[3].x, hull[3].y, hull[3].z);
        gc.radius0 = curve->getRadius0();
        gc.radius1 = curve->getRadius1();
        gc.materialId = getOrAddMat(curve->getMaterial());
        gc.thick = curveThick ? 1 : 0;
        gc.strandId = curve->curveStrandId();  // #1092
        r.curveSegments.push_back(gc);
    } else {
        // pkg85-C: GPRIM_SKIP placeholder keeps prims index-aligned within a BLAS.
        gp.type  = GPRIM_SKIP;
        gp.index = -1;
    }
    if (hittable->isIndirectOnly()) {  // #36
        gp.flags |= GPRIM_FLAG_INDIRECT_ONLY;
        r.hasIndirectOnly = true;
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
        appendOnePrim(hittable, r, getOrAddMat, cpu.getCurveThickMode());
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

// pkg315: texture-derived facts that decide whether triGenerated / triObjectLocal
// upload (#847 / #1006); the full build and the material-only replay share them.
static void texGeomFlags(const SceneUploadResult& r, bool& gen, bool& obj) {
    gen = false;
    obj = false;
    for (const auto& t : r.textures) {
        gen = gen || t.depth > 1 || (t.procId >= 0 && !t.objectCoord);
        obj = obj || t.objectCoord;
    }
}

// Shared producer of the host-side flat arrays (pkg315 / #1067).
//  replayRoots == nullptr: the full build (the original buildSceneArrays).
//  replayRoots != nullptr: the MATERIAL-DOMAIN replay. The geometry walk is
//  replaced by getOrAddMat over the cached walk-order slot roots, so the material
//  producer below runs byte-for-byte as in a full build and only the geometry /
//  light / environment parts (which a material edit cannot change) are skipped.
//  Returns false when the replay hits something it cannot reproduce without the
//  geometry (slot order changed, Object-coordinate bake, attribute layer).
static bool buildSceneArraysImpl(const Renderer& cpu, const Camera* cam, SceneUploadResult& r,
                                 const std::vector<std::shared_ptr<Material>>* replayRoots) {
    bool replayBail = false;

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
        r.camera.orthographic = cam->isOrthographic() ? 1 : 0;  // #845
        { Vec3 f = cam->viewForward(); r.camera.forward = GVec3(f.x, f.y, f.z); }
    }

    // --- Materials: unique ID per shared_ptr (shared by single-level + pkg114 instanced) ---
    std::unordered_map<Material*, int> matIdx;
    // pkg186 — image dedup. #825: a descriptor is keyed on (ImageTexture*, the
    // Mapping applied to it) — the image's own Mapping for a direct/normal/bump
    // use, the parent ProgramTexture's Mapping for an op-VM child — so a direct
    // use and a program use with a different Mapping get distinct descriptors
    // (was keyed on the pointer alone: first consumer's Mapping won). Texels
    // are uploaded once per ImageTexture* and shared by its descriptors.
    std::unordered_map<std::string, int> texIdx;
    std::unordered_map<Texture*, int> texelOffset;
    // pkg219b — op-VM program dedup: one ShaderVMProgram slot per ProgramTexture*.
    std::unordered_map<Texture*, int> progIdx;
    // pkg242 — procedural-bake dedup keyed on (Texture*, Mapping matrix). The
    // bake FOLDS the transform into the texels (see below), so the cache key
    // must include the transform: a Mapping edit changes the key and forces a
    // re-bake, and two textures differing only by transform never alias.
    std::unordered_map<std::string, int> procBakeIdx;
    auto procBakeKey = [](Texture* t) {
        std::string k = std::to_string(reinterpret_cast<uintptr_t>(t));
        if (t->hasMapping()) {
            const float* m = t->getMappingMatrix();
            // Bit-exact float identity: std::to_string rounds to 6 decimals,
            // which would alias two Mapping matrices that differ below 5e-7 in
            // any element onto one bake (pre-review finding 2026-09-07).
            for (int i = 0; i < 12; ++i) {
                uint32_t bits; std::memcpy(&bits, &m[i], sizeof bits);
                k += '|'; k += std::to_string(bits);
            }
        }
        return k;
    };
    // #825 — upload `img` (texels once per pointer) with `mapSrc`'s Mapping on
    // the descriptor; returns the texId. Key = (img, mapSrc Mapping bits), same
    // bit-exact convention as procBakeKey.
    auto uploadImageTexId = [&](ImageTexture* img, const Texture* mapSrc) -> int {
        std::string k = std::to_string(reinterpret_cast<uintptr_t>(img));
        if (mapSrc->hasMapping()) {
            const float* m = mapSrc->getMappingMatrix();
            for (int i = 0; i < 12; ++i) {
                uint32_t bits; std::memcpy(&bits, &m[i], sizeof bits);
                k += '|'; k += std::to_string(bits);
            }
        }
        auto tit = texIdx.find(k);
        if (tit != texIdx.end()) return tit->second;
        GImageTexture desc;
        auto oit = texelOffset.find(img);
        if (oit != texelOffset.end()) {
            desc.offset = oit->second;
        } else {
            desc.offset = (int)r.textureTexels.size();
            texelOffset[img] = desc.offset;
            const std::vector<Vec3>& px = img->getData();
            r.textureTexels.reserve(r.textureTexels.size() + px.size());
            for (const Vec3& c : px)
                r.textureTexels.push_back(GVec3(c.x, c.y, c.z));
        }
        desc.width  = img->getWidth();
        desc.height = img->getHeight();
        desc.extension = img->getExtension();   // #1004 (REPEAT / CLIP / MIRROR)
        // pkg219a — full 3-D Mapping matrix so the GPU image sample honors it
        // exactly like the CPU (M*(u,v,0)).
        if (mapSrc->hasMapping()) {
            desc.hasMapping = 1;
            const float* mm = mapSrc->getMappingMatrix();
            for (int i = 0; i < 12; ++i) desc.mapping[i] = mm[i];
        }
        int texId = (int)r.textures.size();
        texIdx[k] = texId;
        r.textures.push_back(desc);
        return texId;
    };
    // pkg190 procedural bake, factored out (issue #818 Item 1) so it serves BOTH
    // a direct procedural base colour AND a procedural INPUT of an op-VM
    // ProgramTexture. Bakes the CPU texture's own evaluator into the flat texel
    // buffer over its coord domain (2D-UV grid or 3D voxel, Mapping folded in per
    // pkg242) and returns the texId, or -1 for an unbakeable coord mode
    // (Camera/Normal/Reflection/Window; Object without a bbox — CPU stays the reference). Dedups
    // on (pointer, Mapping) via procBakeIdx. Does NOT set r.hasTexture; the caller
    // does when texId >= 0.
    // #994 — world-space bbox of the flat-scene geometry per material (filled
    // before the geometry walk) and the bbox of the material getOrAddMat is
    // uploading: the bake domain of an OBJECT-coordinate procedural.
    std::unordered_map<const Material*, AABB> matWorldBox;
    const AABB* curObjBox = nullptr;
    // #1085 - the WORLD-space bbox per material (matWorldBox holds object-local
    // boxes for triangles that carry them): bakeProceduralTexId reads it to spot a
    // flat (planar) Generated-coordinate consumer.
    // C1 (#1085 review): the GPU lookup (gpu_generatedCoord) interpolates the per-vertex
    // #847 Generated coords, which carry the object's rotation, so a plane that is
    // world-flat on y can be Generated-flat on z. Flatness is therefore judged on the
    // per-vertex Generated coords when every triangle of the material has them; the
    // world bbox is only the fallback frame (no per-vertex Generated at all).
    struct GenFlatInfo {
        AABB world; bool haveWorld = false;   // world bbox (fallback frame)
        AABB gen;   bool haveGen = false;     // bbox of per-vertex Generated coords
        bool noGen = false;                   // some primitive lacks per-vertex Generated
    };
    std::unordered_map<const Material*, GenFlatInfo> matGenBox;
    const GenFlatInfo* curGenBox = nullptr;
    auto bakeProceduralTexId = [&](Texture* tex) -> int {
        Texture* key = tex;
        const Texture::CoordMode cmode = tex->getCoordMode();
        // pkg315: an Object-coordinate bake needs the geometry's world bbox.
        if (replayRoots && cmode == Texture::CoordMode::Object) { replayBail = true; return -1; }
        const bool uvMode  = cmode == Texture::CoordMode::UV;
        // #994: OBJECT coords (CPU: the world hit point, advanced_features.h
        // CoordMode::Object) bake as a 3D voxel over the using geometry's world
        // bbox, the same 64^3 nearest-voxel resolution as a Generated bake. No
        // bbox (instanced-only material) -> unbaked, as before.
        const bool objMode = cmode == Texture::CoordMode::Object && curObjBox;
        const bool bakeable = uvMode || cmode == Texture::CoordMode::Generated || objMode;
        if (!bakeable) return -1;
        std::string pkey = procBakeKey(key);
        // #1085 - a Generated-coordinate procedural on FLAT geometry (the default
        // plane: every swatch card) bakes a 2-layer high-resolution slice at the
        // plane's exact Generated coordinate instead of 64^3 cubes. Before, the plane
        // (Generated z = 0.5) sat on a voxel face and read the cell centred at
        // 31.5/64 (z-dependent Wave Bands: a uniform brightness offset), and detail
        // finer than 1/64 of the object aliased. Flat = world-bbox extent below the
        // Triangle::boundingBox padding (2 x 1e-4) plus slack. All three axes flat
        // (a point-like object) keeps the cube.
        const bool genMode = !uvMode && !objMode;
        bool flat[3] = {false, false, false};
        float flatG[3] = {0.f, 0.f, 0.f};
        int nFlat = 0;
        if (genMode && curGenBox && curGenBox->haveGen && !curGenBox->noGen) {
            // Per-vertex Generated frame (what the shade path reads): the box of the
            // coordinates themselves, no genMin/genSize normalisation.
            for (int a = 0; a < 3; ++a) {
                if (curGenBox->gen.max[a] - curGenBox->gen.min[a] >= 1e-4f) continue;
                flat[a] = true;
                ++nFlat;
                flatG[a] = 0.5f * (curGenBox->gen.min[a] + curGenBox->gen.max[a]);
            }
            if (nFlat == 3) {
                flat[0] = flat[1] = flat[2] = false;
                nFlat = 0;
            }
        } else if (genMode && curGenBox && curGenBox->haveWorld && !curGenBox->haveGen) {
            const AABB* wbox = &curGenBox->world;
            const Vec3 gm = tex->hasGeneratedBBox() ? tex->getGeneratedMin() : Vec3(0.f, 0.f, 0.f);
            const Vec3 gs = tex->hasGeneratedBBox() ? tex->getGeneratedSize() : Vec3(1.f, 1.f, 1.f);
            for (int a = 0; a < 3; ++a) {
                if (wbox->max[a] - wbox->min[a] >= 3e-4f) continue;
                flat[a] = true;
                ++nFlat;
                // The same normalisation the CPU applies to a hit on the plane
                // (advanced_features.h CoordMode::Generated bbox branch).
                flatG[a] = gs[a] > 1e-6f
                    ? std::min(1.0f, std::max(0.0f, (0.5f * (wbox->min[a] + wbox->max[a]) - gm[a]) / gs[a]))
                    : 0.0f;
            }
            if (nFlat == 3) {
                flat[0] = flat[1] = flat[2] = false;
                nFlat = 0;
            }
        }
        if (nFlat > 0) {
            for (int a = 0; a < 3; ++a) {
                if (!flat[a]) continue;
                uint32_t bits; std::memcpy(&bits, &flatG[a], sizeof bits);
                pkey += "|f"; pkey += std::to_string(a); pkey += ':'; pkey += std::to_string(bits);
            }
        }
        if (objMode) {
            const float bb[6] = {curObjBox->min.x, curObjBox->min.y, curObjBox->min.z,
                                 curObjBox->max.x, curObjBox->max.y, curObjBox->max.z};
            for (float f : bb) {
                uint32_t bits; std::memcpy(&bits, &f, sizeof bits);
                pkey += "|o"; pkey += std::to_string(bits);
            }
        }
        auto tit = procBakeIdx.find(pkey);
        if (tit != procBakeIdx.end()) return tit->second;
        // #1007: Noise / Wave / Voronoi on surface consumers are evaluated per hit
        // (perHitTexId); a 3D bake is the fallback (other texture types, emission).
        if (!uvMode)
            fprintf(stderr, "[#1007] DEGRADED: procedural texture with %s coordinates "
                            "sampled from a %s bake on GPU (no per-hit evaluator "
                            "for this texture or consumer); detail finer than a bake "
                            "cell aliases\n", objMode ? "Object" : "Generated",
                    nFlat == 0 ? "64^3 voxel" : (nFlat == 1 ? "512^2 slice" : "4096-cell line"));
        int res = 64;  // pkg190 default bake resolution
        // #1085: one flat axis -> 512^2 (the same 262k evaluations as 64^3), two -> 4096.
        const int nx = flat[0] ? 2 : (nFlat == 0 ? res : (nFlat == 1 ? 512 : 4096));
        const int ny = flat[1] ? 2 : (nFlat == 0 ? res : (nFlat == 1 ? 512 : 4096));
        const int nz = flat[2] ? 2 : (nFlat == 0 ? res : (nFlat == 1 ? 512 : 4096));
        GImageTexture desc;
        desc.offset = (int)r.textureTexels.size();
        desc.width  = res;
        desc.height = res;
        if (uvMode) {
            desc.depth = 1;  // 2D UV field → pkg186 image path verbatim
            r.textureTexels.reserve(r.textureTexels.size() + (size_t)res * res);
            for (int j = 0; j < res; ++j) {
                float v = 1.0f - (j + 0.5f) / res;
                for (int i = 0; i < res; ++i) {
                    float u = (i + 0.5f) / res;
                    // #962: full CPU UV-mode chain (Mapping, else legacy UV
                    // transform) -- Texture::value(HitRecord) with p=(u,v,0).
                    Vec3 c = tex->valueAtCoord(Vec2(u, v), Vec3(u, v, 0.0f));
                    r.textureTexels.push_back(GVec3(c.x, c.y, c.z));
                }
            }
        } else if (objMode) {
            desc.depth = res;
            desc.objectCoord = 1;
            Vec3 gmin = curObjBox->min, gsize = curObjBox->max - curObjBox->min;
            // A flat axis (plane) gets a 1e-4 slab so the device frame stays finite.
            for (int a = 0; a < 3; ++a) {
                if (gsize[a] < 1e-4f) { gmin[a] -= 0.5e-4f; gsize[a] = 1e-4f; }
            }
            desc.genMin  = GVec3(gmin.x,  gmin.y,  gmin.z);
            desc.genSize = GVec3(gsize.x, gsize.y, gsize.z);
            r.textureTexels.reserve(r.textureTexels.size() + (size_t)res * res * res);
            for (int k = 0; k < res; ++k) {
                for (int j = 0; j < res; ++j) {
                    for (int i = 0; i < res; ++i) {
                        // Voxel centre in world space; the CPU Object chain is
                        // uv = p.xy, p = hit point (then Mapping / UV transform).
                        Vec3 p(gmin.x + gsize.x * (i + 0.5f) / res,
                               gmin.y + gsize.y * (j + 0.5f) / res,
                               gmin.z + gsize.z * (k + 0.5f) / res);
                        Vec3 c = tex->valueAtCoord(Vec2(p.x, p.y), p);
                        r.textureTexels.push_back(GVec3(c.x, c.y, c.z));
                    }
                }
            }
        } else {
            desc.width = nx; desc.height = ny; desc.depth = nz;  // Generated 3D voxel
            Vec3 gmin  = tex->hasGeneratedBBox() ? tex->getGeneratedMin()
                                                 : Vec3(0.f, 0.f, 0.f);
            Vec3 gsize = tex->hasGeneratedBBox() ? tex->getGeneratedSize()
                                                 : Vec3(1.f, 1.f, 1.f);
            desc.genMin  = GVec3(gmin.x,  gmin.y,  gmin.z);
            desc.genSize = GVec3(gsize.x, gsize.y, gsize.z);
            r.textureTexels.reserve(r.textureTexels.size() +
                                    (size_t)nx * ny * nz);
            for (int k = 0; k < nz; ++k) {
                float pz = flat[2] ? flatG[2] : (k + 0.5f) / nz;
                for (int j = 0; j < ny; ++j) {
                    float py = flat[1] ? flatG[1] : (j + 0.5f) / ny;
                    for (int i = 0; i < nx; ++i) {
                        if ((flat[0] && i > 0) || (flat[1] && j > 0) || (flat[2] && k > 0)) {
                            // #1085: both layers of a flat axis are the same slice
                            // (depth must stay > 1: the shade path tells a 3D bake
                            // from a 2D UV image by depth > 1).
                            const size_t src = ((size_t)(flat[2] ? 0 : k) * ny + (flat[1] ? 0 : j)) * nx +
                                               (flat[0] ? 0 : i);
                            const GVec3 dup = r.textureTexels[(size_t)desc.offset + src];
                            r.textureTexels.push_back(dup);
                            continue;
                        }
                        float px = flat[0] ? flatG[0] : (i + 0.5f) / nx;
                        // #962: CPU Generated chain (uv = g.xy, p = g).
                        Vec3 c = tex->valueAtCoord(Vec2(px, py), Vec3(px, py, pz));
                        r.textureTexels.push_back(GVec3(c.x, c.y, c.z));
                    }
                }
            }
        }
        int texId = (int)r.textures.size();
        procBakeIdx[pkey] = texId;
        r.textures.push_back(desc);
        return texId;
    };
    // #1007 — per-hit procedural evaluation (replaces the 64^3 bake above for the
    // texture types astroray/procedural_tex.h implements). lowerProcLeaf copies a
    // CPU evaluator's parameters (the SAME struct its value() runs on);
    // lowerProcTexture adds the pkg277 CoordProgramTexture warp (program + at most
    // one texture input, CoordProgramTexture::value). -1 = no device evaluator.
    auto lowerProcLeaf = [](const Texture* t, astroray::proc::GProcTexture& g) -> bool {
        if (auto* n = dynamic_cast<const NoiseTextureCycles*>(t)) {
            g.kind = astroray::proc::G_PROC_NOISE; g.noise = n->procParams(); return true;
        }
        if (auto* w = dynamic_cast<const WaveTexture*>(t)) {
            g.kind = astroray::proc::G_PROC_WAVE; g.wave = w->procParams(); return true;
        }
        if (auto* v = dynamic_cast<const VoronoiTexture*>(t)) {
            g.kind = astroray::proc::G_PROC_VORONOI; g.voronoi = v->procParams(); return true;
        }
        return false;
    };
    std::unordered_map<const Texture*, int> procEvalIdx;
    auto lowerProcTexture = [&](Texture* t) -> int {
        auto it = procEvalIdx.find(t);
        if (it != procEvalIdx.end()) return it->second;
        astroray::proc::GProcTexture g;
        if (auto* cp = dynamic_cast<CoordProgramTexture*>(t)) {
            if (!lowerProcLeaf(cp->child().get(), g)) return -1;
            // VM input 0 is p and input 1 the warp texture (VM_MAX_TEX == 2); the CPU
            // ignores inputs past VM_MAX_TEX - 1, so more than one is not lowered.
            static_assert(astroray::svm::VM_MAX_TEX == 2, "warp lowering assumes 2 VM inputs");
            if (cp->numInputs() > 1) return -1;
            astroray::proc::GProcTexture gi;
            if (cp->numInputs() == 1 && !lowerProcLeaf(cp->getInput(0).get(), gi)) return -1;
            if (cp->numInputs() == 1) {
                g.warpInput = (int)r.procTextures.size();
                r.procTextures.push_back(gi);
            }
            auto pit = progIdx.find(t);  // a CoordProgramTexture* never aliases a ProgramTexture*
            if (pit != progIdx.end()) {
                g.warpProg = pit->second;
            } else {
                g.warpProg = (int)r.programs.size();
                progIdx[t] = g.warpProg;
                r.programs.push_back(cp->program());
            }
        } else if (!lowerProcLeaf(t, g)) {
            return -1;
        }
        const int id = (int)r.procTextures.size();
        r.procTextures.push_back(g);
        procEvalIdx[t] = id;
        return id;
    };
    // Descriptor of `evalTex` evaluated per hit at the point `pointSrc` resolves
    // (CPU: Texture::value(rec) of pointSrc -> coordinate mode, then the 3-D Mapping
    // M*p; the legacy UV transform never moves p). A direct procedural is its own
    // pointSrc; an op-VM input is evaluated at its PARENT's point, exactly as
    // ProgramTexture::eval samples inputs_[i]->value(uv, p) (the child's own
    // coordinate mode / Mapping are not applied on the CPU). Object (flat
    // geometry, the same gate as the bake) and Generated coordinates only; -1 =
    // fall back to the bake. Sets hasProgram: only <HasProgram=true> evaluates it.
    std::unordered_map<std::string, int> perHitIdx;
    auto perHitTexId = [&](Texture* pointSrc, Texture* evalTex) -> int {
        const Texture::CoordMode cmode = pointSrc->getCoordMode();
        if (replayRoots && cmode == Texture::CoordMode::Object) { replayBail = true; return -1; }  // pkg315
        const bool objMode = cmode == Texture::CoordMode::Object && curObjBox;
        if (!objMode && cmode != Texture::CoordMode::Generated) return -1;
        const std::string key = std::to_string(reinterpret_cast<uintptr_t>(pointSrc)) + "|" +
                                std::to_string(reinterpret_cast<uintptr_t>(evalTex));
        auto it = perHitIdx.find(key);
        if (it != perHitIdx.end()) return it->second;
        const int procId = lowerProcTexture(evalTex);
        if (procId < 0) return -1;
        GImageTexture desc;
        desc.offset = 0;
        desc.width = desc.height = desc.depth = 1;
        desc.procId = procId;
        if (objMode) {
            desc.objectCoord = 1;
        } else {  // the Generated bake's frame (bakeProceduralTexId)
            Vec3 gmin  = pointSrc->hasGeneratedBBox() ? pointSrc->getGeneratedMin()
                                                      : Vec3(0.f, 0.f, 0.f);
            Vec3 gsize = pointSrc->hasGeneratedBBox() ? pointSrc->getGeneratedSize()
                                                      : Vec3(1.f, 1.f, 1.f);
            desc.genMin  = GVec3(gmin.x,  gmin.y,  gmin.z);
            desc.genSize = GVec3(gsize.x, gsize.y, gsize.z);
        }
        if (pointSrc->hasMapping()) {
            desc.hasMapping = 1;
            const float* mm = pointSrc->getMappingMatrix();
            for (int i = 0; i < 12; ++i) desc.mapping[i] = mm[i];
        }
        const int texId = (int)r.textures.size();
        r.textures.push_back(desc);
        perHitIdx[key] = texId;
        r.hasProgram = true;
        return texId;
    };
    // Input t of an op-VM ProgramTexture → texId: an image (with the program's
    // Mapping, #825 key) or a procedural (#1007 per-hit evaluator, else the pkg190
    // bake, #818 Item 1). -1 = cannot upload (empty image / unbakeable coord).
    // Shared by base-colour and scalar programs (#846).
    // #990 — a shading attribute layer as a GPU descriptor (attrLayer = slot);
    // its corner texels are appended after the geometry walk. Deduped by layer.
    // Read only in the <HasProgram=true> kernel, hence hasProgram.
    auto uploadAttrTexId = [&](const AttributeTexture* at) -> int {
        // pkg315: attribute corners are per-triangle geometry data.
        if (replayRoots) { replayBail = true; return -1; }
        int slot = -1;
        for (size_t k = 0; k < r.attrLayers.size(); ++k)
            if (r.attrLayers[k] == at->layer()) slot = (int)k;
        if (slot < 0) {
            slot = (int)r.attrLayers.size();
            r.attrLayers.push_back(at->layer());
            r.attrCorners.emplace_back();
            r.attrMissing.push_back(at->missing());
        }
        const std::string k = "attr|" + std::to_string(slot);
        auto tit = texIdx.find(k);
        if (tit != texIdx.end()) return tit->second;
        GImageTexture desc;
        desc.offset = 0;           // patched after the geometry walk
        desc.width = desc.height = 1;
        desc.attrLayer = slot;
        desc.attrMissing = at->missing();
        const int texId = (int)r.textures.size();
        texIdx[k] = texId;
        r.textures.push_back(desc);
        r.hasTexture = true;
        r.hasProgram = true;
        return texId;
    };
    auto uploadProgInputTexId = [&](ProgramTexture* pt, int t) -> int {
        std::shared_ptr<Texture> child = pt->getInput(t);
        if (auto at = std::dynamic_pointer_cast<AttributeTexture>(child))  // #990
            return uploadAttrTexId(at.get());
        if (auto childImg = std::dynamic_pointer_cast<ImageTexture>(child))
            return childImg->getData().empty() ? -1 : uploadImageTexId(childImg.get(), pt);
        if (!child) return -1;
        const int perHit = perHitTexId(pt, child.get());
        return perHit >= 0 ? perHit : bakeProceduralTexId(child.get());
    };
    // #991 — switches met by getOrAddMat; their side-table entries are filled
    // after the geometry walk (children are added then, see below).
    std::vector<std::pair<int, std::shared_ptr<Material>>> lpPending;
    // #1072 -- (material id, partner) of every summable Add Shader met by getOrAddMat;
    // the partner is uploaded as a hidden material and linked after the geometry walk.
    std::vector<std::pair<int, std::shared_ptr<Material>>> addPending;
    // pkg314 — graph value programs (shader_graph.h). One descriptor per unique
    // GraphProgramTexture, appended to the scene arenas with rebased 32-bit
    // offsets. Each input becomes a texture id: an image with its own Mapping on
    // the descriptor (native input) or with none (computed-uv input), or a
    // procedural at its own point (#1007 per-hit evaluator, else the bake). An
    // input the GPU cannot sample fails the whole program on GPU, reported.
    std::unordered_map<const GraphProgramTexture*, int> graphIdx;
    auto uploadGraphProgram = [&](const GraphProgramTexture* gpt) -> int {
        auto git = graphIdx.find(gpt);
        if (git != graphIdx.end()) return git->second;
        std::vector<int> refs;
        for (size_t k = 0; k < gpt->numInputs(); ++k) {
            std::shared_ptr<Texture> child = gpt->getInput(k);
            int texId = -1;
            if (auto img = std::dynamic_pointer_cast<ImageTexture>(child)) {
                // The device image fetch (gpu_progInputTexel) rebuilds UV only: a
                // native image in another coordinate mode is not uploaded (reported
                // by the addon; CPU exact), never sampled at the wrong coordinate.
                const bool uvOk = img->getCoordMode() == Texture::CoordMode::UV;
                if (!img->getData().empty() && uvOk &&
                    !(gpt->inputIsCoord(k) && img->hasMapping()))
                    texId = uploadImageTexId(img.get(), img.get());
            } else if (auto at = std::dynamic_pointer_cast<AttributeTexture>(child)) {
                texId = uploadAttrTexId(at.get());  // #990 attribute layer input
            } else if (child && !gpt->inputIsCoord(k)) {
                // #1007 per-hit evaluator at the input's own point, else the bake.
                const int perHit = perHitTexId(child.get(), child.get());
                texId = perHit >= 0 ? perHit : bakeProceduralTexId(child.get());
            }
            if (texId < 0) {
                fprintf(stderr, "[pkg314] DEGRADED: graph program input %zu cannot be "
                                "sampled on the GPU (empty image / unbakeable coordinate "
                                "mode); the socket keeps its constant value on GPU\n", k);
                graphIdx[gpt] = -1;
                return -1;
            }
            refs.push_back(texId);
        }
        const astroray::sgraph::GraphProgramData& g = gpt->getProgram();
        astroray::sgraph::GraphProgramDesc d = g.desc;
        d.instrOffset = (uint32_t)r.graphInstrs.size();
        d.constOffset = (uint32_t)r.graphConsts.size();
        d.tableOffset = (uint32_t)r.graphTables.size();
        d.texOffset   = (uint32_t)r.graphTexRefs.size();
        const uint32_t dataBase = (uint32_t)r.graphTableData.size();
        r.graphInstrs.insert(r.graphInstrs.end(), g.instrs.begin(), g.instrs.end());
        r.graphConsts.insert(r.graphConsts.end(), g.consts.begin(), g.consts.end());
        for (astroray::sgraph::GraphTable t : g.tables) {
            t.offset += dataBase;
            r.graphTables.push_back(t);
        }
        r.graphTableData.insert(r.graphTableData.end(), g.tableData.begin(), g.tableData.end());
        r.graphTexRefs.insert(r.graphTexRefs.end(), refs.begin(), refs.end());
        const int id = (int)r.graphPrograms.size();
        r.graphPrograms.push_back(d);
        r.graphMaxSlots = std::max(r.graphMaxSlots, (int)d.numSlots);
        r.hasGraph = true;
        if (!refs.empty()) r.hasTexture = true;   // publishes c_wfTexBinding
        graphIdx[gpt] = id;
        return id;
    };
    auto getOrAddMat = [&](const std::shared_ptr<Material>& mKey) -> int {
        auto it = matIdx.find(mKey.get());
        if (it != matIdx.end()) return it->second;
        int id = (int)r.materials.size();
        matIdx[mKey.get()] = id;
        {   // pkg315: per-slot facts the material-only replay guards compare
            MaterialSlotInfo si;
            si.mat = mKey;
            si.key = mKey.get();
            const UvGate g = classifyUvGate(mKey);
            si.uvGate = static_cast<uint8_t>((g.textureUVConsumer ? 1 : 0) | (g.anisoPrincipled ? 2 : 0));
            si.emissive = mKey->isEmissive();
            si.transmissive = mKey->isTransmissive() && mKey->getIOR() > 1.0f;
            si.nameHash = materialNameHash(*mKey, id);
            r.slots.push_back(si);
        }
        {   // #994: OBJECT-coordinate bakes of this material cover its geometry.
            auto wb = matWorldBox.find(mKey.get());
            curObjBox = (wb != matWorldBox.end()) ? &wb->second : nullptr;
            auto gb = matGenBox.find(mKey.get());
            curGenBox = (gb != matGenBox.end()) ? &gb->second : nullptr;
        }
        // #991 — a Mix Shader with a Light Path Fac uploads its emission-context
        // leaf (child A, unwrapped) at its own id: every reader unaware of the
        // switch (light list, emitter evaluation) sees Cycles' emission child.
        std::shared_ptr<Material> mIn = mKey;
        if (dynamic_cast<astroray::LightPathMixMaterial*>(mKey.get())) {
            lpPending.emplace_back(id, mKey);
            while (auto* lp = dynamic_cast<astroray::LightPathMixMaterial*>(mIn.get()))
                mIn = lp->childA();
        }
        // pkg223 — unwrap a NormalMapped decorator: the GMaterial + base-colour
        // texture come from the INNER material; the tangent-space normal texture +
        // Strength ride the parallel side arrays (materialNormalTexId/Strength),
        // read ONLY in the GPU shade path's HasNormalPerturb=true kernel so
        // GMaterial stays 640 B. A bump-only decorator unwraps to the base with
        // normalTexId -1 (bump deferred — GPU renders the base BSDF).
        std::shared_ptr<Material> m = mIn;
        std::shared_ptr<Texture>  nmTex;
        float nmStrength = 1.0f;
        // pkg223b — Bump rides the same NormalMappedPlugin decorator; unwrap once
        // and read both the normal texture and the height (bump) texture.
        std::shared_ptr<Texture>  bmTex;
        float bmStrength = 1.0f;
        float bmDistance = 0.01f;
        if (auto inner = mIn->normalMapInner()) {
            m = inner;
            nmTex = mIn->normalMapTexture();
            nmStrength = mIn->normalMapStrength();
            bmTex = mIn->bumpMapTexture();
            bmStrength = mIn->bumpMapStrength();
            bmDistance = mIn->bumpMapDistance();
        }
        // #1072 -- Add Shader of a summable pair: child A uploads at this id (from A
        // itself, not the Add, whose forwarded ior/transmission may be B's) and child B
        // becomes the hidden partner attached after the geometry walk (addPending).
        std::shared_ptr<Material> addB;
        if (auto* am = dynamic_cast<astroray::AddMaterial*>(m.get())) {
            if (am->gpuSummable()) { addB = am->childB(); m = am->childA(); }
        }
        r.materials.push_back(convertMaterial(m));
        if (addB) addPending.emplace_back(id, addB);
        // pkg178 Stage-3b D4: flag scenes carrying a closure-graph Principled
        // material so the wavefront launchers select the <true> shade-kernel
        // instantiation. The predicate mirrors gpu_closure_graph_is_principled
        // (gpu_materials.h) exactly.
        const GMaterial& g = r.materials.back();
        if (g.type == GMAT_CLOSURE_GRAPH && g.closureCount >= 1 &&
            g.closures[0].type == GCLOSURE_PRINCIPLED) {
            r.hasPrincipled = true;
            // pkg253: a Principled material with alpha < 1 casts a
            // partially-transparent shadow — select the alpha-aware shadow
            // kernel. alpha == 1 leaves the fleet binary-occlusion path.
            if (g.principled.alpha < 1.0f)
                r.hasAlphaShadow = true;
        }
        // pkg225 Stage 4: flag scenes carrying any principled_hair material so the
        // driver publishes c_hasHair (setWavefrontHairEnabled), which gates the
        // shade kernel's hair uvTangent/hairV SoA restore. Non-hair scenes leave it
        // false → the fleet shade kernel is register-byte-identical.
        if (g.type == GMAT_HAIR_PRINCIPLED)
            r.hasHair = true;
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
        int progId = -1;
        // pkg314 — graph programs per slot (svm::ScalarSlot order, 4 = base colour).
        int graphSlots[astroray::sgraph::GRAPH_MAT_SLOTS];
        for (int s = 0; s < astroray::sgraph::GRAPH_MAT_SLOTS; ++s) graphSlots[s] = -1;
        // #826 — texIds of the program's inputs, OP_LOAD_TEX order (-1 = none).
        int progInTex[astroray::svm::VM_MAX_TEX];
        for (int t = 0; t < astroray::svm::VM_MAX_TEX; ++t) progInTex[t] = -1;
        // #962 — a textured Emission Color (TexturedLight) rides the SAME bake +
        // matTexId/program slots; the wavefront intersect stage (emissive hit)
        // and shadow stage (NEE) fetch it per hit. A SolidColor TexturedLight is
        // every untextured "light" material: left on the flat path (bit-identical).
        auto* tl  = dynamic_cast<TexturedLambertian*>(m.get());
        auto* tel = dynamic_cast<TexturedLight*>(m.get());
        std::shared_ptr<Texture> emitTex;
        if (tel && tel->getIntensity() > 0.0f &&
            !std::dynamic_pointer_cast<SolidColor>(tel->getTexture()))
            emitTex = tel->getTexture();
        // #988 — a native Principled with a per-texel Base Color rides the SAME
        // bake + matTexId/program slots as a textured lambertian, but the shade
        // path substitutes the texel into the Principled base colour on a local
        // GMaterial copy (HasProgram block) instead of the lambertian throughput
        // swap (the Principled lobes are not linear in base colour).
        std::shared_ptr<Texture> prBase = (!tl && !emitTex)
            ? m->scalarProgram(astroray::svm::SCALAR_BASE_COLOR) : nullptr;
        if (tl || emitTex || prBase) {
            std::shared_ptr<Texture> tex = tl ? tl->getTexture() : (emitTex ? emitTex : prBase);
            // pkg219b — a ProgramTexture (per-texel op-VM chain). GPU scope (#826):
            // 1..VM_MAX_TEX inputs, each an ImageTexture (uploaded with the
            // ProgramTexture's Mapping on its descriptor, #825 key) or a procedural
            // (issue #818 Item 1: pkg190 bake of the child's own evaluator, its
            // coord_mode + Mapping folded in). The compiled program is deduped into
            // r.programs; the shade path samples every input and runs svm_eval —
            // CPU parity by construction. If any input cannot upload (empty image,
            // unbakeable coord mode, > VM_MAX_TEX inputs) the whole program falls
            // through to the flat baseColor (GPU-degraded; CPU stays correct).
            // #962: an emitter's op-VM chain is NOT run per hit on GPU; it falls
            // through to the bakeProceduralTexId branch below, which bakes the
            // whole ProgramTexture (CPU evaluator, 64^2 / 64^3) -- keeps svm_eval
            // out of the intersect/shadow kernels' call graph (register cost).
            auto pt = (tl || prBase) ? std::dynamic_pointer_cast<ProgramTexture>(tex) : nullptr;
            // pkg314 — a graph value program on the base colour: evaluated by the
            // dedicated graph kernel, read by the <HasProgram=true> shade (lambertian
            // swap or the Principled base-colour override); texId stays -1.
            auto gpt = (tl || prBase) ? std::dynamic_pointer_cast<GraphProgramTexture>(tex)
                                      : nullptr;
            if (gpt) {
                graphSlots[astroray::sgraph::GRAPH_SLOT_BASE_COLOR] = uploadGraphProgram(gpt.get());
                if (graphSlots[astroray::sgraph::GRAPH_SLOT_BASE_COLOR] >= 0) {
                    r.hasTexture = true;
                    r.hasProgram = true;
                }
            } else if (pt) {
                const int numIn = (int)pt->numInputs();
                // #989: a Principled base-colour program may read only per-hit
                // shading inputs (Layer Weight -> Mix): zero textures, texId -1.
                bool inputsOk = (numIn >= 1 || prBase) && numIn <= astroray::svm::VM_MAX_TEX;
                for (int t = 0; inputsOk && t < numIn; ++t) {
                    progInTex[t] = uploadProgInputTexId(pt.get(), t);
                    inputsOk = progInTex[t] >= 0;
                }
                if (inputsOk) {
                    texId = progInTex[0];
                    // Dedup the compiled program by ProgramTexture*.
                    auto pit = progIdx.find(pt.get());
                    if (pit != progIdx.end()) {
                        progId = pit->second;
                    } else {
                        progId = (int)r.programs.size();
                        progIdx[pt.get()] = progId;
                        r.programs.push_back(pt->getProgram());
                    }
                    r.hasTexture = true;
                    r.hasProgram = true;
                } else {
                    // unsupported program input → texId/progId/progInTex stay -1
                    for (int t = 0; t < astroray::svm::VM_MAX_TEX; ++t) progInTex[t] = -1;
                }
            } else if (auto img = std::dynamic_pointer_cast<ImageTexture>(tex)) {
                if (!img->getData().empty()) {
                    texId = uploadImageTexId(img.get(), img.get());
                    r.hasTexture = true;
                }
            } else if (auto at = std::dynamic_pointer_cast<AttributeTexture>(tex)) {
                // #990 — a bare attribute layer on a surface consumer; an emitter
                // keeps its flat colour (the emission fetch has no attribute path).
                if (!emitTex) texId = uploadAttrTexId(at.get());
                else fprintf(stderr, "[#990] DEGRADED: an attribute-driven Emission Color "
                                     "renders flat on GPU\n");
            } else if (emitTex && std::dynamic_pointer_cast<GraphProgramTexture>(tex)) {
                // pkg314 — a graph program on an Emission Color is not evaluated by the
                // intersect / shadow stages and its inputs have per-input coordinates,
                // so no single bake domain exists: GPU keeps the texture mean
                // (reported below and by the addon); CPU evaluates it per hit.
                fprintf(stderr, "[pkg314] DEGRADED: Emission Color graph program renders "
                                "its texture mean on GPU\n");
            } else if (tex) {
                // pkg190 — bake a PROCEDURAL base-colour texture (checker / brick /
                // wave / magic / …) into the flat device texel buffer, then reuse
                // the pkg186 fetch machinery. Factored into bakeProceduralTexId
                // (issue #818 Item 1) which the ProgramTexture procedural-input path
                // shares; see that lambda for the coord-domain / Mapping / dedup
                // convention (Camera/Normal/… stay UNBAKED → -1, CPU is the
                // reference). The bake calls the material's OWN CPU evaluator, so
                // parity is exact-by-construction modulo grid resolution.
                // #1007: a surface consumer (lambertian / Principled base colour)
                // evaluates Noise / Wave / Voronoi per hit instead; an emitter keeps
                // the bake (the intersect/shadow kernels have no evaluator).
                if (!emitTex) texId = perHitTexId(tex.get(), tex.get());
                if (texId < 0) texId = bakeProceduralTexId(tex.get());
                if (texId >= 0) r.hasTexture = true;
            }
            // pkg190 fold-guard exactness (advisory #1, PR #590): a textured
            // lambertian's flat baseColor is only a fallback. Neutralize it so the
            // shade-path albedo swap (throughput *= texUp / upsample(baseColor))
            // divides by a FIXED neutral reference (upsample(1,1,1)) independent of
            // the material's own base chroma — an exact, unbiased swap even for a
            // saturated base. Net reflectance stays texUp, so the pkg186 image path
            // (previously dividing by a near-gray base) is unchanged.
            if ((texId >= 0 || graphSlots[astroray::sgraph::GRAPH_SLOT_BASE_COLOR] >= 0) && tl)
                r.materials[id].baseColor = GVec3(1.f, 1.f, 1.f);
            // #988 — the Principled base-colour override runs only in the
            // <HasProgram=true> shade kernel (even for a plain image / bake).
            if ((texId >= 0 || progId >= 0) && prBase) {
                r.hasTexture = true;
                r.hasProgram = true;
            }
            if (prBase && texId < 0 && progId < 0 &&
                graphSlots[astroray::sgraph::GRAPH_SLOT_BASE_COLOR] < 0)
                fprintf(stderr, "[#988] DEGRADED: Principled Base Color texture with an "
                                "unsupported GPU input (coordinate mode / empty image / "
                                "program inputs) renders the constant Base Color on GPU\n");
            // #962 — emitter: split getEmission() (= mean x intensity) into
            // baseColor = texture mean, emissionIntensity = intensity. Every flat
            // consumer reads the product (the same float product as the host),
            // while the per-hit fetch computes texel x emissionIntensity (CPU
            // TexturedLight::emitted = texel x intensity).
            // #962 (item 2): a baked field (procedural / op-VM) uses the mean of
            // the baked texels, so the flat fallback matches what the per-hit
            // fetch integrates; a plain image keeps its exact pixel mean.
            if (texId >= 0 && emitTex) {
                Vec3 avg = emitTex->average();
                if (!std::dynamic_pointer_cast<ImageTexture>(emitTex)) {
                    const GImageTexture& d = r.textures[texId];
                    const size_t n = (size_t)d.width * d.height * (d.depth > 1 ? d.depth : 1);
                    double sx = 0.0, sy = 0.0, sz = 0.0;
                    for (size_t k = 0; k < n; ++k) {
                        const GVec3& t = r.textureTexels[(size_t)d.offset + k];
                        sx += t.x; sy += t.y; sz += t.z;
                    }
                    if (n > 0) avg = Vec3((float)(sx / n), (float)(sy / n), (float)(sz / n));
                }
                r.materials[id].baseColor = GVec3(avg.x, avg.y, avg.z);
                r.materials[id].emissionIntensity = tel->getIntensity();
                r.hasEmissionTexture = true;
            }
            if (emitTex) {
                r.hasEmissionTextureRequested = true;
                if (texId < 0)   // #962 (item 4): unbakeable coord mode / empty image
                    fprintf(stderr, "[#962] DEGRADED: Emission Color texture with an "
                                    "unsupported GPU coordinate mode (Camera/Normal/Reflection/"
                                    "Window; Object on instanced-only geometry) renders its "
                                    "texture mean on GPU\n");
            }
        }
        // pkg223 — register the tangent-space normal texture (always a plain
        // ImageTexture from load_blender_image) on the parallel side arrays,
        // deduped via the same texIdx map. Mirrors the pkg186 ImageTexture upload;
        // the shade path's HasNormalPerturb kernel fetches it via matNormalTexId.
        // Uses the SAME device texel data as the CPU TextureManager texture, so
        // CPU/GPU parity holds regardless of the image's colour management.
        int normalTexId = -1;
        if (auto nimg = std::dynamic_pointer_cast<ImageTexture>(nmTex)) {
            if (!nimg->getData().empty()) {
                normalTexId = uploadImageTexId(nimg.get(), nimg.get());
                r.hasNormalPerturb = true;
            }
        }
        r.materialNormalTexId.push_back(normalTexId);
        r.materialNormalStrength.push_back(nmStrength);
        // pkg223b — register the height (bump) texture on the same side arrays,
        // deduped via the same texIdx map (mirrors the normal-map block above).
        int bumpTexId = -1;
        if (auto bimg = std::dynamic_pointer_cast<ImageTexture>(bmTex)) {
            if (!bimg->getData().empty()) {
                bumpTexId = uploadImageTexId(bimg.get(), bimg.get());
                r.hasNormalPerturb = true;  // Bump shares the HasNormalPerturb axis
            }
        }
        r.materialBumpTexId.push_back(bumpTexId);
        r.materialBumpStrength.push_back(bmStrength);
        r.materialBumpDistance.push_back(bmDistance);
        r.materialTextureId.push_back(texId);
        r.materialProgramId.push_back(progId);
        for (int t = 0; t < astroray::svm::VM_MAX_TEX; ++t)
            r.materialProgInputTexId.push_back(progInTex[t]);
        // pkg219d — scalar BSDF-parameter op-VM programs (Roughness/Metallic/
        // Transmission/IOR). A program with ONE input, image or procedural bake
        // (#846, same uploadProgInputTexId as base colour). Source + compiled
        // program dedup into the SAME textures/programs buffers (texIdx/procBakeIdx/
        // progIdx); matScalarTexId feeds the shade path's OWN per-slot texel fetch.
        // Multi-input or un-uploadable inputs fall through to -1 (GPU-degraded,
        // addon reports it; CPU stays correct). Read only in <HasProgram=true>.
        auto uploadProgramTexture = [&](const std::shared_ptr<ProgramTexture>& pt,
                                        int& outTexId, int& outProgId) {
            // #989: zero inputs = a program over per-hit shading inputs only
            // (Fresnel -> Math -> Metallic); matScalarTexId stays -1.
            if (pt->numInputs() > 1) return;
            if (pt->numInputs() == 1) {
                int inTex = uploadProgInputTexId(pt.get(), 0);
                if (inTex < 0) return;
                outTexId = inTex;
            }
            auto pit = progIdx.find(pt.get());
            if (pit != progIdx.end()) {
                outProgId = pit->second;
            } else {
                outProgId = (int)r.programs.size();
                progIdx[pt.get()] = outProgId;
                r.programs.push_back(pt->getProgram());
            }
            r.hasTexture = true;
            r.hasProgram = true;
        };
        for (int slot = 0; slot < astroray::svm::VM_SCALAR_SLOTS; ++slot) {
            int sTexId = -1, sProgId = -1;
            if (auto pt = std::dynamic_pointer_cast<ProgramTexture>(m->scalarProgram(slot))) {
                uploadProgramTexture(pt, sTexId, sProgId);
            } else if (auto gpt = std::dynamic_pointer_cast<GraphProgramTexture>(
                           m->scalarProgram(slot))) {
                graphSlots[slot] = uploadGraphProgram(gpt.get());   // pkg314
                if (graphSlots[slot] >= 0) r.hasProgram = true;
            }
            r.materialScalarProgId.push_back(sProgId);
            r.materialScalarTexId.push_back(sTexId);
        }
        for (int s = 0; s < astroray::sgraph::GRAPH_MAT_SLOTS; ++s)
            r.materialGraphProg.push_back(graphSlots[s]);
        return id;
    };

    // --- Geometry: pkg114 two-level (TLAS/BLAS) when the Renderer has instances,
    // else the existing single-level BVH. Both fill r.nodes/prims/triangles/spheres;
    // when instanced, r.tlas/instances/blas are also populated so the device
    // engages gpu_tlas_hit (otherwise it falls back to gpu_bvh_hit, unchanged). ---
    auto& cpuBvh = cpu.getBVH();
    // #994 — per-material world bbox of the flat (world-space) scene, read by
    // bakeProceduralTexId for OBJECT-coordinate procedurals. Instanced meshes are
    // object-space and not included (their materials stay unbaked, as before).
    // #1006: a triangle with object-local positions contributes their bbox (the
    // frame gpu_generatedCoord indexes the Object bake in).
    if (cpuBvh && !replayRoots) {
        for (const auto& h : cpuBvh->getPrimitives()) {
            const Material* pm = nullptr;
            AABB hb;
            bool haveBox = false;
            if (auto* t = dynamic_cast<Triangle*>(h.get())) {
                pm = t->getMaterial().get();
                Vec3 o0, o1, o2;
                if (t->getObjectLocal(o0, o1, o2)) {
                    hb = AABB(Vec3(std::min({o0.x, o1.x, o2.x}), std::min({o0.y, o1.y, o2.y}),
                                   std::min({o0.z, o1.z, o2.z})),
                              Vec3(std::max({o0.x, o1.x, o2.x}), std::max({o0.y, o1.y, o2.y}),
                                   std::max({o0.z, o1.z, o2.z})));
                    haveBox = true;
                }
            }
            else if (auto* s = dynamic_cast<Sphere*>(h.get())) pm = s->getMaterial().get();
            else if (auto* c = dynamic_cast<CurveSegment*>(h.get())) pm = c->getMaterial().get();
            if (!pm || !(haveBox || h->boundingBox(hb))) continue;
            auto it = matWorldBox.find(pm);
            if (it == matWorldBox.end()) matWorldBox.emplace(pm, hb);
            else it->second = it->second.merge(hb);
            GenFlatInfo& gi = matGenBox[pm];   // #1085
            AABB wb;  // world-space box (hb is object-local when haveBox)
            if (h->boundingBox(wb)) {
                gi.world = gi.haveWorld ? gi.world.merge(wb) : wb;
                gi.haveWorld = true;
            }
            Vec3 g0, g1, g2;
            if (auto* gt = dynamic_cast<Triangle*>(h.get());
                gt && gt->getGenerated(g0, g1, g2)) {
                const AABB gb(Vec3(std::min({g0.x, g1.x, g2.x}), std::min({g0.y, g1.y, g2.y}),
                                   std::min({g0.z, g1.z, g2.z})),
                              Vec3(std::max({g0.x, g1.x, g2.x}), std::max({g0.y, g1.y, g2.y}),
                                   std::max({g0.z, g1.z, g2.z})));
                gi.gen = gi.haveGen ? gi.gen.merge(gb) : gb;
                gi.haveGen = true;
            } else {
                gi.noGen = true;
            }
        }
    }
    if (replayRoots) {
        // pkg315: the walk-order slot roots, in slot order. A root that does not
        // land on its own slot id means two slots collapsed (slot order changed).
        for (size_t i = 0; i < replayRoots->size() && !replayBail; ++i)
            if (getOrAddMat((*replayRoots)[i]) != (int)i) replayBail = true;
        if (replayBail) return false;
    } else if (cpu.hasInstances()) {
        // pkg114 inc 3b — mixed: flat scene (cpuBvh) folded in as an identity BLAS.
        buildTwoLevelArrays(cpu, cpuBvh.get(), r, getOrAddMat);
    } else {
        if (!cpuBvh) throw std::runtime_error("BVH not built — call buildAcceleration() first");
        appendFlatScene(cpu, cpuBvh.get(), r, getOrAddMat);
    }
    r.slotsWalked = (int)r.materials.size();   // pkg315: Light Path switch children follow

    // #990: attribute layers first met after this point (a Light Path switch
    // child, below) have no corners: the walk already ran.
    const size_t attrLayersWalked = r.attrLayers.size();

    // #1072 -- link each summable Add Shader to its second child. The partner is not
    // referenced by geometry, so it is added here; GMaterial::addPartner holds index+1
    // (16 bits, so a scene past 65535 materials keeps child A only). The partner path
    // lives in the HasPrincipled=true shade kernels, so flag the scene to select them.
    auto linkAddPartners = [&]() {
        for (const auto& pa : addPending) {
            const int pid = getOrAddMat(pa.second);
            if (pid + 1 > 0xFFFF) {
                fprintf(stderr, "[#1072] DEGRADED: Add Shader partner index %d exceeds 16 bits; "
                                "GPU renders child A only\n", pid);
                continue;
            }
            r.materials[pa.first].addPartner = static_cast<uint16_t>(pid + 1);
            r.hasPrincipled = true;
            r.hasAddPartner = true;
        }
        addPending.clear();
    };
    linkAddPartners();

    // #991 — Light Path switch side table. Child materials are not referenced
    // by geometry, so they are added here (inheriting the switch's world bbox
    // for OBJECT-coordinate bakes); nested switches append to lpPending as
    // they are met, so the loop runs until it drains.
    if (!lpPending.empty()) {
        using astroray::LightPathMixMaterial;
        using astroray::lightpath::GLightPathSwitch;
        std::vector<std::pair<int, GLightPathSwitch>> entries;
        for (size_t k = 0; k < lpPending.size(); ++k) {
            const int self = lpPending[k].first;
            const std::shared_ptr<Material> sw = lpPending[k].second;
            auto* lp = static_cast<LightPathMixMaterial*>(sw.get());
            auto wb = matWorldBox.find(sw.get());
            auto addChild = [&](const std::shared_ptr<Material>& c) {
                if (wb != matWorldBox.end() && !matWorldBox.count(c.get()))
                    matWorldBox.emplace(c.get(), wb->second);
                auto gwb = matGenBox.find(sw.get());   // #1085
                if (gwb != matGenBox.end() && !matGenBox.count(c.get()))
                    matGenBox.emplace(c.get(), gwb->second);
                return getOrAddMat(c);
            };
            std::shared_ptr<Material> leafA = sw;   // what `self` uploaded
            while (auto* l = dynamic_cast<LightPathMixMaterial*>(leafA.get()))
                leafA = l->childA();
            std::shared_ptr<Material> leafS = sw;   // what shadow rays see
            const astroray::lightpath::PathContext shadowCtx =
                astroray::lightpath::shadow_context(0);
            while (auto* l = dynamic_cast<LightPathMixMaterial*>(leafS.get()))
                leafS = l->select(shadowCtx);
            GLightPathSwitch e;
            e.aId = dynamic_cast<LightPathMixMaterial*>(lp->childA().get())
                  ? addChild(lp->childA()) : self;
            e.bId = addChild(lp->childB());
            e.shadowId = (leafS == leafA) ? self : addChild(leafS);
            e.output = (int)lp->output();
            entries.emplace_back(self, e);
        }
        r.lightPathSwitch.resize(r.materials.size());
        for (int i = 0; i < (int)r.materials.size(); ++i)
            r.lightPathSwitch[i] = GLightPathSwitch{ i, -1, i, 0 };
        for (const auto& kv : entries) r.lightPathSwitch[kv.first] = kv.second;
        r.hasLightPath = true;
        // A switch child may itself be an Add Shader: link it, then give the partner
        // materials it appended identity switch entries (never hit by a ray).
        linkAddPartners();
        for (int i = (int)r.lightPathSwitch.size(); i < (int)r.materials.size(); ++i)
            r.lightPathSwitch.push_back(GLightPathSwitch{ i, -1, i, 0 });
    }
    if (replayBail) return false;   // pkg315: a switch child hit a replay bail-out
    // #991 — a program reading a Light Path output (OP_SHADING >= SH_LIGHT_PATH)
    // needs the per-path lp_state maintained as well.
    for (const auto& prog : r.programs) {
        for (int k = 0; k < prog.numInstr && k < astroray::svm::VM_MAX_INSTR; ++k) {
            if (prog.code[k].op == astroray::svm::OP_SHADING &&
                prog.code[k].imm >= astroray::svm::SH_LIGHT_PATH)
                r.hasLightPath = true;
        }
    }
    // #36 — an indirect-only object hides from camera rays only while the path still
    // carries LPF_CAMERA (Cycles PATH_RAY_CAMERA survives transparent passes), which
    // the intersect stage reads from lp_state: have the shade kernel maintain it. Only
    // scenes with an indirect-only object take the HasProgram variant; every other
    // scene's kernels are untouched (the intersect/shade kernels gain no code for it).
    if (r.hasIndirectOnly) r.hasLightPath = true;
    // The lp_state update lives in the HasProgram shade kernel (which also reads
    // the texture binding: publish it too, with all-(-1) material tables).
    if (r.hasLightPath) {
        r.hasProgram = true;
        r.hasTexture = true;
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

    // pkg315: the material-only replay ends here — everything below is the
    // geometry / light / environment domain, which a material edit cannot change.
    if (replayRoots) {
        if (replayBail) return false;
        texGeomFlags(r, r.hasGenBake, r.hasObjCoord);
        return true;
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
    // #962 — instanced prims (global ids past the flat scene) keep the flat mean
    // textured emission: the hit point is world-space, their triangles object-space.
    if (cpu.hasInstances()) {
        r.emissionFlatPrims = (int)orderedPrims.size();
        bool instancedTexEmitter = false;
        for (size_t p = orderedPrims.size(); r.hasEmissionTexture && p < r.prims.size(); ++p) {
            const GPrimitive& gp = r.prims[p];
            int mid = gp.type == GPRIM_TRIANGLE ? r.triangles[gp.index].materialId
                    : gp.type == GPRIM_SPHERE   ? r.spheres[gp.index].materialId : -1;
            if (mid >= 0 && r.materials[mid].type == GMAT_DIFFUSE_LIGHT &&
                r.materialTextureId[mid] >= 0) {
                instancedTexEmitter = true;
                break;
            }
        }
        if (instancedTexEmitter)
            fprintf(stderr, "[#962] DEGRADED: a textured Emission Color on an instanced "
                            "mesh renders its texture mean on GPU\n");
    }

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
            // pkg218: the legacy hittable-sun conversion has no EmissionSpectrum
            // (emittedRadiance() is a plain RGB) — always the RGB fallback.
            gd.emissionProfileIndex = -1;
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
            gd.emissionProfileIndex = -1;  // pkg218 default: RGB fallback
            gd.cameraVisible = (L && L->cameraVisible) ? 1 : 0;  // #903
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
                gd.hasDiscProfile = p.hasDiscProfile ? 1 : 0;  // #946
                gd.discBottomRGB = GVec3(p.discBottomRGB.x, p.discBottomRGB.y, p.discBottomRGB.z);
                gd.discTopRGB = GVec3(p.discTopRGB.x, p.discTopRGB.y, p.discTopRGB.z);
                gd.discHalfAngle = p.discHalfAngle;
                // pkg218: non-RGB emission modes (blackbody/measured_spd/
                // composite) carry a baked device SPD (see light.h
                // DeviceLightParams::emissionProfileSamples). Register it into
                // the flat upload table and stamp the row index; RGB mode
                // (exactIlluminant true) leaves emissionProfileSamples empty
                // and keeps the -1 default (existing RGBIlluminant path).
                if (!p.emissionProfileSamples.empty()) {
                    if ((int)p.emissionProfileSamples.size() != G_EMISSION_SAMPLES) {
                        fprintf(stderr,
                                "[CUDA] WARNING: emission profile size %zu != "
                                "G_EMISSION_SAMPLES %d; skipping device SPD "
                                "(RGB fallback)\n",
                                p.emissionProfileSamples.size(), G_EMISSION_SAMPLES);
                    } else {
                        gd.emissionProfileIndex =
                            (int)(r.emissionProfileTable.size() / G_EMISSION_SAMPLES);
                        r.emissionProfileTable.insert(r.emissionProfileTable.end(),
                            p.emissionProfileSamples.begin(),
                            p.emissionProfileSamples.end());
                    }
                }
                // pkg276: IES profile -> side table entry j (Cycles packed layout).
                if (!p.iesPacked.empty()) {
                    GIESLight none{};
                    none.offset = -1;
                    if (r.iesLights.size() <= j) r.iesLights.resize(j + 1, none);
                    GIESLight& e = r.iesLights[j];
                    e.offset = (int)r.iesTable.size();
                    for (int a = 0; a < 3; ++a) {
                        e.fx[a] = p.iesFrame[a];
                        e.fy[a] = p.iesFrame[3 + a];
                        e.fz[a] = p.iesFrame[6 + a];
                    }
                    r.iesTable.insert(r.iesTable.end(), p.iesPacked.begin(), p.iesPacked.end());
                }
            } else {
                // Unsupported type (e.g. Background): keep the CDF slot aligned
                // but flag invalid so the device sampler yields no contribution.
                gd.kind = -1;
            }
            r.dedicatedLights.push_back(gd);
        }
        // pkg218: row count for uploadEmissionProfileTable (scene_upload.cu
        // callers) — mirrors r.profileCount's dedicated field above.
        r.emissionProfileCount = (int)(r.emissionProfileTable.size() / G_EMISSION_SAMPLES);
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

            // pkg202: a converted legacy sun reindexes r.lights (the sun no
            // longer occupies a hittable slot), so the CPU tree's per-emitter
            // lightIndex values no longer map onto r.lights. Fall back to the
            // power-CDF selection (the documented behavior whenever the tree is
            // not uploadable) rather than upload a mis-indexed tree.
            // #859: dedicated emitters ARE uploadable — encoded as
            // GLightTreeEmitter::lightIndex = -(j+1) for r.dedicatedLights[j]
            // (1:1 with ll2.getDedicatedLights() while no legacy sun was
            // converted). Refusing them made the GPU fall back to the power CDF
            // while the CPU used the tree; a sun's power-CDF weight (solid-angle
            // scaled) is ~1e-5 of any mesh emitter, so the GPU starved the sun.
            bool uploadable = !convertedLegacySun;
            for (const auto& e : temitters) {
                const int limit = e.isDedicated ? (int)r.dedicatedLights.size()
                                                : (int)r.lights.size();
                if (e.lightIndex < 0 || e.lightIndex >= limit) {
                    uploadable = false;
                    break;
                }
            }
            if (!uploadable) {
                fprintf(stderr, "[CUDA] light tree not uploadable (converted "
                                "legacy sun or unmapped emitter) - GPU NEE falls back to "
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
                            const astroray::LightTreeEmitter& te = temitters[n.firstEmitter + k];
                            // #859: dedicated lights encoded as -(j+1).
                            GLightTreeEmitter ge{te.isDedicated ? -(te.lightIndex + 1) : te.lightIndex,
                                                 se.trail};
                            // #851: bounds for per-emitter leaf selection.
                            ge.bboxMin   = GVec3(te.bbox.min.x, te.bbox.min.y, te.bbox.min.z);
                            ge.bboxMax   = GVec3(te.bbox.max.x, te.bbox.max.y, te.bbox.max.z);
                            ge.bconeAxis = GVec3(te.bcone.axis.x, te.bcone.axis.y, te.bcone.axis.z);
                            ge.thetaO    = te.bcone.theta_o;
                            ge.thetaE    = te.bcone.theta_e;
                            ge.energy    = te.energy;
                            r.lightTreeEmitters[n.firstEmitter + k] = ge;
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
                    // #859: slots [0, numLights) = GLight, then one per
                    // dedicated light at numLights + j.
                    r.lightToEmitter.assign(r.lights.size() + r.dedicatedLights.size(), -1);
                    for (size_t ei = 0; ei < r.lightTreeEmitters.size(); ++ei) {
                        int li = r.lightTreeEmitters[ei].lightIndex;
                        int slot = li >= 0 ? li : (int)r.lights.size() + (-li - 1);
                        r.lightToEmitter[slot] = (int)ei;
                    }
                }
            }
        }
    }

    // --- pkg88-C.0: motion vertices for deformation motion blur ---
    // The GPU buffer is the concatenation of the CPU per-batch storage, in
    // batch order — matching the motionPtrToOffset mapping built during the
    // primitive walk above (each GTriangle::motionOffset indexes into this).
    for (const auto& batch : cpu.getMotionVertexBatches()) {
        for (const auto& v : batch)
            r.motionVertices.push_back(GVec3(v.x, v.y, v.z));
    }

    // --- #990: attribute-layer corner slices (descriptor offsets patched) ---
    // #1047: layers first met after the geometry walk (a Light Path switch child
    // materialised in the lpPending loop) get their corners from a second pass over
    // the flat scene's triangles. The flat scene is uploaded first in both layouts,
    // so its ordered-prim Triangle order is the uploaded triangle index.
    if (r.attrLayers.size() > attrLayersWalked && cpuBvh) {
        size_t ti = 0;
        for (const auto& h : cpuBvh->getPrimitives())
            if (auto* tri = dynamic_cast<Triangle*>(h.get()))
                appendAttrCorners(*tri, ti++, attrLayersWalked, r);
    }
    for (size_t k = 0; k < r.attrLayers.size(); ++k) {
        auto& v = r.attrCorners[k];
        const float m = r.attrMissing[k];
        v.resize(r.triangles.size() * 3, GVec3(m, m, m));
        const int offset = (int)r.textureTexels.size();
        r.textureTexels.insert(r.textureTexels.end(), v.begin(), v.end());
        for (auto& d : r.textures)
            if (d.attrLayer == (int)k) d.offset = offset;
        std::vector<GVec3>().swap(v);
    }
    if (cpu.hasInstances() && !r.attrLayers.empty())
        fprintf(stderr, "[#990] DEGRADED: shading attributes on instanced meshes read 0 "
                        "on GPU (object-space BLAS triangles; the addon flattens objects "
                        "whose materials read attributes)\n");

    // --- #847: per-vertex Generated coords ---
    // Only read by the Generated 3D-bake fetch (depth > 1) and the #1007 per-hit
    // Generated evaluation (procId >= 0, not objectCoord). Instanced BLAS
    // triangles are object-local while the fetch uses the world hit point, so
    // instanced scenes keep the per-texture bbox frame (pre-#847 behaviour).
    texGeomFlags(r, r.hasGenBake, r.hasObjCoord);   // pkg315: shared with the replay
    {
        const bool hasGenBake = r.hasGenBake;
        if (!hasGenBake || cpu.hasInstances()) {
            r.triGenerated.clear();
        } else if (!r.triGenerated.empty()) {
            const float nan = std::numeric_limits<float>::quiet_NaN();
            r.triGenerated.resize(r.triangles.size() * 3, GVec3(nan, nan, nan));
        }
    }
    // --- #1006: per-vertex OBJECT-local positions ---
    // Only read for OBJECT-coordinate descriptors (gpu_objectCoord). Instanced
    // BLAS triangles never carry them (the addon flattens Object-coordinate
    // materials), so their NaN entries fall back to the world point.
    {
        const bool hasObjCoord = r.hasObjCoord;
        if (!hasObjCoord) {
            r.triObjectLocal.clear();
        } else if (!r.triObjectLocal.empty()) {
            const float nan = std::numeric_limits<float>::quiet_NaN();
            r.triObjectLocal.resize(r.triangles.size() * 3, GVec3(nan, nan, nan));
        }
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

    return true;
}

// Builds host-side flat arrays from the CPU Renderer + Camera.
// The caller (cuda_renderer.cu) then cudaMalloc/cudaMemcpy them.
SceneUploadResult buildSceneArrays(const Renderer& cpu, const Camera* cam) {
    SceneUploadResult r;
    buildSceneArraysImpl(cpu, cam, r, nullptr);
    return r;
}

// pkg315 (#1067): see gpu_scene_upload.h.
bool buildMaterialDomain(const Renderer& cpu, const SceneUploadResult& cached,
                         const std::vector<MaterialSwap>& swaps, SceneUploadResult& out) {
    const size_t walked = static_cast<size_t>(cached.slotsWalked);
    if (cached.slots.size() != cached.materials.size() || walked > cached.slots.size())
        return false;
    // Slot roots in slot order, following each rebind (old pointer -> new material).
    std::vector<const Material*> keys(walked);
    std::vector<std::shared_ptr<Material>> roots(walked);
    for (size_t i = 0; i < walked; ++i) {
        keys[i] = cached.slots[i].key;
        roots[i] = cached.slots[i].mat.lock();
    }
    for (const MaterialSwap& sw : swaps) {
        std::shared_ptr<Material> nm = sw.newMat.lock();
        for (size_t i = 0; i < walked; ++i) {
            if (keys[i] != sw.oldKey) continue;
            if (!nm) return false;
            roots[i] = nm;
            keys[i] = nm.get();
        }
    }
    for (const auto& rt : roots)
        if (!rt) return false;   // a slot material was released without a recorded swap

    if (!buildSceneArraysImpl(cpu, nullptr, out, &roots)) return false;

    // Guards: anything the geometry arrays on the device depend on must be unchanged.
    if (out.materials.size() != cached.materials.size() ||
        out.slots.size() != cached.slots.size() || out.slotsWalked != cached.slotsWalked)
        return false;
    for (size_t i = 0; i < walked; ++i) {
        const MaterialSlotInfo& a = cached.slots[i];
        const MaterialSlotInfo& b = out.slots[i];
        if (a.uvGate != b.uvGate) return false;            // per-triangle hasUV / uv upload
        if (a.nameHash != b.nameHash) return false;        // per-triangle materialHash
        if (a.transmissive != b.transmissive) return false;  // smsCasters
    }
    for (size_t i = 0; i < out.materials.size(); ++i) {
        const GMaterial& ga = cached.materials[i];
        const GMaterial& gb = out.materials[i];
        if ((ga.type == GMAT_HAIR_PRINCIPLED) != (gb.type == GMAT_HAIR_PRINCIPLED))
            return false;                                  // hair routing
        const MaterialSlotInfo& a = cached.slots[i];
        const MaterialSlotInfo& b = out.slots[i];
        if (a.emissive || b.emissive) {                    // light list / GAreaLight emission
            if (a.emissive != b.emissive || ga.baseColor.x != gb.baseColor.x ||
                ga.baseColor.y != gb.baseColor.y || ga.baseColor.z != gb.baseColor.z ||
                ga.emissionIntensity != gb.emissionIntensity ||
                ga.anisotropicRotation != gb.anisotropicRotation)  // #1099 two-sided flag
                return false;
        }
    }
    if (out.hasGenBake != cached.hasGenBake || out.hasObjCoord != cached.hasObjCoord)
        return false;                                      // triGenerated / triObjectLocal upload
    if (out.hasEmissionTexture || out.hasEmissionTextureRequested ||
        cached.hasEmissionTexture || cached.hasEmissionTextureRequested)
        return false;                                      // textured emitters keep the full path
    return true;
}

void adoptMaterialDomain(SceneUploadResult& dst, SceneUploadResult&& src) {
    dst.materials = std::move(src.materials);
    dst.slots = std::move(src.slots);
    dst.slotsWalked = src.slotsWalked;
    dst.hasGenBake = src.hasGenBake;
    dst.hasObjCoord = src.hasObjCoord;
    dst.hasPrincipled = src.hasPrincipled;
    dst.hasAlphaShadow = src.hasAlphaShadow;
    dst.hasHair = src.hasHair;
    dst.hasDispersive = src.hasDispersive;
    dst.textures = std::move(src.textures);
    dst.textureTexels = std::move(src.textureTexels);
    dst.materialTextureId = std::move(src.materialTextureId);
    dst.hasTexture = src.hasTexture;
    dst.hasEmissionTexture = src.hasEmissionTexture;
    dst.hasEmissionTextureRequested = src.hasEmissionTextureRequested;
    dst.materialNormalTexId = std::move(src.materialNormalTexId);
    dst.materialNormalStrength = std::move(src.materialNormalStrength);
    dst.materialBumpTexId = std::move(src.materialBumpTexId);
    dst.materialBumpStrength = std::move(src.materialBumpStrength);
    dst.materialBumpDistance = std::move(src.materialBumpDistance);
    dst.hasNormalPerturb = src.hasNormalPerturb;
    dst.programs = std::move(src.programs);
    dst.materialProgramId = std::move(src.materialProgramId);
    dst.materialProgInputTexId = std::move(src.materialProgInputTexId);
    dst.hasProgram = src.hasProgram;
    dst.materialScalarProgId = std::move(src.materialScalarProgId);
    dst.materialScalarTexId = std::move(src.materialScalarTexId);
    dst.procTextures = std::move(src.procTextures);
    dst.graphInstrs = std::move(src.graphInstrs);
    dst.graphConsts = std::move(src.graphConsts);
    dst.graphTables = std::move(src.graphTables);
    dst.graphTableData = std::move(src.graphTableData);
    dst.graphTexRefs = std::move(src.graphTexRefs);
    dst.graphPrograms = std::move(src.graphPrograms);
    dst.materialGraphProg = std::move(src.materialGraphProg);
    dst.hasGraph = src.hasGraph;
    dst.graphMaxSlots = src.graphMaxSlots;
    dst.lightPathSwitch = std::move(src.lightPathSwitch);
    dst.hasLightPath = src.hasLightPath;
    dst.profileTable = std::move(src.profileTable);
    dst.profileCount = src.profileCount;
}
