// sdtree.h — spatial binary tree for SD-tree path guiding (pkg136 Stage 1A).
//
// The upper half of the Müller/Gross/Novák 2017 SD-tree: a binary tree over the
// 3D scene AABB whose leaves each own a directional DTree (dtree.h). It caches a
// spatially-varying approximation of the incident-radiance field: shade points
// in different regions of the scene draw from different learned directional
// distributions. Between training iterations a leaf is split (round-robin axis,
// spatial midpoint) once it has received more than a threshold number of samples;
// both children inherit a COPY of the parent's directional tree so learned
// information is not thrown away (Müller 2017 §5.2).
//
// Clean-room port of Müller 2017 (DOI 10.1111/cgf.13227); OpenPGL (Apache-2.0)
// structural reference only, no GPL PPG code lifted (CLAUDE.md §6). Host-only
// (CPU Stage 1). Unit test: tests/test_pkg136_sdtree_unit.py.
//
// License: Apache-2.0

#pragma once

#include <algorithm>
#include <cstdint>
#include <vector>

#include "astroray/guiding/dtree.h"

namespace astroray {
namespace guiding {

class SDTree {
public:
    static constexpr int kMaxDepth = 24;

    // Construct over the scene AABB [minb, maxb] (three floats each): a single
    // leaf owning one empty DTree covering the whole domain.
    SDTree(const float minb[3], const float maxb[3]) {
        dtrees_.emplace_back();
        SNode root{};
        for (int i = 0; i < 3; ++i) { root.minb[i] = minb[i]; root.maxb[i] = maxb[i]; }
        root.dtree = 0;
        root.depth = 0;
        nodes_.push_back(root);
    }

    // Index of the leaf whose AABB contains p (descends the binary tree).
    int leafIndex(const float p[3]) const {
        int idx = 0;
        while (nodes_[idx].axis >= 0) {
            int a = nodes_[idx].axis;
            idx = (p[a] < nodes_[idx].split) ? nodes_[idx].child0 : nodes_[idx].child1;
        }
        return idx;
    }

    // Record a radiance sample: splat `value` into the containing leaf's DTree at
    // the world direction (wx,wy,wz), and count the sample toward that leaf's
    // spatial-split budget. `value` is the radiance estimate Li/pdf (de-risk
    // finding 3 — splat radiance, not f·Li).
    void record(const float p[3], float wx, float wy, float wz, float value) {
        int leaf = leafIndex(p);
        float x, y;
        dirToSquare(wx, wy, wz, x, y);
        dtrees_[nodes_[leaf].dtree].splat(x, y, value);
        ++nodes_[leaf].sampleCount;
    }

    // Importance-sample a world direction from the leaf containing p.
    // Returns the direction (wx,wy,wz) and its solid-angle pdf (0 ⇒ empty guide).
    void sampleDir(const float p[3], float u1, float u2,
                   float& wx, float& wy, float& wz, float& pdfSa) const {
        int leaf = leafIndex(p);
        float x, y, pdfSq;
        dtrees_[nodes_[leaf].dtree].sample(u1, u2, x, y, pdfSq);
        squareToDir(x, y, wx, wy, wz);
        pdfSa = pdfSq / kGuidingSphereJacobian;
    }

    // Solid-angle pdf the leaf containing p would sample direction (wx,wy,wz) with.
    float pdfDir(const float p[3], float wx, float wy, float wz) const {
        return dtrees_[nodes_[leafIndex(p)].dtree].pdfDir(wx, wy, wz);
    }

    // Between-iteration refine (call using the finished iteration's stats, then
    // snapshot for the guide, then resetIteration before the next render pass):
    //   1. spatial: split every leaf with sampleCount > `spatialThreshold`
    //      (round-robin axis by depth, spatial midpoint); children inherit a copy
    //      of the parent DTree.
    //   2. directional: refine each leaf's DTree (subdivide directions holding
    //      > `dirRho` of that leaf's flux).
    void refine(uint32_t spatialThreshold, float dirRho) {
        // (1) spatial split — snapshot current leaf indices; the vectors grow.
        std::vector<int> leaves;
        for (int i = 0; i < (int)nodes_.size(); ++i)
            if (nodes_[i].axis < 0) leaves.push_back(i);
        for (int leaf : leaves) {
            if (nodes_[leaf].depth >= kMaxDepth) continue;
            if (nodes_[leaf].sampleCount <= spatialThreshold) continue;
            int a = nodes_[leaf].depth % 3;  // round-robin split axis
            float mid = 0.5f * (nodes_[leaf].minb[a] + nodes_[leaf].maxb[a]);
            int parentDTree = nodes_[leaf].dtree;

            SNode c0{}, c1{};
            for (int i = 0; i < 3; ++i) {
                c0.minb[i] = c1.minb[i] = nodes_[leaf].minb[i];
                c0.maxb[i] = c1.maxb[i] = nodes_[leaf].maxb[i];
            }
            c0.maxb[a] = mid;
            c1.minb[a] = mid;
            c0.depth = c1.depth = nodes_[leaf].depth + 1;
            // Both children inherit a COPY of the parent's learned directional tree.
            c0.dtree = (int)dtrees_.size();
            dtrees_.push_back(dtrees_[parentDTree]);
            c1.dtree = (int)dtrees_.size();
            dtrees_.push_back(dtrees_[parentDTree]);

            nodes_[leaf].axis = a;
            nodes_[leaf].split = mid;
            nodes_[leaf].child0 = (int)nodes_.size();
            nodes_.push_back(c0);
            nodes_[leaf].child1 = (int)nodes_.size();
            nodes_.push_back(c1);
            // The parent's own DTree index is now dangling (never read on an
            // interior node); left in the pool, harmless.
        }
        // (2) directional refine of every (current) leaf.
        for (const SNode& n : nodes_)
            if (n.axis < 0) dtrees_[n.dtree].refine(dirRho);
    }

    // Zero every leaf's directional flux and spatial sample count, keeping
    // topology (the refined structure is re-splatted next iteration).
    void resetIteration() {
        for (SNode& n : nodes_) n.sampleCount = 0;
        for (DTree& d : dtrees_) d.reset();
    }

    SDTree snapshot() const { return *this; }  // deep copy (vectors copy)

    int numLeaves() const {
        int count = 0;
        for (const SNode& n : nodes_)
            if (n.axis < 0) ++count;
        return count;
    }
    int numNodes() const { return (int)nodes_.size(); }
    // Test accessors: the AABB of the leaf containing p.
    void leafBounds(const float p[3], float outMin[3], float outMax[3]) const {
        const SNode& n = nodes_[leafIndex(p)];
        for (int i = 0; i < 3; ++i) { outMin[i] = n.minb[i]; outMax[i] = n.maxb[i]; }
    }
    uint32_t leafSampleCount(const float p[3]) const {
        return nodes_[leafIndex(p)].sampleCount;
    }

private:
    struct SNode {
        int axis = -1;        // <0 ⇒ leaf
        float split = 0.0f;
        int child0 = -1, child1 = -1;
        int dtree = -1;       // leaf: index into dtrees_
        int depth = 0;
        float minb[3] = {0, 0, 0};
        float maxb[3] = {0, 0, 0};
        uint32_t sampleCount = 0;
    };
    std::vector<SNode> nodes_;
    std::vector<DTree> dtrees_;
};

}  // namespace guiding
}  // namespace astroray
