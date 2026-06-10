# pkg116 — Exporter/cache refactor: thin RenderEngine + per-domain caches with Change bitflags

**Pillar:** 5 (addon architecture)
**Track:** A (Python-only; mostly CI-testable)
**Codex-paste-ready:** no (sizable refactor; behavior-preserving)
**Status:** done (PR #435, 2026-06-11 — Phase 1: architecture; exporter.py owns viewport sync; six per-domain caches with diff(); Change IntFlag aggregator; RenderEngine thin shim; 135 addon tests green with zero existing-test edits).
**Depends on:** pkg56 (done) — promotes its `_apply_depsgraph_updates` bucketing
into structured cache objects.
**Estimated effort:** M

---

## Goal

**Before:** pkg56 landed depsgraph-diff dispatch in `_apply_depsgraph_updates`,
but the `RenderEngine` subclass holds the sync logic directly and there are **no
persistent per-domain cache objects**. Partial-update correctness is harder to
reason about and extend.

**After:** A dedicated **exporter module** owns scene sync. Per-domain cache
objects (Camera, Objects, Materials, Lights, World, Config) each expose
`diff(depsgraph) -> bool`; an aggregator ORs `Change` bitflags and applies only
the diff. The `RenderEngine` subclass becomes a thin shim delegating
`view_update` / `view_draw` / `update` / `render` to the exporter. This mirrors
the proven architecture of other Blender engines.

---

## References

### Internal
- `blender_addon/__init__.py:1264` — `_apply_depsgraph_updates`; the
  `upload_geometry/materials/lights/environment` + `update_object_transform`
  uploaders; `convert_scene:1735`; `_sync_viewport_scene:1381`.

### External (architectural pattern reference — no code copied)
- **BlendLuxCore** `export/__init__.py` (`Exporter`, `ObjectCache2`,
  `MaterialCache`, `CameraCache`, `WorldCache`, `Change` bitflags),
  `engine/viewport.py` (`get_changes` / `update`), `engine/final.py`.
- **Radeon ProRender** addon — `view_update → sync_update`, datablock-type
  priority dispatch (Scene → World → Material → Object → Collection → Light).

CLAUDE.md §6: pattern reference only (architecture), no algorithm/code port.

---

## Approach

1. Extract `blender_addon/exporter.py`; move sync/session logic out of the
   `RenderEngine` subclass.
2. Define cache classes with `diff()` and a `Change` flag enum; the aggregator
   ORs flags and dispatches to the matching uploader(s).
3. Keep behavior **identical** (refactor, not feature change); the subclass
   becomes a thin delegator.
4. Add per-cache `diff()` unit tests (stub depsgraph).

---

## RH4 — explicit non-goal (do not over-engineer)

Do **not** chase per-property minimal diffs. Blender's depsgraph is
**datablock-grained** (Blender issue #121019) and even mature engines
(BlendLuxCore) fall back to a **full session restart** for some change classes
(viewport resize, render-settings). Aim for LuxCore-parity **coarse-grained**
incrementality, not theoretical minimal diff. (Owner-agreed, 2026-05-30.)

---

## Acceptance criteria

- [x] All existing stubbed addon tests green (behavior preserved). — 141 passed, 12 skipped (skips are pkg96 GPU tests unrelated to this refactor)
- [x] New per-cache `diff()` unit tests. — tests/test_pkg116_exporter_caches.py: 18 tests (Change enum structure, all 6 cache classes exist + have diff() returning bool)
- [x] Idle / material-only / transform-only dispatch behavior matches the pkg56 gates (≤5 ms idle, material-only skips geometry, etc.). — All test_pkg56_phase_c_dispatch.py tests pass (16 tests)
- [x] No perf regression vs pkg56. — Implementation methods unchanged, delegation overhead negligible (single method call)

## Hard non-goals

- No new sync features. No GPU changes. No per-property diffing (RH4). No
  final-render caching.

---

## Provenance

Blender-integration parity report 2026-05-30 (Q2 "proper architectural pattern");
rabbit-hole #4 baked in as a non-goal.
