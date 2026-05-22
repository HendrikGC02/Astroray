#pragma once

// Light Tree — many-lights importance sampling via Conty 2018.
//
// Algorithm reference:
//   Alejandro Conty Estevez & Christopher Kulla, "Importance Sampling of Many
//   Lights with Adaptive Tree Splitting", Proc. ACM Comput. Graph. Interact.
//   Tech. 1(2): 25:1-25:17 (2018), DOI 10.1145/3233305.
//
// Implementation reference (Apache-2.0):
//   Blender Cycles light tree, commit e52e5eb06f6b24055f0e7508bc7d7278e139ba0f.
//   - intern/cycles/scene/light_tree.{h,cpp} — build, split, orientation merge.
//   - intern/cycles/kernel/light/tree.h — traversal, importance calculation.
//
// This header defines an Astroray-native light tree API that mirrors the Cycles
// algorithm but uses Astroray's Vec3/AABB/Light types. The Cycles sources are
// vendored at external/cycles_light_tree/ for reference; key functions are cited
// in src/light_tree.cpp at each call site.

#include <vector>
#include <memory>
#include <random>

// Forward-declare types from raytracer.h (Vec3, AABB, etc.).
struct Vec3;
struct AABB;
class LightList;

namespace astroray {

class Light;
struct OrientationCone;
struct SampledWavelengths;
struct SampledSpectrum;

// ============================================================================
// OrientationBounds — bounding cone for a light cluster.
// Mirrors Cycles OrientationBounds (scene/light_tree.h:24-77).
// ============================================================================
struct OrientationBounds {
    Vec3  axis;       // cluster normal axis
    float theta_o;    // outer half-angle (bounds normals)
    float theta_e;    // emission half-angle (bounds emission directions)

    OrientationBounds() : axis(0, 0, 1), theta_o(0), theta_e(0) {}
    OrientationBounds(const Vec3& ax, float to, float te)
        : axis(ax), theta_o(to), theta_e(te) {}

    // Empty sentinel for merge operations.
    static OrientationBounds empty();

    bool isEmpty() const;

    // Surface-area-orientation measure (SAOM).
    // Cycles OrientationBounds::calculate_measure (scene/light_tree.cpp:14-27, Apache-2.0).
    float measure() const;

    // Merge two bounding cones via spherical linear interpolation.
    // Cycles merge(OrientationBounds, OrientationBounds) (scene/light_tree.cpp:29-77, Apache-2.0).
    static OrientationBounds merge(const OrientationBounds& a, const OrientationBounds& b);
};

// ============================================================================
// LightTreeNode — binary tree node (inner or leaf).
// Mirrors Cycles LightTreeNode (scene/light_tree.h:151-211).
// ============================================================================
struct LightTreeNode {
    AABB              bbox;          // spatial bounding box
    OrientationBounds bcone;         // orientation cone
    float             energy;        // total emitted power

    // Inner node: indices of left/right children in the flat array.
    int leftChild  = -1;
    int rightChild = -1;

    // Leaf node: indices into the emitter array.
    int firstEmitter = -1;
    int numEmitters  = 0;

    bool isLeaf() const { return firstEmitter >= 0; }
};

// ============================================================================
// LightTreeEmitter — a single light (Hittable or dedicated Light).
// Simplified version of Cycles LightTreeEmitter (scene/light_tree.h:79-147).
// ============================================================================
struct LightTreeEmitter {
    Vec3              centroid;      // world-space center
    AABB              bbox;          // world-space bounds
    OrientationBounds bcone;         // orientation cone
    float             energy;        // total power

    // Index into LightList (Hittable or dedicated Light).
    int lightIndex;
    bool isDedicated;  // true = dedicatedLights[lightIndex]; false = lights[lightIndex]

    LightTreeEmitter() : energy(0), lightIndex(-1), isDedicated(false) {}
};

// ============================================================================
// LightTree — build-once, sample-many light tree.
// Mirrors Cycles LightTree (scene/light_tree.h:213-275).
// ============================================================================
class LightTree {
public:
    LightTree() = default;

    // Build the tree from a LightList. Call once at scene setup.
    // Mirrors Cycles LightTree::build (scene/light_tree.cpp, Apache-2.0).
    void build(const LightList& lightList);

    // Sample a light from the tree, given a shading point and normal.
    // Returns the light index (into LightList), pdf, and whether it's dedicated.
    // Mirrors Cycles light_tree_sample (kernel/light/tree.h, Apache-2.0).
    struct PickResult {
        int   lightIndex;
        bool  isDedicated;
        float pdf;
    };
    PickResult pick(const Vec3& point, const Vec3& normal, float u, std::mt19937& gen) const;

    // PDF for a given light index from the shading point (for MIS).
    float pdf(const Vec3& point, const Vec3& normal, int lightIndex, bool isDedicated) const;

    bool empty() const { return nodes.empty(); }

private:
    std::vector<LightTreeNode>    nodes;
    std::vector<LightTreeEmitter> emitters;

    // Recursive tree builder. Returns node index in `nodes`.
    // Mirrors Cycles LightTree::recursive_build (scene/light_tree.cpp, Apache-2.0).
    int buildRecursive(int start, int end, int depth);

    // Decide split axis and position using surface-area-orientation heuristic.
    // Mirrors Cycles should_split (scene/light_tree.cpp, Apache-2.0).
    bool shouldSplit(int start, int end, int& splitAxis, int& splitIndex, float& splitCost) const;

    // Compute importance of a node from a shading point.
    // Mirrors Cycles light_tree_importance (kernel/light/tree.h, Apache-2.0).
    float importance(const LightTreeNode& node, const Vec3& point, const Vec3& normal) const;
};

} // namespace astroray
