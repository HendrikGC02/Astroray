# pkg75 — Integrator Normal-Guide Population for Denoiser AOV Mode

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 2–3 days
**Depends on:** nothing — small, focused integrator fix

---

## Goal

**Before:** `Camera::normalBuffer` is sized unconditionally
([include/raytracer.h:1653-1654](../../include/raytracer.h), per the
pkg68 audit) but the integrator path taken by the default `Renderer`
leaves it filled with `Vec3(0)`. `fb.hasBuffer("normal")` returns
`true` (per pkg68 Lessons re: `Camera::normalBuffer` always being
allocated), so OIDN's AOV mode and OptiX's AOV mode both bind the
buffer as a guide image — but the data they upload is degenerate
(all zeros). AOV mode silently behaves as HDR + albedo only.

This was **the empty-normal-buffer defect surfaced during pkg70
verification 2026-05-10**. Both denoisers measured 5.31× / 5.58×
synthetic-noise reduction on a 256×256 Cornell scene at spp=2 — well
above the 5× gate, but the gate-pass-margin is artificially thin
because the AOV path is degraded.

**After:** The integrator writes the first-hit world-space (or
shading) normal into `normalBuffer` for every primary ray hit on
every code path that the default `Renderer` exercises. AOV-mode
denoising actually receives the geometric guide it expects. Existing
denoise-on-render flows automatically benefit; no plugin changes
required.

---

## Context

There is already one write site in `include/raytracer.h:2451-2452`:

```cpp
cam.albedoBuffer[idx] = albedo;
cam.normalBuffer[idx] = normal;
```

That site populates the AOV buffers correctly when its enclosing code
path is taken (a spectral / extended path tracer). The defect is that
the integrator path the default `Renderer` walks for the canonical
`color` render does **not** reach this site, so the buffer stays at
its `resize(..., Vec3(0))` initial state. The pkg68 Lessons section
explicitly noted that `Framebuffer::hasBuffer("albedo"/"normal")`
"always returns true" — that contract is currently fulfilled at the
type level but violated at the data level.

---

## Reference

- **Cycles `intern/cycles/integrator/pass.cpp`** (Apache-2.0,
  mirrorable pattern): `PASS_NORMAL` is populated as the geometric
  normal at the first non-transparent hit, transformed into
  world-space and written once per primary sample (averaged across
  samples per pixel). For glossy/rough surfaces Cycles uses the
  **shading** normal (interpolated, not flat-face) for better
  denoiser quality. We should match this convention.
  - <https://projects.blender.org/blender/blender/src/branch/main/intern/cycles/integrator/pass.cpp>
- **OIDN denoiser guide spec**: world-space, unit-length, mean ≈
  surface orientation. <https://www.openimagedenoise.org/documentation.html#guide-images>
- **OptiX denoiser guide spec**: same as OIDN; the OptiX denoiser
  re-normalizes internally but documents unit-length input as
  expected. See `optix_denoiser_invoke()` in OptiX 8.x/9.x guide.
- **Existing in-tree write site:** `include/raytracer.h:2451-2452`
  (the spectral integrator path).
- **AOV plugin consumers:** `plugins/passes/oidn_denoiser.cpp`
  (binds normal guide when `fb.hasBuffer("normal")`),
  `plugins/passes/optix_denoiser.cpp:108,162-179` (uploads + binds
  to `OptixDenoiserGuideLayer::normal`).

---

## Prerequisites

- [ ] Confirm which integrator path the default `Renderer.render()`
      currently takes for the canonical color render (likely
      `path_tracer` or `multiwavelength_path_tracer` depending on
      build flags). Diff its inner loop against the
      `raytracer.h:2451-2452` site to identify the missing assignment.
- [ ] Confirm whether `cam.normalBuffer` is the right write target
      (vs. a per-thread accumulator that should reduce into it at
      sample-end).

---

## Specification

### Files to modify

| File | What changes |
|---|---|
| `plugins/integrators/<the-actual-default-path-tracer>.cpp` (or `include/raytracer.h` inner loop, depending on dispatch) | After the first ray–surface intersection of each primary ray, write the world-space shading normal into `cam.normalBuffer[idx]`. Average across samples-per-pixel the same way `albedoBuffer` is averaged today. Match Cycles `PASS_NORMAL` semantics: shading normal at first non-transparent hit, world-space, unit length. |
| `plugins/integrators/multiwavelength_path_tracer.cpp` | Same fix here if the spectral path is the actual default for some build flags — reuse the existing `2451-2452` write site if reachable, or replicate the assignment. |
| (optional) `src/gpu/path_trace_kernel.cu` | Mirror the CPU change in the GPU megakernel so GPU-rendered AOVs match. Only if the default Renderer dispatches to GPU when `set_use_gpu(True)` is the user's choice. |

### Files to create

| File | Purpose |
|---|---|
| `tests/test_normal_buffer_populated.py` | New test — synthetic Cornell scene (lambertian sphere on a floor under a ceiling light), render at spp=2, assert `r.get_normal_buffer()` has nonzero values at every pixel that the depth/object-index buffer says was hit; assert mean `‖normal‖ = 1.0 ± 0.01` over hit pixels. |

### Files NOT to touch

- `plugins/passes/oidn_denoiser.cpp` — already reads the buffer
  correctly via `fb.buffer("normal")` and uploads to OIDN.
- `plugins/passes/optix_denoiser.cpp` — already reads + uploads +
  binds correctly.
- `plugins/passes/normal_aov.cpp` — the standalone AOV-pass plugin
  is correct as-is; the defect is upstream of it.

---

## Acceptance criteria

- [ ] Given the test scene in `tests/test_normal_buffer_populated.py`:
      every pixel that the depth buffer marks as hit has a non-zero
      normal in `r.get_normal_buffer()`. Pixels with zero depth (env
      / miss) may remain zero.
- [ ] Mean `‖normal‖` across hit pixels = 1.0 ± 0.01 (unit vectors).
- [ ] `tests/test_normal_buffer_populated.py` passes.
- [ ] **Re-run the pkg70 synthetic-noise test at 256×256 with pkg75
      in place: noise reduction ratio improves over the pkg70-only
      baseline.** Record both numbers in pkg75 Lessons:
      ```
      pkg70 only (this verification, 2026-05-10):
        OptiX 5.31×, OIDN 5.58×
      pkg70 + pkg75 (after this package lands):
        OptiX <NEW>×,  OIDN <NEW>×
      ```
- [ ] **Re-measure the pkg68 OIDN A/B baseline** (same harness as
      `verify(pkg68)` in PR #206 — 256×256 spp=2 max_depth=3 N=100
      warmup=3, OIDN-on vs OIDN-off). Record in pkg75 Lessons:
      ```
      pre-pkg68 (c934bdf):           OIDN-on 130.01 ms / OIDN-off 23.52 ms
      post-pkg68 (1253894):          OIDN-on  50.67 ms / OIDN-off 23.81 ms  → 2.57×
      post-pkg68 + pkg75 (this pkg): OIDN-on  <NEW> ms / OIDN-off <NEW> ms  → <NEW>×
      ```
      A small additional speedup OR cleaner output at the same speed
      is acceptable — either is a win.

---

## Non-goals

- **Not a refactor of the normal pass plugin.** `plugins/passes/normal_aov.cpp` stays as-is.
- **Not adding new buffer types** — just populating the existing `normalBuffer` correctly.
- **Not GPU wavefront refactor.** If the default render path is CPU, fix it on CPU; touch the GPU kernel only if the GPU path is actually exercised by the canonical `Renderer.render()` flow.

---

## Progress

- [ ] Identify the default integrator dispatch path on a clean
      Renderer (instrument `r.render()` with a debug print, or read
      the dispatcher in `module/blender_module.cpp` /
      `include/raytracer.h`).
- [ ] Add the first-hit-shading-normal write next to the existing
      `cam.albedoBuffer[idx] = albedo` site on that path.
- [ ] Write `tests/test_normal_buffer_populated.py`.
- [ ] Re-run pkg70 synthetic-noise test; record before/after numbers.
- [ ] Re-run pkg68 A/B baseline; record before/after numbers.

---

## Lessons

(to be filled after implementation)
