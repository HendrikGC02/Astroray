#pragma once
// ============================================================================
// #990 — per-corner shading attribute layers (Attribute / Color Attribute /
// Object Info nodes), shared CPU + GPU.
//
// A layer is a named Vec3 per triangle corner, interpolated barycentrically at
// the hit (Cycles primitive_surface_attribute for POINT / CORNER domains; a FACE
// domain or a per-object constant arrives as three equal corners). The addon
// decides what a layer holds (Cycles svm_node_attr output conversions, Object
// Info constants: kernel/svm/attribute.h, svm/geometry.h, scene/object.cpp,
// Apache-2.0); the engine only stores and interpolates. Names are interned to
// small ids once per process so the per-hit lookup is an int compare.
// ============================================================================

#include "astroray/gpu_types.h"   // HD

#ifndef __CUDACC__
#include <mutex>
#include <string>
#include <unordered_map>
#endif

namespace astroray {
namespace attr {

// Barycentric interpolation of three corner values at a point of the triangle
// (v0, v1, v2), barycentrics recomputed from the point (Ericson, Real-Time
// Collision Detection §3.4; the same form as the #847 Generated-coordinate
// fetch). Returns false for a degenerate triangle.
template<class V>
HD inline bool interpolate_corners(const V& v0, const V& v1, const V& v2, const V& p,
                                   const V& c0, const V& c1, const V& c2, V& out) {
    V e1 = v1 - v0, e2 = v2 - v0, ep = p - v0;
    float d00 = e1.dot(e1), d01 = e1.dot(e2), d11 = e2.dot(e2);
    float d20 = ep.dot(e1), d21 = ep.dot(e2);
    float denom = d00 * d11 - d01 * d01;
    if (!(denom > 1e-20f || denom < -1e-20f)) return false;
    float b1 = (d11 * d20 - d01 * d21) / denom;
    float b2 = (d00 * d21 - d01 * d20) / denom;
    out = c0 + (c1 - c0) * b1 + (c2 - c0) * b2;   // exact for equal corners
    return true;
}

#ifndef __CUDACC__
// Process-wide layer-name -> id interning (host only; scene build time).
inline int layer_id(const std::string& name) {
    static std::mutex m;
    static std::unordered_map<std::string, int> ids;
    std::lock_guard<std::mutex> lock(m);
    auto it = ids.find(name);
    if (it != ids.end()) return it->second;
    const int id = (int)ids.size();
    ids.emplace(name, id);
    return id;
}
#endif

}  // namespace attr
}  // namespace astroray
