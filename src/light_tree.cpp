#include "raytracer.h"
#include "astroray/light_tree.h"
#include "astroray/light.h"
#include <algorithm>
#include <cmath>
#include <cassert>

// Light Tree implementation mirroring Blender Cycles (Apache-2.0, commit e52e5eb0).
//
// Algorithm: Conty & Kulla 2018, "Importance Sampling of Many Lights with
// Adaptive Tree Splitting", Proc. ACM Comput. Graph. Interact. Tech. 1(2).
//
// Reference implementation: Cycles intern/cycles/scene/light_tree.cpp and
// intern/cycles/kernel/light/tree.h (Apache-2.0, Blender Foundation).
//
// Each mirrored function is cited with "// Cycles <function>::<name>" at the
// point of use. The algorithm is preserved; the infrastructure is adapted to
// Astroray's Vec3/AABB/Light types per CLAUDE.md §6.

namespace astroray {

// ============================================================================
// OrientationBounds implementation
// ============================================================================

// Cycles OrientationBounds::empty (scene/light_tree.h:41-44, Apache-2.0).
OrientationBounds OrientationBounds::empty() {
    return OrientationBounds(Vec3(0, 0, 0), std::numeric_limits<float>::lowest(),
                             std::numeric_limits<float>::lowest());
}

bool OrientationBounds::isEmpty() const {
    return axis.dot(axis) < 1e-8f;
}

// Cycles OrientationBounds::calculate_measure (scene/light_tree.cpp:14-27, Apache-2.0).
float OrientationBounds::measure() const {
    if (isEmpty()) {
        return 0.0f;
    }

    const float theta_w = std::min(static_cast<float>(M_PI), theta_o + theta_e);
    const float cos_theta_o = std::cos(theta_o);
    const float sin_theta_o = std::sin(theta_o);

    return (2.0f * M_PI) * (1.0f - cos_theta_o) +
           (M_PI / 2.0f) * (2.0f * theta_w * sin_theta_o - std::cos(theta_o - 2.0f * theta_w) -
                            2.0f * theta_o * sin_theta_o + cos_theta_o);
}

// Cycles merge(OrientationBounds, OrientationBounds) (scene/light_tree.cpp:29-77, Apache-2.0).
OrientationBounds OrientationBounds::merge(const OrientationBounds& cone_a,
                                           const OrientationBounds& cone_b) {
    if (cone_a.isEmpty()) return cone_b;
    if (cone_b.isEmpty()) return cone_a;

    // Set cone `a` to always have the greater `theta_o`.
    const OrientationBounds* a = &cone_a;
    const OrientationBounds* b = &cone_b;
    if (cone_b.theta_o > cone_a.theta_o) {
        a = &cone_b;
        b = &cone_a;
    }

    const float cos_a_b = a->axis.dot(b->axis);
    const float theta_d = std::acos(std::clamp(cos_a_b, -1.0f, 1.0f));
    const float theta_e = std::max(a->theta_e, b->theta_e);

    // Return axis and `theta_o` of `a` if it already contains `b`.
    if (a->theta_o + 5e-4f >= std::min(static_cast<float>(M_PI), theta_d + b->theta_o)) {
        return OrientationBounds(a->axis, a->theta_o, theta_e);
    }

    // Compute new `theta_o` that contains both `a` and `b`.
    const float theta_o = (theta_d + a->theta_o + b->theta_o) * 0.5f;

    if (theta_o >= M_PI) {
        return OrientationBounds(a->axis, static_cast<float>(M_PI), theta_e);
    }

    // Slerp between `a` and `b`.
    Vec3 new_axis;
    if (cos_a_b < -0.9995f) {
        // Opposite direction, any orthogonal vector is fine.
        // Cycles make_orthonormals (util/math.h, Apache-2.0).
        Vec3 unused;
        if (std::abs(a->axis.x) > std::abs(a->axis.y)) {
            new_axis = Vec3(-a->axis.z, 0, a->axis.x).normalized();
        } else {
            new_axis = Vec3(0, a->axis.z, -a->axis.y).normalized();
        }
    } else {
        const float theta_r = theta_o - a->theta_o;
        const Vec3 ortho = (b->axis - a->axis * cos_a_b).normalized();
        new_axis = (a->axis * std::cos(theta_r) + ortho * std::sin(theta_r)).normalized();
    }

    return OrientationBounds(new_axis, theta_o, theta_e);
}

// ============================================================================
// LightTree::build — construct the tree from LightList
// ============================================================================

// Cycles LightTree::build (scene/light_tree.cpp, Apache-2.0).
void LightTree::build(const LightList& lightList) {
    emitters.clear();
    nodes.clear();

    // Extract emitters from LightList (both Hittables and dedicated Lights).
    const auto& hittableLights = lightList.getLights();
    const auto& dedicatedLights = lightList.getDedicatedLights();

    for (size_t i = 0; i < hittableLights.size(); ++i) {
        const auto& hittable = hittableLights[i];
        LightTreeEmitter e;
        e.lightIndex = static_cast<int>(i);
        e.isDedicated = false;

        // Compute bounding box.
        if (!hittable->boundingBox(e.bbox)) {
            e.bbox = AABB(Vec3(-1e10f, -1e10f, -1e10f), Vec3(1e10f, 1e10f, 1e10f));
        }
        e.centroid = e.bbox.centroid();

        // Compute energy (power).
        Vec3 emission_rgb = hittable->emittedRadiance();
        float luminance = 0.2126f * emission_rgb.x + 0.7152f * emission_rgb.y + 0.0722f * emission_rgb.z;
        e.energy = luminance;
        if (!hittable->isInfiniteLight()) {
            e.energy *= e.bbox.area();
        }

        // Orientation cone: assume full-sphere for Hittable lights (no explicit orientation).
        e.bcone = OrientationBounds(Vec3(0, 0, 1), static_cast<float>(M_PI), static_cast<float>(M_PI));

        emitters.push_back(e);
    }

    for (size_t i = 0; i < dedicatedLights.size(); ++i) {
        const Light* light = dedicatedLights[i].get();
        LightTreeEmitter e;
        e.lightIndex = static_cast<int>(i);
        e.isDedicated = true;

        e.bbox = light->bounds();
        e.centroid = e.bbox.centroid();
        e.energy = light->power();

        // Orientation cone from Light.
        OrientationCone lightCone = light->orientationCone();
        e.bcone = OrientationBounds(lightCone.axis, lightCone.theta_o, lightCone.theta_e);

        emitters.push_back(e);
    }

    if (emitters.empty()) {
        return;
    }

    // Build tree recursively.
    buildRecursive(0, static_cast<int>(emitters.size()), 0);
}

// ============================================================================
// LightTree::buildRecursive — recursive tree builder
// ============================================================================

// Cycles LightTree::recursive_build (scene/light_tree.cpp, Apache-2.0).
int LightTree::buildRecursive(int start, int end, int depth) {
    assert(start < end);

    int nodeIdx = static_cast<int>(nodes.size());
    nodes.emplace_back();

    // Compute bounding box and orientation cone for this cluster.
    AABB bbox = emitters[start].bbox;
    OrientationBounds bcone = emitters[start].bcone;
    float energy = emitters[start].energy;

    for (int i = start + 1; i < end; ++i) {
        bbox = bbox.merge(emitters[i].bbox);
        bcone = OrientationBounds::merge(bcone, emitters[i].bcone);
        energy += emitters[i].energy;
    }

    int numEmitters = end - start;

    // Leaf threshold: stop if ≤ 4 emitters or depth ≥ 32 (practical limit).
    const int maxLeafSize = 4;
    const int maxDepth = 32;

    if (numEmitters <= maxLeafSize || depth >= maxDepth) {
        // Create leaf.
        nodes[nodeIdx].bbox = bbox;
        nodes[nodeIdx].bcone = bcone;
        nodes[nodeIdx].energy = energy;
        nodes[nodeIdx].firstEmitter = start;
        nodes[nodeIdx].numEmitters = numEmitters;
        return nodeIdx;
    }

    // Try to split using SAOH (surface-area-orientation heuristic).
    int splitAxis, splitIndex;
    float splitCost;
    if (!shouldSplit(start, end, splitAxis, splitIndex, splitCost)) {
        // Split not beneficial; make leaf.
        nodes[nodeIdx].bbox = bbox;
        nodes[nodeIdx].bcone = bcone;
        nodes[nodeIdx].energy = energy;
        nodes[nodeIdx].firstEmitter = start;
        nodes[nodeIdx].numEmitters = numEmitters;
        return nodeIdx;
    }

    // Partition emitters around split point (SAOH returns exact count for left partition).
    // Use nth_element to place the splitIndex'th element in the correct position.
    std::nth_element(emitters.begin() + start, emitters.begin() + splitIndex,
                     emitters.begin() + end,
                     [splitAxis](const LightTreeEmitter& a, const LightTreeEmitter& b) {
                         if (splitAxis == 0) return a.centroid.x < b.centroid.x;
                         if (splitAxis == 1) return a.centroid.y < b.centroid.y;
                         return a.centroid.z < b.centroid.z;
                     });

    // Recurse.
    int leftChild = buildRecursive(start, splitIndex, depth + 1);
    int rightChild = buildRecursive(splitIndex, end, depth + 1);

    // Write to node after recursion (safe from reallocation).
    nodes[nodeIdx].bbox = bbox;
    nodes[nodeIdx].bcone = bcone;
    nodes[nodeIdx].energy = energy;
    nodes[nodeIdx].leftChild = leftChild;
    nodes[nodeIdx].rightChild = rightChild;

    return nodeIdx;
}

// ============================================================================
// LightTree::shouldSplit — SAOH (Surface-Area-Orientation Heuristic) split
// ============================================================================

// Cycles should_split (scene/light_tree.cpp, Apache-2.0, commit e52e5eb0).
// Uses bucket-SAOH cost evaluation per Conty & Kulla 2018 §4.2 eq 8.
bool LightTree::shouldSplit(int start, int end, int& outSplitAxis, int& outSplitIndex,
                            float& outSplitCost) const {
    const int numEmitters = end - start;
    if (numEmitters < 2) {
        return false;
    }

    // Compute centroid bounding box.
    AABB centroidBox = AABB(emitters[start].centroid, emitters[start].centroid);
    for (int i = start + 1; i < end; ++i) {
        centroidBox.min = Vec3::min(centroidBox.min, emitters[i].centroid);
        centroidBox.max = Vec3::max(centroidBox.max, emitters[i].centroid);
    }

    Vec3 extent = centroidBox.max - centroidBox.min;
    float maxExtent = std::max({extent.x, extent.y, extent.z});

    // Helper: compute SAOH measure for a cluster.
    // M(C) = energy · bbox_area · orientation_measure (Conty 2018 eq 8).
    auto computeMeasure = [](const AABB& bbox, const OrientationBounds& bcone, float energy) -> float {
        if (energy == 0.0f) return 0.0f;
        float area = bbox.area();
        if (area == 0.0f) {
            // Degenerate bbox: use diagonal length instead.
            area = (bbox.max - bbox.min).length();
        }
        return energy * area * bcone.measure();
    };

    // Compute total cluster measure (for regularization check).
    AABB clusterBox = emitters[start].bbox;
    OrientationBounds clusterCone = emitters[start].bcone;
    float clusterEnergy = emitters[start].energy;
    for (int i = start + 1; i < end; ++i) {
        clusterBox = clusterBox.merge(emitters[i].bbox);
        clusterCone = OrientationBounds::merge(clusterCone, emitters[i].bcone);
        clusterEnergy += emitters[i].energy;
    }
    float totalCost = computeMeasure(clusterBox, clusterCone, clusterEnergy);

    if (totalCost == 0.0f) {
        return false;  // Degenerate cluster.
    }

    // Try each axis, find minimum-cost split.
    const int numBuckets = 12;  // Cycles default (Conty 2018 §4.3).
    float minCost = std::numeric_limits<float>::max();
    outSplitAxis = 0;
    outSplitIndex = (start + end) / 2;

    for (int dim = 0; dim < 3; ++dim) {
        if (extent[dim] == 0.0f) {
            continue;  // No variation along this axis.
        }

        // Bucket emitters along this axis.
        struct Bucket {
            AABB bbox;
            OrientationBounds bcone = OrientationBounds::empty();
            float energy = 0.0f;
            int count = 0;
        };
        Bucket buckets[numBuckets];

        float invExtent = 1.0f / extent[dim];
        for (int i = start; i < end; ++i) {
            const LightTreeEmitter& e = emitters[i];
            int bucketIdx = static_cast<int>(numBuckets * (e.centroid[dim] - centroidBox.min[dim]) * invExtent);
            bucketIdx = std::clamp(bucketIdx, 0, numBuckets - 1);

            Bucket& b = buckets[bucketIdx];
            if (b.count == 0) {
                b.bbox = e.bbox;
                b.bcone = e.bcone;
                b.energy = e.energy;
            } else {
                b.bbox = b.bbox.merge(e.bbox);
                b.bcone = OrientationBounds::merge(b.bcone, e.bcone);
                b.energy += e.energy;
            }
            b.count++;
        }

        // Precompute cumulative left/right measures.
        Bucket leftBuckets[numBuckets - 1];
        leftBuckets[0] = buckets[0];
        for (int i = 1; i < numBuckets - 1; ++i) {
            Bucket& left = leftBuckets[i];
            const Bucket& prev = leftBuckets[i - 1];
            const Bucket& curr = buckets[i];
            left.bbox = prev.bbox.merge(curr.bbox);
            left.bcone = OrientationBounds::merge(prev.bcone, curr.bcone);
            left.energy = prev.energy + curr.energy;
            left.count = prev.count + curr.count;
        }

        Bucket rightBuckets[numBuckets - 1];
        rightBuckets[numBuckets - 2] = buckets[numBuckets - 1];
        for (int i = numBuckets - 3; i >= 0; --i) {
            Bucket& right = rightBuckets[i];
            const Bucket& next = rightBuckets[i + 1];
            const Bucket& curr = buckets[i + 1];
            right.bbox = next.bbox.merge(curr.bbox);
            right.bcone = OrientationBounds::merge(next.bcone, curr.bcone);
            right.energy = next.energy + curr.energy;
            right.count = next.count + curr.count;
        }

        // Evaluate split cost at each bucket boundary.
        // Cycles applies a regularization factor: maxExtent / extent[dim].
        float regularization = maxExtent * invExtent;
        for (int split = 0; split < numBuckets - 1; ++split) {
            const Bucket& left = leftBuckets[split];
            const Bucket& right = rightBuckets[split];

            if (left.count == 0 || right.count == 0) {
                continue;  // Invalid split.
            }

            float leftCost = computeMeasure(left.bbox, left.bcone, left.energy);
            float rightCost = computeMeasure(right.bbox, right.bcone, right.energy);
            float cost = regularization * (leftCost + rightCost);

            if (cost < totalCost && cost < minCost) {
                minCost = cost;
                outSplitAxis = dim;
                outSplitIndex = start + left.count;
            }
        }
    }

    outSplitCost = minCost;
    // Return true if split improves cost, or if cluster is too large.
    return minCost < totalCost || numEmitters > 4;  // maxLeafSize = 4 (from buildRecursive).
}

// ============================================================================
// LightTree::importance — Full Conty 2018 importance metric with cone-cone pruning
// ============================================================================

// Cycles light_tree_importance (kernel/light/tree.h, Apache-2.0, commit e52e5eb0).
// Implements the full Conty & Kulla 2018 §4.4 eq 11 with orientation cone visibility test.
float LightTree::importance(const LightTreeNode& node, const Vec3& point,
                            const Vec3& normal) const {
    // Compute vector from point to cluster centroid.
    Vec3 centroid = node.bbox.centroid();
    Vec3 pointToCentroid = (centroid - point);
    float distance = pointToCentroid.length();
    if (distance < 1e-6f) {
        distance = 1e-6f;  // Avoid division by zero.
    }
    Vec3 pointToCentroidNorm = pointToCentroid / distance;

    // Compute subtended half-angle theta_u (bounding sphere of the cluster bbox).
    // Cycles: light_tree_cos_bound_subtended_angle (kernel/light/tree.h).
    float bboxRadius = (node.bbox.max - centroid).length();
    float distanceSq = distance * distance;
    float radiusSq = bboxRadius * bboxRadius;

    float cosSubtendedAngle;
    if (distanceSq <= radiusSq) {
        // Point inside bounding sphere.
        cosSubtendedAngle = -1.0f;
    } else {
        float sinSubtendedAngleSq = radiusSq / distanceSq;
        cosSubtendedAngle = std::sqrt(1.0f - sinSubtendedAngleSq);
    }
    float sinSubtendedAngle = std::sqrt(std::max(0.0f, 1.0f - cosSubtendedAngle * cosSubtendedAngle));

    // Compute cos(theta_i) — angle between point-to-centroid and shading normal.
    // For surface shading (not volume), we care about the incidence angle.
    float cosThetaI = pointToCentroidNorm.dot(normal);
    float sinThetaI = std::sqrt(std::max(0.0f, 1.0f - cosThetaI * cosThetaI));

    // cos_min_incidence_angle = cos(max{theta_i - theta_u, 0}).
    // Cycles: line 152-154 in kernel/light/tree.h.
    float cosMinIncidenceAngle;
    if (cosThetaI >= cosSubtendedAngle) {
        cosMinIncidenceAngle = 1.0f;
    } else {
        cosMinIncidenceAngle = cosThetaI * cosSubtendedAngle + sinThetaI * sinSubtendedAngle;
    }

    // If cluster is entirely behind the surface (and surface is opaque), prune.
    if (cosMinIncidenceAngle < 0.0f) {
        return 0.0f;
    }

    // Compute cos(theta) — angle between cluster axis and -point_to_centroid (emission direction).
    // Cycles: line 177-178 in kernel/light/tree.h.
    Vec3 negPointToCentroid = pointToCentroidNorm * -1.0f;
    float cosTheta = node.bcone.axis.dot(negPointToCentroid);
    float sinTheta = std::sqrt(std::max(0.0f, 1.0f - cosTheta * cosTheta));

    // cos(theta - theta_u).
    float cosThetaMinusSubtended = cosTheta * cosSubtendedAngle + sinTheta * sinSubtendedAngle;

    // Compute cos_min_outgoing_angle (cone-cone visibility test).
    // Cycles: lines 190-210 in kernel/light/tree.h.
    float cosThetaO = std::cos(node.bcone.theta_o);
    float sinThetaO = std::sin(node.bcone.theta_o);

    float cosMinOutgoingAngle;
    if (cosTheta >= cosSubtendedAngle || cosThetaMinusSubtended >= cosThetaO) {
        // theta - theta_o - theta_u <= 0: cluster fully visible.
        cosMinOutgoingAngle = 1.0f;
    } else if ((node.bcone.theta_o + node.bcone.theta_e > M_PI) ||
               (cosThetaMinusSubtended > std::cos(node.bcone.theta_o + node.bcone.theta_e))) {
        // Partial visibility: theta' = theta - theta_o - theta_u < theta_e.
        // Cycles: lines 203-205.
        float sinThetaMinusSubtended = std::sqrt(std::max(0.0f, 1.0f - cosThetaMinusSubtended * cosThetaMinusSubtended));
        cosMinOutgoingAngle = cosThetaMinusSubtended * cosThetaO + sinThetaMinusSubtended * sinThetaO;
    } else {
        // Cluster is invisible from this shading point.
        return 0.0f;
    }

    // Final importance: (energy / distance²) · cos_min_incidence_angle · cos_min_outgoing_angle.
    // Cycles: line 215-216 in kernel/light/tree.h.
    float minDistance = std::max(distance - bboxRadius, 1e-6f);
    float importance = node.energy * cosMinIncidenceAngle * cosMinOutgoingAngle / (minDistance * minDistance);

    return importance;
}

// ============================================================================
// LightTree::pick — sample a light from the tree
// ============================================================================

// Cycles light_tree_sample (kernel/light/tree.h, Apache-2.0).
LightTree::PickResult LightTree::pick(const Vec3& point, const Vec3& normal, float u,
                                      std::mt19937& gen) const {
    if (nodes.empty()) {
        return PickResult{-1, false, 0.0f};
    }

    // Traverse from root to leaf using importance-weighted stochastic descent.
    int nodeIdx = 0;
    float pdf = 1.0f;

    while (!nodes[nodeIdx].isLeaf()) {
        const LightTreeNode& node = nodes[nodeIdx];
        const LightTreeNode& left = nodes[node.leftChild];
        const LightTreeNode& right = nodes[node.rightChild];

        float leftImp = importance(left, point, normal);
        float rightImp = importance(right, point, normal);
        float totalImp = leftImp + rightImp;

        if (totalImp < 1e-8f) {
            // Both children have zero importance; pick left arbitrarily.
            nodeIdx = node.leftChild;
            pdf *= 0.5f;
        } else {
            float leftProb = leftImp / totalImp;
            if (u < leftProb) {
                nodeIdx = node.leftChild;
                pdf *= leftProb;
                u = u / leftProb;  // Reuse u for next level.
            } else {
                nodeIdx = node.rightChild;
                pdf *= (1.0f - leftProb);
                u = (u - leftProb) / (1.0f - leftProb);
            }
        }
    }

    // At leaf: pick an emitter uniformly.
    const LightTreeNode& leaf = nodes[nodeIdx];
    int emitterIdx = leaf.firstEmitter + static_cast<int>(u * leaf.numEmitters);
    emitterIdx = std::min(emitterIdx, leaf.firstEmitter + leaf.numEmitters - 1);

    pdf *= 1.0f / leaf.numEmitters;

    const LightTreeEmitter& e = emitters[emitterIdx];
    return PickResult{e.lightIndex, e.isDedicated, pdf};
}

// ============================================================================
// LightTree::pdf — compute PDF for a given light index
// ============================================================================

// Helper: check if a subtree contains a given emitter index.
bool LightTree::subtreeContainsEmitter(int nodeIdx, int emitterIdx) const {
    if (nodeIdx < 0 || nodeIdx >= static_cast<int>(nodes.size())) {
        return false;
    }

    const LightTreeNode& node = nodes[nodeIdx];
    if (node.isLeaf()) {
        int leafStart = node.firstEmitter;
        int leafEnd = node.firstEmitter + node.numEmitters;
        return emitterIdx >= leafStart && emitterIdx < leafEnd;
    }

    // Recurse into children.
    return subtreeContainsEmitter(node.leftChild, emitterIdx) ||
           subtreeContainsEmitter(node.rightChild, emitterIdx);
}

float LightTree::pdf(const Vec3& point, const Vec3& normal, int lightIndex,
                     bool isDedicated) const {
    // Find the emitter in the flat array.
    int emitterIdx = -1;
    for (size_t i = 0; i < emitters.size(); ++i) {
        if (emitters[i].lightIndex == lightIndex && emitters[i].isDedicated == isDedicated) {
            emitterIdx = static_cast<int>(i);
            break;
        }
    }

    if (emitterIdx < 0 || nodes.empty()) {
        return 0.0f;
    }

    // Walk the tree to compute the probability of reaching this emitter.
    // This mirrors the traversal logic in pick().
    float pdf = 1.0f;
    int nodeIdx = 0;

    while (!nodes[nodeIdx].isLeaf()) {
        const LightTreeNode& node = nodes[nodeIdx];
        const LightTreeNode& left = nodes[node.leftChild];
        const LightTreeNode& right = nodes[node.rightChild];

        float leftImp = importance(left, point, normal);
        float rightImp = importance(right, point, normal);
        float totalImp = leftImp + rightImp;

        // Determine which subtree contains our target emitter.
        bool inLeft = subtreeContainsEmitter(node.leftChild, emitterIdx);
        bool inRight = subtreeContainsEmitter(node.rightChild, emitterIdx);

        if (!inLeft && !inRight) {
            // Emitter not in this subtree (shouldn't happen).
            return 0.0f;
        }

        if (totalImp < 1e-8f) {
            // Both children have zero importance. Uniform fallback.
            pdf *= 0.5f;
            nodeIdx = inLeft ? node.leftChild : node.rightChild;
        } else {
            float leftProb = leftImp / totalImp;
            if (inLeft) {
                pdf *= leftProb;
                nodeIdx = node.leftChild;
            } else {
                pdf *= (1.0f - leftProb);
                nodeIdx = node.rightChild;
            }
        }
    }

    // At leaf: uniform pdf over emitters in the leaf.
    const LightTreeNode& leaf = nodes[nodeIdx];
    pdf *= 1.0f / leaf.numEmitters;

    return pdf;
}

} // namespace astroray
