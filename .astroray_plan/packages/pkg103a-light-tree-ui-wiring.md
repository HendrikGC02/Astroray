# pkg103a — Light Tree UI Wiring (Blender Addon)

**Pillar:** 5 (addon)
**Track:** A (single-feature wiring)
**Codex-paste-ready:** yes (well-scoped addon wiring task)
**Status:** open
**Depends on:** pkg86 (done), pkg86-B Phase 1 (done)
**Estimated effort:** ½ day (UI property + panel + call site + test)

---

## Goal

**Before:** pkg86 (CPU median-split Light Tree) and pkg86-B Phase 1 (CPU SAOH adaptive split) shipped 2× variance reduction on many-light scenes, but the Light Tree sampler cannot be enabled from the Blender UI. The pybind binding `set_light_sampler` (line 1966 in `module/blender_module.cpp`) has no call site in `blender_addon/__init__.py`.

**After:** A user can toggle `custom_raytracer.light_sampler` in the Blender UI (Render Properties > Sampling or a dedicated Light Tree panel) and select `"uniform"`, `"power"`, or `"light_tree"`. The addon calls `renderer.set_light_sampler(settings.light_sampler)` during scene conversion. Rendering a 64-area-light test scene with `light_sampler="light_tree"` triggers Light Tree traversal (confirmed via diagnostic printfs or variance-reduction measurement).

---

## Context

pkg103 Phase 1 (blender-addon-wiring-audit-2026-05-24.md) identified `set_light_sampler` as the highest-priority missing addon wiring. The renderer-side logic is complete (pkg86 PR #340 + pkg86-B PR #362); only the UI → renderer plumbing is missing.

Cycles exposes this as `RENDER_PT_sampling_light_tree` (currently on Astroray's hide-list at `blender_addon/__init__.py:4576`). We can either unhide that panel or add a simpler Astroray-native toggle in the existing `ASTRORAY_PT_sampling` panel.

---

## Specification

### 1. UI Property

Add to `CustomRayTracerSettings` (around line 200):

```python
light_sampler: EnumProperty(
    name="Light Sampler",
    description="Strategy for sampling lights in Next Event Estimation",
    items=[
        ('uniform', "Uniform", "Sample all lights equally (slowest, lowest variance on few lights)"),
        ('power', "Power", "Sample by total emitted power (default, good for moderate light counts)"),
        ('light_tree', "Light Tree", "Importance sample via hierarchical tree (best for many lights, pkg86/86-B)"),
    ],
    default='power',
)
```

### 2. Call Site

In `convert_scene` (around line 1380, alongside `set_adaptive_sampling`, `set_clamp_direct`, etc.):

```python
renderer.set_light_sampler(settings.light_sampler)
```

### 3. UI Panel

**Option A** (simpler): Add to existing `ASTRORAY_PT_sampling` panel (around line 4630):

```python
layout.prop(settings, "light_sampler")
```

**Option B** (Cycles-parity): Unhide `RENDER_PT_sampling_light_tree` by removing it from the `_PANELS_TO_HIDE` list (line 4576). This exposes Cycles' native Light Tree controls (threshold, splitting strategy, etc.), but most of those parameters are not yet wired to Astroray. Defer Option B unless the owner explicitly requests Cycles UI parity.

**Recommendation:** Ship Option A (simple dropdown in the existing Sampling panel). Option B can be a future refinement if users request per-tree tuning controls.

### 4. Test

Add to `tests/test_blender_addon.py`:

```python
def test_light_sampler_wiring():
    """Verify light_sampler UI property reaches renderer.set_light_sampler."""
    settings = create_mock_settings()
    settings.light_sampler = 'light_tree'
    renderer = create_mock_renderer()
    convert_scene_fragment_sampling(settings, renderer)  # helper extracted from convert_scene
    assert renderer.set_light_sampler.called_with('light_tree')
```

Or, if we add a full Blender render test:

```python
def test_light_tree_64_area_lights():
    """64 area lights, light_tree sampler enabled, confirm variance reduction vs power sampler."""
    scene = create_test_scene_many_lights(num_lights=64)
    scene.custom_raytracer.light_sampler = 'light_tree'
    result = render_scene(scene, spp=16)
    # Check that variance is lower than power-sampler baseline (from pkg86 acceptance test)
    assert result.variance < BASELINE_VARIANCE_POWER_SAMPLER * 0.6  # 2× reduction ≈ 0.5, allow margin
```

---

## Reference

### Internal
- `module/blender_module.cpp:1966` — `set_light_sampler` pybind.
- `include/raytracer.h:1196+` — `LightList::sample` + Light Tree traversal logic (pkg86).
- `.astroray_plan/docs/blender-addon-wiring-audit-2026-05-24.md` (pkg103 Phase 1) — audit that surfaced this gap.
- `blender_addon/__init__.py:4576` — `RENDER_PT_sampling_light_tree` on hide-list.

### External
- Cycles `intern/cycles/blender/sync.cpp` (Apache-2.0) — search for `set_use_light_tree` to see how Cycles wires the toggle.
- Cycles `intern/cycles/scene/light_tree.h` — reference for Light Tree parameters that Cycles exposes (splitting threshold, max depth, etc.). Phase 1 of this package does NOT wire those (we use hardcoded defaults from pkg86); future refinement can expose them if users request tuning knobs.

---

## Acceptance Criteria

- [ ] UI property `custom_raytracer.light_sampler` added with 3 modes (uniform, power, light_tree).
- [ ] `renderer.set_light_sampler(settings.light_sampler)` called in `convert_scene`.
- [ ] UI panel row added to `ASTRORAY_PT_sampling` (Option A) or `RENDER_PT_sampling_light_tree` unhidden (Option B).
- [ ] Test confirms the property reaches the renderer (mock test or full render test with variance measurement).
- [ ] Render a 64-area-light scene with `light_sampler="light_tree"` and confirm via `-DASTRORAY_DIAG_LIGHT_SAMPLING` (if available) or variance reduction measurement that the Light Tree is traversed.

---

## Hard Non-Goals

- **No Cycles Light Tree parameter exposure** (split threshold, max tree depth, etc.) in Phase 1 — we use pkg86 hardcoded defaults. Future refinement if users request tuning.
- **No GPU-specific Light Tree toggle** — pkg86-B Phase 1 (CPU SAOH) is done; GPU port (pkg86-B Phase 2) will automatically use the same `light_sampler` property.
- **No removal of `RENDER_PT_sampling_light_tree` from hide-list unless we actually wire Cycles' parameters** (avoids dead UI toggles).

---

## Provenance

Filed 2026-05-24 as pkg103 Phase 2 follow-up. Gap surfaced by pkg103 Phase 1 audit (highest-priority missing wiring). Renderer-side implementation complete in pkg86 PR #340 (2026-05-22).
