# pkg70 — OptiX Denoiser Backend

**Pillar:** 5
**Track:** A
**Status:** done
**Estimated effort:** 3–5 days (~25 h)
**Depends on:** pkg33 (OIDN integration — done), pkg68 (OIDN architectural fix — establishes the device-selection plumbing pattern this package mirrors)

---

## Goal

**Before:** Astroray's only denoiser backend is Intel OIDN. Even with
pkg68's CUDA-OIDN fix, OIDN-CUDA on the user's RTX 5070 Ti runs
~30–60 ms/frame at 1080p. NVIDIA's OptiX AI denoiser, which uses Tensor
Cores directly via CUDA, runs the same workload in ~10–30 ms — a real
2–3× viewport-responsiveness win for users with RTX hardware. Cycles
ships both backends and lets the user pick; we ship only OIDN.

**After:** A new `optix_denoiser` pass plugin co-equal with
`oidn_denoiser`, exposing the OptiX 8.x AI denoiser API. The pass
registry exposes both options; the addon defaults to OptiX when the
OptiX SDK is present at build time AND a CUDA device is available at
runtime, falling back to OIDN otherwise. Final-render quality matches
OIDN (both are HDR-mode AI denoisers trained on similar datasets);
viewport frame time on RTX 5070 Ti drops to 10–30 ms in OptiX mode.

---

## Context

OptiX 8.x exposes a clean denoiser API via a small subset of the OptiX
SDK — it does not require the user to do path tracing in OptiX. Just
the denoiser. The hardware path on Turing+ GPUs uses Tensor Cores; the
RTX 5070 Ti (Blackwell) has full Tensor Core acceleration with FP8
support. Cycles' OptiX denoiser is the canonical permissive reference
implementation we can mirror.

The pass registry from pkg06 explicitly reserved a slot for an OptiX
denoiser ([pkg06-pass-registry.md](pkg06-pass-registry.md): "Do not
implement the OptiX denoiser. It is `pkg51` in Pillar 5."). We're
picking up that thread, renumbered to pkg70.

---

## Reference

### NVIDIA OptiX SDK

- **SDK download:** https://developer.nvidia.com/designworks/optix/download
  Requires NVIDIA developer account (free). Target version: **OptiX 8.0
  or later** (8.1 is current as of this writing, ships with Driver
  R555+). The user is on an RTX 5070 Ti which requires R570+ drivers,
  so OptiX 8.1 is fully supported.
- **License:** NVIDIA OptiX SDK License Agreement.
  https://raytracing-docs.nvidia.com/optix8/api/optix__host_8h.html
  The SDK headers are NOT redistributable, but binaries linked against
  them are. We ship Astroray's CUDA build linked against OptiX with the
  user-installed SDK; we don't bundle SDK headers in the repo.

### OptiX denoiser API

- **Programming Guide → AI-Accelerated Denoiser:**
  https://raytracing-docs.nvidia.com/optix8/guide/index.html#ai_denoiser
  Read this entire section before implementing. It walks through the
  full lifecycle.
- **API reference:**
  https://raytracing-docs.nvidia.com/optix8/api/optix__host_8h.html
  Specific functions this package uses:
  - `optixDenoiserCreate(context, modelKind, options, denoiser)`
  - `optixDenoiserComputeMemoryResources(denoiser, maxWidth, maxHeight, sizes)`
  - `optixDenoiserSetup(denoiser, stream, width, height, state, stateSize, scratch, scratchSize)`
  - `optixDenoiserInvoke(denoiser, stream, params, state, stateSize, layers, numLayers, offsetX, offsetY, output, scratch, scratchSize)`
  - `optixDenoiserDestroy(denoiser)`
- **Model kinds we care about:**
  - `OPTIX_DENOISER_MODEL_KIND_HDR` — color-only HDR (matches our
    use case for offline render).
  - `OPTIX_DENOISER_MODEL_KIND_AOV` — adds albedo + normal guides
    (the standard viewport mode, matches OIDN's guided behaviour).
  - `OPTIX_DENOISER_MODEL_KIND_TEMPORAL` — adds previous-frame
    color + motion vectors. **Do NOT enable in this package** —
    motion vectors are a separate plumbing problem (see Non-goals).

### Cycles' OptiX denoiser as a reference (Apache-2.0, mirrorable)

- **File:** `intern/cycles/integrator/denoiser_gpu.cpp` (the GPU
  abstract base) and the OptiX-specific code in `intern/cycles/device/optix/`
  in the Blender mono-repo.
  https://projects.blender.org/blender/blender/src/branch/main/intern/cycles/integrator
  https://projects.blender.org/blender/blender/src/branch/main/intern/cycles/device/optix
  License: **Apache-2.0**, mirroring permitted with attribution.
- **Specifically read:** `OptiXDevice::denoise()` for the per-frame
  invocation shape; `denoise_buffer()` for the buffer-binding pattern.
- **Cycles' approach to model-kind selection:** uses HDR by default,
  upgrades to AOV when albedo + normal guide passes are available.
  Mirror this.

### NVIDIA OptiX samples

- **SDK samples:** Included with the OptiX SDK download —
  `SDK/optixDenoiser/` is a minimal standalone reference (~500 LOC).
  License: NVIDIA OptiX SDK License — read but do not redistribute.
- **NVIDIA OptiX apps repo (BSD-3, mirrorable):**
  https://github.com/NVIDIA/OptiX_Apps
  Has additional denoiser examples. Check current commit + license
  before mirroring any code.

### Hardware support matrix

- OptiX denoiser runs on any CUDA-capable GPU with Compute Capability
  **5.0+ (Maxwell)**. Tensor Core acceleration kicks in on **7.5+
  (Turing)**. The user's **RTX 5070 Ti (Blackwell, CC 10.0)** gets
  full acceleration including FP8 paths in OptiX 8.1.
- **Driver requirement:** OptiX 8.1 needs NVIDIA driver **R555+**.
  The RTX 5070 Ti requires R570+ regardless, so this is automatic.

### OptiX vs OIDN — when to prefer which

| Criterion | OptiX | OIDN |
|---|---|---|
| GPU vendor | NVIDIA only | NVIDIA, AMD, Intel, Apple |
| Speed on RTX | ~10–30 ms/1080p | ~30–60 ms/1080p (CUDA), ~200 ms (CPU) |
| Quality (HDR + guides) | Comparable; OptiX slightly favours sharpness | Comparable; OIDN slightly favours noise floor |
| Temporal mode | First-class (motion vectors) | Limited — see pkg68 design decision #4 |
| Build dependency | NVIDIA SDK install | FetchContent-able binary |

The recommendation: ship both. Default to OptiX for viewport when
available; OIDN otherwise. Final-render quality is similar enough that
either is fine — the user can choose.

---

## Prerequisites

- [ ] OptiX 8.1 SDK installed at a known location on the dev/build
  machine. Check default install path on Windows:
  `C:\ProgramData\NVIDIA Corporation\OptiX SDK 8.1.0\`.
- [ ] CMake `find_package(OptiX)` recipe — write a `FindOptiX.cmake`
  module if one doesn't exist. (NVIDIA SDK ships
  `SDK/CMake/FindOptiX.cmake` we can adapt; or use `OPTIX_INSTALL_DIR`
  env var pattern.)
- [ ] pkg68 merged so the device-selection log-line and fallback
  patterns are established. Mirror the pattern.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `cmake/FindOptiX.cmake` | CMake module to locate the OptiX SDK headers. |
| `plugins/passes/optix_denoiser.cpp` | Plugin pass class `OptiXDenoiser` mirroring `OIDNDenoiser`'s shape. |
| `include/astroray/optix_denoiser.h` (if class needs a header) | Persistent-state struct: CUDA context, OptiX denoiser handle, state + scratch device buffers, cached dimensions. |
| `tests/test_optix_denoiser.py` | Skip-if-OptiX-unavailable test that runs the denoiser on a synthetic noisy image and asserts (a) finite output, (b) lower noise than input, (c) it actually runs on CUDA. |

### Files to modify

| File | What changes |
|---|---|
| `CMakeLists.txt` | Guard OptiX with `ASTRORAY_ENABLE_OPTIX=ON` (default `AUTO` — enabled when SDK is found). Add the new plugin to the build only when enabled. Define `ASTRORAY_OPTIX_ENABLED` for conditional code paths. |
| `module/blender_module.cpp` | Expose a `gpu_optix_available()` Python query so the addon can detect runtime support. |
| `blender_addon/__init__.py` | Backend-selection logic: when both OIDN and OptiX are available, default to OptiX in viewport mode. UI dropdown so users can override. Plays nicely with pkg62's pass selector. |

### Key design decisions

1. **Don't bundle the OptiX SDK headers.** The license forbids
   redistribution. Build-time finds `optix.h` via `FindOptiX.cmake`;
   end users who build from source install OptiX themselves. For
   binary distribution, the addon ships the linked plugin binary +
   a runtime check that the OptiX-7+ DLL is loadable.

2. **Persistent denoiser handle, exactly like pkg68.** Mirror the
   class-member-caching pattern: `OptiXDenoiser` holds the
   `OptixDenoiser` handle, the `OptixDeviceContext`, and the device
   memory for state + scratch. Lazy-init on first `execute()`.

3. **Default to AOV model when guides are available.** Same logic as
   Cycles — if `fb.hasBuffer("albedo") && fb.hasBuffer("normal")`,
   use `OPTIX_DENOISER_MODEL_KIND_AOV`; otherwise `HDR`. Mode is
   chosen at first invocation and locked for the denoiser's lifetime
   (changing mode requires recreating the denoiser handle).

4. **No temporal mode in this package.** OptiX's temporal model
   (`OPTIX_DENOISER_MODEL_KIND_TEMPORAL`) requires motion vectors,
   which we don't currently emit from the integrator. Generating
   motion vectors per-pixel is a separate package (~3 days on its
   own). When that exists, a follow-up flips this denoiser to
   temporal mode.

5. **Framebuffer ABI shared with OIDN.** Both denoisers read the
   same `"color"` / `"albedo"` / `"normal"` Framebuffer buffers.
   No new buffer types. The plugin difference is purely in which
   library does the inference. The pkg68 audit confirmed these
   buffers are unconditionally populated by the integrator
   ([include/raytracer.h:1653-1654](../../include/raytracer.h)
   + [include/raytracer.h:2451-2452](../../include/raytracer.h)).

6. **Use `cudaMalloc`-backed buffers (not OptiX-specific).** OptiX
   denoiser operates on CUDA device pointers; we already manage CUDA
   buffers in `cuda_renderer.cu` for path tracing. Reuse those
   allocations where possible to avoid an extra HtoD copy of the
   noisy color image per frame.

---

## Acceptance criteria

- [ ] On a CUDA + OptiX-enabled build, `astroray.gpu_optix_available()`
  returns `True`.
- [ ] `OptiXDenoiser::execute()` produces a finite output buffer with
  noise floor at least 5× lower than the input on a synthetic
  speckle-noise image (256×256, RGB, Gaussian noise σ=0.1).
- [ ] On the parity scene from pkg54a/b at 1080p, OptiX denoise time
  is **at least 1.5× faster** than OIDN-CUDA from pkg68. Record both
  numbers in Lessons.
- [ ] Final-render SSIM between OptiX-denoised and OIDN-denoised
  outputs ≥ 0.95 (they're comparable but not identical algorithms).
  Document the actual SSIM in Lessons; do not silently relax this gate.
- [ ] On a non-OptiX build (SDK absent at compile time, or
  ASTRORAY_ENABLE_OPTIX=OFF), the entire pipeline still works using
  OIDN; the OptiX plugin is simply not registered.
- [ ] On a non-CUDA runtime (CUDA SDK present at build but no NVIDIA
  GPU at runtime), the OptiX plugin construction fails gracefully and
  the addon falls back to OIDN with a log line.

---

## Non-goals

- No motion-vector generation from the integrator. Temporal mode is a
  follow-up package once we have motion vectors.
- No model-fine-tuning on Astroray-specific scenes. We use NVIDIA's
  shipped models as-is.
- No replacement of OIDN. Both backends ship; user picks.
- No GPU vendor abstraction layer. OptiX is NVIDIA-only by design;
  AMD/Intel/Apple users get OIDN.

---

## Progress

- [x] Write `cmake/FindOptiX.cmake` (or adapt NVIDIA SDK's).
- [x] Add `ASTRORAY_ENABLE_OPTIX` build flag with auto-detect default.
- [x] Implement `OptiXDenoiser` plugin with persistent state.
- [x] Implement model-kind selection (HDR vs AOV based on available
  guide buffers).
- [x] Add `gpu_optix_available()` Python binding.
- [x] Wire addon backend-selection logic with user override.
- [x] Add `tests/test_optix_denoiser.py`.
- [ ] Verify on RTX 5070 Ti: record OptiX vs OIDN-CUDA timing + SSIM
  in Lessons. *(pending — OptiX SDK + CUDA hardware verifier session)*

---

## Lessons

Verification 2026-05-10 on RTX 5070 Ti + OptiX 9.1.0:

- **Gate 1:** `[OptiX] Using CUDA device 0 (NVIDIA GeForce RTX 5070 Ti)`
  printed exactly once across N=4 renders on a persistent `Renderer`. ✅
- **Gate 2:** synthetic noise reduction at 256×256 — **5.31× OptiX,
  5.58× OIDN** (both ≥5× target). ✅
  Note: 64×64 fixture fails this gate due to two unrelated causes:
  (a) sliding-window variance estimator boundary artifacts at small
  image sizes, and (b) the empty-normal-guide defect (pkg75). The
  latter silently degrades AOV mode on every scene at every
  resolution — pkg75 will measurably improve this number further
  when it lands. The fixture in
  `tests/test_optix_denoise_reduces_noise_on_synthetic_input` was
  bumped from 64×64 to 256×256 in the verify(pkg70) PR to separate
  the gate from these two artifacts.
- **Gate 3:** OptiX vs OIDN-CUDA 1080p timing on the pkg54a/b parity
  scene (1920×1080, spp=2, max_depth=3, N=10 frames, 2-frame warmup):
  **OptiX 728.94 ms/frame vs OIDN-CUDA 1356.09 ms/frame = 1.86×
  speedup** (target ≥1.5×). ✅
- **Gate 4:** SSIM(OptiX, OIDN) on parity scene at spp=16, Reinhard
  tone-mapped: **0.9987** (target ≥0.95). ✅

Two unrelated build-hygiene issues caught during this verification
round but not blocking promotion (handled separately by the Codex
pkg71-baseline session's PR #215, already merged to main):

- `cmake/FindOptiX.cmake` glob did not match OptiX 9.x — was
  hard-coded to `OptiX SDK 7.*` / `8.*`. PR #215 broadens to
  `OptiX SDK *`.
- `plugins/passes/optix_denoiser.cpp` `std::max(v, 0.0f)` collides
  with the Windows `max` macro that OptiX 9 transitively includes
  via `<windows.h>`. PR #215 adds a `NOMINMAX` guard.

Both were latent because pkg70 was implemented and merged before
anyone built it with OptiX actually enabled on Windows; the OIDN
fallback path masked the issues end-to-end.
