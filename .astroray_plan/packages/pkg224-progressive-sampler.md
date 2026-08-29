# pkg224 — Progressive (Low-Discrepancy) Sampler for the GPU Wavefront

**Pillar:** 3 <!-- Rendering-quality/convergence infra: the sampler itself changes nothing users see by default (opt-in, off-by-default); it exists to unblock pkg131 (Pillar 3's zero-knob adaptive sampling). Filed under 3, not 5, because it is a core-integrator convergence primitive, not a peripheral/tooling concern. -->
**Track:** A
**Status:** open
**Estimated effort:** 2 sessions (~6 h)
**Depends on:** pkg55 (wavefront SoA refactor), pkg92 (WavefrontRNG foundation)

---

## Goal

Before: the GPU wavefront's only RNG is `WavefrontRNG` (PCG32,
`include/astroray/sampling/wavefront_rng.h` / `wavefront_rng_device.h`),
pure white noise — no prefix of N samples for a pixel is better
distributed than any other prefix. pkg131 (adaptive sampling) is blocked
on this: it needs to vary per-pixel sample counts and still get clean
convergence, which requires a sequence where *any* prefix is
well-distributed (the "progressive" property).

After: an **opt-in** progressive low-discrepancy sampler
(hash-Owen-scrambled Sobol', see
`.astroray_plan/docs/pkg224-progressive-sampler-research.md`) is
available at every wavefront RNG draw site, selected by a renderer flag.
With the flag off (the default), rendering is **byte-identical** to
today — same PCG32 stream, same fleet register footprint, same CPU/GPU
snapshot-parity gates. With the flag on, per-pixel sample sequences are
progressive: rendering N samples then M more for a pixel gives the same
result as rendering N+M in one pass, and error decreases faster than
1/√N. pkg131 can then build variable-N adaptive sampling on top without
re-solving this problem.

---

## Context

Serves Pillar 3 (rendering quality/convergence) as the direct
prerequisite for pkg131. Without it, pkg131 cannot be attempted — the
white-noise RNG makes "render fewer samples in easy regions, more in
noisy ones" produce visibly worse noise patterns than uniform sampling,
because early partial sample counts aren't representative. This has been
sitting as a hard block on pkg131 since it was scoped
(`pkg131-blocked-on-progressive-sampler`); the owner decided 2026-08-29
to unblock it rather than continue deferring pkg131.

---

## Reference

- Research note: `.astroray_plan/docs/pkg224-progressive-sampler-research.md`
  (Burley 2020 hash-Owen-Sobol' vs Christensen et al. 2018 PMJ02;
  recommends hash-Owen-Sobol').
- `include/astroray/sampling/wavefront_rng.h` /
  `wavefront_rng_device.h` — existing PCG32 sampler + citation style to
  mirror.
- `include/astroray/gpu_wavefront_state.h` — SoA layout, `rng_pixel` /
  `rng_sample` / `rng_dimension` / `rng_seed` arrays (comment block
  around line 54).
- `src/gpu/wavefront/stage_init.cu` — `WavefrontRNG rng(pixel, sample_idx,
  seed)` construction (line ~301) and the primary-ray draws that advance
  `rng_dimension` (line ~318 stores `rng.dimension()` back to the SoA).
- pkg201-S3 (`c_wfBounceLimit`), pkg186 (`c_wfTexBinding`), pkg223
  (`c_wfTexBinding` normal-map fields) — the proven pattern for adding an
  opt-in, `__constant__`-bound feature to the shade kernel without
  growing its template-instantiation axis count or its byte-identical
  default path.
- `wavefront-shade-kernels-register-saturated` — REG:254 pinned; last
  measured (pkg223 closeout, STATUS.md) as REG:254/STACK:3608/
  CONSTANT[0]:1700 at `stageShadeBucketedKernel<0,0,0,0,false>`. This
  package's probe must re-measure from the current `.pyd`, not trust this
  number.

---

## Prerequisites

- [ ] pkg55 (wavefront SoA) and pkg92 (WavefrontRNG foundation) done, tests green.
- [ ] Build passes on main.
- [ ] `cuobjdump` ground-truth CUDA-arch gate available (per
      `worktree-cmake-cuda-arch-stale-cache`) before trusting any register
      probe.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/sampling/progressive_sobol.h` | Host-side hash-Owen-scrambled Sobol' sampler: `float SobolOwenSample(uint32_t sample_index, uint32_t dimension, uint32_t scramble_seed)`. Ports pbrt-v4's `SobolMatrices32` table (or a trimmed subset covering Astroray's realistic per-bounce dimension count) + `FastOwenScrambler`, Apache-2.0, cited per CLAUDE.md §6. |
| `include/astroray/sampling/progressive_sobol_device.h` | `__device__`/`__host__` mirror, same pattern as `wavefront_rng_device.h` relative to `wavefront_rng.h`. Direction-vector table lives in `__constant__` memory (side-table, NOT a `GMaterial`/per-slot field — see Design). |
| `tests/test_pkg224_progressive_sobol.py` | Unit tests: prefix property (N-sample prefix discrepancy bound), CPU byte-parity of the ported table against a known-good reference (e.g. cross-check first K values against pbrt-v4 or a published Sobol' table), default-off byte-identical fleet render. |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/gpu_wavefront_state.h` | Add the `__constant__ c_wfSamplerBinding` (or extend an existing binding struct) declaration + `setWavefrontSamplerMode(bool useProgressive)` accessor, following the pkg201-S3/pkg186 comment style. |
| `src/gpu/wavefront/stage_advance.cu` (or wherever other `set...Binding` calls are made once per frame) | Publish the sampler-mode flag once per frame from `cuda_wavefront_render`. |
| `src/gpu/wavefront/stage_init.cu` | At `WavefrontRNG rng(...)` construction / primary-ray draw, branch on `c_wfSamplerBinding.useProgressive` to call `SobolOwenSample(sample_idx, dim, hash(pixel, dim, seed))` instead of `rng.Uniform()`. Off path is untouched code, byte-identical. |
| Wherever BSDF/NEE draws happen in the shade kernel (grep `rng.Uniform()` / `rng_uniform(rng)` across `src/gpu/wavefront/stage_shade_*.cu`) | Same opt-in branch at each draw site. **This is the register-risk site** — see Register discipline. |
| `raytracer.h` / render-settings plumbing | Add the renderer-facing flag (e.g. `use_progressive_sampler`, default `false`) that reaches `cuda_wavefront_render`. |

### Key design decisions

- **Sample function signature:** `float sample_value(pixel_index, sample_index, dimension, scene_seed)` — stateless, matching `WavefrontRNG`'s existing constructor tuple exactly. No new per-path SoA columns are needed; `rng_pixel`/`rng_sample`/`rng_dimension`/`rng_seed` already carry everything the progressive sampler needs as pure function inputs.
- **Selection mechanism:** a renderer-level opt-in flag published once per frame into a `__constant__` binding (pkg201-S3 pattern: runtime compare, not a new compile-time template axis) — NOT a new `stageShadeBucketedKernel<..., N+1>` instantiation. This avoids the kernel-explosion pkg201-S3 explicitly steered away from, and keeps the default path's codegen completely untouched (the `if (c_wfSamplerBinding.useProgressive)` branch is dead code eliminated in the off-path... in principle; the register probe in Acceptance is what actually confirms this, since NVCC does not always eliminate dead `__constant__`-gated branches for free at REG:254).
- **Direction-vector table placement:** `__constant__` memory (or a side-table read via the existing texture-binding-style pointer indirection if the table is too large for `__constant__`'s 64 KB budget — Sobol' matrices for a handful of dimensions at 32 words each are small, so plain `__constant__` should fit). Never inline into `GMaterial` or any per-slot SoA struct — matches the `wavefront-shade-kernels-register-saturated` guidance and the pkg186/pkg223 precedent.
- **`rng_dimension` mapping:** the existing live auto-incrementing `dimension_` counter in `WavefrontRNG` maps directly onto the Sobol' dimension index — no change to the counter's semantics, only to what function consumes `(sample_index, dimension_)` to produce the float when the flag is on.
- **Byte-identical default is non-negotiable:** the entire point of gating this behind an opt-in flag (rather than replacing `WavefrontRNG` outright) is that the CPU/GPU wavefront snapshot-parity harness (`src/cpu/wavefront/`, `tests/wavefront_diff/`) and the fleet register gate must see zero change with the flag off. Do not touch `WavefrontRNG::GenerateForDimension` itself; add a sibling function and a call-site branch.

---

## Acceptance criteria

- [ ] `cuobjdump` register probe on `stageShadeBucketedKernel<0,...,false-sampler-flag-path>` matches the pre-change baseline exactly (re-measure the actual current numbers from the built `.pyd`; do not assume the STATUS.md pkg223 numbers are still current) — REG/STACK/CONSTANT[0] unchanged.
- [ ] With the flag off, a fleet render (existing scene set) is byte-identical to pre-pkg224 output (hash compare, not visual compare).
- [ ] With the flag on, `tests/test_pkg224_progressive_sobol.py` demonstrates the prefix property: for a test integral with known ground truth, computing the estimate from any prefix (N, N/2, N/4, ...) of the sample sequence shows discrepancy/error consistent with Sobol'-class convergence (better than 1/√N white-noise scaling; a simple documented test integral is acceptable, does not need a formal QMC discrepancy computation).
- [ ] With the flag on, a convergence comparison (progressive vs. white-noise PCG32) on one representative test scene shows the progressive sampler's per-channel error decreasing faster with sample count than the existing PCG32 path, at matched sample counts.
- [ ] CPU/GPU snapshot-parity gate (`tests/wavefront_diff/`) passes with the flag off; with the flag on, CPU and GPU either match (if the CPU path is also ported, see Non-goals) or the flag is documented as GPU-only and excluded from that specific gate — this must be an explicit, stated decision, not a silent gap.
- [ ] pkg131's spec is updated (or a follow-up note filed) confirming its prefix-property prerequisite is now met and it is unblocked.

---

## Non-goals

- Implementing pkg131 (adaptive sampling) itself — this package delivers only the sampler primitive.
- Replacing or removing the existing PCG32 `WavefrontRNG` — it remains the default and the CPU-parity baseline.
- Porting the progressive sampler to the CPU `std::mt19937` path tracer, unless the owner picks that fork below (Real fork (c)) — CPU currently uses raw `std::mt19937` pervasively (`raytracer.h`, `spectral.h`), a large surface with no existing WavefrontRNG-style abstraction to hook into.
- PMJ02 implementation — recommended against in the research note for statelessness reasons; only revisit if the owner overrides the recommendation (Real fork (a)).

---

## Real forks for the owner

**(a) Sobol'-hash-Owen (Burley 2020) vs. PMJ02 (Christensen et al. 2018).**
Research note recommends hash-Owen-Sobol' for its fully stateless
`f(pixel, sample, dimension, seed)` form, which drops into
`WavefrontRNG`'s existing calling convention with no new per-pixel state
and a small, fixed per-draw cost. PMJ02 has excellent 2D projections but
is naturally table-generated per requested N, which either forces a
precomputed table + a separate per-pixel decorrelation seed (new state)
or loses the closed-form per-thread evaluation the wavefront model wants.
If 2D projection quality specifically (not just the prefix property)
turns out to matter more than statelessness for a target scene class,
PMJ02 is the fallback.

**(b) Opt-in runtime flag vs. a new compile-time template axis.**
Recommended: opt-in runtime flag via `__constant__` binding
(pkg201-S3/pkg186/pkg223 pattern) — keeps kernel count flat, matches
`pkg201-s3-runtime-comparison-not-axis`. A compile-time axis
(`stageShadeBucketedKernel<...,HasProgressiveSampler>`) is the fallback
only if the register probe shows the runtime branch itself spills the
REG:254 kernel even when taking the off-path — in that case isolate with
`if constexpr` the way `closure-graph-lobe-count-spills-fused-kernel` was
solved.

**(c) GPU-only first vs. CPU parity from day one.**
Recommended: GPU-only first. The CPU path tracer's RNG is raw
`std::mt19937` used directly at dozens of call sites (`raytracer.h`,
`spectral.h`) — there is no `WavefrontRNG`-equivalent abstraction on the
CPU side to swap. Porting the CPU path to a matching progressive sampler
is a materially larger, separately-scopeable package if/when CPU↔GPU
progressive-sampler parity becomes a requirement (e.g., if a future
CPU/GPU snapshot-parity gate needs to cover the progressive mode too).
Flagging this explicitly because pkg131, if it ever needs to run on CPU,
will hit this gap.

---

## Progress

- [ ] Research note filed (`pkg224-progressive-sampler-research.md`).
- [ ] Spec filed (this file).
- [ ] Register probe of current baseline (`.pyd` ground truth).
- [ ] `progressive_sobol.h` / `progressive_sobol_device.h` implemented + cited.
- [ ] Opt-in binding wired at `stage_init.cu` + shade-kernel draw sites.
- [ ] Tests: prefix property, byte-identical default, convergence comparison.
- [ ] pkg131 unblock note filed.

---

## Lessons

*(Fill in after the package is done.)*
