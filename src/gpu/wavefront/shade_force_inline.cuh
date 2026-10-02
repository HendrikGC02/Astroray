// shade_force_inline.cuh - pkg300: include FIRST in a shade-kernel TU to
// force-inline every __noinline__ device function of that TU into the kernel,
// so a __maxnreg__ budget covers the whole shade path. Under -rdc ptxas rejects a cap below any out-of-line callee's
// register count (gpu_closure_graph_eval_spectral is 254), and the out-of-line
// shadePathSlot call made the kernel a 40-register shell that copied ~2 KB of
// by-value params to the stack (27 % of shade stall samples; see
// .astroray_plan/docs/pkg300-shade-counter-attribution.md). Cycles compiles its
// kernels the same way: fully inlined under GPU_KERNEL_MAX_REGISTERS
// (kernel/device/cuda/config.h, Apache-2.0). Other TUs keep __noinline__.
// Full inlining doubled the shade-part build (1189 s vs ~460 s, build 7af4baa5),
// so only the two fleet-kernel TUs use it (stage_shade_fleet_p<P>.cu).
// ASTRORAY_SHADE_ALWAYS_INLINE also forces plain-`inline` helpers the compiler
// would keep out of line (gpu_pr_evalLobe, 141 regs: ptxas rejects the cap).
// Attribute-only spelling (several sites already say `__noinline__ inline`):
// MSVC-mode frontend -> __forceinline, GNU mode -> always_inline.
#pragma once
#include <cuda_runtime.h>
#undef __noinline__
#if defined(_MSC_VER) && !defined(__GNUC__)
#define __noinline__ __forceinline
#else
#define __noinline__ __attribute__((always_inline))
#endif
#define ASTRORAY_SHADE_FORCE_INLINE 1
#define ASTRORAY_SHADE_ALWAYS_INLINE __noinline__
