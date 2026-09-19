# pkg275 — HDRI reflection lookup gap: mirror metal ~23% under Cycles and CPU/GPU env-lookup divergence

**Pillar:** 3
**Track:** A
**Status:** done — 2026-09-19 (PR #829): ladder falsified the "env lookup" premise; lookups byte-faithful CPU/GPU (rungs 2/5/6), #755 not reproducible (rung 8), #795 23% not reproduced (rung 9, robust median R0.96/G1.11/B1.02, residual = spectral-vs-RGB skew), half-texel nit -> #832
**Estimated effort:** 2 sessions (~6 h)
**Depends on:** pkg258

---

## Goal

Before: a mirror/rough-metal reflection of the HDRI is ~23% dimmer than Cycles
on the corpus chrome hero while a uniform-environment furnace is exact, and the
CPU and GPU legs disagree systematically on the env-only parity scene; the
causal step in the environment-map reflection lookup is unknown. After: the
defective lookup step is root-caused with a decisive diagnostic ladder, fixed
so the chrome-sphere ROI ratio vs Cycles lands inside [0.95, 1.05] per channel
and the CPU/GPU env-only mean gap is within 3x the RNG floor, with texel-exact
CPU and GPU lookup probes and an extended mirror-sphere parity gate pinning
each.

---

## Context

Serves Pillar 3 (Cycles parity). #795 measured, on the `world_sky_hdri` corpus
chrome hero (metallic=1.0, roughness=0.05): whole-rect reflection ROI
[0.977, 0.985, 0.981], sphere-masked [0.772, 0.775, 0.773]; background
[0.999, 1.01, 0.999] and indirect [0.963, 0.954, 0.95]. A white-furnace run at
the corpus chrome F0=(0.9, 0.9, 0.92) gives furnace/F0 = [1.0002, 1.0044,
0.9846] at r=0.05 (F0=1 control mean 0.9954), so the conductor lobe conserves
energy and the deficit is the env-map reflection LOOKUP, not the BSDF. #755
measured GPU/CPU per-channel mean ratios on the env-only HDRI parity scene:
R 1.0253 (cpu 0.457456 / gpu 0.469012), G 1.0400 (0.014391 / 0.014967),
B 0.9783 (0.475410 / 0.465085), vs a CPU two-stream proxy
|ratio-1| = 0.02 % (R), 0.14 % (G), 0.04 % (B) — 15-200x the RNG floor.

---

## Evidence

- 2026-09-12: #795 — chrome sphere-masked ROI [0.772, 0.775, 0.773]; whole-rect
  reflection [0.977, 0.985, 0.981]; background [0.999, 1.01, 0.999]; indirect
  [0.963, 0.954, 0.95]; white-furnace furnace/F0 = [1.0002, 1.0044, 0.9846] at
  r=0.05 (F0=1 control mean 0.9954, blue = 0.985x F0); PR #805 (re-baseline),
  PR #809 (furnace, Batch I item 1).
- 2026-09-08: #755 — GPU/CPU env-only mean ratios R 1.0253 / G 1.0400 /
  B 0.9783; CPU two-stream proxy |ratio-1| = 0.02 / 0.14 / 0.04 %; found by
  pkg237 PR #754.
- 2026-09-08: pkg258 (PRs #747, #751) fixed the env sampler azimuth and added
  env NEE + power-heuristic MIS on CPU and GPU; the env lookup itself
  (`EnvironmentMap::lookup` / `evalSpectral`, `gpu_envmap_lookup`) was not the
  target.
- 2026-09: #797 / PR #798 — flat Radiance `.hdr` decode (stb goto-into-loop
  fallback) miscompiled by MinGW GCC 15.2; previously read as an
  `EnvironmentMap::lookup` bug, hence the load path must be probed explicitly.

---

## Reference

- Cycles `intern/cycles/kernel/svm/svm_image.h` (image texture interpolation,
  `svm_image_texture`) and `intern/cycles/kernel/light/background.h`
  (`background_light_sample` / `background_light_pdf`) — Apache-2.0. Cycles
  performs no mip / derivative-based blur for background lookups (only the
  background CDF), so a glossy reflection must return the unblurred bilinear
  texel.
- Astroray lookup functions: `EnvironmentMap::lookup` (`include/raytracer.h:1545`),
  `EnvironmentMap::evalSpectral` (`include/raytracer.h:1601`),
  `gpu_envmap_lookup` (`include/astroray/gpu_bvh.h:652`),
  `include/astroray/gpu_env_spectral.cuh` (GPU spectral env sample).
- Existing test binding: `environment_lookup` (`module/blender_module.cpp:3747`,
  pkg258); existing gate: `tests/test_world_hdri_parity.py`.
- Design doc: `.astroray_plan/docs/cycles-world-parity-research.md`;
  `pkg237-hdri-cpu-gpu-ssim-diagnosis.md`, `pkg258-hdri-environment-nee-importance-sampling.md`.

---

## Prerequisites

- [ ] pkg258 is done and tests are green.
- [ ] Build passes on main; `build_cuda/astroray.cp313-win_amd64.pyd` newer
      than HEAD before any GPU number is quoted.
- [ ] `cite-algorithm` research note saved under `.astroray_plan/docs/` before
      changing lookup code (Cycles `svm_image` / `background` semantics, chosen
      filtering and parameterisation recorded).
- [ ] GPU lock held for every CUDA build and GPU gate run.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg275_env_lookup_probe.py` | Texel-exact probe for ladder steps 2 and 5: sample the environment at a fixed set of known directions through `environment_lookup` (and the GPU lookup path) and compare against a numpy bilinear reference computed on the loaded float image, on both backends, tolerance 1e-3 relative. |
| `.astroray_plan/docs/pkg275-env-lookup-research.md` | `cite-algorithm` note: Cycles `svm_image` / background lookup semantics, chosen filtering, and the diagnostic-ladder measurements. |

### Files to modify

| File | What changes |
|---|---|
| `tests/test_world_hdri_parity.py` | Add a mirror-sphere ROI mean-ratio gate vs Cycles within 5 % per channel (GPU-marked), extending the env-only parity test. |
| `include/raytracer.h` | Only the step the ladder localises: `EnvironmentMap::lookup` / `evalSpectral` filtering, half-texel offset, row flip, or sRGB/linear load; no change if the defect is CPU/GPU-only. |
| `include/astroray/gpu_bvh.h` | `gpu_envmap_lookup` mirrored to the CPU fix so the two backends agree. |
| `include/astroray/gpu_env_spectral.cuh` | GPU spectral env lookup mirrored to CPU `evalSpectral` if step 6 implicates spectral upsampling. |
| `src/gpu/wavefront/stage_advance.cu` | Env miss leg (pkg258 MIS weight) only if the #755 divergence is in the wavefront advance path. |
| `module/blender_module.cpp` | Only if the probe needs a binding the existing `environment_lookup` / `sample_environment_map` pair does not cover. |

### Key design decisions

- **Diagnose before fixing.** Run the ladder in order; each rung must be
  decisive on its own (a measurement plus an expectation that would falsify the
  remaining hypotheses). Only the localised step is changed — do not touch the
  env lookup speculatively.
- **Texel-exact oracle, not a render.** Steps 2 and 5 bypass the integrator and
  compare the binding's lookup against a numpy bilinear decode of the same
  float image, so a mismatch cannot be an MC or MIS artefact.
- **Reuse the existing probe binding.** `environment_lookup` (pkg258) already
  exposes the CPU RGB bilinear lookup; add a GPU probe only if step 5 cannot be
  driven through the existing surface.
- **No mip/blur unless Cycles has it.** If Cycles returns the unblurred
  bilinear texel for a background lookup, Astroray must too; any
  roughness-dependent dimming that survives is the bug.

#### Diagnostic ladder (ordered)

1. **Uniform-env vs HDRI through the same chrome sphere on CPU** (done in
   #809 — cite it). Measurement: white-furnace `furnace/F0` at the corpus
   chrome F0=(0.9, 0.9, 0.92), r=0.05, versus the same sphere under the HDRI.
   Decisive expectation: the furnace is exact (≈1.0) while the HDRI sphere is
   ~0.77x Cycles — clears the conductor BSDF and isolates the env reflection
   lookup (if the HDRI sphere also conserves, the issue is not the lookup).
2. **Texel-exact probe: known directions through the engine binding vs numpy
   bilinear on the loaded float image.** Catches filtering / half-texel offset /
   row flip / gamma-on-load. Decisive expectation: every probe direction agrees
   within 1e-3 relative per channel; a constant texel-index offset means a
   half-texel/parameterisation bug, a row-order mismatch means a flip bug.
3. **sRGB-vs-linear on load and the flat-`.hdr` decode path** (#797 / #798
   history). Measurement: decode a known-gradient flat `.hdr` and compare the
   row-exact lookup on each compiler/build. Decisive expectation: values are
   linear on load (no sRGB transform) and rows are not striped; MSVC and MinGW
   agree.
4. **Mip/blur on glossy lookups.** Check Cycles `kernel/svm/svm_image.h` +
   `background.h` and cite that background lookups use no mip. Measurement:
   probe a high-frequency env at increasing mirror roughness. Decisive
   expectation: Astroray returns the unblurred bilinear texel, matching Cycles;
   a roughness-dependent dimming is the divergence.
5. **CPU vs GPU texel-exact probe** (same directions through the wavefront env
   lookup) for #755. Decisive expectation: the two backends return identical
   values within 1e-3 relative; a deterministic offset localises #755 to the
   GPU lookup and removes Monte Carlo from the question.
6. **Spectral upsampling of the HDRI RGB (Jakob-Hanika) vs Cycles RGB.**
   Measurement: quantify with a grey HDRI (which should be exact) versus the
   colour HDRI. Decisive expectation: the grey HDRI gives CPU/GPU ratio 1.000
   and Astroray/Cycles 1.000; any residual colour-HDRI offset is the spectral
   upsampling skew, not the lookup.

---

## Acceptance criteria

Re-scoped 2026-09-19 after the diagnostic ladder. The original premise — "the defective step is in the environment-map reflection
LOOKUP" — was falsified by the texel-exact ladder. The lookup is byte-clean on
both backends, so the two render-level parity gates below cannot be met by a
lookup change and are reassigned per the evidence (research note + PR #829).

- [x] `tests/test_pkg275_env_lookup_probe.py` green on CPU and GPU at 1e-3
      relative tolerance — texel-exact CPU/GPU RGB and spectral probes
      (rungs 2/5/6: 1.9e-7 / 2.25e-7 / 4.94e-6).
- [x] Env lookup + RGB->spectral upsample verified byte-faithful across CPU and
      GPU (the actual, testable pkg275 outcome that replaces the "chrome ROI in
      [0.95,1.05]" gate).
- [x] #755 shown NOT reproducible with adaptive OFF + shared exposure (rung 8:
      GPU/CPU chrome [1.0003, 0.9998, 1.0010]); rung-8 posted on #755 with a
      close-as-not-reproducible recommendation. The original 15-200x gap was the
      pkg237 stopping-metric artefact, not the lookup.
- [x] #795 controlled Cycles-vs-Astroray experiment (rung 9): the 23% deficit
      does not reproduce; robust per-pixel median ratio R 0.96 / G 1.11 / B 1.02;
      F82 Fresnel and ground both rejected; residual is a green-biased
      spectral-vs-RGB pipeline difference, not a lookup/conductor bug.
- [x] Half-texel offset (only lookup-vs-Cycles nit) filed as low-priority
      issue #832 with the Cycles `svm_image` citation (lead: no fleet-wide
      lookup churn in this PR).
- [x] Saved before/after renders qualitatively inspected under
      `test_results/pkg275/` (no visual regression; lookup unchanged).

NOTE: the extended `tests/test_world_hdri_parity.py` mirror-sphere-vs-Cycles
gate is intentionally NOT added — a lookup-clean engine cannot host a
vs-Cycles chrome gate without a committed Cycles reference, and the residual it
would measure is the spectral-pipeline chromatic skew owned outside pkg275.

---

## Non-goals

- Do not change the conductor BSDF — cleared by the white furnace (#795).
- Do not change the light tree (pkg86 owns tree inclusion).
- No new environment sampling strategies (CDF / NEE / MIS) — pkg258 owns them.
- No threshold relaxation on any existing parity gate.
- No HDRI rotation, tint, strength, or colour-management change without a
  ladder step that implicates the load path.

---

## Progress

- [x] Step 1 — diagnostic ladder run in order (rungs 1-9), each rung's
      measurement + verdict recorded in
      `.astroray_plan/docs/pkg275-env-lookup-research.md`.
- [x] Step 2 — CPU/GPU texel-exact probe landed
      (`tests/test_pkg275_env_lookup_probe.py` + `probe_env_lookup_gpu`
      binding). No localised lookup fix was warranted: the ladder proved the
      lookup is clean; the half-texel nit is deferred to issue #832.
- [x] Step 3 — instead of a vs-Cycles mirror gate (impossible for a
      lookup-clean engine without a committed reference), ran the controlled
      Blender Cycles-vs-Astroray experiment (rung 9) and recorded the #795
      verdict + the #755 non-reproducibility (rung 8).

---

## Lessons

- The spec premise (lookup bug) was falsifiable and false — texel-exact probes
  are the right first move before any lookup edit; they cleared both #755 and
  #795 in minutes and saved a speculative fleet-wide change.
- A sphere-masked MEAN ratio over a specular highlight is a trap: a few
  reflected-sun hot pixels moved the mean to 1.68 while the per-pixel median was
  ~1.0. Report robust statistics (median/percentiles + a ratio map) for glossy
  ROI parity, not the mean — this is what flipped "23% dim" into "~10% green
  chromatic skew".
- The residual is a spectral-vs-RGB pipeline difference (Astroray upsamples the
  HDRI RGB via Jakob-Hanika and renders spectrally; Cycles is RGB). That is the
  right home for any further #795 follow-up, not the env lookup.
