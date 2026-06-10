#pragma once
// GPU BVH traversal and primitive intersection.
// Ported from BVHAccel::hit(), Triangle::hit(), and Sphere::hit() in raytracer.h.
// Only include from .cu files compiled by nvcc.

#include "gpu_types.h"
#include "gpu_materials.h"  // for gpu_buildONB

// ---------------------------------------------------------------------------
// pkg88-C.0 GPU — verify on RTX. Motion-aware triangle hit: interpolate vertices
// at ray.time before Möller-Trumbore. Per Cycles motion_triangle.h (Apache-2.0):
// linear blend between bracketing time steps. If motionOffset < 0, falls back to static.
// ---------------------------------------------------------------------------
__device__ inline bool gpu_triangle_hit_motion(
    const GTriangle& tri, const GRay& ray, float tMin, float tMax,
    GHitRecord& rec, const GVec3* d_motionVertices)
{
    const float EPS = 1e-6f;
    // Interpolate vertices at ray.time if motion data exists
    GVec3 p0 = tri.v0, p1 = tri.v1, p2 = tri.v2;
    if (tri.motionOffset >= 0 && tri.motionSteps > 1) {
        float time = ray.time;  // Phase A already samples and carries time in GRay
        int maxStep = tri.motionSteps - 1;
        int step = min(static_cast<int>(time * maxStep), maxStep - 1);
        float t = time * maxStep - step;
        // Center step (step=0) uses tri.v0/v1/v2; additional steps read d_motionVertices.
        // Buffer layout: [v0_step1, v1_step1, v2_step1, v0_step2, ...]
        if (step == 0) {
            // Blend between center and first motion step
            const GVec3* nextVerts = d_motionVertices + tri.motionOffset;
            p0 = tri.v0 * (1.0f - t) + nextVerts[0] * t;
            p1 = tri.v1 * (1.0f - t) + nextVerts[1] * t;
            p2 = tri.v2 * (1.0f - t) + nextVerts[2] * t;
        } else {
            // Blend between two motion steps
            const GVec3* currVerts = d_motionVertices + tri.motionOffset + (step - 1) * 3;
            const GVec3* nextVerts = d_motionVertices + tri.motionOffset + step * 3;
            p0 = currVerts[0] * (1.0f - t) + nextVerts[0] * t;
            p1 = currVerts[1] * (1.0f - t) + nextVerts[1] * t;
            p2 = currVerts[2] * (1.0f - t) + nextVerts[2] * t;
        }
    }
    GVec3 e1 = p1 - p0;
    GVec3 e2 = p2 - p0;
    GVec3 h  = ray.direction.cross(e2);
    float a  = e1.dot(h);
    if (fabsf(a) < EPS) return false;

    float f  = 1.f / a;
    GVec3 s  = ray.origin - p0;
    float u  = f * s.dot(h);
    if (u < 0.f || u > 1.f) return false;

    GVec3 q = s.cross(e1);
    float v = f * ray.direction.dot(q);
    if (v < 0.f || u + v > 1.f) return false;

    float t_hit = f * e2.dot(q);
    if (t_hit < tMin || t_hit > tMax) return false;

    rec.t     = t_hit;
    rec.point = ray.at(t_hit);

    // pkg55-followup: skip redundant interpolation for flat-shaded triangles
    GVec3 outwardNormal;
    if (tri.flat_shaded) {
        outwardNormal = tri.n0;
    } else {
        float w = 1.f - u - v;
        outwardNormal = (tri.n0 * w + tri.n1 * u + tri.n2 * v).normalized();
    }

    rec.frontFace = ray.direction.dot(outwardNormal) < 0.f;
    rec.normal    = rec.frontFace ? outwardNormal : -outwardNormal;
    gpu_buildONB(rec.normal, rec.tangent, rec.bitangent);

    rec.materialId = tri.materialId;
    rec.isDelta    = false;
    return true;
}

// ---------------------------------------------------------------------------
// Ray-triangle intersection: Möller–Trumbore (exact port from raytracer.h)
// STATIC VARIANT — no motion. Kept for backward compatibility and zero-overhead
// when motion is disabled.
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

    // pkg55-followup: skip redundant interpolation for flat-shaded triangles
    GVec3 outwardNormal;
    if (tri.flat_shaded) {
        // n0==n1==n2, already unit; avoid (n0*w + n1*u + n2*v).normalized()
        outwardNormal = tri.n0;
    } else {
        // Per-vertex normals present; interpolate and renormalize
        float w = 1.f - u - v;
        outwardNormal = (tri.n0 * w + tri.n1 * u + tri.n2 * v).normalized();
    }

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
    GHitRecord&       rec,
    // pkg88-C.0: device motion-vertex buffer. nullptr = no deformation motion
    // anywhere in the scene (default keeps motion-agnostic callers — photon
    // pre-pass, TLAS parity probe, wavefront — unchanged).
    const GVec3*     motionVerts = nullptr)
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
                        // pkg88-C.0: motion-aware leaf dispatch (union-AABB BVH;
                        // the node bounds already enclose all time steps).
                        const GTriangle& tri = tris[p.index];
                        if (motionVerts != nullptr && tri.motionOffset >= 0) {
                            isHit = gpu_triangle_hit_motion(tri, ray, tMin, tMax, tmpRec, motionVerts);
                        } else {
                            isHit = gpu_triangle_hit(tri, ray, tMin, tMax, tmpRec);
                        }
                    } else if (p.type == GPRIM_SPHERE) {
                        isHit = gpu_sphere_hit(spheres[p.index], ray, tMin, tMax, tmpRec);
                    } else {
                        // pkg85-C: GPRIM_SKIP placeholder — see gpu_types.h.
                        isHit = false;
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
// pkg114 — Two-level traversal: a TLAS (BVH over instance world-AABBs) whose
// leaves are GInstance records, each referencing a BLAS (the per-mesh BVH this
// file's gpu_bvh_hit traverses) plus a 4x4 object<->world transform pair.
//
// Source: pbrt-v4 (Apache-2.0), Pharr/Jakob/Humphreys —
//   src/pbrt/cpu/primitive.cpp TransformedPrimitive::Intersect;
//   src/pbrt/util/transform.h  Transform::ApplyInverse(const Ray&, Float*).
// Source: Cycles (Apache-2.0), Blender Foundation —
//   src/kernel/bvh/bvh.h bvh_instance_push; src/util/transform.h
//   transform_point / transform_direction (un-normalized) /
//   transform_direction_transposed (normal by inverse-transpose).
// See .astroray_plan/docs/two-level-bvh-research.md.
//
// Invariants (load-bearing):
//  - The world ray is transformed into BLAS-local space with the instance's
//    objectFromWorld (Minv); the local direction is NOT renormalized, so local
//    t == world t and the global tMax is one shared cutoff across both levels.
//    We bypass the GRay(o,d) ctor (which renormalizes) by default-construct +
//    field-assign — the same precedent as src/gpu/wavefront/stage_intersect.cu.
//  - The local hit's GEOMETRIC outward normal is recovered (frontFace ? n : -n),
//    transformed by (Minv)^T, renormalized; frontFace is RECOMPUTED in world
//    space vs the world ray (recomputing from the already-oriented normal would
//    always read "front" since the oriented normal always points against the
//    ray, and it would mis-handle mirror/negative-det transforms). The world
//    ONB is rebuilt from the world normal so the shading frame matches a
//    flattened-world-space reference.
//  - rec.primId is remapped BLAS-local -> global (blas.primOffset + localPrimId)
//    so prims[rec.primId] (Cryptomatte / NEE) keeps working unchanged.
// ---------------------------------------------------------------------------
__device__ inline bool gpu_tlas_hit(
    const GTLASNode*  tlas,
    const GInstance*  instances,
    const GBLAS*      blas,
    const GBVHNode*   blasNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GRay&       ray,
    float tMin, float tMax,
    GHitRecord&       rec,
    // pkg88-C.0: motion verts apply to the classic single-level path only.
    // Deformation motion on INSTANCED meshes is out of scope v1 (the BLAS
    // walk below intentionally does not receive the buffer).
    const GVec3*      motionVerts = nullptr)
{
    // No TLAS uploaded -> behave exactly like the single-level path. (Lets a
    // caller route unconditionally through gpu_tlas_hit before instances exist.)
    if (!tlas || !instances || !blas) {
        return gpu_bvh_hit(blasNodes, prims, tris, spheres, ray, tMin, tMax, rec, motionVerts);
    }

    bool  hit    = false;
    GVec3 invDir(1.f/ray.direction.x,
                 1.f/ray.direction.y,
                 1.f/ray.direction.z);
    int   dirIsNeg[3] = { invDir.x < 0, invDir.y < 0, invDir.z < 0 };
    int   toVisit = 0, curr = 0;
    int   stack[64];

    while (true) {
        const GTLASNode& n = tlas[curr];

        if (n.bounds.hit(ray, tMin, tMax)) {        // TLAS AABB: world space, world ray
            if (n.nPrimitives > 0) {
                // Leaf: a list of instances.
                for (int i = 0; i < n.nPrimitives; ++i) {
                    const GInstance& inst = instances[n.primitivesOffset + i];
                    const GBLAS&     b    = blas[inst.blasIndex];

                    // World ray -> BLAS-local space. Bypass the GRay ctor so the
                    // local direction stays un-normalized (tMax comparability).
                    GRay local;
                    local.origin    = inst.objectFromWorld.xformPoint(ray.origin);
                    local.direction = inst.objectFromWorld.xformDir(ray.direction);

                    GHitRecord lrec;
                    lrec.primId = -1;
                    // Shared, un-scaled tMax: lrec.t comes back in world units.
                    // The BLAS's leaf primitivesOffset is BLAS-LOCAL, so the prims
                    // base is offset by blas.primOffset; tris/spheres are indexed
                    // by GPrimitive.index which is already global (no offset).
                    bool ih = gpu_bvh_hit(blasNodes + b.nodeOffset, prims + b.primOffset,
                                          tris, spheres, local, tMin, tMax, lrec);
                    if (ih && lrec.t < tMax) {
                        hit  = true;
                        tMax = lrec.t;              // tighten the shared cutoff

                        // Recover local geometric outward normal, transform to
                        // world by inverse-transpose, recompute frontFace.
                        GVec3 geomOut_l = lrec.frontFace ? lrec.normal : (lrec.normal * -1.f);
                        GVec3 geomOut_w = inst.objectFromWorld
                                              .xformNormalByInvTranspose(geomOut_l)
                                              .normalized();
                        bool ff = ray.direction.dot(geomOut_w) < 0.f;

                        rec            = lrec;       // t, materialId, isDelta carry over
                        rec.t          = lrec.t;     // world units, unchanged
                        rec.point      = inst.worldFromObject.xformPoint(lrec.point);
                        rec.frontFace  = ff;
                        rec.normal     = ff ? geomOut_w : (geomOut_w * -1.f);
                        gpu_buildONB(rec.normal, rec.tangent, rec.bitangent);
                        rec.primId     = b.primOffset + lrec.primId;
                    }
                }
                if (toVisit == 0) break;
                curr = stack[--toVisit];
            } else {
                // Interior: same near/far ordering as gpu_bvh_hit.
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

// pkg63: forward transform — apply baked rotation matrix M (world dir → env-map dir).
__device__ inline GVec3 gpu_envmap_apply_rot(const GEnvMap& em, const GVec3& d) {
    return GVec3(em.rotMat[0]*d.x + em.rotMat[1]*d.y + em.rotMat[2]*d.z,
                 em.rotMat[3]*d.x + em.rotMat[4]*d.y + em.rotMat[5]*d.z,
                 em.rotMat[6]*d.x + em.rotMat[7]*d.y + em.rotMat[8]*d.z);
}
// pkg63: inverse transform — apply M^T (env-map dir → world dir).
__device__ inline GVec3 gpu_envmap_apply_rot_T(const GEnvMap& em, const GVec3& d) {
    return GVec3(em.rotMat[0]*d.x + em.rotMat[3]*d.y + em.rotMat[6]*d.z,
                 em.rotMat[1]*d.x + em.rotMat[4]*d.y + em.rotMat[7]*d.z,
                 em.rotMat[2]*d.x + em.rotMat[5]*d.y + em.rotMat[8]*d.z);
}

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
    float phi   = (uCont - 0.5f) * 2.f * M_PI_F;

    GVec3 dir_env = GVec3(sinf(theta)*cosf(phi), cosf(theta), sinf(theta)*sinf(phi));
    es.direction = gpu_envmap_apply_rot_T(em, dir_env);

    float sinTheta = fmaxf(sinf(theta), 1e-6f);
    int   pixIdx   = v * em.width + u;
    float funcVal  = em.conditionalFunc[pixIdx];
    float mapPdf   = funcVal * em.width * em.height / (em.totalPower + 1e-10f);
    es.pdf         = mapPdf / (2.f * M_PI_F * M_PI_F * sinTheta);

    // pkg63: apply color tint to radiance (Cycles parity).
    es.radiance = GVec3(em.data[pixIdx*3+0] * em.colorTint[0],
                        em.data[pixIdx*3+1] * em.colorTint[1],
                        em.data[pixIdx*3+2] * em.colorTint[2]) * em.strength;
    return es;
}

__device__ inline float gpu_envmap_pdf(const GEnvMap& em, const GVec3& dir) {
    if (!em.loaded || em.totalPower <= 0.f) return 0.f;
    GVec3 d = gpu_envmap_apply_rot(em, dir);
    float theta = acosf(fminf(fmaxf(d.y, -1.f), 1.f));
    float phi   = atan2f(d.z, d.x);
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
    GVec3 d = gpu_envmap_apply_rot(em, dir);
    float theta = acosf(fminf(fmaxf(d.y, -1.f), 1.f));
    float phi   = atan2f(d.z, d.x);
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
    // pkg63: apply color tint (Cycles: env_sample * background_color * strength).
    c = GVec3(c.x * em.colorTint[0], c.y * em.colorTint[1], c.z * em.colorTint[2]);
    return c * em.strength;
}
