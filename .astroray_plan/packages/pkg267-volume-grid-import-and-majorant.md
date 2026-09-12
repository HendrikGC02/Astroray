# pkg267 — Heterogeneous volume grid representation + Blender/VDB import + majorant grid

**Pillar:** 2
**Track:** A
**Status:** open
**Estimated effort:** 3 sessions (~9 h)
**Depends on:** none

---

## Goal

Before: Astroray has only a homogeneous *world* volume (global fog) and a dead
RTOW `ConstantMedium`; there is no grid, no VDB, no `bpy.types.Volume` import
anywhere in the tree. After: the engine has a `GridMedium` representation backed
by a vendored NanoVDB (Apache-2.0) sparse grid holding density (and, as passthrough
handles, temperature/color) in an object-space bounding box with a world
transform; it builds a coarse **majorant grid** (per-supervoxel max σ_t) for
delta tracking; and the Blender addon exports a `bpy.types.Volume` object plus its
`.vdb` grids into that representation. No transport yet — this package is
representation + import + point/majorant queries only.

---

## Context

This is the foundation of the volumes track (owner directive 2026-09-11, §7 item
5: volume rendering is core Cycles parity, not Pillar 4). Both the CPU transport
(pkg268) and the GPU stage (pkg269) need one shared grid representation, the
majorant grid for tracking, and a decided import path — so this must land first.
It carries no volume dependency and its Blender-import half is CPU-only, so it can
start immediately and run alongside a GPU-locked lane. Without it there is nothing
for delta/ratio tracking to sample. Research: `docs/volumes-track-research-2026-09-12.md`.

---

## Reference

- Design doc: `.astroray_plan/docs/volumes-track-research-2026-09-12.md` §1, §2, §3, §5
- External: Museth 2021 "NanoVDB" (grid); Museth 2013 "VDB" (topology);
  pbrt-v4 `media.h` `MajorantGrid`/`DDAMajorantIterator` (Apache-2.0);
  Cycles `blender/volume.cpp`, `scene/volume.cpp` (grid attribute mapping, Apache-2.0);
  Blender `bpy.types.Volume.grids` Python API.
- Precedent for vendoring Apache Cycles/third-party code: `external/cycles_light_tree/`.

---

## Prerequisites

- [ ] Build passes on main (CPU + `--backend cuda`).
- [ ] `cite-algorithm` run for the majorant-grid construction and the NanoVDB
      grid access before writing code; notes saved under `.astroray_plan/docs/`.
- [ ] Owner open-question 1 (import path) resolved, or default to the
      Blender-API-first path with an engine `.nvdb` reader deferred.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `external/nanovdb/NanoVDB.h` | Vendored NanoVDB single header (Apache-2.0), unmodified, with its licence header intact |
| `include/astroray/volume/grid_medium.h` | `GridMedium`: NanoVDB grid handle + object→world transform + AABB; `sigmaT(p)` / `density(p)` point query; owns the majorant grid |
| `include/astroray/volume/majorant_grid.h` | Coarse `MajorantGrid` (per-supervoxel max σ_t) + a DDA iterator over ray segments (pbrt-v4 structure, clean-room + cited) |
| `src/volume/grid_medium.cpp` | Build `GridMedium` from a NanoVDB grid buffer; construct the majorant grid |
| `blender_addon/volume_export.py` | Read `bpy.types.Volume` + its `.vdb` grids and hand density/temperature/color grids to the engine as a NanoVDB buffer |
| `tests/test_pkg267_grid_import.py` | Grid dims/bbox/world-transform, majorant ≥ max σ_t per supervoxel (numpy), synthetic + real `.vdb` |
| `tests/test_pkg267_blender_volume_export.py` | Blender headless: a Volume object exports to an engine grid handle with correct bounds |

### Files to modify

| File | What changes |
|---|---|
| `module/blender_module.cpp` | Bind a `set_volume_grid(...)` / grid-handle constructor exposing `GridMedium` to Python; expose majorant + point queries for tests |
| `CMakeLists.txt` | Add `external/nanovdb` to the include path; compile `src/volume/grid_medium.cpp` into both targets |
| `blender_addon/exporter.py` | Call `volume_export.py` for `bpy.types.Volume` objects in the scene export |

### Key design decisions

- **Representation:** vendor `NanoVDB.h` (Apache-2.0, verified 2026-09-12) as the
  single shared CPU/GPU grid. Do NOT link full OpenVDB (MPL-2.0 + Boost/TBB/Blosc
  build weight); see research note §3.
- **Import path (owner Q1):** default to Blender's Python API
  (`bpy.types.Volume.grids`) reading grids in the addon and building a NanoVDB
  buffer for the engine — matches "Blender is the steering wheel" and needs no
  engine file dependency. An engine-side standalone `.nvdb` reader is out of scope
  here (defer to pkg272-scope if standalone CLI ever matters).
- **Majorant grid:** follow pbrt-v4 §11.4.2 `MajorantGrid` + `DDAMajorantIterator`
  structure (clean-room, cite in comments). Supervoxel resolution is a tunable;
  start with the pbrt default heuristic. The majorant must be a true upper bound
  (≥ max σ_t) — the numpy gate enforces this.
- **No transport here.** `GridMedium` exposes `sigmaT(p)`, `density(p)`, the AABB,
  the world transform, and the majorant iterator; nothing samples a free flight
  yet. Determinism: no `random_device` (contrast the legacy `ConstantMedium`).
- Grid attribute names follow Cycles: `density`, `temperature`, `color`,
  `velocity` (velocity is stored as a passthrough handle only, consumed later).

---

## Acceptance criteria

- [ ] `external/nanovdb/NanoVDB.h` is present with its Apache-2.0 header intact and
      both targets compile against it.
- [ ] `tests/test_pkg267_grid_import.py` passes: a synthetic grid and a real
      `.vdb` load with correct dims, world AABB, and transform; the majorant grid
      is ≥ the true max σ_t in every supervoxel (numpy cross-check).
- [ ] `tests/test_pkg267_blender_volume_export.py` passes headless: a
      `bpy.types.Volume` object exports to an engine grid handle with matching
      bounds.
- [ ] Adding the grid path changes no existing render output: full CPU + GPU
      suites stay green (grid-free scenes untouched).

---

## Non-goals

- Do not implement any volume transport (free-flight, in-scatter, transmittance) —
  that is pkg268.
- Do not touch the GPU device grid upload — that is pkg269.
- Do not link full OpenVDB or add a Boost/TBB dependency.
- Do not add temperature/color *evaluation* (emission) — only carry the grids as
  handles for pkg270.
- Do not remove the legacy `ConstantMedium` (superseded later; leave until pkg268
  provides the replacement).

---

## Progress

- [ ] Run cite-algorithm for majorant construction + NanoVDB access.
- [ ] Vendor `NanoVDB.h`; wire the include path in both targets.
- [ ] Implement `GridMedium` + `MajorantGrid` + point/majorant queries.
- [ ] Implement the Blender `bpy.types.Volume` export path.
- [ ] Write and pass both test files; run full CPU + GPU suites.

---

## Lessons

*(Fill in after the package is done.)*
</content>
