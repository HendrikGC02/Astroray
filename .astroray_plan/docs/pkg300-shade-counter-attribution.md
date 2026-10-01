# pkg300 Phase 0: shade-kernel counter attribution

Date: 2026-10-02. Build: `Astroray-aq-nodes2/build_cuda` (C++ = main ff7e1438), sm_120,
CUDA 12.8, RTX 5070 Ti, driver 617.14. Tool: Nsight Compute 2025.1.0, `--set full`,
first 3 launches of `stageShadeBucketedKernel` (bounces 0 to 2), pkg298 Cornell pair at
1024², 1 spp, depth 8, OptiX traversal. Both scenes hit the fleet variant
`<0,0,0,0,0,0,0>` (Lambertian walls + emissive quad).

## Counter table (launch 0 = bounce 0, 1 M paths)

| Metric | simple | heavy (2 M tris) |
|---|---|---|
| Duration (bounce 0 / 1 / 2) | 9.85 / 8.47 / 7.49 ms | 9.53 / 8.12 / 7.37 ms |
| Registers / thread, stack | 254, 3776 B | 254, 3776 B |
| Occupancy theoretical / achieved | 16.7 % / 16.5 % (8 warps/SM) | 16.7 % / 16.4 % |
| SM throughput / memory throughput | 8.2 % / 48.0 % | 8.5 % / 48.9 % |
| IPC (per SM) | 0.245 | 0.253 |
| Branch uniformity / active threads per warp | 98.7 % / 31.6 | 98.5 % / 30.8 |
| Local load / store sectors | 64.4 M / 187.1 M | 64.4 M / 187.1 M |
| Global load / store sectors | 68.5 M / 28.3 M | 66.0 M / 25.4 M |
| L1 / L2 hit rate | 42 % / 90 % | 41 % / 90 % |
| Top stalls (cycles per issued instr) | long_scoreboard 12.7, lg_throttle 9.1, no_instruction 5.0, wait 3.2 | long_scoreboard 12.5, lg_throttle 8.9, no_instruction 4.1, wait 3.2 |

Local memory is 72 % of all L1 sector traffic (8.0 GB per bounce-0 launch, against
3.1 GB of global). Stores outnumber loads 3 to 1, which is the signature of stack
materialisation, not of classic spill/reload.

## Source attribution (PC sampling, SASS level)

PCs were grouped into code regions and matched to `cuobjdump -sass` function
prologues. Share of warp-stall samples / share of executed warp instructions,
simple scene (heavy within 1 %):

| Region | Samples | Instructions | What it is |
|---|---|---|---|
| Kernel shell (`stageShadeBucketedKernel`, 4.7 KB) | **27.2 %** (21.1 % on `STL`) | 12.1 % | Copies the by-value kernel params (`GPUWavefrontState`, `GPUWavefrontHitBuffers`, ~2 KB) to the stack so `shadePathSlot` can take them by reference. About 500 `STL` per warp per launch. |
| `shadePathSlot` + inlined body (601 KB, frame 0x5c0) | 37.1 % (11.9 % on `STL`) | 23.2 % | The shade body. Out of line under `-rdc`, so it is an ABI call. |
| `gpu_jhEvalSpectrum` region | 14.2 % | **54.1 %** | Jakob-Hanika RGB-to-spectrum lookup. A linear search over the 64-entry scale axis runs about 39 iterations per call, and the lookup repeats once per wavelength. |
| Other noinline callees (166 KB, frame 0x440) | 9.1 % | 10.7 % | NEE/BSDF helpers. |

By opcode, `STL` is 7.1 % of instructions but **36.7 % of stall samples**. Generic
`LD` (pointer-to-stack reads) is 7.1 %. `R2UR` is 14.3 %.

## Why `__launch_bounds__(256,2)` was "ignored" (pkg174)

In the relocatable object (`stage_shade_part0.cu.obj`), every shade kernel is
**REG 40, STACK 0**. The 254 registers belong to the out-of-line `shadePathSlot`
callee. `nvlink` reports the kernel at the call graph's maximum. A kernel-level
`__launch_bounds__` or `__maxnreg__` limits only the 40-register shell, so it cannot
move the 254. Phase 1 therefore inlines the body into budgeted kernels
(`stage_shade_budget.cu`) and keeps a call-path control kernel to confirm this.

## Conclusions and phase order

- **Divergence is not the bottleneck.** Branch uniformity is 98.5 % and warps run
  with 31.5 of 32 threads active, because the 7-type bucketing already works. The
  Phase 2 sort key is low priority.
- **Local-memory traffic dominates.** `STL` and `lg_throttle` account for over a
  third of stall samples, and occupancy is pinned at 8 warps/SM by 254 registers.
  **Phase 1 goes first**, per the spec rule.
- The largest single item is not register spill. It is the ABI by-reference copy of
  the kernel params (27 % of samples). Inlining the body removes it as a side effect.
- **Follow-up, outside pkg300 scope:** `gpu_jhLookupCoeffs` is 54 % of shade
  instructions. A binary search on the scale axis (as in the rgb2spec reference,
  `rgb2spec_find_interval`) plus one coefficient lookup per RGB instead of one per λ
  would return bit-identical coefficients for a fraction of the cost. This is filed as
  a separate package, not mixed into this diff.

## CUDA 13 A/B (Phase 0b)

Not run. Only CUDA 12.6 and 12.8 are installed, and installing 13.x was not
authorised for this lane. The build embeds no PTX (`cuobjdump -lptx` finds none), so a driver-JIT proxy A/B is not possible without a rebuild.
This is an owner follow-up: install CUDA 13.x and run one AOT `sm_120` rebuild.
