# Issue audit fact sheet — 2026-09-15-A

Facts gathered from `git log`, `gh pr list --state merged --search`, `gh issue view --comments`, and greps of `.astroray_plan/packages/`, `.astroray_plan/docs/STATUS.md`, `include/`, `blender_addon/`, `tools/`, `scripts/`. No recommendations; evidence only.

## #818 Procedural texture -> Math/Mix/Ramp chains flatten to a constant (op-VM accepts image-texture inputs only)
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** none (topic match: pkg219-per-texel-shader-graph — Status: DONE (2026-08-30). Staged scope shipped + HW-verified across three sub-packages - pkg219a coordinate/3-D-Mapping unification (PR #640), pkg219b bounded op-VM core: Color Ramp / Mix / Math / Map Range on textu...)
- **STATUS.md mentions:** L16: "...zimuth first, then re-run parity. (c) **#818 (P1)**: procedural textures through Math/Mix/Ramp chains flatten to a constant because the op-VM accepts image-texture inputs only; coordinate-side Separat..."
- **Code evidence:** `include/astroray/shader_vm.h` (op-VM core); `include/astroray/gpu_scene_upload.h`
- **Last issue comment:** no comments

## #817 Viewport worker (pkg266): no presentation while orbiting; refinement stuck at reduced resolution
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** none (topic match: pkg266-viewport-phase2-3-bounded-cancel-and-commit — Status: done - PR #812 merged 2026-09-13: present-rate=0 root-caused to two bugs (spurious view_update over-cancel; orphaned worker holding the global admission token) and fixed; chunk-spp column; 9 gate table on th...)
- **STATUS.md mentions:** L16: "...ent stuck at the first-unit resolution (#817, P1); `ASTRORAY_VIEWPORT_WORKER=0` restored the old behaviour, so the 9 driver (object-transform edits) never exercised real navigation. (b) **#814 re-sco..."
- **Code evidence:** `blender_addon/exporter.py` (ASTRORAY_VIEWPORT_WORKER opt-in flag)
- **Last issue comment:** no comments

## #814 Nishita sun-disc ground irradiance ~1.48x over Cycles + IES/spot composition check
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** none (topic match: pkg256-sky-texture-node — Status: done - 2026-09-11, PR #793 (merged 54299766). Preetham/Perez 1999 sky bake (appleseed MIT constants) to a 1024x512 flat-RGBE equirect (55 ms) fed through the HDRI path; Cycles A/B on world_sky_sky: sky-band l...)
- **STATUS.md mentions:** L5: "...- **#809 #810 #811 #812 #813**; filed **#814** (sun-disc irradiance residual + IES spot composition). Owner decisions applied and recorded in `north-star-and-integration-gate-2026-09-07.md` 7 (2026-0..." ; L7: "...so the ROIs compared different patches; #814 is now a sun-direction bug first; (3) pkg270 (blackbody spectral Planck) and pkg269 (GPU volumes) are next in the volumes track...."
- **Code evidence:** `include/astroray/nishita_sky.h`; `blender_addon/sky_bake.py`
- **Last issue comment:** 2026-09-13T13:29:14Z — "Owner + lead re-check 2026-09-14 (visual, `test_results/batch_j/gate2_strip_{cycles,astro}.png`, both rendered after the #813 azimuth fix, same camera): the sun DIRECTION still differs from Cycles. Cycles casts every shadow to the left (long horizontal sphere streak, cube shadows left); Astroray's sphere shadow drops toward the camera and the cube shadows fall to the RIGHT. The gate-2 ROI therefore sits on Cycles' sphere shadow but on lit deck in ours, so the 17.4:1 vs 10.2:1 ratio and the derived '~1.48× over-bright disc' compare different patches and are **invalid**..."

## #807 geometry_zoo volume cabinet: Principled Volume renders as a solid yellow disc (pkg268 acceptance)
- **Merged PRs mentioning it:** `#810 feat(batch-f): pkg267 NanoVDB grid + Blender OpenVDB import + majorant; pkg268 CPU heterogeneous volume transport (#807)`
- **Specs mentioning it:** pkg268-cpu-heterogeneous-volume-transport (Status: done - PR #810 merged 2026-09-13 (c231f27d): delta tracking + ratio tracking + HG/isotropic phase + Principled Volume basics (Cycles svm_node_principled_volume coefficient mapping after the cycles-parity revi...); pkg270-principled-volume-emission-blackbody-spectral (Status: open)
- **STATUS.md mentions:** L11: "... pkg270. Specs pkg267/pkg268 done. #807 cabinet corpus A/B: see below...." ; L16: "...erpreter shutdown (noise seen after the #807 headless render; addon-only, no engine change). Addon restaged from b81cbe7a and installed (build id `b81cbe7+20260913T131222Z`; headless enable OK, `nishi..."
- **Code evidence:** `include/astroray/volume/grid_medium.h`; `include/astroray/volume/principled_volume.h`; `include/astroray/volume/volume_transport.h`
- **Last issue comment:** 2026-09-13T11:23:24Z — "pkg268 landed in #810 (2026-09-13). Cabinet re-rendered on the restaged main addon (`render_leg.py`, CPU, 960×220 @ 96 spp; refs regenerated): the solid yellow disc is gone. The Volume Absorption and Volume Scatter cubes now render as translucent boxes like Cycles' faint cubes (ours brighter — the chromatic colours are approximated with grey extinction and warned; per-λ σ is pkg270). The Principled Volume cube renders dark where Cycles shows the soft orange patch: that patch is **emission** (`Emission Strength` 1.4, colour (1.0, 0.45, 0.10) on a density-3 blue-scatter volume), which pkg268 does not honour..."

## #799 pkg256 Phase 2: absolute-exposure sky parity (engine-side spectral sky)
- **Merged PRs mentioning it:** `#813 feat(batch-j): #799 Phase 2 engine-side Nishita sky (Apache/MIT vendored, spectral) with a model-consistent sun disc; absolute IES photometry (Cycles 4pi/177.83)` ; `#808 feat(batch-e1): sky sun disc + exposure decomposition (#799 part 1), textured mesh emitters in NEE/light tree (#776)` ; `#793 feat(pkg256): Blender Sky Texture node -> Preetham/Perez equirect bake`
- **Specs mentioning it:** pkg256-sky-texture-node (Status: done - 2026-09-11, PR #793 (merged 54299766). Preetham/Perez 1999 sky bake (appleseed MIT constants) to a 1024x512 flat-RGBE equirect (55 ms) fed through the HDRI path; Cycles A/B on world_sky_sky: sky-band l...)
- **STATUS.md mentions:** L5: "...lute IES photometry, sun-disc verdict #799 Phase 2. Main `build_cuda` rebuilt after all merges; addon restaged `--backend cuda` and **installed** into the user profile (the Batch G/I/J lanes had ins..." ; L14: "...ch J - lighting physics** (98dfb48e): **#799 Phase 2** engine-side Nishita sky vendored from Blender `intern/sky` (`sky_single_scattering.cpp` Apache-2.0, `sky_multiple_scattering.cpp` MIT, clean-room..."
- **Code evidence:** `include/astroray/nishita_sky.h`; `blender_addon/sky_bake.py`
- **Last issue comment:** 2026-09-13T11:09:33Z — "Phase 2 landed in PR #813 (98dfb48e, 2026-09-13): engine-side Nishita sky vendored from Blender `intern/sky` (single scattering Apache-2.0, multiple scattering MIT, clean-room replacements for the two GPL headers), exposed as `astroray.nishita_sky` / `nishita_sun`; the addon uses it for SINGLE_/MULTIPLE_SCATTERING and derives the dedicated sun disc from the same model (`precompute_sun`), so the 1/1766 bridge is gone for Nishita..."

## #795 Chrome/conductor reflection ~23 % under Cycles
- **Merged PRs mentioning it:** `#809 feat(batch-i): parity fill — #795 chrome A/B, pkg242 #737 follow-ups, pkg201 closeout, #773 root-cause, #767/#763/run_parity scoped` ; `#805 feat(batch-a): spot IES export, Diffuse BSDF specular-0, World Mapping sockets, Render Region, HDRI re-baseline` (Batch A item 5 measurement)
- **Specs mentioning it:** none (topic matches: pkg124-vndf-sampling — Status: open - dispatchable (**UNBLOCKED 2026-07-23**: pkg123/PR #498 merged 2026-07-21 as `587b554` with the chi gates un-xfailed - the swap now measures against a green baseline. Coordinate with pkg138/pkg145: all...; pkg152-gpu-disney-metal-residual-dimness — Status: superseded - metal-dim symptom does not reproduce (pkg165); the rough-transmission furnace deficit is owned by pkg179 Part 2 (2026-09-07 backlog triage))
- **STATUS.md mentions:** L10: "...-VISUAL 3 / LIMITATION 2; spec done), #795 CPU metal white-furnace clears the conductor lobe (furnace/F0 1.000/1.004/0.985 at r=0.05 the deficit is the env-map reflection lookup; posted), #773 r..." ; L31: "...the ABI review) + F12/viewport border, **#795** check-first: corpus chrome roughness 0.05 not multi-scatter; decisive A/B (uniform env vs HDRI through metal_ab) posted. Reviews: cpp-abi-guard + cycle..."
- **Code evidence:** `include/astroray/energy_compensation.h`; `include/astroray/gpu_materials.h` (conductor Fresnel)
- **Last issue comment:** 2026-09-12T23:17:56Z — "**Batch-I in-process CPU metal white-furnace — the ~23% reflection deficit is NOT in the conductor BSDF.** I rendered a Disney metallic=1 sphere under a uniform white environment (radiance 1.0, linear, apply_gamma=False, 256 spp) at the corpus chrome base colour `(0.9, 0.9, 0.92)` and at the F0=1 control, CPU (`build_cpu`, CUDA OFF, this branch). Under a uniform env an energy-conserving conductor reflects ~F0, so `furnace/F0` is the conductor lobe's energy ratio..."

## #789 Rough-glass multiple-scattering walk is achromatic (pkg265)
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** pkg265-multiscatter-microfacet-glass (Status: done - CPU leg MERGED 2026-09-10 (PR #778, b09e2713; cycles-parity review 3 MERGE, cpp-abi-guard MERGE; GPU leg = Phase 3, #782 independent oracle pending, #783 thin-film walk, #789 achromatic walk). Note: `t...)
- **STATUS.md mentions:** L57: "...tic-bound-first`). Follow-ups #782/#783/#789...."
- **Code evidence:** `include/astroray/microsurface_dielectric.h` (Heitz 2016 multiple-scattering Smith dielectric)
- **Last issue comment:** no comments

## #783 Thin-film-aware multiple-scattering microfacet glass walk (pkg265 follow-up)
- **Merged PRs mentioning it:** `#778 feat(pkg265): multiple-scattering microfacet dielectric (Heitz 2016) — CPU leg`
- **Specs mentioning it:** pkg265-multiscatter-microfacet-glass (Status: done - CPU leg MERGED 2026-09-10 (PR #778, b09e2713; cycles-parity review 3 MERGE, cpp-abi-guard MERGE; GPU leg = Phase 3, #782 independent oracle pending, #783 thin-film walk, #789 achromatic walk). Note: `t...)
- **STATUS.md mentions:** L57: "...tic-bound-first`). Follow-ups #782/#783/#789...." ; L90: "...EDGREEN test; thin-film-aware walk **#783**). **Running at handoff (Opus 4.8, `../Astroray-pkg265gpu`):** the paper's stochastic eval (Eq 42) with a hash-seeded RNG (pbrt-v4 `LayeredBxDF` pattern),..."
- **Code evidence:** `include/astroray/thin_film_fresnel.h`; `include/astroray/microsurface_dielectric.h`
- **Last issue comment:** no comments

## #779 run_parity: astroray-cpu leg for .blend scenes goes through tools/blend_import (base-colour-only)
- **Merged PRs mentioning it:** `#778 feat(pkg265): multiple-scattering microfacet dielectric (Heitz 2016) — CPU leg` (pkg265 spec records #779 run_parity honesty complete)
- **Specs mentioning it:** pkg265-multiscatter-microfacet-glass (Status: done - CPU leg MERGED 2026-09-10 (PR #778, b09e2713; cycles-parity review 3 MERGE, cpp-abi-guard MERGE; GPU leg = Phase 3, #782 independent oracle pending, #783 thin-film walk, #789 achromatic walk). Note: `t...)
- **STATUS.md mentions:** L88: "...#773 (addon r0 glass limb -15 %), #776, #779 (run_parity .blend Astroray leg is base-colour-only - the new glass row is a diffuse proxy), #780 (addon CPU renders single-threaded), #782 (independent ex..." ; L90: "...parity row is labelled a diffuse proxy (#779). GPU leg = Phase 3...."
- **Code evidence:** `tools/blend_import/blend_to_astroray.py`; `scripts/run_parity.py`
- **Last issue comment:** 2026-09-08T23:55:13Z — "The side finding (`BlendFile.by_old` silently overwriting on an old-pointer collision across mesh datablocks) is fixed by #784 (DATA pointers now resolve within their owning ID block; ambiguous unscoped lookups raise). The base-colour-only limitation of the run_parity Astroray leg — the main point of this issue — is unchanged."

## #773 Rough-glass A/B: the ADDON render path loses ~15 % at the r=0 limb
- **Merged PRs mentioning it:** `#809 feat(batch-i): parity fill — #795 chrome A/B, pkg242 #737 follow-ups, pkg201 closeout, #773 root-cause, #767/#763/run_parity scoped`
- **Specs mentioning it:** none (topic match: pkg264-rough-glass-transmission-energy-cycles-parity — Status: done - PR #771 merged 2026-09-08 (scoped fix delivered; the 5 % Cycles-parity criterion is NOT met and is re-scoped to #770): the native Principled transmission sampler returned absorbing dead microfacet sam...)
- **STATUS.md mentions:** L10: "...the env-map reflection lookup; posted), #773 root-caused to `principled.cpp` grazing dead-sample discard (pkg264 owner, posted). #767 / #763 / run_parity `textured_emitter`+`sky_sun` scoped with recip..." ; L88: "... glass), pkg266 (viewport P2.3); issues #773 (addon r0 glass limb -15 %), #776, #779 (run_parity .blend Astroray leg is base-colour-only - the new glass row is a diffuse proxy), #780 (addon CPU render..."
- **Code evidence:** `plugins/materials/principled.cpp` (transmission lobe grazing dead-sample discard, ~:1986)
- **Last issue comment:** 2026-09-12T23:41:22Z — "**Batch-I — reproduced on the current engine + root-caused (CPU, staged CPU-backend addon vs Cycles-CPU, 200²/128 spp).** Fresh glass A/B (`benchmarks/cycles-parity/metal_ab/harness.py --material glass`), per-channel astroray/Cycles by ROI: | roughness | centre | **limb** | background | ... The **r=0 limb sits at 0.837× Cycles** (centre and background match) — i.e. this issue's addon limb deficit reproduces exactly (issue: addon 0.232/Cycles 0.284 = 0.815)..."

## #767 HDRI-lit Principled ground: blue channel still 5 % under Cycles after pkg261
- **Merged PRs mentioning it:** `#809 feat(batch-i): parity fill — #795 chrome A/B, pkg242 #737 follow-ups, pkg201 closeout, #773 root-cause, #767/#763/run_parity scoped` ; `#794 fix(786/787): apply world Mapping yaw in Blender space before the env basis change`
- **Specs mentioning it:** pkg261-principled-rough-diffuse-energy-loss (Status: done - PR #766 merged 2026-09-08: Cycles' lobe-averaged `ggx_gen_schlick_ior_s` table ported (extractor + .bin + CPU/GPU lookup), specular + coat layering albedo = mix(f0, 1, s); roughness sweep within 2.2-2....)
- **STATUS.md mentions:** L10: "...-sample discard (pkg264 owner, posted). #767 / #763 / run_parity `textured_emitter`+`sky_sun` scoped with recipes, not executed...." ; L130: "...  0.926 0.962 (blue-skew residual **#767**). cycles-parity-reviewer + cpp-abi-guard MERGE; the..."
- **Code evidence:** `include/astroray/energy_compensation.h` (ggx_gen_schlick_ior_s LUT)
- **Last issue comment:** 2026-09-12T23:53:13Z — "**Correction (lead): not GPU-blocked — a CPU-backend addon is now staged** (`dist/astroray`, `--backend cpu`, cuda=False). These tests are runnable headless on the CPU; I did not complete them this batch for time, but the exact recipe for a fast follow-up: 1. **Test (1) grey ground under HDRI** and **test (2) coloured ground under flat-white world**: render through the staged addon headless (`blender -b` + `ASTRORAY_PYD_DIR=dist/astroray`, like `benchmarks/blender_parity/render_leg.py`) so the **spectral** upsampling path is active..."

## #763 Corpus scenes: Astroray CPU at 128 spp far noisier than Cycles CPU at 128 spp
- **Merged PRs mentioning it:** `#809 feat(batch-i): parity fill — #795 chrome A/B, pkg242 #737 follow-ups, pkg201 closeout, #773 root-cause, #767/#763/run_parity scoped` ; `#788 feat(pkg262): default-on progressive sampler / light tree / GPU adaptive sampling (fixes #759)`
- **Specs mentioning it:** pkg259-cycles-feature-coverage-reference-scenes (Status: done - 2026-09-13: all five families landed (Phase 1 #761/#781, Phase 2 #785, Phase 3 #806 fb0932a3: geometry_zoo 17 rows, camera_lens 9, render_settings 4; manifest tests 34/34; lead-inspected contact sheets...); pkg262-default-on-progressive-sampler-light-tree (Status: done - 2026-09-09, PR #788 (merged dedd4853). GPU adaptive sampling now actually engages: fixed a dead `adaptiveOn` gate in `gpu_wavefront_snapshot.cu` that required `alphaOut == nullptr`, unconditionally fal...)
- **STATUS.md mentions:** L10: "... discard (pkg264 owner, posted). #767 / #763 / run_parity `textured_emitter`+`sky_sun` scoped with recipes, not executed...." ; L29: "...F match; Astroray noisier at equal spp (#763); clip_end backdrop = #724; **volume cabinet diverges (Principled Volume solid yellow disc, absorption/scatter cubes flat white) #807**, the first pkg2..."
- **Code evidence:** `include/astroray/sampling/progressive_sobol.h` (pkg224 progressive Sobol); `include/astroray/light_tree.h`
- **Last issue comment:** 2026-09-12T23:53:14Z — "**Correction (lead): not GPU-blocked — a CPU-backend addon is now staged.** Runnable headless; deferred this batch for time (single-threaded corpus renders are slow). Recipe for a fast follow-up: Render `benchmarks/reference_corpus/scenes/materials_hall.blend` through the staged CPU addon headless at a REDUCED, matched spp (e.g. 32) for BOTH engines — per the lead, report **variance ratios** at the stated spp, not absolute timing..."

## #755 CPU vs GPU per-channel mean gap on the env-only HDRI parity scene
- **Merged PRs mentioning it:** `#794 fix(786/787): apply world Mapping yaw in Blender space before the env basis change`
- **Specs mentioning it:** none (topic match: pkg237-hdri-cpu-gpu-ssim-diagnosis — Status: done - replaced the SSIM gate with the per-channel mean-ratio gate in `tests/test_world_hdri_parity.py::test_gpu_cpu_mean_ratio_hdri` (renamed from `test_gpu_cpu_ssim_hdri`); measured on RTX 5070 Ti (build_cu...)
- **STATUS.md mentions:** L111: "...8, SSIM 0.962 printed only. Finding **#755** (CPU-vs-GPU means differ 15-200x the two-CPU-stream floor)...." ; L181: "...two CPU streams (0.02-0.14 %) **issue #755** (systematic env-lookup/spectral gap)...."
- **Code evidence:** `include/astroray/lights/background_light.h` (env lookup path)
- **Last issue comment:** no comments

## #741 Environment NEE absent on every integrator; HDRI CDF sampler uncalled (pkg258)
- **Merged PRs mentioning it:** `#747 feat(pkg258): CPU env NEE — Terra fixes (continuous sampling, delta guard, complementary MIS)` ; `#751 feat(pkg258): GPU wavefront environment NEE`
- **Specs mentioning it:** pkg258-hdri-environment-nee-importance-sampling (Status: done - CPU leg PR #747 + GPU wavefront leg PR #751 (2026-09-08). Sun-disc RMSE ratio NEE on/off 0.526 CPU / 0.522 GPU vs a 65 536-spp reference (gate 0.58); furnace 0.9946 / 0.9952; sampler pdf contract 9e-...)
- **STATUS.md mentions:** L404: "...ment NEE + importance sampling** (issue #741, P1). Lead code..."
- **Code evidence:** `include/astroray/lights/background_light.h` (env NEE / CDF sampler)
- **Last issue comment:** no comments

## #724 Camera clip_start/clip_end are ignored
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** pkg259-cycles-feature-coverage-reference-scenes (Status: done - 2026-09-13: all five families landed (Phase 1 #761/#781, Phase 2 #785, Phase 3 #806 fb0932a3: geometry_zoo 17 rows, camera_lens 9, render_settings 4; manifest tests 34/34; lead-inspected contact sheets...) — camera_lens family carries clip_start/clip_end gap cards)
- **STATUS.md mentions:** L29: "...t equal spp (#763); clip_end backdrop = #724; **volume cabinet diverges (Principled Volume solid yellow disc, absorption/scatter cubes flat white) #807**, the first pkg268 acceptance scene...." ; L524: "...23 missing image dropped silently (P2), #724 clip planes (P3); labels..."
- **Code evidence:** `blender_addon/native_settings.py`; `blender_addon/settings_map.py` (clip_start/clip_end)
- **Last issue comment:** no comments

## #723 Missing environment/image texture file is dropped silently
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** none
- **STATUS.md mentions:** L524: "...ignored (P2), #723 missing image dropped silently (P2), #724 clip planes (P3); labels..."
- **Code evidence:** no matches for a missing-texture warning in `include/` or `blender_addon/` (feature absent)
- **Last issue comment:** no comments

---

| issue | merged PRs | owning spec | last activity |
|---|---|---|---|
| 818 | none | none (topic: pkg219, DONE) | 2026-09-13 (filed; no comments) |
| 817 | none | none (topic: pkg266, done) | 2026-09-13 (filed; no comments) |
| 814 | none | none (topic: pkg256, done) | 2026-09-13 comment |
| 807 | #810 | pkg268 (done) / pkg270 (open) | 2026-09-13 comment |
| 799 | #793 #808 #813 | pkg256 (done) | 2026-09-13 comment |
| 795 | #805 #809 | none (topic: pkg124 open) | 2026-09-12 comment |
| 789 | none | pkg265 (done) | 2026-09-10 (filed; no comments) |
| 783 | #778 | pkg265 (done) | 2026-09-08 (filed; no comments) |
| 779 | #778 | pkg265 (done) | 2026-09-08 comment |
| 773 | #809 | none (topic: pkg264 done) | 2026-09-12 comment |
| 767 | #794 #809 | pkg261 (done) | 2026-09-12 comment |
| 763 | #788 #809 | pkg259 (done) / pkg262 (done) | 2026-09-12 comment |
| 755 | #794 | none (topic: pkg237 done) | 2026-09-08 (filed; no comments) |
| 741 | #747 #751 | pkg258 (done) | 2026-09-07 (filed; no comments) |
| 724 | none | pkg259 (done) | 2026-09-06 (filed; no comments) |
| 723 | none | none | 2026-09-06 (filed; no comments) |