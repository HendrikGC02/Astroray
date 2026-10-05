#pragma once
// GPU BVH traversal and primitive intersection.
// Ported from BVHAccel::hit(), Triangle::hit(), and Sphere::hit() in raytracer.h.
// Only include from .cu files compiled by nvcc.

#include "gpu_types.h"
#include "gpu_materials.h"  // for gpu_buildONB
#include "gpu_curve_intersect.cuh"  // pkg225 Stage 3 — gpu_curve_intersect

// ---------------------------------------------------------------------------
// pkg225 Stage 3 — HasCurves template axis: the curve leaf (a __noinline__
// gpu_curve_intersect call + its Frame-stack frame) measurably raises the
// intersect kernel's register/stack footprint (127->158 REG, 616->1704 STACK on
// stageIntersectQueuedKernel<0,0>), dropping register-limited occupancy on the
// UNIVERSAL intersect path. `template<bool HasCurves=false>` + `if constexpr`
// keeps every non-curve caller (photon pre-pass, TLAS-parity, and the intersect
// kernel's <false> specialization) byte-identical — the curve branch (and its
// call) is dead-code-eliminated. Only scenes that actually upload curve segments
// launch the <true> intersect/shadow kernels and pay the cost.

// ---------------------------------------------------------------------------
// Watertight ray/triangle test: Woop, Benthin, Wald, "Watertight Ray/Triangle
// Intersection", JCGT 2(1), 2013, with the error-free edge-function product
// (DifferenceOfProducts via FMA) as in pbrt-v4 shapes.h (Apache-2.0). The
// paper's double-precision fallback for exactly-zero edge functions is omitted:
// it costs registers in the intersect kernel and a zero edge counts as inside for
// both neighbours, so shared edges still do not leak. Replaces an absolute |det| < 1e-6 Moller-Trumbore rejection that
// dropped small/grazing triangles (#1000). Mirrors astroray::watertightTriangle
// in watertight_triangle.h so the CPU oracle and this fallback agree. Returns t and the
// barycentric weights (u, v) of (p1, p2), as the Moller-Trumbore code did.
// ---------------------------------------------------------------------------
__device__ inline float gpu_dop(float a, float b, float c, float d) {
    float w = d * c;
    float e = fmaf(-d, c, w);
    float f = fmaf(a, b, -w);
    return f + e;
}

__device__ inline bool gpu_triangle_watertight(
    const GVec3& p0, const GVec3& p1, const GVec3& p2, const GRay& ray,
    float tMin, float tMax, float& t_out, float& u_out, float& v_out)
{
    const GVec3 d = ray.direction;
    float adx = fabsf(d.x), ady = fabsf(d.y), adz = fabsf(d.z);
    int kz = (adx > ady) ? ((adx > adz) ? 0 : 2) : ((ady > adz) ? 1 : 2);
    int kx = kz + 1; if (kx == 3) kx = 0;
    int ky = kx + 1; if (ky == 3) ky = 0;
    float dz = d[kz];
    if (dz == 0.f) return false;
    GVec3 a = p0 - ray.origin, b = p1 - ray.origin, c = p2 - ray.origin;
    float Sz = 1.f / dz, Sx = -d[kx] * Sz, Sy = -d[ky] * Sz;
    float ax = a[kx] + Sx * a[kz], ay = a[ky] + Sy * a[kz];
    float bx = b[kx] + Sx * b[kz], by = b[ky] + Sy * b[kz];
    float cx = c[kx] + Sx * c[kz], cy = c[ky] + Sy * c[kz];
    float e0 = gpu_dop(bx, cy, by, cx);
    float e1 = gpu_dop(cx, ay, cy, ax);
    float e2 = gpu_dop(ax, by, ay, bx);
    if ((e0 < 0.f || e1 < 0.f || e2 < 0.f) && (e0 > 0.f || e1 > 0.f || e2 > 0.f)) return false;
    float det = e0 + e1 + e2;
    if (det == 0.f) return false;
    float tScaled = e0 * (Sz * a[kz]) + e1 * (Sz * b[kz]) + e2 * (Sz * c[kz]);
    float invDet = 1.f / det;
    float t = tScaled * invDet;
    if (t < tMin || t > tMax) return false;
    t_out = t; u_out = e1 * invDet; v_out = e2 * invDet;
    return true;
}

// pkg88-C.0 GPU — verify on RTX. Motion-aware triangle hit: interpolate vertices
// at ray.time before Möller-Trumbore. Per Cycles motion_triangle.h (Apache-2.0):
// linear blend between bracketing time steps. If motionOffset < 0, falls back to static.
// ---------------------------------------------------------------------------
__device__ inline bool gpu_triangle_hit_motion(
    const GTriangle& tri, const GRay& ray, float tMin, float tMax,
    GHitRecord& rec, const GVec3* d_motionVertices)
{
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
    float t_hit, u, v;
    if (!gpu_triangle_watertight(p0, p1, p2, ray, tMin, tMax, t_hit, u, v)) return false;

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

// #947 — shading normal of a motion triangle at ray time, evaluated ONCE at the final
// accepted hit by gpu_bvh_hit (never per traversal candidate, so the closest-hit
// kernels pay nothing for it). __noinline__: only motion-blur scenes ever call it.
// Re-derives (t, u, v) with the same watertight test on the same time-interpolated
// vertices (bit-identical result), then follows Cycles motion_triangle_normal /
// motion_triangle_smooth_normal (Apache-2.0): flat -> facet normal of the interpolated
// vertices; smooth -> each end-lerped vertex normal normalised BEFORE the barycentric
// blend, `is_zero(N) ? Ng : N`. motionSteps == 2 only (buffer layout per triangle:
// [v0_end, v1_end, v2_end, n0_end, n1_end, n2_end]; enforced by Triangle::setMotionData).
__device__ __noinline__ inline void gpu_motion_triangle_finalize(
    const GTriangle& tri, const GRay& ray, const GVec3* d_motionVertices, GHitRecord& rec)
{
    const GVec3* e = d_motionVertices + tri.motionOffset;
    const float t = ray.time;  // maxStep == 1: step 0, blend factor == time
    const GVec3 p0 = tri.v0 * (1.0f - t) + e[0] * t;
    const GVec3 p1 = tri.v1 * (1.0f - t) + e[1] * t;
    const GVec3 p2 = tri.v2 * (1.0f - t) + e[2] * t;
    float t_hit, u, v;
    if (!gpu_triangle_watertight(p0, p1, p2, ray, 0.f, 3.0e38f, t_hit, u, v)) return;
    GVec3 n = (p1 - p0).cross(p2 - p0).normalized();
    if (!tri.flat_shaded) {
        const float w = 1.f - u - v;
        const GVec3 nm0 = (tri.n0 * (1.0f - t) + e[3] * t).normalized();
        const GVec3 nm1 = (tri.n1 * (1.0f - t) + e[4] * t).normalized();
        const GVec3 nm2 = (tri.n2 * (1.0f - t) + e[5] * t).normalized();
        const GVec3 ns = (nm0 * w + nm1 * u + nm2 * v).normalized();
        if (ns.length2() > 0.f) n = ns;
    }
    rec.frontFace = ray.direction.dot(n) < 0.f;
    rec.normal    = rec.frontFace ? n : -n;
    gpu_buildONB(rec.normal, rec.tangent, rec.bitangent);
}

// ---------------------------------------------------------------------------
// Hit record of a static triangle from its hit distance t and barycentrics
// (u, v) = weights of (v1, v2). Shared by the Möller–Trumbore test below and the
// pkg299 OptiX hit reconstruction (gpu_hw_hit_record), so both paths build the
// record with one piece of code.
// ---------------------------------------------------------------------------
__device__ inline void gpu_triangle_fill_rec(
    const GTriangle& tri, const GRay& ray, float t, float u, float v,
    GHitRecord& rec)
{
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
}

// ---------------------------------------------------------------------------
// Ray-triangle intersection: watertight, Woop 2013 (gpu_triangle_watertight)
// STATIC VARIANT — no motion. Kept for backward compatibility and zero-overhead
// when motion is disabled.
// ---------------------------------------------------------------------------
__device__ inline bool gpu_triangle_hit(
    const GTriangle& tri, const GRay& ray, float tMin, float tMax,
    GHitRecord& rec)
{
    float t, u, v;
    if (!gpu_triangle_watertight(tri.v0, tri.v1, tri.v2, ray, tMin, tMax, t, u, v)) return false;

    gpu_triangle_fill_rec(tri, ray, t, u, v, rec);
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

// #1092 — curve self-intersection skip. Cycles intersection_skip_self compares
// the primitive's prim_index, which for curves is the CURVE (strand) index
// (intern/cycles/bvh/build.cpp add_reference_curves; kernel/bvh/util.h), so a ray
// leaving a strand skips all of its segments. `skipPrim` = ordered-prim index of
// the segment the ray leaves (-1 none; may be a non-curve prim -> no skip);
// `seg` = the candidate segment at ordered-prim index `primIdx`. Called on curve
// leaf candidates only: one load of the skipped prim + its segment's strandId.
__device__ inline bool gpu_curve_skip_self(const GPrimitive* prims,
                                           const GCurveSegment* curves,
                                           int primIdx, int skipPrim,
                                           const GCurveSegment& seg)
{
    if (skipPrim < 0) return false;
    if (primIdx == skipPrim) return true;
    if (seg.strandId < 0) return false;
    const GPrimitive& sp = prims[skipPrim];
    return sp.type == GPRIM_CURVE && curves[sp.index].strandId == seg.strandId;
}

// ---------------------------------------------------------------------------
// Iterative BVH traversal — direct port of BVHAccel::hit()
// Thread-local stack[64] matches the CPU implementation.
// ---------------------------------------------------------------------------
template<bool HasCurves = false>  // pkg225 Stage 3 — curve-leaf isolation (see header)
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
    const GVec3*     motionVerts = nullptr,
    // pkg225 Stage 3: device curve-segment array. nullptr = no curves (default
    // keeps every non-curve caller byte-identical — the GPRIM_CURVE leaf below
    // is guarded on `curves`, and the intersection body is __noinline__ so it
    // adds only a guarded call to the inlined traversal loop).
    const GCurveSegment* curves = nullptr,
    // #1037: ordered-prim index (relative to `prims`) of the curve segment the
    // ray leaves; that segment is skipped (Cycles intersection_skip_self,
    // kernel/bvh/util.h). -1 = none. Only the HasCurves curve leaf reads it.
    int skipPrim = -1,
    // #36: primitives whose GPrimitive::flags intersect this mask are invisible to
    // this traversal (Cycles ray visibility mask; GPRIM_FLAG_INDIRECT_ONLY for a
    // camera ray). 0 = nothing skipped; constant-folds away for every caller that
    // leaves the default.
    int skipFlags = 0)
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
                    if (p.flags & skipFlags) continue;  // #36
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
                    } else if constexpr (HasCurves) {
                        // pkg225 Stage 3 — curve leaf (ribbon/thick swept-circle).
                        // if constexpr: DCE'd entirely in the <false> fleet path,
                        // so the __noinline__ gpu_curve_intersect call never enters
                        // the non-curve intersect kernel's register/stack budget.
                        if (curves != nullptr && p.type == GPRIM_CURVE &&
                            !gpu_curve_skip_self(prims, curves, (int)(n.primitivesOffset + i),
                                                 skipPrim, curves[p.index]))
                            isHit = gpu_curve_intersect(curves[p.index], ray, tMin, tMax, tmpRec);
                        // else GPRIM_SKIP / own strand (#1037, #1092) → isHit stays false
                    }
                    // (HasCurves=false: GPRIM_CURVE/SKIP fall through, isHit stays false)
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
    // #947: the motion triangle's shading normal at ray time, only for the accepted hit.
    if (hit && motionVerts != nullptr) {
        const GPrimitive& hp = prims[rec.primId];
        if (hp.type == GPRIM_TRIANGLE && tris[hp.index].motionOffset >= 0)
            gpu_motion_triangle_finalize(tris[hp.index], ray, motionVerts, rec);
    }
    return hit;
}

// ---------------------------------------------------------------------------
// pkg55-B' any-hit shadow traversal: boolean occlusion query — returns true
// on the FIRST accepted primitive hit, with no closest tracking, no hit
// record, and no tangent-frame construction. The classic shadow-ray
// optimization: PBRT-v4 Primitive::IntersectP (src/pbrt/cpu/aggregates.cpp,
// Apache-2.0); Cycles scene_intersect_shadow / BVH_FUNCTION any-hit walks
// (src/kernel/bvh/, Apache-2.0). Same node walk and leaf predicates as
// gpu_bvh_hit above so accept/reject decisions are identical; only the
// early-exit differs.
// ---------------------------------------------------------------------------
template<bool HasCurves = false>  // pkg225 Stage 3 — curve-leaf isolation (see header)
__device__ inline bool gpu_bvh_occluded(
    const GBVHNode*  nodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GRay&       ray,
    float tMin, float tMax,
    const GVec3*     motionVerts = nullptr,
    // pkg225 Stage 3 — curves cast shadows too (any-hit). nullptr = no curves.
    const GCurveSegment* curves = nullptr,
    int skipPrim = -1)  // #1037: see gpu_bvh_hit
{
    if (!nodes) return false;

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
                for (int i = 0; i < n.nPrimitives; ++i) {
                    const GPrimitive& p = prims[n.primitivesOffset + i];
                    GHitRecord tmpRec;
                    bool isHit = false;
                    if (p.type == GPRIM_TRIANGLE) {
                        const GTriangle& tri = tris[p.index];
                        if (motionVerts != nullptr && tri.motionOffset >= 0) {
                            isHit = gpu_triangle_hit_motion(tri, ray, tMin, tMax, tmpRec, motionVerts);
                        } else {
                            isHit = gpu_triangle_hit(tri, ray, tMin, tMax, tmpRec);
                        }
                    } else if (p.type == GPRIM_SPHERE) {
                        isHit = gpu_sphere_hit(spheres[p.index], ray, tMin, tMax, tmpRec);
                    } else if constexpr (HasCurves) {
                        if (curves != nullptr && p.type == GPRIM_CURVE &&
                            !gpu_curve_skip_self(prims, curves, (int)(n.primitivesOffset + i),
                                                 skipPrim, curves[p.index]))  // #1037, #1092
                            isHit = gpu_curve_intersect(curves[p.index], ray, tMin, tMax, tmpRec);
                    }
                    if (isHit) return true;  // any hit occludes
                }
                if (toVisit == 0) break;
                curr = stack[--toVisit];
            } else {
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
    return false;
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
// Instance-local hit -> world hit record (the invariants above). Shared by
// gpu_tlas_hit and the pkg299 OptiX hit reconstruction.
__device__ inline void gpu_instance_rec_to_world(
    const GInstance& inst, const GBLAS& b, const GRay& ray,
    const GHitRecord& lrec, GHitRecord& rec)
{
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

template<bool HasCurves = false>  // pkg225 Stage 3 — forwarded to the single-level fallback
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
    const GVec3*      motionVerts = nullptr,
    // pkg225 Stage 3: curves live in the flat scene (addObject → orderedPrims),
    // never in a registered-mesh BLAS. With a TLAS the flat scene is the
    // identity-transform BLAS (pkg114 inc 3b), so curves go into the BLAS walk
    // too (#963: dropping them hid every strand once a scene had instances).
    // Registered-mesh BLASes hold no GPRIM_CURVE, so the leaf never fires there.
    const GCurveSegment* curves = nullptr,
    // #1037: GLOBAL ordered-prim index of the curve segment the ray leaves
    // (GHitRecord::primId of the previous vertex); -1 = none.
    int skipPrim = -1,
    int skipFlags = 0)  // #36: see gpu_bvh_hit
{
    // No TLAS uploaded -> behave exactly like the single-level path. (Lets a
    // caller route unconditionally through gpu_tlas_hit before instances exist.)
    if (!tlas || !instances || !blas) {
        return gpu_bvh_hit<HasCurves>(blasNodes, prims, tris, spheres, ray, tMin, tMax, rec,
                                      motionVerts, curves, skipPrim, skipFlags);
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
                    bool ih = gpu_bvh_hit<HasCurves>(blasNodes + b.nodeOffset, prims + b.primOffset,
                                          tris, spheres, local, tMin, tMax, lrec,
                                          nullptr, curves,
                                          skipPrim >= 0 ? skipPrim - b.primOffset : -1,
                                          skipFlags);
                    if (ih && lrec.t < tMax) {
                        hit  = true;
                        tMax = lrec.t;              // tighten the shared cutoff
                        gpu_instance_rec_to_world(inst, b, ray, lrec, rec);
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
// Any-hit form of gpu_tlas_hit (pkg55-B' shadow rays). No TLAS -> the lean
// gpu_bvh_occluded walk (the wavefront path). With a TLAS, v1 delegates to
// the closest-hit instance walk and discards the record — boolean-identical;
// a dedicated any-hit instance walk is a follow-up optimization.
template<bool HasCurves = false>  // pkg225 Stage 3 — forwarded to the single-level fallback
__device__ inline bool gpu_tlas_occluded(
    const GTLASNode*  tlas,
    const GInstance*  instances,
    const GBLAS*      blas,
    const GBVHNode*   blasNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GRay&       ray,
    float tMin, float tMax,
    const GVec3*      motionVerts = nullptr,
    // pkg225 Stage 3 — curves cast shadows (both paths; see gpu_tlas_hit, #963).
    const GCurveSegment* curves = nullptr,
    int skipPrim = -1)  // #1037: see gpu_tlas_hit
{
    if (!tlas || !instances || !blas) {
        return gpu_bvh_occluded<HasCurves>(blasNodes, prims, tris, spheres,
                                ray, tMin, tMax, motionVerts, curves, skipPrim);
    }
    GHitRecord rec;
    return gpu_tlas_hit<HasCurves>(tlas, instances, blas, blasNodes, prims, tris,
                        spheres, ray, tMin, tMax, rec, motionVerts, curves, skipPrim);
}

// ---------------------------------------------------------------------------
// pkg299 — rebuild the hit record of an OptiX hardware-traversal hit from what
// the closest-hit program returned (t, primitive, barycentrics b1/b2, instance).
// OptiX reports the same (u, v) Möller–Trumbore yields (P = (1-u-v) v0 + u v1 +
// v v2; OptiX 9.1 optixGetTriangleBarycentrics) and the world-ray t (instance
// transforms keep the direction unnormalised, as gpu_tlas_hit does). The record
// is built by the SAME helpers as the software path, so shading sees identical
// record semantics; only t/u/v can differ, by the watertight hardware test.
// Scenes routed here are triangle-only with no motion (the driver's gate).
// inst < 0: flat GAS, prim = global prims[] index. inst >= 0: IAS instance
// index into `instances`, prim = BLAS-local index.
// ---------------------------------------------------------------------------
__device__ inline bool gpu_hw_hit_record(
    float t, int prim, float u, float v, int inst,
    const GInstance* instances, const GBLAS* blas,
    const GPrimitive* prims, const GTriangle* tris,
    const GRay& ray, GHitRecord& rec)
{
    if (!(t >= 0.f)) return false;   // miss (-1) or dead slot
    if (inst < 0) {
        gpu_triangle_fill_rec(tris[prims[prim].index], ray, t, u, v, rec);
        rec.primId = prim;
        return true;
    }
    const GInstance& in = instances[inst];
    const GBLAS&     b  = blas[in.blasIndex];
    GRay local;   // bypass the GRay ctor: keep the local direction unnormalised
    local.origin    = in.objectFromWorld.xformPoint(ray.origin);
    local.direction = in.objectFromWorld.xformDir(ray.direction);
    GHitRecord lrec;
    gpu_triangle_fill_rec(tris[prims[b.primOffset + prim].index], local, t, u, v, lrec);
    lrec.primId = prim;
    gpu_instance_rec_to_world(in, b, ray, lrec, rec);
    return true;
}

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

// Forward declaration: gpu_envmap_sample returns the bilinear radiance at the
// sampled direction (defined below), matching the CPU EnvironmentMap::sample.
__device__ inline GVec3 gpu_envmap_lookup(const GEnvMap& em, const GVec3& dir);

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

// pkg258: environment CDF sampler from EXPLICIT uniforms (xi1, xi2), returning
// only the direction + solid-angle pdf (NO radiance lookup). Used by the GPU
// wavefront env-NEE generate body, which draws its two uniforms directly from the
// per-path PCG32 stream (WavefrontRNG) rather than a curandState, and defers the
// spectral radiance to the env shadow-resolve kernel (register economy in the
// REG-254 shade kernel). The direction/pdf math is IDENTICAL to gpu_envmap_sample
// (continuous within-texel residual remap + lat-long Jacobian); factored so the
// two share one contract.
__device__ inline GEnvSample gpu_envmap_sample_dir_pdf(const GEnvMap& em,
                                                       float xi1, float xi2) {
    GEnvSample es;
    es.pdf = 0.f;
    es.radiance = GVec3(0.f);
    es.direction = GVec3(0,1,0);
    if (!em.loaded || em.totalPower <= 0.f) return es;

    int v = gpu_lower_bound(em.marginalCdf, em.height, xi1);
    if (v >= em.height) v = em.height - 1;
    float vCdfLo = (v > 0) ? em.marginalCdf[v - 1] : 0.f;
    float vCdfHi = em.marginalCdf[v];
    float dv = (vCdfHi > vCdfLo) ? (xi1 - vCdfLo) / (vCdfHi - vCdfLo) : 0.5f;
    dv = fminf(fmaxf(dv, 0.f), 1.f);

    const float* condRow = em.conditionalCdf + v*em.width;
    int u = gpu_lower_bound(condRow, em.width, xi2);
    if (u >= em.width) u = em.width - 1;
    float uCdfLo = (u > 0) ? condRow[u - 1] : 0.f;
    float uCdfHi = condRow[u];
    float du = (uCdfHi > uCdfLo) ? (xi2 - uCdfLo) / (uCdfHi - uCdfLo) : 0.5f;
    du = fminf(fmaxf(du, 0.f), 1.f);

    float uCont = u + du;
    float vCont = v + dv;
    float theta = (1.f - vCont / em.height) * M_PI_F;
    float phi   = (uCont / em.width - 0.5f) * 2.f * M_PI_F;

    GVec3 dir_env = GVec3(sinf(theta)*cosf(phi), cosf(theta), sinf(theta)*sinf(phi));
    es.direction = gpu_envmap_apply_rot_T(em, dir_env);

    float sinTheta = fmaxf(sinf(theta), 1e-6f);
    int   pixIdx   = v * em.width + u;
    float funcVal  = em.conditionalFunc[pixIdx];
    float mapPdf   = funcVal * em.width * em.height / (em.totalPower + 1e-10f);
    es.pdf         = mapPdf / (2.f * M_PI_F * M_PI_F * sinTheta);
    return es;
}

__device__ inline GEnvSample gpu_envmap_sample(const GEnvMap& em, curandState* rng) {
    GEnvSample es;
    es.pdf = 0.f;
    es.radiance = GVec3(0.f);
    es.direction = GVec3(0,1,0);
    if (!em.loaded || em.totalPower <= 0.f) return es;

    float xi1 = curand_uniform(rng);
    float xi2 = curand_uniform(rng);

    // pkg258: remap the CDF residual to a continuous within-texel offset
    // (PBRT PiecewiseConstant1D::Sample / Cycles background_map_sample) so the
    // sampled direction is uniform inside the texel; pdf stays the texel's
    // piecewise-constant density. Mirrors the CPU EnvironmentMap::sample.
    int v = gpu_lower_bound(em.marginalCdf, em.height, xi1);
    if (v >= em.height) v = em.height - 1;
    float vCdfLo = (v > 0) ? em.marginalCdf[v - 1] : 0.f;
    float vCdfHi = em.marginalCdf[v];
    float dv = (vCdfHi > vCdfLo) ? (xi1 - vCdfLo) / (vCdfHi - vCdfLo) : 0.5f;
    dv = fminf(fmaxf(dv, 0.f), 1.f);

    const float* condRow = em.conditionalCdf + v*em.width;
    int u = gpu_lower_bound(condRow, em.width, xi2);
    if (u >= em.width) u = em.width - 1;
    float uCdfLo = (u > 0) ? condRow[u - 1] : 0.f;
    float uCdfHi = condRow[u];
    float du = (uCdfHi > uCdfLo) ? (xi2 - uCdfLo) / (uCdfHi - uCdfLo) : 0.5f;
    du = fminf(fmaxf(du, 0.f), 1.f);

    float uCont = u + du;
    float vCont = v + dv;
    // pkg258: azimuth uses NORMALISED u (uCont/width) -- exact inverse of
    // gpu_envmap_pdf's u = 0.5 + phi/(2*pi). Pre-pkg258 used uCont in PIXEL
    // units, wrapping phi to ~0 for every column (mirrors the CPU sample() bug).
    float theta = (1.f - vCont / em.height) * M_PI_F;
    float phi   = (uCont / em.width - 0.5f) * 2.f * M_PI_F;

    GVec3 dir_env = GVec3(sinf(theta)*cosf(phi), cosf(theta), sinf(theta)*sinf(phi));
    es.direction = gpu_envmap_apply_rot_T(em, dir_env);

    float sinTheta = fmaxf(sinf(theta), 1e-6f);
    int   pixIdx   = v * em.width + u;
    float funcVal  = em.conditionalFunc[pixIdx];
    float mapPdf   = funcVal * em.width * em.height / (em.totalPower + 1e-10f);
    es.pdf         = mapPdf / (2.f * M_PI_F * M_PI_F * sinTheta);

    // pkg258: bilinear radiance at the sampled direction (matches the miss leg),
    // strength+tint applied inside gpu_envmap_lookup.
    es.radiance = gpu_envmap_lookup(em, es.direction);
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

// #832: bilinear taps at texel CENTRES (x = u*W - 0.5), u wraps, v clamps.
// Cycles kernel/device/cpu/image.h interp_bilinear (Apache-2.0). CPU twin:
// EnvironmentMap::bilinearTexels (raytracer.h) -- keep in lockstep.
__device__ inline void gpu_envmap_bilinear_texels(const GEnvMap& em, float u, float v,
                                                  int& x0, int& x1, int& y0, int& y1,
                                                  float& fu, float& fv) {
    float x = u * em.width - 0.5f, y = v * em.height - 0.5f;
    float fx = floorf(x), fy = floorf(y);
    fu = x - fx; fv = y - fy;
    x0 = (int)fx; y0 = (int)fy;
    x1 = x0 + 1; y1 = y0 + 1;
    x0 = (x0 % em.width + em.width) % em.width;
    x1 = (x1 % em.width + em.width) % em.width;
    y0 = y0 < 0 ? 0 : (y0 >= em.height ? em.height-1 : y0);
    y1 = y1 < 0 ? 0 : (y1 >= em.height ? em.height-1 : y1);
}

__device__ inline GVec3 gpu_envmap_lookup(const GEnvMap& em, const GVec3& dir) {
    if (!em.loaded || em.width == 0) return GVec3(0.f);
    GVec3 d = gpu_envmap_apply_rot(em, dir);
    float theta = acosf(fminf(fmaxf(d.y, -1.f), 1.f));
    float phi   = atan2f(d.z, d.x);
    float u     = 0.5f + phi / (2.f * M_PI_F);
    float v     = 1.f - theta / M_PI_F;
    if (u < 0.f) u += 1.f; if (u >= 1.f) u -= 1.f;

    int x0, x1, y0, y1; float uf, vf;
    gpu_envmap_bilinear_texels(em, u, v, x0, x1, y0, y1, uf, vf);

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
