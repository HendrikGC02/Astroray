// shade_force_inline.cuh - pkg300: include FIRST in a shade-kernel TU to
// force-inline every ASTRORAY_SHADE_NOINLINE device function (gpu_shade_noinline.h)
// of that TU into the kernel, so a __maxnreg__ budget covers the whole shade path.
// Under -rdc ptxas rejects a cap below any out-of-line callee's register count
// (gpu_closure_graph_eval_spectral is 254), and the out-of-line shadePathSlot call
// made the kernel a 40-register shell that copied ~2 KB of by-value params to the
// stack (27 % of shade stall samples; see
// .astroray_plan/docs/pkg300-shade-counter-attribution.md). Cycles compiles its
// kernels the same way: fully inlined under GPU_KERNEL_MAX_REGISTERS
// (kernel/device/cuda/config.h, Apache-2.0). Other TUs keep __noinline__.
// Full inlining doubled the shade-part build (1189 s vs ~460 s, build 7af4baa5),
// so only the HasPrincipled=false fleet kernel uses it (stage_shade_fleet_p0.cu).
// Linkage: this only changes inlining, never semantics, and with every callee
// inlined the TU emits no out-of-line copy of any external-linkage header
// function, so nvlink has no weak copy from here to choose (cuobjdump of
// stage_shade_fleet_p0.cu.obj, build 8172ffa5: the kernel, one internal-linkage
// hair helper and the compiler's div/rcp/sqrt slowpaths only).
// A project macro, never a redefinition of __noinline__: libstdc++ spells
// __attribute__((__noinline__)) (PR #1014 cuda-syntax-check, GCC 13).
// Attribute-only spelling (most sites already say `ASTRORAY_SHADE_NOINLINE inline`):
// MSVC-mode frontend -> __forceinline, GNU mode -> always_inline.
#pragma once
#if defined(_MSC_VER) && !defined(__GNUC__)
#define ASTRORAY_SHADE_NOINLINE __forceinline
#else
#define ASTRORAY_SHADE_NOINLINE __attribute__((always_inline))
#endif
