#pragma once
// gpu_material_class.cuh - the device material bounce class (diffuse vs glossy),
// moved verbatim out of stage_advance_device.cuh (#991) so the out-of-line Light
// Path TU (shading_inputs_eval.cu) shares the one definition with the shade kernels.
// Included INSIDE namespace astroray::wavefront by stage_advance_device.cuh.
#include "astroray/gpu_types.h"

// Device twin of the CPU Material::isGlossy() (raytracer.h:455) — base Material is
// false; Metal (plugins/materials/metal.cpp) and Principled/Disney
// (plugins/materials/principled.cpp) override to true. Used to split the
// reflection-lobe category for a non-delta, non-transmitted first bounce (diffuse
// vs glossy). CRITICAL: scene_upload.cu lowers EVERY material that produces a valid
// closure graph to GMAT_CLOSURE_GRAPH (line 112) — so a Metal is uploaded as a
// GCLOSURE_GGX_CONDUCTOR closure and a Principled as GCLOSURE_PRINCIPLED, NOT as
// GMAT_METAL/GMAT_DISNEY. Checking only those two types misses the metal (its
// glossy indirect leaks into diffuse_indirect — the pkg198-s2 parity failure). So
// also scan the closure graph: a conductor or principled closure ⇒ glossy; a
// diffuse/dielectric-transmission/thin-glass closure ⇒ not glossy (matching the CPU
// Lambertian/Dielectric isGlossy()==false). Behind `if constexpr(HasLightPassAOVs)`
// at the one call site, so the fleet <…,false> shade kernel never compiles it.
__device__ __forceinline__ bool gpu_material_is_glossy(const ::GMaterial& m) {
    if (m.type == GMAT_METAL || m.type == GMAT_DISNEY) return true;
    if (m.type == GMAT_CLOSURE_GRAPH) {
        for (int i = 0; i < (int)m.closureCount; ++i) {
            GClosureType t = m.closures[i].type;
            if (t == GCLOSURE_GGX_CONDUCTOR || t == GCLOSURE_PRINCIPLED) return true;
        }
    }
    return false;
}
