# DCC-integration architecture — DECISION document (2026-08-07)

**Package:** pkg177 (`.astroray_plan/packages/pkg177-dcc-integration-architecture-eval.md`)
**Prepared by:** architect (Integration Milestone; owner directive 2026-08-03)
**Grounds:** the research note `.astroray_plan/docs/dcc-integration-research-2026-08.md`
(the three-routes survey). This document deepens that survey into a decision:
verified 2026 facts, the real tradeoff axes populated, falsifiable claims with
stated mechanisms, an explicit architect recommendation, and the near-term
hard rules pkg176 must respect.

**Status of the decision itself:** Owner ratification is PENDING (see §7). This
was written in an unattended session and cannot ratify on the owner's behalf.

---

## 0. TL;DR

One route is clearly right *for the milestone we are actually in*, so this
document does not manufacture a balanced N-option ballot (per
`design_no_forced_options`). The routes are not competitors; they are a
sequence:

- **Route 1 (native Blender `RenderEngine`) is the charter for now** — it is
  the ONLY route that reaches the owner's stated goal ("use Blender's own
  Cycles-shaped settings as the steering wheel"), because every other route
  reaches multi-host reach by inserting an interchange layer (USD/MaterialX)
  that provably erases the Cycles-native surface. This is pkg176.
- **Route 2 (session-boundary discipline) is not an alternative — it is the
  cheap insurance that makes Route 1 and Route 3 multipliable.** It is a
  refactoring discipline inside the addon, not a new framework, and costs
  essentially nothing to hold now. This is a pkg176 design rule (see §6).
- **Route 3 (USD/Hydra `hdAstroray` delegate) is a LATER, EVENT-TRIGGERED
  decision, not a now-decision.** It buys host *count* at the cost of host
  *fidelity* and a heavy USD dependency our MinGW/CUDA toolchain does not want
  yet. It is not written until a real second-host user exists (see §7 trigger).

The research note's lean (Route 1 native + Route 2 discipline, Route 3 deferred)
**still holds after verifying against current 2026 releases.** If anything the
2026 facts strengthen it: hdCycles — the closest precedent — is still
experimental in 2026 and still cannot round-trip a native material graph (§4).

---

## 1. The decision frame

The owner directive is not "integrate into many DCCs." It is "integrate into
Blender *rigorously first*, and *generalize the story* so Blender is the first
target, not the only one." Those are two different obligations:

1. **A now-obligation:** make Blender's native controls drive the engine (the
   steering-wheel goal). Fidelity in exactly one host.
2. **A don't-paint-into-a-corner obligation:** make sure the now-work does not
   foreclose a cheap second host later.

The mistake to avoid is collapsing #2 into "therefore build the multi-host
route now." The multi-host route (Hydra) actively *defeats* obligation #1 (it
erases the steering wheel), so building it now would trade away the thing the
owner explicitly asked for to buy reach for a user who does not yet exist.

---

## 2. Verified current facts (2026)

Facts checked against current releases on 2026-08-07 (sources in §8):

- **Blender 5.1.2** released 2026-05-19 (Python 3.13 / VFX Platform 2026 line).
  Blender hosts Hydra render delegates natively via
  `bpy.types.HydraRenderEngine`: an addon sets `bl_delegate_id` (the Hydra
  plugin name, e.g. `"HdCustomRendererPlugin"`) and optionally
  `bl_use_materialx = True`; Blender does the scene→USD translation in C++ and
  exports materials to a MaterialX nodegraph that is translated to USD shaders
  for the delegate. This is stable API, present since 4.0.
- **OpenUSD v25.11** is the current release. Hydra 2.0 (`UsdImagingSceneIndex`)
  is now the *default* imaging code path; the legacy `.sdf` text format is
  deprecated. **MaterialX 1.39.3** is the default MaterialX in USD 25.05+.
  These are large, fast-moving native dependencies.
- **hdCycles (the direct precedent) is still experimental in 2026.** Active
  work in 2026 is still *build plumbing* — e.g. PR #158533 "Fixing hdCycles
  build problems when using USD version lower than v25.11", and a WIP branch
  for "hdCycles for Houdini 21" that reports "some instabilities with the
  actual delegate." Cycles inside Blender remains a **native** engine; the
  Hydra delegate targets *other* hosts (usdview, Omniverse, Houdini) and is
  not how Cycles renders inside Blender.
- **hdCycles's documented material limitation is the load-bearing fact for
  us:** it "expects a flattened Cycles Material graph, with no groups or
  reroute nodes, and does not use the Material Output node, instead favoring
  USD/Hydra material binding inputs." Light node networks are "currently
  unsupported via UsdLux," pending a Pixar proposal. This is not a Cycles bug;
  it is what the USD/Hydra material boundary *is*.
- The multi-DCC delegate ecosystem is real and mature: hdPrman (RenderMan),
  Arnold, V-Ray, Karma, and 10+ third-party delegates ship against Hydra. So
  Route 3's reach claim is true — the question is only its *cost* to us and its
  *erasure* of the steering wheel, not whether it works.

---

## 3. The real tradeoff axes (populated)

Not an option ballot — these are the axes along which the routes actually
differ, each populated with the verified facts and a falsifiable claim where
one exists.

### Axis A — Host fidelity vs host count

- **Route 1:** fidelity = maximum in exactly one host; count = 1 per
  integration written. A native `RenderEngine` reads Blender's OWN property
  groups (`scene.cycles.*` sampling/light-path panels, native
  Principled/world/light node trees, `scene.render.*`) directly.
- **Route 3:** count = every Hydra host from one delegate (Houdini/Solaris,
  Katana, Maya-USD, usdview, Omniverse, Blender itself); fidelity = whatever
  survives USD + MaterialX 1.39.3.
- **The two are in direct tension, and today the milestone needs the fidelity
  end of the axis in one host.** Route 2 is what lets us move rightward on
  *count* later without re-paying the fidelity cost.

### Axis B — Where material/settings translation happens, and what it ERASES

This is the decisive axis. **Falsifiable claim:** *the Hydra route cannot
carry the Cycles-native steering wheel, by construction, not by immaturity.*

Mechanism, three concrete erasures — each independently disprovable by
exhibiting a counterexample:

1. **`scene.cycles.*` render/sampling/light-path settings have no USD
   transport.** On Route 3, Blender exports the *scene* to USD and the delegate
   receives USD prims + render settings tokens; the Cycles panel property
   group is a Blender-Python datablock, not a USD concept. To disprove: point
   to a USD schema that carries Cycles' adaptive-sampling / light-path-bounce /
   clamp-direct-indirect / filter-glossy semantics into a delegate. There is
   none — hosts pass renderer-specific settings as opaque per-delegate render
   settings, which is exactly Route 1's native read wearing a USD costume.
2. **Native material node graphs are flattened to MaterialX and lose
   structure.** hdCycles documents it plainly: it "expects a flattened Cycles
   Material graph, with no groups or reroute nodes, and does not use the
   Material Output node." So even the engine we are mimicking cannot round-trip
   its own node tree through the boundary. To disprove: show a native Blender
   shader graph surviving `export_mtlx()` → USD → delegate with groups/reroutes
   and Material-Output routing intact.
3. **Astroray's differentiators have no MaterialX vocabulary.** Spectral render
   options and GR/Kerr black-hole objects are not expressible in
   UsdPreviewSurface or MaterialX 1.39.3's standard nodes; they would require
   custom USD schemas + custom MaterialX node definitions authored and
   registered on both ends. To disprove: exhibit a stock MaterialX/USD schema
   for a spectral-dispersion or gravitational-lensing shader. There is none.

Net: Route 3's translation boundary erases precisely the surface the owner
named as the steering wheel. Route 1's "boundary" is a direct Python read of
that surface, so it erases nothing.

### Axis C — Dependency / toolchain weight on our MinGW/CUDA stack

- **Route 1 / Route 2:** zero new native dependencies. Route 2 is a Python
  module boundary. This is free on our toolchain.
- **Route 3:** adds a full **OpenUSD 25.11** build (+ MaterialX 1.39.3, TBB,
  boost-ish deps, Hydra) as a native link dependency of a new C++ delegate.
  Our toolchain already carries documented ABI footguns — MinGW large-struct
  by-value corruption (pass structs >32B by `const&`), MinGW libgomp deadlocks
  in Blender (addon `.pyd` must build `-DASTRORAY_DISABLE_OPENMP=ON`). Layering
  USD's ABI surface on top of that is a real, not hypothetical, cost; 2026's
  hdCycles work is *still* fighting USD-version build breakage (§2).

### Axis D — Maintenance surface per added DCC

- **Route 1:** each new DCC is a full re-walk of that DCC's data model —
  linear cost per host, but each is self-contained and only breaks when that
  one host's API churns. Blender 5.x already churns (5.0 removed panel classes
  that external engines re-register), so even the single Route-1 host has a
  live maintenance tax pkg176 handles by keeping the re-registered panel list
  explicit and fail-loud.
- **Route 3:** one delegate, but its maintenance is coupled to USD's fast
  release cadence (25.05 → 25.11 in one year, Hydra 1.0→2.0 scene-index
  default flip) AND to each host's delegate-loading quirks. "Write once" is
  real for reach but not for maintenance-free.

### Axis E — Which route the astro-viz audience actually needs

- The realistic second host for astro visualization is **Houdini/Solaris**
  (USD-native, the VFX/scientific-viz pipeline). That is a genuine Route-3
  argument — *if and when* a real Houdini user exists.
- **As of 2026-08-07 there is no identified second-host user.** The owner is
  verifying the engine *in Blender*. Building the multi-host route before the
  second-host user is speculative generality, and it would be paid for by
  giving up the steering-wheel fidelity the current user (the owner) needs.

### Axis F — What each route demands of the engine core NOW vs LATER

- **Route 1 now:** nothing new in the core — the pybind session surface
  already accepts geometry/materials/lights/camera/AOVs + incremental TLAS
  refit (pkg114/pkg116). pkg176 is addon-side plumbing.
- **Route 2 now:** nothing in the core — a discipline line in the addon.
- **Route 3 later:** a substantial new C++ surface (`HdRenderDelegate`, render
  passes/buffers, material-network → engine-material translation, change
  tracking) plus custom USD/MaterialX schemas for the spectral/GR
  differentiators. This is a multi-package effort, not a discipline.

---

## 4. Why the strongest evidence is hdCycles's own choice

The single most persuasive datum is a precedent, not an argument: **the engine
Astroray mimics chose Route 1 for Blender and Route 3 only for *other* hosts,
and its Route-3 delegate is still experimental in 2026.** Cycles is the
best-resourced open renderer with first-class USD engineering, and inside
Blender it stays a native engine because the Hydra boundary would cost it the
same native-surface fidelity it costs us. If hdCycles cannot even round-trip a
Cycles node graph through MaterialX in 2026, a solo project should not expect
to carry its spectral/GR differentiators through that boundary sooner.

This is falsifiable: if a future Blender release ships Cycles *as its in-Blender
Hydra delegate by default* (retiring the native path), the precedent flips and
Route 3 deserves re-evaluation. It has not, as of 5.1.2.

---

## 5. Architect recommendation

1. **NOW — Route 1, done rigorously (pkg176).** Drive Astroray from Blender's
   native render properties and Cycles panels (re-register via `COMPAT_ENGINES`
   where every control is honoured or gracefully degraded), native
   world/material/light node trees as the sole source; retire the ground-up
   custom UI down to one small "Astroray" panel for genuinely engine-only
   features (spectral, GR, device diagnostics). Pin to Blender 5.1 as installed
   locally; keep the re-registered panel list explicit so 5.x churn fails loud.
2. **ALONGSIDE — Route 2 as discipline, zero framework.** Enforce the
   session boundary inside the addon as pkg176 touches code (see §6 hard
   rules). This is the insurance that makes a future Houdini adapter or
   `hdAstroray` attach to the *same* pybind session core the Blender addon
   uses — the way hdCycles attaches to Cycles' `session/` layer. Do NOT build
   a standalone C API; the simplicity tax says not before a second consumer.
3. **LATER — Route 3 evaluated, not assumed.** `hdAstroray` is the second-DCC
   vehicle IF/WHEN a real second host matters (Houdini/Solaris the realistic
   one). No Hydra/USD code, no USD dependency, no C API before the trigger in
   §7 fires. pkg177 (this document) carries the decision record.

The recommendation is deliberately lopsided because the evidence is lopsided.
Per `design_no_forced_options`, padding it with a co-equal "or do Hydra now"
option would misrepresent the tradeoff: Hydra-now loses the owner's stated goal
for a user who does not exist. Stated plainly: **Route 1 + Route-2 discipline
is the answer; Route 3 is a future contingency, not a live alternative.**

---

## 6. Near-term consequences for pkg176 — HARD rules (session-boundary discipline)

These are the *only* things the pkg176 addon refactor must not foreclose. They
are constraints, not API design (no speculative surface). Keep them to a
handful:

1. **No `bpy` below the translation line.** The engine-session driver (the code
   that calls the pybind surface: geometry/material/light/camera push, render,
   AOV pull, incremental refit) must not `import bpy` or touch `bpy` datablocks.
   All `bpy`/depsgraph walking lives above it, in a translator that emits
   plain, host-neutral Python data structures. A future Hydra delegate or
   Houdini adapter substitutes a different translator against the *same*
   session driver. (Enforceable mechanically: grep for `bpy` imports in the
   session-driver module in review.)

2. **The pybind session surface stays host-neutral — no Blender concepts leak
   into it.** Do not add engine/binding parameters named or shaped after
   `scene.cycles.*` or Blender datablocks. Native-setting *interpretation* (the
   pkg176 Stage-0 mapping table) is the translator's job; the session API
   receives already-neutral values (e.g. "max_bounces=8", not "a cycles
   light_path property group"). This keeps Route 2 real rather than nominal.

3. **The Stage-0 mapping table is the single source of translation policy, and
   it lives on the translator side.** Every native→engine mapping decision is
   recorded there, not scattered inline. A second host reads this table to know
   what Blender's steering wheel *meant*, then maps its own host's controls to
   the same neutral session values.

4. **Custom-UI retirement must not delete the neutral values, only the Blender
   duplication.** When Stage 4 removes custom PropertyGroups, the values they
   carried must still arrive at the session driver via the native-read
   translator — i.e. retirement collapses two input paths into one *above* the
   boundary, never removes a session capability below it.

5. **Do not build a standalone C API or any second-consumer framework in
   pkg176.** The discipline is a module boundary and a naming rule, nothing
   more. Any actual second-host adapter is its own package, filed only after
   the §7 trigger. (Simplicity tax; explicit non-goal.)

If pkg176 honours these five, Route 3 later costs "write a delegate + custom
schemas," not "re-architect the addon." If it violates rule 1 or 2, a future
delegate has to reach through Blender-shaped code and the insurance is void.

---

## 7. Owner decision record

**Owner decision: PENDING owner ratification.** Written in an unattended
session; the architect cannot ratify on the owner's behalf.

**Architect recommends:** Route 1 (native Blender `RenderEngine`) as the
milestone charter, with Route 2 (session-boundary discipline, §6) held as a
pkg176 design rule, and Route 3 (`hdAstroray` USD/Hydra delegate) deferred as
an event-triggered future contingency. See §5.

**Proposed revisit trigger (owner to confirm/amend):** re-open the Route-3
evaluation when the FIRST of these fires —

- a real, identified user needs Astroray in a second DCC (Houdini/Solaris the
  realistic one for the astro-viz audience); OR
- a paper/deliverable requires Solaris/Katana/usdview renders Blender cannot
  produce; OR
- Blender ships Cycles as its in-Blender Hydra delegate by default (the
  precedent flip in §4), signalling the native-engine API is being retired.

Until a trigger fires: no USD dependency, no delegate code, no standalone C
API. pkg176 proceeds on Route 1 + §6 discipline; this decision can only refine,
not reverse, work consistent with all three routes.

**No follow-up package is filed** by pkg177: the recommended path (Route 1 +
Route-2 discipline) needs no code beyond pkg176. A Route-3 package would be
filed only if the owner picks a second host now — which the architect
recommends against.

---

## 8. Sources (verified 2026-08-07)

- `bpy.types.HydraRenderEngine` — https://docs.blender.org/api/current/bpy.types.HydraRenderEngine.html
- Blender Hydra render engine design/PR — https://projects.blender.org/blender/blender/issues/100892 , https://projects.blender.org/blender/blender/pulls/104712
- MaterialX export for Hydra (Python property) — https://projects.blender.org/blender/blender/pulls/111219 , https://projects.blender.org/blender/blender/pulls/111765
- Cycles Hydra Render Delegate (hdCycles) status — https://developer.blender.org/T96731
- hdCycles USD<25.11 build fix (2026) — https://projects.blender.org/blender/blender/pulls/158533
- hdCycles for Houdini 21 WIP (2026) — https://projects.blender.org/blender/cycles/pulls/46
- OpenUSD v25.11 announcement (Hydra 2.0 default, .sdf deprecation) — https://aousd.org/blog/announcing-openusd-v25-11-key-features-and-improvements/
- MaterialX (1.39.3 default in USD 25.05+) — https://materialx.org/ , https://github.com/AcademySoftwareFoundation/MaterialX/blob/main/CHANGELOG.md
- Hydra delegate ecosystem (third-party plugins) — https://openusd.org/release/plugins.html , https://learn.foundry.com/katana/Content/ug/using_hydra_viewer/hydra-render-delegates.html
- Blender 5.1 release / 2026 roadmap — https://www.blender.org/download/releases/5-1/ , https://www.blender.org/development/projects-to-look-forward-to-in-2026/
- Blender release compatibility (panel-class removals) — https://developer.blender.org/docs/release_notes/compatibility/
