# pkg296 — Real engine volume support for mesh-bounded volumes: the medium follows the mesh, not its AABB (CPU then GPU; #833)

**Pillar:** 2
**Track:** A
**Status:** in-progress — Phases 0-1 (CPU + addon) done on lane/an-296 2026-09-29: icosphere IoU 0.998 vs Cycles (main 0.77), corpus ROI parity at volume_bounces 0/4; Phase 2 (GPU) open
**Estimated effort:** 3–4 sessions (~12 h): Phase 0 ~2 h, Phase 1 (CPU + addon) ~5 h, Phase 2 (GPU) ~5 h incl. one lead-run CUDA build cycle
**Depends on:** pkg268, pkg269, pkg271

---

## Goal

Before: a MESH object with a volume material is lowered by the addon to an
axis-aligned world AABB (`volume_export.mesh_world_aabb` →
`add_homogeneous_medium`), its triangles are dropped, and the engine sweeps
`BoundedMedium::aabbMin/aabbMax` on every segment (CPU
`spectralTrackSegment`, per-segment NEE, shadow transmittance; GPU
`stage_volume_hetero.cu`), so an icosphere renders as a cube and only a
DEGRADED line admits it. After: each bounded medium can carry a closed
triangle boundary; on both backends a point is inside the medium exactly
when Cycles' volume stack would say so (entered through a front face, left
through a back face), for homogeneous and grid media, overlapping and nested
media, and a camera that starts inside a volume. An icosphere volume matches
Cycles' silhouette and ROI means; media-free scenes are bit-identical.

---

## Context

Owner decision 2026-09-29: "we need real volume support", not the
DEGRADED report (architect plan AN-4, replaced by this spec). Mesh volumes
are the most common Blender volume construct (fog boxes, clouds, glass
with an interior medium); rendering them as boxes breaks every corpus
v2 media scene and the showcase volumes. #842 (every medium on a segment)
and #860 (0.75–0.81 of Cycles, closed in Batch U #893) left the AABB
lowering untouched. Physics- and register-sensitive on the GPU: an
Opus 5.5 lane, CPU first, then the GPU twin; Terra second-opinion review,
`cycles-parity-reviewer` and `cpp-abi-guard` per phase. The lead runs every
CUDA build; the lane never polls a build.

---

## Evidence

- 2026-09-19: owner — icosphere with Principled Volume renders as a cube (#833).
- 2026-09-29: `blender_addon/__init__.py` ~5550 lowers a volume MESH to `mesh_world_aabb` and returns `not has_surface` (volume-only triangles never reach the BVH); `tests/test_issue833_mesh_volume_bounds.py` asserts only the degradation report.
- 2026-09-29: AABB sweep sites: `volume_transport.h:406` (`spectralTrackSegment`), `:543` (shadow Tr), `raytracer.h:2885` (#925 per-segment NEE), `raytracer.h:4004`; GPU `stage_volume_hetero.cu` (`c_wfGridVolume` loops), `stage_advance.cu`, `gpu_volume_phase.cuh:148` (`intersectAABB` twin).
- 2026-09-27 (pkg269): shade kernel REG 254; adding lanes to by-value `GPUWavefrontState` grew all 128 shade STACKs by 40 B — per-path volume data must stay in `GWavefrontGridVolumeBinding`.

---

## Reference

- Cycles (Apache-2.0): `src/kernel/integrator/volume_stack.h` `volume_stack_enter_exit` (`SR_BACKFACING` ⇒ exit, else enter; dedupe on object+shader); `src/kernel/integrator/intersect_volume_stack.h` `integrator_volume_stack_init` (camera-inside: +Z probe ray, back-face-first hit ⇒ inside, ≤ 2·`volume_stack_size` hits); `src/kernel/integrator/shade_volume.h` (segment over all stack entries = our overlap composite).
- pbrt-v4 (Apache-2.0): `MediumInterface` on `GeometricPrimitive`, interface-only surfaces skipped by `SurfaceInteraction::SkipIntersection`, per-ray current medium — the alternative considered (single medium per ray, no overlap; rejected, see Key design decisions).
- Watertight ray–triangle test: Woop, Benthin, Wald 2013, JCGT 2(1) — boundary crossings must not leak at shared edges.
- Existing: `include/astroray/volume/volume_transport.h` (`BoundedMedium`, `spectralTrackSegment`, `spectralTrackOverlap`), pkg114 `GBLAS` layout (`gpu_types.h:388`), memory notes `wavefront-shade-kernels-register-saturated`, `shade-axis-side-table-avoids-spill`, `cycles-caustics-need-smooth-shading`.
- Record the enter/exit semantics and citations in a research note `.astroray_plan/docs/pkg296-mesh-volume-boundary-research.md` before code (`cite-algorithm`).

---

## Prerequisites

- [ ] pkg268, pkg269, pkg271 done (they are).
- [ ] pkg294 is not mid-flight in `stage_volume_hetero.cu` when Phase 2 starts (serialize; same conflict key).
- [ ] Blender 5.2 local headless Cycles available for the reference renders.
- [ ] Build passes on main; `.pyd` mtime ≥ HEAD before any render.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/volume/medium_boundary.h` | `MediumBoundary`: world-space triangle soup + own BVH; `nextCrossing(o, d, tMin, tMax) → {t, backFacing}` (watertight, closest hit); `insideAt` = first crossing back-facing |
| `src/gpu/gpu_medium_boundary.cuh` | Device twin: closest-hit over a boundary BLAS referenced from the side table |
| `tests/test_pkg296_mesh_volume_boundary.py` | CPU gates: AABB regression, silhouette IoU, Cycles ROI bands, overlap/nested/camera-inside/glass-shell, bit-identity |
| `tests/test_pkg296_gpu_mesh_volume_parity.py` | GPU vs CPU and vs Cycles on the same scenes; media-free GPU bit-identity |
| `.astroray_plan/docs/pkg296-mesh-volume-boundary-research.md` | Cited semantics, divergence notes (open meshes) |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/volume/volume_transport.h` | `BoundedMedium` gains `const MediumBoundary* boundary` (null ⇒ today's AABB path, byte-identical). One helper `mediumCoverage(m, o, d, cursor, tMax) → {covers, tEnd}` replaces the raw `intersectAABB` in `spectralTrackSegment` and the shadow-Tr loop |
| `include/raytracer.h` | `addHomogeneousMedium` / `addGridMedium` accept an optional boundary; #925 per-segment NEE (~2885) and ~4004 use `mediumCoverage` |
| `module/blender_module.cpp` | `add_homogeneous_medium` / `set_volume_grid` take optional `boundary_vertices` (N×3 world) + `boundary_indices` (M×3) kwargs, defaulted empty; structs by `const&` (MinGW rule) |
| `blender_addon/volume_export.py` | `mesh_world_triangles(obj, matrix_world)` (evaluated mesh, loop-triangles, world space, negative-scale flip as Cycles); `mesh_is_closed` edge-manifold check |
| `blender_addon/__init__.py` | Mesh-volume branch passes the triangles; DEGRADED line only for non-closed boundaries; surface+volume meshes keep their surface triangles too |
| `src/gpu/wavefront/stage_volume_hetero.cu` | `HasGridVolume=true` coverage loops call the device `nextCrossing` for media with a boundary |
| `src/gpu/wavefront/stage_advance.cu` | Shadow-kernel medium Tr uses the same coverage helper |
| `src/gpu/gpu_volume_phase.cuh` | Device coverage helper beside the `intersectAABB` twin |
| `include/astroray/gpu_types.h` | `GGridMedium` gains boundary BLAS offset/count (side table only; `GPUWavefrontState` untouched) |
| `src/gpu/wavefront/gpu_wavefront_snapshot.cu` | Upload boundary BLAS per medium (≤ 8), cached with the #828 grid cache, invalidated with the scene |
| `benchmarks/reference_corpus/build_corpus.py` | `volumes_mesh` family: icosphere, Suzanne, nested spheres, overlapping spheres, camera-inside fog sphere, glass shell with interior medium |
| `tests/test_issue833_mesh_volume_bounds.py` | Re-pin: closed mesh ⇒ no degradation; open mesh ⇒ still reported |

### Key design decisions

**Stateless boundary query, not a per-path stack.** A point at ray
parameter `t` is inside medium k iff the closest boundary-k crossing
after `t` is back-facing (geometric normal, Cycles' `SR_BACKFACING`). For
closed, consistently oriented meshes this equals Cycles' enter/exit stack,
including camera-inside (no separate init pass) and nested/overlapping
media (all covering media feed the existing `spectralTrackOverlap`
composite = Cycles summing stack entries). It carries no path state, so a
missed crossing cannot corrupt the rest of a path (the classic stack bug),
and the GPU shade kernel is untouched. pbrt-v4's single current-medium
interface is rejected: no overlap. Divergence: rays entering an OPEN mesh
through a hole count as inside here, outside in Cycles — the addon reports
non-closed boundaries (DEGRADED) and the gates avoid hole ROIs.

**Where the state lives (REG 254).** Nothing per path. Boundary BLAS
pointers/offsets live in the `__constant__ GWavefrontGridVolumeBinding`
side table (`GGridMedium`); queries run only in the `HasGridVolume=true`
intersect and shadow instantiations and `stageVolumeHeteroScatterKernel`.
`GPUWavefrontState` and `stageShadeBucketedKernel` must not change.

**Separate boundary BVH, not the scene BVH.** Volume-only triangles stay out
of the main BVH (no pass-through surface hits, no bounce-accounting or
transparent-depth changes, media-free traversal untouched). The medium's
AABB remains a pre-filter; the mesh query runs only where the AABB covers.

**Surface + volume meshes** (glass shell with interior medium) keep their
surface triangles in the scene BVH AND a boundary copy; the spawn offset
decides the side. Test it explicitly — this is the epsilon-sensitive case.

**Heterogeneous.** The boundary is medium-type agnostic: a grid medium with
a boundary is clipped to it (engine-level test). Procedural density on a
mesh volume (Noise Texture → Density) stays a DEGRADED default-value
lowering; file it as a follow-up issue, do not build it here.

#### Phase 0 — red tests and references (CPU only, no build)

Build the `volumes_mesh` corpus family and headless Cycles references
(256×256, 5 seeds, `volume_bounces` 0 and 4). Write the AABB regression
test: icosphere (subdiv 3) absorbing volume, orthographic view over a
bright emissive backdrop; the AABB-minus-sphere corner pixels must equal
the backdrop within 3σ. Confirm it FAILS on main before any engine change.

#### Phase 1 — CPU + addon

`MediumBoundary`, `mediumCoverage`, every CPU AABB site from Evidence
switched, bindings, addon triangles + closed-mesh check. Grep every
`aabbMin`/`intersectAABB` use and show none is left on the AABB-only path
for a bounded medium. One PR (or one batch commit set) with CPU gates green.

#### Phase 2 — GPU twin

Device boundary BLAS upload + query in the three `HasGridVolume` sites.
The lead runs the CUDA build. Register/stack table from `cuobjdump
--dump-resource-usage` before vs after is part of the PR body.

---

## Acceptance criteria

- [ ] Regression: the Phase 0 corner-pixel test fails on main (recorded in PR) and passes on CPU and GPU.
- [ ] Silhouette: icosphere volume mask IoU vs the Cycles mask ≥ 0.98 (mask = |render − empty-scene render| > 0.02 linear, 5-seed mean), CPU and GPU.
- [ ] Cycles ROI means, per channel, CPU and GPU, `volume_bounces` 0 and 4: sphere, Suzanne (ROIs off the eye holes), nested spheres, overlapping spheres, camera-inside fog, glass shell — each |ratio − 1| ≤ max(0.03, 3σ_seed) (the #860 five-seed method).
- [ ] Grid medium with a sphere boundary: zero density outside the sphere (engine-level, oracle = numpy Beer–Lambert on the clipped chord, ratio 0.98–1.02).
- [ ] GPU/CPU per-channel ROI ratio 0.97–1.03 on every `volumes_mesh` scene.
- [ ] Bit-identity: media-free Cornell `np.array_equal` CPU and GPU; an axis-aligned box mesh volume with and without its boundary within 3σ (same medium).
- [ ] Registers: `stageShadeBucketedKernel` 128/128 identical REG and STACK; all `HasGridVolume=false` intersect/shadow instantiations identical; `true` instantiations' deltas listed with zero new spill loads/stores.
- [ ] Cost: icosphere scene CPU and GPU wall time ≤ 1.3× the AABB path at equal spp.
- [ ] Addon: closed mesh volumes emit no DEGRADED line; open meshes still do; `test_issue833_mesh_volume_bounds.py` re-pinned; headless Blender F12 renders an icosphere volume round (lead inspects the PNG against Cycles).
- [ ] Full local suite green, CPU and RTX closeout sweep (CI has no GPU); `python scripts/project_index.py lint` passes for touched specs.

---

## Non-goals

- Do not put volume-only triangles in the scene BVH or add per-path stack state to `GPUWavefrontState`.
- Do not implement procedural (texture-driven) density or Color Attribute on mesh volumes; file an issue.
- Do not change the 8-media GPU cap, pkg294 lamp sampling, or world-volume paths.
- Do not add Cycles' Volume object bounds mesh around active voxels (VDB objects keep their grid AABB).

---

## Progress

- [x] Phase 0: research note, `volumes_mesh` corpus + Cycles refs, AABB regression test red on main (main: aabb_corner 0.19 vs Cycles 1.0, IoU 0.77)
- [x] Phase 1: CPU boundary + addon, CPU gates green (reviews pending) — pre-existing, boundary-independent divergences reported: multi-scatter red deficit at volume_bounces 4 (cube control 0.955), smooth-glass rim +7.5 % with no volume; media-free Cornell differs from main at the ulp level only (codegen, see research note)
- [ ] Phase 2: GPU twin, register table, GPU gates green, RTX sweep
- [ ] Lead visual inspection of icosphere/Suzanne/glass-shell renders vs Cycles

---

## Lessons

*(Fill in after the package is done.)*
