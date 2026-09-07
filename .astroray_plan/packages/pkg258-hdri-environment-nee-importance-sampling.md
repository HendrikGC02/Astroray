# pkg258 — HDRI environment next-event estimation and importance sampling

**Pillar:** 5
**Track:** A
**Status:** in-progress — CPU leg PR (feat/pkg258-2026-09-08); GPU wavefront leg pending a separate PR off this branch
**Estimated effort:** 3 sessions (~9 h; CPU first, then GPU wavefront under the GPU lock)
**Depends on:** pkg63, pkg89, pkg195

---

## Goal

Before: no reachable integrator performs next-event estimation against the
environment map. The HDRI contributes only when a BSDF-sampled ray misses all
geometry, so receivers under a concentrated HDRI (sun disc, window) are lit by
rare lucky misses: high variance, and under Astroray's firefly clamp a
systematically dark mean. The CDF sampler that pkg63 recorded as "already
wired" exists on both CPU and GPU but has no callers and returns a wrong
direction. After: every reachable integrator (in-header spectral path tracer,
CPU wavefront kernel, multiwavelength tracer, GPU wavefront) draws environment
NEE samples from a correct, Cycles-equivalent importance CDF, combines them
with BSDF sampling by the power heuristic, and the sun-disc convergence gate
pkg63 promised but never ran is green on CPU and GPU.

---

## Context

Owner hypothesis (2026-09-07 evening) for the Astroray-vs-Cycles HDRI
background gap (0.047 vs 0.121 on `hdri_exterior_hair`): the Astroray side of
the environment sampling is broken, not the Cycles reference. The lead's code
read the same evening confirms the direction of that hypothesis: environment
NEE is absent everywhere, and the dormant sampler is wrong. This is a Pillar 5
(Blender parity) defect and a gate (c) blocker: any HDRI-lit reference scene
compares an NEE-lit Cycles image against a BSDF-miss-lit Astroray image.
`cite-algorithm` applies: the estimator is PBRT 4e §12.5 / Cycles
`background_light_sample` + `background_light_pdf`; nothing is invented.

---

## Evidence

- 2026-09-07: `include/raytracer.h:3105` comment in `pathTraceSpectral`:
  "No env NEE in pathTraceSpectral, so env always contributes on miss".
  Miss handling at `:3109` and `:3564` is a plain `evalSpectral` lookup.
- 2026-09-07: `envSelectProb()` (`include/raytracer.h:2768`) has no call
  site. `EnvironmentMap::sample` (`:1686`) and `EnvironmentMap::pdf` (`:1746`)
  have no call site. `gpu_envmap_sample` / `gpu_envmap_pdf`
  (`include/astroray/gpu_bvh.h:532`, `:569`) have no call site
  (repo-wide grep over `*.{h,cpp,cu,cuh}`).
- 2026-09-07: `EnvironmentMap::sample` computes
  `phi = (uCont - 0.5f) * 2π` with `uCont = u + 0.5f` in **pixel** units
  (`:1715-1720`); the `/ width` is missing, so the sampled azimuth is
  `2π·u` for integer `u`, i.e. azimuth 0 (plus float rounding) for every
  sample, while `radiance` and `pdf` are read from the correct texel
  `(u, v)`. `gpu_envmap_sample` (`gpu_bvh.h:548-553`) mirrors the bug
  exactly. `pdf(direction)` on both backends uses the correct normalised
  `u = 0.5 + phi/2π`, so sample and pdf disagree with each other.
- 2026-09-07: `src/lights/background_light.cpp:18-55` —
  `BackgroundLight::sampleLi` is a uniform-sphere placeholder (`pdf = 1/4π`,
  comment "Full integration with EnvironmentMap::sample is deferred to
  Phase B"), `power()` returns the stub `1.0f`, and no code constructs a
  `BackgroundLight` (the only other mention is inside
  `external/cycles_light_tree`).
- 2026-09-07: pkg63 Progress claims "Path-tracer NEE already wires env-MIS
  via the existing balance heuristic in `default_integrator.cpp` and
  `path_trace_kernel.cu`". `src/default_integrator.cpp` contains no
  environment reference; `path_trace_kernel.cu` no longer exists. The pkg63
  acceptance gate (sun-disc scene converges 4× faster with MIS) was
  explicitly swapped for a CPU/GPU SSIM gate that cannot detect a missing
  sampler (pkg63 Lessons).
- 2026-09-07: `.astroray_plan/docs/hdri-background-gap-diagnosis-2026-09-07.md`
  measured Astroray CPU 0.047 vs Cycles CPU 0.121 on the background ROI; the
  world-only isolate agrees between engines (0.0347 vs 0.0333) and hiding
  the Ground plane collapses Cycles to the isolate value. Whether the
  ROI's own pixels or the receiver lighting carries the gap is still
  undetermined (lead review note in that doc).

---

## Reference

- PBRT 4e §12.5 "Infinite Area Lights" (`ImageInfiniteLight::SampleLi`,
  `PDF_Li`, `PiecewiseConstant2D`) — the estimator and the equal-area
  parameterisation caveat.
- Cycles `intern/cycles/kernel/light/background.h`
  (`background_light_sample`, `background_light_pdf`,
  `background_map_sample`, `background_map_pdf`) and
  `intern/cycles/scene/light.cpp::device_update_background` (CDF build,
  `sample_map_resolution`, MIS compensation via `background_portal_*` is out
  of scope) — Apache-2.0.
- Existing Astroray precedent for lamp NEE + two-sided MIS:
  `include/raytracer.h` pathTraceSpectral lamp block (`:2415-2568` per the
  pkg195 port note) and `plugins/integrators/multiwavelength_path_tracer.cpp`
  pkg195 Stage A block.
- Diagnosis docs: `hdri-background-gap-diagnosis-2026-09-07.md`,
  `pkg237-238-diagnosis-2026-09-07.md`.
- `.astroray_plan/docs/cycles-world-parity-research.md` (pkg63 research
  note; rotation and tint conventions already verified there).

---

## Prerequisites

- [ ] Build passes on main; `build_cuda/astroray.cp313-win_amd64.pyd` newer
      than HEAD before any GPU number is quoted.
- [ ] `cite-algorithm` research note saved under `.astroray_plan/docs/`
      before writing estimator code (Cycles `background.h` formulas, PBRT
      §12.5 pdf/Jacobian, equal-area vs lat-long choice recorded).
- [ ] GPU lock held for every CUDA build and GPU gate run.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg258_env_sampler_contract.py` | Sampler unit contract via a test binding: for N draws, `pdf(sample.direction) == sample.pdf` within 1e-4 relative; `lookup(sample.direction) == sample.radiance` within bilinear tolerance; direction histogram over azimuth bins is proportional to column energy (chi² vs the CDF) — this is the test that fails today. |
| `tests/test_pkg258_env_nee_convergence.py` | pkg63's never-run gate: sun-disc HDRI over a Lambertian floor; RMSE vs a 64k-spp CPU reference at 256 spp with env NEE ≤ 0.25× the RMSE with NEE disabled, on CPU and GPU; white-furnace variant (uniform env, albedo 1) stays at 1.0 ± 1% so NEE + miss never double-counts. |
| `.astroray_plan/docs/pkg258-env-nee-research.md` | `cite-algorithm` note: formulas, Jacobian, MIS weights, Cycles/PBRT line pointers, chosen parameterisation. |

### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` | Fix `EnvironmentMap::sample` azimuth (`phi = (uCont / width - 0.5f) * 2π`, matching `pdf`'s inverse); add env NEE to `pathTraceSpectral` and the GPU-mirroring CPU loop (`:3105` block): pick env vs lamp with `envSelectProb()` (or Cycles' energy-weighted selection — record the choice), shadow ray to infinity through `shadowTransmittance()` (pkg253), power-heuristic MIS on both the NEE leg and the miss leg (miss contribution weighted by `powerHeuristic(bsdfPdf, envPdf)` after a non-specular bounce). |
| `include/astroray/gpu_bvh.h` | Same azimuth fix in `gpu_envmap_sample`. |
| `src/gpu/wavefront/stage_light_sample.cu` | GPU wavefront env NEE sample generation with the same selection as CPU; occlusion is resolved by the deferred shadow stage (memory `gpu-wavefront-nee-occlusion-deferred-stage`), which must accept an "infinite" env shadow ray. Register-critical: follow `noinline-runtime-flag-avoids-shade-spill` / `shade-axis-side-table-avoids-spill`; REG must stay 254 and STACK growth reported. |
| `src/gpu/wavefront/stage_advance.cu` | The miss leg (`:661-670`) gains the power-heuristic MIS weight against the env pdf after a non-specular bounce; the env-NEE contribution is accumulated with its own weight. |
| `src/cpu/wavefront/path_kernel.cpp` | Mirror the in-header change (this is the CPU/GPU snapshot oracle — the pinned snapshot moment must not move; see `wavefront-snapshot-semantics-class-of-bug`). |
| `plugins/integrators/multiwavelength_path_tracer.cpp` | Same NEE block as the pkg195 lamp port, using `evalSpectralExt` where the lamp code does. |
| `src/lights/background_light.cpp` | Either implement `sampleLi`/`pdfLi`/`power` on top of the fixed `EnvironmentMap` sampler (so the pkg86 light tree can include the world) or delete the class; do not leave the uniform stub. |
| `module/blender_module.cpp` | Test binding `sample_environment_map(seed, n) -> (dirs, radiances, pdfs)` and `environment_pdf(dir)` for the contract test; a `set_env_nee(bool)` toggle for the convergence A/B. |
| `.astroray_plan/packages/pkg63-world-hdri-parity.md` | Progress: strike the "already wires env-MIS" claim with a pointer here. |
| `benchmarks/blender_parity/harness.py` | Re-derive `HDRI_MIN_BACKGROUND_MEAN` from the ground-truth `.hdr` decode of the ROI after the fix lands, not from either engine. |

### Key design decisions

- **Fix the sampler before wiring it.** The azimuth bug makes any NEE
  wiring produce wrong-direction shadow rays with right-texel radiance; the
  contract test must be red on main and green after the one-line fix on
  each backend before the estimator work starts.
- **Cycles-equivalent selection and MIS, no invention.** Env-vs-lamp
  selection and the power heuristic follow the existing pkg195 lamp block
  and Cycles `background.h`; if Cycles' energy-weighted light selection is
  adopted instead of the dormant 50 % `envSelectProb()`, say so in the
  research note. The miss leg must be MIS-weighted or the furnace double
  counts.
- **`world.cycles.max_bounces` gating stays** (pkg201): env NEE at bounce
  `b` contributes only if `b + 1 <= worldMaxBounces`, mirroring the miss
  gate.
- **Spectral radiance path unchanged.** NEE reuses `evalSpectral`
  (`RGBIlluminantSpectrum` upsampling) for the sampled texel so NEE and
  miss legs agree per wavelength.
- **GPU under register pressure.** If the wavefront shade kernel spills,
  isolate the env-NEE branch behind a `__constant__` runtime flag with a
  `__noinline__` body (pkg224 pattern) rather than shrinking the estimator.
- **Order:** research note → sampler fix + contract test (CPU, then GPU)
  → CPU NEE in the in-header tracer + convergence gate → CPU wavefront
  kernel + MW tracer → GPU wavefront → re-run the HDRI gap experiments and
  the `hdri_exterior_hair` non-vacuity gate → re-derive the harness floor.

---

## Acceptance criteria

- [ ] `tests/test_pkg258_env_sampler_contract.py` green on CPU and GPU
      (pdf/sample agreement, radiance/lookup agreement, azimuth histogram
      chi² p > 0.01); the same test fails on main before the azimuth fix
      (recorded in the PR).
- [ ] `tests/test_pkg258_env_nee_convergence.py`: sun-disc RMSE ratio
      (NEE on / NEE off at 256 spp) ≤ 0.25 on CPU and GPU; white furnace
      1.0 ± 1 % with NEE on (linear, upper bound asserted — see
      `gamma-furnace-cannot-detect-energy-gain`).
- [ ] CPU/GPU parity on `hdri_exterior_hair` and `tests/test_world_hdri_parity.py`
      unchanged or better; pkg55 wavefront snapshot gates green (no
      snapshot-moment drift).
- [ ] `hdri_exterior_hair` background-ROI experiment 1a re-run with env NEE
      on: Astroray CPU value recorded alongside the ground-truth decode
      (0.0338) and Cycles (0.121); the HDRI gap diagnosis doc gets a dated
      addendum saying which side moved.
- [ ] Saved renders (sun-disc floor, `hdri_exterior_hair`) before/after,
      inspected by the lead; no new fireflies, no darkening of the sky.
- [ ] GPU shade kernel REG unchanged (254) and STACK delta reported via
      `cuobjdump`; frame time on the metal_sweep GPU bench within +5 %.
- [ ] pkg63 Progress corrected; `HDRI_MIN_BACKGROUND_MEAN` re-derived with
      the derivation written next to the constant.

---

## Non-goals

- No Cycles MIS-compensation / portal lights (`background_portal_*`); file
  separately if the re-run gap analysis still needs it.
- No change to HDRI rotation, tint, strength or colour-management paths
  (all cleared by the diagnosis doc).
- No light-tree integration beyond making `BackgroundLight` correct or
  removing it; pkg86 owns tree inclusion.
- No threshold relaxation on any existing parity gate.
- Do not touch pkg237's SSIM scene choice (owned by pkg237).

---

## Progress

- [ ] 2026-09-07 evening — filed by the lead after the owner's hypothesis;
      code-read evidence above; no code changed yet.
- [~] 2026-09-08 — CPU leg (PR feat/pkg258-2026-09-08). Done: cite-algorithm
      research note; azimuth fix in `EnvironmentMap::sample` and
      `gpu_envmap_sample` (phi normalised by width); env NEE + power-heuristic
      MIS on the NEE leg and the miss leg in `pathTraceSpectral`, the
      multiwavelength tracer, and the CPU wavefront shared kernel
      (`advance_one_bounce`), all gated on a runtime `envNeeEnabled` flag
      (default ON) and guarded on a loaded HDRI so non-env scenes are
      byte-identical; `background_light.cpp` now importance-samples the fixed
      CDF instead of the uniform-sphere stub; test bindings
      (`sample_environment_map`, `environment_pdf`, `environment_lookup`,
      `set_env_nee`); contract + convergence tests. Design choice: env and lamp
      NEE are **independent additive strategies** (disjoint supports), no
      `envSelectProb()` selection — see the research note (open question for the
      Terra review). Not in this PR: GPU wavefront leg
      (`stage_light_sample.cu` / `stage_advance.cu`) — a separate PR off this
      branch; CPU/GPU HDRI parity gates that go red because CPU has env NEE and
      GPU does not are marked xfail(strict) "pkg258 GPU leg pending".

---

## Lessons

- (none yet)
