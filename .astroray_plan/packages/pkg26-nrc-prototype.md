# pkg26 — NRC Prototype

**Pillar:** 3
**Track:** C
**Status:** implemented
**Estimated effort:** 2–3 sessions (~9 h)
**Depends on:** pkg25

---

## Goal

**Before:** pkg25 proved that tiny-cuda-nn builds and runs a dummy MLP
on the RTX 3000 Ada. There is no connection between that MLP and the
renderer; the smoke test is a throwaway binary.

**After:** A minimal `NeuralCache` helper class wraps a tiny-cuda-nn
network trained and queried at render time. A standalone harness renders
a Cornell-box scene where secondary bounces query the cache instead of
tracing full recursive paths. The output image shows the cache learning
over frames (noise decreasing without explicit SPP increase). The class
is not yet a registered integrator plugin — that is pkg27.

---

## Context

Phase 3C of the light-transport plan calls for a "standalone integrator
test, not wired into plugin system yet" between the build feasibility
proof (pkg25) and the production plugin (pkg27). The explicit
intermediate step exists because:

1. The NRC algorithm has training latency — a warmup period is needed
   before inference is useful. Validating that latency in a harness
   outside the plugin system reduces risk before pkg27 wires it into
   Blender UI.
2. The input feature design (position / direction / normal encoding) must
   be tuned against a rendered reference before committing to an API.
3. Keeping this prototype behind `ASTRORAY_TINY_CUDA_NN` means any
   instability does not touch the always-on render path.

---

## Reference

- Design doc: `.astroray_plan/docs/light-transport.md §Phase 3C`
- Prototype notes: `.astroray_plan/docs/tiny-cuda-nn-prototype-notes.md`
- tiny-cuda-nn inference + optimizer API: `build_tcnn/_deps/tiny-cuda-nn-src/include/tiny-cuda-nn/`
- NRC paper: Müller et al., "Real-time Neural Radiance Caching for Path
  Tracing," SIGGRAPH 2021.
- Reference inference pattern: NVlabs/instant-ngp `src/testbed_nerf.cu`

---

## Prerequisites

- [x] pkg25 is implemented: `ASTRORAY_TINY_CUDA_NN=ON` builds `tcnn_smoke.exe`
      and the forward pass returns finite outputs.
- [x] NVIDIA driver ≥ 596.36 (CUDA 13.2 runtime supported) — confirmed
      after the pkg25 driver update.
- [x] `test_gpu_renders_match_cpu` passes (GPU render path is confirmed
      working in the MSVC build).
- [x] Build passes on main with `BUILD_PYTHON_MODULE=ON ASTRORAY_ENABLE_CUDA=ON`.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `src/neural_cache.h` | `NeuralCache` class declaration — network lifecycle, `query()`, `train()` |
| `src/neural_cache.cu` | Implementation: tcnn model construction, optimizer, per-frame batch I/O |
| `scripts/nrc_smoke_render.cu` | Standalone harness: render N frames of a Cornell box using NRC for secondary bounces; write PPM output |
| `.astroray_plan/docs/nrc-prototype-notes.md` | Experiment log: input feature choices, warmup frames needed, quality observations |

### Files to modify

| File | What changes |
|---|---|
| `CMakeLists.txt` | Add `nrc_smoke_render` executable target inside the `ASTRORAY_TINY_CUDA_NN` block; link `tiny-cuda-nn` and `astroray_cuda` |
| `.astroray_plan/docs/STATUS.md` | Record outcome once the experiment finishes |
| `.astroray_plan/packages/pkg25-tiny-cuda-nn-prototype.md` | Tick the "dummy inference call runs" acceptance criterion (now resolved after driver update) |

### Key design decisions

**`NeuralCache` is not an `Integrator` subclass.** It is a helper that
the harness calls explicitly. The production plugin wrapper (`pkg27`)
will subclass `Integrator` and own a `NeuralCache` internally. Keeping
them separate here avoids touching plugin registry code while the
algorithm is still being tuned.

**Input feature vector — 16 floats (Identity encoding):**

| Slot | Data | Encoding |
|---|---|---|
| 0–2 | World-space surface position (xyz), normalized to [0,1] scene AABB | raw |
| 3–4 | View direction (spherical θ, φ) | raw |
| 5–6 | Surface normal (spherical θ, φ) | raw |
| 7 | Surface roughness | raw |
| 8–10 | Diffuse albedo (RGB) | raw |
| 11–15 | Padding (zeros) | — |

16 floats satisfies `FullyFusedMLP`'s input-width constraint without
a frequency or hash encoding layer. A proper multi-resolution hash
encoding can replace the raw position slots in pkg27 once the pipeline
is proven.

**Output — 16 floats, first 3 used:**
Slots 0–2 are R, G, B indirect radiance. Slots 3–15 are discarded.
`FullyFusedMLP` requires output width to be a multiple of 16.

**Network config:** Identity encoding, FullyFusedMLP, 2 hidden layers,
64 neurons, ReLU hidden, None output. Same as `tcnn_smoke` but with
`n_hidden_layers = 2`. Optimizer: Adam, lr = 1e-3.

**Training target:** Each frame, the path tracer traces a full secondary
path for a random subset of pixels (the "training set"). The resulting
radiance is used as the supervision signal via `NeuralCache::train()`.
The remaining pixels query the cache via `NeuralCache::query()`. After
a configurable warmup period (`WARMUP_FRAMES`, default 16) all pixels
use the cache.

**Batch granularity:** Collect all training samples for a frame into a
single `GPUMatrix` and call `optimizer->step()` once per frame. This
matches tiny-cuda-nn's intended use and avoids per-pixel CUDA launches.

**Use existing scene infrastructure.** The harness must use the
`Renderer` + `Camera` types already in the codebase to set up the
Cornell box, not a hand-rolled scene. This validates that `NeuralCache`
integrates with real scene data, not toy geometry.

---

## Acceptance criteria

- [x] `nrc_smoke_render.exe` builds with `ASTRORAY_TINY_CUDA_NN=ON` and no
      production target (no `BUILD_PYTHON_MODULE` target) depends on it.
- [x] Running `nrc_smoke_render.exe` produces a PPM image that is visually
      a recognizable Cornell box scene (no all-black or NaN output).
- [x] Mean pixel luminance in the output image increases (or noise
      decreases) between frame 1 and frame 50, confirming the cache learns.
- [x] No CUDA memory errors (`cudaDeviceSynchronize` returns
      `cudaSuccess` after each frame).
- [x] `.astroray_plan/docs/nrc-prototype-notes.md` records: warmup frames
      needed, any NaN/divergence conditions observed, and a recommendation
      for pkg27 (proceed / redesign input features / change network size).

---

## Non-goals

- Do not register `NeuralCache` as an `Integrator` plugin. That is pkg27.
- Do not add a Blender UI property or Python binding for NRC.
- Do not implement spectral NRC. Use RGB radiance only (convert
  `SampledSpectrum` → sRGB at the cache boundary).
- Do not implement double-buffered training. Single-buffer same-frame
  training is sufficient for the prototype.
- Do not make CI depend on `nrc_smoke_render` — it requires a GPU and the
  `ASTRORAY_TINY_CUDA_NN=ON` flag.

---

## Progress

- [x] Write `NeuralCache` class (`src/neural_cache.h` / `.cu`) with
      construction, `set_params`, `query()`, `train()`, and `step()`.
- [x] Add `nrc_smoke_render` target to `CMakeLists.txt` inside the
      `ASTRORAY_TINY_CUDA_NN` guard.
- [x] Write `scripts/nrc_smoke_render.cu`: Cornell box scene via existing
      `Renderer`, per-frame train/query loop, PPM write.
- [x] Run 50-frame render; verify no CUDA errors and image is non-black.
- [x] Observe and record learning curve (frame 1 vs frame 50 luminance).
- [x] Write `.astroray_plan/docs/nrc-prototype-notes.md`.
- [x] Update `STATUS.md` and pkg25 acceptance criteria.

---

## Lessons

- tiny-cuda-nn master now requires 256-sample batch alignment at the public
  `forward()` boundary; pkg27 must keep `NeuralCache::BATCH_ALIGN = 256`.
- The 16-frame warmup is enough for a visible Cornell-box learning curve, but
  production scheduling needs larger frame-level batches and double-buffering.
