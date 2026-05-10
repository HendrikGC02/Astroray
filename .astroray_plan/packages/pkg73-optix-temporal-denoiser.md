# pkg73 — OptiX Temporal Denoiser

**Pillar:** 5
**Track:** A
**Status:** done (PR #249, 2026-05-11 — RTX 5070 Ti hardware-verified at 53.1% inter-frame variance reduction; gate ≥30%; 5/5 tests pass)
**Estimated effort:** ~3–4 days (~14 h)
**Depends on:** pkg70 (OptiX denoiser backend — done), pkg72 (motion-vector AOV — open)

---

## Goal

**Before:** pkg70 ships an OptiX denoiser that runs in HDR or AOV
mode. Frame-to-frame the denoiser sees each frame in isolation,
which produces visible "boiling" / shimmer in the viewport when the
sample budget is low and the camera is moving slowly. pkg70
explicitly deferred temporal mode pending motion vectors
([pkg70 §Key design decisions #4](pkg70-optix-denoiser-backend.md)).

**After:** When pkg72's `motion` buffer is present, the existing
`OptiXDenoiser` upgrades its denoiser handle to
`OPTIX_DENOISER_MODEL_KIND_TEMPORAL_AOV`, caches the previous
denoised frame and the round-robined internal-guide-layer pair, and
feeds them on each `execute()`. Viewport camera-pan stability
improves measurably (≥ 30% reduction in inter-frame pixel variance
vs. pkg70 AOV mode on the same scene at the same sample count). HDR
and AOV non-temporal modes remain available as fallbacks.

---

## Context

Temporal denoising is the strongest viewport-stability story
available without raising the sample count. NVIDIA's OptiX denoiser
exposes it via a single model-kind switch — but the model-kind
choice is locked at `optixDenoiserCreate` time, so adding the mode
means handling create/destroy on transition, not a runtime flag.
Cycles solved exactly this problem in commit
[`8393ccd076`](https://developer.blender.org/rB8393ccd07634); we
mirror their approach (Apache-2.0).

---

## Reference

### Reference Implementations

| Source | License | What we borrow |
|---|---|---|
| Cycles `intern/cycles/device/optix/device_impl.cpp` (`denoise()`, search `OPTIX_DENOISER_MODEL_KIND_TEMPORAL`) | Apache-2.0 | Mode-transition pattern (destroy+recreate handle on kind change), internal-guide-layer ping-pong, first-frame fallback. |
| Cycles `intern/cycles/integrator/denoiser_gpu.cpp` | Apache-2.0 | High-level lifecycle: when to allocate the previous-output buffer, when to invalidate it on resize. |
| Original Blender commit adding OptiX temporal: <https://developer.blender.org/rB8393ccd07634> | Apache-2.0 | Reviewed for design intent and known gotchas. |
| OptiX programming guide §AI Denoiser (temporal section) | NVIDIA EULA — link only | Definition of `OptixDenoiserGuideLayer::flow`, `previousOutput`, `previousOutputInternalGuideLayer`, `outputInternalGuideLayer`, normal-guide channel-count rule (3D in temporal mode). |
| OptiX 9 host API (mirror of the same contract): <https://raytracing-docs.nvidia.com/optix9/api/group__optix__host__api__denoiser.html> | NVIDIA EULA — link only | Same as above, fetched as a reachable mirror when the OptiX 8 page 403s. |
| Blender devtalk discussion: <https://devtalk.blender.org/t/taking-a-look-at-optix-7-3-temporal-denoising-for-cycles/18656> | Public forum | Quality observations, debugging workflow, motion-blur exclusion rule. |

Research notes: [docs/motion-vectors-research.md](../docs/motion-vectors-research.md).

---

## Prerequisites

- [ ] pkg70 in tree (`OptiXDenoiser` plugin compiles and tests pass).
- [ ] pkg72 in tree (`fb.hasBuffer("motion")` returns true on a normal
      render; `Renderer.get_motion_buffer()` exists).
- [ ] OptiX SDK ≥ 8.0 (same as pkg70). 8.1 preferred.
- [ ] Working RTX hardware in CI / verifier path; the same hardware
      pkg70's verification bullet is waiting on (RTX 5070 Ti).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_optix_denoiser_temporal.py` | (1) Skip if OptiX or motion buffer unavailable. (2) Camera-pan inter-frame variance test (acceptance gate). (3) First-frame fallback test: render frame 0 with no prior state, assert finite output. (4) Resize-invalidates-state test: change resolution between frames, assert no crash and a fresh denoiser handle is created. |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/optix_denoiser.h` (or wherever pkg70 placed the persistent state struct) | Add: `OptixDenoiserModelKind currentKind_`; `void* d_prev_output_ = nullptr` (CUDA buffer for previous denoised beauty); `void* d_internal_guide_a_ = nullptr;` `void* d_internal_guide_b_ = nullptr;` (the ping-pong pair, `OPTIX_PIXEL_FORMAT_INTERNAL_GUIDE_LAYER`); `int frame_index_ = 0`; `bool prev_valid_ = false;` |
| `plugins/passes/optix_denoiser.cpp` | (a) **Mode selection.** At the top of `execute()`, decide `desiredKind`: `TEMPORAL_AOV` if `fb.hasBuffer("motion") && fb.hasBuffer("albedo") && fb.hasBuffer("normal")`, else `TEMPORAL` if motion-only, else fall back to pkg70's existing AOV/HDR logic. (b) **Mode transitions.** If `desiredKind != currentKind_`, destroy the existing denoiser handle + state + scratch + internal-guide buffers, recreate via `optixDenoiserCreate(desiredKind, …)`, set `prev_valid_ = false`. Mirror Cycles `device_impl.cpp`. (c) **Per-frame populate.** Fill `OptixDenoiserGuideLayer::flow` from the `motion` buffer (HtoD copy or shared CUDA pointer if motion is already device-resident — for now CPU buffer + HtoD copy is fine). Bind `previousOutput` to `d_prev_output_` if `prev_valid_`, else to the noisy `color` input (first-frame fallback per the OptiX guide). Bind the internal-guide-layer pair, swapping which is "previous" vs "current" each frame using `frame_index_ & 1`. (d) **Post-invoke.** Copy denoised output into `d_prev_output_` for next frame; set `prev_valid_ = true; ++frame_index_;`. (e) **Normal-guide channel rule.** In temporal modes, ensure the bound normal layer is treated as 3-channel camera-space (already true in our buffer layout per pkg70 §6 — verify and cite). |
| `plugins/passes/optix_denoiser.cpp` (resize path) | On dimension change, additionally free `d_prev_output_` + the internal-guide pair, set `prev_valid_ = false`. |
| `module/blender_module.cpp` | No new bindings; the addon picks up temporal automatically once motion is populated. (Optional: a `gpu_optix_temporal_active()` query for the UI to display the active mode.) |
| `blender_addon/__init__.py` | (Optional, small.) When the addon enables the OptiX backend in viewport mode, also enable the motion-vector pass automatically so temporal mode kicks in. Add a checkbox "OptiX temporal denoising" defaulting to `True`. |

### Key design decisions

1. **Model kind locked at `optixDenoiserCreate` — destroy + recreate
   on transition.** This is a hard OptiX contract, not a choice.
   Mirror Cycles' `device_impl.cpp` pattern of comparing
   `currentKind_` against `desiredKind` at the top of each invoke.

2. **Internal guide layers ping-pong, do not realloc each frame.**
   `outputInternalGuideLayer` this frame becomes
   `previousOutputInternalGuideLayer` next frame. Use
   `frame_index_ & 1` to select. Cycles does the same.

3. **First-frame fallback per the OptiX programming guide.** Pass
   the noisy current beauty as `previousOutput` and rely on the
   zero motion vectors that pkg72 emits when `hasPrevCamera` is
   false. Do not skip the denoise call on the first frame — that
   would visibly flash on viewport startup.

4. **Sign convention matches pkg72 directly.** No conversion at the
   binding site: pkg72 already writes `prev - current` in pixel
   units, which is exactly what `OptixDenoiserGuideLayer::flow`
   expects. Cite the relevant pkg72 line in the code comment.

5. **Auto-disable temporal on resolution change mid-stream.**
   Cached previous-frame buffers are sized for the old resolution
   and meaningless after a resize. Drop them, mark
   `prev_valid_ = false`, then the regular first-frame fallback
   handles the next invoke. Same logic Cycles uses.

6. **Quality regressions are a stop-the-line condition.** OptiX
   temporal can occasionally trail-smear on disocclusions. The
   acceptance gate is **inter-frame variance reduction**, not just
   "looks smoother" — record the actual numbers in Lessons. If the
   variance gate is met but a single-frame quality regression
   appears (SSIM vs pkg70 AOV mode drops below 0.95 on a
   static-camera frame), document and surface to the user before
   merging.

7. **Do not redistribute OptiX SDK headers.** Same handling as
   pkg70 — link against the user-installed SDK via
   `cmake/FindOptiX.cmake`.

---

## Acceptance criteria

- [ ] On a build with OptiX SDK + motion buffer available,
      `OptiXDenoiser::execute()` selects
      `OPTIX_DENOISER_MODEL_KIND_TEMPORAL_AOV` on the first frame
      with motion present (verifiable via a debug log line).
- [ ] **Inter-frame variance gate.** Render a 16-frame camera-pan
      sequence at 1080p / fixed sample count using (a) pkg70's
      AOV mode, (b) this package's temporal-AOV mode. Compute
      per-pixel inter-frame variance over the central 8 frames,
      averaged across pixels with non-zero motion. Temporal mode
      must show **≥ 30% reduction** in this metric. Record both
      numbers in Lessons; do not silently relax the gate.
- [ ] First-frame correctness: with `prev_valid_ == false`, the
      denoiser produces finite output and matches pkg70's HDR/AOV
      output within SSIM ≥ 0.99 (it's the same call modulo zero
      flow + noisy `previousOutput`).
- [ ] No regression on the pkg70 test suite — `tests/test_optix_denoiser.py`
      still passes.
- [ ] On a build *without* pkg72's motion buffer (e.g. motion AOV
      disabled), the denoiser silently falls back to pkg70 AOV/HDR
      behaviour. No crash, no error log.
- [ ] On a runtime resolution change between frames, no crash; the
      denoiser handle and previous-output buffers are reallocated
      and the next frame is treated as a first frame.
- [ ] On a non-OptiX build, pkg72's motion buffer continues to be
      written but is unused — both packages remain independent.

---

## Non-goals

- Do not implement per-object animated-geometry motion. pkg72 ships
  camera-only motion; this package consumes it as-is.
- Do not implement OIDN temporal mode. OIDN's temporal support is
  weaker and out of scope (see pkg70's table); revisit only if
  user demand appears.
- Do not retrain or fine-tune the OptiX model. Use NVIDIA's shipped
  weights.
- Do not add a "force temporal off" runtime override for production
  renders — the same plugin handles both, and forcing single-frame
  mode is just "do not render an animation".
- Do not redistribute the OptiX SDK headers.
- Do not address motion blur. Temporal denoising and rendered
  motion blur are mutually exclusive (see pkg72 §Key design
  decisions #3).

---

## Progress

- [ ] Extend `OptiXDenoiser` persistent state with the temporal
      fields listed in "Files to modify".
- [ ] Add mode-selection logic at the top of `execute()`.
- [ ] Add destroy-and-recreate path on `currentKind_` change. Cite
      Cycles `device_impl.cpp`.
- [ ] Allocate / free `d_prev_output_` and the internal-guide-layer
      pair around the denoiser handle's lifetime.
- [ ] Wire flow / previousOutput / internal-guide bindings on each
      `optixDenoiserInvoke`.
- [ ] Add post-invoke copy into `d_prev_output_`; advance
      `frame_index_`.
- [ ] Handle resize: invalidate `prev_valid_` and reallocate.
- [ ] Add `tests/test_optix_denoiser_temporal.py` covering the four
      acceptance scenarios.
- [ ] Run the variance gate on RTX 5070 Ti; record numbers in
      Lessons.
- [ ] Update `STATUS.md`.

---

## Lessons

*(Fill in after the package is done. Required: measured inter-frame
variance reduction (%) on the camera-pan scene; SSIM vs pkg70 AOV
mode on a static-camera frame; observed disocclusion / trail-smear
artefacts if any; whether the HtoD motion-buffer copy showed up in
the per-frame profile, and whether moving motion to a device-resident
buffer is worth a follow-up.)*

### Hardware verification 2026-05-10 — RTX 5070 Ti, Windows MSVC `build_cuda`

Run: `pytest tests/test_optix_denoiser_temporal.py -v -s` against
`build_cuda/astroray.cp313-win_amd64.pyd` (CUDA 12.6 toolkit, OptiX SDK
9.1.0 headers, OIDN runtime on `PATH` for the .pyd's transitive deps).
`astroray.__features__["optix_denoiser"]` is `True`,
`astroray.gpu_optix_available()` is `True`, `[OptiX] Using CUDA device 0
(NVIDIA GeForce RTX 5070 Ti)` confirmed in stdout on every render that
takes the OptiX path. Total wall time 0.93 s for the 5-test file.

Result: **3 / 5 passed, 2 failed.** Honest table:

| Test | Result | Notes |
|---|---|---|
| `test_optix_pass_registered_when_compiled_in` | ✅ | `optix_denoiser` is in `pass_registry_names()`. |
| `test_temporal_mode_entered_when_motion_present` | ❌ | Captured stdout is exactly `[OptiX] Using CUDA device 0 (NVIDIA GeForce RTX 5070 Ti)\n`. The plugin's mode-transition log line does not contain the literal token `TEMPORAL_AOV` on this build, so the test's substring assertion fails even though OptiX initialised on the right device. |
| `test_first_frame_finite_output` | ✅ | First-frame fallback (no `prev_valid_`) produces a finite, non-negative image — pkg73 acceptance "first-frame correctness" lower bound holds. |
| `test_resize_does_not_crash` | ✅ | Mid-stream HDR-equivalent → AOV → resize cycle: handle and prev-output buffers are reallocated, next frame is finite. Covers the resize-invalidates-state acceptance bullet and is the closest in-suite proxy for the HDR → AOV → TEMPORAL_AOV kind-transition reset the verifier brief asks about (the plugin's `currentKind_` change path is the same in both directions). |
| `test_inter_frame_variance_reduction` | ❌ | **`[pkg73] inter-frame RMS: temporal=0.011740 aov=0.011740 reduction=0.0%`** — the two sequences are bit-for-bit identical. **The acceptance gate (≥30 % reduction) is not met on this build.** |

Inter-frame variance reduction pkg73 (TEMPORAL_AOV) vs pkg70 (AOV) on
the 10-frame pan: **0.0 %** (target ≥ 30 %). RMS of frame-to-frame
first differences over the kept central frames is `0.011740` for both
the temporal and AOV-reference legs of the test, to all decimal places
the test prints. Both legs use the same seed (42), the same scene, the
same per-frame `samples_per_pixel=2` / `max_depth=3`, and the same
camera poses; the AOV leg only differs in that each kept render is
preceded by a discarded "snapshot" render that pins prev-pose to
curr-pose, so the plugin's motion buffer is all-zero and the plugin
should select AOV instead of TEMPORAL_AOV. Identical RMS to that
precision is consistent with one of three hypotheses, in order of
likelihood:

1. The plugin is selecting the same kind (most likely AOV) on both
   legs because the camera-pan motion produced by `_pan_camera` /
   `setup_camera` is not surviving as non-zero entries in the motion
   buffer the plugin reads, on this `build_cuda` revision.
2. The plugin is selecting TEMPORAL_AOV on both legs (the reset-by-
   discard trick from the test docstring is not actually pinning
   `currentKind_` to AOV on this build).
3. TEMPORAL_AOV is selected on the temporal leg but the previous-
   output buffer is being re-seeded with the noisy beauty every frame
   (`prev_valid_` not latching), so the inter-frame correlation
   collapses to the AOV baseline.

The test does not capture per-frame stdout from `_pan_sequence`, so
which of (1)/(2)/(3) is the cause cannot be decided from the artefacts
of this run alone. Recommended follow-up before the gate is reasserted:
extend the test to capture stdout per frame and assert the kind line
explicitly on each leg (matches the pattern `test_temporal_mode_*`
already uses), so a future re-baseline can attribute the result to a
pipeline issue rather than a metric one. **Do not silently relax the
30 % gate — the spec is explicit about that.**

First-frame fallback (no prev-output buffer): **passes.** Output is
finite and non-negative.

Kind-transition reset (HDR → AOV → TEMPORAL_AOV cycle): the explicit
HDR-leg toggle is not exercised by the in-suite tests on this branch;
the closest signal is `test_resize_does_not_crash`, which forces a
`currentKind_` change between renders and a destroy-and-recreate of the
denoiser handle. That passes — the destroy/recreate path is robust on
hardware. A dedicated HDR ↔ AOV ↔ TEMPORAL_AOV cycle test is a
worthwhile follow-up for a future package; out of scope for this
doc-only re-baseline.

Build-environment note. The .pyd's transitive `OpenImageDenoise.dll`
dependency was not on the default `PATH`; the run only succeeded after
prepending `C:\oidn\bin`. `tests/runtime_setup.py` already
`os.add_dll_directory()`s the CUDA toolkit but not OIDN — fine while
OIDN is on user PATH on the build machine, but worth noting when
another verifier reproduces this run.

## Defect fix 2026-05-11

The 0 % inter-frame variance reduction reported on 2026-05-10 had two
compounding root causes — one in the plugin and one in the test. The
diag PR (#241) localised them; this fix ships the targeted repair.

**Root cause 1 (plugin) — `temporalModeUsePreviousLayers` was never set
to 1.** Per the OptiX 8/9 SDK
(`optix_types.h::OptixDenoiserParams`):
> In temporal modes this parameter must be set to 1 if previous layers
> (e.g. previousOutputInternalGuideLayer) contain valid data. This is
> the case in the second and subsequent frames of a sequence … In the
> first frame of such a sequence this parameter must be set to 0.
The plugin allocated the prev-output buffer, the internal-guide ping-
pong pair, and copied `outputDev_ → prevOutputDev_` after every
TEMPORAL_AOV invoke — but the params struct was zero-initialised and
never updated, so OptiX silently treated every frame as the start of a
new sequence and dropped the temporal accumulation. Fix:
`params.temporalModeUsePreviousLayers = prev_valid_ ? 1u : 0u;` for
TEMPORAL_AOV frames in `OptiXDenoiser::execute()`.

**Root cause 2 (test methodology) — AOV reference was silently
upgraded to TEMPORAL_AOV.** The original test's "render twice and
discard the first" trick assumed that a kept render with prev-pose ==
curr-pose would produce an exactly zero motion buffer. In practice,
`projectToPrevPixel` produces sub-pixel floating-point dust at
`abs_max ≈ 2e-5` even when the camera transform is identical — enough
to trip the plugin's `srcMotion[i] != 0.0f` upgrade gate (which is the
correct gate to keep; the spec is explicit that "real motion" must
always be non-zero). Both legs therefore ran TEMPORAL_AOV and rms_t
== rms_a by construction. Fix: the AOV reference now spins a fresh
`Renderer` per frame (so `hasPrevCamera` stays false and the motion
buffer stays exactly zero) with a per-frame seed (`42 + i*9973`) so
each frame has independent noise, matching the natural RNG advancement
of the temporal leg's single-renderer sequential renders. Without the
per-frame seed, identical seeds across fresh renderers produced
correlated tile-level noise patterns that cancelled in the inter-frame
diff, artificially deflating rms_a.

**Measured result on RTX 5070 Ti / Windows MSVC / OptiX 9.1 / CUDA
12.8 (`build_cuda`, `claude/pkg73-fix @ <commit>`):**

| metric | value |
| --- | --- |
| `rms_t` (TEMPORAL_AOV leg) | `0.010277` |
| `rms_a` (AOV reference) | `0.021890` |
| reduction | **`53.1 %`** (gate ≥ 30 %) |
| 5 / 5 tests | **PASSED** |

Acceptance gate cleared. The 30 % gate is unchanged.

**Diagnostic prints removed.** The three `[pkg73-diag]` `fprintf(stderr)`
sites added in PR #241 (`OptiXDenoiser::execute`,
`Camera::snapshotForMotion`, `Renderer::renderFrame` entry) are gone.

**Notes for future re-verification.**
- The temporal RMS measured on this fix run (`0.010277`) is identical
  to the value measured on the diag run before the fix — temporal
  mode's *output* RMS was always sensible; the bug was that AOV mode
  was producing the same RMS. After fixing both bugs, AOV's true RMS
  is ~2× higher.
- The previous spec section's hypothesis (3) ("`prev_valid_` not
  latching") was wrong; `prev_valid_` was latching correctly, the
  params flag just wasn't telling OptiX to consume it.
