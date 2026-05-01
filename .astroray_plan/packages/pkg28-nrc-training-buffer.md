# pkg28 — NRC Training Buffer

**Pillar:** 3
**Track:** A
**Status:** implemented
**Estimated effort:** 1 session (~3 h)
**Depends on:** pkg27a, pkg27b

---

## Goal

**Before:** `neural-cache` is selectable, but each warmup sample trains the
tiny-cuda-nn backend immediately. That is correct but defeats the point of
tiny-cuda-nn batching and serializes cache updates inside the render hot path.

**After:** `neural-cache` collects RGB indirect-radiance training samples during
the frame, keeps inference on the previous cache parameters, and performs one
aligned training step from `Integrator::endFrame()`. Default builds still use
the path-tracer fallback and do not require tiny-cuda-nn.

---

## Context

pkg28 is the final planned Pillar 3 implementation package. It turns pkg27's safe but
per-sample training into the frame-delayed update pattern needed for practical
NRC: render workers only append samples, and the cache trains after all workers
finish. The validation gates prove finiteness, stats, chart generation,
frame-level training, and safe defaults. The current tiny-cuda-nn inference
path is deliberately gated behind `enable_inference=1` because the charts show
per-sample cache queries are not yet performance-positive; batched inference is
the follow-up Pillar 3 validation target.

---

## Reference

- Design doc: `.astroray_plan/docs/light-transport.md §Phase 3D`
- Prior package: `.astroray_plan/packages/pkg27-nrc-plugin.md`
- Scheduling prerequisite: `.astroray_plan/packages/pkg27a-nrc-training-observability.md`
- Validation prerequisite: `.astroray_plan/packages/pkg27b-nrc-indirect-validation.md`
- Prototype notes: `.astroray_plan/docs/nrc-prototype-notes.md`

---

## Prerequisites

- [x] pkg27 registered `neural-cache`.
- [x] `Renderer::render()` calls `Integrator::endFrame()` after OpenMP tiles
      complete.
- [x] `NeuralCache::BATCH_ALIGN` remains 256 for tiny-cuda-nn master.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `.astroray_plan/packages/pkg28-nrc-training-buffer.md` | Package contract and completion record. |

### Files to modify

| File | What changes |
|---|---|
| `plugins/integrators/neural_cache.cpp` | Buffer warmup training samples during `sampleFull()` and train once in `endFrame()`. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg28 implemented and call out remaining Pillar 3 validation gates. |
| `.astroray_plan/docs/light-transport.md` | Mark the NRC production package as implemented. |

### Key design decisions

The production integrator keeps the existing primary-hit NRC boundary from
pkg27. Direct lighting remains spectral and exact. Warmup samples trace a
reference secondary path, append a 16-float feature vector plus RGB target into
a mutex-protected frame buffer, and return the reference indirect radiance for
that sample. Cache queries during the frame use parameters from prior frames.
At `endFrame()`, the training buffer is padded to `NeuralCache::BATCH_ALIGN`
and submitted as one `trainStep()`.

`min_train_batch` and `max_train_samples` integrator params control training
batching without adding new public API. Defaults are conservative:
`min_train_batch=1` (padding handles tiny frames), `max_train_samples=128`,
`training_pct=4`, and `enable_inference=0`.

`Auto (Best Available)` selects the fastest validated default today: the
spectral path tracer. `neural-cache` remains available for explicit experiments
and will be promotable to the auto default once batched inference satisfies the
Pillar 3 speedup gate.

Transparent/glass dispersion is deliberately not part of this package. A prism
rainbow test requires wavelength-dependent dielectric sampling
(`Material::sampleSpectral` or equivalent), not an NRC training-buffer change.

---

## Acceptance criteria

- [x] `neural-cache` no longer calls `NeuralCache::trainStep()` from the
      per-sample hot path.
- [x] Training samples are collected during warmup and trained in one padded
      frame-level batch from `endFrame()`.
- [x] Default builds still register and select `neural-cache` without
      tiny-cuda-nn.
- [x] Opt-in CUDA/tiny-cuda-nn builds link the Python module successfully.
- [x] pkg27a observability verifies fallback stats and frame-level train stats.
- [x] pkg27b validates indirect-scene quality/timing and produces charts.
- [x] Follow-up tuning keeps default renders on the fastest validated fallback
      until NRC batched inference demonstrates the original speedup target on a
      viewport-sized indirect scene.

---

## Non-goals

- Do not solve spectral glass/transparent transport. Track the prism rainbow
  test as the next spectral-material validation target.
- Do not make `path_tracer` default to NRC.
- Do not make CI require CUDA/tiny-cuda-nn.
- Do not implement ReSTIR GI or neural path guiding.

---

## Progress

- [x] Replace per-sample `trainCache()` with frame-buffer enqueue.
- [x] Add `endFrame()` training step with 256-aligned padding.
- [x] Add training batch controls.
- [x] Add pkg27a diagnostic coverage.
- [x] Complete pkg27b indirect validation.
- [x] Tune default/backend policy so charts prevent a slower NRC path from
      becoming the default before batched inference is ready.

---

## Lessons

- The existing integrator lifecycle was enough for a safe first double-buffer:
  OpenMP workers finish before `endFrame()`, so no background worker is needed
  for correctness.
- The prism rainbow render belongs to the spectral dielectric queue. The
  renderer already has spectral radiance, but transparent/glass still needs a
  wavelength-aware sampling path before a prism can split white light into
  different exit directions.
- The first production charts proved an uncomfortable but useful fact:
  frame-buffered training is correct, but single-sample tiny-cuda-nn inference
  launches are too expensive to be the default. The next optimization step is
  batched frame-level cache query scheduling, not more per-sample tuning.
