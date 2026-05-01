# pkg27a — NRC Training Observability

**Pillar:** 3
**Track:** A
**Status:** implemented
**Estimated effort:** 1 session (~2 h)
**Depends on:** pkg27
**Blocks:** pkg28

---

## Goal

**Before:** pkg28 can buffer NRC training samples, but tests cannot directly
observe whether samples were queued during worker rendering and trained at the
frame boundary.

**After:** integrators can expose lightweight diagnostic counters, and
`neural-cache` reports queued samples, padded frame-level training, cache
queries, and fallback use through the Python API. Default builds still work
without tiny-cuda-nn.

---

## Context

This is a prerequisite split from pkg28. Frame-buffered training is easy to
claim and hard to prove from image output alone, especially when the default CI
build intentionally falls back without a tiny-cuda-nn backend. A small
diagnostic hook lets package tests assert the scheduling contract without
making production rendering depend on a test helper.

---

## Specification

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/integrator.h` | Add optional `debugStats()` hook with an empty default. |
| `include/raytracer.h` | Surface active-integrator stats through `Renderer`. |
| `module/blender_module.cpp` | Bind `Renderer.get_integrator_stats()`. |
| `plugins/integrators/neural_cache.cpp` | Report queue/train/query/fallback counters. |
| `tests/test_integrator_plugin.py` | Cover stats shape in fallback and opt-in backend modes. |

---

## Acceptance criteria

- [x] `Renderer.get_integrator_stats()` returns `{}` for integrators without
      diagnostics.
- [x] `neural-cache` reports `buffered_training=1` and backend/fallback status.
- [x] Default builds expose zero training counters while fallback samples are
      counted.
- [x] Opt-in tiny-cuda-nn builds can assert that warmup samples are queued and
      trained as one padded frame-level batch.
- [x] Focused integrator tests pass in the default build.

---

## Non-goals

- Do not turn diagnostics into a stable public telemetry contract.
- Do not require CUDA or tiny-cuda-nn in default tests.
- Do not validate indirect-quality speedup; that belongs to pkg27b.

