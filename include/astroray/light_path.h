#pragma once
// ============================================================================
// #991 — Light Path node semantics, shared CPU + GPU (single source, HD).
//
// An explicit path-state shading context (PathContext) plus the pure functions
// that read it (light_path_output = Cycles svm_node_light_path) and advance it
// across a bounce (next_surface / next_volume = the subset of Cycles
// path_state_next that the Light Path outputs observe). Callers fill the
// context from state already live at the vertex (CPU: pathTraceSpectral locals;
// GPU: GPUWavefrontState.bounce + lp_state + the parked hit t), so this header
// is a re-hostable service for the per-hit graph interpreter (architecture memo
// .astroray_plan/docs/shader-graph-architecture-2026-10-03.md, option B).
//
// Reference (Apache-2.0): Blender Cycles
//   intern/cycles/kernel/svm/light_path.h        svm_node_light_path
//   intern/cycles/kernel/integrator/path_state.h path_state_next,
//                                                path_state_ray_visibility
// Research note: .astroray_plan/docs/issue991-light-path-research.md.
//
// Contexts (Cycles path_visibility / path_flag):
//   camera ray   : CAMERA                     (path start)
//   surface hit  : labels of the bounce that produced the ray
//   shadow ray   : SHADOW only (visibility); Ray Depth = bounce + 1
//   emission eval: no visibility bit, EMISSION path flag; Ray Depth = bounce + 1
// A transparent pass (a straight-through delta sample: Principled Alpha / a
// Transparent BSDF) keeps the ray's flags, as Cycles' LABEL_TRANSPARENT does, and
// counts in transparentDepth; Astroray's bounce counter still includes it, so
// Ray Depth subtracts it.
//
// SPDX-License-Identifier: Apache-2.0 (semantics derived from Cycles).
// ============================================================================

#include "astroray/gpu_types.h"   // HD

namespace astroray {
namespace lightpath {

// Path-flag bits (Cycles PATH_RAY_VISIBILITY_* + PATH_RAY_SINGULAR/REFLECT/EMISSION).
enum : unsigned {
    LPF_CAMERA         = 1u << 0,
    LPF_SHADOW         = 1u << 1,
    LPF_DIFFUSE        = 1u << 2,
    LPF_GLOSSY         = 1u << 3,
    LPF_TRANSMIT       = 1u << 4,
    LPF_VOLUME_SCATTER = 1u << 5,
    LPF_SINGULAR       = 1u << 6,
    LPF_REFLECT        = 1u << 7,
    LPF_EMISSION       = 1u << 8,
    LPF_LABEL_MASK     = (1u << 9) - 1u,
};

// Light Path node outputs (compiler-owned order; blender_addon/shader_vm_compiler.py
// LIGHT_PATH_OUTPUTS mirrors it).
enum Output : unsigned char {
    LPO_IS_CAMERA = 0, LPO_IS_SHADOW, LPO_IS_DIFFUSE, LPO_IS_GLOSSY, LPO_IS_SINGULAR,
    LPO_IS_REFLECTION, LPO_IS_TRANSMISSION, LPO_IS_VOLUME_SCATTER,
    LPO_RAY_LENGTH, LPO_RAY_DEPTH, LPO_DIFFUSE_DEPTH, LPO_GLOSSY_DEPTH,
    LPO_TRANSPARENT_DEPTH, LPO_TRANSMISSION_DEPTH,
    LPO_COUNT
};

// The explicit shading context. depth = Cycles path bounce of the vertex.
struct PathContext {
    unsigned flags = LPF_CAMERA;
    unsigned short depth = 0;
    unsigned short diffuseDepth = 0;
    unsigned short glossyDepth = 0;
    unsigned short transmissionDepth = 0;
    unsigned short transparentDepth = 0;
    float rayLength = 0.0f;
};

// Cycles svm_node_light_path. Visibility outputs (camera/shadow/diffuse/glossy/
// transmission/volume) read the visibility bits, singular/reflection the path
// flag, exactly as upstream.
HD inline float light_path_output(unsigned char o, const PathContext& c) {
    switch (o) {
        case LPO_IS_CAMERA:         return (c.flags & LPF_CAMERA) ? 1.0f : 0.0f;
        case LPO_IS_SHADOW:         return (c.flags & LPF_SHADOW) ? 1.0f : 0.0f;
        case LPO_IS_DIFFUSE:        return (c.flags & LPF_DIFFUSE) ? 1.0f : 0.0f;
        case LPO_IS_GLOSSY:         return (c.flags & LPF_GLOSSY) ? 1.0f : 0.0f;
        case LPO_IS_SINGULAR:       return (c.flags & LPF_SINGULAR) ? 1.0f : 0.0f;
        case LPO_IS_REFLECTION:     return (c.flags & LPF_REFLECT) ? 1.0f : 0.0f;
        case LPO_IS_TRANSMISSION:   return (c.flags & LPF_TRANSMIT) ? 1.0f : 0.0f;
        case LPO_IS_VOLUME_SCATTER: return (c.flags & LPF_VOLUME_SCATTER) ? 1.0f : 0.0f;
        case LPO_RAY_LENGTH:        return c.rayLength;
        case LPO_RAY_DEPTH: {
            // "For background, light emission and shadow evaluation from a surface
            // or volume we are effectively one bounce further." (light_path.h)
            // Cycles' bounce excludes transparent passes; Astroray's counts them.
            float d = (float)(c.depth > c.transparentDepth ? c.depth - c.transparentDepth : 0);
            if (c.flags & (LPF_SHADOW | LPF_EMISSION)) d += 1.0f;
            return d;
        }
        case LPO_DIFFUSE_DEPTH:      return (float)c.diffuseDepth;
        case LPO_GLOSSY_DEPTH:       return (float)c.glossyDepth;
        case LPO_TRANSPARENT_DEPTH:  return (float)c.transparentDepth;
        case LPO_TRANSMISSION_DEPTH: return (float)c.transmissionDepth;
        default:                     return 0.0f;
    }
}

// Cycles path_state_next for a surface bounce. lobeCat is Astroray's bounce class
// (0 diffuse, 1 glossy, 2 transmission: the pkg201 per-type bounce-limit
// classifier, shared by both backends). A transmission ray carries no diffuse/
// glossy visibility (path_state_ray_visibility); a delta reflection is glossy +
// singular. The returned context is the one the NEXT vertex is shaded with
// (depth and rayLength are filled in there). `transparent`: a straight-through
// delta pass (Cycles LABEL_TRANSPARENT): flags kept, transparentDepth + 1.
HD inline PathContext next_surface(const PathContext& c, int lobeCat, bool singular,
                                   bool transparent = false) {
    PathContext n = c;
    if (transparent) {
        n.transparentDepth = (unsigned short)(c.transparentDepth + 1);
        return n;
    }
    unsigned f = 0u;
    if (lobeCat == 2) {
        f |= LPF_TRANSMIT;
        n.transmissionDepth = (unsigned short)(c.transmissionDepth + 1);
    } else {
        f |= LPF_REFLECT;
        if (lobeCat == 0) {
            f |= LPF_DIFFUSE;
            n.diffuseDepth = (unsigned short)(c.diffuseDepth + 1);
        } else {
            f |= LPF_GLOSSY;
            n.glossyDepth = (unsigned short)(c.glossyDepth + 1);
        }
    }
    if (singular) f |= LPF_SINGULAR;
    n.flags = f;
    return n;
}

// A straight-through delta sample (Principled Alpha / Transparent BSDF pass:
// wi == -wo) is Cycles' LABEL_TRANSPARENT. An IOR-1 smooth refraction is
// geometrically identical and is classified the same way here.
HD inline bool is_transparent_pass(bool isDelta, float woDotWi) {
    return isDelta && woDotWi < -0.99999f;
}

// Cycles path_state_next for a volume scatter: visibility VOLUME_SCATTER only,
// reflect/singular cleared, surface counters unchanged.
HD inline PathContext next_volume(const PathContext& c) {
    PathContext n = c;
    n.flags = LPF_VOLUME_SCATTER;
    return n;
}

// Shadow-ray / emission-evaluation contexts of a vertex at bounce `depth`.
HD inline PathContext shadow_context(unsigned short depth) {
    PathContext c; c.flags = LPF_SHADOW; c.depth = depth; return c;
}
HD inline PathContext emission_context(unsigned short depth) {
    PathContext c; c.flags = LPF_EMISSION; c.depth = depth; return c;
}

// GPU per-path packing (GPUWavefrontState.lp_state, one uint32 per slot): bits
// 0-8 label flags, then three 6-bit saturating counters (diffuse, glossy,
// transmission) and a 5-bit transparent counter. Depth and ray length are not
// stored: they are the slot's bounce and the parked hit t.
HD inline unsigned pack_state(const PathContext& c) {
    unsigned d = c.diffuseDepth < 63 ? c.diffuseDepth : 63;
    unsigned g = c.glossyDepth < 63 ? c.glossyDepth : 63;
    unsigned t = c.transmissionDepth < 63 ? c.transmissionDepth : 63;
    unsigned a = c.transparentDepth < 31 ? c.transparentDepth : 31;
    return (c.flags & LPF_LABEL_MASK) | (d << 9) | (g << 15) | (t << 21) | (a << 27);
}
HD inline PathContext unpack_state(unsigned s, int depth, float rayLength) {
    PathContext c;
    c.flags = s & LPF_LABEL_MASK;
    c.diffuseDepth = (unsigned short)((s >> 9) & 63u);
    c.glossyDepth = (unsigned short)((s >> 15) & 63u);
    c.transmissionDepth = (unsigned short)((s >> 21) & 63u);
    c.transparentDepth = (unsigned short)((s >> 27) & 31u);
    c.depth = (unsigned short)(depth > 0 ? depth : 0);
    c.rayLength = rayLength;
    return c;
}
// Path start (stage_init / CPU loop entry).
constexpr unsigned kInitialState = LPF_CAMERA;

// ---- Mix Shader with a Light Path Fac (closure selection) -----------------
// Mix(A, B, Fac = boolean Light Path output): Cycles weights (1-f)A + fB with
// f in {0,1}, i.e. exactly one child. Returns true when B is selected.
HD inline bool mix_selects_b(unsigned char output, const PathContext& c) {
    return light_path_output(output, c) >= 0.5f;
}
// Boolean outputs only (a fractional Ray Length Fac would need a stochastic
// closure pick; the addon reports it instead).
HD inline bool is_boolean_output(unsigned char o) {
    return o <= LPO_IS_VOLUME_SCATTER;
}

// Device side table entry, one per uploaded GMaterial (scene_upload.cu). A
// switch's own GMaterial is its emission-context leaf (child A, unwrapped), so
// every reader that does not know about switches (NEE light list, emitter
// evaluation) sees Cycles' emission-context child. aId/bId are the GMaterial
// ids of the two children (aId == own id when A is not itself a switch);
// shadowId is the leaf shadow rays see. Non-switch material: bId = -1,
// aId = shadowId = own id.
struct GLightPathSwitch {
    int aId;
    int bId;              // -1: not a switch
    int shadowId;
    int output;           // Light Path output driving Fac (Output)
};

// Surface-hit remap (GPU intersect stage): follow the switch chain from
// `matId` with context `c` to the GMaterial id the ray shades with.
HD inline int resolve_switch(const GLightPathSwitch* sw, int matId, const PathContext& c) {
    for (int k = 0; k < 8; ++k) {
        const GLightPathSwitch e = sw[matId];
        if (e.bId < 0) break;
        const int next = mix_selects_b((unsigned char)e.output, c) ? e.bId : e.aId;
        if (next == matId) break;
        matId = next;
    }
    return matId;
}

}  // namespace lightpath
}  // namespace astroray

// #991 — GPU wavefront binding (published once per frame by
// setWavefrontLightPathBinding; all-null = no Light Path in the scene, every
// reader then skips). sw[matId] is indexed by uploaded GMaterial id; `enabled`
// makes the shade / volume stages maintain GPUWavefrontState.lp_state.
// Plain POD (no member initializers: it lives in __constant__ memory).
struct GWavefrontLightPathBinding {
    const astroray::lightpath::GLightPathSwitch* sw;
    int enabled;
};
