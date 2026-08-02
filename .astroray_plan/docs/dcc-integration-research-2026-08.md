# DCC integration architecture research (2026-08-03)

**Prepared by:** architect, for the Integration Milestone (owner directive
2026-08-03). Feeds `pkg177-dcc-integration-architecture-eval.md`; grounds
`pkg175` (dev loop) and `pkg176` (Blender-native steering wheel).

**Question:** Astroray must integrate rigorously into Blender first, and the
owner wants the integration story GENERALIZED — Blender is the first target,
not the only one. What are the real architecture routes other engines use to
integrate into many DCCs, and which serves the "Blender's native Cycles-style
settings are the steering wheel" goal?

---

## 1. The three real routes (as practiced by shipping renderers)

### Route 1 — Native per-DCC plugin (Blender `bpy.types.RenderEngine`)

What Astroray does today, and what Cycles itself is inside Blender. The
addon subclasses `RenderEngine` (`bl_idname = "CUSTOM_RAYTRACER"`), walks
`bpy` data (depsgraph, node trees, light/camera/world datablocks) and feeds
the engine through pybind11 bindings.

- **Every serious commercial renderer still ships these** for its tier-1
  hosts: Arnold (MtoA/HtoA/C4DtoA + `kick` standalone), V-Ray (per-host
  plugins on a shared AppSDK core), RenderMan (RfM, RfH, RfB), Octane,
  Redshift. The native plugin is where deep host-fidelity lives.
- **Decisive property for the steering-wheel goal:** a native `RenderEngine`
  can read Blender's OWN property groups — `scene.cycles.*`, the Cycles
  panels (an addon can re-register Cycles' panel classes for its own
  `bl_idname` via each panel's `COMPAT_ENGINES` set, the standard trick),
  native world/material node trees, `scene.render.*`. No other route sees
  the Cycles-native surface at this fidelity, because the others go through
  an interchange format that erases it.
- Cost: one integration per DCC, each a full re-walk of that DCC's data
  model. Fine while the DCC count is 1.

### Route 2 — Renderer-agnostic session/C-API core + thin per-DCC adapters

The V-Ray AppSDK / Arnold-SDK shape: the renderer exposes one
scene-description + render-session API (create session, push
geometry/materials/lights/camera, render, pull AOVs, incremental updates),
and each DCC plugin is a thin translator onto that API. Cycles itself is
structured this way internally: `blender/` (host glue) vs `scene/` +
`session/` (host-agnostic), which is exactly what let hdCycles and Cycles
standalone exist without touching the Blender layer.

- **Astroray status:** we are *accidentally close*. The pybind11 module
  already IS a session API (add_triangles_bulk, materials, lights, camera,
  render, AOVs, incremental TLAS refit from pkg114/pkg116). What is missing
  is the discipline line: today's `blender_addon/__init__.py` mixes
  bpy-walking, translation policy, and engine-session management in one
  5k-line file. pkg116 already split exporter/caches out; the remaining
  work is a boundary, not a framework.
- This route is not an alternative to Route 1 — it is what makes Route 1
  (and 3) cheap to multiply. It only pays off if the boundary is enforced
  where a second consumer could actually attach.

### Route 3 — USD/Hydra render delegate (`hdAstroray`)

Write one Hydra delegate (`HdRenderDelegate` subclass); every Hydra host —
usdview, Houdini/Solaris, Katana, Maya (maya-usd), Omniverse, and Blender
itself — can then select the renderer. This is the industry's current
multi-DCC answer: hdPrman (RenderMan), Arnold, V-Ray, Karma and 10+ other
delegates exist ([Foundry Katana delegate docs](https://learn.foundry.com/katana/Content/ug/using_hydra_viewer/hydra-render-delegates.html),
[OpenUSD third-party plugins](https://openusd.org/release/plugins.html)).

- **Blender supports this natively since 4.0:** addons subclass
  [`bpy.types.HydraRenderEngine`](https://docs.blender.org/api/current/bpy.types.HydraRenderEngine.html)
  (introduced with the Storm addon,
  [blender/blender#104712](https://projects.blender.org/blender/blender/pulls/104712),
  [design #100892](https://projects.blender.org/blender/blender/issues/100892)),
  set `bl_delegate_id`, and Blender does the scene→USD translation in C++
  (fast) with materials exported via **MaterialX** (`bl_use_materialx`,
  `export_mtlx()`).
- **The catch, and it is load-bearing for us:** the Hydra path means
  Blender translates materials/settings into USD/MaterialX FIRST, and the
  delegate sees only that. Cycles-native node trees and `scene.cycles`
  settings — the exact steering wheel the owner wants — are flattened or
  dropped at that boundary. Even Blender's own Cycles ships its Hydra
  delegate ([hdCycles](https://github.com/alex-v-dev/hdcycles),
  [T96731](https://developer.blender.org/T96731)) as
  experimental/unstable and does NOT use it inside Blender — inside
  Blender, Cycles stays a native engine. That is the strongest possible
  precedent: the engine we are mimicking chose Route 1 for Blender and
  Route 3 only for *other* hosts.
- Cost side: a delegate is a substantial C++ surface (HdRenderDelegate,
  render passes/buffers, material network → engine materials via
  MaterialX/UsdPreviewSurface, change tracking), plus a USD build
  dependency on a MinGW/CUDA toolchain that already has ABI footguns
  (memory: `mingw_large_struct_byval`, OpenMP constraints). And our
  spectral/astro differentiators (Kerr objects, spectral options) have no
  MaterialX vocabulary — they'd need custom schemas anyway.

## 2. How this maps onto the owner's stated goal

The directive is explicit: *"the purpose of mimicking Cycles was to be able
to use as much of the existing options and settings in Blender as the
steering wheel."* That goal is **only fully reachable on Route 1** — it is
precisely the Cycles-native surface (`scene.cycles` sampling/light-path
panels, native Principled/world nodes) that Routes 2/3's interchange layers
abstract away. Route 3 optimizes for host COUNT at the price of host
FIDELITY; today we need fidelity in exactly one host.

Route 2 is not a competitor but insurance: keeping the bpy-walking layer
thin over the existing pybind session surface means a future `hdAstroray`
or a Houdini adapter attaches to the same core the Blender addon uses,
the way hdCycles attaches to Cycles' session layer. The cheap version of
Route 2 is a refactoring discipline (module boundary + "no bpy imports
below this line"), not a new C API — the simplicity tax says don't build
the C API until a second consumer exists.

## 3. Recommendation (architect, for owner ratification in pkg177)

1. **Now:** Route 1, done rigorously — map Blender's native render
   properties, Cycles panels (via `COMPAT_ENGINES` re-registration where
   sane), and native node trees onto the engine; retire the ground-up
   custom UI except for genuinely Astroray-only features (spectral, GR),
   which stay in a small "Astroray" panel. This is `pkg176`.
2. **Alongside, structural:** enforce the session boundary inside the addon
   (bpy-facing translator vs engine-session driver) as pkg176 refactors
   touch code — Route 2 as discipline, zero new framework. Recorded as a
   pkg176 design rule, not a separate package.
3. **Later, evaluated not assumed:** `hdAstroray` as the second-DCC vehicle
   IF/WHEN a second DCC matters (Houdini/Solaris being the realistic one
   for the astro-viz audience). pkg177 carries the decision record; no
   Hydra code is written before the owner picks a second host.

Blender 5.x context checked: extensions platform is the 5.x distribution
mechanism ([Blender 2026 roadmap](https://www.blender.org/development/projects-to-look-forward-to-in-2026/),
[5.1 release](https://www.blender.org/download/releases/5-1/) — Python 3.13
/ VFX Platform 2026); external render engine API improvements are on the
2026 investigation list; 5.0 removed some UI panel classes that render
addons re-registered (compat notes:
[developer.blender.org release compat index](https://developer.blender.org/docs/release_notes/compatibility/)) —
pkg176 must pin against Blender 5.1 as installed locally and keep the panel
re-registration list explicit so 5.x churn fails loudly.

## Sources

- https://docs.blender.org/api/current/bpy.types.HydraRenderEngine.html
- https://projects.blender.org/blender/blender/pulls/104712
- https://projects.blender.org/blender/blender/issues/100892
- https://developer.blender.org/T96731
- https://github.com/alex-v-dev/hdcycles
- https://openusd.org/release/plugins.html
- https://learn.foundry.com/katana/Content/ug/using_hydra_viewer/hydra-render-delegates.html
- https://www.blender.org/development/projects-to-look-forward-to-in-2026/
- https://www.blender.org/download/releases/5-1/
- https://developer.blender.org/docs/release_notes/compatibility/
