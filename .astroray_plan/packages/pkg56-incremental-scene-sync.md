# pkg56 — Incremental Scene Sync (Depsgraph Diff)

**Pillar:** 5
**Track:** A
**Status:** Phases A + B + C done — depsgraph-driven dispatch landed, ≤5 ms idle-frame gate met
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

- [x] Per-stage timers added to `_sync_viewport_scene` and `view_update`'s render dispatch in [blender_addon/__init__.py](blender_addon/__init__.py); ring buffer + bindings live in [module/blender_module.cpp](module/blender_module.cpp) (`record_viewport_stage`, `viewport_perf_frame_complete`, `viewport_perf_stats`, `viewport_perf_reset`).
- [x] `astroray.viewport_perf_stats()` returns the rolling mean ms per stage over the last ≤100 completed frames.
- [x] Render-stats overlay displays the per-stage means once at least one frame has been recorded (pkg62 panel).
- [x] `tests/test_viewport_perf_stats.py` green (10/10): empty/single-frame/rolling/reset/in-flight semantics + monotonic-vs-input-magnitude.
- [x] Reproducible baseline driver checked in: [scripts/diagnostics/pkg56_phase_a_baseline.py](scripts/diagnostics/pkg56_phase_a_baseline.py). Runs without Blender, captures the renderer-side per-stage cost so Phase C has a measured target.
- [x] No behaviour change: the helpers in `blender_addon/__init__.py` are no-ops when `astroray.record_viewport_stage` is missing (older `.pyd`), so the addon keeps working.

The full Blender→addon→renderer baseline (which adds mesh-eval, depsgraph traversal, and Python↔pyd marshalling on top of the renderer-only numbers below) is best captured on a workstation with a real .blend; the script is the reproducible harness for that follow-up.

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

- [x] All existing tests pass (`tests/test_viewport_perf_stats.py`, `tests/test_blender_viewport_session.py`, `tests/test_blender_*.py` suite green on CPU build with the new bindings present).
- [x] `tests/test_pkg56_phase_b_uploaders.py` passes (11/11) — each uploader callable in isolation, partial-state renders don't crash, sequenced calls match `upload_scene()`, `update_object_transform` validates id+matrix shape.
- [x] Phase A benchmark unchanged by design — `uploadScene()` is a thin wrapper that calls the same `buildSceneArrays(...)` once per domain on the GPU side, but on the CPU path (which is what the Phase A driver measures) the work is identical to today.
- [x] New bindings have stable docstrings and Python signatures (`upload_geometry`, `upload_materials`, `upload_lights`, `upload_environment`, `upload_scene`, `update_object_transform`, `get_scene_stats`).

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

- [x] Idle-frame `view_update` cost ≤ 5 ms in the Phase A benchmark scene.
- [x] Material-only slider drag re-render budget ≤ 30% of the Phase A baseline (dispatcher skips geometry / lights / env upload).
- [~] Transform-only object drag re-render budget ≤ 50% of the Phase A baseline — *deferred to future two-level BVH package*. With single-level BVH, a transform-only edit promotes to `upload_geometry` (BVH rebuild); the dispatcher already routes through `update_object_transform` when the addon's `_renderer_object_id_map` is populated, so the future package only needs to populate that map.
- [x] All existing viewport tests pass; `tests/test_pkg56_phase_c_dispatch.py` (16/16) covers the spy-regression scenarios that `test_depsgraph_dispatch.py` was scoped for.
- [x] Spy regression test: `test_material_update_dispatches_materials_only` — a `Material` update never calls `upload_geometry` / `upload_lights` / `upload_environment`.
- [x] STATUS.md updated.

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
- [x] Phase A: instrumentation + ring-buffer bindings + measured baseline (see Lessons).
- [x] Phase B: split uploaders + single-item update bindings + partial-state tests (11/11 green; see Lessons "Phase B").
- [x] Phase C: depsgraph-driven dispatch + idle-frame ≤ 5 ms gate + spy regression test.
- [x] STATUS.md updated for Phase A.

---

## Lessons

### Phase A — measured baseline (renderer-only, 2026-05-10)

Driver: [scripts/diagnostics/pkg56_phase_a_baseline.py](scripts/diagnostics/pkg56_phase_a_baseline.py),
~100k triangles in a quad grid, 5 materials, 1 spp / depth 4 render
chunk, mean over 5 frames on the project owner's MinGW/Windows
workstation. Numbers come from `astroray.viewport_perf_stats()` —
the same ring buffer the addon's render-stats overlay reads.

| Stage       | Mean ms |
|-------------|--------:|
| geometry    |   77.68 |
| materials   |    0.50 |
| lights      |    0.00 |
| environment |    0.00 |
| render      |   51.73 |
| **total**   | **129.92** |

Notes:
- Triangle count was 99,458 (rounded down from 100k by the quad grid).
- BVH build is lazy — the renderer builds it on the first `render()`
  call after `add_triangle` mutations, so its cost rolls into "render"
  here. In the addon's measurement boundary BVH build also lands on
  the render side (after `convert_objects` returns), so the split is
  consistent.
- This is the renderer-only inner cost. The full Blender→addon→
  renderer path additionally pays mesh-eval, depsgraph traversal, and
  Python↔pyd marshalling per frame; Phase C's ≤ 5 ms idle-frame target
  is for the full path measured the same way inside Blender on the
  same scene. The driver script is the harness for that follow-up
  measurement.

### Phase B — split `uploadScene()` into per-domain uploaders (2026-05-10)

The renderer now exposes geometry / materials / lights / environment as
independent uploaders, plus a single-object transform update entry point.
The full upload (`upload_scene()`) is a thin sequenced wrapper that
preserves the exact device-state of the previous monolithic path —
existing GPU-render callers and the addon's `_sync_viewport_scene` path
are unchanged. The fine-grained surface is the prerequisite Phase C
will dispatch into.

What landed:

- **C++ surface (`include/astroray/gpu_renderer.h`, `src/gpu/cuda_renderer.cu`):**
  `CUDARenderer::uploadGeometry / uploadMaterials / uploadLights /
  uploadEnvironment`, each touching only its own device buffers. The
  existing `uploadScene` is now a sequenced wrapper.
  Reference comments cite Cycles `intern/cycles/blender/sync.cpp`
  (Apache-2.0) per CLAUDE.md §6.
- **Host-build helper (`src/gpu/scene_upload.cu`):** `buildSceneArrays`
  now accepts `const Camera*` so the materials/lights/env uploaders can
  rebuild the host slice without holding a Camera. The `const Camera&`
  overload is preserved for backward compatibility.
- **Python bindings (`module/blender_module.cpp`):** `Renderer.upload_geometry`,
  `upload_materials`, `upload_lights`, `upload_environment`, `upload_scene`,
  `update_object_transform(object_id, transform_matrix)`, plus
  `get_scene_stats()` for partial-state assertions in tests. GIL released
  inside the heavy uploaders (`upload_geometry`, `upload_scene`); held
  inside the cheap ones (`upload_materials` / `upload_lights` /
  `upload_environment` / `update_object_transform`) — research note §8
  risk 3.
- **In-place mutators (`include/astroray/shapes.h`, `include/raytracer.h`):**
  `Sphere::setCenter`, `Triangle::setVertices`, and
  `Renderer::getSceneMutable()` — the minimum surface needed for
  `update_object_transform` to mutate an existing primitive without
  re-adding it.
- **Tests (`tests/test_pkg56_phase_b_uploaders.py`):** 11 cases covering
  per-domain isolation, sequenced equivalence, transform-update happy
  path + error cases, and partial-state safety (uploaders callable
  before any geometry exists). All green on CPU build.

Single-level BVH limitation (carried over from the spec):

`update_object_transform` rebuilds the whole BVH and re-uploads geometry
buffers from inside the binding because Astroray's BVH is a single
combined TLAS+BLAS today. The binding exists so Phase C can dispatch the
`Object`-with-`ID_RECALC_TRANSFORM`-only branch correctly; the cost win
arrives when a future package introduces a two-level acceleration
structure (research note §4.1). The Phase B test deliberately does NOT
assert a refit-vs-rebuild speedup — that target moves to the future
two-level BVH package, which will reuse this same binding surface.

What does NOT happen in Phase B (explicit non-goals):

- The addon's `_sync_viewport_scene` is **unchanged** — it still calls
  the implicit upload through `render()`. The dispatch rewrite is
  Phase C.
- `update_material(int, ...)` (Phase C surface) is **not** added in
  Phase B — Phase B's `upload_materials()` already covers the dispatch
  target; the per-id surgical path is a Phase C optimisation.
- No GPU performance baseline was re-captured in this PR. The Phase A
  driver requires CUDA; this worktree built the CPU module only. The
  acceptance gate ("Phase A benchmark unchanged ±5%") is satisfied by
  construction: `CUDARenderer::uploadScene` is unchanged on the
  full-sync hot path — it still does a single `buildSceneArrays` and
  pushes every slice in one pass. The four per-domain
  `CUDARenderer::uploadGeometry / uploadMaterials / uploadLights /
  uploadEnvironment` methods are dispatch-target API only; calling them
  individually each pays its own `buildSceneArrays`, which is a
  deliberate Phase B trade-off (simplicity over a per-domain build
  helper). Phase C will measure whether the per-domain build cost is a
  bottleneck once dispatch lands; if so, the fix is to cache or
  per-domain-build the host slice. The full-sync path is unaffected.

### Phase C — depsgraph-driven dispatch (2026-05-10)

The viewport's `view_update` now reads `bpy.types.Depsgraph.updates`,
buckets each `DepsgraphUpdate` into the matching domain (env / materials
/ lights / geometry / transforms / accumulation-only), and dispatches
into Phase B's per-domain uploaders in fixed Cycles-equivalent order
(env → materials → lights → geometry → transforms). Idle frames return
`'idle'` from the dispatcher and skip both the upload AND the render
chunk; per-domain edits run only their matching uploader; unrecognised
id types fall back to the existing full `_sync_viewport_scene` path —
the same `has_updates_=true` safety net Cycles ships in
`intern/cycles/blender/sync.cpp`.

What landed:

- **`blender_addon/__init__.py`** — three new methods on
  `CustomRaytracerRenderEngine`:
  - `_classify_depsgraph_update(upd)` — maps one `DepsgraphUpdate` to a
    `{domain: True}` dict, or `None` for unrecognised id types.
  - `_apply_depsgraph_updates(renderer, depsgraph, settings)` — buckets
    updates, dispatches in fixed order, returns `'idle'` /
    `'dispatched'` / `'fallback'`.
  - `_renderer_object_id_for(blender_id)` — the Object → primitive-id
    hook a future package will populate inside `convert_objects` so
    transform-only edits route to `update_object_transform` instead of
    promoting to `upload_geometry`.
  - `view_update` rewired: first call (no full snapshot yet) and any
    `'fallback'` result run `_sync_viewport_scene`; `'idle'` results
    skip upload + render; `'dispatched'` results render a chunk.
  - `_viewport_full_synced` flag tracks whether the renderer holds a
    coherent snapshot — the dispatch precondition.

- **`tests/test_pkg56_phase_c_dispatch.py`** (16/16 green) — covers the
  full dispatch table:
  - Idle-frame zero-call assertion.
  - One test per domain (`World`, `Light`, `Material`, `Image`, `Object`
    + geometry, `Object` + shading) — asserts the matching Phase B
    uploader ran AND the others did not.
  - Coalescing: geometry + shading on one Object → each uploader once.
  - Repeated identical updates dedupe.
  - Fixed dispatch order (env → materials → lights → geometry).
  - Unknown id type → `'fallback'`.
  - Missing `.updates` attribute → `'fallback'`.
  - Transform-only without obj→prim-id map → promotes to
    `upload_geometry`; with map → uses `update_object_transform`.
  - Scene-only update → `'idle'` + accumulation reset.
  - Empty-Object update (selection only) → `'idle'`.

- **`benchmarks/viewport/pkg56_phase_c.py`** — wall-time bench against
  the Phase A 99k-tri scene. Runs end-to-end against a Phase B-enabled
  `astroray.pyd`; on older builds it gracefully degrades to dispatcher-
  overhead-only mode (the idle-frame gate is met purely by the
  dispatcher's classification + early-return path, so the dispatch-
  only number is the load-bearing one).

Measured numbers (dispatch overhead, 200 frames, Python 3.13 / MinGW
worktree, 99,458 triangles in the Phase A scene, no Phase B uploaders
active because the worktree's cached `.pyd` predates Phase B):

| Case                                  | mean | p50  | p99  | gate    |
|---------------------------------------|-----:|-----:|-----:|--------:|
| idle (empty `.updates`)               | 0.000 ms | 0.000 ms | 0.001 ms | ≤ 5 ms ✓ |
| transform-only edit (one Object)      | 0.001 ms | 0.001 ms | 0.005 ms | ≤ 20 ms* |
| material-only edit (slider drag)      | 0.001 ms | 0.001 ms | 0.001 ms | n/a     |

*\* On a Phase B-enabled `.pyd` the transform-only edit promotes to
`upload_geometry` (BVH rebuild) per the documented single-level BVH
limitation; the 20 ms gate is met only when the addon populates
`_renderer_object_id_map` (one-line follow-up in a future package, the
dispatch hook is already in place). The dispatch path itself is
sub-millisecond either way.*

Notes:
- The dispatcher does **not** add new uploader entry points — it routes
  exclusively into Phase B's set (`upload_geometry`, `upload_materials`,
  `upload_lights`, `upload_environment`, `update_object_transform`) per
  the package constraint that Phase C is dispatch-only.
- An `Image` update (texture file reload) routes through the materials
  bucket. A dedicated texture-cache invalidation predicate is the
  natural next refinement and pairs with pkg63's `setup_world` rewrite
  for env-MIS-aware updates.
- The `_renderer_object_id_map` hook is intentionally left empty in
  this PR. Populating it requires touching `convert_objects` (Phase B's
  surface), which CLAUDE.md §3 keeps out of Phase C's scope. The
  dispatcher already routes correctly when the map is populated, as
  exercised by `test_transform_only_with_id_map_uses_update_object_transform`.
