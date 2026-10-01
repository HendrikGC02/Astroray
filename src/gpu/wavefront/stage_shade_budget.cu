// stage_shade_budget.cu - pkg300 Phase 1 register-budget sweep, mode 1.
//
// The generic stageShadeBucketedKernel calls shadePathSlot out of line (not
// inlined under -rdc), so the kernel is a 40-register shell that copies the
// ~2 KB of by-value params to the stack for the by-reference call, and a
// __launch_bounds__/__maxnreg__ on it cannot bound the 254-register body
// (pkg174's "ignored" launch bounds). Mode 1 inlines the shade body
// (shadePathSlotImpl is __forceinline__) but keeps the __noinline__ BSDF/NEE
// callees out of line, uncapped. Capped kernels live in stage_shade_budget_fi.cu:
// under -rdc ptxas rejects a cap below any out-of-line callee's regcount
// (gpu_closure_graph_eval_spectral is 254), so a cap needs every callee inlined.
// Selected at runtime by ASTRORAY_SHADE_BUDGET (sweep only; default 0 = generic).
#include "stage_shade_budget.cuh"

namespace astroray::wavefront {

template<bool P> __global__ void stageShadeInlKernel(ASTRORAY_PKG300_SHADE_PARAMS)
{ ASTRORAY_PKG300_SHADE_BODY(shadePathSlotImpl, P) }

const void* stageShadeBudgetFI(int mode, bool P, bool launch,
                               int blocks, int threads, const StageShadeArgs& a);

// mode: 1 = inline body; 2..4 = fully inlined (stage_shade_budget_fi.cu).
// Returns the kernel pointer, or nullptr when the combination has no budget
// kernel (caller falls back to the generic kernel); launch == true also launches.
const void* stageShadeBudget(int mode, bool P, bool launch,
                             int blocks, int threads, const StageShadeArgs& a)
{
    if (mode == 1) {
        if (P) { if (launch) ASTRORAY_PKG300_LAUNCH(stageShadeInlKernel<true>);  return (const void*)stageShadeInlKernel<true>; }
        else   { if (launch) ASTRORAY_PKG300_LAUNCH(stageShadeInlKernel<false>); return (const void*)stageShadeInlKernel<false>; }
    }
    return stageShadeBudgetFI(mode, P, launch, blocks, threads, a);
}

}  // namespace astroray::wavefront
