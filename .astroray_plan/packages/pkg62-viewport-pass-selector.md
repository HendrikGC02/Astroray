# pkg62 — Viewport Pass Selector + Live OIDN Preview

**Pillar:** 5
**Track:** B
**Status:** open
**Estimated effort:** 1 session (~4 h)
**Depends on:** pkg06 (pass registry, done), pkg33 (OIDN, done)

---

## Goal

**Before:** Final renders export Cycles-style passes to the compositor (Albedo, Normal, Depth, Mist, Diffuse Direct, Glossy Indirect, …) but the viewport always shows Combined. Debugging a material by switching to Albedo or Normal in the viewport — Cycles' standard workflow — is impossible. OIDN runs only in final renders.

**After:** A "Render Pass" dropdown on the Astroray render properties panel selects which pass `view_draw` displays. Albedo, Normal, Depth, Diffuse, Glossy, and Combined are all live in the viewport. OIDN can optionally run on the viewport buffer (off by default for performance).

---

## Context

This addresses your "debugging is slow" complaint directly. Visual inspection of Albedo/Normal/Depth in the viewport is the single fastest way to triage material bugs, the kind that look weird but you cannot articulate from a Combined render alone. Cycles ships this; we should too.

---

## Reference

- Final-render pass export: [`update_render_passes`](blender_addon/__init__.py:238) and [`write_pixels`](blender_addon/__init__.py:1894).
- Viewport draw: [`view_draw`](blender_addon/__init__.py:433).
- Pass registry: [include/astroray/pass.h](include/astroray/pass.h).
- OIDN denoiser plugin: pkg33.

---

## Prerequisites

- [ ] pkg52 (persistent viewport session) recommended but not required — works without it, just at "one-shot" frequency.
- [ ] `Renderer::get_render_pass_buffer(name)` already returns the per-pass buffer (verified in `module/blender_module.cpp`).

---

## Specification

### Files to modify

| File | What changes |
|---|---|
| [blender_addon/__init__.py](blender_addon/__init__.py) | Add `viewport_display_pass: EnumProperty` with items `('combined', 'albedo', 'normal', 'depth', 'diffuse_direct', 'glossy_direct', ...)`. In `view_update`, register the matching pass plugin (`add_pass("albedo_aov")`, etc.). In `view_draw`, fetch the chosen pass buffer instead of the combined one (or in addition, if combined is also being requested). Add `viewport_oidn: BoolProperty(default=False)` that adds the OIDN pass when enabled. |
| `tests/test_blender_viewport_passes.py` (new) | Stubbed test asserting the dropdown sets the correct pass and the renderer is configured accordingly. |

### Key design decisions

1. **One pass at a time in viewport.** No multi-pass split-screen — that's a feature, not a bug fix. Keep it simple.
2. **Reuse the existing pass plugins.** Do not write new ones.
3. **OIDN viewport off by default.** Denoising every viewport sample adds latency. Make it a deliberate user opt-in.
4. **Normal pass shown in screen space.** Cycles convention; users expect blue-ish normals in the viewport.
5. **No compositor support.** Final-render pass export already works (pkg06). This is purely a viewport feature.

---

## Acceptance criteria

- [ ] A user can switch the viewport from Combined → Albedo → Normal → Depth and see each pass live, without leaving rendered shading mode.
- [ ] Toggling Viewport OIDN denoises the current pass on the fly.
- [ ] Final-render pass export is unchanged.
- [ ] Test passes.

---

## Non-goals

- Do not add cryptomatte to viewport (Combined is enough for selection feedback).
- Do not split the viewport into a multi-pass mosaic.
- Do not change how passes are computed.

---

## Progress

- [ ] Add `viewport_display_pass` and `viewport_oidn` properties + UI row.
- [ ] Wire `view_update` to register the chosen pass.
- [ ] Wire `view_draw` to fetch and display the chosen pass.
- [ ] Test.

---

## Lessons

*(Fill in after the package is done.)*
