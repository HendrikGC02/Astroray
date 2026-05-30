# pkg112 — Batched geometry upload (NumPy arrays) to cut per-triangle pybind11 overhead

**Pillar:** 5 (addon) + core bindings
**Track:** A
**Codex-paste-ready:** no (C++ binding + addon change + clean rebuild + RTX verify)
**Status:** open — proposed 2026-05-30. **GPU-gated: pixel-parity must be RTX-`/verify`-ed; CI has no GPU and CI-green ≠ correct.**
**Depends on:** none (independent of pkg114; complementary). Plays well with pkg117.
**Estimated effort:** M (~1 week incl. one RTX session)

---

## Goal

**Before:** `convert_objects` (`blender_addon/__init__.py:3355`) walks every
loop-triangle in Python and calls `renderer.add_triangle(...)` once per triangle
(binding `module/blender_module.cpp:1957`, impl `PyRenderer::addTriangle`
`blender_module.cpp:601`). On a 100k-triangle scene this is ~150–400 ms of pure
pybind11 marshalling per geometry sync — the dominant viewport/F12 upload cost
per the Phase-A benchmark in `.astroray_plan/docs/blender-depsgraph-sync-research.md`.

**After:** A single bulk binding ingests contiguous NumPy arrays (vertices,
triangle indices, per-loop UVs, normals, per-triangle material ids) and uploads
them in one call. `convert_objects` fills these arrays with Blender's C-speed
`foreach_get` and calls the bulk API once per mesh. Target **≥5× reduction** in
geometry-upload wall-clock on the 100k-tri benchmark, with pixel-identical output.

---

## References

### Internal
- `module/blender_module.cpp:1957-1960` — `add_triangle` binding; `:1961` —
  `add_triangle_layers` (multi-UV variant); `:1965` — `add_mesh` (existing bulk
  `.obj` ingest, proves the C++ side can build geometry without per-tri Python
  round-trips). `PyRenderer::addTriangle` `:601-627`.
- `blender_addon/__init__.py:3498-3564` — the hot per-triangle loop.
- `blender_addon/__init__.py:3785+` — pixel writeback already uses
  `foreach_set` over a NumPy buffer: the proven NumPy↔Blender bridge pattern to
  mirror on the input side.

### External
- Blender `bpy.types.Mesh` `vertices.foreach_get` / `loop_triangles.foreach_get`
  (docs.blender.org) — the standard C-speed bulk extract used by Cycles' own
  exporter (`intern/cycles/blender/mesh.cpp`, Apache-2.0).
- pybind11 `py::array_t` / buffer protocol for zero-copy array ingestion
  (pybind11 docs).

CLAUDE.md §6: N/A — this is an engineering/marshalling optimization, no novel
numerical algorithm.

---

## Approach

1. **C++ binding.** Add `add_triangles_bulk(verts, tri_indices, material_ids,
   uvs=…, normals=…, object_pass_index=0, material_pass_index=0)` taking
   `py::array_t` arguments; validate shapes; loop entirely in C++ (no per-tri
   Python boundary). Keep `add_triangle` for fallback/standalone use.
2. **Addon.** In `convert_objects`, replace the per-tri loop with `foreach_get`
   into preallocated NumPy arrays; remap Blender material slot indices → engine
   material ids; issue one bulk call per mesh. Preserve the caustic-caster flag
   and Cryptomatte object-name tagging via the existing
   `scene_object_count()` range trick (`:3569`).
3. **Multi-UV.** Mirror `add_triangle_layers` — pass a layered UV array plus the
   `uvLayerNames` list so named-UV scenes (test_blender_named_uv_layers) keep working.

---

## Acceptance criteria

- [ ] Bulk binding compiles via a **clean** rebuild (see memory
      *incremental-build-signature-staleness*); call-site sweep for
      `add_triangle` shows no broken callers.
- [ ] Geometry-upload time on the pkg56 Phase-A 100k-tri benchmark **≥5×**
      faster; before/after numbers recorded in the PR.
- [ ] **Pixel-identical** render vs the per-tri path on a textured, multi-UV,
      multi-material scene (RTX `/verify`, paired stills).
- [ ] Existing stubbed addon tests green; a new CPU/stub test asserts the bulk
      path emits the same triangle/material/UV set as the per-tri path on a
      small mesh.

## Hard non-goals

- Not a BVH change (pkg114). Not removing `add_triangle` (kept for fallback +
  standalone). Not touching the final-render-vs-viewport dispatch.

---

## Provenance

Blender-integration parity report 2026-05-30 (Q2 bottleneck #1), owner-prioritized
as the highest-value performance item. Rabbit-hole #5: `add_mesh` already
demonstrates a C++ ingest path, lowering the cost of this work.
