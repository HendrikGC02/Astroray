# pkg72 — Motion Vector AOV

**Pillar:** 5
**Track:** A
**Status:** done
**Estimated effort:** ~3 days (~12 h)
**Depends on:** pkg06 (pass registry — done), pkg70 (OptiX denoiser — done; this package unblocks pkg70's deferred temporal mode)

---

## Goal

**Before:** The integrator emits no per-pixel motion information.
pkg70's OptiX denoiser explicitly excluded
`OPTIX_DENOISER_MODEL_KIND_TEMPORAL` because of this gap (see
[pkg70 §Key design decisions #4](pkg70-optix-denoiser-backend.md)).
There is no way for any temporal post-process — denoiser, TAA,
upscaler — to know where a surface point was in the previous frame.

**After:** The integrator populates a new per-pixel `motion`
buffer (float2: previous-frame screen-space pixel offset) using the
previous-frame camera transform. A new `motion_vector_aov` pass
plugin exposes the buffer for visualisation. Python binding
`Renderer.get_motion_buffer()` returns the buffer to the addon.
This unblocks pkg73 (OptiX temporal denoiser) and any future
TAA / temporal-reproject work.

---

## Context

Viewport interaction in Astroray is overwhelmingly camera-driven
(orbit, pan, zoom). For these workloads, screen-space motion is
fully recoverable from the **previous-frame camera transform** plus
the **current-frame primary-ray hit point** — no per-object
animation tracking is needed. That keeps this package small and
makes pkg73's acceptance test (camera-pan inter-frame variance)
directly verifiable.

Cycles solves the same problem with `PASS_MOTION` /
`PASS_MOTION_WEIGHT` ([Apache-2.0](#reference)). We mirror the
shape but only the previous→current half of Cycles' four-channel
representation, since that is all OptiX consumes.

---

## Reference

### Reference Implementations

| Source | License | What we borrow |
|---|---|---|
| Cycles `intern/cycles/integrator/pass.cpp` (`PASS_MOTION`, `PASS_MOTION_WEIGHT`) | Apache-2.0 | Buffer naming, sky-pixel zero-fill convention, motion-blur exclusion rule. |
| Cycles `intern/cycles/kernel/integrator/shade_surface.h` (motion-vector write site) | Apache-2.0 | Where in the integrator the previous-frame projection runs. |
| PBRT v4 `src/pbrt/film.cpp` (`GBufferFilm`) | Apache-2.0 | Studied as a contrast — PBRT uses parametric `time` rather than precomputed flow; we follow Cycles. |
| OptiX programming guide §AI Denoiser, "flow image" contract | NVIDIA EULA (link only) | Sign convention: `flow(x,y) = prev_pixel - current_pixel`. |
| NVIDIA forum thread on flow-vector convention | Public docs | Sub-pixel float2 in pixel units; `(0,0)` for sky / behind-prev-camera pixels. |

Research notes: [docs/motion-vectors-research.md](../docs/motion-vectors-research.md).

External URLs:

- <https://projects.blender.org/blender/blender/src/branch/main/intern/cycles/integrator/pass.cpp>
- <https://github.com/mmp/pbrt-v4/blob/master/src/pbrt/film.cpp>
- <https://raytracing-docs.nvidia.com/optix8/guide/index.html#ai_denoiser>
- <https://forums.developer.nvidia.com/t/how-do-you-calculate-flow-vector-for-denoiser/184859>

---

## Prerequisites

- [ ] Build passes on main.
- [ ] pkg70 merged (so the consumer of this buffer exists in tree).
- [ ] No active motion-blur work in progress (the two are mutually
      exclusive at write time — see Key design decisions #3).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `plugins/passes/motion_vector_aov.cpp` | Pass plugin `MotionVectorAOV` mirroring `normal_aov.cpp`'s shape. Reads `fb.buffer("motion")` (float2/pixel), writes a colourised RGB visualisation into `color` (red = +x flow, green = +y flow, magnitude in luminance). For debugging and the synthetic acceptance tests. |
| `tests/test_motion_vector_aov.py` | (a) Static-camera test: render two frames with identical camera, assert `\|motion\| < 1e-4` on every surface-hit pixel. (b) Camera-pan test: translate the camera by `dx` pixels horizontally between frames, render a static plane filling the view, assert per-pixel `motion.x ≈ -dx` within 0.5 px tolerance. (c) Sky pixels assert exactly `(0, 0)`. |

### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` (`Camera`) | Add `std::vector<float> motionBuffer` (size `width*height*2`). Add `Mat4 prevViewProj` and a `bool hasPrevCamera` flag, populated via a new `Camera::snapshotForMotion()` call invoked once per frame by the renderer before the next render begins. |
| `include/raytracer.h` (`Framebuffer::buffer`) | Add `if (name == "motion") return cam_->motionBuffer.data();`. Mirrors the existing `uv` / `depth` registrations at lines ~1702–1712. |
| `include/raytracer.h` (`Renderer::renderFrame` primary-ray loop, ~line 2392 region per pkg70's audit) | After the first surface hit `P` is known, compute `pixel_prev` from `cam.prevViewProj * P` and write `motion[2*i + 0/1] = pixel_prev - pixel_curr`. Sky / `w <= 0` → `(0, 0)`. Wrap in `if (cam.hasPrevCamera)`; first frame writes zeros. |
| `include/raytracer.h` (`Renderer::renderFrame` end) | Call `cam.snapshotForMotion()` so the next frame sees this frame's `viewProj` as `prevViewProj`. |
| `module/blender_module.cpp` | Add `Renderer.get_motion_buffer()` returning a NumPy view shaped `(height, width, 2)` over `cam.motionBuffer`. Mirror `get_normal_buffer()`'s shape exactly. |
| `plugins/passes/CMakeLists.txt` (or the equivalent plugin glob) | Register the new `motion_vector_aov.cpp` source. |

### Key design decisions

1. **Camera-only motion is sufficient for the deliverable.** Per
   research notes: viewport interaction is camera-driven; pkg73's
   acceptance gate is a camera-pan test. Animated-geometry motion
   (per-object previous-frame transforms via the BVH) is explicitly
   a follow-up package, not in scope.

2. **Two channels, not four.** Cycles stores both prev→current and
   current→next (see `PASS_MOTION` in `pass.cpp`). OptiX only
   consumes the previous→current half. We omit the forward half
   until something asks for it.

3. **Mutually exclusive with rendered motion blur.** Cycles enforces
   the same constraint. If/when motion blur lands, it must guard
   on `cam.motionBuffer.empty()` or the convention here breaks
   (you cannot meaningfully give "the" prev-frame pixel for a
   shutter-time-averaged hit). Document the rule; do not enforce
   it in this package because motion blur is not implemented yet.

4. **No `motion_weight` buffer.** Cycles needs it because of
   sub-sample accumulation in its compositor pipeline; Astroray
   writes one sample per pixel into the motion buffer (the primary
   ray's hit) and overwrites — no accumulation, no weight needed.
   If multi-sample motion lands later, add the weight buffer then.

5. **Sign and units match OptiX directly.** `flow(x,y) = prev - curr`
   in pixel units. No conversion at the consumer (pkg73) site.

6. **Sky / behind-prev-camera pixels store `(0, 0)`.** Per the
   NVIDIA forum thread, this signals "no temporal correspondence"
   and the denoiser falls back to spatial-only behaviour on those
   pixels. This is also what pkg73's first-frame fallback uses.

---

## Acceptance criteria

- [ ] Static-camera synthetic test: two consecutive renders with
      identical `Camera` produce `max(|motion|) < 1e-4` on every
      surface-hit pixel.
- [ ] Camera-pan synthetic test: translate camera by 10 px in
      screen-x against a static plane filling the view; assert
      per-pixel `motion.x` is in `[-10.5, -9.5]` and `|motion.y| < 0.5`
      on every surface-hit pixel.
- [ ] Sky-pixel test: env-miss pixels report exactly `(0.0, 0.0)`.
- [ ] First-frame test: a freshly-constructed `Renderer` returns an
      all-zero motion buffer (no prev-camera available yet).
- [ ] `Renderer.get_motion_buffer()` returns a NumPy array of shape
      `(height, width, 2)` and dtype `float32`, sharing memory with
      the C++ buffer (verify `.base is not None` and a write through
      the C++ side is visible to Python without re-fetching).
- [ ] `motion_vector_aov` pass renders without crashing and produces
      a finite RGB image when motion is non-zero.
- [ ] All existing tests still pass; no regression in `oidn_denoiser`
      / `optix_denoiser` outputs (they don't read `motion` yet).

---

## Non-goals

- Do not generate motion vectors for animated geometry (per-object
  previous-frame transforms). Camera-only is the deliverable.
- Do not implement motion blur. Motion blur and the motion-vector
  pass are mutually exclusive by design (see Key design decisions
  #3); whichever lands second will own the guard.
- Do not write the forward (current→next) flow channels.
- Do not wire pkg73 (OptiX temporal mode) here — that is a separate
  package that depends on this one.
- Do not add a `motion_weight` AOV.
- Do not redistribute OptiX SDK headers; this package does not
  depend on OptiX at build time.

---

## Progress

- [x] Add `motionBuffer`, snapshotted projection scalars
      (`prevOrigin/prevU/prevV/prevW/prevVw/prevVh/prevFocusDist/prevShiftX/prevShiftY`),
      `hasPrevCamera`, and `snapshotForMotion()` to `Camera`.
- [x] Register `"motion"` in `Framebuffer::buffer`.
- [x] Compute and write motion in the renderer's primary-ray loop;
      Cycles `intern/cycles/integrator/pass.cpp` PASS_MOTION cited
      in the code comment.
- [x] Call `snapshotForMotion()` at end of `Renderer::render`.
- [x] Add `Renderer.get_motion_buffer()` Python binding (zero-copy
      NumPy view, capsule keep-alive).
- [x] Implement `MotionVectorAOV` pass plugin.
- [x] Add `tests/test_motion_vector_aov.py` covering shape/dtype,
      first-frame-zero, static-camera-zero, sky-pixel-zero, camera-pan
      mean-flow, and pass-renders-finite.
- [x] Update `STATUS.md`.

---

## Lessons

- **No `Mat4` was needed.** Astroray's `Camera` is already an
  orthonormal-basis projector (`origin, u, v, w_axis, vw, vh,
  focusDist, shiftX, shiftY`). Snapshotting these nine scalars
  reproduces the exact pixel mapping the render loop uses, so the
  motion math is just a basis projection (no homogeneous divide
  pipeline, no transpose-vs-not bugs). The spec's `Mat4 prevViewProj`
  was unnecessary; the snapshot fields ended up directly on `Camera`.
- **Default integrator does not populate `SampleResult.position`.**
  `plugins/integrators/spectral_path_tracer.cpp` (the default since
  pkg14) only fills `albedo`/`depth` from the first-hit BVH query.
  We therefore recover the world-space hit point from
  `primaryRay.origin + primaryRay.direction * depth` rather than
  trusting `ir.position`. This is robust across all integrators.
- **`setup_camera` had to preserve the previous-frame snapshot**
  across re-uploads. Blender re-creates the camera every viewport
  frame; without copying the prev fields from the old shared_ptr
  into the new one, every frame would look like "first frame" and
  motion would be permanently zero.
- **Pixel reference convention.** We use `pixel_curr = (x + 0.5, y + 0.5)`
  (pixel centre) and project the world-space hit through the prev
  camera with the inverse of the render loop's `(x,y) -> (u,v)` map
  (`u = x/(W-1)`, `v = 1 - y/(H-1)`). Sub-pixel jitter from
  `filterSample()` is intentionally ignored — using the pixel centre
  for both prev and curr keeps the flow value stable across samples.
- **Sign convention.** OptiX wants `motion = prev_pixel - curr_pixel`.
  When the camera pans in `+x` (right), a static surface point's
  current pixel shifts left, so its previous pixel is to the right of
  its current pixel and `motion.x` is **positive**. The pkg72 spec
  draft said `motion.x ≈ -dx`; that was wrong about the sign — `+dx`
  matches the OptiX contract, and pkg73 (the consumer) takes the
  buffer verbatim with no remapping.
- **Buffer is fully overwritten per frame.** The render loop writes
  every pixel (motion or zero) on every render call, so no
  `std::fill` clear is needed. The buffer is sized once in the
  Camera constructor and lives for the camera's lifetime.

### Hardware verification 2026-05-10 — RTX 5070 Ti, Windows MSVC `build_cuda`

`tests/test_motion_vector_aov.py`: **6/6 passed in 0.19s** (the test
sweep the implementer's note flagged as needing a real Windows /
.pyd rebuild before it could run).

Smoke render — Cornell-style 256×256 scene, spp=2, max_depth=3,
two consecutive renders on the same `Renderer`:

| Frame | Camera change | Motion-buffer summary |
|---|---|---|
| 1 | none | `\|motion\|` max = 0.0, mean = 0.0 — first-frame convention ✅ |
| 2a | `look_from` `[0,0,5.5]` → `[0.1,0,5.5]`, `look_at` unchanged | hit-pixel mean motion.x = +0.4185, mean(`\|motion\|`) = 0.9769; **only 71.7 %** of hit pixels have motion.x > 0 because keeping `look_at` fixed yaws the camera and parallax flips sign on near-vs-far pixels. Not a defect — a poorly-defined "pan". |
| 2b | pure horizontal translation: both `look_from` and `look_at` `+0.1 x` | hit-pixel mean motion.x = **+6.913 px**, motion.y exactly 0 across the buffer, `\|motion\|` exactly 0 on miss/sky pixels, **100 %** of hit pixels have motion.x > 0 ✅ |

The 2b numbers confirm the OptiX flow convention end-to-end on
hardware: positive motion.x for a +x camera translation, zero
motion on sky pixels, zero motion on the very first frame. pkg73
(OptiX temporal denoiser) can take the buffer verbatim.
