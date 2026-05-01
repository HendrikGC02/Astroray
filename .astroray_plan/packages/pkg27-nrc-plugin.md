# pkg27 — NRC Plugin

**Pillar:** 3  
**Track:** A  
**Status:** implemented  
**Estimated effort:** 1-2 sessions (~6 h)  
**Depends on:** pkg26

---

## Goal

**Before:** pkg26 proves that `NeuralCache` can train and infer in a
standalone Cornell-box harness, but users cannot select it through the
integrator registry.

**After:** Astroray registers a `neural-cache` integrator. Normal builds can
select it and render via a path-tracer fallback; opt-in
`ASTRORAY_TINY_CUDA_NN=ON` builds link the pkg26 tiny-cuda-nn backend into the
production targets and use the cache for primary-hit indirect radiance.

---

## Context

This is the promotion step between the successful pkg26 prototype and the
pkg28 double-buffered training work. The package must make NRC visible through
the plugin system without making CI, Blender packaging, or default local builds
depend on tiny-cuda-nn. The result is intentionally conservative: a selectable
integrator with same-frame training and mutex-guarded single-sample batches,
not the final high-throughput viewport implementation.

---

## Reference

- Design doc: `.astroray_plan/docs/light-transport.md §Phase 3D`
- Prototype notes: `.astroray_plan/docs/nrc-prototype-notes.md`
- Prototype package: `.astroray_plan/packages/pkg26-nrc-prototype.md`
- tiny-cuda-nn: https://github.com/NVlabs/tiny-cuda-nn

---

## Prerequisites

- [x] pkg26 is complete: `NeuralCache` and `nrc_smoke_render` validate learning
      on the RTX 5070 Ti.
- [x] The pkg26 batch alignment fix is carried forward
      (`NeuralCache::BATCH_ALIGN = 256`).
- [x] Default builds must remain valid with `ASTRORAY_TINY_CUDA_NN=OFF`.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `plugins/integrators/neural_cache.cpp` | Registered `neural-cache` integrator wrapper around the pkg26 helper. |
| `.astroray_plan/packages/pkg27-nrc-plugin.md` | Package contract and completion record. |

### Files to modify

| File | What changes |
|---|---|
| `CMakeLists.txt` | Promote `src/neural_cache.cu` into an opt-in reusable backend library and link it into production targets only when requested. |
| `tests/test_integrator_plugin.py` | Verify `neural-cache` is registered and selectable. |
| `tests/runtime_setup.py` | Add CUDA toolkit DLL discovery for CUDA-enabled Python module tests on Windows. |
| `.astroray_plan/docs/STATUS.md` | Record pkg27 completion and package table update. |
| `.astroray_plan/docs/light-transport.md` | Mark the NRC plugin phase as implemented. |
| `.astroray_plan/packages/pkg26-nrc-prototype.md` | Align stale status with the completed prototype notes. |

### Key design decisions

`neural-cache` is registered in all builds. When `ASTRORAY_TINY_CUDA_NN=OFF`,
the integrator falls back to the spectral path tracer so Python/Blender
selection is stable and CI does not need CUDA or tiny-cuda-nn.

When `ASTRORAY_TINY_CUDA_NN=ON`, production targets link
`astroray_neural_cache` and compile the integrator with
`ASTRORAY_NEURAL_CACHE_ENABLED`. The first visible implementation caches
primary-hit indirect radiance: direct light remains spectral and exact; warmup
samples trace one secondary path, train the RGB cache target, and return the
reference value; post-warmup samples query the cache and upsample predicted RGB
back through the existing spectral boundary.

The backend calls are mutex-guarded because `Renderer::render()` calls
`sampleFull()` from OpenMP workers. This is correct but not the final
performance shape; pkg28 owns double-buffered batched training.

---

## Acceptance criteria

- [x] `integrator_registry_names()` includes `neural-cache`.
- [x] `renderer.set_integrator("neural-cache")` works from Python.
- [x] Default builds do not require tiny-cuda-nn.
- [x] Opt-in builds expose the pkg26 `NeuralCache` backend to production
      targets without duplicating `src/neural_cache.cu`.
- [x] Focused integrator tests pass.

---

## Non-goals

- Do not make CI depend on CUDA or tiny-cuda-nn.
- Do not implement double-buffered training or frame-level batch scheduling;
  that is pkg28.
- Do not implement spectral NRC training targets beyond the documented
  RGB-at-cache-boundary compromise.
- Do not replace ReSTIR DI or the default `path_tracer`.

---

## Progress

- [x] Add `neural-cache` integrator plugin.
- [x] Add default-build fallback path.
- [x] Wire optional `astroray_neural_cache` CMake backend.
- [x] Add Python registry/selectability tests.
- [x] Update package/status docs.

---

## Lessons

- The renderer's current integrator API is per-sample, while tiny-cuda-nn wants
  large batches. A correct pkg27 therefore has to favor safety over speed and
  leave high-throughput scheduling for pkg28.
- Registering the plugin unconditionally keeps user-facing selection stable,
  while compile-time backend gating preserves the "default builds are boring"
  rule that made pkg25/pkg26 safe to merge.
- On Windows, tiny-cuda-nn/CUTLASS checkout can exceed path-length limits under
  the OneDrive repo path. Use a short build directory such as
  `C:\tmp\astroray_pkg27_tcnn` for opt-in CUDA/tcnn verification.
