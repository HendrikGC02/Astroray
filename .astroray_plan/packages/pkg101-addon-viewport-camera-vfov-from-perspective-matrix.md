# pkg101 — Blender addon viewport camera: vfov mis-extracted from `perspective_matrix`

**Pillar:** 5 (addon)
**Track:** A (correctness, small Python-only fix)
**Codex-paste-ready:** yes
**Status:** open
**Depends on:** none
**Estimated effort:** small (<½ day; few-line fix + regression test)

---

## Goal

**Before:** Rotating/orbiting the 3D-view camera in a Blender PERSP or
ORTHO view causes the rendered object to "shrink, grow, flip, and rotate
differently from how the camera is actually moving," and the framing
fails to line up with Blender's viewport overlay. Owner-reported
symptom 2026-05-24.

**After:** Camera orbit/pan/dolly in PERSP/ORTHO and CAMERA views
produces a rendered frame whose vertical FOV and framing match
Blender's viewport overlay to within float tolerance. A pytest exercises
several rotated `RegionView3D` states and asserts the vfov extracted by
the addon equals the vfov implied by `rv3d.window_matrix` (the projection
matrix), not by `rv3d.perspective_matrix` (the projection × view product).

---

## The defect (verified on HEAD 24b5701, 2026-05-24)

`blender_addon/__init__.py` extracts the rendered vfov in two sites:

- `_setup_viewport_camera` lines 1683–1700 (PERSP/ORTHO branch).
- `_apply_camera` lines 1824–1834 (CAMERA-view branch, called from
  `_setup_viewport_camera` via line 1663–1666).

Both sites read:

```python
persp = rv3d.perspective_matrix
if abs(persp[1][1]) > 1e-6:
    vfov = math.degrees(2.0 * math.atan(1.0 / persp[1][1]))
```

with the comment *"perspective_matrix[1][1] = 1 / tan(vfov/2) for a
symmetric frustum."* That identity is only true of the **projection
matrix alone**.

In Blender's `bpy.types.RegionView3D`, `perspective_matrix =
window_matrix @ view_matrix` (documented). `window_matrix` is the pure
projection; `view_matrix` is the camera-to-world inverse including
rotation. Their product mixes the rotation of the view into element
`[1][1]`. As the camera orbits, `perspective_matrix[1][1]` changes
with `cos(pitch)` etc., so the extracted vfov grows and shrinks with
camera rotation — exactly the reported symptom.

The fix is to read `rv3d.window_matrix[1][1]` (the projection matrix),
which is the OpenGL convention `1 / tan(vfov/2)` for a symmetric
frustum and is rotation-invariant.

**Why this shipped:** pkg95 added the perspective-matrix extraction as
"BUG-08" specifically to align with Blender's overlay (PR #305). The
intent was correct (read Blender's projection rather than re-derive
from sensor/lens) but the matrix attribute chosen carries view rotation.
No test exercises a rotated view, so a fixed-identity-rotation manual
check looked correct.

---

## Reference

### Internal
- `blender_addon/__init__.py` lines 1683–1700 (PERSP/ORTHO) and 1824–1834
  (CAMERA view).
- `module/blender_module.cpp` lines 790–816 (`setupCamera`) and
  `include/raytracer.h` lines 1840–1875 (`Camera` constructor) — the
  consumer. `vh = 2 * tan(vfov/2) * focusDist`; an over-large vfov
  scales the image plane and changes apparent object size.
- `tools/blend_import/scene_builder.py` `_emit_camera` (line 144) —
  importer-side vfov extraction; uses sensor/lens directly and is **not
  affected** (no `perspective_matrix` use).

### External
- Blender Python API `RegionView3D` docs: `perspective_matrix = window_matrix @
  view_matrix` (see `bpy.types.RegionView3D.perspective_matrix`).
- Cycles `intern/cycles/blender/camera.cpp` `BlenderCamera::sync` uses
  `cam->sensor_height / cam->sensor_width` and `cam->lens`, not
  `perspective_matrix`, for the projection axis. Apache-2.0.

CLAUDE.md §6 N/A (no novel numerical algorithm; this is a Blender API
read fix).

---

## Fix

Replace `rv3d.perspective_matrix[1][1]` with `rv3d.window_matrix[1][1]`
at both sites. Keep the existing degenerate-fallback (`abs(...) <
1e-6`) and the existing CAMERA-view zoom scaling
(`vfov_scale`) intact. **Do not** touch `_emit_camera` or other
camera-math code (CLAUDE.md §3 surgical).

---

## Acceptance criteria

- [ ] A pytest in `tests/test_addon_viewport_camera_vfov.py` constructs a
      handful of synthetic `RegionView3D`-like stubs with **different
      rotations** but the **same projection** (same `window_matrix`) and
      asserts the addon's vfov extractor returns the same vfov for all
      of them (rotation-invariant). The test must fail on current HEAD
      and pass after the fix.
- [ ] Manual visual check on RTX: orbit the camera around a primitive
      cube; the rendered frame's framing and apparent object size remain
      stable, and the rendered image aligns with Blender's viewport
      overlay (no "shrink/grow/flip" while orbiting). Recorded in the
      PR description with a short before/after gif or paired stills.
- [ ] CI green.

## Hard non-goals

- No refactor of `_apply_camera` or `_setup_viewport_camera` beyond the
  matrix swap.
- No change to the F12 batch-render path that already uses sensor/lens.
- No change to `tools/blend_import/scene_builder.py`.

---

## Provenance

Owner-reported in goal-capture 2026-05-24: *"As I rotate the camera
around the object, the object appears to shrink and grow, flip and
rotate completely different from how the camera is actually moving. It
also obviously because of this doesn't line up with the viewport."*
Architect traced to `perspective_matrix[1][1]` misuse (pkg95 BUG-08
fix).
