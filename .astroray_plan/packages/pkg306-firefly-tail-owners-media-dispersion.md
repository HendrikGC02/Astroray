# pkg306 — Firefly tail owners: media emitter glow and dispersion floor

**Pillar:** 3
**Track:** A
**Status:** open
**Estimated effort:** 3 sessions (~9 h): Phase 0 1, Phase 1 1-2, Phase 2 0.5
**Depends on:** pkg284, pkg294

---

## Goal

Before:
- In `v2_media`, 0.1 % of pixels hold 95 % of Astroray's variance: full relVar
  is 43x Cycles on the CPU and 12x on the GPU, against a bulk of 2.5-2.8x. They
  cluster in the `emitter_cool_glow` / `emitter_warm_glow` ROIs, where the worst
  5-seed pixel mean is 26.9 against Cycles' 0.18.
- In `v2_dispersion_caustics`, 0.1 % of pixels hold 100 %. The lit floor strip
  shows coloured confetti, with pixel means 101-186 against Cycles' 0.02-0.21.

After:
- Each tail has a named owner (a path class plus a code site), proven by
  ablation.
- The media tail is fixed, or shown to be correct transport, with numbers.
- The dispersion tail is either fixed or arbitrated as physically correct transport
  that Cycles (RGB) does not render, using a spectral reference.

---

## Context

`research-noise-2026-09-29.md` M4 and M5. After pkg305 and pkg297 remove the
spectral floor and the sampler gap, these tails are the largest remaining
equal-spp excess in the corpus.
- The media tail is 6x the bulk.
- The dispersion tail is the whole signal.

This work comes before any "beat Cycles" technique (guiding, EARS): a
variance-reduction method measured on a scene with an unexplained 40x tail proves
nothing. Opus 5.5 diagnosis lane; Sonnet 5.5 runs the ablation grid.

---

## Evidence

- 2026-09-29 (`astra_run\RS\rs-noise\decomp2.py` on `ak-284b\work{,2}`, 5 seeds
  x 64 spp, adaptive/denoise/clamps/filter-glossy off):

  | scene | trimmed | full | top-0.1 % share (Astroray / Cycles, same pixels) |
  |---|---|---|---|
  | media, CPU | 7.0x | 43x | 0.95 / 0.42 |
  | media, GPU | 7.0x | 12x | n/a |
  | dispersion, CPU | 65x | 67x | 1.00 / 0.000 |
  | dispersion, GPU | 66x | 264x | n/a |

  The dispersion mean is 1.12x Cycles on the CPU and 1.73x on the GPU. The GPU
  also renders a rainbow prism beam that neither Cycles nor the Astroray CPU shows.
- 2026-09-29: Cycles `blur_glossy` 0 vs 1 does not change either scene's variance
  (1.00, trimmed 1.00/1.20). Filter glossy is not the reason Cycles is clean here.
- Suspects, unverified:
  - Media: an emitter reached through a phase-sampled or equiangular vertex without
    the matching MIS weight, near small emitters.
  - Media: pkg294's lamp-footprint anomaly (a tilted rectangle's floor footprint
    reads 4.9x Cycles).
  - Dispersion: `terminateSecondary` (hero pdf / 4) on a sun-through-glass chain.
  - Dispersion: the photon-caustic auto-enable (`set_use_photon_caustics(has_caster)`)
    on the CPU K-NN gather (#909 fixed only the GPU round loop).
  - Dispersion: sun-disc hits through delta glass.

---

## Reference

- `.astroray_plan/docs/research-noise-2026-09-29.md` §1-2, maps
  `research-noise-2026-09-29/variance_ratio_maps_cpu.jpg`.
- `.astroray_plan/docs/pkg294-media-lamp-variance-ablation.md` (variant
  environment-flag pattern, z-metric, clamp item 5).
- `.astroray_plan/docs/issue909-caustic-speckle-research.md` (photon rounds, K-NN
  radius, double counting).
- `.astroray_plan/docs/issue925-volume-segment-direct-light-research.md`.
- Cycles `kernel/integrator/shade_volume.h` (equiangular + distance MIS),
  `kernel/light/*` (emitter-hit MIS), Apache-2.0.
- Veach 1997 ch. 9 (MIS); Kulla and Fajardo 2012 (equiangular).
- Mitsuba 3 `volpath` / spectral `dielectric` for arbitration, once pkg307 Phase 2
  has it installed.

---

## Prerequisites

- [ ] pkg294 Phase 1 merged (spherical-rectangle draw), so the media ablation is
      not confounded by it.
- [ ] Corpus v2 on main (`benchmarks/reference_corpus/gates_v2.toml`).
- [ ] Baseline binaries kept.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg306_tail_owners.py` | Tail gates below: `v2_media`/`v2_dispersion_caustics` top-0.1 % share and full relVar vs Cycles, means in band (CPU; GPU leg marked `gpu`) |
| `.astroray_plan/docs/pkg306-tail-attribution.md` | Phase 0 ablation table and owner verdict |

### Files to modify

| File | What changes |
|---|---|
| `benchmarks/reference_corpus/mc_tolerance.py` | `--tail-report` over its existing per-seed renders: top-0.1 % variance share, pixel locations by manifest ROI, and worst-pixel per-seed values. Update the `scripts/README.md` entry. Shared with pkg307 |
| `include/raytracer.h` | Phase 1 fix site (expected: medium-vertex emitter-hit MIS, or the caustic/photon split), cited |
| `include/astroray/volume/volume_transport.h` | Phase 1 fix site if media-owned |
| `src/gpu/wavefront/stage_volume_hetero.cu` | GPU mirror of the media fix (no new shade-kernel live state) |
| `src/gpu/wavefront/stage_advance.cu` | GPU mirror of a dispersion/caustic fix, if any |

### Key design decisions

#### Phase 0: attribution (no fix yet)

- Use temporary `ASTRORAY_PKG306_DIAG` variants, following the pkg294 pattern,
  on both scenes, CPU and GPU. Each is one switch:
  - NEE only;
  - BSDF/phase only;
  - equiangular only;
  - distance only;
  - photon caustics off;
  - SMS off;
  - `terminateSecondary` bypassed (all 4 lanes kept through dispersion; biased,
    diagnostic only);
  - emitters camera-invisible.
- For each variant, report:
  - the top-0.1 % share;
  - full, trimmed and bulk variance ratios;
  - worst-pixel per-seed values, to tell a 1-in-N firefly from a stable
    bright pixel;
  - |z| of the ROI means.
- A tail owner is a variant that removes ≥ 80 % of the tail share with its
  paired complement not doing so.
- Per memory `unbiased-strategy-switch-moving-a-mean-is-a-bug-signal`: an
  unbiased switch that moves a mean is a bug in its own right. Report it first.

#### Phase 1: fix

- Cite the reference for any MIS/pdf change. The GPU mirror must add no per-hit
  live state (REG 254).
- If Phase 0 says the dispersion tail is correct transport (sun, then glass,
  then floor, a path Cycles skips), do not suppress it. Record it as "RGB
  reference limit".
- Mark the ROI provisional in `provisional_v2.toml`, tied to a Mitsuba
  arbitration row in pkg307. Separately file the variance reduction for that
  transport (photon/SMS routing or B2 lambda-splitting).

#### Phase 2: gates

- Re-run the corpus v2 bands for the two scenes. Do not re-bless others.

---

## Acceptance criteria

- [ ] Phase 0 table committed. Each tail has an owner (path class + file:line),
      or an explicit "not found" with the variants that ruled things out.
- [ ] `v2_media`: full relVar ≤ 3x Cycles on CPU and GPU (from 43x / 12x), and
      the top-0.1 % share is ≤ 2x Cycles' share on the same pixels. Every media
      ROI mean has |z| ≤ 3 vs Cycles bands.
- [ ] `v2_dispersion_caustics`: either trimmed relVar ≤ 5x Cycles, or a committed
      arbitration shows the Astroray mean in the floor ROIs agrees with a
      spectral reference (Mitsuba 3 or pbrt-v4) within 3 sigma, with Cycles out.
      The GPU beam's mean is explained in the same way.
- [ ] No regressions. Full CPU suite and RTX sweep (no `-x`) show no new failure
      attributable against a baseline build. pkg294 cubes stay within their bands.
- [ ] Visual. Opus or Astra inspects equal-spp crops (not against a 1024 spp
      reference) of both scenes before and after.

---

## Non-goals

- Do not add clamps, outlier rejection or filter glossy to hide tails.
- Do not change the sampler (pkg305/pkg297) or light selection (pkg86/pkg294).
- Do not implement new caustic transport (photon/SMS/lambda-splitting). File it.

---

## Progress

- [ ] Phase 0: tail report flag + ablation grid + attribution doc
- [ ] Phase 1: media fix (CPU, then GPU). 2026-10-03 lane au-media (#961/#1019):
      media tail owner = the light-tree path of the #925/#929 segment direct light
      (midpoint point pick for the anchor, independent pick at P;
      `include/raytracer.h` segmentDirectLight, `stage_volume_hetero.cu`
      gpu_volumeSegmentDirect). Fixed with Cycles' segment light-tree pick; CPU
      v2_media 64 spp: top-0.1 % share 0.957 -> 0.494 (Cycles 0.705), relVar 64x ->
      4.6x Cycles, emitter_cool_glow variance 28x -> 4.2x. Remaining smoke-VDB
      per-sample excess filed as #1032. Notes:
      `.astroray_plan/docs/issue961-segment-light-tree-research.md`.
- [ ] Phase 1: dispersion fix or arbitration
- [ ] Phase 2: bands + gates

---

## Lessons

*(Fill in after the package is done.)*
