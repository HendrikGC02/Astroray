# pkg103 — Blender addon feature-wiring audit: expose shipped renderer features in the UI

**Pillar:** 5 (addon)
**Track:** A (UI-wiring audit; mixed surface across `blender_addon/__init__.py`)
**Codex-paste-ready:** partial — Phase 1 (audit) is mechanical; Phase 2 (wiring) requires per-feature UI design judgement and should ship as several small follow-up PRs.
**Status:** done (PR #370, 2026-05-24 — audit complete: 37 bindings audited, 6 MISSING identified, 2 high-priority follow-ups filed as pkg103a/pkg103b)
**Depends on:** none (but coordinates with pkg101, pkg102 in the same file)
**Estimated effort:** Phase 1 ≈ ½ day (audit table). Phase 2 ≈ 1 day per
feature wired.

---

## Goal

**Before:** Several renderer-side features have shipped (pkg44 ADAF,
pkg86/86-B Light Tree, pkg88 motion blur, pkg89 dedicated lights,
others) but their addon UI exposure is inconsistent — some are wired
end-to-end, some have pybind bindings but no UI property, some have a
UI property but the property never reaches the renderer. The owner
reports *"a lot of the new features and things and lights-related
features still need their blender addon wiring and exposure in the
UI."*

**After:** A concrete audit table maps every PyRenderer setter to
(a) whether a `custom_raytracer.<prop>` UI property exists,
(b) whether `convert_scene`/`setup_world`/`convert_lights` calls the
setter, and (c) whether a UI panel exposes the prop. Each gap becomes
either a documented intentional non-exposure or a small wiring PR.

---

## Confirmed gaps on HEAD 24b5701 (architect spot-check, non-exhaustive)

1. **Light Tree sampler** (`set_light_sampler`, pybind 1966).
   - **No call site in addon** (`grep set_light_sampler blender_addon/`
     returns nothing). pkg86 (CPU median-split) and pkg86-B Phase 1
     (CPU SAOH) are shipped; Cycles' `RENDER_PT_sampling_light_tree`
     panel is hidden from Astroray's UI register (line 4570 of the
     blacklist). User cannot turn on the light tree from the addon.

2. **Camera motion blur** (`set_camera_motion_blur`, pybind 1953).
   - **No call site in addon**. pkg88-A shipped the renderer-side
     keyframe interpolation but the addon never invokes
     `set_camera_motion_blur`, so Blender's `render.use_motion_blur`
     toggle has no effect on the camera. Geometric motion blur was
     explicit non-goal of pkg88-A.

3. **Spot/sun/area dedicated lights** (pkg89 Phase B, PR #317).
   - Wired (lines 3533, 3554, 3568). The `dedicated` toggle is
     UI-exposed; **leave as-is**, listed here only as the positive
     control showing the wiring pattern.

4. **ADAF / accretion model selector** (pkg43 + pkg44).
   - Wired via `add_black_hole(params=…)` (line 3314 area); UI panel at
     line 4437. **Leave as-is.**

5. **Cryptomatte** (pkg87a-d).
   - Wired via `set_cryptomatte_enabled` (line 939). **Leave as-is.**

The audit deliverable (Phase 1) is the **complete** version of the
above list, not these five spot-checks.

---

## Phase 1 — audit (this package's only required deliverable)

Produce a single markdown table in
`.astroray_plan/docs/blender-addon-wiring-audit-2026-05-24.md` with
columns:

| PyRenderer setter | pybind line | UI prop name | `convert_scene` call site | UI panel | Status |
|---|---|---|---|---|---|

Generation procedure:

1. `grep -nE '^\s*\.def\("(set_|enable_|add_|use_)' module/blender_module.cpp`
   → seed the rows.
2. For each row, grep `blender_addon/__init__.py` for the setter name.
3. Mark each row as `OK`, `gap:no-call`, `gap:no-prop`, `gap:no-panel`,
   or `intentionally-internal` (with one-line justification).

The audit must include every `enable_*` / `set_*` / `add_*` binding,
not only the obvious ones. The audit is a docs-only deliverable in
this package's PR.

## Phase 2 — wiring follow-ups (out of scope here; file as follow-up specs)

For each non-`intentionally-internal` gap surfaced in Phase 1, the
follow-up is its own small spec (template pkg99/pkg100 style): one
property, one panel row, one `convert_scene` call, one test. Do **not**
attempt to land all of Phase 2 inside this package.

The architect-recommended initial follow-up cuts (file as separate
specs after audit lands):

- **pkg103a** — Light Tree UI toggle + `set_light_sampler` call.
- **pkg103b** — Camera motion-blur addon wiring (decompose
  `camera.matrix_world` at shutter start/end, call
  `set_camera_motion_blur`).

Any further pkg103x specs are determined by the Phase 1 audit table.

---

## Reference

### Internal
- `module/blender_module.cpp` lines ~1880-2130 (PyRenderer setter
  bindings).
- `blender_addon/__init__.py` (the consumer).
- `.astroray_plan/packages/pkg89-dedicated-lights.md` (positive
  reference for end-to-end light wiring).
- `.astroray_plan/packages/pkg86-light-tree.md` and
  `pkg86-B-light-tree-gpu.md` (Light Tree renderer side).
- `.astroray_plan/packages/pkg88-motion-blur.md` (camera motion blur
  renderer side; pkg88-A was camera-only by design).

### External
- Cycles `intern/cycles/blender/sync.cpp` (Apache-2.0) — reference for
  walking a Blender scene and pushing each setting to the renderer.
  Cite when wiring individual follow-ups (Phase 2).

CLAUDE.md §6 N/A in Phase 1 (audit is mechanical). Phase 2 follow-ups
that touch sampling/physics (Light Tree mode plumbing, motion-blur
shutter-position mapping) must cite Cycles.

---

## Acceptance criteria (this package — Phase 1 only)

- [ ] Audit doc filed at
      `.astroray_plan/docs/blender-addon-wiring-audit-2026-05-24.md`
      covering every PyRenderer `set_*` / `enable_*` / `add_*`
      binding.
- [ ] Audit table marks ≥3 concrete `gap:*` rows (we already know of
      Light Tree, motion-blur, and the audit will surface more).
- [ ] PR body links the audit and lists which follow-up specs the
      architect should file next.
- [ ] CI green (docs-only PR).

## Hard non-goals

- **No Phase 2 wiring in this package** — surgical scope discipline
  (CLAUDE.md §3). Wiring follow-ups are separate small PRs.
- No refactor of the existing wiring for already-wired features.
- No removal of the `RENDER_PT_sampling_light_tree` panel from the
  hide-list until pkg103a actually wires the call site (avoids a
  dead-toggle UI).

---

## Provenance

Owner-reported 2026-05-24: *"A lot of the new features and things and
lights-related features still need their blender addon wiring and
exposure in the UI."* Architect spot-checked five renderer features
and confirmed at least two concrete gaps (Light Tree sampler, camera
motion blur); a full mechanical audit is the right next step before
filing per-feature wiring PRs.
