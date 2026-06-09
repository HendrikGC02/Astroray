#pragma once
// gpu_tlas_parity.h — pkg114 increment 1 test hook (pure C++; NO CUDA headers).
//
// Declares the host entry point for the two-level-BVH identity-passthrough
// parity probe. Included by the pybind translation unit (blender_module.cpp)
// which nvcc never compiles; the implementation lives in src/gpu/tlas_parity.cu.
//
// The probe builds a single IDENTITY instance (one BLAS = the whole uploaded
// scene, identity transform, a 1-leaf TLAS) and, for every primary camera ray,
// compares gpu_tlas_hit(identity) against the single-level gpu_bvh_hit. If the
// two-level plumbing is correct, the only permitted difference is a sub-ulp
// normal drift from the (no-op) inverse-transpose renormalize.

class Renderer;
class Camera;

namespace astroray {
namespace twolevel {

struct TlasParityResult {
    int   totalRays      = 0;   // width*height
    int   hitDisagree    = 0;   // rays where one path hit and the other missed
    int   fieldMismatch  = 0;   // both hit but t / primId / materialId / frontFace differ
    float maxTDelta      = 0.f; // max |t_tlas - t_ref| over agreeing hits
    float maxPointDelta  = 0.f; // max |point_tlas - point_ref|
    float maxNormalDelta = 0.f; // max |normal_tlas - normal_ref|
};

// Requires the CPU Renderer to have a built BVH (call Renderer::buildAcceleration()
// — or render once — first). Uploads the scene, runs the dual-trace probe over a
// width*height grid of primary camera rays, frees device memory, returns stats.
// Throws std::runtime_error on any CUDA failure.
TlasParityResult cuda_tlas_identity_parity(
    const Renderer& cpu, const Camera& cam, int width, int height);

}  // namespace twolevel
}  // namespace astroray
