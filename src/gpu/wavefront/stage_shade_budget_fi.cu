// stage_shade_budget_fi.cu - pkg300 Phase 1 register-budget sweep, modes 2..4.
//
// Every __noinline__ device function reachable from the shade body is
// force-inlined IN THIS TU ONLY (the redefinition below precedes every project
// header; host_defines.h is already included and guarded), so __maxnreg__
// bounds the whole shade path. This is the Cycles arrangement: everything
// inlined into the kernel under GPU_KERNEL_MAX_REGISTERS 168 at 384 threads
// (kernel/device/cuda/config.h, Apache-2.0). Without it ptxas rejects the cap:
// "max regcount of 128 calls function gpu_disney_eval with regcount of 147"
// (build 98d68391; gpu_closure_graph_eval_spectral is 254). HasPrincipled=false
// fleet variant only (the pkg298 Cornell pair); other scenes use the generic kernel.
// Attribute-only spelling (no extra `inline`, which several `__noinline__ inline`
// sites already carry): MSVC-mode frontend -> __forceinline, GNU mode -> always_inline.
#include <cuda_runtime.h>
#undef __noinline__
#if defined(_MSC_VER) && !defined(__GNUC__)
#define __noinline__ __forceinline
#else
#define __noinline__ __attribute__((always_inline))
#endif
#include "stage_shade_budget.cuh"

namespace astroray::wavefront {

__global__ void stageShadeFiKernel(ASTRORAY_PKG300_SHADE_PARAMS)
{ ASTRORAY_PKG300_SHADE_BODY(shadePathSlotImpl, false) }
__global__ void __maxnreg__(168) stageShadeFi168Kernel(ASTRORAY_PKG300_SHADE_PARAMS)
{ ASTRORAY_PKG300_SHADE_BODY(shadePathSlotImpl, false) }
__global__ void __maxnreg__(128) stageShadeFi128Kernel(ASTRORAY_PKG300_SHADE_PARAMS)
{ ASTRORAY_PKG300_SHADE_BODY(shadePathSlotImpl, false) }

// mode: 2 = fully inlined, uncapped; 3 = +__maxnreg__(168); 4 = +__maxnreg__(128).
const void* stageShadeBudgetFI(int mode, bool P, bool launch,
                               int blocks, int threads, const StageShadeArgs& a)
{
    if (P) return nullptr;
    switch (mode) {
    case 2: if (launch) ASTRORAY_PKG300_LAUNCH(stageShadeFiKernel);    return (const void*)stageShadeFiKernel;
    case 3: if (launch) ASTRORAY_PKG300_LAUNCH(stageShadeFi168Kernel); return (const void*)stageShadeFi168Kernel;
    case 4: if (launch) ASTRORAY_PKG300_LAUNCH(stageShadeFi128Kernel); return (const void*)stageShadeFi128Kernel;
    default: return nullptr;
    }
}

}  // namespace astroray::wavefront
