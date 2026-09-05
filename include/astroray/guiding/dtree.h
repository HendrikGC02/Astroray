// dtree.h — directional quadtree for SD-tree path guiding (pkg136 Stage 1A).
//
// The lower half of the Müller/Gross/Novák 2017 SD-tree: an adaptive quadtree
// over the 2D equal-area cylindrical parameterisation of the *world-space*
// direction sphere, storing an approximation of the incident-radiance field
// L_i(x, .) at one spatial leaf. Directions are learned by splatting radiance
// estimates during rendering (learn-then-sample); continuation directions are
// then importance-sampled from the tree, MIS-combined with the BSDF.
//
// Clean-room port of Müller 2017 (DOI 10.1111/cgf.13227) + the 2019 SIGGRAPH
// course improvements (DOI 10.1145/3305366.3328091), using OpenPGL (Apache-2.0)
// only as a structural reference — no GPL PPG code lifted (CLAUDE.md §6). The
// algorithm and its variance-reduction win (~110x on a hard-transport integrand,
// unbiased under guide/BSDF MIS) were de-risked in numpy before this port; see
// .astroray_plan/docs/pkg136-stage1-derisking.md and the acceptance test
// tests/test_pkg136_dtree_unit.py, which drives these exact primitives.
//
// Host-only (CPU Stage 1). The GPU leg (Stage 2) mirrors the warp into a
// __constant__-bound CDF side table; this header carries no device concerns.
//
// License: Apache-2.0

#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

namespace astroray {
namespace guiding {

// ---------------------------------------------------------------------------
// Equal-area cylindrical direction map (the paper's parameterisation).
//
//   x = (cosθ + 1) / 2            with cosθ = ω_z,    x ∈ [0, 1]
//   y = (φ + π) / (2π)            with φ = atan2(ω_y, ω_x), y ∈ [0, 1]
//
// The map is area-preserving up to the constant solid-angle jacobian
//   dω = sinθ dθ dφ = (2 dx)(2π dy) = 4π · dx · dy,
// so a density p_square over the unit square corresponds to a solid-angle
// density p_ω = p_square / (4π). Uniform on the square ⇔ uniform on the sphere.
// Directions are in a fixed WORLD frame (L_i is a world-space field), never the
// shading frame — the exact same map must be reused on the GPU (Stage 2) or the
// parity gate diverges silently ([[wavefront-snapshot-semantics-class-of-bug]]).
// ---------------------------------------------------------------------------

constexpr float kGuidingPi = 3.14159265358979323846f;
constexpr float kGuidingTwoPi = 2.0f * kGuidingPi;
// dω = 4π dx dy → solid-angle pdf = square pdf / (4π).
constexpr float kGuidingSphereJacobian = 4.0f * kGuidingPi;

// World unit direction (wx,wy,wz) → unit-square point (x,y).
inline void dirToSquare(float wx, float wy, float wz, float& x, float& y) {
    float cosTheta = std::min(1.0f, std::max(-1.0f, wz));
    x = (cosTheta + 1.0f) * 0.5f;
    float phi = std::atan2(wy, wx);          // [-π, π]
    y = (phi + kGuidingPi) / kGuidingTwoPi;  // [0, 1]
    // Guard the poles / wraparound onto the half-open unit square.
    x = std::min(0.9999999f, std::max(0.0f, x));
    y = std::min(0.9999999f, std::max(0.0f, y));
}

// Unit-square point (x,y) → world unit direction (wx,wy,wz).
inline void squareToDir(float x, float y, float& wx, float& wy, float& wz) {
    float cosTheta = std::min(1.0f, std::max(-1.0f, 2.0f * x - 1.0f));
    float sinTheta = std::sqrt(std::max(0.0f, 1.0f - cosTheta * cosTheta));
    float phi = y * kGuidingTwoPi - kGuidingPi;
    wx = sinTheta * std::cos(phi);
    wy = sinTheta * std::sin(phi);
    wz = cosTheta;
}

// ---------------------------------------------------------------------------
// DTree — adaptive quadtree over the unit square.
//
// A node is either a leaf or an interior node with exactly four children
// (quadrants child = 2*qy + qx, qx/qy ∈ {0,1}). Each node stores the total flux
// splatted into its subtree; sampling descends proportional to child flux, and
// the pdf telescopes so that ∫ pdf = 1 over the square regardless of topology.
// ---------------------------------------------------------------------------
class DTree {
public:
    static constexpr int kMaxDepth = 20;  // 4^-20 leaf — far finer than needed

    DTree() { nodes_.push_back(Node{}); }  // single root leaf

    // Splat flux `v` at square point (x,y): add to every node on the descent
    // path so each node's flux stays equal to its subtree sum.
    void splat(float x, float y, float v) {
        if (!(v > 0.0f)) return;
        int idx = 0;
        nodes_[idx].flux += v;
        while (nodes_[idx].child[0] >= 0) {
            int qx = x < 0.5f ? 0 : 1;
            int qy = y < 0.5f ? 0 : 1;
            x = x * 2.0f - float(qx);
            y = y * 2.0f - float(qy);
            idx = nodes_[idx].child[qy * 2 + qx];
            nodes_[idx].flux += v;
        }
    }

    // Subdivide, by ONE level, every leaf holding more than fraction `rho` of
    // total flux (below kMaxDepth). Children seed their flux as an even split of
    // the parent's — irrelevant once reset()+re-splat runs, but keeps a refined
    // tree self-consistent if sampled before the next iteration. Call between
    // training iterations, using the just-finished iteration's flux, BEFORE
    // reset() (refine-before-final-splat — de-risk finding 2).
    void refine(float rho) {
        float total = nodes_[0].flux;
        if (!(total > 0.0f)) return;
        // Snapshot current leaf indices; the vector grows as we split.
        std::vector<int> leaves;
        for (int i = 0; i < (int)nodes_.size(); ++i)
            if (nodes_[i].child[0] < 0) leaves.push_back(i);
        for (int leaf : leaves) {
            if (nodes_[leaf].depth >= kMaxDepth) continue;
            if (nodes_[leaf].flux <= rho * total) continue;
            float childFlux = nodes_[leaf].flux * 0.25f;
            int childDepth = nodes_[leaf].depth + 1;
            for (int c = 0; c < 4; ++c) {
                Node n{};
                n.flux = childFlux;
                n.depth = childDepth;
                nodes_[leaf].child[c] = (int)nodes_.size();
                nodes_.push_back(n);
            }
        }
    }

    // Zero the flux of every node, keeping topology (the refined structure is
    // re-splatted with the next iteration's samples).
    void reset() {
        for (Node& n : nodes_) n.flux = 0.0f;
    }

    // Hierarchical-warp sample. `u1` drives the flux-proportional descent (it is
    // rescaled at every level and reused for the leaf's x coordinate); `u2` is
    // the leaf's y coordinate. Returns the square point (x,y) and the square-
    // measure pdf. A tree with no flux warps nothing (returns pdf 0); the caller
    // falls back to the BSDF (the MIS support floor keeps the estimator valid).
    void sample(float u1, float u2, float& x, float& y, float& pdf) const {
        int idx = 0;
        float x0 = 0.0f, y0 = 0.0f, size = 1.0f;
        pdf = 1.0f;  // root leaf ⇒ uniform on the square, pdf 1 (full support)
        while (nodes_[idx].child[0] >= 0) {
            float f[4];
            float total = 0.0f;
            for (int c = 0; c < 4; ++c) {
                f[c] = nodes_[nodes_[idx].child[c]].flux;
                total += f[c];
            }
            // Zero-flux subtree ⇒ uniform among the four children (equal weight),
            // so an untrained region samples uniformly with a pdf consistent with
            // pdf() below — the MIS support floor that keeps the estimator unbiased.
            if (!(total > 0.0f)) { f[0] = f[1] = f[2] = f[3] = 1.0f; total = 4.0f; }
            // Proper 2D hierarchical warp: u2 selects the row (y-quadrant) by its
            // marginal, then u1 selects the column (x-quadrant) within that row,
            // each rescaled to [0,1). Using one number for a flattened 4-way pick
            // does NOT reproduce pdf() (the sample/pdf inconsistency that made the
            // guide's MIS weight wrong). child index = 2*qy + qx.
            float bottom = f[0] + f[1];  // qy = 0 row
            int qy;
            if (u2 * total < bottom && bottom > 0.0f) {
                qy = 0;
                u2 = std::min(0.9999999f, u2 * total / bottom);
            } else {
                qy = 1;
                float top = total - bottom;
                u2 = std::min(0.9999999f, (u2 * total - bottom) / (top > 0.0f ? top : 1.0f));
            }
            float left = f[2 * qy + 0], right = f[2 * qy + 1];
            float row = left + right;
            int qx;
            if (u1 * row < left && left > 0.0f) {
                qx = 0;
                u1 = std::min(0.9999999f, u1 * row / left);
            } else {
                qx = 1;
                u1 = std::min(0.9999999f, (u1 * row - left) / (right > 0.0f ? right : 1.0f));
            }
            int c = 2 * qy + qx;
            pdf *= (f[c] / total) * 4.0f;
            size *= 0.5f;
            x0 += float(qx) * size;
            y0 += float(qy) * size;
            idx = nodes_[idx].child[c];
        }
        // Uniform within the reached leaf (u1, u2 are now independent uniforms).
        x = x0 + u1 * size;
        y = y0 + u2 * size;
    }

    // Square-measure pdf of the point (x,y): the density this tree would sample
    // it with. Descends to the leaf containing (x,y), telescoping Π(f_c/f · 4).
    float pdf(float x, float y) const {
        int idx = 0;
        float p = 1.0f;  // root leaf ⇒ uniform, pdf 1 (consistent with sample())
        while (nodes_[idx].child[0] >= 0) {
            float f[4];
            float total = 0.0f;
            for (int c = 0; c < 4; ++c) {
                f[c] = nodes_[nodes_[idx].child[c]].flux;
                total += f[c];
            }
            // Zero-flux subtree ⇒ uniform (matches sample()'s fallback).
            if (!(total > 0.0f)) { f[0] = f[1] = f[2] = f[3] = 1.0f; total = 4.0f; }
            int qx = x < 0.5f ? 0 : 1;
            int qy = y < 0.5f ? 0 : 1;
            x = x * 2.0f - float(qx);
            y = y * 2.0f - float(qy);
            int c = qy * 2 + qx;
            p *= (f[c] / total) * 4.0f;
            idx = nodes_[idx].child[c];
        }
        return p;
    }

    // Solid-angle pdf of a world direction (folds in the 1/4π jacobian).
    float pdfDir(float wx, float wy, float wz) const {
        float x, y;
        dirToSquare(wx, wy, wz, x, y);
        return pdf(x, y) / kGuidingSphereJacobian;
    }

    float totalFlux() const { return nodes_[0].flux; }
    int numNodes() const { return (int)nodes_.size(); }
    int numLeaves() const {
        int count = 0;
        for (const Node& node : nodes_)
            if (node.child[0] < 0) ++count;
        return count;
    }

private:
    struct Node {
        float flux = 0.0f;
        int depth = 0;
        int child[4] = {-1, -1, -1, -1};  // <0 ⇒ leaf
    };
    std::vector<Node> nodes_;
};

}  // namespace guiding
}  // namespace astroray
