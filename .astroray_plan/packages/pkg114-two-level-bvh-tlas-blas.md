# pkg114 — Two-level BVH (TLAS/BLAS) for cheap instance + transform refit

**Pillar:** 5 (GPU) + 3 (light transport)
**Track:** A
**Codex-paste-ready:** no (core CUDA + CPU; large; multi-session RTX verify)
**Status:** open — proposed 2026-05-30. **GPU-gated.** This is the follow-up
acceleration-structure package explicitly deferred by pkg56 §4.1.
**Depends on:** pkg56 (done — provides the `_renderer_object_id_map` placeholder
and transform-only dispatch hook). Complementary to pkg112.
**Estimated effort:** L (~3–4 weeks, multiple RTX sessions)

---

## Goal

**Before:** Astroray's BVH is single-level (one combined tree). Moving a single
object rebuilds the **entire** BVH; pkg56's transform-only viewport path still
pays a full CPU rebuild (~80–200 ms on 100k tris per the Phase-A benchmark), and
the "transform-only ≤50% of baseline" gate was **deferred** (pkg56 §4 non-goals).
Instanced geometry is not deduplicated.

**After:** A two-level acceleration structure — per-mesh **bottom-level (BLAS)**
built once and cached, and a **top-level (TLAS)** over instance transforms,
rebuilt/refitted cheaply when an object moves. Instances of the same mesh share
one BLAS. Transform-only viewport edits meet the pkg56 ≤50%-of-baseline budget.

---

## References

### Internal
- pkg56 `.astroray_plan/packages/pkg56-incremental-scene-sync.md` §4.1
  (deferred TLAS-refit) and Phase-B `update_object_transform` uploader.
- The single-level BVH build (CPU) and CUDA traversal in `include/` /
  `astroray/` (the structure this package splits in two).

### External (cite the reproduced reference in code; license-clean)
- **PBRT-v4 §4.3** `BVHAccel` and the instancing/two-level pattern
  (pbr-book.org; BSD) — canonical structure.
- **Cycles** `intern/cycles/bvh/bvh2.{h,cpp}` and object/instance BVH
  (Apache-2.0) — TLAS-over-instances + per-object BLAS layout to mirror.
- Wald et al. / Embree + NVIDIA OptiX TLAS-BLAS concept (papers) for the
  device-traversal transform-into-local-space approach.

CLAUDE.md §6: this is a non-trivial structural algorithm — cite the exact
reference (PBRT §4.3 / Cycles `bvh2`) in the C++/CUDA, and save a research note
to `.astroray_plan/docs/two-level-bvh-research.md` before coding.

---

## Approach (phased)

1. **BLAS cache.** Build per-mesh BVH keyed by the mesh datablock; reuse across
   instances and across frames when the mesh is unchanged.
2. **TLAS.** Build over `(instance_id → BLAS ref + 4×4 transform)`; ray
   traversal transforms the ray into BLAS-local space.
3. **CUDA.** Device-side two-level traversal; upload only the instance transform
   table on a transform edit (cheap), not geometry.
4. **Depsgraph wiring.** Transform-only update → TLAS rebuild only; geometry
   update → rebuild only that BLAS. Hooks into pkg56's dispatch.

---

## Acceptance criteria

- [ ] Research note saved; references cited in code.
- [ ] Instanced geometry (collection/particle instances) renders correctly and
      shares one BLAS (memory/timing evidence).
- [ ] Transform-only viewport edit ≤ **50%** of the pkg56 Phase-A baseline.
- [ ] **Pixel parity** vs single-level BVH on static scenes (RTX `/verify`).
- [ ] CPU/GPU parity gate green.

## Hard non-goals

- Not motion-blur BVH (separate). Not deformable-mesh refit (rebuild the BLAS for
  now). Not a build-algorithm change (LBVH/SAH) beyond what BLAS reuse requires.

---

## Provenance

Blender-integration parity report 2026-05-30 (Q2); explicit pkg56 §4.1 deferral.
