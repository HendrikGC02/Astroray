# pkg260 — Coverage-matrix scanner extension (object, image-property, input-node rows)

**Pillar:** 5
**Track:** B
**Status:** open — filed 2026-09-08 per owner decision (pkg259 §7 Q1/Q6/Q7/Q4); pkg259 Phase 1 proceeds in parallel
**Estimated effort:** 2 sessions (~6 h)
**Depends on:** pkg229, pkg259

---

## Goal

Before: `scripts/generate_blender_parity_matrix.py` enumerates only shader-node
sockets, lights, camera, render settings and world rows (527 rows), so the
Cycles features the pkg259 corpus must exercise for geometry (instancing,
modifiers applied, motion blur, smooth/flat/auto-smooth, hair/curves objects),
Image Texture sub-properties (colour space, alpha mode, interpolation,
extension, projection, UDIM tiles) and shader input nodes with zero rows
(Geometry, Object Info, Attribute / Color Attribute, Hair Info, Light Path)
have no row to be classified SUPPORTED / APPROXIMATED / DROPPED-SILENT, and
13 rows are double-counted (Map Range float/vector variants and similar).
After: the matrix carries an `object`, an `image_property` and an `input_node`
category with the same AST-evidence classification as shader sockets, the
duplicate rows are collapsed by a stable row key, and `coverage_report.py`
(pkg259) can prove corpus coverage for every family, `geometry_zoo` included.
Light linking / shadow linking is declared out of scope (no per-object light
collections are planned for Astroray).

---

## Context

Owner decision 2026-09-08 morning (pkg259 design doc §7 questions 1, 4, 6, 7):
file the scanner extension now and let pkg259 Phase 1 (`materials_hall`,
`textures_mapping`) proceed against the matrix as it stands; later families
(`geometry_zoo`, `camera_lens`, `render_settings`) must be provable, not
visual-only. Gate (b) is frequency-weighted over the corpus, so every feature
the corpus exercises needs a row. Serves Pillar 5.

---

## Evidence

- 2026-09-07: `docs/blender_parity/coverage_matrix.json` 527 rows, categories
  `shader_node`, `light`, `camera`, `render_settings`, `world` only
  (`reference-corpus-design-2026-09.md` §1.5, §2).
- 2026-09-08: 13 duplicate (category, feature, socket) rows counted by
  `.astroray_plan/docs/pkg259-phase0/build_allocation_table.py`.
- 2026-09-08: Astra brainstorm (`pkg259-phase0/astra_response.md`) listed
  `TEX_IMAGE` sub-properties, input nodes and nested node groups as unscanned.

---

## Reference

- `scripts/generate_blender_parity_matrix.py` (pkg119 Phase A, pkg229 re-audit,
  pkg257 hand-verified evidence hook `_apply_displacement_evidence`).
- `.astroray_plan/docs/blender-coverage-reaudit-2026-09.md` (reproduce block).
- `.astroray_plan/docs/reference-corpus-design-2026-09.md` §1.5, §2, §7.
- Addon export entry points to scan: `blender_addon/__init__.py`
  `convert_objects` (instancing, modifiers via the evaluated depsgraph, motion
  blur pkg88-B, smooth shading), `load_blender_image` /
  `_load_blender_image_resolved` (image properties), the input-node handlers
  in `convert_shader_node`.

---

## Prerequisites

- [x] pkg229 done — matrix regenerable headlessly.
- [ ] pkg259 Phase 0 design merged (#743) — allocation table names the rows.
- [ ] Build passes on main.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg260_scanner_categories.py` | The new categories appear with the documented row keys; no duplicate (category, feature, socket_or_prop) rows; the hand-verified evidence hooks still apply; the total row count is recorded and changes only with a documented delta. |

### Files to modify

| File | What changes |
|---|---|
| `scripts/generate_blender_parity_matrix.py` | Add enumerators for `object` (Object/Mesh RNA: instancing modes, modifier presence via evaluated depsgraph, `use_motion_blur`, smooth/auto-smooth, Curves objects), `image_property` (`Image.colorspace_settings.name`, `alpha_mode`, `ShaderNodeTexImage.interpolation/extension/projection`, UDIM `source='TILED'`) and `input_node` (Geometry, Object Info, Attribute, Color Attribute, Hair Info, Light Path outputs); classify them with the same AST evidence scan of the addon; collapse duplicates by a stable row key. |
| `docs/blender_parity/coverage_matrix.json` | Regenerated headlessly with the new categories. |
| `docs/blender_parity/report.md` | Regenerated alongside the matrix. |
| `.astroray_plan/docs/reference-corpus-design-2026-09.md` | §2 allocation table regenerated with the new rows (`pkg259-phase0/build_allocation_table.py`). |

### Key design decisions

- **Same evidence model, new categories.** Rows are credited only by AST
  evidence in the addon (or a hand-verified hook with a comment), never by a
  hand-maintained "supported" table — the pkg253/pkg255 lessons apply.
- **Light linking / shadow linking out of scope** (owner 2026-09-08): record as
  a single `world`-category gap card, not per-object rows.
- **Duplicate collapse by key, not by name**: the Map Range float/vector
  variants become distinct sockets with a variant suffix, so no information is
  lost.

---

## Acceptance criteria

- [ ] Matrix regenerated with `object`, `image_property`, `input_node`
      categories; row count and per-category counts recorded in the PR body;
      zero duplicate row keys.
- [ ] `tests/test_pkg260_scanner_categories.py` green in CI (no Blender —
      runs on the committed JSON) and the headless regeneration reproduces it.
- [ ] pkg259 allocation table regenerated; `geometry_zoo` and `camera_lens`
      families have rows for every feature the design doc §1.5/§1.6 lists.
- [ ] Existing SUPPORTED/APPROXIMATED classifications unchanged (diff shows
      only added rows and the duplicate collapse).

---

## Non-goals

- No engine or addon behaviour change; classification only.
- No light linking / shadow linking rows (owner decision).
- No frequency weighting here — `coverage_report.py` (pkg259 Phase 4) owns
  the weight rule (distinct scenes per socket, capped at 3).

---

## Progress

- [ ] 2026-09-08 — filed per owner decision; not started.

---

## Lessons

- (none yet)
