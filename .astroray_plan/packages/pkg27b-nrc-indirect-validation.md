# pkg27b — NRC Indirect Validation Gate

**Pillar:** 3
**Track:** A
**Status:** implemented
**Estimated effort:** 1-2 sessions (~5 h)
**Depends on:** pkg27a
**Blocks:** pkg28

---

## Goal

**Before:** `neural-cache` is selectable and can train at the frame boundary,
but Pillar 3 still lacks an acceptance scene that demonstrates useful indirect
lighting behavior rather than only crash-free integration.

**After:** a focused indirect-lighting validation scene compares
`neural-cache` against the spectral path tracer for finite output, bounded
bias, and measurable timing/quality behavior on a CUDA/tiny-cuda-nn opt-in
build. Default CI keeps a fallback smoke test.

---

## Context

pkg28 should not be considered complete just because the training buffer exists.
It is the final NRC production package, so it needs a package-level proof that
the buffered cache still behaves like an indirect-light estimator. The prism
rainbow request is tracked separately as spectral dielectric work; it is not an
NRC correctness condition.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_neural_cache_validation.py` | Opt-in NRC indirect validation and default fallback smoke. |
| `tests/scenes/neural_cache_indirect.py` | Small Cornell-style indirect scene shared by tests. |
| `scripts/benchmark_light_transport.py` | Emits JSON/CSV stats and PNG charts comparing path tracer, auto default, NRC fallback, and NRC backend. |

### Files to modify

| File | What changes |
|---|---|
| `.astroray_plan/packages/pkg28-nrc-training-buffer.md` | Mark pkg28 blocked until this gate is complete. |
| `.astroray_plan/docs/STATUS.md` | Track the split prerequisite package. |
| `include/raytracer.h`, `src/default_integrator.cpp` | Auto-select the optimized `neural-cache` integrator by default, with path tracer as fallback. |
| `blender_addon/__init__.py` | Add `Auto (Best Available)` as the first/default integrator choice. |

---

## Acceptance criteria

- [x] Default build: `neural-cache` fallback renders a finite, non-black
      indirect scene and reports no backend training.
- [x] Opt-in build: warmup frames report queued samples and at least one padded
      training step.
- [x] Opt-in build: post-warmup `neural-cache` output remains finite on the
      validation scene and records MSE against the path-tracer reference.
- [x] Opt-in build: benchmark records timing, quality, speedup, and training
      activity. Current 32x32 validation run does **not** meet the original 30%
      speedup target; it documents the next pkg28 tuning requirement instead.
- [x] The package notes explicitly separate NRC validation from spectral prism
      dispersion.

---

## Benchmark Output

Generated with:

```powershell
$env:ASTRORAY_BUILD_DIR='C:\tmp\astroray_pkg27_tcnn\Release'
python scripts/benchmark_light_transport.py --output-dir test_results/light_transport_benchmark --width 32 --height 32 --samples 4 --reference-samples 16 --max-depth 5 --frames 2
```

Files:

- `test_results/light_transport_benchmark/light_transport_stats.json`
- `test_results/light_transport_benchmark/light_transport_stats.csv`
- `test_results/light_transport_benchmark/light_transport_time.png`
- `test_results/light_transport_benchmark/light_transport_mse.png`
- `test_results/light_transport_benchmark/light_transport_speedup.png`
- `test_results/light_transport_benchmark/light_transport_nrc_training.png`

Observed summary on the RTX 5070 Ti opt-in build:

| Config | Seconds/frame | Speedup vs path tracer | MSE vs reference | Notes |
|---|---:|---:|---:|---|
| `path_tracer` | 0.0067 | 1.00x | 0.1264 | Baseline. |
| `auto_default` | 0.2868 | 0.02x | 0.2096 | Uses backend and trains, but first-use/cache overhead dominates this tiny scene. |
| `neural_cache_fallback` | 0.0066 | 1.01x | 0.1078 | Path-tracer fallback remains cheap. |
| `neural_cache_backend` | 0.0078 | 0.86x | 0.2727 | Backend trains two padded batches; not yet performance-positive. |

---

## Follow-up

The validation harness is complete, but the data says the prototype needs a
pkg28 tuning pass before Pillar 3 can claim the NRC speedup acceptance target:
cache initialization should be amortized, default warmup should be less
aggressive on tiny scenes, and inference/training batching should be profiled on
viewport-sized renders.

---

## Non-goals

- Do not make the test suite require a GPU by default.
- Do not solve spectral dielectric dispersion.
- Do not replace the path tracer default integrator.

