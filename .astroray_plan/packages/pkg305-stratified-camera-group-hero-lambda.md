# pkg305 — Stratified camera group: hero wavelength, pixel filter and lens (pkg297 slice 1)

**Pillar:** 3
**Track:** A
**Status:** done — PR #1003, 2026-09-30: sky R/B relVar 1.9e-3/2.6e-3 -> 2.4e-5/3.7e-5 (CPU+GPU), sky_sun bulk 190x -> 4.2x Cycles, cost 0 %, shade REG unchanged
**Estimated effort:** 2 sessions (~6 h): CPU 1, GPU + gates 1
**Depends on:** pkg224, pkg284

---

## Goal

Before:
- Every pixel sample draws its hero-wavelength uniform, its 2D filter offset and
  its 2D lens position from white noise: `std::mt19937` on the CPU, PCG32 on the
  GPU unless adaptive sampling is on.
- Astroray therefore shows a spectral colour floor wherever Cycles' pixel is
  deterministic: sky, world background, directly seen emitters and flat albedo.
  Examples: sky R/B relVar 0.0024/0.0026 at 64 spp vs Cycles 0; `v2_sky_sun` bulk
  luminance variance 190x Cycles.
- Anti-aliasing and depth of field converge at the white-noise rate.

After:
- These five dimensions come from Cycles-style Sobol-Burley. Each 1-2D set gets
  its own index shuffle, keyed by (pixel, global sample index, seed), on CPU and
  GPU through one `__host__ __device__` implementation.
- The rest of the path keeps today's RNG.
- This is slice 1 of pkg297. pkg297 extends the same files per bounce.

---

## Context

`research-noise-2026-09-29.md` M1 found the spectral floor is the hero sampler's
white noise, not the 4-lane estimator.
- A numpy model of `sampleImportance` reproduces the measured sky noise.
- Stratifying the single hero uniform across a pixel's samples removes about
  75x of it at 64 spp.

Why split this out of pkg297:
- It is a one-draw change before the path starts.
- It needs no `Rng` retype, and adds no shade-kernel live state (REG 254).
- It ships the most visible win on its own, weeks ahead of the per-bounce layout.

Opus 5.5 lane with Terra review; the lead runs CUDA builds.

---

## Evidence

- 2026-09-29 (`research-noise-2026-09-29.md` §1; `astra_run\RS\rs-noise\lam.py`):
  - Model, 64 spp, blue-sky SPD: R/G/B relVar 0.0021 / 0.00029 / 0.0034 iid.
    Stratified, the same is 2.8e-5 / 4e-6 / 5.3e-5.
  - Measured `v2_sky_sun` sky ROI: 0.0024 / 0.00018 / 0.0026. Cycles: 0 / 0 / 0.
- 2026-09-29: Cycles `TABULATED_SOBOL` and `AUTOMATIC` (blue noise) have the same
  per-pixel variance (0.92-0.98x). So the gain comes from per-pixel
  stratification, and dithering is not needed.
- 2026-09-29: Cycles N x relVar from 4 to 64 spp falls to 0.24-0.71. Astroray's
  stays at 0.96-1.05 (`slope.py`, 4 scenes).
- Draw sites:
  - `plugins/integrators/spectral_path_tracer.cpp:238-241` (hero `dist01(gen)`)
  - `include/raytracer.h:5006-5007` (filter)
  - `raytracer.h:2211` (lens, `Camera::getRay`)
  - `raytracer.h:3263-3290` (filter; Blackman-Harris/Gaussian use rejection or
    Box-Muller, with a variable draw count)
  - `src/gpu/wavefront/stage_init.cu:77-114` (filter), `:305` (hero), lens in
    the camera ray

---

## Reference

- Burley 2020, "Practical Hash-based Owen Scrambling", JCGT 9(4).
- Cycles (Apache-2.0):
  - `kernel/sample/sobol_burley.h`
  - `kernel/sample/pattern.h` (`path_rng_1D/2D`, `path_rng_pixel_init`)
  - `kernel/types.h` `PRNG_FILTER`, `PRNG_LENS_TIME`
  - Filter table: separable inverse-CDF filter importance sampling, not
    rejection. The host builds it in `scene/film.cpp` (`filter_table`); the
    kernel reads it with `lookup_table_read` in `kernel/camera/camera.h`
    (`filter_table_sample`). Verify the file locations on current main before
    porting.
- pbrt-v4 `SampledWavelengths::SampleVisible` (already ported, pkg206). It stays
  as is; only its input uniform changes.
- pkg297 spec (dimension layout, seeds and determinism, adaptive/viewport rules):
  follow it exactly for the camera group.
- `.astroray_plan/docs/pkg224-progressive-sampler-research.md`.
- Memories: `seed-zero-is-random-sentinel`, `gpu-perf-ab-clock-drift`,
  `fix-tests-calibrated-on-broken-engine`, `wavefront-shade-kernels-register-saturated`.

---

## Prerequisites

- [ ] Baseline CPU and CUDA binaries kept for the A/B (sm_120 verified by cuobjdump).
- [ ] Corpus v2 seed renders available (`astra_run\AK\ak-284b\work{,2}`) or re-rendered.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/sampling/sobol_burley.h` | pkg297's file: `__host__ __device__` `sample1D/2D(index, dimSet, pixelSeed, mask)`, a cited Cycles port reusing pkg224 `HashHP`/`FastOwenScramble`/`ReverseBits32`, with a 4x32 table |
| `include/astroray/sampling/path_dimensions.h` | pkg297's file, camera group only here: `FILTER` (2D), `LENS` (2D), `HERO_LAMBDA` (1D). The per-bounce entries are added by pkg297 |
| `include/astroray/sampling/filter_table.h` | Separable inverse-CDF table for Box/Gaussian/Blackman-Harris (Cycles `filter_table` port); one 2D uniform in, one offset out; host + device |
| `tests/test_pkg305_camera_group.py` | Cycles bit-exactness of `sobol_burley` tuples; filter-table distribution equals the analytic filter (chi2); chroma and slope gates below |

### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` | Tile loop: build `pixelSeed` per pixel (global sample index, not tile), draw FILTER and LENS from `sobol_burley.h`, pass `lambdaU` to the integrator; `filterSample` uses the table; `useStratifiedCamera` flag (default on after gates) |
| `plugins/integrators/spectral_path_tracer.cpp` | Hero draw takes the supplied `lambdaU` instead of `dist01(gen)` |
| `plugins/integrators/multiwavelength_path_tracer.cpp` | Same hero input, if it draws its own |
| `src/gpu/wavefront/stage_init.cu` | FILTER/LENS/HERO_LAMBDA via `sobol_burley.h`; filter via the table; PCG stream unchanged for later dims |
| `include/astroray/sampling/progressive_sobol_device.h` | pkg224 path unchanged; document precedence (camera group always stratified) |
| `module/blender_module.cpp` | Bind `set_stratified_camera(bool)` |
| `.astroray_plan/packages/pkg297-qmc-sampler-cpu-gpu.md` | Note that the camera group, `sobol_burley.h` and the filter table landed here |

### Key design decisions

- **Scope.** Camera group only. All later draws keep today's streams.
  - The CPU mt19937 stream loses the draws the camera group now takes, so byte
    streams change. Re-pin byte-identity tests in the same PR, with the reason
    in the commit.
  - Means must not move.
- **Seeds.** As pkg297:
  - `pixelSeed = HashHP(pixel ^ seed_lo ^ seed_hi)`.
  - Seed 0 is drawn once per render.
  - The sample index is global, so viewport chunks continue it.
- **Mask.** The mask is `next_pow2(maxSpp) - 1`, so the index loop runs about
  log2(spp) iterations. Unlimited viewport uses the full mask.
- **Filter.** Rejection sampling cannot take a fixed 2D QMC input. Port Cycles'
  table; its tail truncation must match Cycles' width semantics (pkg203).
- **Integrator API.** `sampleFull(const Ray&, std::mt19937&)` has no slot for
  `lambdaU`. Add the smallest carrier: a defaulted parameter or a per-call context
  struct. Sweep every `Integrator` override and every test/mock caller (CLAUDE.md
  "Before you push"). Integrators that ignore it keep their behaviour.
- **Time.** Time keeps its Halton base 2. Adding it to the camera group is pkg297's call.
- **GPU registers.** All work is in `stage_init.cu`; nothing new is live in
  the shade kernel. Report cuobjdump REG for `stage_init` and the shade
  instantiations.

---

## Acceptance criteria

- [ ] Chroma floor. On the `v2_sky_sun` sky ROI at 64 spp (5 seeds, CPU and GPU),
      R and B relVar are ≤ 2.4e-4 each (from 0.0024 / 0.0026).
- [ ] Bulk luminance. The `v2_sky_sun` per-pixel median ratio vs Cycles is ≤ 5
      (from 190). `v2_camera_geometry` world-background ROI chroma ratio falls
      ≥ 10x.
- [ ] Means. Every corpus v2 ROI has |z| ≤ 3 against the baseline, CPU and GPU.
      The white-furnace and energy suites stay green. The full CPU suite and the
      RTX sweep (no `-x`) show no new failure attributable against a baseline build.
- [ ] Filter. A chi2 test of the table sampler against the analytic
      Box/Gaussian/Blackman-Harris profile passes. Edge-AA ROI (`v2_camera_geometry`
      ortho) N x relVar at 64 spp is ≤ 0.8x baseline.
- [ ] Determinism. A fixed seed is byte-identical across two runs and across
      `OMP_NUM_THREADS` 1 and 8. Seed 0 gives different renders.
- [ ] Cost. Wall time is ≤ 3 % over baseline (min-of-3, burn-in) on
      `v2_light_tree`, CPU and GPU. Shade-kernel REG is unchanged.
- [ ] Visual. Opus or Astra inspects before/after 64 spp crops of the sky, the
      world background and a directly seen emitter, with no structured patterns.

---

## Non-goals

- Do not route per-bounce draws (NEE, BSDF, RR, media): that is pkg297.
- Do not add blue-noise or screen-space dithering.
- Do not change the hero sampler's pdf, lane count or `terminateSecondary`.
- Do not touch photon/caustic forward passes.

---

## Progress

- [x] `sobol_burley.h` + camera slots + filter table (CPU), unit tests
- [x] CPU tile loop + hero input; gates on CPU
- [x] GPU `stage_init` port; REG report; gates on GPU
- [x] Default on; re-pins; pkg297 note

---

## Lessons

- The spec's `HashHP(pixel ^ seed)` makes seed s+1 at pixel p replay seed s at
  pixel p ^ 1, so the corpus MC seeds 278..282 would render one set of
  sequences. The seed is hashed first.
- Cycles' uniform-u inverse filter table fails chi2 in the near-zero tails
  (BH 1.5 outer bin 5x); a forward CDF + binary search passes.
- The CPU tile stream `mt19937(seed + tile)` also correlates consecutive
  seeds: corpus CPU band sigmas are underestimated (#986). Use seeds 10000 apart
  for A/B z-tests.
- Several seed-pinned tests encoded one realization of the old stream
  (pkg67 SSIM, glass-sphere phash, pkg287 max, ReSTIR spatial MSE); each was
  attributed against a main build before re-pinning.
