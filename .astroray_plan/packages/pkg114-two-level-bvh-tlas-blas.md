# pkg114 — Two-level BVH (TLAS/BLAS) for cheap instance + transform refit

**Pillar:** 5 (GPU) + 3 (light transport)
**Track:** A
**Codex-paste-ready:** no (core CUDA + CPU; large; multi-session RTX verify)
**Status:** COMPLETE (core) — all acceptance criteria met & RTX-verified
2026-06-12 (inc 1 #430, inc 2 #431, inc 3a #460, inc 3b #462, inc 3c #465,
inc 3d #468). GPU two-level BVH: instanced renders pixel-match flattened, share
one BLAS (Blender test 325→5 flat objects), mixed instanced+flat scenes work, the
addon instances collection/particle duplis, and a transform-only edit refits the
TLAS at **19.5%** of a full geometry upload (≤50% budget). **GPU-gated.** The
remaining exporter INTEGRATION is now **done (PR #TBD, 2026-07-18)**: the viewport
`Change.TRANSFORMS` path dispatches the inc-3d fast path
(`update_instance_transform` per dupli + `upload_instance_transforms` +
`render(skip_upload=True)`) for a pure transform-only batch whose changed objects
are all instanced sources or eligible instancer empties — headless Blender 5.1
refit render is **byte-identical** to a full re-sync (mad 0.00000 < 0.02). Follow-up
acceleration-structure package explicitly deferred by pkg56 §4.1.

### Increment log
- **Inc 1 (PR #430, merged):** device structs (`GMat4`/`GBLAS`/`GInstance`/
  `GTLASNode`), `gpu_tlas_hit` traversal (ray→BLAS-local, un-normalized dir →
  shared `tMax`; normal via inverse-transpose; frontFace recomputed in world
  space), and a device identity-passthrough parity probe. RTX: 4096 Cornell rays
  byte-exact on t/primId/mat/frontFace/point, normal ≤3.2e-6. Research note
  `.astroray_plan/docs/two-level-bvh-research.md` (PBRT-v4/Cycles/Embree, all
  Apache-2.0; corrected pbrt-v4 = Apache not BSD).
- **Inc 2 (PR #431, merged):** host `Renderer::registerMesh`/`addInstance` +
  bindings; `buildSceneArrays` two-level branch (per-mesh BLAS concatenated in
  object-local space, affine-inverse `Minv`, flat-leaf TLAS over instance
  world-AABBs); both megakernels routed through `gpu_tlas_hit` (null-TLAS →
  `gpu_bvh_hit` fallback, non-instanced scenes byte-unaffected). RTX: 3 instances
  (rigid / non-uniform scale / mirror) vs baked world-space — mean ratio 1.00000,
  mean abs diff 8.1e-9; BLAS sharing shown (4 prims vs 12 baked). Visual:
  `docs/renders/pkg114_instanced_tetrahedra.png`.
- **Inc 3a (PR #460, merged):** `register_mesh_bulk` binding — bulk twin of
  `register_mesh_triangles` ingesting object-local UVs / smooth normals /
  multi-material into a shared BLAS. RTX: 2 instances (smooth normals + 2 mats +
  UV layer) vs baked match; BLAS sharing 8 prims vs 16.
- **Inc 3b (PR #462):** **MIXED instanced + non-instanced scenes.** The two-level
  upload was all-or-nothing — any instance dropped every non-instanced "flat"
  object from the GPU. Fix: the flat scene (`cpu.getBVH()`) is uploaded first
  (offset 0) and exposed as ONE identity-transform instance, so `gpu_tlas_hit`
  traverses flat+instanced uniformly (no device change; inc-1 identity path is
  byte-exact). Flat prims at offset 0 keep pkg64-SMS + light emitter→prim search
  valid (flat-scene area lights now resolve in mixed scenes). Shared
  `appendFlatScene()` for single-level + mixed. Also adds an optional
  `object_name` to `register_mesh_bulk`/`register_mesh_triangles` → correct
  Cryptomatte object id on the shared BLAS. RTX: floor + 3 instanced tetrahedra
  (incl. mirror) == fully-baked; broad GPU regression sweep clean.
- **Inc 3c (addon wiring landed — PR pending):** Blender addon `convert_objects`
  registers each shared mesh datablock once + `add_instance(matrix_world)` per
  instance. **GPU-gated** via a pure device pre-check (`_render_will_use_gpu`;
  CPU keeps flattening — see Decisions). Groups `object_instances` by
  `(obj.data, obj.name)`, instances groups with **count ≥ 2** (object-local via
  `mesh_to_bulk_arrays` identity, `object_name=obj.name`); everything else
  flattens. `_object_instanceable` EXCLUDES emissive (mirrors the renderer's
  `'light'`-material gate) / caustic-caster / volume / non-MESH (→ flatten).
  Verified headless on Blender 5.1 (`scripts/verify_pkg114_instancing_blender.py`):
  collection-instanced props + static floor — instanced vs forced-flatten
  mean-abs-diff **0.0007**, per-channel ratios ~0.9997, flat-scene objects
  **325 → 5** (4 props collapsed into one shared BLAS + 4 instances; floor stays
  flat). Multi-material + smooth normals + non-uniform scale + mirror exercised.
- **Inc 3d (TLAS-only refit landed — PR pending):** `update_instance_transform`
  (CPU, in place) + `upload_instance_transforms` re-push ONLY `d_instances` +
  `d_tlas` (no BLAS geometry walk; per-mesh bounds from each cached BLAS's O(1)
  `boundingBox`), and `render(skip_upload=True)` renders from the existing device
  state. The instance/TLAS construction is shared with the full build
  (`buildInstancesAndTlas`) so a refit is byte-identical. RTX: refit-then-
  skip-upload render == a from-scratch build at the new transform (mad < 0.02,
  with a negative control proving `skip_upload` reads device state); refit upload
  cost **19.5%** of a full `upload_geometry` (≤50% budget met). `test_tlas_refit.py`.
- **Inc 3d exporter wiring (landed — PR #TBD, 2026-07-18):** `convert_objects`
  records `_renderer_instance_id_map` {source name: [instance_id…] in dupli order}
  and `_renderer_instancer_eligible` {instancer name: bool}. The viewport
  `Change.TRANSFORMS` branch takes the TLAS-only fast path
  (`refit_instance_transforms` re-walks `depsgraph.object_instances` and re-derives
  EACH dupli's fresh `matrix_world` → `update_instance_transform` per instance →
  `upload_instance_transforms()` → `render(skip_upload=True)`) iff the batch is
  pure-transform and every changed object is an instanced source or an eligible
  instancer empty. Pure-Python dispatch tests
  (`test_pkg114_exporter_transform_dispatch.py`, 7) + headless Blender 5.1
  (`scripts/verify_pkg114_refit_blender.py`): moving an instancer empty and
  refitting is **byte-identical** to a full re-sync (mad 0.00000 < 0.02; moved-image
  Δ 0.092 non-vacuous; negative control 0.092 proving `skip_upload` reads device
  state).

  **Decisions (inc 3c):** (1) addon instancing is **GPU-only**; CPU has no
  two-level traversal (renders solely via the scene-only `bvh`), so CPU keeps
  flattening — correct, no memory win. A CPU `InstanceHittable` decorator is a
  possible later enhancement. (2) Per-instance Cryptomatte uses the shared-BLAS
  `object_name` (duplis share the source name = one matte; linked duplicates
  stay count-1 → flatten). (3) GPU Cryptomatte is currently CPU-only for the
  `path_tracer` integrator (MW kernel has no crypto block) — orthogonal to this
  package. Multi-instance EMISSIVE-light NEE, instanced caustic casters, and
  deformation-motion-on-instances remain deferred. SAH TLAS stays an explicit
  non-goal. See memory `pkg114-instancing-engine-facts`.

  **Decisions (inc 3d exporter wiring, 2026-07-18):** (1) The refit never writes
  one `obj.matrix_world` onto a dupli group — since inc-3c only instances duplis
  (≥2 per name), each with its own composed `instancer ∘ prop_local` matrix, the
  fast path re-walks `depsgraph.object_instances` and re-derives each instance's
  fresh transform. It refreshes ALL mapped instances (not just the changed one):
  `upload_instance_transforms` rebuilds the whole TLAS from current transforms
  regardless, so this is free and immune to per-object change-attribution. (2)
  **Trigger semantics:** a moved instancer EMPTY takes the fast path when it is
  refit-eligible — recorded at registration as "not nested AND every dupli it
  generated went through the shared BLAS." Any poisoned instancer (a flattened
  member: count-1 linked dupe, emissive/caustic/volume, non-MESH), a nested
  instancer, a mixed flat+instanced transform batch, a transform batch mixed with
  another domain, or a CPU render (instance maps empty) all fall back to the
  existing full sync — a partial refit can't keep flat-scene geometry consistent.
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

- [x] Research note saved; references cited in code. *(inc 1)*
- [~] Instanced geometry renders correctly and shares one BLAS (memory evidence).
      *(inc 2: GPU API + `register_mesh`/`add_instance` shares one BLAS — 4 prims
      vs 12 baked, pixel-parity 8.1e-9. The Blender collection/particle path is
      inc 3.)*
- [x] Transform-only viewport edit ≤ **50%** of the pkg56 Phase-A baseline. *(inc 3d:
      `update_instance_transform` + `upload_instance_transforms` (TLAS-only re-push) +
      `render(skip_upload=True)`. Measured refit = **19.5%** of a full `upload_geometry`
      on 3200-tri ×16-instance; gap widens with geometry. `test_tlas_refit.py`.)*
- [x] **Pixel parity** vs single-level BVH on static scenes (RTX). *(inc 2:
      mean ratio 1.00000, mean abs diff 8.1e-9; inc 1 identity probe byte-exact)*
- [x] CPU/GPU parity gate green. *(routing is byte-safe for non-instanced scenes;
      full RTX regression sweep clean, only pre-existing xfails)*

## Hard non-goals

- Not motion-blur BVH (separate). Not deformable-mesh refit (rebuild the BLAS for
  now). Not a build-algorithm change (LBVH/SAH) beyond what BLAS reuse requires.

---

## Provenance

Blender-integration parity report 2026-05-30 (Q2); explicit pkg56 §4.1 deferral.
