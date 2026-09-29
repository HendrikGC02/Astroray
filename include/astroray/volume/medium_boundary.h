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
    // Every crossing with t > tMin along one ray, ascending (one traversal
    // instead of one closest-hit query per interval end). overflow => more than
    // kMax crossings: callers fall back to nextCrossing.
    struct Crossings {
        static constexpr int kMax = 16;
        int n;
        bool overflow;
        float t[kMax];
        bool back[kMax];
        // The first crossing strictly after `after` (same t values as
        // nextCrossing(o, d, after, inf) would return).
        Crossing next(float after) const {
            Crossing c;
            for (int i = 0; i < n; ++i)
                if (t[i] > after) { c.hit = true; c.t = t[i]; c.backFacing = back[i]; break; }
            return c;
        }
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
        const RayPre r(o, d);
        if (!slab(nodes_[0], r, tMin, tMax)) return best;
        float tFar = tMax;
        int stack[64];
        int sp = 0;
        stack[sp++] = 0;
        while (sp > 0) {
            const Node& n = nodes_[stack[--sp]];
            if (n.count > 0) {
                for (int i = 0; i < n.count; ++i) {
                    const Tri& tr = tris_[n.first + i];
                    float t;
                    if (intersectTri(tr, r, tMin, tFar, t)) {
                        tFar = t;
                        best.hit = true;
                        best.t = t;
                        best.backFacing = facingBack(tr, r.d);
                    }
                }
                continue;
            }
            // Test both children here; push the hit ones, nearer on top.
            const int l = n.first, rr = n.first + 1;
            const bool hl = slab(nodes_[l], r, tMin, tFar);
            const bool hr = slab(nodes_[rr], r, tMin, tFar);
            if (sp + 2 > 64) continue;
            if (r.d[n.axis] >= 0.0f) {
                if (hr) stack[sp++] = rr;
                if (hl) stack[sp++] = l;
            } else {
                if (hl) stack[sp++] = l;
                if (hr) stack[sp++] = rr;
            }
        }
        return best;
    }

    Crossings allCrossings(const Vec3& o, const Vec3& d, float tMin) const {
        Crossings out;
        out.n = 0;
        out.overflow = false;
        if (nodes_.empty()) return out;
        const RayPre r(o, d);
        constexpr float kFar = std::numeric_limits<float>::max();
        if (!slab(nodes_[0], r, tMin, kFar)) return out;
        int stack[64];
        int sp = 0;
        stack[sp++] = 0;
        while (sp > 0) {
            const Node& n = nodes_[stack[--sp]];
            if (n.count > 0) {
                for (int i = 0; i < n.count; ++i) {
                    const Tri& tr = tris_[n.first + i];
                    float t;
                    if (!intersectTri(tr, r, tMin, kFar, t)) continue;
                    if (out.n == Crossings::kMax) { out.overflow = true; return out; }
                    // insertion into the ascending list
                    int j = out.n++;
                    while (j > 0 && out.t[j - 1] > t) {
                        out.t[j] = out.t[j - 1];
                        out.back[j] = out.back[j - 1];
                        --j;
                    }
                    out.t[j] = t;
                    out.back[j] = facingBack(tr, r.d);
                }
                continue;
            }
            if (sp + 2 > 64) continue;
            if (slab(nodes_[n.first + 1], r, tMin, kFar)) stack[sp++] = n.first + 1;
            if (slab(nodes_[n.first], r, tMin, kFar)) stack[sp++] = n.first;
        }
        return out;
    }

private:
    struct Tri { float p[3][3]; };
    struct Node {  // 32 B
        float mn[3], mx[3];
        int first = 0;        // leaf: first triangle; interior: left child (right = first+1)
        int16_t count = 0;    // > 0 => leaf
        int16_t axis = 0;
    };
    // Per-ray constants: slab reciprocals and the Woop 2013 permutation/shear
    // (computed once per ray instead of per triangle; same arithmetic as pbrt-v4).
    struct RayPre {
        float o[3], d[3], inv[3];
        int kx, ky, kz;
        float Sx, Sy, Sz;
        RayPre(const Vec3& ov, const Vec3& dv) {
            o[0] = ov.x; o[1] = ov.y; o[2] = ov.z;
            d[0] = dv.x; d[1] = dv.y; d[2] = dv.z;
            for (int a = 0; a < 3; ++a) inv[a] = 1.0f / d[a];  // +-inf for 0 is fine
            const float ax = std::abs(d[0]), ay = std::abs(d[1]), az = std::abs(d[2]);
            kz = (ax > ay) ? (ax > az ? 0 : 2) : (ay > az ? 1 : 2);
            kx = (kz + 1) % 3;
            ky = (kx + 1) % 3;
            Sx = -d[kx] / d[kz];
            Sy = -d[ky] / d[kz];
            Sz = 1.0f / d[kz];
        }
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

    static bool slab(const Node& n, const RayPre& r, float tMin, float tMax) {
        // Branchless (min/max) form of pbrt-v4 Bounds3::IntersectP. A NaN slab
        // bound (0*inf: origin on a slab plane, d parallel) leaves t0/t1
        // unchanged: std::max(t0, NaN) == t0, std::min(t1, NaN) == t1.
        const float kRobust = 1.0f + 2.0f * gamma(3);
        float t0 = tMin, t1 = tMax;
        for (int a = 0; a < 3; ++a) {
            const float ta = (n.mn[a] - r.o[a]) * r.inv[a];
            const float tb = (n.mx[a] - r.o[a]) * r.inv[a];
            t0 = std::max(t0, std::min(ta, tb));
            t1 = std::min(t1, std::max(ta, tb) * kRobust);
        }
        return t0 <= t1;
    }

    static constexpr float gamma(int n) {
        constexpr float eps = std::numeric_limits<float>::epsilon() * 0.5f;
        return (n * eps) / (1.0f - n * eps);
    }

    // pbrt-v4 shapes.cpp IntersectTriangle (Woop, Benthin, Wald 2013, JCGT 2(1)),
    // Apache-2.0, with an added lower bound tMin (strict).
    static bool intersectTri(const Tri& tr, const RayPre& r, float tMin, float tMax,
                             float& tOut) {
        const int kx = r.kx, ky = r.ky, kz = r.kz;
        float a0[3] = {tr.p[0][kx] - r.o[kx], tr.p[0][ky] - r.o[ky], tr.p[0][kz] - r.o[kz]};
        float a1[3] = {tr.p[1][kx] - r.o[kx], tr.p[1][ky] - r.o[ky], tr.p[1][kz] - r.o[kz]};
        float a2[3] = {tr.p[2][kx] - r.o[kx], tr.p[2][ky] - r.o[ky], tr.p[2][kz] - r.o[kz]};
        a0[0] += r.Sx * a0[2]; a0[1] += r.Sy * a0[2];
        a1[0] += r.Sx * a1[2]; a1[1] += r.Sy * a1[2];
        a2[0] += r.Sx * a2[2]; a2[1] += r.Sy * a2[2];
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
        a0[2] *= r.Sz; a1[2] *= r.Sz; a2[2] *= r.Sz;
        const float tScaled = e0 * a0[2] + e1 * a1[2] + e2 * a2[2];
        if (det < 0 && (tScaled >= 0 || tScaled < tMax * det)) return false;
        if (det > 0 && (tScaled <= 0 || tScaled > tMax * det)) return false;
        const float invDet = 1.0f / det;
        const float t = tScaled * invDet;
        if (!(t > tMin) || !(t < tMax)) return false;
        // Conservative t > 0 bound (pbrt-v4 deltaT).
        const float maxZt = std::max(std::abs(a0[2]), std::max(std::abs(a1[2]), std::abs(a2[2])));
        const float deltaZ = gamma(3) * maxZt;
        const float maxXt = std::max(std::abs(a0[0]), std::max(std::abs(a1[0]), std::abs(a2[0])));
        const float maxYt = std::max(std::abs(a0[1]), std::max(std::abs(a1[1]), std::abs(a2[1])));
        const float deltaX = gamma(5) * (maxXt + maxZt);
        const float deltaY = gamma(5) * (maxYt + maxZt);
        const float deltaE = 2.0f * (gamma(2) * maxXt * maxYt + deltaY * maxXt + deltaX * maxYt);
        const float maxE = std::max(std::abs(e0), std::max(std::abs(e1), std::abs(e2)));
        const float deltaT =
            3.0f * (gamma(3) * maxE * maxZt + deltaE * maxZt + deltaZ * maxE) * std::abs(invDet);
        if (t <= deltaT) return false;
        tOut = t;
        return true;
    }

    // pbrt-v4 BVHAggregate::buildRecursive (Apache-2.0): binned SAH split
    // (12 buckets on the largest centroid-extent axis, cost 1/2 per traversal
    // step relative to a triangle test), equal-counts split for <= 2
    // triangles; leaves of <= 4 triangles when no split is cheaper.
    void build() {
        nodes_.clear();
        if (tris_.empty()) return;
        nodes_.reserve(2 * tris_.size());
        nodes_.push_back(Node{});
        buildRec(0, 0, int(tris_.size()));
    }
    static float area(const float mn[3], const float mx[3]) {
        const float dx = mx[0] - mn[0], dy = mx[1] - mn[1], dz = mx[2] - mn[2];
        return (dx < 0.0f) ? 0.0f : 2.0f * (dx * dy + dy * dz + dz * dx);
    }
    static void grow(float mn[3], float mx[3], const Tri& t) {
        for (int k = 0; k < 3; ++k)
            for (int a = 0; a < 3; ++a) {
                mn[a] = std::min(mn[a], t.p[k][a]);
                mx[a] = std::max(mx[a], t.p[k][a]);
            }
    }
    static void emptyBox(float mn[3], float mx[3]) {
        for (int a = 0; a < 3; ++a) { mn[a] = std::numeric_limits<float>::max(); mx[a] = -mn[a]; }
    }
    void buildRec(int ni, int begin, int end) {
        Node n;
        emptyBox(n.mn, n.mx);
        float cmn[3], cmx[3];
        emptyBox(cmn, cmx);
        for (int i = begin; i < end; ++i) {
            grow(n.mn, n.mx, tris_[i]);
            for (int a = 0; a < 3; ++a) {
                const float c = tris_[i].p[0][a] + tris_[i].p[1][a] + tris_[i].p[2][a];
                cmn[a] = std::min(cmn[a], c);
                cmx[a] = std::max(cmx[a], c);
            }
        }
        const int count = end - begin;
        int axis = 0;
        for (int a = 1; a < 3; ++a)
            if (cmx[a] - cmn[a] > cmx[axis] - cmn[axis]) axis = a;
        auto makeLeaf = [&]() {
            n.first = begin;
            n.count = int16_t(count);
            nodes_[ni] = n;
        };
        if (count == 1 || !(cmx[axis] > cmn[axis])) { makeLeaf(); return; }
        auto cen = [axis](const Tri& t) { return t.p[0][axis] + t.p[1][axis] + t.p[2][axis]; };
        int mid;
        if (count <= 2) {
            mid = begin + count / 2;
            std::nth_element(tris_.begin() + begin, tris_.begin() + mid, tris_.begin() + end,
                             [&](const Tri& x, const Tri& y) { return cen(x) < cen(y); });
        } else {
            constexpr int kB = 12;
            int bc[kB] = {};
            float bmn[kB][3], bmx[kB][3];
            for (int b = 0; b < kB; ++b) emptyBox(bmn[b], bmx[b]);
            const float scale = kB / (cmx[axis] - cmn[axis]);
            auto bucketOf = [&](const Tri& t) {
                return std::min(kB - 1, int((cen(t) - cmn[axis]) * scale));
            };
            for (int i = begin; i < end; ++i) {
                const int b = bucketOf(tris_[i]);
                ++bc[b];
                grow(bmn[b], bmx[b], tris_[i]);
            }
            // cost[s] of splitting after bucket s (pbrt-v4 forward/backward sweep).
            float cost[kB - 1];
            {
                float mn[3], mx[3];
                emptyBox(mn, mx);
                int c = 0;
                for (int b = 0; b < kB - 1; ++b) {
                    for (int a = 0; a < 3; ++a) { mn[a] = std::min(mn[a], bmn[b][a]); mx[a] = std::max(mx[a], bmx[b][a]); }
                    c += bc[b];
                    cost[b] = c * area(mn, mx);
                }
                emptyBox(mn, mx);
                c = 0;
                for (int b = kB - 1; b >= 1; --b) {
                    for (int a = 0; a < 3; ++a) { mn[a] = std::min(mn[a], bmn[b][a]); mx[a] = std::max(mx[a], bmx[b][a]); }
                    c += bc[b];
                    cost[b - 1] += c * area(mn, mx);
                }
            }
            int best = 0;
            for (int b = 1; b < kB - 1; ++b)
                if (cost[b] < cost[best]) best = b;
            const float leafCost = float(count);
            const float splitCost = 0.5f + cost[best] / std::max(area(n.mn, n.mx), 1e-30f);
            if (count <= 4 && leafCost <= splitCost) { makeLeaf(); return; }
            auto it = std::partition(tris_.begin() + begin, tris_.begin() + end,
                                     [&](const Tri& t) { return bucketOf(t) <= best; });
            mid = int(it - tris_.begin());
            if (mid == begin || mid == end) {  // degenerate bucketing: equal counts
                mid = begin + count / 2;
                std::nth_element(tris_.begin() + begin, tris_.begin() + mid, tris_.begin() + end,
                                 [&](const Tri& x, const Tri& y) { return cen(x) < cen(y); });
            }
        }
        n.axis = int16_t(axis);
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
