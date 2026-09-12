# pkg267 research — NanoVDB grid access + majorant grid + DDA (cite-algorithm)

Batch F, 2026-09-13. Required by CLAUDE.md §6 before writing the non-trivial
grid-build and DDA-traversal code.

## 1. NanoVDB sparse grid (representation + host build)

- **Paper:** Ken Museth, *NanoVDB: A GPU-Friendly and Portable VDB Data Structure
  for Real-Time Rendering and Simulation*, SIGGRAPH 2021 Talks.
- **Reference impl / licence:** `nanovdb/NanoVDB.h` and the header-only builder
  `nanovdb/tools/GridBuilder.h` + `nanovdb/tools/CreateNanoGrid.h` from
  AcademySoftwareFoundation/openvdb **v12.0.0**, Apache-2.0 (verified SPDX header
  on every file). Vendored at `external/nanovdb/` — see that dir's README and
  THIRD_PARTY.md.
- **Host build path (no OpenVDB):** `nanovdb::tools::build::Grid<float>` gives a
  mutable VDB tree with `getAccessor().setValue(Coord(i,j,k), v)`. After filling
  active voxels, `nanovdb::tools::createNanoGrid(buildGrid)` returns a
  `nanovdb::GridHandle<HostBuffer>` holding a read-optimised NanoGrid. The
  OpenVDB-file path in `CreateNanoGrid.h` is `#if defined(NANOVDB_USE_OPENVDB)`;
  we never define it, so no OpenVDB/Boost/TBB.
- **Point query:** `handle.grid<float>()->getAccessor().getValue(Coord(i,j,k))`
  returns the voxel value (0 = background). We keep the NanoGrid in pure **index
  space** (identity map) and do all world<->index transforms ourselves in
  `GridMedium`, which keeps the majorant grid and the device grid (pkg269) in the
  same space.
- **Opacity discipline:** NanoVDB.h is huge and must not leak into the widely
  included `raytracer.h`. `grid_medium.h` exposes only opaque handles (PIMPL);
  NanoVDB.h is included by the single TU `src/volume/grid_medium.cpp`.

## 2. Grid transfer contract (addon -> engine)

Per the Batch F brief owner decision (Blender native OpenVDB import). The addon
reads the resolved `.vdb` with Blender's bundled `openvdb` module and hands the
engine, per grid:

- a **dense float array** over the grid's ACTIVE-voxel bounding box, C-order
  `[nz][ny][nx]` (x fastest),
- the **bbox min** index `ijk` (int3) of that dense block,
- the **index->object** affine (from `openvdb` `grid.transform`: voxel size +
  origin; we accept a full 3x4/4x4 linear map),
- the **object->world** 4x4 (Blender `object.matrix_world`).

v1 is *dense over the active bbox* (memory ceiling: `nx*ny*nz*4` bytes for
density; a 512^3 dense block is 512 MB — acceptable for the CPU oracle, noted in
a code comment; sparse upload is a pkg269/pkg272 concern). The engine skips
background (0) voxels when filling the NanoVDB build grid, so the NanoGrid itself
stays sparse.

`density` is built into a NanoVDB grid; `temperature` / `color` / `velocity` are
carried as **passthrough** dense arrays + metadata only (consumed by pkg270),
matching the spec "do not evaluate emission here".

## 3. Majorant grid + DDA iterator

- **Source:** pbrt-v4 §11.4.2 "DDA Majorant Iterator"; reference impl
  `src/pbrt/media.h` `struct MajorantGrid` + `class DDAMajorantIterator`
  (Apache-2.0). Clean-room re-implementation in
  `include/astroray/volume/majorant_grid.h`, cited in comments.
- **Construction:** a coarse grid of `res.x*res.y*res.z` supervoxels over the
  index-space AABB `[bboxMin, bboxMin+dims]`. Supervoxel value = **max density**
  of the fine voxels it covers (a true upper bound). Supervoxel size heuristic:
  pbrt uses res ~ grid dim capped (default ~ min(dim, 128) with a target voxels-
  per-supervoxel). We start with a fixed supervoxel edge (`kSupervoxel = 16` fine
  voxels), res = ceil(dim/16) clamped to >=1, <=128 — documented as tunable.
- **σ_t majorant:** pkg267 stores **max density** per supervoxel. σ_t(λ) =
  density · extinctionCoeff(λ) with extinctionCoeff ≥ 0 constant per medium
  (from Principled Volume, pkg268). Hence `maxDensity · coeff(λ)` is a true upper
  bound for σ_t over the supervoxel — the majorant stays density-only here and
  pkg268 multiplies by the per-λ coefficient. The numpy gate uses coeff = 1.
- **DDA (`DDAMajorantIterator`):** ported structure — `deltaT`, `nextCrossingT`,
  `step`, `voxelLimit`, the `cmpToAxis[8]` branch-free axis selection, and
  `Next()` returning a `{tMin, tVoxelExit, majorantDensity}` segment. Ray is in
  index space; bounds offset normalises to [0,1]^3 across the grid before
  stepping (pbrt `grid->bounds.Offset`).

## 4. Algorithms deferred to pkg268 (separate notes)

Delta/Woodcock tracking (Woodcock 1965), residual ratio tracking (Novák 2014),
equiangular sampling (Kulla & Fajardo 2012), HG phase (Henyey–Greenstein 1941)
— see `pkg268-volume-transport-research.md`.
</content>
