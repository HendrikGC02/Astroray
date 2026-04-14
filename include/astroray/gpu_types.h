#pragma once

// GPU-portable POD types for CUDA path tracer.
// This header is included by both .cu files (compiled with nvcc) and
// pure C++ translation units.  NO std:: headers, NO virtual functions.

#ifdef __CUDACC__
#  define HD __host__ __device__
#  include <cuda_runtime.h>   // sqrtf, fmaxf, etc. in device code
#else
#  define HD
#  include <cmath>
#  include <cstdint>
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
// GRay
// ---------------------------------------------------------------------------
struct GRay {
    GVec3 origin, direction;
    HD GRay() {}
    HD GRay(const GVec3& o, const GVec3& d) : origin(o), direction(d.normalized()) {}
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
enum GPrimType : uint8_t { GPRIM_TRIANGLE = 0, GPRIM_SPHERE = 1 };
struct GPrimitive {
    GPrimType type;
    int       index;   // index into d_triangles or d_spheres
};

struct GTriangle {
    GVec3 v0, v1, v2;
    GVec3 n0, n1, n2;   // per-vertex normals (or face normal repeated 3×)
    int   materialId;
};

struct GSphere {
    GVec3 center;
    float radius;
    int   materialId;
};

// ---------------------------------------------------------------------------
// Material
// ---------------------------------------------------------------------------
enum GMaterialType : uint8_t {
    GMAT_LAMBERTIAN   = 0,
    GMAT_METAL        = 1,
    GMAT_DIELECTRIC   = 2,
    GMAT_DIFFUSE_LIGHT = 3,
    GMAT_DISNEY       = 4
};

struct alignas(64) GMaterial {
    GMaterialType type;
    uint8_t _pad[3];

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

    float  _padding[1]; // fill to 64 bytes
};

// ---------------------------------------------------------------------------
// Hit record
// ---------------------------------------------------------------------------
struct GHitRecord {
    GVec3 point;
    GVec3 normal;
    GVec3 tangent;
    GVec3 bitangent;
    float t;
    int   materialId;
    int   primId;     // index into d_prims[] — set by gpu_bvh_hit
    bool  frontFace;
    bool  isDelta;
};

// ---------------------------------------------------------------------------
// BSDF sample
// ---------------------------------------------------------------------------
struct GBSDFSample {
    GVec3 wi;
    GVec3 f;
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
// Environment map (device pointers set during upload)
// ---------------------------------------------------------------------------
struct GEnvMap {
    const float* data;            // RGB interleaved, width*height*3 floats, device ptr
    const float* conditionalCdf;  // width*height floats, device ptr
    const float* conditionalFunc; // width*height floats, device ptr
    const float* marginalCdf;     // height floats, device ptr
    const float* marginalFunc;    // height floats, device ptr
    int   width, height;
    float strength, rotation, totalPower;
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
};
