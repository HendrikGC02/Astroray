#pragma once

// GPU-portable POD types for CUDA path tracer.
// This header is included by both .cu files (compiled with nvcc) and
// pure C++ translation units.  NO std:: headers, NO virtual functions.

#include <cstdint>

#ifdef __CUDACC__
#  define HD __host__ __device__
#  include <cuda_runtime.h>   // sqrtf, fmaxf, etc. in device code
#else
#  define HD
#  include <cmath>
#endif

// ---------------------------------------------------------------------------
// GVec3
// ---------------------------------------------------------------------------
struct GVec3 {
    float x, y, z;

    HD GVec3() : x(0.f), y(0.f), z(0.f) {}
    HD GVec3(float v) : x(v), y(v), z(v) {}
    HD GVec3(float a, float b, float c) : x(a), y(b), z(c) {}

    HD GVec3 operator+(const GVec3& o) const { return {x+o.x, y+o.y, z+o.z}; }
    HD GVec3 operator-(const GVec3& o) const { return {x-o.x, y-o.y, z-o.z}; }
    HD GVec3 operator-()               const { return {-x, -y, -z}; }
    HD GVec3 operator*(float s)        const { return {x*s, y*s, z*s}; }
    HD GVec3 operator*(const GVec3& o) const { return {x*o.x, y*o.y, z*o.z}; }
    HD GVec3 operator/(float s)        const { float inv = 1.f/s; return {x*inv, y*inv, z*inv}; }

    HD GVec3& operator+=(const GVec3& o) { x+=o.x; y+=o.y; z+=o.z; return *this; }
    HD GVec3& operator-=(const GVec3& o) { x-=o.x; y-=o.y; z-=o.z; return *this; }
    HD GVec3& operator*=(float s)        { x*=s;   y*=s;   z*=s;   return *this; }
    HD GVec3& operator*=(const GVec3& o) { x*=o.x; y*=o.y; z*=o.z; return *this; }
    HD GVec3& operator/=(float s)        { x/=s;   y/=s;   z/=s;   return *this; }

    HD float dot(const GVec3& o)   const { return x*o.x + y*o.y + z*o.z; }
    HD GVec3 cross(const GVec3& o) const {
        return {y*o.z - z*o.y, z*o.x - x*o.z, x*o.y - y*o.x};
    }
    HD float length2() const { return dot(*this); }
    HD float length()  const { return sqrtf(length2()); }
    HD GVec3 normalized() const {
        float l = length();
        return l > 0.f ? *this * (1.f/l) : GVec3(0.f);
    }

    HD float maxComponent() const {
        return x > y ? (x > z ? x : z) : (y > z ? y : z);
    }
    HD bool operator!=(const GVec3& o) const {
        return x != o.x || y != o.y || z != o.z;
    }
    HD bool operator==(const GVec3& o) const {
        return x == o.x && y == o.y && z == o.z;
    }

    // Array subscript (matches CPU Vec3 convention)
    HD float  operator[](int i) const { return (&x)[i]; }
    HD float& operator[](int i)       { return (&x)[i]; }
};

// pkg178 Stage-3b PR-4b — minimal 2D POD for per-triangle UVs (anisotropy).
struct GVec2 {
    float x, y;
    HD GVec2() : x(0.f), y(0.f) {}
    HD GVec2(float a, float b) : x(a), y(b) {}
};

HD inline GVec3 operator*(float s, const GVec3& v) { return v * s; }
HD inline float luminance(const GVec3& c) {
    return 0.2126f*c.x + 0.7152f*c.y + 0.0722f*c.z;
}
HD inline GVec3 gvec3_min(const GVec3& a, const GVec3& b) {
    return { a.x < b.x ? a.x : b.x,
             a.y < b.y ? a.y : b.y,
             a.z < b.z ? a.z : b.z };
}
HD inline GVec3 gvec3_max(const GVec3& a, const GVec3& b) {
    return { a.x > b.x ? a.x : b.x,
             a.y > b.y ? a.y : b.y,
             a.z > b.z ? a.z : b.z };
}

// ---------------------------------------------------------------------------
// Compact sampled-spectrum payload for the CUDA material path.
// RGB remains the framebuffer representation, but materials now carry the same
// four sampled wavelengths through GPU BSDF/emitter dispatch that the CPU
// spectral path uses.
// ---------------------------------------------------------------------------
static constexpr int G_SPECTRUM_SAMPLES = 4;
static constexpr float G_LAMBDA_MIN = 360.f;
static constexpr float G_LAMBDA_MAX = 830.f;

struct GSampledWavelengths {
    float lambda[G_SPECTRUM_SAMPLES];
    float pdf[G_SPECTRUM_SAMPLES];

    HD GSampledWavelengths() {
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
            lambda[i] = G_LAMBDA_MIN;
            pdf[i] = 1.f / (G_LAMBDA_MAX - G_LAMBDA_MIN);
        }
    }

    HD void terminateSecondary() {
        for (int i = 1; i < G_SPECTRUM_SAMPLES; ++i) {
            lambda[i] = lambda[0];
            pdf[i] = 0.f;
        }
    }
};

// Compile-time size check: GSampledWavelengths must match the host-side
// astroray::SampledWavelengths layout (2 × std::array<float, 4> = 32 bytes).
// This guard catches accidental additions to either struct that would break
// the semantic correspondence between CPU and GPU spectral paths.
static_assert(sizeof(GSampledWavelengths) == 32,
              "GSampledWavelengths size mismatch — must be 32 bytes (8 floats)");

struct GSampledSpectrum {
    float v[G_SPECTRUM_SAMPLES];

    HD GSampledSpectrum() {
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) v[i] = 0.f;
    }
    HD explicit GSampledSpectrum(float s) {
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) v[i] = s;
    }

    HD float& operator[](int i) { return v[i]; }
    HD float operator[](int i) const { return v[i]; }

    HD GSampledSpectrum operator+(const GSampledSpectrum& o) const {
        GSampledSpectrum r;
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) r.v[i] = v[i] + o.v[i];
        return r;
    }
    HD GSampledSpectrum operator-(const GSampledSpectrum& o) const {
        GSampledSpectrum r;
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) r.v[i] = v[i] - o.v[i];
        return r;
    }
    HD GSampledSpectrum operator*(const GSampledSpectrum& o) const {
        GSampledSpectrum r;
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) r.v[i] = v[i] * o.v[i];
        return r;
    }
    HD GSampledSpectrum operator*(float s) const {
        GSampledSpectrum r;
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) r.v[i] = v[i] * s;
        return r;
    }
    HD GSampledSpectrum operator/(float s) const {
        float inv = 1.f / s;
        return (*this) * inv;
    }
    HD GSampledSpectrum& operator+=(const GSampledSpectrum& o) {
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) v[i] += o.v[i];
        return *this;
    }
    HD GSampledSpectrum& operator-=(const GSampledSpectrum& o) {
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) v[i] -= o.v[i];
        return *this;
    }
    HD GSampledSpectrum& operator*=(const GSampledSpectrum& o) {
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) v[i] *= o.v[i];
        return *this;
    }
    HD GSampledSpectrum& operator*=(float s) {
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) v[i] *= s;
        return *this;
    }
    HD GSampledSpectrum& operator/=(float s) {
        float inv = 1.f / s;
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) v[i] *= inv;
        return *this;
    }
    HD float maxValue() const {
        float m = v[0];
        for (int i = 1; i < G_SPECTRUM_SAMPLES; ++i) if (v[i] > m) m = v[i];
        return m;
    }
};

static_assert(sizeof(GSampledSpectrum) == 16,
              "GSampledSpectrum size mismatch — must be 16 bytes (4 floats)");

HD inline GSampledSpectrum operator*(float s, const GSampledSpectrum& x) { return x * s; }

// ---------------------------------------------------------------------------
// GRay
// ---------------------------------------------------------------------------
struct GRay {
    GVec3 origin, direction;
    // pkg88-C.0: shutter time in [0,1]. Default 0 = shutter open; static
    // geometry ignores it. Mirrors CPU Ray::time (raytracer.h).
    float time = 0.f;
    HD GRay() {}
    HD GRay(const GVec3& o, const GVec3& d) : origin(o), direction(d.normalized()) {}
    HD GRay(const GVec3& o, const GVec3& d, float t)
        : origin(o), direction(d.normalized()), time(t) {}
    HD GVec3 at(float t) const { return origin + direction * t; }
};

// ---------------------------------------------------------------------------
// GAABB
// ---------------------------------------------------------------------------
struct GAABB {
    GVec3 min, max;

    HD bool hit(const GRay& r, float tMin, float tMax) const {
        for (int a = 0; a < 3; ++a) {
            float invD = 1.0f / r.direction[a];
            float t0 = (min[a] - r.origin[a]) * invD;
            float t1 = (max[a] - r.origin[a]) * invD;
            if (invD < 0.f) { float tmp = t0; t0 = t1; t1 = tmp; }
            if (t0 > tMin) tMin = t0;
            if (t1 < tMax) tMax = t1;
            if (tMax <= tMin) return false;
        }
        return true;
    }
};

// ---------------------------------------------------------------------------
// Flattened BVH node — mirrors LinearBVHNode from raytracer.h
// Kept at 32 bytes (2 cache lines on Ampere) for coalesced access.
// ---------------------------------------------------------------------------
struct GBVHNode {
    GAABB    bounds;            // 24 bytes
    union {
        int primitivesOffset;   // leaf: first primitive index
        int secondChildOffset;  // interior: index of right child
    };                          // 4 bytes
    uint16_t nPrimitives;       // 0 = interior node
    uint8_t  axis;
    uint8_t  pad;
};                              // total = 32 bytes

// ---------------------------------------------------------------------------
// Primitive descriptors
// ---------------------------------------------------------------------------
// pkg85-C: GPRIM_SKIP is a placeholder used for CPU-only primitives
// (e.g., DistantLight) that share the BVH with GPU-renderable prims.
// scene_upload.cu pushes one of these for every orderedPrims entry that
// isn't a Sphere or Triangle, so r.prims stays index-aligned with the
// BVH's primitivesOffset and with GLight.primitiveIndex. gpu_bvh_hit
// and the area-light sampler treat GPRIM_SKIP as a no-op.
enum GPrimType : uint8_t { GPRIM_TRIANGLE = 0, GPRIM_SPHERE = 1, GPRIM_SKIP = 2 };
struct GPrimitive {
    GPrimType type;
    int       index;   // index into d_triangles or d_spheres
};

struct GTriangle {
    GVec3 v0, v1, v2;
    GVec3 n0, n1, n2;   // per-vertex normals (or face normal repeated 3×)
    int   materialId;
    // pkg87a — Cryptomatte hashed names, populated at scene upload
    uint32_t objectHash;
    uint32_t materialHash;
    // pkg55-followup — flat-shaded flag: true when n0==n1==n2 (no per-vertex normals),
    // allows gpu_triangle_hit to skip the redundant interpolate+normalize chain.
    bool flat_shaded;
    // pkg88-C.0 GPU — verify on RTX. Motion blur: offset into d_motionVertices device array.
    // If motionOffset >= 0, triangle has motion; read [offset, offset+1, offset+2] for end verts.
    // motionSteps=2 → one additional step. Linear blend per Cycles motion_triangle.h (Apache-2.0).
    int motionOffset = -1;    // -1 = no motion (static)
    int motionSteps = 1;      // 1 = static, 2 = pre+post shutter
    // pkg178 Stage-3b PR-4b — active-UV-layer texture coordinates, uploaded by
    // scene_upload ONLY for triangles whose material is an anisotropic Principled
    // (host-side conditional). `hasUV` false ⇒ the shade path skips the
    // UV-aligned-tangent computation entirely (zero cost for non-aniso scenes);
    // fields are then left default. Consumed by the GPU shade path to build the
    // anisotropy tangent frame (mirror of CPU manifold::uvAlignedTangent).
    GVec2 uv0, uv1, uv2;
    bool  hasUV = false;
};

struct GSphere {
    GVec3 center;
    float radius;
    int   materialId;
    // pkg64-gpu Phase 1 — per-object caustic-caster opt-in, mirrored
    // from CPU Hittable::isCausticCaster_ at scene upload. Sphere-only
    // caster scope (same as CPU pkg64 Phases 1-3). One bool, no flag
    // packing: gate selectivity dominates and a single bool keeps the
    // CPU↔GPU upload diff minimal (pkg64-gpu spec, Phase 1 / decision 3).
    bool  isCausticCaster = false;
    // pkg87a — Cryptomatte hashed names, populated at scene upload
    uint32_t objectHash;
    uint32_t materialHash;
};

// ---------------------------------------------------------------------------
// pkg114 — Two-level BVH (TLAS over per-mesh BLAS + instance transforms).
//
// Ported from pbrt-v4 (Apache-2.0) Transform::ApplyInverse / operator() and
// Cycles (Apache-2.0) transform_point/transform_direction. See
// .astroray_plan/docs/two-level-bvh-research.md. Row-major affine; we store
// BOTH M (object->world) and Minv (world->object) so the device never inverts
// a matrix per ray (pbrt/Cycles both precompute the inverse).
// ---------------------------------------------------------------------------
struct GMat4 {
    float m[16];   // row-major: m[row*4 + col]

    HD static GMat4 identity() {
        GMat4 r;
        for (int i = 0; i < 16; ++i) r.m[i] = 0.f;
        r.m[0] = r.m[5] = r.m[10] = r.m[15] = 1.f;
        return r;
    }

    // Point transform: full 4x4 incl. translation + homogeneous w-divide.
    HD GVec3 xformPoint(const GVec3& p) const {
        float x = m[0]*p.x + m[1]*p.y + m[2]*p.z + m[3];
        float y = m[4]*p.x + m[5]*p.y + m[6]*p.z + m[7];
        float z = m[8]*p.x + m[9]*p.y + m[10]*p.z + m[11];
        float w = m[12]*p.x + m[13]*p.y + m[14]*p.z + m[15];
        float inv = (w != 0.f) ? 1.f/w : 1.f;
        return GVec3(x*inv, y*inv, z*inv);
    }
    // Vector transform: upper 3x3, NO translation, *** NOT renormalized ***
    // (so a ray direction keeps the object-space scale and local t == world t;
    //  pbrt §6.1.4 / Cycles transform_direction).
    HD GVec3 xformDir(const GVec3& d) const {
        return GVec3(m[0]*d.x + m[1]*d.y + m[2]*d.z,
                     m[4]*d.x + m[5]*d.y + m[6]*d.z,
                     m[8]*d.x + m[9]*d.y + m[10]*d.z);
    }
    // Normal transform by the inverse-transpose: 'this' MUST be Minv
    // (world<-object), and we read it transposed (multiply by columns) to get
    // (Minv)^T * n_local = world normal direction. Caller renormalizes.
    HD GVec3 xformNormalByInvTranspose(const GVec3& n) const {
        return GVec3(m[0]*n.x + m[4]*n.y + m[8]*n.z,
                     m[1]*n.x + m[5]*n.y + m[9]*n.z,
                     m[2]*n.x + m[6]*n.y + m[10]*n.z);
    }
};

// One BLAS = one unique mesh BVH. Slices into the shared global node/prim
// arrays. Each BLAS is flattened INDEPENDENTLY starting at node 0, so its
// GBVHNode.secondChildOffset values are BLAS-local; only the root pointer
// (blasNodes + nodeOffset) is offset at traversal time.
struct GBLAS {
    int nodeOffset;   // first GBVHNode of this BLAS in the global blas-node array
    int primOffset;   // added to a BLAS-local leaf primId to land in global prims[]
};

// One instance. A TLAS leaf points at a list of these.
struct GInstance {
    GMat4 worldFromObject;   // M    — hit point + tangents back to world
    GMat4 objectFromWorld;   // Minv — ray into local space + normal inverse-transpose
    int   blasIndex;         // index into the GBLAS array
    int   instanceId;        // stable id (Cryptomatte/NEE join handle; used in inc 2)
};

// The TLAS reuses the 32-byte GBVHNode layout verbatim ("the TLAS is just
// another BVH", pbrt-v4). A TLAS leaf's primitivesOffset/nPrimitives index the
// instance list instead of prims[].
using GTLASNode = GBVHNode;

// ---------------------------------------------------------------------------
// Material
// ---------------------------------------------------------------------------
// Sellmeier dispersion coefficients (Sellmeier 1871, public domain).
// Used by dispersive dielectrics to compute wavelength-dependent IOR:
//   n²(λ) = 1 + B1·λ²/(λ²−C1) + B2·λ²/(λ²−C2) + B3·λ²/(λ²−C3)
// with λ in μm. For non-dispersive materials, all coefficients are zero.
struct GDispersion {
    float b1, b2, b3;  // Sellmeier B coefficients
    float c1, c2, c3;  // Sellmeier C coefficients (μm²)
};

enum GMaterialType : uint8_t {
    GMAT_LAMBERTIAN   = 0,
    GMAT_METAL        = 1,
    GMAT_DIELECTRIC   = 2,
    GMAT_DIFFUSE_LIGHT = 3,
    GMAT_DISNEY       = 4,
    GMAT_THIN_GLASS   = 5,
    GMAT_CLOSURE_GRAPH = 6
};

enum GSpectralMode : uint8_t {
    GSPEC_NONE = 0,
    GSPEC_RGB_ALBEDO = 1,
    GSPEC_RGB_ILLUMINANT = 2
};

enum GClosureType : uint8_t {
    GCLOSURE_NONE = 0,
    GCLOSURE_DIFFUSE = 1,
    GCLOSURE_GGX_CONDUCTOR = 2,
    GCLOSURE_DIELECTRIC_TRANSMISSION = 3,
    GCLOSURE_CLEARCOAT = 4,
    GCLOSURE_SHEEN = 5,
    GCLOSURE_EMISSION = 6,
    GCLOSURE_THIN_GLASS = 7,
    // pkg178 Stage 2: device mirror of MaterialClosureType::Principled — the
    // monolithic native-Principled core-lobe closure. A Principled material
    // emits exactly ONE of these, so G_MAX_MATERIAL_CLOSURES stays 8 (no cap
    // bump). Handled by the gpu_principled_* twin in gpu_materials.h.
    GCLOSURE_PRINCIPLED = 8
};

static constexpr int G_MAX_MATERIAL_CLOSURES = 8;

struct GMaterialClosure {
    GClosureType type;
    uint8_t twoSidedEmission;
    uint8_t _pad0[2];
    GVec3 color;
    float weight;
    float roughness;
    float metallic;
    float ior;
    float transmission;
    float clearcoatGloss;
    // pkg178 Stage-3b perf: the Principled advanced params (Stage-2 specular*
    // and Stage-3 coat/sheen/subsurface/emission) formerly lived here. Because
    // GMaterial stores closures[G_MAX_MATERIAL_CLOSURES], every added byte cost
    // 8x in sizeof(GMaterial), and gpu_closure_as_material returns GMaterial BY
    // VALUE on the shared (non-Principled) closure-graph path — so the growth
    // landed on the register-saturated shade kernel's stack even in the <false>
    // instantiation (if constexpr cannot shrink a struct). Those params now live
    // ONCE per material in GMaterial::principled (GPrincipledClosure), read only
    // by the gpu_principled_* twin. A Principled material carries a single closure
    // of type GCLOSURE_PRINCIPLED here (a marker + its core fields); its advanced
    // data is in GMaterial::principled. Restores the former _pad1[2].
    float _pad1[2];
};

// pkg178 Stage-3b perf: the monolithic native-Principled parameter block. Held
// ONCE per GMaterial (GMaterial::principled) rather than on every GMaterialClosure
// in the closures[] array, so the shared non-Principled closure-graph path (which
// stack-copies a full GMaterial via gpu_closure_as_material) no longer pays for
// principled-only fields. Read only by the gpu_principled_* twin in the <true>
// shade-kernel instantiation. Mirrors the Stage-2/3 fields of the CPU
// MaterialClosure (material_closure.h); scene_upload.cu copies them across.
struct GPrincipledClosure {
    GVec3 color;             // base_color
    float roughness;
    float metallic;
    float ior;
    float transmission;
    GVec3 specularTint;      // Cycles specular_tint
    float specularIorLevel;  // Cycles specular_ior_level
    float diffuseRoughness;  // Cycles diffuse_roughness (EON)
    GVec3 coatTint;          // Cycles coat_tint
    float coatWeight;        // Cycles coat_weight
    float coatRoughness;     // Cycles coat_roughness
    float coatIor;           // Cycles coat_ior
    GVec3 sheenTint;         // Cycles sheen_tint
    float sheenWeight;       // Cycles sheen_weight
    float sheenRoughness;    // Cycles sheen_roughness
    GVec3 subsurfaceRadius;  // Cycles subsurface_radius (uploaded; not yet read)
    float subsurfaceWeight;  // Cycles subsurface_weight (APPROX, D2=a)
    float subsurfaceScale;   // Cycles subsurface_scale (uploaded; not yet read)
    GVec3 emissionColor;     // Cycles emission_color (uploaded; not yet read)
    float emissionStrength;  // Cycles emission_strength (uploaded; not yet read)
    // pkg178 Stage-3b PR-4b — anisotropy (metallic/specular; 0 → isotropic).
    float anisotropic;
    float anisotropicRotation;
    // pkg178 Stage-3b PR-6 — alpha transparency (1 → opaque, no transparent lobe).
    float alpha;
    // pkg178 Stage 4 PR-3 — thin-film iridescence (GPU twin of the CPU work in
    // principled.cpp PR-1/PR-2; Belcour-Barla 2017, see thin_film_fresnel.h).
    // thickness ≤ 0.1nm cutoff → film OFF, byte-identical to PR-6. Only two floats
    // (+8 B): the metallic-lobe conductor (n,k,g) are recomputed ON-DEVICE per hit
    // inside the thin-film path (gpu_pr_thinFilmConductorRGB, <true> only), NOT
    // stored here. Storing 9 more floats inflated GMaterial, which the SHARED
    // closure-graph path stack-copies by value, so the non-principled <false>
    // kernel paid +320 B STACK for data it never reads (measured regression:
    // 3608→3928 B, +6.1% perf; same data-leak class as the Stage-3 data-iso
    // finding). The per-hit Gulbrandsen inversion now lands only in <true> (which
    // has budget). CPU (PR-2) keeps its plugin-stored precompute — this is a
    // GPU-only trade-off (register/stack over a per-hit recompute).
    float thinFilmThickness = 0.f;      // Cycles thin_film_thickness (nm)
    float thinFilmIor = 1.33f;          // Cycles thin_film_ior
    // pkg178 Stage 4 PR-4 — thin_wall (bool) + subsurface_anisotropy (∈[-1,1])
    // packed into ONE float. MEASURED (host sizeof): GPrincipledClosure has exactly
    // one float of trailing slack inside the alignas(64) GMaterial (640 B); a SECOND
    // added field rounds GMaterial 640→704 B (+64) which the shared <false> path pays
    // in its by-value GMaterial copy (gpu_closure_as_material `GMaterial tmp = parent`)
    // — the same STACK-leak class PR-3 documented. So both PR-4 params ride ONE float.
    // Encoding: thin_wall=false → -8 sentinel; thin_wall=true → subsurface_anisotropy.
    // Decode via gpu_pr_thinWall / gpu_pr_subsurfaceAniso (gpu_materials.h). Filled by
    // scene_upload.cu from MaterialClosure::{thinWall,subsurfaceAnisotropy}.
    float thinWallAniso = -8.f;
};

// pkg54a: layout for the device-side spectral profile table. Profiles are
// resampled onto a fixed 5 nm grid spanning 300-1000 nm (141 samples) before
// upload; each material can carry a profileIndex into a flat
// [numProfiles * G_PROFILE_SAMPLES] constant-memory table. -1 means no
// profile (CPU `Material::evalSpectralExt` no-profile fallback semantics).
static constexpr int   G_MAX_PROFILES        = 32;
static constexpr int   G_PROFILE_SAMPLES     = 141;
static constexpr float G_PROFILE_LAMBDA_MIN  = 300.0f;
static constexpr float G_PROFILE_LAMBDA_MAX  = 1000.0f;
static constexpr float G_PROFILE_LAMBDA_STEP = 5.0f;

struct alignas(64) GMaterial {
    GMaterialType type;
    GSpectralMode spectralMode;
    bool spectralGpu;
    uint8_t closureCount;
    int     profileIndex;   // pkg54a: index into device profile table; -1 = none

    GVec3  baseColor;
    float  roughness;
    float  metallic;
    float  ior;
    float  transmission;
    float  clearcoat;
    float  clearcoatGloss;
    float  emissionIntensity; // > 0 means emissive (DiffuseLight)

    // Disney extra params
    float  specular;
    float  specularTint;
    float  sheen;
    float  sheenTint;
    float  subsurface;
    float  anisotropic;
    float  anisotropicRotation;

    // pkg64-gpu-sellmeier-upload: wavelength-dependent IOR (Sellmeier dispersion)
    GDispersion dispersion;
    bool        isDispersive;

    // pkg141: DisneyPlugin::closureGraph() always emits a GGXConductor closure
    // for any non-fully-transmissive Disney material (see
    // plugins/materials/disney.cpp closureGraph(), which this header must not
    // edit — Lane A's exclusive file). MetalPlugin's standalone "metal"
    // material emits the IDENTICAL closure type/shape for its own lobe. The
    // closure itself carries no information distinguishing the two origins,
    // but they need DIFFERENT GPU BRDF models: MetalPlugin's near-delta
    // perfect-mirror shortcut (gpu_metal_eval, roughness<=0.1) is correct only
    // for MetalPlugin (CPU MetalPlugin::eval/sample has the identical
    // shortcut); DisneyPlugin's CPU eval()/sample()/pdf() never special-cases
    // low roughness (alpha floors at 0.0064 but stays a continuous GGX lobe).
    // Routing a Disney-native conductor closure through gpu_metal_eval
    // therefore replaced Disney's Fresnel/GGX-shaped near-delta lobe with an
    // unconditional full-albedo mirror reflection, measured 2.7-4.0x brighter
    // than the CPU (see gpu_closure_as_material's GCLOSURE_GGX_CONDUCTOR case
    // below). This flag is stamped by scene_upload.cu's closure-graph upload
    // path (a call to the already-public Material::getGPUTypeName(), not a
    // disney.cpp edit) so gpu_closure_as_material can route the conductor
    // lobe to the correct model per origin.
    bool        disneyMetalConductor;

    GMaterialClosure closures[G_MAX_MATERIAL_CLOSURES];

    // pkg178 Stage-3b perf: the single native-Principled parameter block for a
    // Principled material (closures[0].type == GCLOSURE_PRINCIPLED). Kept out of
    // the per-closure array so non-Principled materials, and the by-value GMaterial
    // temp in the shared closure-graph path, do not pay for principled-only data.
    // Read only by the gpu_principled_* twin (<true> instantiation).
    GPrincipledClosure principled;
};

// ---------------------------------------------------------------------------
// pkg186 — GPU image texture (baked buffer + nearest fetch).
//
// Design decision (2): baked device buffer + manual nearest fetch, NOT
// cudaTextureObject_t. Reason: the CPU ImageTexture sampler (advanced_features.h
// ImageTexture::value) is NEAREST-neighbour with a uv clamp to [0,1] and a v
// flip — hardware bilinear via a texture object would DIVERGE from the CPU
// reference and break the per-channel parity gate. A baked buffer replicates the
// CPU sampler bit-for-bit and needs no cudaArray/format/lifetime machinery.
//
// Storage (decision layout): every uploaded image's texels are concatenated into
// ONE flat device buffer (see SceneUploadResult::textureTexels); each texture is
// an {offset,width,height} slice into it. Index-based addressing avoids a
// device-pointer-inside-a-descriptor and per-texture cudaMalloc churn, so it maps
// straight onto the wavefront's grow-only wfUpload(vector) path.
//
// Materials do NOT carry a texture id: GMaterial is exactly 640 B (alignas(64),
// zero slack) and is stack-copied by value in gpu_closure_as_material, so any
// added field rounds it to 704 B and spills the shared non-principled shade
// kernel (the register-pressure regression pkg178 documented). The per-material
// texture index therefore lives in a PARALLEL device array (d_materialTextureId),
// read only inside the HasTexture shade branch.
// ---------------------------------------------------------------------------
struct GImageTexture {
    int offset;   // start index into the flat texel buffer
    int width;
    int height;
    // pkg190 — procedural-texture slice. depth == 1 → a 2D image (or a 2D-UV
    // procedural bake), sampled by (u,v) via gpu_sampleImageTexture (the pkg186
    // path, unchanged). depth > 1 → a 3D voxel bake of a Generated-coord
    // procedural, sampled by the normalized Generated coordinate via
    // gpu_sampleProcedural3D. genMin/genSize carry the SAME object-space bbox the
    // CPU Texture uses (Texture::getGeneratedMin/Size) so the GPU rebuilds the
    // identical g = clamp((objectPoint - genMin)/genSize, 0, 1).
    int   depth   = 1;
    GVec3 genMin  = GVec3(0.f, 0.f, 0.f);
    GVec3 genSize = GVec3(1.f, 1.f, 1.f);
    // pkg219a — full 3-D Blender Mapping node transform (top 3x4 rows,
    // row-major) baked from the CPU Texture (Texture::getMappingMatrix). When
    // hasMapping != 0 the image sample coordinate is (M * (u,v,0)).xy — the
    // exact CPU UV-mode path (advanced_features.h Texture::value). Lives in the
    // __constant__ GWavefrontTextureBinding array so applying it is a runtime
    // branch + a few FMAs on already-live (u,v), no per-ray SoA state.
    int   hasMapping = 0;
    float mapping[12] = {1.f,0.f,0.f,0.f, 0.f,1.f,0.f,0.f, 0.f,0.f,1.f,0.f};
};

// pkg186 — wavefront image-texture binding. Published ONCE per frame into a
// __constant__ symbol (setWavefrontTextureBinding) so the shared shade kernel
// reads texture data from constant memory rather than three per-launch signature
// pointer params. Passing them in the signature grew CONSTANT[0] and cost the
// untextured <false,false> fleet kernel +24 B STACK (native sm_120: 3632 vs
// main's 3608) even though the texture code is if-constexpr'd out; constant
// memory keeps the <false,*> signature at its pre-pkg186 footprint.
struct GWavefrontTextureBinding {
    const GImageTexture* textures;
    const GVec3*         texelBuf;
    const int*           matTexId;
    // pkg223 — tangent-space normal map, published on the SAME __constant__ side
    // table so GMaterial stays exactly 640 B and the fleet <…,false> shade kernel
    // (HasNormalPerturb=false) is byte-identical. matNormalTexId[mat] indexes into
    // `textures` (-1 = no normal map); matNormalStrength[mat] is the Cycles
    // Strength. Read ONLY inside the HasNormalPerturb=true specialization.
    const int*           matNormalTexId;    // per-material normal-texture id, -1 absent
    const float*         matNormalStrength;  // per-material Strength [0,1]
};

// pkg197 — wavefront first-hit denoise-guide AOV binding. Published ONCE per
// frame into a __constant__ symbol (setWavefrontGuideBinding), exactly like the
// pkg186 texture binding, so the register-saturated shade kernel and the
// intersect kernel read the three output pointers from constant memory rather
// than growing their per-launch signatures (which would bump CONSTANT[0] and
// the fleet <false,…> shade kernel's STACK — the pkg186 lesson). The intersect
// stage writes base-colour albedo + shading normal + hit distance at the first
// camera-ray hit (bounce 0, sample 0) to feed the OIDN/OptiX denoiser guides
// and the addon Albedo/Normal/Depth AOVs. All three pointers null == guides
// disabled (the default for the snapshot/ReSTIR drivers). Layout matches the
// CPU Camera buffers: albedo/normal are numPixels*3 floats (Vec3 per pixel),
// depth is numPixels floats.
struct GWavefrontGuideBinding {
    float* albedo;  // numPixels*3 floats, or nullptr to disable
    float* normal;  // numPixels*3 floats
    float* depth;   // numPixels floats
};

// pkg198 Stage 2 — wavefront light-path-expression render passes. Published ONCE
// per frame into a __constant__ symbol (setWavefrontLightPassBinding), exactly like
// the pkg186 texture / pkg197 guide bindings, so the register-saturated shade kernel
// and the 127-reg intersect kernel read the pass pointers from constant memory rather
// than growing their per-launch signatures (the pkg186 lesson: a signature pointer
// bumps CONSTANT[0] and costs the fleet kernel +STACK even when the code is
// if-constexpr'd out). The REGISTER PROBE (spec §Stage-2, PR #620) confirmed this
// keeps the fleet shade kernel byte-identical at 254/3352/1700 and adds zero STACK
// even to the pass-AOV specialization.
//
// Data flow (mirrors the beauty accumulate-at-death path):
//   * shade locks `firstCat` at the first BSDF interaction (bounce 0);
//   * intersect / shadow-resolve / volume-scatter kernels splat each radiance
//     contribution into the per-SLOT spectral accumulator `passAccum` (one += per
//     color += site → Σpasses == beauty EXACTLY in spectral space);
//   * stageRegen, at path death, converts each slot's per-pass spectral accumulator
//     to XYZ with the slot's lambdas and atomic-adds into the per-PIXEL `passXYZ`
//     (linear XYZ, same convention as beauty accum_xyz), then zeroes the slot.
// The driver converts passXYZ → linear sRGB with the SAME /samples·exposure·
// xyzToLinearSRGB transform as beauty, so sum-to-beauty holds in linear sRGB.
//
// `passAccum == nullptr` (every non-AOV driver / snapshot / ReSTIR route) makes the
// HasLightPassAOVs=false shade/intersect specializations compile the whole partition
// OUT (byte-identical fleet) and the runtime-gated shadow/volume/regen blocks skip.
//
// Pass layout matches RenderPassIndex (raytracer.h): index = cat*3 + {0=direct,
// 1=indirect, 2=color(unused)}, cat 0=diffuse/1=glossy/2=transmission/3=volume;
// PASS_EMISSION=11, PASS_ENVIRONMENT=12. ASTRORAY_LP_NUM_PASSES == PASS_ENVIRONMENT+1;
// a static_assert in blender_module.cpp ties it to the enum.
#ifndef ASTRORAY_LP_NUM_PASSES
#define ASTRORAY_LP_NUM_PASSES 13   // PASS_DIFFUSE_DIRECT(0) .. PASS_ENVIRONMENT(12)
#endif
struct GWavefrontLightPassBinding {
    float*         passAccum;   // per-slot spectral: capacity*ASTRORAY_LP_NUM_PASSES*G_SPECTRUM_SAMPLES, or null=disabled
    float*         passXYZ;     // per-pixel XYZ output: numPixels*ASTRORAY_LP_NUM_PASSES*3
    unsigned char* firstCat;    // per-slot locked first-bounce category (0xFF=not set), capacity bytes
    int            numPixels;   // pixels in the frame (passXYZ pixel stride guard)
};

// pkg199 Stage 1 — homogeneous world-volume medium, published ONCE per frame
// into a __constant__ symbol (setWavefrontWorldVolume), mirroring the
// pkg186/pkg197 binding pattern so the wavefront reads the medium from constant
// memory rather than growing any kernel signature. Beer-Lambert absorption only
// (no in-scatter/phase — Stage 2). `hasVolume == 0` (the default; snapshot/ReSTIR
// drivers never set it) makes intersectPathSlot/stageShadowKernel skip the
// transmittance branch, so vacuum renders are byte-identical AND the
// REG-254-saturated stageShadeBucketedKernel is untouched entirely. `color` is
// the reflectance-like world-volume tint; the transmittance helper upsamples it
// through the JH albedo LUT (GSPEC_RGB_ALBEDO) then applies exp(-sigma·density·d)
// per wavelength — the CPU twin (Renderer::worldTransmittanceSpectral) is
// identical, so parity holds by construction.
// Plain scalars only (no GVec3 member): a __constant__ variable of this type
// must be trivially initializable — a GVec3 member's user-defined ctor triggers
// "dynamic initialization is not supported for a __constant__ variable".
struct GWorldVolume {
    int   hasVolume;              // 0 = vacuum (skip); 1 = active medium
    float density;               // worldVolumeDensity
    float colorR, colorG, colorB; // worldVolumeColor (reflectance-like tint)
    // pkg199 Stage 2 — single-scattering albedo alpha in [0,1] and HG anisotropy g.
    // scatter==0 (default) => absorption-only (Stage-1 behaviour, byte-identical:
    // the free-flight scatter decision in intersectPathSlot is gated on scatter>0).
    // sigma_s = scatter*sigma_t; g is live only when scatter>0.
    float scatter;               // worldVolumeScatter (alpha)
    float anisotropy;            // worldVolumeAnisotropy (HG g)
};

// Nearest-neighbour image fetch — mirrors CPU ImageTexture::value EXACTLY
// (clamp u,v to [0,1]; v flip; floor to texel; clamp index to bounds).
HD inline GVec3 gpu_sampleImageTexture(const GImageTexture& tex,
                                       const GVec3* texels,
                                       float u, float v) {
    u = u < 0.f ? 0.f : (u > 1.f ? 1.f : u);
    v = 1.f - (v < 0.f ? 0.f : (v > 1.f ? 1.f : v));
    int i = (int)(u * (float)tex.width);
    int j = (int)(v * (float)tex.height);
    if (i > tex.width  - 1) i = tex.width  - 1;
    if (j > tex.height - 1) j = tex.height - 1;
    return texels[tex.offset + j * tex.width + i];
}

// pkg190 — nearest-neighbour 3D voxel fetch for a baked Generated-coord
// procedural. `g` is the normalized Generated coordinate in [0,1]^3, built by
// the caller EXACTLY as the CPU does (g = clamp((objectPoint - genMin)/genSize,
// 0, 1); include/advanced_features.h CoordMode::Generated). The bake stores cell
// CENTERS (value at (idx+0.5)/res), so a floor(g*res) fetch returns the cell
// containing g — the point-sampled twin of the CPU's continuous evaluation.
// Filtering is parity-coupled: the CPU procedural is point-sampled per shade, so
// the GPU point-samples the same grid. Do NOT add GPU-only trilinear filtering
// unless the CPU sampler gains it in lockstep (pkg186 Decision 2; pkg190).
HD inline GVec3 gpu_sampleProcedural3D(const GImageTexture& tex,
                                       const GVec3* texels, GVec3 g) {
    float gx = g.x < 0.f ? 0.f : (g.x > 1.f ? 1.f : g.x);
    float gy = g.y < 0.f ? 0.f : (g.y > 1.f ? 1.f : g.y);
    float gz = g.z < 0.f ? 0.f : (g.z > 1.f ? 1.f : g.z);
    int i = (int)(gx * (float)tex.width);
    int j = (int)(gy * (float)tex.height);
    int k = (int)(gz * (float)tex.depth);
    if (i > tex.width  - 1) i = tex.width  - 1;
    if (j > tex.height - 1) j = tex.height - 1;
    if (k > tex.depth  - 1) k = tex.depth  - 1;
    return texels[tex.offset + (k * tex.height + j) * tex.width + i];
}

// ---------------------------------------------------------------------------
// Hit record
// ---------------------------------------------------------------------------
struct GHitRecord {
    GVec3 point;
    GVec3 normal;
    GVec3 tangent;
    GVec3 bitangent;
    // pkg178 Stage-3b PR-4b — UV-aligned shading tangent for anisotropy (GPU twin
    // of CPU HitRecord::uvTangent). Transient/per-thread; the production shade
    // path fills it from the hit triangle's uploaded UVs when the material is an
    // anisotropic Principled, else it defaults to the arbitrary `tangent` frame.
    // Isotropic shading never reads it → bit-identical.
    GVec3 uvTangent      = GVec3(1.f, 0.f, 0.f);
    float uvBitangentSign = 1.f;
    float t;
    int   materialId;
    int   primId;     // index into d_prims[] — set by gpu_bvh_hit
    bool  frontFace;
    bool  isDelta;
};

// ---------------------------------------------------------------------------
// NEE sample handoff (pkg55-B' shadow stage; blueprint:
// .astroray_plan/docs/pkg55-nee-shadow-stage-blueprint.md).
// Produced by gpu_nee_sample (sampling only, all RNG draws), consumed by
// gpu_nee_occlude (shadow trace) + gpu_nee_resolve (material evals +
// contribution). The megakernel recomposes the three back-to-back.
// ---------------------------------------------------------------------------
struct GNEESample {
    GVec3 origin;      // shadow ray origin (rec.point)
    GVec3 wi;          // shadow ray direction (normalized)
    float maxDist;     // shadow ray extent (OCCLUSION tMax — 1e30 sentinel for
                       // sphere/distant sources; NOT a geometric distance)
    // pkg199 Stage 1 — TRUE geometric vertex->light distance for Beer-Lambert
    // world-volume transmittance. Distinct from maxDist, which is 1e30 for
    // sphere-primitive and distant lights (an occlusion sentinel that would make
    // exp(-sigma*maxDist)=0 collapse every fogged NEE-to-sphere contribution —
    // the pkg199 HW-611 regression). Set to the sampled-point distance for
    // sphere/triangle/point/spot/area sources, and 0 for distant/infinite lights
    // (treated like env-miss: NON-attenuated, per the Stage-1 infinite-segment
    // convention). gpu_worldTransmittanceMW(geomDist) returns Tr=1 for geomDist<=0.
    float geomDist;

    float lightPdf;    // solid-angle pdf incl. selection pdf
    int   lightMatId;  // emission material index (geometry emitters)
    int   isSphere;    // 1 = sphere source (frontFace from the hit), 0 = triangle
    int   valid;       // 0 => no contribution (early-out in sampling)
    // pkg89-GPU / GAP 1 — dedicated-light source (point/spot/distant/area). When
    // set, emission comes from dedEmissionRGB·dedGeoScale (no material lookup),
    // and occlusion uses the isSphere=0 "any occluder in [eps,maxDist]" branch.
    int   isDedicated;    // 1 = dedicated light
    GVec3 dedEmissionRGB; // reference color for the device RGBIlluminant upsample
    float dedGeoScale;    // staticScale · per-sample geometric factor (λ-independent)
    // pkg140: 1 = this sample came from a delta (zero-measure) light
    // distribution (e.g. GDED_DISTANT with angular_diameter == 0). Forces
    // gpu_nee_resolve's MIS weight to 1 instead of a power heuristic against
    // bsdfPdf, mirroring CPU LightSample::isDelta. Zero-initialized by every
    // `GNEESample s{};` call site, so non-distant / non-delta samples are
    // unaffected.
    int   isDeltaLight;
};

struct GNEEOcclusion {
    int occluded;      // 1 = blocked
    int frontFace;     // sphere sources: hit frontFace; triangles: unused
};

// ---------------------------------------------------------------------------
// BSDF sample
// ---------------------------------------------------------------------------
struct GBSDFSample {
    GVec3 wi;
    GVec3 f;
    GSampledSpectrum fSpectral;
    float pdf;
    bool  isDelta;
};

// ---------------------------------------------------------------------------
// Light (area + emissive sphere) for NEE
// ---------------------------------------------------------------------------
struct GLight {
    int   primitiveIndex;   // index into d_primitives[]
    float power;            // luminance * surface area
    float cumulativePower;  // for CDF-based power-weighted selection
};

// ---------------------------------------------------------------------------
// Dedicated light (pkg89-GPU / GAP 1) — device mirror of astroray::PointLight /
// SpotLight / DistantLight / AreaLight. A tagged-union POD à la Cycles
// KernelLight (intern/cycles/kernel/types.h, Apache-2.0). The device sampler
// (src/gpu/gpu_nee.cuh gpu_dedicated_sample) reproduces the CPU
// src/lights/*.cpp sampleLi() pdfs + emission scale so GPU NEE == CPU NEE.
// cumulativePower continues the unified power CDF PAST the GLight entries
// (mirrors CPU PowerLightSampler's single CDF over hittable + dedicated lights).
// ---------------------------------------------------------------------------
enum GDedLightKind { GDED_POINT = 0, GDED_SPOT = 1, GDED_DISTANT = 2, GDED_AREA = 3 };

struct GDedicatedLight {
    int   kind;             // GDedLightKind
    GVec3 position;         // point/spot/area center (world space)
    GVec3 axis;             // spot axis / distant axis (FROM light) / area normal
    GVec3 u, v;             // area plane axes (normalized)
    float width, height;    // area extents (width = disk radius for Disk)
    int   areaShape;        // 0 rect, 1 disk, 2 ellipse
    float radius;           // point/spot soft-shadow radius (0 = hard/delta)
    float spread;           // area emission cone half-angle (radians)
    float cosInner, cosOuter; // spot cone cosines / distant cos(halfAngle)
    GVec3 emissionRGB;      // reference color (device RGBIlluminant upsample)
    float staticScale;      // intensity·invarea·(1/π) baked (distant omits 1/π)
    float power;            // this light's unified-CDF selection weight
    float cumulativePower;  // unified CDF position (after the GLight entries)
};

// ---------------------------------------------------------------------------
// Area light structure for wavefront NEE (pkg55-B' Session N+4)
// ---------------------------------------------------------------------------
// This is a SIMPLIFIED light structure for Session N+4 (Lambertian-only Cornell).
// It inlines the triangle vertices + emission for direct light sampling without
// primitive indirection. Production would use GLight + primitive lookup.
//
// Session N+4 scope: single triangle area light (Cornell box ceiling).
// Future sessions: merge with GLight or add multi-triangle area light support.
struct GAreaLight {
    GVec3 v0, v1, v2;       // triangle vertices (world space)
    GVec3 normal;           // triangle normal (flat shading for Session N+4)
    GVec3 emission;         // RGB emission (converted to spectral in kernel)
    float power;            // luminance * area (for importance sampling, unused in N+4)
};

// ---------------------------------------------------------------------------
// Light tree (pkg86-B) — flat device mirror of astroray::LightTree.
// Mirrors include/astroray/light_tree.h LightTreeNode/LightTreeEmitter;
// traversal in src/gpu/light_tree_device.cuh (Cycles kernel/light/tree.h,
// Apache-2.0, commit e52e5eb0).
// ---------------------------------------------------------------------------
struct GLightTreeNode {
    GVec3 bboxMin, bboxMax;   // spatial bounds
    GVec3 bconeAxis;          // orientation cone axis
    float thetaO, thetaE;     // cone half-angles (outer / emission)
    float energy;             // total emitted power
    int   leftChild;          // inner node: child indices (-1 on leaf)
    int   rightChild;
    int   firstEmitter;       // leaf node: emitter range (-1 on inner)
    int   numEmitters;
};

struct GLightTreeEmitter {
    int          lightIndex;  // index into the GLight array (same order as LightList::getLights)
    unsigned int bitTrail;    // root->leaf path: bit i = level-i branch (0 = left, 1 = right)
};

// View passed into the kernels. enabled != 0 only when the CPU sampler mode
// is Tree AND the tree was uploadable (no dedicated lights — those have no
// GLight slot on the GPU yet).
struct GLightTreeView {
    const GLightTreeNode*    nodes;
    const GLightTreeEmitter* emitters;
    const int*               lightToEmitter;  // GLight index -> emitter index (-1 if absent)
    int                      numNodes;
    int                      enabled;
};

// ---------------------------------------------------------------------------
// Environment map (device pointers set during upload)
// ---------------------------------------------------------------------------
struct GEnvMap {
    const float* data;            // RGB interleaved, width*height*3 floats, device ptr
    const float* conditionalCdf;  // width*height floats, device ptr
    const float* conditionalFunc; // width*height floats, device ptr
    const float* marginalCdf;     // height floats, device ptr
    const float* marginalFunc;    // height floats, device ptr
    int   width, height;
    float strength, totalPower;
    // pkg63: baked 3x3 rotation matrix (row-major, world->envmap) and color tint.
    float rotMat[9];
    float colorTint[3];
    bool  loaded;
};

// ---------------------------------------------------------------------------
// Camera parameters passed to the kernel (avoids struct-packing issues)
// ---------------------------------------------------------------------------
struct GCameraParams {
    GVec3 origin;
    GVec3 lowerLeft;
    GVec3 horizontal;
    GVec3 vertical;
    GVec3 u, v;       // camera basis for DOF disk sampling
    float lensRadius;
    int   width, height;

    // pkg88-A: motion blur shutter keyframes (T/R/S decomposed)
    GVec3 shutterStartT, shutterEndT;   // Translation
    float shutterStartR[4], shutterEndR[4];  // Rotation (quaternion w,x,y,z)
    GVec3 shutterStartS, shutterEndS;   // Scale
    float shutter;                       // Shutter duration in frames
    int   shutterPosition;               // 0=Start, 1=Center, 2=End
    float vw, vh, focusDist;             // Projection scalars for interpolated camera
    float shiftX, shiftY;                // Camera shift for interpolated camera
};
