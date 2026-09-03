#pragma once
// pkg225 Stage 3 — GPU ray-curve intersection (device port of the CPU
// CurveSegment::hit in include/astroray/curves.h).
//
// ALGORITHM (cited, not invented — CLAUDE.md §6; research note at
// .astroray_plan/docs/pkg225-curve-intersect-research.md):
//
//   pbrt-v3 Curve::Intersect / Curve::recursiveIntersect. Source: mmp/pbrt-v3,
//   src/shapes/curve.cpp, copyright Matt Pharr / Greg Humphreys / Wenzel Jakob,
//   BSD-2-Clause. This file ports the SAME math the CPU CurveSegment already
//   ships (which was itself the verbatim pbrt port), so GPU and CPU produce the
//   same hit up to float ULP.
//
// TWO MODES (pkg225 spec Stage 3 "Ribbon vs thick on GPU"):
//   - RIBBON (thick == 0, the GPU default): camera-facing flat strip. The same
//     recursive Bezier-hull 2D width test, but the shading normal is the flat
//     ray-facing perpendicular — NO Rodrigues rotation (transcendental-free
//     leaf). Cheaper; the viewport default.
//   - THICK  (thick == 1): pbrt CurveType::Cylinder swept-circle. The leaf
//     additionally rotates the flat perpendicular around the true curve tangent
//     by theta = lerp(v, -90deg, +90deg) to reconstruct a round shading normal.
//     This is the CPU-parity mode (curves.h uses Cylinder); the Stage-3 GPU-vs-
//     CPU mean-ratio gate renders in THICK so both backends run identical math.
//
// STL-free (no std::), device intrinsics only (fmaxf/fminf/sqrtf/...). The whole
// intersection is a single __noinline__ function so the recursive-subdivision
// locals live in ITS frame, not in the register budget of the (inlined)
// gpu_bvh_hit traversal loop / the REG:254 shade kernel — the pkg224
// __noinline__ isolation discipline (MEMORY noinline-runtime-flag-avoids-shade-
// spill). Parent must register-probe the intersect kernel to confirm.

#include "gpu_types.h"

#ifndef M_PI_F
#define M_PI_F 3.14159265358979323846f
#endif

namespace astroray_curve_detail {

__device__ inline float gClampf(float x, float lo, float hi) {
    return fminf(fmaxf(x, lo), hi);
}

__device__ inline GVec3 gLerp3(float t, const GVec3& a, const GVec3& b) {
    return a + (b - a) * t;
}

// pbrt EvalBezier — de Casteljau evaluation (+ optional derivative).
__device__ inline GVec3 gEvalBezier(const GVec3 cp[4], float u, GVec3* deriv) {
    GVec3 cp1[3] = { gLerp3(u, cp[0], cp[1]),
                     gLerp3(u, cp[1], cp[2]),
                     gLerp3(u, cp[2], cp[3]) };
    GVec3 cp2[2] = { gLerp3(u, cp1[0], cp1[1]),
                     gLerp3(u, cp1[1], cp1[2]) };
    if (deriv) {
        if ((cp2[1] - cp2[0]).length2() > 0.f) *deriv = (cp2[1] - cp2[0]) * 3.f;
        else                                    *deriv = cp[3] - cp[0];  // degenerate → chord
    }
    return gLerp3(u, cp2[0], cp2[1]);
}

// pbrt SubdivideBezier — de Casteljau midpoint split, 4 → 7 control points.
__device__ inline void gSubdivideBezier(const GVec3 cp[4], GVec3 out[7]) {
    out[0] = cp[0];
    out[1] = (cp[0] + cp[1]) * 0.5f;
    out[2] = (cp[0] + cp[1] * 2.f + cp[2]) * 0.25f;
    out[3] = (cp[0] + cp[1] * 3.f + cp[2] * 3.f + cp[3]) * 0.125f;
    out[4] = (cp[1] + cp[2] * 2.f + cp[3]) * 0.25f;
    out[5] = (cp[2] + cp[3]) * 0.5f;
    out[6] = cp[3];
}

// CPU raytracer.h buildOrthonormalBasis(n,u,v), ported verbatim — used only in
// the ray-parallel-to-chord degenerate fallback (pbrt CoordinateSystem).
__device__ inline void gBuildONB(const GVec3& n, GVec3& u, GVec3& v) {
    u = (fabsf(n.x) > 0.9f) ? GVec3(0.f, 1.f, 0.f) : GVec3(1.f, 0.f, 0.f);
    u = (u - n * n.dot(u)).normalized();
    v = n.cross(u);
}

// Rodrigues' rotation (rotate v by angleRad around unit axis a).
__device__ inline GVec3 gRotateAroundAxis(const GVec3& v, const GVec3& a, float angleRad) {
    float c = cosf(angleRad), s = sinf(angleRad);
    return v * c + a.cross(v) * s + a * (a.dot(v) * (1.f - c));
}

// pbrt's y-then-x-then-z ray-local-frame AABB reject.
__device__ inline bool gBoundsOverlapRay(const GVec3 cp[4], float radius,
                                         float tMin, float tMax) {
    float yMax = fmaxf(fmaxf(cp[0].y, cp[1].y), fmaxf(cp[2].y, cp[3].y));
    float yMin = fminf(fminf(cp[0].y, cp[1].y), fminf(cp[2].y, cp[3].y));
    if (yMax + radius < 0.f || yMin - radius > 0.f) return false;
    float xMax = fmaxf(fmaxf(cp[0].x, cp[1].x), fmaxf(cp[2].x, cp[3].x));
    float xMin = fminf(fminf(cp[0].x, cp[1].x), fminf(cp[2].x, cp[3].x));
    if (xMax + radius < 0.f || xMin - radius > 0.f) return false;
    float zMax = fmaxf(fmaxf(cp[0].z, cp[1].z), fmaxf(cp[2].z, cp[3].z));
    float zMin = fminf(fminf(cp[0].z, cp[1].z), fminf(cp[2].z, cp[3].z));
    if (zMax + radius < tMin || zMin - radius > tMax) return false;
    return true;
}

}  // namespace astroray_curve_detail

// ---------------------------------------------------------------------------
// Ray-curve intersection. Fills `rec` (point, front-face-oriented normal,
// tangent/bitangent ONB, uvTangent = ∂p/∂u strand tangent, hairV = azimuthal v,
// materialId) on the nearest hit inside [tMin, tMax]. Mirrors CurveSegment::hit.
//
// __noinline__: keep the recursive-subdivision frame out of the caller's
// register budget (see file header). Return value is the hit boolean; on true
// the caller narrows its own tMax (gpu_bvh_hit leaf contract).
// ---------------------------------------------------------------------------
__device__ __noinline__ inline bool gpu_curve_intersect(
    const GCurveSegment& seg, const GRay& ray, float tMin, float tMax,
    GHitRecord& rec)
{
    using namespace astroray_curve_detail;

    const GVec3 bez[4] = { seg.bezier0, seg.bezier1, seg.bezier2, seg.bezier3 };
    const float r0 = seg.radius0, r1 = seg.radius1;
    const float maxRadius = fmaxf(r0, r1);
    const bool  thick = (seg.thick != 0);

    // ---- Ray-local orthonormal frame (z = ray dir; already normalized). ----
    GVec3 zAxis = ray.direction;
    GVec3 chord = bez[3] - bez[0];
    GVec3 dxHint = zAxis.cross(chord);
    GVec3 xAxis, yAxis;
    if (dxHint.length2() < 1e-12f) {
        gBuildONB(zAxis, xAxis, yAxis);
    } else {
        GVec3 up = dxHint.normalized();
        xAxis = up.cross(zAxis).normalized();
        yAxis = zAxis.cross(xAxis);
    }

    // ---- Project the Bezier hull into the ray-local frame. ----
    GVec3 cp0[4];
    for (int i = 0; i < 4; ++i) {
        GVec3 d = bez[i] - ray.origin;
        cp0[i] = GVec3(d.dot(xAxis), d.dot(yAxis), d.dot(zAxis));
    }
    if (!gBoundsOverlapRay(cp0, maxRadius, tMin, tMax)) return false;

    // ---- Adaptive max recursion depth (pbrt L0/eps flatness heuristic). ----
    float L0 = 0.f;
    for (int i = 0; i < 2; ++i) {
        L0 = fmaxf(L0, fabsf(cp0[i].x - 2.f * cp0[i + 1].x + cp0[i + 2].x));
        L0 = fmaxf(L0, fabsf(cp0[i].y - 2.f * cp0[i + 1].y + cp0[i + 2].y));
        L0 = fmaxf(L0, fabsf(cp0[i].z - 2.f * cp0[i + 1].z + cp0[i + 2].z));
    }
    float eps = maxRadius * 0.1f;
    int maxDepth = 0;
    if (L0 > 0.f && eps > 0.f) {
        float val = 1.41421356f * 6.f * L0 / (8.f * eps);
        if (val >= 1.f) {
            int log2v = (int)floorf(log2f(val) + 0.5f);   // round-to-nearest
            int d = log2v / 2;
            maxDepth = d < 0 ? 0 : (d > 10 ? 10 : d);
        }
    }

    // ---- Iterative de Casteljau subdivision (explicit stack replaces the CPU
    // recursion; a shared running tMax reproduces the "nearest of two halves
    // wins + narrowing prune" semantics of CurveSegment::recursiveIntersect). --
    struct Frame { GVec3 cp[4]; float u0, u1; int depth; };
    Frame stack[16];
    int sp = 0;
    stack[0].cp[0] = cp0[0]; stack[0].cp[1] = cp0[1];
    stack[0].cp[2] = cp0[2]; stack[0].cp[3] = cp0[3];
    stack[0].u0 = 0.f; stack[0].u1 = 1.f; stack[0].depth = maxDepth;
    sp = 1;

    bool  hitAny = false;
    float bestT = tMax;   // narrows as closer hits are found
    float best_u = 0.f, best_v = 0.5f;

    while (sp > 0) {
        Frame f = stack[--sp];

        // Interior: split and push both halves (pruned against the running tMax).
        if (f.depth > 0) {
            GVec3 split[7];
            gSubdivideBezier(f.cp, split);
            float uMid = (f.u0 + f.u1) * 0.5f;
            float uArr[3] = { f.u0, uMid, f.u1 };
            const GVec3* segCp = split;
            for (int s = 0; s < 2; ++s, segCp += 3) {
                float ru0 = r0 + (r1 - r0) * uArr[s];
                float ru1 = r0 + (r1 - r0) * uArr[s + 1];
                float rMax = fmaxf(ru0, ru1);
                if (!gBoundsOverlapRay(segCp, rMax, tMin, bestT)) continue;
                if (sp < 16) {
                    Frame& nf = stack[sp++];
                    nf.cp[0] = segCp[0]; nf.cp[1] = segCp[1];
                    nf.cp[2] = segCp[2]; nf.cp[3] = segCp[3];
                    nf.u0 = uArr[s]; nf.u1 = uArr[s + 1]; nf.depth = f.depth - 1;
                }
            }
            continue;
        }

        // Leaf: flat 2D distance-to-chord width test (pbrt flattened test).
        const GVec3* cp = f.cp;
        float edge0 = (cp[1].y - cp[0].y) * -cp[0].y + cp[0].x * (cp[0].x - cp[1].x);
        if (edge0 < 0.f) continue;
        float edge1 = (cp[2].y - cp[3].y) * -cp[3].y + cp[3].x * (cp[3].x - cp[2].x);
        if (edge1 < 0.f) continue;

        float segDirX = cp[3].x - cp[0].x, segDirY = cp[3].y - cp[0].y;
        float denom = segDirX * segDirX + segDirY * segDirY;
        if (denom == 0.f) continue;
        float w = (-cp[0].x * segDirX + -cp[0].y * segDirY) / denom;

        float u = gClampf(f.u0 + (f.u1 - f.u0) * w, f.u0, f.u1);
        float hitRadius = r0 + (r1 - r0) * u;
        if (hitRadius <= 0.f) continue;

        GVec3 dpcdw;
        GVec3 pc = gEvalBezier(cp, gClampf(w, 0.f, 1.f), &dpcdw);
        float distSq = pc.x * pc.x + pc.y * pc.y;
        if (distSq > hitRadius * hitRadius) continue;
        if (pc.z < tMin || pc.z > bestT) continue;   // z == t (rayLength==1)

        float dist = sqrtf(distSq);
        float edgeFunc = dpcdw.x * -pc.y + pc.x * dpcdw.y;
        float v = (edgeFunc > 0.f) ? 0.5f + dist / (2.f * hitRadius)
                                   : 0.5f - dist / (2.f * hitRadius);

        // Accept — narrow tMax so a farther half can't overwrite.
        hitAny = true;
        bestT  = pc.z;
        best_u = u;
        best_v = v;
    }

    if (!hitAny) return false;

    // ---- Shading frame at the accepted hit (recompute from the global hull at
    // best_u, exactly like CurveSegment::recursiveIntersect's tail). ----
    GVec3 dpdu;
    gEvalBezier(bez, best_u, &dpdu);
    if (dpdu.length2() == 0.f) return false;

    GVec3 outwardNormal;
    GVec3 dpduPlane(dpdu.dot(xAxis), dpdu.dot(yAxis), dpdu.dot(zAxis));
    GVec3 dpdvPlane = GVec3(-dpduPlane.y, dpduPlane.x, 0.f);
    float hitRadius = r0 + (r1 - r0) * best_u;
    dpdvPlane = (dpdvPlane.length2() > 0.f)
                    ? dpdvPlane.normalized() * (2.f * hitRadius)
                    : GVec3(2.f * hitRadius, 0.f, 0.f);
    if (thick) {
        // Cylinder swept-circle: rotate the flat perpendicular around the true
        // tangent by theta = lerp(v, -90deg, +90deg).
        GVec3 dpduPlaneAxis = dpduPlane.normalized();
        float theta = (best_v - 0.5f) * M_PI_F;
        GVec3 dpdvRot = gRotateAroundAxis(dpdvPlane, dpduPlaneAxis, -theta);
        GVec3 dpdv = dpdvRot.x * xAxis + dpdvRot.y * yAxis + dpdvRot.z * zAxis;
        outwardNormal = dpdu.cross(dpdv).normalized();
    } else {
        // Ribbon: flat strip. The perpendicular (unrotated) → the ray-facing
        // plane normal; no transcendentals in the leaf's normal.
        GVec3 dpdv = dpdvPlane.x * xAxis + dpdvPlane.y * yAxis + dpdvPlane.z * zAxis;
        outwardNormal = dpdu.cross(dpdv).normalized();
    }

    // ---- Fill the hit record (setFaceNormal convention: orient the normal to
    // face the incoming ray; the curve's own tangent overrides uvTangent). ----
    float tHit = bestT;
    rec.t = tHit;
    rec.point = ray.at(tHit);
    rec.frontFace = ray.direction.dot(outwardNormal) < 0.f;
    rec.normal = rec.frontFace ? outwardNormal : -outwardNormal;
    gBuildONB(rec.normal, rec.tangent, rec.bitangent);
    rec.uvTangent = dpdu.normalized();     // strand tangent (∂p/∂u), pkg178 twin
    rec.uvBitangentSign = 1.f;
    rec.hairV = best_v;                    // azimuthal v (0.5 = fiber centre)
    rec.materialId = seg.materialId;
    rec.isDelta = false;
    return true;
}
