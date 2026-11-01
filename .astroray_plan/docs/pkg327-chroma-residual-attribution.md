# pkg327 Phase A: attribution of the row (g) minor-channel chroma residual

Evidence only. No engine, gate or tolerance change. Phase B (per-channel pins) is not started.

## Result

All ten target channels are **chroma-dependent** (a grey albedo removes them) and **Mitsuba spectral reproduces the shift** to within
0.003 on a diffuse stand-in of the production scene (hero sphere / bowl, production camera, ROIs and lighting). No target channel is an
engine-bug candidate. Two major-channel misses (wood `grain_center` r, light_path `floor_near` r) are the same effect plus a low gate-seed
draw; one of them keeps a 1.2-point remainder at 2.4 sigma. The shift is **spectral transport of a saturated albedo under coloured light**,
not a single bounce under white light: a flat white world removes most of it for the warm channels and makes the curves cyan worse.

What this proves and does not: Mitsuba 3 uses the same Jakob-Hanika upsampler in independent code, so agreement shows Astroray matches a
reference spectral renderer, not that the upsampled spectrum is the true one (memory `clean-room-oracle-is-self-consistency-not-ground-truth`).
CPU only; GPU legs were not run (the cluster reads CPU = GPU, spec).

## Method

- Engine under test: staged addon `dist_batch_931dd0af` (build `931dd0a+20261031T134118Z`, pyd sha256 `48f9d16e02e3fab9972ba43f9abe6b66fb6e3c6a3cd90969831088755cd1e2c`),
  CPU legs, `effective_device` cpu in every receipt. Blender 5.2.0 LTS Cycles CPU. Mitsuba 3.9.1 `scalar_spectral` / `scalar_rgb`.
- Production scenes: gate settings (320x240, 64 spp), seeds 278, 1301, 2711, 4177 (the first four of the suite's decorrelated seeds). Baselines of
  wood and light_path have 8 seeds (4177 + 6113, 7351, 8209, 9181 added after the first read). Ratio = mean over seeds of Astroray over mean of Cycles, SE by the delta method.
- Controls (`render_leg.py --attrib-spec`, each receipted on a `PKG327_ATTRIB` line and refusing a no-op): `albedo_grey` (every Principled Base Color of the
  material, node groups included, to a constant grey of the material's luminance), `world_flat_white` (HDRI node removed, white world at the HDRI's solid-angle-mean
  luminance x 0.3), `albedo_const`, `lambertian`, `lights_only`, `world_hdri`. `grey_flat` = both. The first `world_flat_white` run left the Environment Texture node in
  place and Astroray still read it; those renders were discarded and rerun (the addon finds the node by type, not by link).
- Mitsuba proxies (`arbitration/mitsuba_scenes.py` `PARAMS`, built for Cycles/Astroray by `build_arbitration.py`, so all engines render one definition):
  `arb_chroma_bowl`, `_warm`, `_warm_sky`, `_warm_hdri`, `_patches` (ten coplanar albedos incl. a grey control), `_bowl_stage`, `_hero_wood`, `_hero_car`, `_hero_pbr`.
  The last four use the production stage (sun 1.1, 60 W area lamp, HDRI 0.3) with the stage area lamp scale calibrated area-lamp-only against Cycles (4.7722; sun and HDRI
  are physical units; a single-component check on the hero_car ROIs reads Cycles/Mitsuba-rgb 0.98-0.99 for the sun alone and 0.99-1.00 for the HDRI alone). Proxies run 256 spp (Cycles, Astroray) and 1024 spp (Mitsuba), same four seeds.
- Arbitration reading: `A/C` = Astroray / Cycles, `Ms/Mr` = Mitsuba spectral / Mitsuba rgb, per ROI channel. Agreement band = 2 x combined SE + 0.01.
- **Raw HDRI caveat.** The production HDRI carries 84 % of its energy in six sun texels (peak 1.6e5). Mitsuba's spectral envmap is not texel-invariant there: on the **grey** patch
  (flat albedo, so exactly 1) Mitsuba spectral/rgb reads G 0.982, B 0.966 under the raw HDRI. Astroray/Cycles on the same patch read 1.00 and are unchanged by smoothing the sun.
  Arbitration therefore uses the production HDRI with the sun replaced by a 2-degree Gaussian of equal RGB energy (`attribution.py smooth-hdri`, sha256 `7001c4058b72ef2e283c43150c48ec4feef9b98e9c555998c83e9c3e7162ccf5`, energy ratio 1.0007).
  Astroray/Cycles ratios move by at most 0.01 between raw and smooth; Mitsuba's move by 0.03-0.07 in B. Raw-HDRI numbers are in `pkg327-attribution/proxy_raw_hdri.json` for the record, not for arbitration.

## Per-channel verdicts (CPU)

`A/C` columns are Astroray / Cycles. "Gate seed" = 278. "Mean" = n-seed mean (SE). Proxy = smooth-HDRI proxy of the same ROI. Dilution = production deficit / proxy deficit.

| Scene | ROI | Ch | Tol | Gate seed | Mean (SE) | Grey albedo | Flat white world | Proxy A/C | Proxy Ms/Mr | Dilution | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| curves_geometry | inner_backface | r | .084 | .844 | .857 (.007) n4 | 1.002 (.007) | **.457** (.003) | .755 | .747 | 0.58 | Mitsuba confirms |
| wood | grain_center | b | .026 | .932 | .941 (.003) n8 | 1.000 (.007) | .992 (.001) | .925 | .924 | 0.79 | Mitsuba confirms |
| wood | grain_right | b | .045 | .932 | .938 (.002) n8 | .993 (.003) | .988 (.001) | .901 | .902 | 0.63 | Mitsuba confirms |
| wood | lower | b | .027 | .937 | .947 (.003) n8 | .994 (.003) | .989 (.001) | .915 | .917 | 0.62 | Mitsuba confirms |
| wood | grain_left | b | .042 | .979 | .979 (.001) n8 | .998 (.002) | .992 (.002) | .969 | .969 | 0.68 | Mitsuba confirms (passes the gate; no pin needed) |
| wood | grain_center | r | .024 | .953 | .972 (.005) n8 | 1.000 (.009) | .996 (.001) | .984 | .983 | 1.75 | Mitsuba confirms 1.7 of 2.8 points; remainder 1.2 (2.4 sigma) |
| car_paint | lit_front | b | .031 | .930 | .929 (.005) n4 | .995 (.005) | .981 (.003) | .912 | .912 | 0.81 | Mitsuba confirms |
| car_paint | upper_flake | b | .026 | .958 | .960 (.004) n4 | .995 (.003) | .983 (.004) | .935 | .937 | 0.62 | Mitsuba confirms |
| pbr_group | lower | b | .056 | .905 | .926 (.008) n4 | .997 (.007) | .980 (.003) | .912 | .912 | 0.84 | Mitsuba confirms |
| light_path | floor_near | r | .020 | .975 | .982 (.002) n8 | .997 (.003) | .987 (.003) | .986 | .987 | 1.27 | Mitsuba confirms 1.4 of 1.8 points; remainder 0.4 (1.6 sigma) |

Reading the dilution: the proxies are diffuse, the production materials are Principled (white specular lobe, albedo varying over the ROI), so b deficits sit at 0.6-0.85 of the proxy's.
The two r rows exceed the proxy (a diluted effect cannot); their remainders are 2.4 and 1.6 sigma and the same sign as the spectral shift.

Other controls on the same channels (`production_variants.json`):

- light_path `floor_near` r, #1199 recipe: Lambertian floor 0.983 (3), baseline 0.982: the specular lobe is not involved. Constant floor colour at the camera-ray ramp value (0.426, 0.277, 0.474) 0.982 (4): the Ray Length ramp is not involved.
  R-only albedo sweep at G, B = 0.38, 0.49: R 0.15 -> 1.043, 0.30 -> 1.005, 0.48 -> 0.989, 0.75 -> 0.980 (SE 0.002-0.004): smooth and monotone in the albedo's R, which is a chroma law, not a defect.
  The patch proxy at the exact ramp colour reproduces it: Astroray 0.986, Mitsuba 0.987. Per-seed 0.975, 0.987, 0.989, 0.975: the gate seed is a low draw on a 1.8-point shift.
- wood `grain_center` r per seed 0.953, 0.978, 0.994, 0.981: the gate seed is the outlier.
- Saturation sweep under the stage lighting (patches, Astroray = Mitsuba to 0.003): b 0.98 (wood light), 0.958 (wood), 0.953 (wood dark), 0.948 (car), 0.939 (pbr sat), 0.929 (car sat); cyan r 1.19 (above 1).

## Proxy arbitration (smooth HDRI unless noted; full tables in `pkg327-attribution/proxy_smooth_hdri.json`)

| Proxy | ROIs | Astroray/Cycles vs Mitsuba spectral/rgb, largest channel difference | Notes |
|---|---|---|---|
| `arb_chroma_warm` (white world, floor + box) | 3 | 0.004 | box_front b 0.952 vs 0.952: multi-bounce, white light |
| `arb_chroma_warm_sky` (uniform blue sky) | 3 | 0.004 | b **1.08**: the sign flips with illuminant colour; both agree |
| `arb_chroma_warm_hdri` (HDRI only) | 3 | 0.002 | b 0.841-0.902 |
| `arb_chroma_patches` | 10 | 0.005 (cyan r 1.190 vs 1.194) | grey 1.000 vs 1.000 |
| `arb_chroma_bowl_stage` | 2 | 0.009 (inner r 0.755 vs 0.747) | the production-lit bowl |
| `arb_chroma_hero_wood / car / pbr` | 12 | 0.003 | lighting matched to Cycles within 1 % per ROI (C/Mr 0.991-0.998) |
| `arb_chroma_bowl` (white world, no direct light) | 3 | r only: 0.026 vs **-0.094** | G, B within 0.003 |

`arb_chroma_bowl`: Mitsuba's spectral red is **negative** (unclipped); Astroray's film clips it to +0.026 of Cycles. The collapse is reproduced; the magnitude differs by Astroray's own
negative-tristimulus clip (#1024, a stated non-goal). With direct light (`bowl_stage`) the red stays positive and the two agree to 0.009.

## Engine-bug candidates

None among the target channels. Each is bounded as follows.

1. wood `grain_center` r: remainder 1.2 points at 2.4 sigma (8 seeds, SE 0.005), the same sign as the spectral shift, no mechanism found. Not a bug claim. If Phase B pins this channel, seed-calibrate the pin; more seeds would settle whether the remainder is real.
2. light_path `floor_near` r: remainder 0.4 points at 1.6 sigma. Nothing to fix.
3. Side findings outside the target list, with no Mitsuba arbitration, for the owner to file or drop:
   - curves `outer_front` reads 0.989 (SE 0.001) in all channels under `grey_flat`, 0.982-0.989 under `world_flat_white` alone: a 1.1-point **achromatic** deficit that cannot be spectral. Baseline L is 0.997.
   - pbr_group `centre` reads 0.978-0.981 under a grey albedo with the HDRI (SE 0.009) and 1.000 under a flat white world: a weak (2 sigma) HDRI-conditional achromatic deficit.
   - light_path `floor_far` reads 1.012-1.016 under a Lambertian floor against 1.006 baseline (CPU); the GPU-only +2.5 % item (#1156-adjacent) is out of scope.
4. Tool caveat, not an engine finding: Mitsuba spectral on the raw HDRI sun (see Method).

## Phase B inputs

Per owner 2026-10-31 a channel is pinned when Mitsuba reproduces it. All ten are reproduced. Pin candidates by gate failure at seed 278, per channel and never per ROI, on Astroray's own seed mean:
curves inner_backface r; wood grain_center b, grain_right b, lower b; car_paint lit_front b, upper_flake b; pbr_group lower b. wood grain_left b passes on its own. wood grain_center r fails at its 8-seed mean (0.972 vs 0.024) and is a pin
candidate with remainder 1 above. light_path floor_near r passes at its 8-seed mean (0.982 vs 0.020) and fails only at the gate seed; a pin is defensible, not required.
The pin must cite `arb_chroma_hero_*` / `arb_chroma_bowl_stage` / `arb_chroma_patches` with the smooth HDRI, not the raw one. The `*_hdri` and `_patches` scenes are not render-gated (`render_gate` false), so default `--suite arbitration` runs are unchanged.

## Evidence and reproduction

Committed: this document, `.astroray_plan/docs/pkg327-attribution/{production_variants,target_channels,proxy_smooth_hdri,proxy_raw_hdri}.json`, the proxy scenes and manifest entries, `calibration.json` (`arb_chroma_stage`).
Local frames and renders: `%LOCALAPPDATA%\astroray-evidence\2026-11-01\p327\{work,work_proxy,work_decomp}` and contact sheets `sheet_*.png` (e.g. `sheet_curves.png`: Cycles vs Astroray, baseline over flat white world).

```
set ASTRORAY_PYD_DIR=%LOCALAPPDATA%\astroray-evidence\2026-11-01\dist_batch_931dd0af
set E=%LOCALAPPDATA%\astroray-evidence\2026-11-01\p327
set A=python benchmarks/reference_corpus/arbitration/attribution.py
%A% blender --work-dir %E%\work                                   REM 5 scenes x variants x 4 seeds, Cycles then Astroray CPU, 64 spp
%A% blender --work-dir %E%\work --scenes prod_light_path prod_wood --variants baseline --seeds 6113 7351 8209 9181
%A% table --work-dir %E%\work --json %E%\attrib_blender.json
%A% smooth-hdri --out %E%\hdri_smoothsun.hdr & set ASTRORAY_ATTRIB_SMOOTH_HDRI=%E%\hdri_smoothsun.hdr
blender -b --factory-startup --python benchmarks/reference_corpus/arbitration/build_arbitration.py -- --scenes arb_chroma_bowl arb_chroma_warm arb_chroma_warm_sky arb_chroma_warm_hdri arb_chroma_patches arb_chroma_bowl_stage arb_chroma_hero_wood arb_chroma_hero_car arb_chroma_hero_pbr
set S=arb_chroma_patches arb_chroma_bowl_stage arb_chroma_hero_wood arb_chroma_hero_car arb_chroma_hero_pbr arb_chroma_warm_hdri
%A% blender --manifest arb --work-dir %E%\work_proxy --scenes arb_chroma_bowl arb_chroma_warm arb_chroma_warm_sky %S% --variants baseline hdri_smooth --spp 256   REM hdri_smooth exists for the HDRI scenes only
%A% mitsuba --work-dir %E%\work_proxy --scenes arb_chroma_bowl arb_chroma_warm arb_chroma_warm_sky --spp 1024
%A% mitsuba --work-dir %E%\work_proxy --scenes %S% --spp 1024                                  REM raw HDRI, record only
%A% mitsuba --work-dir %E%\work_proxy --scenes %S% --spp 1024 --hdri %ASTRORAY_ATTRIB_SMOOTH_HDRI% --tag=-smooth
%A% calibrate-stage --work-dir %E%\work_proxy
%A% proxy --work-dir %E%\work_proxy --blender-variant hdri_smooth --tag=-smooth --json %E%\attrib_proxy_smooth.json
```

Build id and module hash of every Astroray leg are in the per-render `.log` (`PKG119B_LEG REPORT`). Tests: `tests/test_pkg327_attribution.py`; `tests/test_pkg307_noise_bench.py` still passes with the new `PARAMS`.
