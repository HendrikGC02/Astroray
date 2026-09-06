# Blender Integration Parity Report — Camera, Scene Sync, Textures, Color Management

**Date:** 2026-05-30
**Author:** Claude (research + codebase audit)
**Scope:** Four owner questions about how Astroray's Blender addon compares to Cycles
and other third-party Blender render engines, with a verdict on current Astroray state
and concrete refactor recommendations.

**Method:** Repo audit (3 parallel Explore agents over `blender_addon/`, `include/`,
`.astroray_plan/`) + an adversarially-verified web-research pass (22 primary/secondary
sources, 25 claims verified 3-vote, 23 confirmed / 2 refuted). Sources cited inline.

---

## TL;DR verdict table

| Area | Astroray today | Blender/Cycles convention | Gap |
|---|---|---|---|
| **1. Camera frustum / viewport alignment** | Symptoms fixed (pkg100/101/102, merged). FOV now from `window_matrix`. | Derive frustum from camera datablock + inverted view matrix; branch on viewport context. | **Minor.** No parity-regression gate; bridge is hand-wired. Architecturally aligned now. |
| **2. Scene conversion / interactivity** | Two paths. Viewport = incremental depsgraph diff (pkg56 done). F12 = full re-export. | Incremental per-domain cache + Change bitflags keyed off `depsgraph.updates`. | **Moderate.** Per-triangle pybind11 marshalling dominates; no per-domain cache objects. This is the real perf bottleneck, not the sync *logic*. |
| **3. Textures / UVs / procedurals** | Engine-native: 8+ own procedural textures, own coord-space model. Addon adds 5 custom nodes. | Shared Blender shader node tree; `ShaderNodeTexCoord` spaces are Blender-core, inherited by all engines. | **Large & strategic.** Astroray reinvents what Cycles/EEVEE/RPR/LuxCore all share. |
| **4. Color management / compositor** | ✅ Outputs linear scene-referred; addon writes linear to Combined; Blender does view transform. Denoise + split passes registered. | Output linear, let Blender's display-space shader + compositor handle it (Cycles convention). | **Done.** Matches the canonical convention. (Your original goal is met.) |

---

## Question 1 — Camera frustum / Blender viewport alignment: **has it been fixed?**

### Verdict: PARTIALLY FIXED — symptoms resolved and merged; no parity guarantee.

**The diagnosis was correct.** The "recent analysis" you remember is
[addon-remediation-first-principles-plan-2026-05-16.md](.astroray_plan/docs/addon-remediation-first-principles-plan-2026-05-16.md),
which named this **Primitive P4 — "camera re-derived, not taken from Blender"**
(root cause RC-7, symptom BUG-08: "rendered output and viewport never line up").
The invariant it states is exactly right: *engine frustum ≡ Blender frustum.*

**Three surgical fixes landed in `main`:**

- **pkg101** ([PR #368](https://github.com/) — `pkg101-addon-viewport-camera-vfov-from-perspective-matrix.md`, Status: DONE):
  the addon was extracting vertical FOV from `rv3d.perspective_matrix[1][1]`, which is
  `window_matrix @ view_matrix` — so the FOV changed as the camera *orbited*
  (`cos(pitch)` etc. leaked in). That is precisely your "objects shrink, grow, flip and
  rotate differently from the camera" symptom. Now reads `rv3d.window_matrix[1][1]`
  (pure projection, rotation-invariant). Code: `blender_addon/__init__.py:1690-1717`.
- **pkg100** (PR #339/#341, Status: DONE): `.blend` importer camera intrinsics now
  threaded up the call chain instead of stashed as dynamic attributes.
- **pkg102** (PR #369, Status: DONE): DOF aperture unit bug — was producing ~45 mm blur
  at a 45 mm lens; now `aperture_radius = focal_length_m / (2·fstop)` per Cycles'
  `intern/cycles/blender/camera.cpp`. Code: `blender_addon/__init__.py:1930-1935`.

**The C++ frustum math itself was never wrong.** `include/raytracer.h:1840-1875`
implements a standard pinhole model with correct `shift_x/shift_y` film-offset support.
The bug was always in *what the addon passed in*.

### How Cycles / RPR / LuxCore do it (and what's still missing)

The cross-engine convention (verified 3-0):

- **Derive the frustum from the Blender camera datablock + the inverted view matrix.**
  RPR reads `camera.lens`, `sensor_fit`/`sensor_width`, `ortho_scale`, clip planes, and
  feeds them plus the inverted view matrix to backend setters (`set_focal_length`,
  `set_sensor_size`, `set_transform`) and lets the *backend* build the projection — it
  never derives its own frustum.
  ([RPR addon source](https://github.com/GPUOpen-LibrariesAndSDKs/RadeonProRenderBlenderAddon))
- **One camera-convert entry point that branches on viewport context.** BlendLuxCore's
  `convert(exporter, scene, depsgraph, context=None, ...)`: if `context` is present it's a
  viewport render and it dispatches on `context.region_data.view_perspective` into
  ORTHO / PERSP-free-nav / CAMERA-locked helpers; if `context=None` it's a final render
  off `scene.camera`.
  ([BlendLuxCore export/camera.py](https://github.com/LuxCoreRender/BlendLuxCore/blob/main/export/camera.py))

Astroray now matches the *spirit* of this. **What's still missing is a parity-regression
gate** — there is no automated test that renders a known scene and asserts the Astroray
frustum matches the Blender camera overlay across rotation, zoom, shift, and lens changes.
The fixes are tactical; nothing prevents a future edit to either side of the hand-wired
bridge from silently re-breaking alignment. **Recommendation:** add a property-based or
reference-image test that locks `(vfov, aspect, shift_x/y, focus, aperture)` parity.

---

## Question 2 — Scene conversion on every render: normal, or does Cycles have "magic"?

### Verdict: There is no magic. Cycles does exactly what pkg56 already built — incremental depsgraph diffing. Your viewport path already does this; the slowness is elsewhere.

**There are two paths in Astroray, and they behave very differently:**

- **F12 final render** (`render()` → `convert_scene()`, `blender_addon/__init__.py:889, 1735`):
  full re-export every time (`renderer.clear()` then re-convert materials/objects/lights/world).
  Zero caching. *This is intentional and correct* — a one-shot render doesn't benefit from
  caching. Cycles does the same.
- **Viewport / "Rendered" shading** (`view_update`/`view_draw`, lines 1522/1575):
  already **incremental** as of **pkg56 (all 3 phases done)** — persistent renderer,
  progressive sample accumulation, and `_apply_depsgraph_updates()` (line 1264) that
  buckets `depsgraph.updates` by domain and dispatches only the affected uploader
  (geometry / transform / materials / lights / world). Idle frames cost ≤5 ms.

**This is precisely the Cycles architecture.** Cycles' `BlenderSync::sync_recalc()` diffs
the depsgraph and only re-exports changed datablock IDs — there is no secret. The Blender
dev docs state the principle directly: *"the dependency graph only updates what was
dependent on the modified value and will not update anything which was not changed"*
([Blender depsgraph docs](https://developer.blender.org/docs/features/core/depsgraph/)).
The canonical `RenderEngine.py` example shows `view_update` iterating `depsgraph.updates`
and calling `depsgraph.id_type_updated('MATERIAL'/'OBJECT')`
([bpy.types.RenderEngine.py](https://github.com/dfelinto/blender/blob/master/doc/python_api/examples/bpy.types.RenderEngine.py)).
Your own [blender-depsgraph-sync-research.md](.astroray_plan/docs/blender-depsgraph-sync-research.md)
already documented this and pkg56 implemented it.

### So why does it still feel slow? Two real bottlenecks, both confirmed in-repo:

1. **Per-triangle pybind11 marshalling.** On a geometry change, `convert_objects()`
   (`__init__.py:3355-3579`) loops every loop-triangle in Python and calls
   `renderer.add_triangle(...)` once per triangle — ~150–400 ms for 100k tris just in
   call overhead (per the Phase-A benchmark in the sync research doc). **Fix:** batch the
   upload — build NumPy arrays and pass them in one `foreach_get`-style call, the way
   you already write pixels back with `foreach_set`. This is the single biggest win.
2. **BVH rebuild on transform-only edits.** Astroray's single-level BVH means moving an
   object rebuilds the whole BVH. Cycles/RPR/LuxCore use a **two-level BVH (TLAS/BLAS)** so
   a transform is a cheap top-level refit. This is already noted as a deferred limitation
   in pkg56 §4. **Fix:** two-level BVH → instance transforms become near-free.

### The proper architectural pattern other engines use (and Astroray should adopt)

Both LuxCore and RPR keep the `RenderEngine` subclass **thin** and put sync in a dedicated
**exporter with per-domain cache objects**:

- BlendLuxCore: `engine/` (the `RenderEngine` subclass) is separate from a top-level
  `export/` module. The engine holds an `Exporter` that owns `CameraCache`, `ObjectCache2`,
  `MaterialCache`, `VisibilityCache`, `WorldCache`, `StringCache`, plus a `node_cache`.
  `get_changes()` ORs `Change.OBJECT | Change.MATERIAL | ...` bitflags and `update()` applies
  only the diff.
  ([BlendLuxCore export/__init__.py](https://github.com/LuxCoreRender/BlendLuxCore/blob/master/export/__init__.py))
- RPR processes `depsgraph.updates` by datablock type in priority order
  (Scene → World → Material → Object → Collection → Light), delegating
  `view_update→sync_update`, `view_draw→draw`, `update→sync` to internal engine objects.

Astroray's `_apply_depsgraph_updates` does the dispatch but lacks the **persistent
per-domain cache objects with diff()/Change-flag** structure. Promoting your bucketing into
real cache classes would make the code match LuxCore's proven design and make
partial-update correctness easier to reason about.

**Honest caveat from the research:** incremental is *not universal* even in mature engines.
BlendLuxCore falls back to a **full session restart** for viewport resize and render-setting
changes (a documented memory-leak workaround), and Blender's depsgraph is **datablock-grained,
not per-property** (Blender issue #121019), so it over-updates. "Incremental" everywhere means
coarse-grained, not minimal-diff. Don't over-invest chasing per-property granularity Blender
itself doesn't provide.

---

## Question 3 — Textures / UVs / procedurals: should Astroray follow Blender instead of reinventing?

### Verdict: You are NOT misunderstanding. Astroray reinvents what every other engine inherits from Blender. This is the biggest strategic divergence.

**What Astroray does today:**

- Its own coordinate-space machinery: a `CoordMode` enum (UV/Object/World/Generated) and
  per-texture UV transforms baked in (`include/advanced_features.h:95-170`).
- Its **own** procedural texture library — Checker, Noise, Marble, Wood, Gradient, Wave,
  Magic, Voronoi, Musgrave, Brick — all hand-written
  (`include/advanced_features.h:145-450`).
- The addon adds 5 *custom* Astroray shader nodes (pkg57) and the `.blend` importer (pkg76)
  extracts only base color (procedural node graphs are explicitly out of scope).

**What Cycles, EEVEE, RPR, and LuxCore do (verified 3-0):**

Texture-coordinate spaces and the material model are **shared Blender shader-node-tree
constructs**, not per-engine inventions. The `Texture Coordinate` node (`ShaderNodeTexCoord`)
supplies **Generated** (0–1 over the undeformed bounding box), **Normal, UV, Object,
Camera, Window, Reflection** — and `ShaderNodeTexCoord` inherits from `ShaderNode`
(Blender-*core*, not Cycles-private). The Blender manual states EEVEE "uses the same shader
nodes as Cycles."
([Texture Coordinate node manual](https://docs.blender.org/manual/en/latest/render/shader_nodes/input/texture_coordinate.html),
[ShaderNodeTexCoord API](https://docs.blender.org/api/current/bpy.types.ShaderNodeTexCoord.html))

Every external engine **reads the same `material.node_tree`**, dispatches from
`ShaderNodeOutputMaterial`, and locates coordinate nodes (e.g. `ShaderNodeUVMap`) by
`bl_idname` — then *translates* them into its own backend. RPR does exactly this and adds
its *own* extension nodes **additively** on top of the shared tree, rather than replacing it.
([RPR addon source](https://github.com/GPUOpen-LibrariesAndSDKs/RadeonProRenderBlenderAddon))

**Important nuance (the one claim that split 2-1):** the space *definitions and interface*
are shared, but the *numerical evaluation* of each space still happens per-engine in the
kernel (e.g. Cycles `svm/tex_coord.h`, `NODE_TEXCO_CAMERA` uses `cam.worldtocamera`). So
"follow Blender" means: **inherit the node-tree interface and coordinate-space semantics,
evaluate them in your own kernel.** You don't avoid writing a Voronoi evaluator — but you
*do* stop inventing a private texture-coordinate model and a private node system, and you
gain every Blender procedural the user already knows how to wire.

### Recommendation (strategic, not a quick fix)

Pivot from "engine defines textures, Blender follows" to "**Blender's node tree is the
source of truth, Astroray translates it.**" Concretely:

1. Walk `material.node_tree` from `ShaderNodeOutputMaterial` (the RPR/LuxCore pattern).
2. Map Blender's standard texture/coordinate nodes (`ShaderNodeTexCoord`, `ShaderNodeUVMap`,
   `ShaderNodeTexNoise`, `ShaderNodeTexVoronoi`, `ShaderNodeMapping`, etc.) onto your existing
   kernel evaluators — you already *have* Voronoi/Musgrave/Noise, so this is wiring, not new
   math. Match Blender's parameterization so results agree.
3. Keep your 5 custom nodes as **additive extensions** (spectral/Sellmeier/IR-UV/NRC) — that's
   the sanctioned RPR pattern.
4. Treat anything not yet mapped as a graceful-degrade fallback (base color), which is what
   pkg76 already does.

This is the highest-leverage refactor for "feel like a normal Blender render engine,"
because procedural/texture authoring is where users spend the most node-editor time.

---

## Question 4 — Color management: was Blender-owned color management fully implemented? Does the compositor work?

### Verdict: YES — fully implemented and matches the canonical Cycles convention. Your original goal is met.

The package you remember was about **not double-processing color**. The current pipeline does
exactly the right thing:

- **Engine outputs linear scene-referred data.** No tonemapping; gamma is off by default
  (`applyGamma=false`). The path is spectral → XYZ → linear sRGB (D65) with only an exposure
  multiplier and finite-clamping (`include/raytracer.h:2925-2942`, `include/astroray/spectral.h`).
- **Addon hands linear float32 straight to Blender.** `write_pixels()`
  (`blender_addon/__init__.py:3785-3890`) copies the linear buffer into the `Combined` pass
  via `foreach_set`, with only a Y-flip — **no view transform applied.** Blender then applies
  AgX/Filmic/OCIO.
- **Compositor-ready passes are registered.** Denoise guide passes (albedo + normal, pkg69,
  PR #339) and split passes (`diffuse_direct/indirect`, `glossy_*`, `transmission_*`,
  `volume_*`, pkg62) feed Blender's compositor/Denoise node. Tests
  (`tests/test_blender_compositor_denoise_passes.py`) pass.

**This is verbatim the Cycles convention (verified 3-0):** Blender's color-management docs
and the canonical `RenderEngine.py` example show the engine emitting linear scene-referred
pixels and binding the **display-space shader** (`bind_display_space_shader(scene)` /
`unbind_display_space_shader`) so Blender applies the view transform; the comment in the
example reads *"Bind shader that converts from scene linear to display space."*
([bpy.types.RenderEngine.py](https://github.com/dfelinto/blender/blob/master/doc/python_api/examples/bpy.types.RenderEngine.py),
[RenderEngine API](https://docs.blender.org/api/current/bpy.types.RenderEngine.html))

**The compositor should "just work"** with the current setup, because you deliver
scene-referred linear data into named passes — which is exactly what the compositor expects to
operate on before the view transform. No double-processing.

### Two caveats worth knowing

1. **An agent initially flagged "color management NOT DONE."** That refers to an *in-test-harness*
   OpenColorIO ACES step (`metrics/color_pipeline.py`, pkg104 — used to compute ΔE2000 in a
   perceptual space for the reference-image bank). That is *benchmark infrastructure*, not the
   render path, and is unrelated to your goal. The render path is correct.
2. **LuxCore is the cautionary counter-example.** It does **not** follow the convention — it
   bakes its *own* imagepipeline tonemapper
   (`scene.camera.data.luxcore.imagepipeline.tonemapper`) into the buffer before Blender sees
   it, and even warns about conflicts with multiple render layers. So "all engines defer color
   to Blender" is false — Cycles defers, LuxCore does not. **Astroray is on the correct
   (Cycles) side of this line; keep it there.** Don't add an in-engine tonemapper.
   ([BlendLuxCore](https://github.com/LuxCoreRender/BlendLuxCore))
3. **Modern API drift:** the `bind_display_space_shader` pattern in the canonical example is the
   legacy GPU-draw path; Blender 4.x/5.x viewport color management has evolved
   (dev doc `features/gpu/viewports/color_management`). The *linear-scene-referred principle*
   holds, but if/when Astroray implements a true GPU `view_draw` viewport (vs. the current
   pixel-buffer approach), verify the current GPU-module API surface.

---

## Cross-cutting: what to learn from other Blender render-engine addons

Synthesized from BlendLuxCore, RPR, Malt, and Cycles (all primary-source verified):

1. **Read evaluated depsgraph data, never original `bpy.data`/DNA.** Blender evaluates a
   copy-on-write copy (modifiers/constraints applied); engines consume `depsgraph.scene_eval`
   / `depsgraph.object_instances` / `evaluated_get`. The interactive depsgraph comes from
   the Window+Workspace, the F12 one from the Render structure — same scene, two evaluations,
   no conflict.
   ([Blender depsgraph docs](https://developer.blender.org/docs/features/core/depsgraph/))
   *Action: audit Astroray's `convert_*` to confirm it reads evaluated meshes, not originals.*
   **(Audited 2026-05-30: CLEAN — `convert_objects`/`convert_lights` iterate
   `depsgraph.object_instances`, whose `.object` is already evaluated. `convert_lights`
   was fixed this round to iterate `object_instances` instead of `depsgraph.objects` so
   instanced lights render.)**
2. **Thin `RenderEngine` subclass + dedicated exporter/cache layer.** LuxCore `export/` +
   `Exporter`, RPR internal engine objects. *Action: promote `_apply_depsgraph_updates`
   bucketing into real per-domain cache classes with `diff()` + `Change` bitflags.*
3. **Decouple the engine core from Blender entirely.** Cycles builds standalone (its own XML
   scene API) and as a **Hydra render delegate** (runs in Usdview/Houdini/Omniverse) — the
   Blender addon is just an integration shim.
   ([Cycles repo](https://github.com/blender/cycles),
   [Cycles standalone](https://developer.blender.org/docs/features/cycles/standalone/))
   *Astroray already has this shape (C++/CUDA core + thin addon) — this validates the
   architecture. Consider a standalone scene-description entry point as a forcing function to
   keep the boundary clean.* **→ tracked as a future/milestone item in GitHub issue #398.**
4. **Write results via `begin_result()`/`end_result()` layer passes** — never a private image
   window. Astroray already does this. ✓
5. **Two-level BVH (TLAS/BLAS)** is the standard answer to "transforms shouldn't rebuild the
   accel structure." Single-level BVH is Astroray's current sync bottleneck for object motion.

---

## Prioritized recommendations

_Status as of 2026-05-30: specs written and items actioned this round (see annotations)._

1. **(High leverage, medium effort) Batch geometry upload.** Replace per-triangle
   `add_triangle()` with a single NumPy `foreach_get`→buffer→one pybind11 call. Biggest
   single viewport-responsiveness win; doesn't change architecture. **→ spec
   [pkg112](../packages/pkg112-batched-geometry-upload.md).**
2. **(High leverage, large effort, strategic) Consume Blender's shader node tree** for
   textures/UVs/procedurals instead of the private node/texture system. Map standard Blender
   texture & coordinate nodes onto your existing kernel evaluators; keep custom nodes additive.
   **→ spec [pkg115](../packages/pkg115-adopt-blender-shader-node-textures.md).**
3. **(Medium) Two-level BVH** so object transforms refit instead of rebuild — closes the
   pkg56 transform-only deferral. **→ spec [pkg114](../packages/pkg114-two-level-bvh-tlas-blas.md).**
4. **(Medium) Promote sync into a real exporter + per-domain caches with Change bitflags**
   (LuxCore pattern) for correctness and maintainability. **→ spec
   [pkg116](../packages/pkg116-exporter-cache-refactor.md).**
5. **(Low effort, closes Q1) Add a camera-frustum parity-regression test** locking
   vfov/aspect/shift/focus/aperture against the Blender camera overlay. **→ DONE 2026-05-30:
   `tests/test_addon_viewport_camera_vfov.py` extended with sensor_fit (H/V/AUTO), shift,
   aspect, and known-vfov parity tests (7 tests green).**
6. **Keep color management exactly as-is** (linear out, Blender does view transform). Do not
   add an in-engine tonemapper (the LuxCore mistake).

### Also actioned this round (rabbit holes)

- **Non-MESH geometry dropped** (curves/text/metaballs) → spec
  [pkg117](../packages/pkg117-nonmesh-geometry-to-mesh.md).
- **Instanced lights not rendered** → fixed in `convert_lights` (iterate `object_instances`);
  regression test `tests/test_addon_instanced_lights.py`.
- **Hydra/standalone engine-decoupling** → GitHub issue #398 (future/milestone).
- **GPU `view_draw` viewport color-management drift** → note added to
  [blender-depsgraph-sync-research.md](blender-depsgraph-sync-research.md) (future-work section).
- **Don't over-engineer incremental sync** (datablock-grained depsgraph) → baked into pkg116 as
  an explicit non-goal.

---

## Sources (primary unless noted)

- Blender `bpy.types.RenderEngine` canonical example —
  https://github.com/dfelinto/blender/blob/master/doc/python_api/examples/bpy.types.RenderEngine.py
- `bpy.types.RenderEngine` API — https://docs.blender.org/api/current/bpy.types.RenderEngine.html
- Blender Dependency Graph dev docs — https://developer.blender.org/docs/features/core/depsgraph/
- `bpy.types.Depsgraph` API — https://docs.blender.org/api/current/bpy.types.Depsgraph.html
- Texture Coordinate node manual —
  https://docs.blender.org/manual/en/latest/render/shader_nodes/input/texture_coordinate.html
- `ShaderNodeTexCoord` API — https://docs.blender.org/api/current/bpy.types.ShaderNodeTexCoord.html
- Cycles repo (standalone + Hydra delegate) — https://github.com/blender/cycles
- Cycles standalone dev docs — https://developer.blender.org/docs/features/cycles/standalone/
- BlendLuxCore exporter — https://github.com/LuxCoreRender/BlendLuxCore/blob/master/export/__init__.py
- BlendLuxCore camera — https://github.com/LuxCoreRender/BlendLuxCore/blob/main/export/camera.py
- BlendLuxCore viewport — https://github.com/LuxCoreRender/BlendLuxCore/blob/main/engine/viewport.py
- BlendLuxCore final — https://github.com/LuxCoreRender/BlendLuxCore/blob/master/engine/final.py
- Radeon ProRender Blender addon — https://github.com/GPUOpen-LibrariesAndSDKs/RadeonProRenderBlenderAddon
- Malt (BlenderMalt) — https://github.com/bnpr/Malt
- Legacy RenderEngine API wiki (archive) —
  https://archive.blender.org/wiki/2015/index.php/Dev:Source/Render/RenderEngineAPI/

**Two refuted claims** (excluded; verifier vote 1-2): a specific LuxCore final-render
`update_session(changes)` delta path, and a Malt geometry-only incremental-unload mechanism —
neither survived adversarial verification, so don't rely on those specifics.

**Repo cross-references:**
[addon-remediation-first-principles-plan-2026-05-16.md](.astroray_plan/docs/addon-remediation-first-principles-plan-2026-05-16.md),
[blender-depsgraph-sync-research.md](.astroray_plan/docs/blender-depsgraph-sync-research.md),
[blender-shader-nodes-research.md](.astroray_plan/docs/blender-shader-nodes-research.md),
pkg56 / pkg57 / pkg62 / pkg69 / pkg76 / pkg100 / pkg101 / pkg102 / pkg104.
