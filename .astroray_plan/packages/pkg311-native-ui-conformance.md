# pkg311 — Blender-native UI conformance, Phase 1: categorised nodes, node status badges, astro sub-panels + presets, tooltip lint

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 2 sessions (~6 h), addon Python only
**Depends on:** pkg176, pkg195

---

## Goal

Before:
- Astroray-specific features sit in one flat 8-item "Astroray" Add submenu.
- A 35-property Black Hole object panel has no units or presets.
- Native nodes render grey behind a Mix Shader or when unwired, with no
  on-node hint.
- Tooltips are uneven, and Cycles controls the engine ignores look live.

After:
- Every Astroray feature lives on a native Blender surface that follows
  Cycles' conventions.
- The Add menu has categories (Spectral Sources, Spectral Modifiers,
  Response, Hints).
- Each native node shows a status line when it will not affect the render.
- The Black Hole panel is split into sub-panels with units and a preset menu
  (Sgr A*, M87*, stellar-mass HMXB).
- Render/quality presets exist through Blender's preset-menu mechanism.
- A test asserts that every Astroray RNA property has a description.
- A short conventions note fixes the rules for all future UI work.

---

## Context

Owner 2026-09-29: "Astroray-specific features need dedicated interfaces that
are intuitive to use and fit in with the rest of Blender's interface." The
north star forbids a parallel ground-up UI (pkg176), so "dedicated" means
native surfaces: Properties contexts, Add-menu categories, presets, the asset
browser and node badges. This package is Phase 1 of theme 2
(`product-themes-plan-2026-09-29.md` §2). The View Layer passes panel
(Phase 2) waits for pkg313's AOVs. The spectral library picker (Phase 3)
waits for pkg312. Sonnet 5.5 (or Flash) lane, Terra review. Addon only; no
engine build.

---

## Evidence

- 2026-09-29: `blender_addon/nodes/__init__.py` ~684–700 appends one flat submenu from `_ASTRORAY_NODE_TYPES` (8 entries) to `NODE_MT_add`.
- 2026-09-29: `blender_addon/__init__.py` ~7564 `OBJECT_PT_astroray_black_hole`: one panel, about 35 properties, no sub-panels or presets.
- 2026-09-29: `_convert_astroray_native_surface` (~2720) resolves native nodes only when wired directly as Surface; grey fallback elsewhere.

---

## Reference

- Plan: `.astroray_plan/docs/product-themes-plan-2026-09-29.md` §2.
- Blender conventions (GPL, pattern only, no code copied): Cycles `intern/cycles/blender/addon/ui.py` (panel hierarchy, `bl_parent_id`, `CYCLES_PT_*` naming); `scripts/startup/bl_ui/properties_*.py`; `bpy.types.Menu` + `PresetBase` (`scripts/startup/bl_operators/presets.py`) for preset menus.
- Existing: pkg176 Stage 0 mapping `docs/blender_parity/pkg176_stage0_mapping.md` (which Cycles controls are honoured), pkg195 nodes, memory `astroray-native-nodes-need-astroray-output`, `addon-packaging-file-list` (new `.py` files go in `ADDON_FILES`), `addon-init-mixed-line-endings`.

---

## Prerequisites

- [ ] AN-2 (#866) and AN-3 (#867) merged, since they touch the same panels in `__init__.py`.
- [ ] Blender 5.2 headless available for the UI tests and screenshots.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `.astroray_plan/docs/ui-conventions.md` | One page: native surfaces only; panel naming/parenting; units in labels; tooltips mandatory; presets through `PresetBase`; how to mark un-honoured controls |
| `blender_addon/presets/astroray_black_hole/` | Preset `.py` files: Sgr A*, M87*, stellar-mass HMXB (values cited in each file) |
| `tests/test_pkg311_ui_conformance.py` | Headless Blender: every Astroray RNA property has a non-empty description; Add-menu categories resolve; sub-panels register; preset round-trip; node status line appears on an unwired native node |

### Files to modify

| File | What changes |
|---|---|
| `blender_addon/nodes/__init__.py` | Categorised Add submenus; a `draw_buttons` status line (icon ERROR/INFO) when a native node is not reachable by the converter |
| `blender_addon/__init__.py` | Black Hole panel split into sub-panels (Mass & Spin, Disk, ADAF/Jet, Observer) with units; preset menu; missing tooltips; un-honoured adopted Cycles controls greyed or labelled |
| `scripts/build/build_blender_addon.py` | Add the presets directory to the packaged files (`ADDON_FILES`) |

### Key design decisions

- **Native only.** No N-panel sidebar, no custom workspace, and no duplicate
  of a Cycles control. Where a Cycles control is adopted but not honoured,
  label it; do not re-implement it.
- **Status-line reachability.** The status line uses the converter's own
  reachability (the same function `_convert_astroray_native_surface` uses),
  so the UI and the render cannot disagree. Do not add a second graph walker.
- **Preset values are cited.** Mass, spin and distance come from EHT 2019/2022
  for M87*/Sgr A* and a named HMXB (for example Cyg X-1, Miller-Jones et al.
  2021), with a DOI comment in each preset file.
- **No behaviour change.** Renders must be bit-identical before and after.
  The package is UI only.

---

## Acceptance criteria

- [ ] `tests/test_pkg311_ui_conformance.py` green in Blender 5.2 headless; the property-description check covers every `PropertyGroup` the addon registers.
- [ ] Byte-identical CPU renders of two corpus scenes before and after (UI-only proof).
- [ ] Screenshots of the Add menu, the Black Hole sub-panels and a node status line under `test_results/pkg311/`, inspected by Opus or Astra.
- [ ] Packaged ZIP contains the presets; clean-profile install shows them.
- [ ] `python scripts/project_index.py lint` clean.

---

## Non-goals

- Do not build the View Layer passes panel (Phase 2, after pkg313).
- Do not build the spectral library picker or the asset catalogues (Phase 3, after pkg312).
- Do not add Add > Astroray object menus for nebulae or disks (science-later).
- Do not change exporter semantics or engine code.

---

## Progress

- [ ] Conventions note
- [ ] Add-menu categories + node status line
- [ ] Black Hole sub-panels + presets
- [ ] Tooltip lint + un-honoured labels
- [ ] Tests, screenshots, packaging

---

## Lessons

*(Fill in after the package is done.)*
