# pkg300 — Shade-kernel diet: counter attribution, register budget, scene specialisation

**Pillar:** 3
**Track:** A
**Status:** in-progress — Phases 0-1 done (PR #1014, 2026-10-02: Cornell simple 13.43 s -> 4.72 s 2.85x, heavy 15.00 s -> 5.89 s 2.55x, build 1.1x; JH bisection PR #1013 1.11x/1.13x); Phase 2 scene specialisation open
**Estimated effort:** 6 sessions (~18 h) for Phases 0 to 2; Phase 3 TBD (speculative)
**Depends on:** pkg298, pkg174, pkg155

---

## Goal

Before this package, `stageShadeBucketedKernel` takes 71 % of GPU time on a
12-triangle Cornell. Every one of its 128 template variants is at REG 254 with
3.8 to 8.7 KB of stack. Every scene pays for the full light-tree NEE and the 7-way
spectral BSDF union, whatever it contains.

After this package:

- shade cost is attributed with hardware counters;
- the kernel runs under a measured register budget;
- the kernel is specialised on what the scene actually contains: light count and
  types, the material-type mask, and the closure opcodes;
- specialised output is bit-equivalent to the generic kernel;
- the simple Cornell renders at least 2× faster.

---

## Context

This is the research doc's item #3 and roadmap phase P2. Here is the largest remaining
factor, and the one Cycles-parity depends on. On the simple scene Astroray is 3.4×
slower than Cycles, even though traversal is nearly free.

pkg174 closed the micro-lever avenue and showed that a naive stage split is
net-negative: NEE and BSDF each want about 160 registers on a 95-register base. It
did not try scene specialisation, a Cycles-style budget (384 threads, 168 registers),
`__maxnreg__`, or counter-guided attribution; counters were unavailable.

The 2026-05 lean megakernel ran this workload about 13× faster than today, which is
the existence proof. The package is perf-only and correctness-frozen.

---

## Evidence

- 2026-09-29, profile at 512², 64 spp: shade 71 % (cornell_diffuse) and 72 % (glass),
  254 registers, 1 block per SM.
- 2026-09-29, `cuobjdump` on the main build: 128 shade variants, all at REG 254, with
  STACK 3768 to 8696 B.
- 2026-09-29: `ncu` fails with `ERR_NVGPUCTRPERM`, the same as on 2026-08-08.
- 2026-08-08, `pkg174-register-pressure-ledger.md`: with NEE and BSDF both removed,
  REG is 95; with either one present, it is 254.
- 2026-07-25, `pkg155-phase1-profile-findings.md`: the Phase-A megakernel took
  20.3 ms against 98 ms for the wavefront, on cornell_diffuse at 256², 64 spp.
- Cycles `kernel/device/cuda/config.h` for sm_7x/8x/12x:
  `GPU_KERNEL_BLOCK_NUM_THREADS 384` and `GPU_KERNEL_MAX_REGISTERS 168`, applied via
  `__launch_bounds__`.

---

## Reference

- Design doc: `.astroray_plan/docs/research-performance-2026-09-29.md §1.2–1.4, §3 item 3, §5 bet 1`
- `.astroray_plan/docs/pkg174-register-pressure-ledger.md`,
  `pkg174-stage-split-design.md`, `pkg174-per-material-kernel-dispatch-design.md`.
- Cycles `kernel/device/cuda/config.h`, `kernel/svm/svm.h` (`KERNEL_FEATURE_NODE_*`
  masks) and `integrator/shade_surface.h` (Apache-2.0).
- Laine, Karras, Aila, "Megakernels Considered Harmful", HPG 2013.
- Dr.Jit (Jakob et al. 2022, BSD-3) for Phase 3 JIT caching.
- Memory:
  - `wavefront-shade-kernels-register-saturated`;
  - `noinline-runtime-flag-avoids-shade-spill`;
  - `shade-axis-side-table-avoids-spill`;
  - `gpu-perf-ab-clock-drift`.

---

## Prerequisites

- [ ] pkg298 harness landed.
- [ ] **Owner action:** GPU performance counters are enabled for non-admin users
      (NVIDIA App or Control Panel > Developer > Manage GPU Performance Counters).
      Phase 0 cannot run without it.
- [ ] The lead runs builds; lanes report expected register impact (lane rule 13).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `.astroray_plan/docs/pkg300-shade-counter-attribution.md` | Phase 0 Nsight Compute report: spill traffic vs latency vs divergence, per variant |
| `tests/test_pkg300_specialized_equivalence.py` | Fixed-seed specialised vs generic kernel, max abs diff ≤ 1e-5, over corpus-v2 scenes + the harness pair |

### Files to modify

| File | What changes |
|---|---|
| `src/gpu/wavefront/stage_advance.cu` | Register budget attribute (`__maxnreg__` / `__launch_bounds__`) on the shade kernel; new specialisation axes; dispatch table |
| `src/gpu/wavefront/gpu_wavefront_snapshot.cu` | Host-side scene feature mask (light count and types, material-type mask) chooses the variant; launch block size per budget |
| `include/astroray/gpu_materials.h` | Guard BSDF union cases behind the material-type mask axis |
| `src/gpu/gpu_nee.cuh` | Light-count fast path (skip light-tree descent at ≤ N lights), selected by an axis, not a runtime branch |
| `CMakeLists.txt` | Phase 0b CUDA 13.x toolkit A/B build option (ptxas quality on sm_120) |

### Key design decisions

#### Phase 0: attribute (no code changes)

Nsight Compute on the shade kernel, for the simple and heavy harness scenes:

- local-memory load/store bytes, warp stall reasons, achieved occupancy;
- branch efficiency per material bucket;
- source-level hot spots.

0b is a single rebuild with the CUDA 13.x toolkit, measuring AOT sm_120 against 12.8
(pkg155 found driver-JIT PTX beat AOT 12.8 by 1.7×). The findings decide the order of
Phases 1 and 2. If spill traffic dominates, Phase 1 comes first. If divergence
dominates, the Phase 2 sort key comes first.

#### Phase 1: register budget sweep

Measure {256 × 254 today, 256 × 128, 384 × 168 as in Cycles, 512 × 128} with
`__maxnreg__` (CUDA ≥ 12.4) on the shade kernel only.

- Verify the budget took effect with `cuobjdump`. pkg174 saw
  `__launch_bounds__(256,2)` ignored; find out why before trusting any number.
- Adopt the best min-of-5 configuration only if it is ≥ 5 % faster on both harness
  scenes.

#### Phase 2: scene specialisation and sort key

- **Specialisation axes.** The existing `template<bool ...>` axes pattern is extended
  with:
  - `LightMode` ∈ {single, few-list, tree}, mapped to the existing NEE functions
    (no new estimator);
  - a material-type mask, bucketed into 3 or 4 families to bound the variant count.
- **Compile-time budget.** Variant explosion is capped against `stage_advance.cu`
  compile time. The lead measures it, and the cap is ≤ +30 % build time.
- **Sort key.** Refine the bucket from 7 material types to (type, closure program id)
  where the queue is large, as in Cycles' shader sort.
- **Correctness.** Specialisation removes dead code only. Any output difference
  above 1e-5 is a bug, not a tolerance to widen.

#### Phase 3 (speculative, owner-gated): NVRTC scene-JIT

- Compile the scene's op-VM / closure programs to native code, cached on disk by
  (feature hash, build id).
- The generic kernel renders until the JIT kernel is ready.
- Only start if Phase 2 shows ≥ 1.5× from specialisation. The research doc §5 bet 1
  lists the risks.

---

## Acceptance criteria

- [ ] Phase 0 report committed, with counter tables for both scenes and the CUDA 13
      A/B number.
- [ ] Simple Cornell 1024², 256 spp (pkg298 harness): **≤ 8 s** (from 16.5 s,
      ≥ 2×), min-of-5 after burn-in.
- [ ] Heavy Cornell: **≤ 10 s** with pkg299 landed, or a ≥ 25 % shade-time cut
      without it.
- [ ] `test_pkg300_specialized_equivalence.py` passes: specialised == generic within
      1e-5 on every tested scene.
- [ ] pkg284 corpus-v2 bands green on GPU. Full RTX `pytest -m gpu` sweep and CPU
      suite green.
- [ ] Build time of `stage_advance.cu` ≤ 1.3× the base, as measured by the lead.

---

## Non-goals

- Do not change any estimator, sampler, BSDF or light-selection maths. Specialisation
  selects existing code paths only.
- Do not reduce spectral samples or precision (fp16, fewer λ). That needs a separate
  owner decision.
- Do not split NEE out into its own stage. pkg174 measured it net-negative.

---

## Progress

- [x] Phase 0: counters (CUDA 13 A/B not run: toolkit not installed, owner follow-up)
- [x] Phase 1: register budget sweep (fleet kernels; see pkg300-shade-counter-attribution.md)
- [ ] Phase 2: specialisation axes + sort key
- [ ] Phase 3: owner decision on NVRTC scene-JIT

---

## Lessons

*(Fill in after the package is done.)*
