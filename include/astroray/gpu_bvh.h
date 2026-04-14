#pragma once
// GPU BVH traversal and primitive intersection.
// Ported from BVHAccel::hit(), Triangle::hit(), and Sphere::hit() in raytracer.h.
// Only include from .cu files compiled by nvcc.

#include "gpu_types.h"
#include "gpu_materials.h"  // for gpu_buildONB

// ---------------------------------------------------------------------------
// Ray-triangle intersection: Möller–Trumbore (exact port from raytracer.h)
// ---------------------------------------------------------------------------
__device__ inline bool gpu_triangle_hit(
    const GTriangle& tri, const GRay& ray, float tMin, float tMax,
    GHitRecord& rec)
{
    const float EPS = 1e-6f;
    GVec3 e1 = tri.v1 - tri.v0;
    GVec3 e2 = tri.v2 - tri.v0;
    GVec3 h  = ray.direction.cross(e2);
    float a  = e1.dot(h);
    if (fabsf(a) < EPS) return false;

    float f  = 1.f / a;
    GVec3 s  = ray.origin - tri.v0;
    float u  = f * s.dot(h);
    if (u < 0.f || u > 1.f) return false;

    GVec3 q = s.cross(e1);
    float v = f * ray.direction.dot(q);
    if (v < 0.f || u + v > 1.f) return false;

    float t = f * e2.dot(q);
    if (t < tMin || t > tMax) return false;

    rec.t     = t;
    rec.point = ray.at(t);

    // Interpolate vertex normals if per-vertex normals were set
    float w = 1.f - u - v;
    GVec3 outwardNormal = (tri.n0 * w + tri.n1 * u + tri.n2 * v).normalized();

    // Front-face test
    rec.frontFace = ray.direction.dot(outwardNormal) < 0.f;
    rec.normal    = rec.frontFace ? outwardNormal : -outwardNormal;
    gpu_buildONB(rec.normal, rec.tangent, rec.bitangent);

    rec.materialId = tri.materialId;
    rec.isDelta    = false;
    return true;
}

// ---------------------------------------------------------------------------
// Ray-sphere intersection (exact port from Sphere::hit() in raytracer.h)
// ---------------------------------------------------------------------------
__device__ inline bool gpu_sphere_hit(
    const GSphere& sph, const GRay& ray, float tMin, float tMax,
    GHitRecord& rec)
{
    GVec3 oc  = ray.origin - sph.center;
    float a   = ray.direction.length2();
    float hb  = oc.dot(ray.direction);
    float c   = oc.length2() - sph.radius * sph.radius;
    float disc = hb*hb - a*c;
    if (disc < 0.f) return false;

    float sqrtd = sqrtf(disc);
    float root  = (-hb - sqrtd) / a;
    if (root < tMin || root > tMax) {
        root = (-hb + sqrtd) / a;
        if (root < tMin || root > tMax) return false;
    }

    rec.t     = root;
    rec.point = ray.at(root);

    GVec3 outwardNormal = (rec.point - sph.center) / sph.radius;
    rec.frontFace = ray.direction.dot(outwardNormal) < 0.f;
    rec.normal    = rec.frontFace ? outwardNormal : -outwardNormal;
    gpu_buildONB(rec.normal, rec.tangent, rec.bitangent);

    rec.materialId = sph.materialId;
    rec.isDelta    = false;
    return true;
}

// ---------------------------------------------------------------------------
// Iterative BVH traversal — direct port of BVHAccel::hit()
// Thread-local stack[64] matches the CPU implementation.
// ---------------------------------------------------------------------------
__device__ inline bool gpu_bvh_hit(
    const GBVHNode*  nodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GRay&       ray,
    float tMin, float tMax,
    GHitRecord&       rec)
{
    if (!nodes) return false;

    bool  hit    = false;
    GVec3 invDir(1.f/ray.direction.x,
                 1.f/ray.direction.y,
                 1.f/ray.direction.z);
    int   dirIsNeg[3] = { invDir.x < 0, invDir.y < 0, invDir.z < 0 };
    int   toVisit = 0, curr = 0;
    int   stack[64];

    while (true) {
        const GBVHNode& n = nodes[curr];

        if (n.bounds.hit(ray, tMin, tMax)) {
            if (n.nPrimitives > 0) {
                // Leaf — test each primitive
                for (int i = 0; i < n.nPrimitives; ++i) {
                    const GPrimitive& p = prims[n.primitivesOffset + i];
                    GHitRecord tmpRec;
                    bool isHit = false;
                    if (p.type == GPRIM_TRIANGLE) {
                        isHit = gpu_triangle_hit(tris[p.index], ray, tMin, tMax, tmpRec);
                    } else {
                        isHit = gpu_sphere_hit(spheres[p.index], ray, tMin, tMax, tmpRec);
                    }
                    if (isHit) {
                        hit  = true;
                        tMax = tmpRec.t;
                        rec  = tmpRec;
                        rec.primId = n.primitivesOffset + i;
                    }
                }
                if (toVisit == 0) break;
                curr = stack[--toVisit];
            } else {
                // Interior — push far child, visit near child first
                if (dirIsNeg[n.axis]) {
                    stack[toVisit++] = curr + 1;
                    curr = n.secondChildOffset;
                } else {
                    stack[toVisit++] = n.secondChildOffset;
                    curr = curr + 1;
                }
            }
        } else {
            if (toVisit == 0) break;
            curr = stack[--toVisit];
        }
    }
    return hit;
}

// ---------------------------------------------------------------------------
// Environment map sampling helpers (device-side)
// ---------------------------------------------------------------------------

// Binary search on a monotone device array of length n, return first index
// where arr[i] >= target.
__device__ inline int gpu_lower_bound(const float* arr, int n, float target) {
    int lo = 0, hi = n;
    while (lo < hi) {
        int mid = (lo + hi) / 2;
        if (arr[mid] < target) lo = mid + 1;
        else                   hi = mid;
    }
    return lo;
}

struct GEnvSample { GVec3 direction; GVec3 radiance; float pdf; };

__device__ inline GEnvSample gpu_envmap_sample(const GEnvMap& em, curandState* rng) {
    GEnvSample es;
    es.pdf = 0.f;
    es.radiance = GVec3(0.f);
    es.direction = GVec3(0,1,0);
    if (!em.loaded || em.totalPower <= 0.f) return es;

    float xi1 = curand_uniform(rng);
    float xi2 = curand_uniform(rng);

    int v = gpu_lower_bound(em.marginalCdf, em.height, xi1);
    if (v >= em.height) v = em.height - 1;

    int u = gpu_lower_bound(em.conditionalCdf + v*em.width, em.width, xi2);
    if (u >= em.width) u = em.width - 1;

    float uCont = u + 0.5f;
    float vCont = v + 0.5f;
    float theta = (1.f - vCont / em.height) * M_PI_F;
    float phi   = (uCont - 0.5f) * 2.f * M_PI_F - em.rotation;

    es.direction = GVec3(sinf(theta)*cosf(phi), cosf(theta), sinf(theta)*sinf(phi));

    float sinTheta = fmaxf(sinf(theta), 1e-6f);
    int   pixIdx   = v * em.width + u;
    float funcVal  = em.conditionalFunc[pixIdx];
    float mapPdf   = funcVal * em.width * em.height / (em.totalPower + 1e-10f);
    es.pdf         = mapPdf / (2.f * M_PI_F * M_PI_F * sinTheta);

    es.radiance = GVec3(em.data[pixIdx*3+0],
                        em.data[pixIdx*3+1],
                        em.data[pixIdx*3+2]) * em.strength;
    return es;
}

__device__ inline float gpu_envmap_pdf(const GEnvMap& em, const GVec3& dir) {
    if (!em.loaded || em.totalPower <= 0.f) return 0.f;
    float theta = acosf(fminf(fmaxf(dir.y, -1.f), 1.f));
    float phi   = atan2f(dir.z, dir.x) + em.rotation;
    float u     = 0.5f + phi / (2.f * M_PI_F);
    float v     = 1.f - theta / M_PI_F;
    if (u < 0.f) u += 1.f; if (u >= 1.f) u -= 1.f;
    int x = (int)(u * em.width);  if (x >= em.width)  x = em.width-1;
    int y = (int)(v * em.height); if (y >= em.height) y = em.height-1;
    int pixIdx   = y * em.width + x;
    float funcVal = em.conditionalFunc[pixIdx];
    float sinTheta = fmaxf(sinf(theta), 1e-6f);
    float pdfUV    = funcVal * em.width * em.height / (em.totalPower + 1e-10f);
    return pdfUV / (2.f * M_PI_F * M_PI_F * sinTheta);
}

__device__ inline GVec3 gpu_envmap_lookup(const GEnvMap& em, const GVec3& dir) {
    if (!em.loaded || em.width == 0) return GVec3(0.f);
    float theta = acosf(fminf(fmaxf(dir.y, -1.f), 1.f));
    float phi   = atan2f(dir.z, dir.x) + em.rotation;
    float u     = 0.5f + phi / (2.f * M_PI_F);
    float v     = 1.f - theta / M_PI_F;
    if (u < 0.f) u += 1.f; if (u >= 1.f) u -= 1.f;

    // Bilinear interpolation
    float uP = u * em.width;
    float vP = v * em.height;
    int x0 = (int)uP; int x1 = x0 + 1;
    int y0 = (int)vP; int y1 = y0 + 1;
    x0 = x0 < 0 ? 0 : (x0 >= em.width  ? em.width-1  : x0);
    x1 = x1 < 0 ? 0 : (x1 >= em.width  ? em.width-1  : x1);
    y0 = y0 < 0 ? 0 : (y0 >= em.height ? em.height-1 : y0);
    y1 = y1 < 0 ? 0 : (y1 >= em.height ? em.height-1 : y1);
    float uf = uP - (int)uP, vf = vP - (int)vP;

    auto px = [&](int x, int y) {
        int i = (y*em.width + x) * 3;
        return GVec3(em.data[i], em.data[i+1], em.data[i+2]);
    };
    GVec3 c = (px(x0,y0)*(1-uf) + px(x1,y0)*uf) * (1-vf)
            + (px(x0,y1)*(1-uf) + px(x1,y1)*uf) * vf;
    return c * em.strength;
}
