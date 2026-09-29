# pkg294 Phase 0: media lamp-variance attribution ablation (#922)

2026-09-29, lane ak0-294, CPU MinGW build of `lane/ak0-294` (OpenMP on, 8 threads) vs
Cycles (Blender 5.2, CPU, 8 threads). Evidence: `astra_run\AK0\ak0-294\` (`phase0_table.md`
is the full table; renders as `.npy`).

## Setup

- Scenes (`pkg294-phase0/build_scenes.py`): geometry_zoo scatter cube (0.55 m, density 4,
  g 0.55, colour 0.95/0.96/1.0), backlight 900 W rectangle 1.5 x 1.125 m about 1.3 m away,
  black world, no surfaces, lamps camera-invisible, clamp off, 256x256. `cube1` = backlight
  only; `cube3` = plus key 650 W and fill 220 W. `v` suffix = `volume_bounces` 8 (the
  default 0 is single scatter). ROI = the cube's centre 60 % (49 x 50 px).
- Metric: Rec.709 luminance. relVar = mean per-pixel across-seed variance / mean^2. 64 spp
  x 3 seeds; per-sample relVar = 1 spp x 12 seeds. The spatial pkg290 metric gives the same
  numbers (checked). Seeds are uncorrelated (residual correlation below 0.05).
- Mean preservation: z = (mean - baseline) / combined sigma. Band = |z| <= 3.
- Variants (`ASTRORAY_PKG294_DIAG`, temporary; see `src/lights/area_light.cpp`):
  `ar0` baseline; `ar1` hit-site pdf: solid-angle 1/Omega in both MIS weights at medium
  vertices, estimator pdf unchanged; `ar2` segment draw: the NEE point at the scatter point
  drawn by spherical rectangle, with pdfLi paired (port of Cycles `area_light_rect_sample`,
  Urena et al. 2013). The anchor stays area-uniform. `ar3` NEE-only; `ar4` phase-only.
  Tens digit: 1 = equiangular only, 2 = exponential only. Hundreds digit 1 = the `ar2` draw.
  Tree on/off = `scene.cycles.use_light_tree` (both engines).

## Table (tree on unless stated)

| scene | variant | z vs ar0 | relVar 64 spp, x Cycles | per-sample relVar, x Cycles | clamp-10 removed (Cycles) |
|---|---|---|---|---|---|
| cube1 | ar0 baseline | 0 | 5.23 | 0.562 / 0.495 = 1.13 | 0 (0) |
| cube1 | ar1 hit-site pdf | +0.14 | 5.08 (0.97x ar0) | n/a | 0 |
| cube1 | ar2 segment draw | +0.22 | 4.17 (0.80x ar0) | n/a | 0 |
| cube1 | ar13 NEE-only, equiangular | +0.79 | 21 (vs Cycles, same strategy) | 0.393 / 0.301 = 1.31 | n/a |
| cube1 | ar113 same + ar2 draw | +0.57 | 16 (vs Cycles, same strategy) | 0.296 / 0.301 = **0.98** | n/a |
| cube1 | tree off (ar0 / ar1 / ar2) | +0.0 / +0.03 / -0.11 | 5.06 / 4.98 / 4.03 | n/a | n/a |
| cube3 | ar0 / ar1 / ar2 | 0 / +0.08 / +0.29 | 1.88 / 1.81 / 1.57 | n/a | 0 |
| cube3 | tree off (ar0 / ar1 / ar2) | 0 / +0.10 / +0.08 | 2.09 / 2.00 / 1.83 | n/a | n/a |
| cube1v | ar0 / ar1 / ar2 | 0 / +0.21 / +0.12 | 2.24 / 2.18 / 2.05 | 0.74 / 0.72 / 0.67 | 13.8 / 14.0 / 12.7 % (12.3 %) |
| cube3v | ar0 / ar1 / ar2 | 0 / +0.18 / +0.13 | 1.14 / 1.10 / 1.04 | 0.45 / 0.43 / 0.41 | 16.5 / 16.6 / 15.5 % (21.9 %) |
| cube3v | tree off (ar0 / ar1 / ar2) | 0 / +0.12 / +0.26 | 1.14 / 1.09 / 1.04 | 0.46 / 0.44 / 0.42 | 22.0 / 22.1 / 21.2 % (27.8 %) |

All variants fall inside the band (largest |z|: 2.2 for exponential-only, ar4 phase-only
-2.0). Cycles against Astroray baseline: z -1.7 to -3.8, so Astroray reads 0.2 % (single
scatter) and 0.6 % (multi-scatter) brighter. This is informational only, not a variant effect.

Tree: Astroray's on/off factor tracks Cycles'. cube3 0.48 vs Cycles 0.54; cube3v 0.62 vs
0.62. Astroray/Cycles stays 1.14 either way on cube3v, and one lamp shows no change.

Equal time (1024 spp wall, 2 seeds): Astroray CPU is 2.10x (cube1), 1.48x (cube1v) and
1.38x (cube3v) slower per sample than Cycles. Efficiency gap (relVar x time, Astroray over
Cycles): ar0 11.0 / 3.3 / 1.57; ar1 10.9 / 3.3 / 1.56; ar2 9.1 / 3.2 / 1.51.

## Attribution

1. **Hit-site pdf: acquitted.** `ar1` gives 0.96-0.98x of baseline in every scene and tree
   setting.
2. **Light-tree selection: acquitted.** The tree's gain matches Cycles', and the Astroray/
   Cycles ratio does not depend on the tree. **Phase 2 is not needed.**
3. **Segment draw: the only term that moves variance, and only by a small amount.** It gives
   0.80-0.92x at 64 spp. Per sample it moves NEE-only equiangular from 1.31x Cycles to
   0.98x, i.e. exact parity.
4. **Most of the equal-spp excess is the sampler, not an estimator term.** Per sample,
   Astroray is at parity or better: 1.13x (cube1), 0.74x (cube1v), 0.45x (cube3v).
   Cycles' N x relVar falls 4.5x from 1 to 64 spp on cube1 (0.495 to 0.109; this is the
   within-pixel stratification of its Sobol/blue-noise sequence). The CPU Astroray path
   draws from `std::mt19937` and stays flat (0.562 to 0.568). The pkg224 progressive
   Sobol sampler is not read on the CPU. On the GPU it is enabled only with adaptive
   sampling; otherwise the GPU uses PCG32 (`blender_addon/__init__.py`, pkg262).
   The numpy estimator (`pkg294-phase0/sim_estimator.py`) gives per-sample relVar 0.373
   (equiangular) and 1.345 (exponential). Astroray measures 0.393 and 1.38, so the engine
   matches the textbook estimator.
5. **Clamp (pkg290): not reproduced in media alone.** At `sample_clamp_indirect` 10,
   Astroray removes 13.8 % vs Cycles 12.3 % (cube1v) and 16.5 % vs 21.9 % (cube3v). The
   cabinet's 20.4 vs 6.5 % gap needs its surfaces. A diffuse floor under a tilted rectangle
   lamp renders a sharp bright footprint in Astroray: the lamp rectangle projected along its
   normal, 17.6 vs Cycles 3.6 (4.9x). The footprint does not change with `ar2`, tree on or
   off, or installed-extension vs lane build. So it is not in `AreaLight::sampleLi`/`pdfLi`
   (`nv_variants.png`, `nvsq_modes.png`). A downward-facing lamp shows no footprint but reads
   0.82x Cycles.
6. **Luminance-only gates.** Astroray has a spectral chroma noise floor: R/B relVar about
   0.002 at 64 spp on a directly viewed white emitter, where Cycles has 0. A per-channel
   variance gate against Cycles cannot pass.

## Phase 1 recommendation

Phase 1 (spherical-rectangle pdf/draw, rectangle + disk, CPU + GPU) is Cycles-parity work.
Its measured gain is 8-20 % variance and per-sample parity. It **cannot** reach the spec's
"≤ 1.5x Cycles at 64 spp" gate on the one-lamp cube (projected about 4.2x); that gate is
a sampler gate. Suggested re-scope:
(a) Phase 1 gate = per-sample (1 spp) relVar ≤ 1.1x Cycles, means in band.
(b) Drop Phase 2.
(c) File the QMC sampler gap: the pkg224 Sobol path is off on CPU and on non-adaptive GPU.
(d) File the tilted-rectangle floor footprint as the likely pkg290 blocker, ahead of #922.

## Phase 1 result (CPU, 2026-09-29)

Full-spread rectangles now use the spherical-rectangle draw and pdf (`include/astroray/spherical_rectangle.h`)
for surface NEE, the lamp-hit pdf and the re-sample at the volume scatter point. The segment anchor stays
area-uniform. Rectangles below 180 deg spread and disks/ellipses are unchanged. Gate: per-sample
(1 spp x 12 seeds) luminance relVar against Cycles.

| scene | tree on | tree off |
|---|---|---|
| cube1 | 0.91 | 0.91 |
| cube3 | 0.38 | 0.47 |
| cube1v | 0.67 | not run |
| cube3v | 0.42 | 0.41 |

All values are ≤ 1.1. Means stay inside the band: |z| ≤ 1.3, and cube3 tree-off -1.9 with 12 seeds
(-3.16 at 3 seeds). Equal-spp 64 spp ratios move from 5.23 to 4.33 (cube1) and from 1.14 to 1.11 (cube3v),
as Phase 0 predicted. Table: `astra_run\AK0\ak0-294\phase1_full_table.md`.
