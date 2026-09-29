// pkg296 (#833) — closed triangle boundary of a bounded medium: world-space
// triangle soup + its own BVH (kept out of the scene BVH). The medium covers a
// point at ray parameter t iff the closest crossing strictly after t is
// back-facing (Cycles volume_stack.h volume_stack_enter_exit: SR_BACKFACING =>
// exit; Apache-2.0). Research: .astroray_plan/docs/pkg296-mesh-volume-boundary-research.md.
//
// Assumes Vec3 (raytracer.h) is already defined; include after raytracer.h.

#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <vector>

namespace astroray {
namespace volume {

class MediumBoundary {
public:
    struct Crossing {
        bool hit = false;
        bool backFacing = false;
        float t = 0.0f;
    };

    // verts: 3*nv floats (world), idx: 3*nt vertex indices. Triangles with an
    // out-of-range index are dropped. Winding: counter-clockwise seen from
    // outside (Blender), i.e. the geometric normal points out of the medium.
    MediumBoundary(const float* verts, size_t nv, const int32_t* idx, size_t nt) {
        tris_.reserve(nt);
        for (size_t i = 0; i < nt; ++i) {
            Tri tr;
            bool ok = true;
            for (int k = 0; k < 3; ++k) {
                int32_t v = idx[3 * i + k];
                if (v < 0 || size_t(v) >= nv) { ok = false; break; }
                for (int a = 0; a < 3; ++a) tr.p[k][a] = verts[3 * size_t(v) + a];
            }
            if (ok) tris_.push_back(tr);
        }
        for (int a = 0; a < 3; ++a) { bmin_[a] = std::numeric_limits<float>::max(); bmax_[a] = -bmin_[a]; }
        for (const Tri& tr : tris_)
            for (int k = 0; k < 3; ++k)
                for (int a = 0; a < 3; ++a) {
                    bmin_[a] = std::min(bmin_[a], tr.p[k][a]);
                    bmax_[a] = std::max(bmax_[a], tr.p[k][a]);
                }
        build();
    }

    bool empty() const { return tris_.empty(); }
    size_t triangleCount() const { return tris_.size(); }
    const float* boundsMin() const { return bmin_; }
    const float* boundsMax() const { return bmax_; }

    // Closest crossing with tMin < t < tMax along (o, d) (d need not be unit;
    // t is in units of d). Watertight (Woop et al. 2013 via pbrt-v4).
    Crossing nextCrossing(const Vec3& o, const Vec3& d, float tMin, float tMax) const {
        Crossing best;
        if (nodes_.empty()) return best;
        const float od[3] = {o.x, o.y, o.z}, dd[3] = {d.x, d.y, d.z};
        float inv[3];
        for (int a = 0; a < 3; ++a) inv[a] = 1.0f / dd[a];  // +-inf for 0 is fine (slab test)
        float tFar = tMax;
        int stack[64];
        int sp = 0;
        stack[sp++] = 0;
        while (sp > 0) {
            const Node& n = nodes_[stack[--sp]];
            if (!slab(n, od, inv, tMin, tFar)) continue;
            if (n.count > 0) {
                for (int i = 0; i < n.count; ++i) {
                    const Tri& tr = tris_[n.first + i];
                    float t;
                    if (intersectTri(tr, od, dd, tMin, tFar, t)) {
                        tFar = t;
                        best.hit = true;
                        best.t = t;
                        best.backFacing = facingBack(tr, dd);
                    }
                }
            } else if (sp + 2 <= 64) {
                // Visit the nearer child first (pushed last).
                const int l = n.first, r = n.first + 1;
                const bool leftFirst = dd[n.axis] >= 0.0f;
                stack[sp++] = leftFirst ? r : l;
                stack[sp++] = leftFirst ? l : r;
            }
        }
        return best;
    }

private:
    struct Tri { float p[3][3]; };
    struct Node {
        float mn[3], mx[3];
        int first = 0;   // leaf: first triangle; interior: left child (right = first+1)
        int count = 0;   // > 0 => leaf
        int axis = 0;
    };

    // Back-facing: the ray travels along the geometric normal (dot(Ng, d) > 0),
    // Cycles SR_BACKFACING. Ng = (p1-p0) x (p2-p0).
    static bool facingBack(const Tri& tr, const float d[3]) {
        float e1[3], e2[3];
        for (int a = 0; a < 3; ++a) { e1[a] = tr.p[1][a] - tr.p[0][a]; e2[a] = tr.p[2][a] - tr.p[0][a]; }
        const float n0 = e1[1] * e2[2] - e1[2] * e2[1];
        const float n1 = e1[2] * e2[0] - e1[0] * e2[2];
        const float n2 = e1[0] * e2[1] - e1[1] * e2[0];
        return n0 * d[0] + n1 * d[1] + n2 * d[2] > 0.0f;
    }

    static bool slab(const Node& n, const float o[3], const float inv[3], float tMin, float tMax) {
        float t0 = tMin, t1 = tMax;
        for (int a = 0; a < 3; ++a) {
            float tn = (n.mn[a] - o[a]) * inv[a];
            float tf = (n.mx[a] - o[a]) * inv[a];
            if (tn > tf) std::swap(tn, tf);
            tf *= 1.0f + 2.0f * gamma(3);  // pbrt-v4 Bounds3::IntersectP robustness
            if (tn > t0) t0 = tn;          // NaN (0*inf) leaves t0/t1 unchanged
            if (tf < t1) t1 = tf;
            if (t0 > t1) return false;
        }
        return true;
    }

    static constexpr float gamma(int n) {
        constexpr float eps = std::numeric_limits<float>::epsilon() * 0.5f;
        return (n * eps) / (1.0f - n * eps);
    }

    // pbrt-v4 shapes.cpp IntersectTriangle (Woop, Benthin, Wald 2013, JCGT 2(1)),
    // Apache-2.0, with an added lower bound tMin (strict).
    static bool intersectTri(const Tri& tr, const float o[3], const float d[3], float tMin,
                             float tMax, float& tOut) {
        float p0t[3], p1t[3], p2t[3];
        for (int a = 0; a < 3; ++a) {
            p0t[a] = tr.p[0][a] - o[a];
            p1t[a] = tr.p[1][a] - o[a];
            p2t[a] = tr.p[2][a] - o[a];
        }
        const float ax = std::abs(d[0]), ay = std::abs(d[1]), az = std::abs(d[2]);
        const int kz = (ax > ay) ? (ax > az ? 0 : 2) : (ay > az ? 1 : 2);
        const int kx = (kz + 1) % 3, ky = (kx + 1) % 3;
        const float dx = d[kx], dy = d[ky], dz = d[kz];
        float a0[3] = {p0t[kx], p0t[ky], p0t[kz]};
        float a1[3] = {p1t[kx], p1t[ky], p1t[kz]};
        float a2[3] = {p2t[kx], p2t[ky], p2t[kz]};
        const float Sx = -dx / dz, Sy = -dy / dz, Sz = 1.0f / dz;
        a0[0] += Sx * a0[2]; a0[1] += Sy * a0[2];
        a1[0] += Sx * a1[2]; a1[1] += Sy * a1[2];
        a2[0] += Sx * a2[2]; a2[1] += Sy * a2[2];
        float e0 = a1[0] * a2[1] - a1[1] * a2[0];
        float e1 = a2[0] * a0[1] - a2[1] * a0[0];
        float e2 = a0[0] * a1[1] - a0[1] * a1[0];
        if (e0 == 0.0f || e1 == 0.0f || e2 == 0.0f) {
            e0 = float(double(a2[1]) * double(a1[0]) - double(a2[0]) * double(a1[1]));
            e1 = float(double(a0[1]) * double(a2[0]) - double(a0[0]) * double(a2[1]));
            e2 = float(double(a1[1]) * double(a0[0]) - double(a1[0]) * double(a0[1]));
        }
        if ((e0 < 0 || e1 < 0 || e2 < 0) && (e0 > 0 || e1 > 0 || e2 > 0)) return false;
        const float det = e0 + e1 + e2;
        if (det == 0.0f) return false;
        a0[2] *= Sz; a1[2] *= Sz; a2[2] *= Sz;
        const float tScaled = e0 * a0[2] + e1 * a1[2] + e2 * a2[2];
        if (det < 0 && (tScaled >= 0 || tScaled < tMax * det)) return false;
        if (det > 0 && (tScaled <= 0 || tScaled > tMax * det)) return false;
        const float invDet = 1.0f / det;
        const float t = tScaled * invDet;
        // Conservative t > 0 bound (pbrt-v4 deltaT).
        const float maxZt = std::max({std::abs(a0[2]), std::abs(a1[2]), std::abs(a2[2])});
        const float deltaZ = gamma(3) * maxZt;
        const float maxXt = std::max({std::abs(a0[0]), std::abs(a1[0]), std::abs(a2[0])});
        const float maxYt = std::max({std::abs(a0[1]), std::abs(a1[1]), std::abs(a2[1])});
        const float deltaX = gamma(5) * (maxXt + maxZt);
        const float deltaY = gamma(5) * (maxYt + maxZt);
        const float deltaE = 2.0f * (gamma(2) * maxXt * maxYt + deltaY * maxXt + deltaX * maxYt);
        const float maxE = std::max({std::abs(e0), std::abs(e1), std::abs(e2)});
        const float deltaT =
            3.0f * (gamma(3) * maxE * maxZt + deltaE * maxZt + deltaZ * maxE) * std::abs(invDet);
        if (t <= deltaT) return false;
        if (!(t > tMin) || !(t < tMax)) return false;
        tOut = t;
        return true;
    }

    // pbrt-v4 BVHAggregate "EqualCounts" split: median of the centroids on the
    // largest centroid-extent axis; leaves of <= 4 triangles.
    void build() {
        nodes_.clear();
        if (tris_.empty()) return;
        nodes_.reserve(2 * tris_.size());
        nodes_.push_back(Node{});
        buildRec(0, 0, int(tris_.size()));
    }
    void buildRec(int ni, int begin, int end) {
        Node n;
        for (int a = 0; a < 3; ++a) { n.mn[a] = std::numeric_limits<float>::max(); n.mx[a] = -n.mn[a]; }
        float cmn[3], cmx[3];
        for (int a = 0; a < 3; ++a) { cmn[a] = std::numeric_limits<float>::max(); cmx[a] = -cmn[a]; }
        for (int i = begin; i < end; ++i)
            for (int a = 0; a < 3; ++a) {
                float c = 0.0f;
                for (int k = 0; k < 3; ++k) {
                    n.mn[a] = std::min(n.mn[a], tris_[i].p[k][a]);
                    n.mx[a] = std::max(n.mx[a], tris_[i].p[k][a]);
                    c += tris_[i].p[k][a];
                }
                cmn[a] = std::min(cmn[a], c);
                cmx[a] = std::max(cmx[a], c);
            }
        const int count = end - begin;
        int axis = 0;
        for (int a = 1; a < 3; ++a)
            if (cmx[a] - cmn[a] > cmx[axis] - cmn[axis]) axis = a;
        if (count <= 4 || !(cmx[axis] > cmn[axis])) {
            n.first = begin;
            n.count = count;
            nodes_[ni] = n;
            return;
        }
        const int mid = begin + count / 2;
        auto cen = [axis](const Tri& t) { return t.p[0][axis] + t.p[1][axis] + t.p[2][axis]; };
        std::nth_element(tris_.begin() + begin, tris_.begin() + mid, tris_.begin() + end,
                         [&](const Tri& x, const Tri& y) { return cen(x) < cen(y); });
        n.axis = axis;
        n.count = 0;
        n.first = int(nodes_.size());
        nodes_[ni] = n;
        nodes_.push_back(Node{});
        nodes_.push_back(Node{});
        const int l = n.first;
        buildRec(l, begin, mid);
        buildRec(l + 1, mid, end);
    }

    std::vector<Tri> tris_;
    std::vector<Node> nodes_;
    float bmin_[3], bmax_[3];
};

}  // namespace volume
}  // namespace astroray
