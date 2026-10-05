// shading_inputs_eval.cu - #991 / #990: the GPU per-hit shading-input services,
// out of line (Light Path state; shading attribute layers).
//
// The Light Path context of a hit, the Mix Shader closure-switch remap, the
// per-bounce path-state update and the op-VM Light Path output. The math is the
// shared host+device service in astroray/light_path.h (Cycles
// kernel/svm/light_path.h + integrator/path_state.h, Apache-2.0); the CPU calls
// the same functions inline. One external-linkage definition each (-rdc), called
// only behind the c_wfLightPath runtime flag / switch table, so the 12 shade
// part TUs and stage_advance.cu compile a call, not the body (build time), and
// the bodies' registers never enter the fleet, intersect or shadow kernels
// (pattern: proc_tex_eval.cu, #1007).
#include "astroray/light_path.h"
#include "astroray/attribute_layers.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_wavefront_state.h"

namespace astroray::wavefront {

#include "gpu_material_class.cuh"   // gpu_material_is_glossy (pkg201 bounce class)

extern __constant__ GWavefrontLightPathBinding c_wfLightPath;   // stage_advance.cu
extern __constant__ GWavefrontPrimaryClip c_wfPrimaryClip;      // stage_advance.cu

// Light Path context of the ray that produced this hit: the packed path state,
// the bounce, and the hit distance. A camera ray is measured from its near-clip
// start like Cycles (camera.h camera_sample_perspective: P += nearclip*z_inv*D);
// the CPU twin is pathTraceSpectral (raytracer.h).
__device__ __noinline__ astroray::lightpath::PathContext gpu_lpContext(
    unsigned lpState, int bounce, float t, GVec3 dir)
{
    if (bounce == 0 && c_wfPrimaryClip.active) {
        const float zInv = 1.f / fmaxf(1e-6f, dir.dot(GVec3(
            c_wfPrimaryClip.fwdX, c_wfPrimaryClip.fwdY, c_wfPrimaryClip.fwdZ)));
        t -= c_wfPrimaryClip.nearDist * zInv;
    }
    return astroray::lightpath::unpack_state(lpState, bounce, t);
}

// Intersect stage: a Mix Shader with a Light Path Fac -> the child this ray
// shades with (GLightPathSwitch chain). Reached only when c_wfLightPath.sw.
__device__ __noinline__ int gpu_lpRemap(int matId, unsigned lpState, int bounce,
                                        float t, GVec3 dir)
{
    return astroray::lightpath::resolve_switch(
        c_wfLightPath.sw, matId, gpu_lpContext(lpState, bounce, t, dir));
}

// Shade stage: Cycles path_state_next across this bounce, with the pkg201
// bounce class (CPU twin: pathTraceSpectral lobeCat) and the transparent-pass
// test (a straight-through delta sample keeps the flags).
__device__ __noinline__ unsigned gpu_lpAdvance(unsigned lpState, const ::GMaterial* mat,
                                               GVec3 wo, GVec3 n, GVec3 wi, bool isDelta)
{
    using namespace astroray::lightpath;
    const float sWo = wo.dot(n);
    const float sWi = wi.dot(n);
    const int cat = (sWo * sWi < 0.f) ? 2
                  : ((isDelta || gpu_material_is_glossy(*mat)) ? 1 : 0);
    // Transparent lobe: a Principled alpha < 1 (device twin of the CPU
    // shadowAlpha() < 1 test; gpu_nee.cuh gpu_shadowAlpha).
    const bool alphaLobe = mat->closureCount >= 1 &&
                           mat->closures[0].type == GCLOSURE_PRINCIPLED &&
                           mat->principled.alpha < 1.0f;
    return pack_state(next_surface(unpack_state(lpState, 0, 0.f), cat, isDelta,
                                   is_transparent_pass(isDelta, wo.dot(wi), alphaLobe)));
}

// Volume-scatter continuation (path_state_next LABEL_VOLUME_SCATTER).
__device__ __noinline__ unsigned gpu_lpVolume(unsigned lpState)
{
    using namespace astroray::lightpath;
    return pack_state(next_volume(unpack_state(lpState, 0, 0.f)));
}

// #990 — shading attribute layer at this hit: the uploaded triangle's three
// corner values (scene_upload.cu, [offset + 3*triIndex + k]) interpolated with
// barycentrics recomputed from the point (astroray/attribute_layers.h, the CPU
// Triangle::attributeValue twin). A non-triangle hit reads 0 (Cycles' missing
// attribute; 1 for the Attribute node's Alpha, `attrMissing`), as the CPU
// AttributeTexture does.
extern __constant__ GWavefrontTextureBinding c_wfTexBinding;   // stage_advance.cu
extern __constant__ int c_wfEmissionFlatPrims;                 // stage_advance.cu
__device__ __noinline__ GVec3 gpu_attrTexel(int texId, GVec3 point, int primId,
                                            const GPrimitive* prims, const GTriangle* tris)
{
    // Instanced (pkg114 BLAS) prims start at c_wfEmissionFlatPrims: their
    // triangles are object-space while `point` is world-space, and scene_upload
    // gives them no attribute corners -> 0 (reported host-side).
    if (primId < 0 || primId >= c_wfEmissionFlatPrims ||
        prims[primId].type != GPRIM_TRIANGLE) {
        const float m = c_wfTexBinding.textures[texId].attrMissing;
        return GVec3(m, m, m);
    }
    const int ti = prims[primId].index;
    const GVec3* c = c_wfTexBinding.texelBuf + c_wfTexBinding.textures[texId].offset + 3 * ti;
    const GTriangle& t = tris[ti];
    GVec3 out(0.f, 0.f, 0.f);
    if (!astroray::attr::interpolate_corners(t.v0, t.v1, t.v2, point, c[0], c[1], c[2], out))
        return c[0];
    return out;
}

}  // namespace astroray::wavefront

namespace astroray::lightpath {
// op-VM OP_SHADING Light Path output on the device (shader_vm.h svm_shading).
__device__ __noinline__ float light_path_output_dev(unsigned char o, const PathContext& c)
{
    return light_path_output(o, c);
}
}  // namespace astroray::lightpath
