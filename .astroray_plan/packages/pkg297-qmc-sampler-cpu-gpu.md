# pkg297 — QMC sampler for CPU and GPU (#941)

**Pillar:** 3
**Track:** A
**Status:** open
**Estimated effort:** 6 sessions (~18 h): Phase 0 1, Phase 1 2-3, Phase 2 2, Phase 3 1
**Depends on:** pkg224, pkg131, pkg294, pkg284, pkg305

---

## Goal

Before: the CPU path tracer draws every sample from `std::mt19937` (per-tile
stream, `raytracer.h` tile loop); the GPU draws PCG32 unless GPU adaptive
sampling is on, when the pkg224 Sobol' path engages. Astroray's variance x spp
stays flat from 1 to 64 spp (0.562 -> 0.568 on the pkg294 one-lamp cube) while
Cycles' falls 4.5x (0.495 -> 0.109), so at 64 spp Astroray is 5.23x noisier
although per-sample it is at 1.13x. After: one Cycles-style Sobol-Burley
sampler, a single `__host__ __device__` implementation, drives CPU, CPU
wavefront oracle and GPU wavefront through a fixed per-bounce dimension layout.
It is ON by default (this is the #858 sampler flip), means are unchanged within
MC bands, and variance x spp falls like Cycles'.

---

## Context

pkg294 Phase 0 showed that most of the equal-spp noise excess over Cycles comes
from the sampler, not from any estimator term. It is probably also a large part
of #763 (corpus scenes noisier than Cycles at equal spp). This is Pillar 3
convergence infrastructure.

**Reconciling with #858 (owner 2026-09-29: pkg224 sampler ON by default).**
Keep pkg224's primitives and plumbing, and replace its sequencing model:

- Kept: `HashHP`, `FastOwenScramble` (equal to Cycles `reversed_bit_owen`),
  `ReverseBits32`, `sobol_matrices.h`, the `c_wfSamplerMode` `__constant__`
  flag, the `__noinline__` device entry, and the adaptive round loop.
- Replaced (a): one shared shuffled index feeding a 64-dim Joe-Kuo point.
  Cycles instead gives each 1-4D dimension set its own index shuffle (padding)
  and uses only Sobol dims 0-3, which have good low-count 2D projections.
- Replaced (b): the auto-incrementing `dimension_` counter. Any branch that
  changes the draw count (RR, lobe count, NEE on/off, media) shifts every later
  dimension, so it breaks stratification across samples.
- Replaced (c): the unmasked 32-bit index loop over a 64x32 `__constant__`
  table. Divergent constant reads are the likely cause of pkg262 fork (a)
  blowing the perf ceiling (0.57-0.71 s -> 1.63 s, ceiling 1.5 s).

So AL-5 flips only the pkg86 light tree. The sampler flip is Phase 3 here.

**Amendment 2026-09-29 (`research-noise-2026-09-29.md` §4).**
- The camera group lands first, in pkg305: FILTER, LENS and HERO_LAMBDA, plus
  `sobol_burley.h`, the camera slots of `path_dimensions.h`, and an inverse-CDF
  filter table replacing rejection sampling. pkg297 extends those files per
  bounce and does not re-implement them.
- Add two gates when Phase 1 is measured:
  - equal time: relVar x wall time vs Cycles, same device class, no worse than
    the luminance gate;
  - chroma: R/B relVar must not regress from pkg305's level.
Opus 5.5 lane with Terra review; the lead runs CUDA builds.

---

## Evidence

- 2026-09-29 (pkg294 Phase 0, CPU, `pkg294-media-lamp-variance-ablation.md`):
  cube1 relVar at 64 spp is 5.23x Cycles, per-sample 1.13x; cube1v 2.24x vs
  0.74x; cube3v 1.14x vs 0.45x. Cycles N x relVar 0.495 -> 0.109 (1 -> 64 spp);
  Astroray 0.562 -> 0.568. The engine matches the numpy textbook estimator
  (0.393 vs 0.373).
- 2026-09-09 (pkg262 A/B, `pkg262-default-flip-ab-2026-09.md`): pkg224 as the
  engine default took the wavefront contact-sheet ceiling to 1.629 s (> 1.5 s)
  and the CPU-PCG vs GPU PostInit threshold gate to about 2.1e9 ULP (> 4). It
  also broke six byte-identity-pinned GPU tests. Reverted to addon-only,
  GPU+adaptive-only.
- 2026-09-29: `std::mt19937` appears in 60 files under
  `include/ src/ plugins/`. The largest are `raytracer.h` (28),
  `volume_transport.h` (9), `reservoir.h` (8), `frame_state.h` (7) and
  `spectral_path_tracer.cpp` (6).

---

## Reference

- Burley 2020, "Practical Hash-based Owen Scrambling", JCGT 9(4).
- Cycles (Apache-2.0):
  - `src/kernel/sample/sobol_burley.h`: `sobol_burley_sample_{1,2,3,4}D`,
    per-set `hash_hp_uint(dimension_set)` seed, index shuffle then
    `& sobol_index_mask`, 4x32 table, and a dim-0 fast path via
    `reverse_integer_bits`.
  - `src/kernel/sample/pattern.h`: `path_rng_*D`, and `path_rng_pixel_init`
    (`hash_iqnt2d(x, y) ^ seed`).
  - `src/kernel/types.h` `enum PathTraceDimension` (PRNG_*, PRNG_BOUNCE_NUM).
  - `src/kernel/integrator/path_state.h`: `rng_offset += PRNG_BOUNCE_NUM` per
    bounce, and a separate `shadow_path.rng_offset`.
- Christensen, Kensler, Kilpatrick 2018, "Progressive Multi-Jittered Sample
  Sequences" (PMJ02). This is the fallback only; pkg224's fork (a) rejected it
  for statelessness.
- `.astroray_plan/docs/pkg224-progressive-sampler-research.md`. Save a new note,
  `pkg297-sobol-burley-dimension-layout.md`, via `cite-algorithm` before coding.
- Code:
  - `include/astroray/sampling/progressive_sobol_device.h`,
    `wavefront_rng{,_device}.h`
  - `src/gpu/wavefront/stage_init.cu` (`WavefrontRNG rng(...)` ~l.335, hero
    lambda)
  - `include/astroray/gpu_wavefront_state.h` (`bounce[]`, `rng_*` SoA)
  - `include/raytracer.h` tile loop ~l.4935
  - `include/astroray/sampling/adaptive_sampling.h` (the half-buffer metric
    is QMC-safe)
- Memories: `wavefront-shade-kernels-register-saturated`,
  `noinline-runtime-flag-avoids-shade-spill`,
  `gpu-wavefront-nee-occlusion-deferred-stage`, `seed-zero-is-random-sentinel`,
  `adaptive-sampling-colour-blind-stop-metric`, `gpu-perf-ab-clock-drift`,
  `fix-tests-calibrated-on-broken-engine`.

---

## Prerequisites

- [ ] pkg294 Phase 1 merged (per-sample parity on the cube; otherwise the
      64-spp gate mixes estimator and sampler effects).
- [ ] pkg284 corpus v2 scenes and Cycles references on main.
- [ ] Baseline binaries kept (CPU MinGW and CUDA `build_cuda`, arch verified by
      cuobjdump) for the A/B.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/sampling/sobol_burley.h` | `__host__ __device__` Sobol-Burley `sample1D..4D(index, dimSet, pixelSeed, mask)`, a port of the Cycles functions with constants verbatim, cited. Reuses the pkg224 `HashHP`/`FastOwenScramble`/`ReverseBits32`. Table: dims 0-3 of `kSobolMatrices32`, asserted byte-equal to Cycles `sobol_burley_table`. |
| `include/astroray/sampling/path_dimensions.h` | The `enum PathDim` layout (see Key design decisions) and `kBounceStride`. It is one table shared by CPU, CPU wavefront and GPU. |
| `include/astroray/sampling/path_sampler.h` | Host `PathSampler`: holds (pixelSeed, sampleIndex, mask, rngOffset, slot cursor), with `get1D/2D/3D(PathDim)`, `beginBounce(b)` and `beginSlot(PathDim)`. It models UniformRandomBitGenerator, so `dist(gen)` inside materials maps to the next component of the current slot, and overflow goes to a hashed white-noise stream. Mode off: forwards to an internal `std::mt19937` (byte-identical). |
| `tests/test_pkg297_sobol_burley.py` | Unit: Cycles bit-exactness for known (index, set, seed) tuples; 2D stratification of every set at N = 4^k; prefix property; the mask does not change values for index < N. |
| `tests/test_pkg297_variance_slope.py` | Render-level gates: slope, means, per-sample variance, determinism (CPU; GPU leg marked `gpu`). |

### Files to modify

| File | What changes |
|---|---|
| `scripts/diagnostics/convergence_tracker.py` | Phase 0: add `--variance-slope`: across-seed relVar x N at N in {1, 4, 16, 64, 256}, Rec.709 luminance ROI (pkg294 metric), plus Cycles legs. Record the Cycles `sampling_pattern`. Update the entry in `scripts/README.md`. No new script. |
| `include/raytracer.h` | Retype `std::mt19937&` to `astroray::Rng&` (alias to `PathSampler`). Build the per-pixel sampler in the tile loop (keyed by pixel and global sample index, not by tile). Add `beginBounce`/`beginSlot` at camera, lambda, NEE, BSDF, RR and the media sites. Add the `useQmcSampler` flag. |
| `plugins/integrators/spectral_path_tracer.cpp` | Phase 1a retype; Phase 1b slot routing (camera, hero lambda, NEE, BSDF, RR, guiding). |
| `include/astroray/volume/volume_transport.h` | Phase 1a retype; Phase 1b VOL_* slot routing (distance, phase, equiangular, channel, shadow). |
| `plugins/materials/` | Phase 1a: mechanical `std::mt19937&` -> `astroray::Rng&` retype, byte-identical with mode off. |
| `plugins/integrators/` | Phase 1a: mechanical `std::mt19937&` -> `astroray::Rng&` retype, byte-identical with mode off. |
| `include/astroray/light_sampler.h` | Phase 1a: mechanical `std::mt19937&` -> `astroray::Rng&` retype, byte-identical with mode off. |
| `src/light_sampler.cpp` | Phase 1a: mechanical `std::mt19937&` -> `astroray::Rng&` retype, byte-identical with mode off. |
| `src/lights/` | Phase 1a: mechanical `std::mt19937&` -> `astroray::Rng&` retype, byte-identical with mode off. |
| `include/astroray/shapes.h` | Phase 1a: mechanical `std::mt19937&` -> `astroray::Rng&` retype, byte-identical with mode off. |
| `include/astroray/restir/` | Phase 1a: mechanical `std::mt19937&` -> `astroray::Rng&` retype, byte-identical with mode off. |
| `include/astroray/sampling/wavefront_rng.h` | In QMC mode, `Uniform()` resolves `rngOffset(bounce) + slot` through `sobol_burley.h`. The host oracle takes the same path, so the CPU/GPU threshold gate compares QMC with QMC. The PCG path stays verbatim. |
| `include/astroray/sampling/wavefront_rng_device.h` | Device mirror of the same QMC `Uniform()` path; PCG path verbatim. |
| `include/astroray/sampling/progressive_sobol_device.h` | `ProgressiveSobolSampleDevice` becomes a thin `__noinline__` shim onto `sobol_burley.h`. Drop the 64x32 `__constant__` upload in favour of a 4x32 table (512 B). |
| `src/gpu/wavefront/stage_init.cu` | Camera group slots (FILTER, LENS, HERO_LAMBDA); publish nothing per-hit. |
| `src/gpu/wavefront/stage_shade_lambertian.cu` | Draw sites via `PathDim` slots. |
| `src/gpu/wavefront/stage_volume_hetero.cu` | VOL_* slots. |
| `src/gpu/wavefront/stage_advance.cu` | `stageShadeBucketedKernel` NEE/BSDF/RR/guiding draws via `PathDim` slots; deferred-NEE shadow offset from parked bounce; publish `c_wfSamplerMode` and `c_wfSobolMask` once per frame; 4x32 table definition. |
| `module/blender_module.cpp` | Bind `set_sampler("qmc"/"white")`; keep `set_use_progressive_sampler` as an alias. |
| `blender_addon/__init__.py` | Phase 3: default QMC on, remove the pkg262 "GPU and adaptive only" gating. |
| `blender_addon/exporter.py` | Same as `__init__.py`; viewport chunks pass the global (accumulated) sample index. |

### Key design decisions

#### Dimension layout (Cycles `PathTraceDimension`, adapted)

- Each `PathDim` is a 1-4D set with its own index shuffle.
- The dimension used is `rngOffset + slot`. `rngOffset` starts at
  `kBounceStride` and adds `kBounceStride` (16) per bounce.
- Camera group (bounce 0):
  - FILTER (2D)
  - LENS (2D)
  - HERO_LAMBDA (1D)
  - Time keeps its deterministic Halton base-2 in `stage_init`.
- Per bounce:
  - TERMINATE (1D, RR)
  - LIGHT (3D: select + 2D position)
  - LIGHT_TERMINATE (1D)
  - BSDF (3D: lobe + 2D)
  - BSDF_GUIDING (2D, pkg136 guiding RIS/one-sample mix)
  - VOL_DISTANCE (1D)
  - VOL_PHASE (2D)
  - VOL_EQUIANGULAR (1D)
  - VOL_CHANNEL (1D, hero/colour channel pick)
  - VOL_SHADOW (1D, ratio tracking / transmittance)
  - SSS (2D)
  - 5 spare slots
- Shadow rays and deferred NEE derive their offset from the parked bounce depth
  (int lane 3, pkg157). They never use a running counter.
- Hero wavelength: one QMC 1D draw per path in the camera group. The other
  hero lambdas stay at a deterministic stratified offset, which also targets
  pkg294 item 6 (spectral chroma floor).
- Overflow: extra draws inside a slot (beyond 4 components) and all
  variable-count loops fall back to a hashed white-noise stream keyed by
  (pixel, sample, offset, cursor). Examples: null-collision delta tracking
  steps, ReSTIR candidates, SMS Newton restarts, closure-graph extra lobes.
  This fallback is unbiased, just not stratified.
- Photon/caustic forward passes keep their own PCG/mt19937 streams. They are
  not per-pixel sequences.

#### GPU live state (REG 254)

- No new per-hit live state. `rngOffset` is recomputed as
  `(bounce[idx] + 1) * kBounceStride` from the existing SoA `bounce[]` column.
  The slot is a compile-time constant at each call site.
- The existing `rng_dimension` column becomes the within-slot cursor in QMC
  mode.
- `sobol_index_mask` and the mode flag live in `__constant__` (pkg201-S3
  pattern). There is no new template axis.
- The Sobol body stays `__noinline__`.
- The index loop is bounded by the mask: next_pow2(max spp) - 1. The adaptive
  cap sets it; unlimited viewport uses 0xFFFFFFFF. Iterations are therefore
  about log2(spp), not 32.
- The table is 4x32 words. If Phase 2 profiling shows constant-cache
  serialisation, read it through `__ldg`/shared memory instead.

#### Seeds and determinism

- `pixelSeed = HashHP(pixel ^ seed_lo ^ seed_hi)`, as in pkg224 (Cycles uses
  `hash_iqnt2d(x, y) ^ seed`).
- Seed 0 stays the random sentinel. It is drawn once per render (not per tile)
  and folded into `pixelSeed`.
- A fixed seed gives byte-identical CPU output across runs and OpenMP schedules
  (per-pixel keying removes today's tile dependence).
- A different seed gives an independent Owen randomisation, which is what makes
  the across-seed variance metric valid.

#### Adaptive and viewport

- pkg131's half-buffer (even/odd) convergence metric is valid under randomised
  QMC. Per-pixel within-sample variance is not, and must not be introduced.
- Adaptive stop steps (every 16th sample past the floor) sit on Sobol
  power-of-two boundaries.
- Viewport chunks must continue the global sample index (chunk k starts at the
  accumulated spp). Phase 0 checks whether chunks restart at 0 today.
- Navigation resets reset the index to 0.

#### Phase 0: measurement

- Run `convergence_tracker.py --variance-slope` on the pkg294 cube1, cube1v and
  cube3v scenes and on corpus v2 `v2_light_tree`, `v2_media` and
  `v2_dispersion_caustics`.
- Legs: CPU mt19937; GPU PCG32; GPU pkg224-on (its slope, to confirm the
  replace-not-extend call); Cycles default and Cycles `SOBOL_BURLEY`.
- Record per-sample relVar, the N x relVar slope and wall time.
- Commit the table to `.astroray_plan/docs/pkg297-phase0-variance-slope.md`.
  It needs no engine change.

#### Phase 1: CPU

- 1a: the mechanical retype, mode off. Fleet hash compare must be
  byte-identical.
- 1b: `sobol_burley.h`, `path_dimensions.h` and slot routing, with the flag
  default off.
- Gates are measured with the flag on.

#### Phase 2: GPU and wavefront oracle

- Same layout on the GPU and in the host `wavefront_rng.h`. Re-pin the
  threshold gate for QMC vs QMC.
- Register and perf probes run against the baseline binary.

#### Phase 3: default flip

- `useQmcSampler = true` in the engine, the addon and `settings_map.py`.
- Remove the pkg262 gating.
- Re-pin tests calibrated on PCG/mt19937 byte streams in the same PR
  (`fix-tests-calibrated-on-broken-engine`). Update the pkg224 and pkg262
  status lines.

---

## Acceptance criteria

- [ ] Means: every ROI has |z| <= 3 (QMC vs baseline, pkg294 z-metric) on the
      pkg294 cubes and on all corpus v2 scenes, CPU and GPU. The white furnace
      and energy-conservation suites stay green. The full CPU suite and the RTX
      sweep (no `-x`) show no new failure attributable against a baseline build.
- [ ] Variance slope: on cube1 at 64 spp (luminance), CPU relVar is <= 1.2x
      Cycles (was 5.23x) and GPU relVar is <= 1.2x Cycles. Sampler-only
      check: Astroray (N x relVar)(64)/(N x relVar)(1) <= 1.2 x Cycles' ratio
      (0.22), on CPU and GPU.
- [ ] corpus v2: N x relVar at 64 spp is no worse than baseline in any ROI, and
      the median ROI improves by at least 1.5x.
- [ ] Per-sample: 1-spp relVar with QMC is <= 1.05x the mt19937/PCG value
      (12 seeds, 95 % CI) on every Phase 0 scene.
- [ ] Determinism: a fixed seed gives byte-identical CPU renders across two
      runs and OMP_NUM_THREADS in {1, 8}. Seed 0 gives two different renders.
- [ ] GPU registers: cuobjdump shows REG <= 254 on 128/128 fleet shade
      instantiations, with sm_120 verified embedded. The pkg224 off-path probe
      is superseded, and the new numbers go in STATUS.md.
- [ ] Perf: wall time is <= 5 % over baseline (min-of-3, burn-in) on cube1v
      and on `v2_light_tree` at 256 spp, CPU and GPU. The pkg55 contact-sheet
      ceiling stays <= 1.5 s.
- [ ] Structure: the CPU wavefront oracle and the GPU share one
      `sobol_burley.h`. The CPU/GPU PostInit threshold gate holds at ULP <= 4
      with QMC on both sides.
- [ ] Visual: before/after 64-spp crops of cube1 and `v2_media` are inspected by
      Opus or Astra, with no structured (correlated) patterns.

---

## Non-goals

- Do not implement blue-noise screen-space dithering (Cycles
  `BLUE_NOISE_*`). If Phase 0 shows Cycles' default pattern differs from
  Sobol-Burley in per-pixel variance, file it as a follow-up.
- Do not use PMJ02 or tabulated Sobol, unless Phase 1 shows Sobol-Burley
  2D projections fail the stratification test.
- Do not change estimators, MIS or light selection (pkg294/pkg86). Do not
  change the photon/caustic forward passes or the ReSTIR candidate streams.
- Do not add a new template axis to the shade kernels.

---

## Progress

- [ ] Phase 0: variance-slope harness and table (CPU, GPU PCG, GPU pkg224, Cycles x2)
- [ ] Research note via cite-algorithm (Sobol-Burley and the dimension layout)
- [ ] Phase 1a: `Rng` retype, byte-identical
- [ ] Phase 1b: CPU Sobol-Burley and slots, gates
- [ ] Phase 2: GPU and wavefront oracle, REG/perf probes
- [ ] Phase 3: default flip, re-pins, pkg224/pkg262 status update

---

## Lessons

*(Fill in after the package is done.)*
