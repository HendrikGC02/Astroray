# Blender Depsgraph Incremental Scene Sync — Research

**Status:** research, signed off pending owner review
**Owner package:** [pkg56-incremental-scene-sync.md](../packages/pkg56-incremental-scene-sync.md)
**Author:** Claude Code (Track A, research session, worktree `research-depsgraph`)
**Date:** 2026-05-10
**Source pin:** Blender `main`, fetched 2026-05-10 (file paths stable since 4.0; line ranges may drift by a handful of lines, but the function structure and decision logic cited here are unchanged across the 4.x series).
**License posture:** Cycles is Apache-2.0 (mirrorable into Astroray's MIT). BlendLuxCore is GPL-3.0 (architecture reference only — no code mirroring, no close paraphrasing). Blender's depsgraph public C API headers and the Python `bpy.types.DepsgraphUpdate` surface are part of Blender's normal extension contract — use as documented, no porting concern.

---

## 1. The problem

pkg52 ([pkg52-persistent-viewport-session.md](../packages/pkg52-persistent-viewport-session.md)) landed a persistent viewport `Renderer` on the Blender side. The renderer instance survives across `view_update` / `view_draw` calls and progressively accumulates samples until `preview_samples` is reached. That fix made wheel-zoom and orbit re-render correctly.

But every `view_update` still performs a *full* scene re-upload through [`_sync_viewport_scene`](../../blender_addon/__init__.py:802):

```
renderer.clear()
renderer.set_clamp_direct(...)
... # all material toggles re-pushed
self.convert_materials(depsgraph, renderer)   # walks every material
self.convert_objects(depsgraph, renderer, ...) # walks every Object,
                                              # rebuilds every Mesh,
                                              # adds every Triangle
self.convert_lights(depsgraph, renderer)
self.setup_world(depsgraph.scene, renderer)
```

Concretely, what `renderer.clear()` followed by `convert_objects` costs on a non-trivial scene:

| Component                             | Per-frame cost on a 100k-tri scene |
|---|---|
| Tear down the GPU scene buffers       | ~5–10 ms (cudaFree, host vector clears) |
| Re-walk every `bpy.types.Object` evaluated copy | ~20–50 ms (Python iteration is the floor) |
| `add_triangle` × N (100k calls into pybind11) | ~150–400 ms |
| `add_triangle_layers` UV upload (pkg59) | ~30–80 ms |
| Re-build BVH on CPU                   | ~80–200 ms |
| Re-upload BVH + materials to CUDA     | ~10–30 ms |
| **Total per `view_update`**           | **~300–800 ms** |

(Numbers are estimates from the existing [module/blender_module.cpp](../../module/blender_module.cpp) upload path's structure. They will be replaced by Phase A measurements; see §7.)

Any depsgraph event — moving a single light, scrolling a material slider, toggling a modifier on an off-screen object, ticking the timeline — triggers the full path. For a 100k-tri scene, the user types one slider digit, pays 0.5 s of re-upload, then the renderer starts a 1-spp viewport pass. The "persistent renderer" win from pkg52 is consumed by the per-event upload cost, and progressive accumulation rarely gets beyond a handful of samples between user inputs.

This is the same wall Cycles hit ten years ago and solved with depsgraph diffing. The Astroray addon should mirror their structure.

---

## 2. Cycles' approach

Cycles' viewport sync is centred on `BlenderSync` (`intern/cycles/blender/sync.cpp`, `sync.h`). The class diffs Blender's evaluated depsgraph against Cycles' last-known scene state and only re-exports what changed.

### 2.1 The `has_updates_` flag and `tag_update()`

`BlenderSync::has_updates_` is the master "do I need to do anything at all this frame" boolean. It defaults to `true` (so the first call always syncs) and is cleared at the very end of `sync_data()`.

- `intern/cycles/blender/sync.h:224` — `bool has_updates_ = true;` with the inline comment *"Indicates that `sync_recalc()` detected changes in the scene."*
- `intern/cycles/blender/sync.h:52` — `void tag_update();` setter that flips it back to `true` when external code (e.g. session params change, denoiser toggle, viewport flag) wants to force a re-sync independent of the depsgraph.
- `intern/cycles/blender/sync.cpp:85–87` — the trivial setter body.
- `intern/cycles/blender/sync.cpp:294–341` — `sync_data()` opens with the early-out:
  ```
  if (!has_updates_ && !auto_refresh_update) { return; }
  ```
  and ends (~line 335) with `has_updates_ = false;`. Auto-refresh exists because animated image textures don't fire depsgraph updates per frame.

This is the pattern: the depsgraph clears the flag *implicitly* — the next frame, if no `ID_RECALC_*` bits are set on any ID, `sync_recalc()` does not flip `has_updates_` back to true, and `sync_data()` returns immediately. Cost of an idle frame is ~0.

### 2.2 `sync_recalc()` — depsgraph diff

`intern/cycles/blender/sync.cpp:99–291` is the diff loop. The structure:

1. **Iterate only updated IDs** (`sync.cpp:107–121`). Cycles uses `DEG_iterator_ids_begin` with `only_updated = true`, so the loop walks only IDs the depsgraph flagged this evaluation. Idle frames iterate zero IDs.

2. **Switch on `GS(b_id->name)` ID type** to dispatch to the right map. The relevant types for us are `ID_OB` (Object), `ID_ME`/`ID_CU_LEGACY`/`ID_HA`/etc. (geometry datablocks), `ID_MA` (Material), `ID_NT` (NodeTree), `ID_IM` (Image), `ID_WO` (World), `ID_LA` (Light).

3. **Read `recalc` bitfield on the ID** (`sync.cpp:153–160`):
   - `ID_RECALC_TRANSFORM` — object moved (translation/rotation/scale or parent chain)
   - `ID_RECALC_GEOMETRY` — mesh data changed (verts, topology, modifiers re-evaluated)
   - `ID_RECALC_SHADING` — material/shader graph changed
   - The decision rule:
     ```
     if (updated_geometry || (updated_transform && use_adaptive_subdiv))
     ```
     Transform alone does **not** force geometry re-export — the object map records the new transform and the BVH refits. Geometry changes (or transform under adaptive subdivision, where dicing depends on object scale) force `Geometry::tag_modified()`.

4. **Set `has_updates_ = true`** if anything was found, leave it false otherwise.

The Python-side mirror of this is `bpy.types.Depsgraph.updates` — an iterator of `DepsgraphUpdate` records, each carrying `id`, `is_updated_transform`, `is_updated_geometry`, `is_updated_shading`. The semantics are identical to the C `ID_RECALC_*` flags above; that's deliberate — the Python iterator is a thin wrapper over the same depsgraph state.

### 2.3 `sync_objects()` and the geometry/transform split

`intern/cycles/blender/sync.cpp` `sync_objects()` walks the depsgraph object iterator and calls `sync_object()` per evaluated object. The cheap-vs-expensive split lives in `intern/cycles/blender/object.cpp`:

- `object.cpp:246–249` — the work-or-skip predicate:
  ```
  bool object_updated = object_map.add_or_update(&object, &b_ob.id,
      &b_parent->id, key) || !object->tfm_equals(tfm);
  ```
  i.e. "this is a new object the map hasn't seen, *or* the transform changed."
- `object.cpp:252–254` — geometry is fetched conditionally:
  ```
  Geometry *geometry = sync_geometry(b_ob_info, object_updated, ..., task_pool);
  object->set_geometry(geometry);
  ```
  When `object_updated` is false, `sync_geometry` short-circuits — the existing Geometry pointer is reused, no mesh data is re-read from Blender, no BVH leaf is rebuilt.
- `object.cpp:226–240` — motion-blur path: when only motion time samples differ (subframe sample), the code calls `sync_geometry_motion()` instead of full geometry sync. Not directly relevant to viewport interaction, but the same pattern: targeted update, never the global path.

### 2.4 Geometry sync, dirty sets, and the BVH

`BlenderSync` keeps `set<Geometry *> geometry_synced;` (`sync.h:194`) so that within a single `sync_data` call, instanced geometry reachable through multiple objects is only synced once. `id_map<...> shader_map;` (`sync.h:191`) does the same for shaders, and `bool world_recalc;` (`sync.h:208`) is a one-bit dirty flag for the world/HDRI.

After `sync_data()` returns, `Scene::need_update` is consulted by the device-update step to decide what to push to the GPU and how to update the BVH (covered next).

---

## 3. The depsgraph API surface

### 3.1 Python side (what the addon uses)

The Blender Python API exposes the same diff structure that Cycles reads in C:

- `depsgraph.updates` — iterator of `DepsgraphUpdate`. Only contains IDs the depsgraph flagged this evaluation.
- `DepsgraphUpdate.id` — the evaluated ID datablock that changed. `id.bl_rna.identifier` (or `type(id).__name__`) tells us the class: `Object`, `Mesh`, `Material`, `ShaderNodeTree` / `NodeTree`, `Image`, `World`, `Light`, `Camera`, `Scene`.
- `DepsgraphUpdate.is_updated_transform` — boolean, set when the matrix changed.
- `DepsgraphUpdate.is_updated_geometry` — boolean, set when evaluated mesh data changed (verts, indices, topology, modifier re-evaluation).
- `DepsgraphUpdate.is_updated_shading` — boolean, set when a shading-relevant property changed (material socket, image colorspace, world background colour).

(These map 1:1 to `ID_RECALC_TRANSFORM` / `ID_RECALC_GEOMETRY` / `ID_RECALC_SHADING` cited in §2.2.)

### 3.2 What each ID type means for our pipeline

| `id` class       | Triggered by user action               | Astroray reaction                                    |
|---|---|---|
| `Object`         | move / rotate / scale / link / unlink  | re-upload object's transform + flag BVH refit; if `is_updated_geometry`, also re-upload its mesh and flag BVH rebuild for that subtree |
| `Mesh` / `Curve` | edit-mode changes, modifier change     | re-upload triangles + UVs for every Object instancing this datablock; flag BVH rebuild for affected subtrees |
| `Material`       | slider / colour / IOR change           | rebuild the Astroray `Material` for that material id; **no geometry upload** |
| `NodeTree`       | shader graph topology change           | full re-conversion of the parent material (we already do `_eval_color_socket_node` walking) |
| `Image`          | image reload, colorspace change        | invalidate texture cache entry; re-upload that texture's GPU memory only |
| `World`          | HDRI swap, background tint change      | `world_recalc = true`; rebuilds env atlas + (post-pkg63) MIS CDF |
| `Light`          | light power / colour / size change     | re-upload that light only |
| `Camera`         | (rare from depsgraph; usually viewport-side) | already handled by `_camera_state_hash` from pkg52 |
| `Scene`          | render setting change, frame change    | force tag-update equivalent — just re-render, no scene mutation |

### 3.3 C-side header (for reference if we ever talk to the depsgraph natively)

`source/blender/depsgraph/DEG_depsgraph_query.h` exposes `DEG_id_type_updated`, `DEG_get_evaluated_id`, `DEG_iterator_objects_begin/next/end`. The addon does **not** need to call these directly — `bpy.types.Depsgraph` covers everything we need. We mention them only because Cycles uses the C iterator (`DEG_iterator_ids_begin` in `sync.cpp:107–121`) where the Python addon will use the iterator wrapper. No functional difference.

---

## 4. BVH refit vs rebuild

Cycles' rule, distilled from `intern/cycles/scene/geometry.cpp:274–280` and `update_kernel_features`:

| Change                                  | BVH action                          |
|---|---|
| Object transform only                   | **refit** (top-level BVH refit; per-mesh BLAS untouched). ~constant-time in #objects, no leaf reconstruction. |
| Single mesh's vertex positions changed, topology unchanged | **refit** that mesh's BLAS only (BVH2 / Embree / OptiX-with-allow-update layouts only). |
| Topology changed (vert count, index count, primitive offsets) | **rebuild** that mesh's BLAS, then refit/rebuild TLAS. |
| Object added or removed                 | **rebuild full TLAS** (primitive offsets shift; OptiX/Metal forbid refit when offsets change — see `geometry.cpp:274`). |
| BVH layout changed (device switch, motion blur on/off) | **rebuild everything**. |

The OptiX caveat is the load-bearing comment from `geometry.cpp:274–280`:
> "Need to rebuild BVH in OptiX, since refit only allows modified mesh data."

i.e. on OptiX/Metal, even an in-place vertex update through a stale primitive layout is illegal; a topology change must be a rebuild.

### 4.1 Astroray's BVH structure

Astroray uses a CPU-built BVH that is uploaded to CUDA in `cudaRenderer->uploadScene(...)` ([module/blender_module.cpp:715](../../module/blender_module.cpp)). It is a single TLAS+BLAS combined structure today, not a two-level acceleration structure. This matters for pkg56:

- **Today:** any geometry change forces a full rebuild and re-upload. There is no refit path.
- **Phase B (this package):** split the upload into geometry/material/lights/env so a *non-geometry* change skips the BVH path entirely. That alone recovers most of the win — sliding a material colour should not touch the BVH.
- **Phase B follow-up (out of scope, defer to a successor pkg):** introduce a real two-level acceleration structure so per-object transform changes can refit the TLAS without rebuilding leaves. Cycles' policy maps cleanly once the structure is two-level.

For pkg56 we recommend matching Cycles' decision table at the *dispatch* level (the addon decides which uploader runs) and treating the underlying single-level BVH as a temporary limitation. The kernel and acceleration structure are out of scope for this package; pkg55 (wavefront SoA) and a future BVH-refit package own that work.

---

## 5. Material change propagation

A pure material slider drag is the most common user action and the cheapest one for Cycles to handle. The path is:

1. Blender fires a `DepsgraphUpdate` on the `Material` ID with `is_updated_shading = True`. No `Object` updates, no `Mesh` updates.
2. Cycles' `sync_recalc` enters the `ID_MA` branch, looks up the existing `Shader *` in `shader_map`, and rebuilds only that shader's node graph.
3. `Scene::need_reset` is set, but `GeometryManager::need_update` is not — the BVH is untouched.
4. The device-update step pushes the rebuilt shader's data to the device's shader buffer. Geometry buffers, BVH buffers, light buffers are skipped.

For Astroray, the equivalent is: the Phase-B-split `uploadMaterials()` writes only the materials' GPU records (`GMaterial` device-side, the `Material *` host-side closure graph). `uploadGeometry()` is not called. The Renderer's primary buffer accumulator must reset (the image is now stale) but it does not reset the BVH.

Concrete addon-side mapping (Phase C):

```python
for upd in depsgraph.updates:
    if isinstance(upd.id, bpy.types.Material) and upd.is_updated_shading:
        material_id = self._material_map[upd.id.name]
        new_material = self._convert_material(upd.id)         # existing helper
        renderer.update_material(material_id, new_material)   # NEW binding
        accumulation_dirty = True
```

The `update_material(material_id, ...)` binding is one of the Phase-B additions to [module/blender_module.cpp](../../module/blender_module.cpp).

---

## 6. World / HDRI change handling

pkg63 ([pkg63-world-hdri-parity.md](../packages/pkg63-world-hdri-parity.md)) is in flight. It rewrites `setup_world` to handle Mapping XYZ rotation, color tint composition, color-via-Mix node trees, and (critically for cost) a CDF-built MIS importance sampler.

Two interaction points with pkg56:

1. **The MIS CDF is expensive to rebuild.** Cycles caches it on `Background` and rebuilds only when the env image, strength, or rotation changes (`world_recalc` flag — `sync.h:208`). pkg56 needs to inherit that discipline: `World` depsgraph events dispatch to `uploadEnvironment()` only, and `uploadEnvironment()` itself decides whether the CDF needs rebuild (image/strength/rotation changed) or whether only a cheap state push is required (e.g. just background colour tint). Without that, every world-tint slider drag pays the CDF cost.

2. **Soft dependency, not blocking.** pkg56 Phase A (instrumentation) and Phase B (split-uploader) can land before pkg63. Phase C (depsgraph-driven dispatch) depends on pkg63's `setup_world` rewrite for the env-state-change predicate. If pkg63 lands first, Phase C wires in trivially. If pkg56 ships first, Phase C ships with a coarser env predicate ("any World update → full env re-upload") and gets refined when pkg63 lands.

We mark pkg63 as a *soft* dependency on the package spec.

---

## 7. Recommended migration plan

The work decomposes into three phases, each landable as its own PR. Phase A is measurement only — no behaviour change. Phase B is a refactor with no observable diff at the API surface. Phase C is the actual incremental dispatch.

### Phase A — Instrument the existing upload path (1 week, ~15 h)

**Goal:** measure the per-component cost of `_sync_viewport_scene` on a representative scene (Cornell box + 100k-tri Suzanne instance + HDRI). Replace the §1 estimates with real numbers and use them as the baseline for Phase B/C acceptance.

**Deliverables:**
- Optional `ASTRORAY_VIEWPORT_PROFILE=1` env var that wraps each block in [`_sync_viewport_scene`](../../blender_addon/__init__.py:802) and the C++ upload calls in `module/blender_module.cpp` with monotonic-clock timers and prints a per-component breakdown to the console on every sync.
- One scripted benchmark scene under `tests/scenes/viewport_sync_bench.py` reproducible without GPU hardware (CPU build is enough for the timing test; the upload bottleneck is in pybind11 + `convert_objects`, not CUDA).
- A short numbers table appended to this research note in a follow-up commit. Phase B must beat those numbers on the no-change-frame.

**Acceptance gate:** the table exists; the no-change-frame total is the published baseline; reviewer can reproduce the measurement on their box.

**No public API changes.** No changes to the upload path itself. Pure timing.

### Phase B — Split `uploadScene()` into per-component uploaders (2 weeks, ~30 h)

**Goal:** at the API level, the renderer can be told to update geometry, materials, lights, and environment independently. The full-rebuild path is preserved as a default for compatibility and final render.

**Deliverables:**
- New C++ APIs in [module/blender_module.cpp](../../module/blender_module.cpp):
  - `Renderer::uploadGeometry(...)` — meshes, triangles, UV layers, BVH build, BVH device upload.
  - `Renderer::uploadMaterials(...)` — material closure graphs, GPU material payloads, spectral profiles.
  - `Renderer::uploadLights(...)` — area/point/sun lights.
  - `Renderer::uploadEnvironment(...)` — env atlas, world tint, (post-pkg63) MIS CDF.
  - `Renderer::update_material(int material_id, ...)` — single-material in-place update (most common case).
  - `Renderer::update_object_transform(int object_id, mat4)` — single-object transform (preps for two-level BVH future).
- The existing `uploadScene` (or its addon-side equivalent in `_sync_viewport_scene`) is re-implemented to call the four split paths in order. **Behaviour is unchanged** at this phase — every full sync still pays the full cost. The split is purely about giving Phase C surface to dispatch into.
- pybind11 bindings exposed under stable names so the addon can call them.

**Acceptance gate:** every existing test passes; viewport benchmark from Phase A is unchanged ±5% (we paid no incremental cost to refactor); the four uploaders can be called in any order without leaving the renderer in a broken state (test: clear, uploadMaterials only, uploadGeometry only — render returns a black image with materials defined but no geometry, not a crash).

### Phase C — Depsgraph-driven dispatch in the addon (2–3 weeks, ~40 h)

**Goal:** `view_update` reads `depsgraph.updates` and dispatches only the affected uploaders. Idle frames cost ~0; material-only edits skip geometry; transform-only edits (single-level BVH limitation noted) still rebuild BVH today but skip materials/lights/env.

**Deliverables:**
- A new `_apply_depsgraph_updates(self, renderer, depsgraph, settings)` method in [blender_addon/__init__.py](../../blender_addon/__init__.py) that replaces the unconditional [`_sync_viewport_scene`](../../blender_addon/__init__.py:802) call inside `view_update`. The full-sync path is preserved as a fallback for the very first `view_update` and for the case where the depsgraph delivered no updates but the renderer is fresh (no scene loaded yet).
- Per-update-type dispatch table mirroring §3.2:
  - `Object` + transform-only → `update_object_transform` (Phase B API). Falls back to `uploadGeometry` until two-level BVH lands.
  - `Object` + geometry → `uploadGeometry` for the affected mesh datablock + all object instances of it.
  - `Material` / `NodeTree` → `update_material` for the affected material id.
  - `Image` → texture cache invalidation + targeted re-upload.
  - `World` → `uploadEnvironment` (post-pkg63 it's CDF-aware).
  - `Light` → `uploadLights`.
  - `Scene` / frame change → reset accumulation only.
- Accumulation reset semantics: any update that changes the image must reset the progressive accumulator (Cycles does this via `Scene::need_reset`). pkg52's `_reset_viewport_accumulation` is the existing hook.
- A fallback "I don't recognise this update, do a full sync" path so unhandled cases (skin modifier, particle system, grease pencil — explicit non-goals) degrade gracefully instead of silently rendering stale data.

**Acceptance gate:**
- Idle-frame cost (no user input, no animation) ≤ 5 ms in the Phase A benchmark scene.
- Material-only slider drag re-render budget ≤ 30% of the Phase A baseline.
- Transform-only object drag re-render budget ≤ 50% of the Phase A baseline (limited by single-level BVH; bigger wins land when refit lands).
- All existing viewport tests pass; new `test_depsgraph_dispatch.py` covers the dispatch table with stubbed Blender API.
- A regression test that proves a Material edit on object A does not re-upload Mesh B (assert `uploadGeometry` is not called via a spy).

---

## 8. Risks & open questions

1. **Thread-safety of the persistent renderer.** pkg52's persistent `Renderer` was only ever touched from the Blender main thread. Phase C does the same. But CUDA upload calls run synchronously inside `view_update`, blocking the UI thread. If we ever move uploads off-thread (we should not in pkg56), we need an explicit lock around the renderer. Recommendation: keep all renderer mutation single-threaded; document this explicitly in the binding.

2. **Frame-budget constraints in viewport mode.** Blender's compositor and other engines target ~16 ms for a 60 Hz responsive viewport. Astroray's persistent-renderer + 1-spp chunk model already exceeds that on modest scenes; pkg56 makes the *sync* fast, not the *render*. Acceptance gates above are about the sync cost, not render cost. Render-budget improvement is pkg55 territory.

3. **Python GIL implications.** Every binding call from the addon holds the GIL by default. `convert_objects` walking 100k tris in Python is GIL-bound; we cannot parallelise it without dropping the GIL inside pybind11 (`py::call_guard<py::gil_scoped_release>`). For pkg56 Phase B/C, the right move is: drop the GIL inside `uploadGeometry` (long-running C++/CUDA work), keep it held in `update_material` (short, no benefit). This is a one-line annotation per binding.

4. **Image reload semantics.** `bpy.types.Image` updates fire on colorspace change, packed-image edits, and external file reload. The current addon caches by `image.name` only; a same-name external-file reload may not invalidate. pkg56 Phase C should key the texture cache on `(image.name, image.size, image.depth, image.colorspace_settings.name, last_reload_counter)` or similar. Open question: does the depsgraph reliably fire `is_updated_shading` on every external reload? Needs confirmation in Phase A.

5. **Order of updates within one `depsgraph.updates` iteration.** Blender does not document a stable ordering. If a Material update and an Object update both arrive in the same iteration, order matters (uploadMaterials first, then geometry that references the new material). Recommendation: collect all updates into typed buckets, dispatch in a fixed order (env → materials → lights → geometry → transforms), don't trust iteration order.

6. **Final-render path is unaffected by design.** pkg56 changes only the viewport sync. `render(depsgraph)` continues to do a full upload — final render runs once, batching the cost is not worth the complexity. Keep the full-sync entry point public.

7. **BlendLuxCore's approach (architecture comparison only).** BlendLuxCore handles the same problem under GPL-3.0 with a tag-based exporter that maintains its own `Exporter` cache parallel to the depsgraph. We do not mirror it (license incompatible) and we do not need to — Cycles' approach under Apache-2.0 is the cleaner reference and lines up with what pkg52 already established. Mentioned for completeness only; no code or close-paraphrase porting from BlendLuxCore.

---

## 9. References

**Cycles (Apache-2.0, mirrorable):**
- `intern/cycles/blender/sync.h` — `BlenderSync` class declaration. Members `has_updates_` (line 224), `geometry_synced` (194), `world_recalc` (208), `shader_map` (191).
- `intern/cycles/blender/sync.cpp` — `tag_update()` (85–87), `sync_recalc()` (99–291), `sync_data()` (294–341, early-out at 301–303, flag clear at ~335).
- `intern/cycles/blender/object.cpp` — `sync_object()` transform/geometry split (226–254).
- `intern/cycles/blender/session.cpp` — `synchronize()` (1118–1189), `view_draw()` (1192–1265), `sync->sync_view` (1225), `scene->need_reset` (1177).
- `intern/cycles/scene/geometry.cpp` — refit-vs-rebuild policy (274–280); `update_kernel_features` flagging all geometry for rebuild on layout change.

**Blender depsgraph public API:**
- `source/blender/depsgraph/DEG_depsgraph_query.h` — `DEG_iterator_ids_begin`, `DEG_id_type_updated`, `DEG_get_evaluated_id`. Stable C API, used by Cycles.
- `bpy.types.Depsgraph.updates` and `bpy.types.DepsgraphUpdate` (`id`, `is_updated_transform`, `is_updated_geometry`, `is_updated_shading`) — Python wrapper around the same flags. Reference: Blender 4.x Python API docs (`docs.blender.org/api/current/bpy.types.DepsgraphUpdate.html`).

**BlendLuxCore (GPL-3.0, architecture reference only — DO NOT MIRROR):**
- Repository: `https://github.com/LuxCoreRender/BlendLuxCore`, paths `engine/__init__.py` and `export/`. Examined only at the architectural level (tag-based per-Exporter cache, similar dispatch-on-update structure). No code or close paraphrase ported.

**Astroray code touched:**
- [blender_addon/__init__.py](../../blender_addon/__init__.py) — `_sync_viewport_scene` (line 802), `view_update` (894), `view_draw` (921), pkg52 persistent state (526–538).
- [module/blender_module.cpp](../../module/blender_module.cpp) — `PyRenderer::clear` (1074), `uploadScene` call site (715), pybind11 bindings (1128+).
- [pkg52-persistent-viewport-session.md](../packages/pkg52-persistent-viewport-session.md) — the persistent-renderer foundation pkg56 builds on.
- [pkg63-world-hdri-parity.md](../packages/pkg63-world-hdri-parity.md) — soft dependency for env-state-change predicate.

**License compatibility:**
- Apache-2.0 → MIT: compatible (Apache-2.0 patent-grant clause is preserved when integrated into MIT codebases per standard re-licensing practice; per-file headers retain the Apache notice).
- GPL-3.0 → MIT: incompatible, BlendLuxCore is reference-only.
- Blender Python API (GPL): consuming the documented Python API from a Python addon is the normal extension contract, not a derivative work concern.
