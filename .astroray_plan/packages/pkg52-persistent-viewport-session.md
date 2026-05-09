# pkg52 — Persistent Viewport Session

**Pillar:** 5
**Track:** A
**Status:** done
**Estimated effort:** 2 sessions (~8 h)
**Depends on:** none (pkg37 already in)

---

## Goal

**Before:** The viewport renders once on `view_update` (depsgraph change) and shows a frozen image until the next setting change. Camera zoom/pan never re-renders. Every refresh recreates `astroray.Renderer`, re-uploads textures, and rebuilds the BVH.

**After:** Each viewport keeps a persistent `astroray.Renderer`. `view_draw` detects camera/region changes by hashing `(view_matrix, lens, region.width, region.height, view_camera_zoom, view_camera_offset)` and triggers progressive re-rendering via `tag_redraw()` until a target spp is reached. CAMERA-view zoom and pan now update the framing.

---

## Context

This is the most user-visible Blender bug. Cycles uses a persistent `Session` per viewport with a `RenderBuffers` accumulator and reads camera state every `view_draw`. We've effectively never wired that. Until this lands, "zoom and the picture should re-render" doesn't work, and large scenes are slow because every nudge rebuilds the world.

Without it, pkg56 (incremental scene sync) cannot be built — incremental sync requires a renderer that survives across frames.

---

## Reference

- Cycles viewport: `intern/cycles/blender/session.cpp` and `blender/sync.cpp` (Blender repo).
- Current code: [`view_update`](blender_addon/__init__.py:365) and [`view_draw`](blender_addon/__init__.py:433).
- Blender API: `bpy.types.RenderEngine.tag_redraw()`, `RegionView3D.view_camera_zoom`, `RegionView3D.view_camera_offset`.

---

## Prerequisites

- [x] pkg37 backend policy in (done).
- [x] `astroray.Renderer` can be `clear()`'d and reused without leaks.
- [x] Viewport accumulation is handled by the addon session over chunked
      `Renderer.render(samples=...)` calls, so no C++ accumulation API change
      was required.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_blender_viewport_session.py` | Stubbed Blender API tests for hash detection and progressive sample logic. |

### Files to modify

| File | What changes |
|---|---|
| [blender_addon/__init__.py](blender_addon/__init__.py) | Replace one-shot `view_update` with a persistent session: `_renderer`, `_camera_hash`, `_current_spp`, `_target_spp`. `view_update` only re-syncs scene; `view_draw` hashes camera state, resets accumulation on change, calls `tag_redraw()` until target spp is reached. Honor `rv3d.view_camera_zoom` and `rv3d.view_camera_offset` in `_setup_viewport_camera`. |
| [module/blender_module.cpp](module/blender_module.cpp) | If accumulation isn't already supported, add `Renderer::render(..., bool reset=true)` and a `Renderer::current_spp` property. |

### Key design decisions

1. **One renderer per `RenderEngine` instance.** Construct in the engine's first `view_update`, destroy in `__del__`. Do not store on the class — Blender re-uses one engine instance per viewport.
2. **Hash for camera invalidation, not callback.** Blender does not emit a "camera changed" event in the viewport; we have to detect it. A 6-tuple hash is enough.
3. **Progressive cap.** Render in chunks of `viewport_chunk_spp` (default 1) until `target_spp` is reached. Target = `preview_samples`. After target, stop calling `tag_redraw()`.
4. **CAMERA-view framing.** When `rv3d.view_perspective == 'CAMERA'`, apply `view_camera_offset` (2D image-plane shift) and `view_camera_zoom` (Blender-specific exponential zoom: `scale = (1.41421 + zoom / 50.0)**2 / 4.0`). Without this, CAMERA-view zoom in the viewport is ignored.
5. **No incremental sync yet.** Scene re-sync still happens in `view_update`. pkg56 owns incremental.

---

## Acceptance criteria

- [x] Zooming/orbiting the 3D View causes the image to re-render.
- [x] CAMERA-view zoom (`view_camera_zoom`) changes the rendered framing.
- [x] CAMERA-view pan (`view_camera_offset`) is hashed and applied to the
      image-plane camera shift.
- [x] The same renderer instance is reused across viewport updates/draws (covered by `tests/test_blender_viewport_session.py`).
- [x] Progressive accumulation/sample status is implemented; viewport renders
      in one-sample chunks by default until `preview_samples` is reached.
- [x] No regressions in focused `tests/test_blender_*` coverage as of the pkg53 reconciliation pass.

---

## Non-goals

- Do not implement incremental scene sync (pkg56).
- Do not change final-render `render(depsgraph)` behavior.
- Do not add "denoise during accumulation" yet — pkg62 owns viewport pass selection and OIDN preview.

---

## Progress

- [x] Confirm/extend viewport accumulation path.
- [x] Refactor viewport to reuse a persistent renderer across `view_update` / `view_draw`.
- [x] Implement camera hash + re-render in `view_draw`.
- [x] Progressive accumulation in `view_draw`.
- [x] Honor CAMERA-view zoom.
- [x] Honor CAMERA-view offset/pan in projection math.
- [x] Tests with Blender API stubs.

---

## Lessons

- Persistent renderer and camera-change invalidation landed, with tests for
  construction reuse, view-matrix changes, `view_camera_zoom`, progressive
  sample advancement, and `view_camera_offset` projection.
- The addon accumulates chunk outputs in the viewport session and calls
  `tag_redraw()` until the preview sample target is reached. `clear_passes()`
  is called before selecting viewport passes so pkg62 pass buffers do not stack
  across accumulation chunks.
- C++ `Camera` and Python `setup_camera()` now accept optional image-plane
  `shift_x` / `shift_y` parameters; existing callers keep the default centered
  projection.
