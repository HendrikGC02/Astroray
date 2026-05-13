# CUDA Kernel Pre-warm Research (pkg84)

**Date:** 2026-05-14
**Task:** pkg84 — CUDA kernel pre-warm at viewport start
**CLAUDE.md §6 requirement:** cite published patterns for non-trivial algorithms

---

## Problem

First CUDA frame in Astroray viewport takes ~12,079 ms (RTX 5070 Ti, pkg81
measurement). Subsequent frames are ~14 ms. The gap is CUDA context init +
kernel JIT, paid once per session. User-perceived as "viewport freeze" on
first "Rendered" click.

---

## Reference Pattern

**Source:** Blender Cycles rendering engine
**License:** Apache-2.0
**Files:**
- `intern/cycles/device/cuda/device.cpp` — `reserve_local_memory()` method
- Search results: [Blender Cycles CUDA device implementation](https://github.com/wchargin/blender/blob/master/intern/cycles/device/device_cuda.cpp)
- [Cycles release announcement](https://code.blender.org/2013/08/cycles-render-engine-released-with-permissive-license/) — confirms Apache 2.0 license

**Pattern:**
1. At device initialization time (before user-triggered render), launch a
   minimal kernel with just 1 block.
2. The kernel invocation forces NVRTC / nvJitLink to compile and cache all
   kernel variants needed for the session.
3. Synchronize with `cuCtxSynchronize()` to wait for completion.
4. First "real" render now sees warm cache, avoiding the JIT latency spike.

**Cycles code excerpt** (paraphrased from search results):
```cpp
// Launch kernel, using just 1 block appears sufficient to reserve memory
// for all multiprocessors.
CUfunction kernel_func;
cuModuleGetFunction(&kernel_func, module, "path_trace_kernel");
cuLaunchKernel(kernel_func, 1, 1, 1, ...);
cuCtxSynchronize();
```

---

## Astroray Implementation

**File:** `module/blender_module.cpp` — `PyRenderer::prewarmCUDA()`
**Pattern mirrored:**
- Create a trivial scene (single grey triangle, 1-pixel camera).
- Call existing `cudaRenderer->render(...)` with 1 spp, 1 bounce.
- This invokes the full path-trace megakernel (same code path as real
  renders), forcing JIT of all SM-specific optimizations.
- Discard the result; clear the scene so subsequent `addObject` calls start
  fresh.

**Why this works:**
- CUDA kernels are JIT-compiled per (SM architecture, optimization flags,
  template parameters) tuple on first launch. The compiled binary is cached
  in the process for subsequent launches.
- By launching the kernel once during addon load / viewport init, we pay the
  JIT cost at a moment the user expects to wait (clicking "Rendered" for the
  first time) instead of mid-interaction.
- Cost is not eliminated (still ~12 s); it's moved.

---

## License Compliance

- **Cycles source:** Apache-2.0 — compatible with Astroray (same license).
- **Pattern borrowed:** general device-warm strategy (launch minimal kernel
  early). No Cycles code copied; we use our existing `cudaRenderer->render()`
  API.
- **Citation in code:** comment block in `blender_module.cpp` line 1181 cites
  `intern/cycles/device/cuda/device.cpp reserve_local_memory, Apache-2.0`.

---

## Acceptance Criteria (pkg84 spec)

- [ ] First "real" viewport frame after pre-warm shows ≤ 100 ms
      initialization cost (vs 12,079 ms pre-fix). Measured by re-running
      pkg81 harness.
- [ ] Pre-warm time itself is ~12 s (cost moved, not eliminated).
- [ ] CPU mode unchanged (no pre-warm needed).
- [ ] Idempotent (addon guards re-fire on device_mode change).

---

## Search Citations

Sources consulted per CLAUDE.md §6:

- [Cycles CUDA device implementation](https://github.com/wchargin/blender/blob/master/intern/cycles/device/device_cuda.cpp)
- [Cycles Apache 2.0 license announcement](https://code.blender.org/2013/08/cycles-render-engine-released-with-permissive-license/)
- Web search: "Blender Cycles source code Apache 2.0 license intern/cycles CUDA device initialization"
- Web search: "Cycles blender_python.cpp list_render_devices CUDA context initialization Apache 2.0"

All sources confirmed Cycles uses Apache-2.0 for the `intern/cycles/` tree.
Pattern is a standard CUDA best-practice (warm kernel cache early to avoid
user-facing JIT latency). No novel algorithm invented.
