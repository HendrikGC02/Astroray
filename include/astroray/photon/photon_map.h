#pragma once
// pkg109 — world-space photon map: balanced kd-tree + k-NN density estimate.
//
// Replaces the prism-specific flat 2D (x,z) grid in light_tracer_caustic.cpp with
// a general world-space photon store so caustics can later (pkg110/111) be
// deposited from ANY glass shape and gathered on ANY receiver. This file is
// storage-only: build a balanced kd-tree over photons, locate the k nearest at a
// query point, and form the Jensen irradiance density estimate.
//
// Citations (CLAUDE.md §6; see .astroray_plan/docs/pkg109-110-111-photon-map-research.md):
//   Jensen, "Global Illumination using Photon Maps", EGWR 1996 (DOI
//     10.1007/978-3-7091-7484-5_3) — the photon map.
//   Jensen, "A Practical Guide to Global Illumination using Photon Maps",
//     SIGGRAPH 2000 Course 8 — the implementable reference:
//       §2.2 Fig. 7  balance()        -> PhotonMap::balance (median split on the
//                                         largest-extent axis; O(N log N)).
//       §3.4 Fig. 10 locate_photons() -> PhotonMap::locate (bounded max-heap k-NN,
//                                         signed plane-distance pruning, squared d).
//       §3.1 Eq. 8  L_r = (1/(pi r^2)) sum f_r dPhi_p -> estimateIrradiance().
//   Disk-area density factor 1/(pi r^2): pbrt-v4 (Apache-2.0)
//     src/pbrt/cpu/integrators.cpp:3229 (L = tau/(np * Pi * r^2)); we mirror the
//     non-progressive single-pass simplification (fixed radius, no atomics).
//
// MinGW note (memory/mingw_large_struct_byval): Photon is 40 bytes (> 32) so it is
// always passed by const reference; never by value in the hot query path.

#include "../../raytracer.h"   // Vec3
#include "../spectrum.h"       // astroray::XYZ

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <utility>
#include <vector>

namespace astroray {
namespace photon {

struct Photon {
    Vec3 position;             // world-space deposit point (diffuse surface)
    Vec3 incidentDir;          // unit dir the photon arrived along (for pkg110/111 BSDF eval)
    astroray::XYZ power;       // CIE-weighted flux carried by this photon
    float lambda = 0.0f;       // sampled wavelength (nm) — diagnostics / pkg110
};

class PhotonMap {
public:
    PhotonMap() = default;

    // Build a balanced kd-tree over the photons (reordered in place). O(N log N).
    // Jensen 2000 §2.2 Fig. 7: split on the axis of largest extent, at the median.
    void build(std::vector<Photon> photons) {
        photons_ = std::move(photons);
        axis_.assign(photons_.size(), -1);
        if (!photons_.empty())
            balance(0, static_cast<int>(photons_.size()) - 1);
    }

    bool empty() const { return photons_.empty(); }
    std::size_t size() const { return photons_.size(); }
    const Photon& photon(int i) const { return photons_[i]; }

    // k-NN locate (Jensen 2000 §3.4 Fig. 10). Fills outIdx/outD2 (indices into the
    // internal reordered array + squared distances), sorted ascending by distance.
    // Returns the count found within maxRadius (<= k). Photons beyond maxRadius are
    // ignored, so a query in an empty region returns 0.
    int knn(const Vec3& q, int k, float maxRadius,
            std::vector<int>& outIdx, std::vector<float>& outD2) const {
        outIdx.clear();
        outD2.clear();
        if (photons_.empty() || k <= 0) return 0;
        std::vector<std::pair<float, int>> heap;  // max-heap by d2; front() = farthest kept
        heap.reserve(static_cast<std::size_t>(k));
        const float maxR2 = maxRadius * maxRadius;
        locate(0, static_cast<int>(photons_.size()) - 1, q, k, maxR2, heap);
        std::sort(heap.begin(), heap.end());
        for (const auto& e : heap) { outIdx.push_back(e.second); outD2.push_back(e.first); }
        return static_cast<int>(heap.size());
    }

    // Jensen 2000 §3.1 Eq. 8 irradiance estimate with the §3.2.1 cone filter:
    //   E = [ sum_p Phi_p * (1 - d_p/(kf*r)) ] / [ (1 - 2/(3*kf)) * pi r^2 ]
    // r = distance to the farthest of the k nearest photons within maxRadius; the
    // cone weight down-weights far photons to reduce edge blur (a far photon in a
    // dispersive band is a different wavelength, so this also sharpens the colour).
    // kf >= 1 is the filter constant. Returns zero if no photon is within maxRadius.
    // The receiver's Lambertian BRDF (albedo/pi) is applied by the caller (matches
    // the prior grid semantics, where the caller did `Lo += albedo * E`).
    astroray::XYZ estimateIrradiance(const Vec3& q, int k, float maxRadius,
                                     float kf = 1.1f) const {
        if (photons_.empty() || k <= 0) return {};
        std::vector<std::pair<float, int>> heap;
        heap.reserve(static_cast<std::size_t>(k));
        const float maxR2 = maxRadius * maxRadius;
        locate(0, static_cast<int>(photons_.size()) - 1, q, k, maxR2, heap);
        if (heap.empty()) return {};
        const float r2 = heap.front().first;  // max-heap: front() is the farthest kept
        if (r2 <= 0.0f) return {};
        const float r = std::sqrt(r2);
        astroray::XYZ sum;
        for (const auto& e : heap) {
            const float w = 1.0f - std::sqrt(e.first) / (kf * r);  // cone weight, >= 0
            const Photon& p = photons_[e.second];
            sum.X += p.power.X * w; sum.Y += p.power.Y * w; sum.Z += p.power.Z * w;
        }
        const float norm = (1.0f - 2.0f / (3.0f * kf)) * 3.14159265358979323846f * r2;
        if (norm <= 0.0f) return {};
        return { sum.X / norm, sum.Y / norm, sum.Z / norm };
    }

private:
    std::vector<Photon> photons_;
    std::vector<int> axis_;  // split axis (0/1/2) at the node whose subtree root is index i

    static float comp(const Vec3& v, int axis) {
        return axis == 0 ? v.x : (axis == 1 ? v.y : v.z);
    }
    static float dist2(const Vec3& a, const Vec3& b) {
        const float dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
        return dx * dx + dy * dy + dz * dz;
    }

    // Implicit subtree ranges: the node at [lo,hi] has root index mid=(lo+hi)/2,
    // left child range [lo,mid-1], right child range [mid+1,hi]. The query recursion
    // recomputes mid identically, so no child pointers are stored.
    void balance(int lo, int hi) {
        if (lo > hi) return;
        Vec3 mn = photons_[lo].position, mx = photons_[lo].position;
        for (int i = lo + 1; i <= hi; ++i) {
            const Vec3& p = photons_[i].position;
            mn = Vec3(std::min(mn.x, p.x), std::min(mn.y, p.y), std::min(mn.z, p.z));
            mx = Vec3(std::max(mx.x, p.x), std::max(mx.y, p.y), std::max(mx.z, p.z));
        }
        const float ex = mx.x - mn.x, ey = mx.y - mn.y, ez = mx.z - mn.z;
        const int axis = (ex >= ey && ex >= ez) ? 0 : (ey >= ez ? 1 : 2);
        const int mid = (lo + hi) / 2;
        std::nth_element(
            photons_.begin() + lo, photons_.begin() + mid, photons_.begin() + hi + 1,
            [axis](const Photon& a, const Photon& b) {
                return comp(a.position, axis) < comp(b.position, axis);
            });
        axis_[mid] = axis;
        balance(lo, mid - 1);
        balance(mid + 1, hi);
    }

    void locate(int lo, int hi, const Vec3& q, int k, float maxR2,
                std::vector<std::pair<float, int>>& heap) const {
        if (lo > hi) return;
        const int mid = (lo + hi) / 2;
        const int axis = axis_[mid];

        const float d2 = dist2(photons_[mid].position, q);
        // bound = current search radius^2: maxR2 until the heap is full, then the
        // farthest kept photon (heap root). This both enforces the maxRadius cap and
        // tightens the search as closer photons are found.
        float bound = (static_cast<int>(heap.size()) < k) ? maxR2 : heap.front().first;
        if (d2 < bound) {
            if (static_cast<int>(heap.size()) < k) {
                heap.emplace_back(d2, mid);
                std::push_heap(heap.begin(), heap.end());
            } else {
                std::pop_heap(heap.begin(), heap.end());
                heap.back() = {d2, mid};
                std::push_heap(heap.begin(), heap.end());
            }
        }

        const float delta = comp(q, axis) - comp(photons_[mid].position, axis);
        int nlo, nhi, flo, fhi;
        if (delta < 0.0f) { nlo = lo;      nhi = mid - 1; flo = mid + 1; fhi = hi; }
        else              { nlo = mid + 1; nhi = hi;      flo = lo;      fhi = mid - 1; }
        locate(nlo, nhi, q, k, maxR2, heap);
        const float bound2 = (static_cast<int>(heap.size()) < k) ? maxR2 : heap.front().first;
        if (delta * delta < bound2)
            locate(flo, fhi, q, k, maxR2, heap);
    }
};

}  // namespace photon
}  // namespace astroray
