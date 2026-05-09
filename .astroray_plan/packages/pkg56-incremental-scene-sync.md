# pkg56 — Incremental Scene Sync (Depsgraph Diff)

**Pillar:** 5
**Track:** A
**Status:** open (research signed off)
**Estimated effort:** 3 phases × 1–2 weeks each = ~85 h total over 4–6 weeks of calendar time. Phase A: 1 week (~15 h). Phase B: 2 weeks (~30 h). Phase C: 2–3 weeks (~40 h).
**Depends on:**
- pkg52 (persistent viewport session, **done**) — hard dependency. Without a renderer that survives across frames, incremental sync is meaningless.
- pkg63 (world / HDRI parity, **in flight**) — soft dependency. Phase C's environment-update predicate keys off pkg63's `setup_world` rewrite for the "did the env actually change?" decision. If pkg63 lands first, Phase C uses its predicate directly. If pkg56 ships first, Phase C uses a coarser "any World update → full env re-upload" fallback and is refined when pkg63 lands.

---

## Goal

**Before:** Every depsgraph update — moving a light, dragging a material slider, ticking the timeline, toggling a modifier on an off-screen object — triggers `_sync_viewport_scene` ([blender_addon/__init__.py:802](blender_addon/__init__.py:802)), which calls `renderer.clear()` and re-walks every material, mesh, light, and the world. On a 100k-tri scene this costs an estimated 300–800 ms per event (measured precisely in Phase A). pkg52's persistent renderer cannot accumulate samples between user inputs because every input pays full re-upload cost.

**After:** `view_update` reads `bpy.types.Depsgraph.updates` and dispatches only to the affected uploader: material edits skip geometry, transform edits skip materials, idle frames cost ≤ 5 ms. The full-sync path is preserved for the first frame, the final render path, and as an explicit fallback for unrecognised update types. Behaviour mirrors Cycles' `BlenderSync::sync_recalc` decision tree (see research note §2).

---

## Context

This is the architectural follow-up to pkg52. pkg52 made the renderer persist; pkg56 makes the *upload pipeline* incremental so persistence pays off. The full design — including a per-component cost estimate, the Cycles algorithm walk-through, the depsgraph API mapping, BVH refit-vs-rebuild policy, material/world propagation rules, risks, and the three-phase migration plan — is in [.astroray_plan/docs/blender-depsgraph-sync-research.md](.astroray_plan/docs/blender-depsgraph-sync-research.md).

CLAUDE.md §6 applies: every dispatch decision in this package mirrors a specific Cycles function with a cited line range. No invented algorithms.

---

## Reference

- **Cycles `BlenderSync` (Apache-2.0):** `intern/cycles/blender/sync.h`, `sync.cpp`, `object.cpp`, `session.cpp`. Specific line ranges per pattern in the research note §9.
- **Blender depsgraph API:** `bpy.types.Depsgraph.updates` / `DepsgraphUpdate` (`id`, `is_updated_transform`, `is_updated_geometry`, `is_updated_shading`). C-side: `source/blender/depsgraph/DEG_depsgraph_query.h`.
- **Existing Astroray code:** [blender_addon/__init__.py](blender_addon/__init__.py:802) (`_sync_viewport_scene`), `view_update` (line 894), `view_draw` (line 921); [module/blender_module.cpp](module/blender_module.cpp) (`PyRenderer::clear` line 1074, `uploadScene` site line 715, pybind11 bindings 1128+).
- **License:** Cycles is Apache-2.0 (mirrorable into MIT). BlendLuxCore is GPL-3.0 (architecture-only; no porting).

---

## Prerequisites

- [x] pkg52 persistent viewport session in place.
- [ ] Owner sign-off on [blender-depsgraph-sync-research.md](.astroray_plan/docs/blender-depsgraph-sync-research.md).
- [ ] Confirm the §1 estimated cost numbers are within the right order of magnitude on a real workstation before committing to the Phase A baseline scope.

---

## Specification

The work is three phases, each landed as its own PR. Phase A is measurement; Phase B is a refactor with no behavioural change; Phase C is the actual incremental dispatch. See research note §7 for full rationale.

### Phase A — Instrument the existing upload path

**Goal:** replace the §1 estimates with measured numbers. No behaviour change.

#### Files to create

| File | Purpose |
|---|---|
| `tests/scenes/viewport_sync_bench.py` | Reproducible 100k-tri benchmark scene (Cornell box + Suzanne instance + HDRI). CPU build is sufficient. |
| `scripts/diagnostics/viewport_sync_profile.py` | Driver that loads the benchmark scene, fires synthetic `view_update` calls with the `ASTRORAY_VIEWPORT_PROFILE=1` flag, and writes a per-component timings table to `test_results/viewport_sync_profile.json`. |

#### Files to modify

| File | What changes |
|---|---|
| [blender_addon/__init__.py](blender_addon/__init__.py) | Wrap each block of `_sync_viewport_scene` (clear, materials, objects, lights, world, backend config) in monotonic-clock timers gated by `os.environ.get("ASTRORAY_VIEWPORT_PROFILE")`. Print a per-component breakdown to stderr; emit JSON when a sink path is set. |
| [module/blender_module.cpp](module/blender_module.cpp) | Optional `Renderer::set_profiling_enabled(bool)` binding that times the C++ side of `addTriangle` / `clear` / BVH build / device upload. Same env-var gate. |
| [.astroray_plan/docs/blender-depsgraph-sync-research.md](.astroray_plan/docs/blender-depsgraph-sync-research.md) | Append the measured numbers table; this becomes the Phase B/C baseline. |

#### Acceptance gate (Phase A)

- [ ] Per-component cost table appended to the research note.
- [ ] No-change-frame baseline figure published (the cost of `view_update` on a frame where nothing actually changed). This is the number Phase C drives below 5 ms.
- [ ] Reproducible by another contributor on a different box (script + scene checked in).
- [ ] `ASTRORAY_VIEWPORT_PROFILE` is undefined → zero overhead. Existing tests unchanged.

### Phase B — Split `uploadScene()` into per-component uploaders

**Goal:** the renderer exposes geometry, materials, lights, and environment as independent uploaders, plus single-item update entry points for the common cases. **Behaviour is unchanged at this phase** — full sync still calls all four; the win is the surface for Phase C.

#### Files to create

| File | Purpose |
|---|---|
| `tests/test_blender_module_upload_split.py` | Calls each new uploader in isolation, asserts the renderer is in a sane state after partial uploads (e.g. materials-only → render returns black, not a crash). |

#### Files to modify

| File | What changes |
|---|---|
| [module/blender_module.cpp](module/blender_module.cpp) | New methods: `uploadGeometry()`, `uploadMaterials()`, `uploadLights()`, `uploadEnvironment()`, `update_material(int material_id, ...)`, `update_object_transform(int object_id, mat4)`. Re-implement the existing `uploadScene` path as a sequenced call to all four. Drop the GIL inside `uploadGeometry` (long-running) via `py::call_guard<py::gil_scoped_release>`; keep it held in `update_material` (short, no benefit). |
| [include/astroray/](include/astroray/) (renderer header) | Mirror C++ method signatures. |
| [blender_addon/__init__.py](blender_addon/__init__.py) | `_sync_viewport_scene` re-implemented as four sequenced calls into the new uploaders. No external behaviour change. |

#### Key design decisions (Phase B)

1. **`update_material(int, ...)` is the surgical path.** The most common user action is a slider drag on one material. It must not touch geometry, BVH, lights, or env. Mirror Cycles' `Shader::tag_update()` semantics (see research note §5).
2. **`update_object_transform(int, mat4)` exists from Phase B but is single-level today.** Astroray's BVH is a single combined TLAS+BLAS; transform-only changes still rebuild the whole BVH inside this binding for now. The binding exists so Phase C can dispatch correctly; the cost win arrives when a future package introduces a two-level acceleration structure (research note §4.1). Document this clearly in the binding's docstring.
3. **`uploadEnvironment()` is the only env path.** No incremental "tint changed but image didn't" optimisation in Phase B — that wires through pkg63's `setup_world` rewrite (research note §6) and lands as part of Phase C.
4. **Uploaders are order-independent for state.** The renderer must tolerate `uploadMaterials` before `uploadGeometry` (materials defined, no triangles → black image, not a crash). This makes Phase C's dispatch order safe.
5. **Final-render path unchanged.** `render(depsgraph)` still does a full upload. pkg56 changes the viewport sync only.

#### Acceptance gate (Phase B)

- [ ] All existing tests pass.
- [ ] `tests/test_blender_module_upload_split.py` passes — each uploader callable in isolation, partial-state renders don't crash.
- [ ] Phase A benchmark unchanged ±5% (refactor is cost-neutral by design).
- [ ] New bindings have stable docstrings and Python signatures.

### Phase C — Depsgraph-driven dispatch

**Goal:** `view_update` reads `depsgraph.updates` and dispatches only the affected uploaders.

#### Files to create

| File | Purpose |
|---|---|
| `tests/test_depsgraph_dispatch.py` | Stubbed Blender API tests for the dispatch table: each `DepsgraphUpdate` type produces the expected uploader call set. Spy on the renderer to assert "Material edit on A does NOT call `uploadGeometry`". |
| `tests/scenes/depsgraph_regression.py` | Scripted scene with one Object, two Materials. Sliding Material A's roughness must produce a `update_material(A, ...)` call and **no** geometry upload. |

#### Files to modify

| File | What changes |
|---|---|
| [blender_addon/__init__.py](blender_addon/__init__.py) | New `_apply_depsgraph_updates(self, renderer, depsgraph, settings)` method. `view_update` calls `_apply_depsgraph_updates` instead of `_sync_viewport_scene` when a previous full sync exists. The dispatch table (research note §3.2): `Object`+transform → `update_object_transform`; `Object`+geometry → `uploadGeometry`-for-affected-mesh-and-instances; `Material`/`NodeTree` → `update_material`; `Image` → texture cache invalidate + targeted re-upload; `World` → `uploadEnvironment`; `Light` → `uploadLights`; `Scene`/frame → reset accumulation only. Unrecognised update types fall back to full `_sync_viewport_scene`. Updates are bucketed by type and dispatched in fixed order (env → materials → lights → geometry → transforms) regardless of iteration order (research note §8 risk 5). Any update that changes the image must call `_reset_viewport_accumulation` (the pkg52 hook). |
| [blender_addon/__init__.py](blender_addon/__init__.py) | Texture cache key extended to `(image.name, image.size, image.depth, image.colorspace_settings.name)` to handle external-file reloads (research note §8 risk 4). |
| [.astroray_plan/docs/STATUS.md](.astroray_plan/docs/STATUS.md) | Move pkg56 from "deferred" to active/done, summarise the cost win. |

#### Key design decisions (Phase C)

1. **Full-sync fallback is mandatory.** First frame, unrecognised update types (skin modifier, particle system, grease pencil — explicit non-goals), and the case where `_viewport_renderer` is fresh all fall back to `_sync_viewport_scene`. Cycles does the same — `has_updates_` defaults to `true` so the first call is always a full sync.
2. **Bucket then dispatch in fixed order.** Don't trust iteration order of `depsgraph.updates`. Collect into typed buckets (env / materials / lights / geometry / transforms / accumulation-only) and run them in a fixed order. Mirrors Cycles' explicit ordering in `sync_data()`.
3. **Mesh-instance fanout.** A `Mesh` update affects every `Object` instancing that mesh. Resolve through the existing material/object map cached in the addon — do not walk the depsgraph again.
4. **Accumulation reset semantics.** Every uploader call that changes the image resets the pkg52 progressive accumulator. Bucketing makes this a single reset per frame, not per update.
5. **No off-thread upload.** All renderer mutation stays on the Blender main thread (research note §8 risk 1). Document this in the binding.

#### Acceptance gate (Phase C)

- [ ] Idle-frame `view_update` cost ≤ 5 ms in the Phase A benchmark scene.
- [ ] Material-only slider drag re-render budget ≤ 30% of the Phase A baseline.
- [ ] Transform-only object drag re-render budget ≤ 50% of the Phase A baseline (limited by single-level BVH; the bigger win arrives with a future BVH-refit package).
- [ ] All existing viewport tests pass; `tests/test_depsgraph_dispatch.py` and `tests/scenes/depsgraph_regression.py` pass.
- [ ] Spy regression test: a `Material` slider drag never calls `uploadGeometry`.
- [ ] STATUS.md updated.

---

## Non-goals

- **Not a full Cycles-feature-parity sync.** Skin modifier, grease pencil, particle systems, hair/curves dynamics fall through to the full-sync fallback. Adding any of these is a separate package.
- **Not a GPU-side restructure.** The CUDA upload path and integrator kernels do not change. pkg55 (wavefront SoA) owns kernel-side work.
- **Not a two-level acceleration structure.** Astroray's BVH stays single-level for pkg56; transform-only updates rebuild the whole BVH (with the cheaper-than-today Phase C path skipping materials/lights/env). True TLAS-refit is a follow-up package.
- **Not a final-render path change.** `render(depsgraph)` continues to do a full upload. pkg56 changes the viewport sync only.
- **Not env-MIS aware on its own.** The MIS CDF cost-management lands when pkg63's `setup_world` predicate plumbs through (soft dependency). Until pkg63 lands, World updates do a full env re-upload.

---

## Progress

- [x] Research note signed off ([blender-depsgraph-sync-research.md](.astroray_plan/docs/blender-depsgraph-sync-research.md)) — pending owner review.
- [ ] Phase A: instrumentation + benchmark scene + measured baseline appended to research note.
- [ ] Phase B: split uploaders + single-item update bindings + partial-state tests.
- [ ] Phase C: depsgraph-driven dispatch + idle-frame ≤ 5 ms gate + spy regression test.
- [ ] STATUS.md updated.

---

## Lessons

*(Fill in after the package is done.)*
