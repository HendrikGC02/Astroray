#pragma once
// pkg106 Chunk D — mesh caustic-caster seed-ray construction.
//
// Generalises the sphere-only SMS seed (uniform-on-sphere) to triangle-mesh
// casters. Mirrors Cycles mnee.h kernel_path_mnee_sample seed-ray construction
// (lines 29-44): cast a ray from the shading point x0 toward the light and
// collect the ordered intersections with caustic-caster surfaces — those become
// the initial specular vertex chain (a prism between x0 and the light gives two:
// the exit face then the entry face). The damped block Newton (manifold_chain.h)
// then walks them onto the specular manifold.
//
// For flat facets the Newton tangent step stays on the triangle's plane, so the
// per-vertex reprojection is the flat step already validated in manifold_chain.h
// (no per-step ray-cast needed while the vertex stays on its face).

#include "../../raytracer.h"
#include "manifold_chain.h"
#include <cmath>

namespace astroray::manifold {

// A flat caustic-caster triangle (geometric normal derived from the winding).
struct CausticTri {
    Vec3 v0, v1, v2;
};

// Möller-Trumbore ray-triangle intersection. Returns the front/back hit
// distance t along `d` (which need not be normalised); false on miss.
inline bool rayTriHit(const Vec3& o, const Vec3& d, const CausticTri& tri, float& tOut) {
    const Vec3 e1 = tri.v1 - tri.v0;
    const Vec3 e2 = tri.v2 - tri.v0;
    const Vec3 p = d.cross(e2);
    const float det = e1.dot(p);
    if (std::fabs(det) < 1e-12f) return false;
    const float inv = 1.0f / det;
    const Vec3 tv = o - tri.v0;
    const float u = tv.dot(p) * inv;
    if (u < -1e-5f || u > 1.0f + 1e-5f) return false;
    const Vec3 q = tv.cross(e1);
    const float v = d.dot(q) * inv;
    if (v < -1e-5f || u + v > 1.0f + 1e-5f) return false;
    const float t = e2.dot(q) * inv;
    tOut = t;
    return t > 1e-5f;
}

// Construct the seed chain by casting x0 -> light and collecting the ordered
// caustic-caster intersections (nearest x0 first). Each becomes a ChainVertex
// with the triangle's flat partials, geometric normal oriented to face x0, and
// the caster IOR. Returns the number of vertices (0 if the segment misses all
// casters, or > maxV which is treated as unsupported).
inline int seedChainFromRay(const CausticTri* tris, int nTris,
                            const Vec3& x0, const Vec3& light, float ior,
                            ChainVertex* outV, int maxV) {
    const Vec3 seg = light - x0;
    const float segLen = std::sqrt(seg.length2());
    if (segLen < 1e-9f) return 0;
    const Vec3 dir = seg * (1.0f / segLen);

    // Collect hits (t in (0, segLen)).
    float ts[2 * kMaxChainVertices];
    int idx[2 * kMaxChainVertices];
    int count = 0;
    for (int i = 0; i < nTris; ++i) {
        float t;
        if (!rayTriHit(x0, dir, tris[i], t)) continue;
        if (t <= 1e-4f || t >= segLen - 1e-4f) continue;
        if (count < 2 * kMaxChainVertices) { ts[count] = t; idx[count] = i; ++count; }
    }
    if (count == 0 || count > maxV) return 0;

    // Insertion-sort by t (nearest x0 first).
    for (int i = 1; i < count; ++i) {
        float kt = ts[i]; int ki = idx[i]; int j = i - 1;
        while (j >= 0 && ts[j] > kt) { ts[j + 1] = ts[j]; idx[j + 1] = idx[j]; --j; }
        ts[j + 1] = kt; idx[j + 1] = ki;
    }

    for (int i = 0; i < count; ++i) {
        const CausticTri& tri = tris[idx[i]];
        ChainVertex& v = outV[i];
        v.p = x0 + dir * ts[i];
        v.n = (tri.v1 - tri.v0).cross(tri.v2 - tri.v0).normalized();
        // Build an ORTHONORMAL in-plane (u,v) frame — NOT the raw edge vectors.
        // The manifold Newton steps along the unit tangents (s,t) and clamps the
        // (du,dv) magnitude; a non-unit parameterization (raw edges, length ~|edge|)
        // makes that clamp meaningless and the solve diverges. Verified: raw edges
        // -> no convergence; orthonormal frame -> 3 iterations. dp_du/dp_dv here are
        // exactly the (s,t) frame the constraint builds, so the flat reprojection
        // (p += s*du + t*dv) is consistent with the Jacobian's (u,v) measure.
        Vec3 e1 = tri.v1 - tri.v0;
        Vec3 s = e1 - v.n * e1.dot(v.n);
        float ls = std::sqrt(s.length2());
        s = (ls > 1e-12f) ? s * (1.0f / ls) : Vec3(1.0f, 0.0f, 0.0f);
        v.dp_du = s;
        v.dp_dv = v.n.cross(s);
        v.dn_du = Vec3(0.0f);   // flat facet
        v.dn_dv = Vec3(0.0f);
        v.eta = ior;
    }
    return count;
}

// Flat-facet reprojection for solveChain: the in-plane tangent step keeps the
// vertex on its triangle's plane, so position updates and normal/partials are
// unchanged (valid while the vertex stays on its face — true for large prism
// faces and the small caustic footprint).
inline ReprojectChainFn makeFlatReproject() {
    return [](int, const Vec3& s, const Vec3& t, float du, float dv, ChainVertex& v) {
        v.p = v.p + s * du + t * dv;
        return true;
    };
}

}  // namespace astroray::manifold
