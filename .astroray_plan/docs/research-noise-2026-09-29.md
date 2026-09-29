# Noise research: why Astroray is noisier than Cycles, and how to beat it (2026-09-29)

Owner request 2026-09-29. Research and planning only. Measurements come from the
existing corpus v2 seed renders plus short new runs on this machine (RTX 5070 Ti,
Blender 5.2 Cycles, Astroray `al-293` build `cc535221`). Evidence is in
`C:\Users\hgcom\OneDrive\Astroray\astra_run\RS\rs-noise\` (scripts, `e1/`, `e2/`,
`times.jsonl`) and `C:\Users\hgcom\OneDrive\Astroray\astra_run\AK\ak-284b\work{,2}\`
(5 seeds x 64 spp per leg). Companion: `comparison-renderers-2026-09-29.md`.

## Headline

1. **At equal time on the GPU, Astroray's relMSE is about 7-40x Cycles OptiX on
   the corpus scenes.** Most of that is throughput, not noise. Astroray's wavefront
   is **3.8-9.1x slower per sample** than Cycles OptiX at 1280x720 (light_tree
   9.1, thin_film 7.8, camera_geometry 3.8). On the CPU it is **3.0-4.6x slower**
   per sample than Cycles CPU.
2. **At equal spp, bulk variance is 0.6-5x Cycles, not 50x.** The large
   ratios come from two things. First, heavy tails: 0.1 % of pixels hold 95-100 %
   of the variance in `v2_media` and `v2_dispersion_caustics`. Second,
   **spectral colour noise** in regions where Cycles has zero variance: sky,
   world background and directly visible emitters.
3. **The spectral floor is fully explained, and cheap to remove.** A numpy model of the
   engine's hero sampler reproduces the measured sky noise. Per-channel relVar at
   64 spp is R 0.0021 / G 0.00029 / B 0.0034 in the model, against R 0.0024 /
   G 0.00018 / B 0.0026 measured on the `v2_sky_sun` sky; Cycles measures exactly 0.
   Stratifying the **one** hero-wavelength uniform across a pixel's samples cuts
   it about **75x** at 64 spp in the model. Today that uniform is white noise
   (`std::mt19937` on the CPU, PCG32 on the GPU).
4. **Missing sample stratification is the second multiplier.** From 4 to 64 spp,
   Cycles' N x relVar falls to 0.24-0.71 while Astroray stays at about 1.0.
   pkg294 measured 4.5x from 1 to 64 spp on its cube. pkg297 is the right fix,
   and its camera group should ship first (pkg305).
5. **Acquitted, measured today:**
   - Filter glossy. Corpus scenes author it off. With Blender's default of 1.0,
     Cycles' trimmed variance falls only 0-23 %.
   - Cycles' blue-noise pattern. Its per-pixel variance equals the Classic
     Sobol pattern (0.92-0.98x); the gain is perceptual only.
   - The light tree on `v2_light_tree`: Astroray's bulk variance there is
     **0.6x** Cycles.
   - Earlier: per-sample estimators (pkg294).
6. **Correction to the visual record.** The `ak-284b` `sheet2_*` contact sheets
   put a **1024 spp** Cycles reference beside 64 spp Astroray renders. That
   overstates the gap. At equal spp (`research-noise-2026-09-29/equal_spp_sheet.jpg`),
   `v2_light_tree` and the `v2_camera_geometry` floor "confetti" look alike in
   both engines.

## 1. Measured decomposition (corpus v2, equal spp)

Setup: 64 spp, seeds 278-282, adaptive/denoise/clamps/filter-glossy off (the
corpus authors `blur_glossy = 0`, `sample_clamp_indirect = 0` through
`blender_showcase/showcase.py::_render_defaults`). Per-pixel luminance variance
across the 5 seeds. Pixels with reference luminance > 0.01. Ratio = Astroray / Cycles CPU.
"Bulk" = median over pixels of the per-pixel ratio. "Trimmed" = mean variance with
each engine's top 1 % of pixels dropped. "Chroma" = median per-pixel ratio of var(rgb/lum).

| scene | leg | bulk lum | trimmed | full | chroma | top-1 % share A / C | mean vs ref |
|---|---|---|---|---|---|---|---|
| light_tree | CPU / GPU | 0.60 / 0.60 | 0.76 / 0.75 | 1.5 / 1.7 | 1.7 | 0.59 / 0.17 | 0.96 |
| media | CPU / GPU | 2.8 / 2.5 | 7.0 / 7.0 | **43 / 12** | 14 | 0.99 / 0.95 | 0.97 |
| dispersion_caustics | CPU / GPU | 2.2 / 3.6 | **65 / 66** | **67 / 264** | 116-163 | 1.00 / 1.00 | 1.12 / **1.73** |
| sky_sun | CPU / GPU | **190** | 7.6 | 17 | 1.2e5 | 1.00 / 1.00 | 1.00 |
| thin_film_metals | CPU / GPU | 5.1 / 4.4 | 1.6 | 1.4 | 540-560 | 0.83 / 0.85 | 0.99 |
| textures_opvm | CPU / GPU | 26 / 4.5 | 6.2 / 5.4 | 3.9 | 5.6e3 | 0.74 / 0.84 | 0.92 / 1.08 |
| camera_geometry | CPU / GPU | 15 / 12 | 2.7 / 1.8 | 2.6 / 1.7 | 83-90 | 0.47 / 0.50 | 0.97 |
| camera_geometry@ortho | CPU / GPU | 20 / 17 | 3.0 / 2.1 | 2.8 / 1.9 | 49-53 | 0.43 / 0.47 | 0.95 |

Maps of the per-pixel ratio: `research-noise-2026-09-29/variance_ratio_maps_cpu.jpg`.
- relMSE vs the 1024 spp reference is **bias-dominated** (bias^2 / relMSE ≈ 0.98)
  on `sky_sun` and `textures_opvm`. These are parity defects, not noise. The GPU
  `dispersion_caustics` mean is 1.73x Cycles: the GPU renders a sun-through-prism
  rainbow beam that Cycles does not.

### Per-sample time (render-only; 60 spp difference on CPU, 240 spp at 1280x720 on GPU, min of 2)

| scene | Astroray CPU / Cycles CPU | Astroray GPU / Cycles OptiX (1280x720) | GPU at 320x180 (960 spp) |
|---|---|---|---|
| light_tree | 4.6 | **9.1** | 6.2 |
| thin_film_metals | 3.7 | **7.8** | 9.6 |
| camera_geometry | 3.0 | **3.8** | 16 |
| sky_sun | 4.6 | n/m | 4.4 |
| media | n/m | n/m | 3.3 |

Equal-time relMSE gap (GPU, variance only) = trimmed or full ratio x time ratio:
- light_tree: 7-15x
- thin_film: 11-13x
- camera_geometry: 7x
- media: about 23-39x
- sky: about 33x

## 2. Mechanisms, with owners

| # | mechanism | evidence | share of the gap | owner |
|---|---|---|---|---|
| M1 | **White-noise hero wavelength** (4 lanes stratified inside a sample, 1 uniform per sample from mt19937/PCG) | model = measured, to within 10-35 % per channel (above). Sky bulk lum 190x, chroma 1e2-1e5x wherever Cycles' pixel is deterministic (world, emitters, flat albedo) | dominates direct-view regions. Invisible in luminance only when lit transport is noisy anyway | **pkg305** (new) |
| M2 | **No stratification** of pixel/lens/light/BSDF dims (CPU mt19937; GPU PCG32 unless adaptive) | N x relVar 64 vs 4 spp: Cycles 0.24-0.71, Astroray 0.96-1.05 (`slope.py`). pkg294 cube 4.5x (1 to 64 spp) | 1.4-4.5x at 64 spp; grows with spp | pkg297 (existing) |
| M3 | **Per-sample throughput** | table above; agrees with `research-performance-2026-09-29.md` (3.4x Cornell, 6.6x at 2M tris) | 3-9x at equal time on both backends | pkg298/pkg299/pkg300 (#972); not a noise spec |
| M4 | **Heavy tails, `v2_media`**: 0.1 % of pixels hold 95 % of the variance, in `emitter_cool_glow`/`emitter_warm_glow`. Worst pixel mean 26.9 vs Cycles 0.18 | `decomp2.py`, CPU 43x vs GPU 12x | 6x on full variance | **pkg306** (new) |
| M5 | **Heavy tails, `v2_dispersion_caustics` floor**: 0.1 % of pixels hold 100 %; pixel means 101-186 vs Cycles 0.02-0.21, coloured confetti on the lit strip | sheet and `decomp2.py` | 65x trimmed | **pkg306**; ground truth needs a spectral renderer (Cycles is RGB) |
| M6 | Bias, not noise (sky_sun, opvm, GPU dispersion beam) | bias^2 / relMSE 0.98 | inflates relMSE, not variance | parity backlog |

Acquitted, measured today:
- **Filter glossy.** It is a no-op in Astroray (setter only, `raytracer.h:2506`),
  but the corpus turns it off.
  - Cycles `blur_glossy` 1 vs 0: trimmed variance 0.91 (camera), 0.77 (thin film),
    1.00-1.20 elsewhere.
  - Means shift ≤ 0.7 %.
  - It matters for user scenes at Blender defaults, but as parity (pkg201 item C),
    not as a noise lever.
- **Blue-noise pattern.** Cycles `TABULATED_SOBOL` / `AUTOMATIC` per-pixel
  variance is 0.92 / 0.98. Cycles re-renders are bit-identical, so this is a
  clean A/B.

Unmeasured suspects, ranked:
- **RR.** Astroray uses `p = min(0.95, Y)` from bounce 4 (`raytracer.h:4124`).
  Cycles uses `min(1, sqrt(max|T|))` (`path_state.h`). This kills more paths
  in dim interiors and always kills 5 %.
- **Env NEE and lamp NEE both fire per vertex** (not a selection). This is
  correct, and it costs rays.
- The `terminateSecondary` collapse at dispersive vertices (hero pdf / 4). It
  is the likely engine of M5's colour.

## 3. Ranked opportunities

Gain = expected variance or efficiency factor on the corpus. The evidence is ours
unless a paper is cited. "Parity" = effect on Cycles-oracle gates.

| rank | item | gain (evidence) | cost | bias | parity / oracle | licence |
|---|---|---|---|---|---|---|
| 1 | **Stratified camera group: hero lambda + filter + lens (pkg305)** | chroma floor ~75x at 64 spp (model); direct-view regions to about parity; AA edges | 1-2 sessions; no shade-kernel state | none | means unchanged; byte streams change, so re-pin | Cycles Apache-2.0 (Sobol-Burley), Burley 2020 |
| 2 | **Per-bounce QMC (pkg297)** | 1.4-4.5x at 64 spp (M2); Cycles-like convergence slope | 6 sessions; 60-file retype | none | as above | same |
| 3 | **GPU per-sample throughput (pkg298-pkg300)** | 3-9x equal time (M3) | specced in #972 | none | none | n/a |
| 4 | **Tail owners in media and dispersion (pkg306)** | media full 43x to ≤3x plausible (the trimmed 7x is the bulk); dispersion needs arbitration | 2-3 sessions | fix-dependent | Mitsuba spectral arbitration for M5 | n/a |
| 5 | **Noise-per-time benchmark + Mitsuba 3 leg (pkg307)** | enabling: turns every row here into a gate | 2 sessions + owner install | n/a | adds a spectral oracle | Mitsuba BSD-3 |
| 6 | RR survival `min(1, sqrt(max))`, then EARS (Rath 2022) / MARS (Meyer 2024) | RR: small ±; EARS ~1.5-2x efficiency (paper, from memory; verify), MARS 1.6x over EARS on BDPT (verified) | RR 1 h; EARS 3-4 sessions (CPU first) | unbiased | means unchanged | EARS/MARS code (Mitsuba-based) licence to check |
| 7 | Path guiding (pkg136 resume) | ~1.3x equal cost measured (Stage 1); larger on hard indirect | GPU leg L | unbiased | none | own code / OpenPGL Apache-2.0 |
| 8 | Filter glossy (pkg201 item C) | ≤ 23 % variance at Blender defaults (measured on Cycles) | 1-2 sessions | biased, as Cycles | needed for default-scene parity | Cycles Apache-2.0 |
| 9 | Colour-aware adaptive stop metric + denoise defaults | user-perceived noise; Cycles' error sums \|dR\|+\|dG\|+\|dB\| | 1 session | consistent | none | Cycles |
| 10 | ReSTIR DI/GI | large at 1-4 spp (Bitterli 2020); small offline | L; register pressure | biased unless MIS'd | viewport only | RTXDI MIT |

## 4. pkg297 review

pkg297's diagnosis and design are right: Cycles-style per-set Sobol-Burley, a
fixed per-bounce dimension layout, and the rejection of the pkg224 auto-counter.
Five changes:

1. **Split out the camera group first (pkg305).**
   - M1 is the biggest single excess in direct-view regions. Its fix is one draw,
     made before the path starts.
   - It needs `sobol_burley.h` and the camera slots of `path_dimensions.h` only:
     no `Rng` retype, and no shade-kernel registers (it lives in
     `stage_init.cu` / the tile loop).
   - pkg297 then extends the same files per bounce.
2. **Add a chroma gate.** pkg297's gates are luminance-only and would pass while
   the spectral floor stays. Add "R and B relVar at 64 spp on a white emitter
   ≤ 0.1x the current value". pkg305 carries it.
3. **Add an equal-time gate.** relVar x wall time against Cycles at the same
   device class. Otherwise a sampler that costs 20 % could pass.
4. **Blackman-Harris/Gaussian filter draws use rejection** (variable count,
   `raytracer.h:3263`). Stratified filter dimensions need Cycles'
   inverse-CDF filter table instead. pkg305 takes this.
5. Keep blue noise a non-goal. It is confirmed perceptual-only here.
   After pkg297, a ZSobol-style screen-space ordering (Ahmed and Wonka 2020;
   pbrt-v4 `ZSobolSampler`) is a cheap follow-up for denoised viewport frames.

## 5. Roadmap and gates

| stage | package(s) | gate (measured by pkg307 on corpus v2, 5 seeds) |
|---|---|---|
| N0 | pkg307 Phase 1 | equal-spp and equal-time relMSE table, 8 scenes x {Astroray CPU, GPU} x {Cycles CPU, OptiX}, committed and reproducible in one command |
| N1 | pkg305 | sky ROI R/B relVar at 64 spp ≤ 2.4e-4 (from 0.0024); `v2_sky_sun` bulk lum ratio ≤ 5 (from 190); means in band |
| N2 | pkg306 | `v2_media` full relVar ≤ 3x Cycles (from 43x CPU / 12x GPU); dispersion floor tail either fixed or proven correct against Mitsuba |
| N3 | pkg297 | pkg297 gates, plus median-ROI N x relVar down ≥ 1.5x |
| N4 | pkg298-pkg300 | GPU per-sample time ≤ 2x OptiX on light_tree / thin_film at 1280x720 (this doc's timing method) |
| **Parity** | N0-N4 | **equal-time relMSE ≤ Cycles on ≥ 4/8 corpus v2 scenes, GPU vs OptiX** |
| **Beat** | bets below | **≤ 0.7x Cycles on ≥ 6/8, and on every spectral arbitration scene vs Mitsuba at equal time** |

Parity is reachable with known techniques. Beating Cycles needs something Cycles
does not have. Cycles already has stratification, a light tree, and OpenPGL
guiding (CPU, off by default).

## 6. Innovation bets (speculative)

- **B1: wavelength splitting on non-dispersive paths.** Path geometry does not
  depend on lambda until a dispersive event. Evaluating the throughput at 8-16
  wavelengths costs BSDF/spectrum evaluations, not rays. This would give spectral
  colour noise below an RGB renderer's (Cycles has none to beat on white, but has
  it on chromatic media and dispersion). CPU first; GPU is register-bound
  (REG 254).
- **B2: lambda-splitting at dispersive vertices.** Instead of `terminateSecondary`
  (hero only, pdf / 4), trace the 4 lanes as 4 rays from the first dispersive vertex
  only. It targets M5 and prism/nebula scenes directly. Related: continuous MIS
  over wavelength (West et al. 2020, SIGGRAPH). It also serves the astro direction
  (line emission).
- **B3: efficiency-aware RR and splitting (EARS/MARS)** on the spectral path, with
  the cost model including lane count. No published spectral variant exists.
- **B4: spectral path guiding.** A guiding distribution conditioned on
  wavelength band. We found no canonical paper, so it is a research gap and a
  possible publication. It pays off in emission-line scenes (HMXB, nebulae)
  where Cycles cannot compete at all.
- **B5: GPU guiding plus QMC, with the viewport as the showcase.** Cycles' guiding
  is CPU-only. A GPU pkg136 leg would be a genuine lead on the 5070 Ti.

## 7. Owner decisions

1. Order: pkg305 (cheap, visible) before or in parallel with pkg298-pkg300
   (throughput, the largest equal-time factor)? Proposed: in parallel. The files
   are disjoint except `stage_init.cu`.
2. Should "noisier than Cycles" be judged at equal time on the same device class
   (proposed), or at equal spp?
3. The comparison-renderer installs (companion doc).
4. CPU per-sample cost (3.0-4.6x Cycles CPU) has no owner. pkg298-pkg300 are
   GPU-only. Is the CPU an efficiency target, or only the correctness oracle?
5. pkg307's timing method (spp differencing) and pkg298's
   `wavefront_baseline.py` should share one instrument. Proposed: pkg307 calls
   pkg298's harness for GPU timing once it lands.
