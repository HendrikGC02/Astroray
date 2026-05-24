# pkg103b — Camera Motion Blur Addon Wiring (Blender Addon)

**Pillar:** 5 (addon)
**Track:** A (single-feature wiring)
**Codex-paste-ready:** yes (well-scoped depsgraph + pybind wiring)
**Status:** done (PR #372, 2026-05-24 — wired `set_camera_motion_blur` via depsgraph T/R/S decomposition; CENTER shutter window; 3/3 tests green)
**Depends on:** pkg88-A (done)
**Estimated effort:** 1 day (depsgraph evaluation + transform decomposition + test)

---

## Goal

**Before:** pkg88-A (PR #284, 2026-05-15) shipped renderer-side camera motion blur via T/R/S decomposition + quaternion slerp. The pybind binding `set_camera_motion_blur(transform_start, transform_end)` (line 1953 in `module/blender_module.cpp`) exists, but the Blender addon never calls it. Enabling `scene.render.use_motion_blur` has no effect on the camera — renders are crisp freeze-frames instead of showing motion streaks.

**After:** When `scene.render.use_motion_blur == True`, the addon evaluates the camera transform at shutter start and end via Blender's depsgraph, decomposes the two 4×4 matrices, and calls `renderer.set_camera_motion_blur(T_start, T_end)`. Rendering a panning or rotating camera produces correct motion streaks. SSIM vs Cycles ≥ 0.95 on a simple camera rotation test scene.

---

## Context

pkg103 Phase 1 (blender-addon-wiring-audit-2026-05-24.md) identified `set_camera_motion_blur` as the second-highest-priority missing addon wiring. pkg88-A is marked "done" in STATUS.md, but the feature is invisible to Blender users without this wiring.

pkg88-A shipped camera motion blur only (pkg88-B object transform blur and pkg88-C deformation blur are deferred). This package wires the camera-only path; object/deformation blur wiring will be pkg88-B/C follow-ups when those renderer features ship.

---

## Specification

### 1. Depsgraph Evaluation for Camera Transforms

Extract camera world-space transform at two time samples:
- `t_start = frame_current + motion_blur_shutter_offset`
- `t_end = t_start + motion_blur_shutter`

Blender's depsgraph allows evaluating the scene at arbitrary fractional frames. The pattern (borrowed from Cycles `sync.cpp::sync_camera_motion`):

```python
def get_camera_transform_at_time(scene, camera_obj, frame):
    """Evaluate depsgraph at `frame` and return camera.matrix_world as 4×4."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    # Temporarily set scene frame
    original_frame = scene.frame_current_final
    scene.frame_set(frame, subframe=0.0)
    depsgraph.update()  # Force depsgraph recalc at new frame
    evaluated_camera = camera_obj.evaluated_get(depsgraph)
    matrix = evaluated_camera.matrix_world.copy()  # 4×4 mathutils.Matrix
    scene.frame_set(original_frame, subframe=0.0)  # Restore
    depsgraph.update()
    return matrix
```

**Shutter timing:** Blender's `render.motion_blur_shutter` is the shutter open duration (in frames). `motion_blur_position` controls the shutter center:
- `"START"` → shutter opens at `frame`, closes at `frame + shutter`.
- `"CENTER"` → shutter opens at `frame - shutter/2`, closes at `frame + shutter/2`.
- `"END"` → shutter opens at `frame - shutter`, closes at `frame`.

Map these to `(t_start, t_end)`:

```python
shutter = scene.render.motion_blur_shutter
position = scene.render.motion_blur_position
frame = scene.frame_current

if position == 'START':
    t_start, t_end = frame, frame + shutter
elif position == 'CENTER':
    t_start, t_end = frame - shutter / 2, frame + shutter / 2
elif position == 'END':
    t_start, t_end = frame - shutter, frame
```

### 2. Call Site in `convert_scene`

Around line 1730 (after `set_film_exposure`, before `set_seed`):

```python
if scene.render.use_motion_blur:
    camera_obj = scene.camera
    if camera_obj is not None:
        shutter = scene.render.motion_blur_shutter
        position = scene.render.motion_blur_position
        frame = scene.frame_current

        # Compute shutter start/end times
        if position == 'START':
            t_start, t_end = frame, frame + shutter
        elif position == 'CENTER':
            t_start, t_end = frame - shutter / 2, frame + shutter / 2
        elif position == 'END':
            t_start, t_end = frame - shutter, frame
        else:
            t_start, t_end = frame, frame + shutter  # fallback

        # Evaluate camera at both times
        T_start = get_camera_transform_at_time(scene, camera_obj, t_start)
        T_end = get_camera_transform_at_time(scene, camera_obj, t_end)

        # Convert mathutils.Matrix (4×4) to nested list for pybind
        T_start_list = [list(row) for row in T_start]
        T_end_list = [list(row) for row in T_end]

        renderer.set_camera_motion_blur(T_start_list, T_end_list)
```

**Edge case:** If `camera_obj is None`, skip the call (addon already handles missing camera elsewhere). If `T_start == T_end` (static camera), the renderer should detect this and skip motion blur internally (pkg88-A may already handle this; verify via test).

### 3. Test

Add to `tests/test_blender_addon.py`:

```python
def test_camera_motion_blur_wiring():
    """Verify motion blur toggle wires to renderer.set_camera_motion_blur."""
    scene = create_test_scene_with_animated_camera()
    scene.render.use_motion_blur = True
    scene.render.motion_blur_shutter = 0.5
    scene.render.motion_blur_position = 'CENTER'
    renderer = create_mock_renderer()
    convert_scene(scene, renderer)
    assert renderer.set_camera_motion_blur.called
    # Verify transforms differ
    T_start, T_end = renderer.set_camera_motion_blur.call_args
    assert T_start != T_end
```

Or, for a full render test:

```python
def test_camera_motion_blur_rotating_camera():
    """Render a rotating camera with motion blur; confirm streaking."""
    scene = create_test_scene_rotating_camera(rotation_speed=45.0)  # 45°/frame
    scene.render.use_motion_blur = True
    scene.render.motion_blur_shutter = 0.5
    result = render_scene(scene, spp=64)
    # Check for streaking (e.g., SSIM vs static render < 0.8)
    static_result = render_scene(scene_no_motion_blur, spp=64)
    assert ssim(result, static_result) < 0.8  # Motion blur creates visible difference
    # Compare to Cycles
    cycles_result = render_with_cycles(scene, spp=64)
    assert ssim(result, cycles_result) >= 0.95  # Cycles parity
```

---

## Reference

### Internal
- `module/blender_module.cpp:1953` — `set_camera_motion_blur` pybind.
- `src/raytracer.cpp` (pkg88-A PR #284) — T/R/S decomposition + quaternion slerp for camera interpolation.
- `.astroray_plan/docs/blender-addon-wiring-audit-2026-05-24.md` (pkg103 Phase 1) — audit that surfaced this gap.
- `.astroray_plan/packages/pkg88-motion-blur.md` — parent spec (pkg88-A camera-only phase).

### External
- Cycles `intern/cycles/blender/camera.cpp::BlenderSync::sync_camera_motion` (Apache-2.0) — reference for depsgraph evaluation at shutter start/end. [Link to Blender source](https://projects.blender.org/blender/blender/src/branch/main/intern/cycles/blender/camera.cpp) (search for `sync_camera_motion`).
- Blender Python API: [`bpy.types.Scene.frame_set`](https://docs.blender.org/api/current/bpy.types.Scene.html#bpy.types.Scene.frame_set), [`Depsgraph.update`](https://docs.blender.org/api/current/bpy.types.Depsgraph.html#bpy.types.Depsgraph.update).

---

## Acceptance Criteria

- [ ] `renderer.set_camera_motion_blur(T_start, T_end)` called when `scene.render.use_motion_blur == True`.
- [ ] Depsgraph evaluation at `t_start` and `t_end` correctly computes camera transforms (test with animated camera).
- [ ] Shutter timing respects `motion_blur_position` (START / CENTER / END).
- [ ] Test confirms motion streaking appears in render output (SSIM vs static < 0.8).
- [ ] SSIM vs Cycles ≥ 0.95 on a simple camera rotation test scene.
- [ ] Edge case: static camera (T_start == T_end) does not error (renderer skips motion blur internally or treats as no-op).

---

## Hard Non-Goals

- **No object transform motion blur** — pkg88-B deferred. This package wires camera only.
- **No deformation motion blur** — pkg88-C deferred.
- **No Blender rolling shutter** — Blender's `motion_blur_rolling_shutter_*` props are EEVEE-only; Cycles and Astroray ignore them. No wiring needed.
- **No per-camera motion blur override** — use the global `scene.render.use_motion_blur` toggle. Future refinement if users request per-camera control.

---

## Known Risks

1. **Depsgraph evaluation cost:** Evaluating the depsgraph at two time samples may slow down interactive viewport renders if motion blur is enabled. Cycles pays this cost too; acceptable for offline rendering. If it becomes a bottleneck, we can cache the transforms or skip motion blur in viewport mode (check `context.region_data.view_perspective`).

2. **Frame-set side effects:** Temporarily changing `scene.frame_current` via `frame_set` may trigger callbacks or invalidate caches. The Cycles reference restores the original frame immediately after evaluation, which should be safe. Test with complex scenes (drivers, constraints, simulation) to verify no corruption.

3. **Subframe accuracy:** Blender's depsgraph interpolation uses the scene's frame rate and interpolation mode (e.g., Bezier for F-curves). If the user has discontinuous keyframes (stepped interpolation), the transform might not interpolate smoothly. This is expected behavior (Cycles has the same limitation).

---

## Provenance

Filed 2026-05-24 as pkg103 Phase 2 follow-up. Gap surfaced by pkg103 Phase 1 audit. Renderer-side implementation complete in pkg88-A PR #284 (2026-05-15). Camera motion blur is the second-highest-priority wiring gap after Light Tree (pkg103a).
