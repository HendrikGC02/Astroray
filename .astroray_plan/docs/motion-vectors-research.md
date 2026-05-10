# Motion Vectors + OptiX Temporal Denoiser — Research Notes

Background reading for pkg72 (motion-vector AOV) and pkg73 (OptiX temporal
denoiser). Saved per CLAUDE.md §6 (cite, borrow, verify).

---

## Reference implementations surveyed

### Cycles motion pass — Apache-2.0, mirrorable

- File: `intern/cycles/integrator/pass.cpp` in the Blender mono-repo.
  Search keys: `PASS_MOTION`, `PASS_MOTION_WEIGHT`.
  Repo: <https://projects.blender.org/blender/blender> (also mirrored on
  <https://github.com/blender/blender>).
- License: Apache-2.0.
- Key facts (from Blender devtalk + commit `8393ccd076` — "Cycles: Add
  OptiX temporal denoising support"):
  - Cycles' `PASS_MOTION` stores **2D vectors to both the next AND
    previous frame** (4 channels: `(prev.x, prev.y, next.x, next.y)`).
    OptiX temporal mode only consumes the previous→current direction.
  - Cycles enforces: motion-vector pass and rendered motion blur are
    mutually exclusive — you cannot have per-frame motion blur and
    temporal denoising at the same time.
  - Cycles also writes a `PASS_MOTION_WEIGHT` so the compositor can
    normalize when multiple sub-samples accumulate into a pixel.

### PBRT v4 — Apache-2.0, mirrorable

- File: `src/pbrt/film.cpp` — searched, **no explicit per-pixel motion
  vector storage**. PBRT v4's `GBufferFilm` records `visibleSurface->time`
  and applies `outputFromRender.ApplyInverse(p, time)`, i.e. PBRT works
  with parametric time-of-hit rather than a precomputed flow image.
  Repo: <https://github.com/mmp/pbrt-v4>.
- Implication: Cycles is the cleaner reference for our use case
  (per-pixel screen-space flow consumed by an OptiX denoiser).

### NVIDIA OptiX 8/9 denoiser — temporal mode

- Programming guide: <https://raytracing-docs.nvidia.com/optix8/guide/index.html>
  §"AI-Accelerated Denoiser". (HTTPS sometimes 403/cert-fails depending
  on the fetch path; the OptiX 9 host-API page is mirrored at
  <https://raytracing-docs.nvidia.com/optix9/api/group__optix__host__api__denoiser.html>
  and contains identical API contract text.)
- License: NVIDIA OptiX SDK License Agreement. Headers **not
  redistributable**; we link against a user-installed SDK exactly as
  pkg70 already does.
- Contract for `OPTIX_DENOISER_MODEL_KIND_TEMPORAL` /
  `OPTIX_DENOISER_MODEL_KIND_TEMPORAL_AOV`:
  1. **Flow image** in `OptixDenoiserGuideLayer::flow` — 2D vectors in
     pixel space, "flow from previous to current frame" (i.e. for each
     pixel in the current frame, the displacement from where that
     surface point was sampled in the previous frame).
  2. **Normal guide** must be 3D camera-space vectors (XYZ used; in
     non-temporal modes only XY are read).
  3. `previousOutputInternalGuideLayer` and `outputInternalGuideLayer`
     must both be allocated, pixel format
     `OPTIX_PIXEL_FORMAT_INTERNAL_GUIDE_LAYER`, dimensions matching the
     other layers.
  4. `previousOutput` (in `OptixDenoiserLayer`) must hold the denoised
     beauty of the previous frame. First-frame fallback: pass the
     current noisy beauty + a zeroed flow image.

### Cycles' OptiX temporal wiring — Apache-2.0, mirrorable

- Files: `intern/cycles/device/optix/device_impl.cpp` and
  `intern/cycles/integrator/denoiser_gpu.cpp`.
  Search key: `OPTIX_DENOISER_MODEL_KIND_TEMPORAL`, `previousOutput`.
- Original commit:
  <https://developer.blender.org/rB8393ccd07634> ("Cycles: Add OptiX
  temporal denoising support").
- Forum thread that walks through the wiring, gotchas, and quality
  observations:
  <https://devtalk.blender.org/t/taking-a-look-at-optix-7-3-temporal-denoising-for-cycles/18656>
- Key reusable patterns:
  - Lazy upgrade from HDR→AOV→TEMPORAL_AOV is *not* supported by a
    single denoiser handle — each model kind needs its own
    `optixDenoiserCreate`. Cycles destroys + recreates on mode change.
  - The internal-guide-layer pair is round-robined across frames: this
    frame's `outputInternalGuideLayer` becomes next frame's
    `previousOutputInternalGuideLayer`.
  - First frame is detected by an `is_first_frame_` flag; on first
    frame the code passes the noisy beauty as `previousOutput` and a
    zero buffer as `flow`.

### NVIDIA forum — flow-vector convention sanity check

- <https://forums.developer.nvidia.com/t/how-do-you-calculate-flow-vector-for-denoiser/184859>
  Confirms: for each pixel `(x, y)` in the **current** frame, the flow
  value is `prev_pixel_xy - current_pixel_xy` — i.e. "where did this
  surface point come from in the previous frame, in pixel units".
  Sub-pixel precision matters; the denoiser samples the previous-output
  with bilinear interpolation under the hood.

---

## Math we will reproduce (pkg72)

Camera-only motion (sufficient for static-geometry viewport stability,
which is pkg73's acceptance gate):

```
Given:
  P_world      : world-space hit point sampled by the primary ray
  cam_curr     : current frame camera (view + projection)
  cam_prev     : previous frame camera (view + projection)
  pixel_curr   : (x, y) integer pixel of the primary ray

Compute:
  P_clip_prev  = cam_prev.proj * cam_prev.view * P_world
  P_ndc_prev   = P_clip_prev.xy / P_clip_prev.w
  pixel_prev   = ((P_ndc_prev * 0.5 + 0.5) * (width, height))

Store:
  motion(x,y) = pixel_prev - pixel_curr        // float2, OptiX convention
```

Sky / env-miss pixels store `(0, 0)` (no surface point, no flow).
Negative-w (point behind previous-frame camera) is also stored as
`(0, 0)` — the denoiser will fall back to spatial-only behaviour for
those pixels.

This is **camera-only** motion. Animated geometry would need the
previous-frame object transform looked up via the BVH instance; that
is explicitly out of scope for pkg72 — viewport interaction is
camera-driven and the static-geometry test covers it.

---

## License compliance summary

| Source | License | Action |
|---|---|---|
| Cycles `pass.cpp`, `device/optix/*` | Apache-2.0 | Mirror with `Cycles <file>:<line>` citation in code comments. |
| PBRT v4 `film.cpp` | Apache-2.0 | Studied, not mirrored (different model). Cite in research notes only. |
| OptiX SDK headers | NVIDIA EULA, **not redistributable** | Link only. Matches pkg70's existing handling. |
| OptiX programming guide text | NVIDIA docs | Cite by URL; do not paste verbatim. |
