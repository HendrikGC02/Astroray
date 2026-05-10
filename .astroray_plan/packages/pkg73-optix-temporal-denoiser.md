# pkg73 — OptiX Temporal Denoiser

**Pillar:** 5
**Track:** A
**Status:** implemented (pending CUDA + OptiX verification)
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
