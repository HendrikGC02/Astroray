#pragma once
// optix_internal.h — pkg299 private OptiX host header, shared by optix_accel.cu
// and optix_pipeline.cpp only.
//
// The OptiX denoiser (plugins/passes/optix_denoiser.cpp) already defines the
// default OptiX function table and the extern "C" stubs in the same .pyd. The
// traversal code keeps its own table under a distinct symbol and uses
// OPTIX_ENABLE_SDK_MIXING, which makes the optix_stubs.h wrappers `static`, so
// neither TU sees the other's definitions (NVIDIA OptiX 9.1 optix_stubs.h
// "Mixing multiple SDKs" note).

#ifndef NOMINMAX
#define NOMINMAX 1
#endif
#define OPTIX_ENABLE_SDK_MIXING 1
#include <optix_function_table.h>
#undef  OPTIX_FUNCTION_TABLE_SYMBOL
#define OPTIX_FUNCTION_TABLE_SYMBOL g_astrorayOptixTraversalFunctionTable
// optix_host.h directly (not optix.h): under nvcc optix.h selects the device
// header, and optix_accel.cu needs the host API.
#include <optix_host.h>
#include <optix_stubs.h>

#include <stdexcept>
#include <string>

namespace astroray {
namespace optix_trav {

// Context on the current CUDA primary context; nullptr when OptiX is unusable.
OptixDeviceContext context();
// Publish the traversable root the launches trace against (optix_accel.cu).
void setRoot(unsigned long long handle, int isIas);

}  // namespace optix_trav
}  // namespace astroray

#define ASTRORAY_OPTIX_TRAV_CHECK(expr) do {                                       \
        OptixResult _r = (expr);                                                   \
        if (_r != OPTIX_SUCCESS)                                                   \
            throw std::runtime_error(std::string("[pkg299 OptiX] " #expr " -> ") + \
                                     optixGetErrorName(_r));                       \
    } while (0)

#define ASTRORAY_OPTIX_TRAV_CUDA(expr) do {                                        \
        cudaError_t _e = (expr);                                                   \
        if (_e != cudaSuccess)                                                     \
            throw std::runtime_error(std::string("[pkg299 CUDA] " #expr " -> ") +  \
                                     cudaGetErrorString(_e));                      \
    } while (0)
