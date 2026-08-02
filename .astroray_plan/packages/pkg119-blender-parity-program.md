# pkg119 — Blender integration parity program (coverage matrix + differential harness + graceful degradation)

**Pillar:** 5 (Blender addon / integration)
**Track:** A (addon/Python-heavy; headless-Blender introspection is CPU; render legs need RTX — serialize GPU with other work per repo rule)
**Codex-paste-ready:** no (large, staged; headless-Blender API introspection + Cycles-oracle render legs + UI/log surface)
**Status:** Phase A done (PR #487, 2026-07-19 — v4 Final AST-scanned coverage matrix, helper-method reads included: 131 SUPPORTED / 23 APPROXIMATED / 370 DROPPED-SILENT / 0 UNKNOWN / 20 stale sockets of 524 socket-level features; reworked four times under adversarial review to kill fake-SUPPORTED / anti-flattering swings); Phases B+C open. **RE-SCOPED INTO THE INTEGRATION MILESTONE 2026-08-03 (owner directive):** this package is no longer a deferred parity side-program — Phases B (differential harness) and C (graceful degradation) are the milestone's VERIFICATION LAYER. Sequencing: Phase A's matrix feeds pkg176's Stage-0 mapping table now; Phase B dispatches once pkg175's dev loop exists (it is Phase B's runner substrate) and gates each pkg176 stage; Phase C lands with/behind pkg176 Stage 3 (its degradation policy is what makes pkg176's panel adoption honest). The spec body below is unchanged and remains the contract.
**Estimated effort:** M–L, phased (A: coverage matrix generator; B: differential harness; C: graceful-degradation policy)
**Depends on:** none hard — this package *builds the measurement system*, it does not fix the red cells it finds.
**Builds on / relates to:** pkg115 (adopted Blender shader-node textures — the translation layer this matrix audits), pkg57 (additive custom-node pattern + `convert_shader_node` dispatch), pkg89 (dedicated lights; its known GPU gaps are pre-classified red cells — see Context), pkg71 (Cycles-parity benchmark: paired Cycles/Astroray render legs + SSIM), pkg104 (`benchmarks/reference_bank/` — Cycles-as-oracle blessing + SSIM/ΔE metrics reused by Phase B).

---

## Goal

**Before:** Astroray's engine is near Cycles parity, but the *addon integration*
is measured only anecdotally. The owner's standing concern (2026-07-18): the
integration "seemed miles behind — shader nodes a mess, most settings still not
available," and no one can enumerate — let alone test — every Cycles feature they
rely on. The addon's translation layer (`blender_addon/__init__.py`:
`convert_node_material` → `convert_shader_node` → `_principled_shader_spec`,
`load_procedural_texture`, `convert_lights`, the camera/world handlers) dispatches
on `node.type` / `light.type` / property names, and anything it doesn't recognise
falls through to a neutral Disney grey or is silently ignored. There is no
inventory of what is covered, what is approximated, and what is dropped without a
trace. New Blender releases add nodes and properties that no one notices are
missing.

**After:** A regenerable, machine-readable **coverage matrix** classifies every
enumerable Blender rendering feature (shader nodes + their sockets/enums, and the
render-relevant properties on render settings / world / light / camera / material
data) as `SUPPORTED` / `APPROXIMATED` / `DROPPED-SILENT` / `UNKNOWN-CRASH`; a
**differential harness** renders each feature through both Cycles (oracle) and
`CUSTOM_RAYTRACER` and triages every visual failure into exactly one of
`NOT-IMPLEMENTED` / `TRANSLATION-BUG` / `INTENTIONAL-DIVERGENCE`; and a
**graceful-degradation policy** guarantees the addon never renders silently-wrong —
every unsupported input is either approximated-with-warning or
explicitly-reported-ignored, surfaced in the addon UI and logs. The matrix and
triage regenerate on demand (test-suite targets), so they track addon changes and
new Blender releases automatically. This package produces the *measurement system*;
each remaining red cell becomes a follow-up package candidate at round close.

---

## Context

The owner cannot think of, or hand-test, every Cycles feature they use — so
"parity" has to be *enumerated from Blender's own API*, not from memory. Three
things are missing and this package supplies all three: (1) an exhaustive,
self-updating inventory of what the addon actually translates; (2) an automated
oracle comparison (Cycles is the ground truth for everything both engines can
render); (3) a hard guarantee against the silent-wrong-render failure mode the
owner keeps hitting — a shader-node mess that renders grey Disney with no warning.

pkg115 already fought this failure mode by hand (the `id(node)` cache-aliasing bug
that silently bound the wrong texture to the wrong sphere — pkg115 finding 6) and
seeded the fix machinery: `_warn_shader_fallback` / `_shader_fallback_warnings`
already exist in the addon (`__init__.py:2981`) but are populated only for a
handful of BSDF fallbacks. Phase C generalises that accumulator into the policy.

**Owner decision (2026-07-18):** the strategy below was proposed by the lead
session and approved by the owner with **one amendment — the corpus / `.blend`-file
runner is CUT as overkill.** Combination coverage is instead provided by a small
curated set of COMPOSITE scenes in Phase B. This spec is filed from a direct owner
request, not a package finding.

---

## Reference

### Internal

- `blender_addon/__init__.py` — the translation layer this program audits:
  - `CustomRaytracerRenderEngine` (`:793`, `bl_idname = "CUSTOM_RAYTRACER"`) — the render leg.
  - `convert_node_material` (`:1843`) → `convert_shader_node` (`:3225`) → `_principled_shader_spec` (`:2938`) — surface-shader dispatch on `node.type` (BSDF_DIFFUSE/GLOSSY/GLASS/…, EMISSION, MIX_SHADER, ADD_SHADER).
  - `load_procedural_texture` (`:2713`), `_resolve_vector_input` (`:2520`) — texture/coordinate translation (pkg115).
  - `convert_lights` (`:3879`) — `light.type` POINT/SUN/AREA/SPOT → `add_point_light` / `add_*_light_dedicated` (pkg89).
  - Camera-datablock property extraction (`:1280-1288`: lens/sensor/shift/dof/aperture); world nodes (`:4556`, `world.use_nodes`).
  - `_warn_shader_fallback` / `_shader_fallback_warnings` (`:2981`) — the seed Phase C generalises.
- `benchmarks/reference_bank/` (pkg104) — Cycles-as-oracle blessing (`runner.py::_bless_via_cycles :184`) + metrics (`metrics/ssim.py::compute_ssim`, `delta_e_2000`, `phash`, `hue_spread`). Phase B reuses these, not a new metric stack.
- `benchmarks/cycles-parity/` (pkg71) — paired Cycles-CPU/CUDA + Astroray-CPU/GPU render legs, SSIM-vs-Cycles gate, subprocess-per-engine isolation. Phase B reuses the paired-still driver shape.
- `scripts/verify_pkg115_textures_blender.py`, `scripts/verify_pkg114_instancing_blender.py` — existing headless-Blender (`--background --factory-startup`) render-and-compare scripts; Phase B's per-feature scene generator follows this pattern.
- pkg115 spec (findings 1, 5, 6 — silent-drop and dedicated-light-energy red cells already known); pkg89 spec (Phase A/B done, GPU port explicitly deferred).

### External (read for understanding; no algorithms mirrored — this is tooling, not physics)

- Blender Python API: `bpy.types.ShaderNode` subclass hierarchy, `bpy.types.NodeSocket`, `RenderSettings`, `Light`, `Camera`, `World`, `Material` (docs.blender.org). Enumerated at runtime via `bpy.types.ShaderNode.__subclasses__()` and `bl_rna.properties`.
- Cycles is the parity oracle (Apache-2.0); its EEVEE-shared shader nodes define the feature surface. No Cycles *code* is ported here — Phase B calls Cycles as a black-box renderer.

---

## Specification

### Phase A — coverage matrix generator (the core deliverable)

A headless-Blender script (`blender --background --factory-startup --python …`)
that **introspects the full render-relevant Blender API surface and
cross-references it against the addon's actual translation layer**, emitting a
parity matrix.

**Enumerate (from Blender, at runtime — so it self-updates per Blender release):**
- Every `bpy.types.ShaderNode*` subclass, and for each: all input/output socket
  names + types, and all enum/bool/float properties (via `bl_rna.properties`).
- Render-relevant properties on `RenderSettings`, `World`, `Light` (per light
  `type`), `Camera` (datablock), and `Material` data. "Render-relevant" is defined
  by an explicit checked-in allow-list of property categories (sampling, film,
  light paths, camera intrinsics/DoF, world surface/lighting) so the matrix does
  not drown in UI-only or Cycles-CPU-tiling knobs — document the inclusion rule.

**Cross-reference against the addon** by inspecting the dispatch surface in
`blender_addon/__init__.py` / `exporter.py`: which `node.type` / `bl_idname` /
`light.type` / property names does the translation layer actually read and act on?
The generator does not guess — where static inspection is ambiguous, the cell is
`UNKNOWN-CRASH` until Phase B resolves it by rendering (see acceptance).

**Classify each feature into exactly one bucket:**
| Bucket | Meaning |
|---|---|
| `SUPPORTED` | Addon translates it to a distinct engine behaviour. |
| `APPROXIMATED` | Addon maps it to a nearest engine behaviour (already emits, or should emit, a fallback warning — links to Phase C). |
| `DROPPED-SILENT` | Addon ignores it with no warning and no distinct behaviour — the failure mode this program exists to kill. |
| `UNKNOWN-CRASH` | Feeding it to the addon raises / crashes, or classification is undetermined without a render. |

**Emit two artifacts** (regenerate on demand):
- Machine-readable: `test_results/blender_parity/coverage_matrix.json` (or
  `benchmarks/blender_parity/…` — pick one and document it), one row per feature
  with `{feature, category, socket/prop, bucket, addon_anchor, notes}`.
- Human-readable: a generated Markdown summary (counts per bucket, the full
  DROPPED-SILENT list foregrounded).

Wire the generator as a **test-suite target** (e.g.
`tests/test_blender_parity_matrix.py` invoking the headless script, skipped
cleanly when Blender is absent) so it tracks addon and Blender-version drift.

**Acceptance (Phase A):**
- [ ] Matrix covers 100% of enumerable `ShaderNode*` types + the allow-listed
      render-relevant settings (enumeration is exhaustive over
      `__subclasses__()`, not a hand-maintained list).
- [ ] Zero features remain classified `UNKNOWN-CRASH` in the final artifact
      (each is resolved to one of the other three buckets — `UNKNOWN-CRASH`
      resolution may hand off to a Phase-B render probe).
- [ ] Machine-readable + human-readable artifacts checked into `test_results/`
      or `docs/`; regeneration target runs green (or skips) in the suite.

### Phase B — differential render harness vs Cycles as oracle

For **each matrix feature** and a **small curated set of COMPOSITE scenes**
(node combinations — e.g. mix-shader stacks, texture-driven roughness, bump +
normal — the owner-approved replacement for the cut corpus runner), the harness:

1. **Auto-generates a minimal scene** exercising exactly that feature (single
   object, one light, that node/property set), following the
   `scripts/verify_pkg115_textures_blender.py` headless pattern.
2. **Renders both engines headless**: the `CYCLES` leg (oracle) and the
   `CUSTOM_RAYTRACER` leg, reusing the pkg115/pkg71 paired-still machinery and the
   pkg104 reference-bank blessing/metric path — **do not** author a new renderer
   driver or a new metric stack.
3. **Compares** with the reference-bank metrics (`compute_ssim` + per-channel
   ratios / ΔE) against explicit thresholds.

**Triage every failure into exactly one bucket:**
| Bucket | Action |
|---|---|
| `NOT-IMPLEMENTED` | Feeds the roadmap; auto-listed as follow-up-package candidates. |
| `TRANSLATION-BUG` | Addon *tries* to translate but gets it wrong (the pkg115 `id(node)` class of bug) — fix. |
| `INTENTIONAL-DIVERGENCE` | Physically-justified difference (spectral-vs-RGB, energy model) — documented, not "fixed." |

**Acceptance (Phase B):**
- [ ] Harness runs the full matrix + composite scenes unattended (one command;
      subprocess-isolated per engine per feature per pkg71 discipline).
- [ ] A triage report is generated (machine + human readable), every failing
      feature in exactly one of the three buckets.
- [ ] **No crash on any feature** — a feature that crashes the addon is caught,
      recorded (and back-propagates to close its Phase-A `UNKNOWN-CRASH` cell),
      and the run continues (per pkg71 `skip_reason` discipline).

### Phase C — graceful-degradation policy

The addon must **never render silently-wrong on unsupported input.** Generalise
the existing `_warn_shader_fallback` / `_shader_fallback_warnings` accumulator
(`__init__.py:2981`) into a per-render degradation policy:

- **Nearest-approximation fallback** for every recognised-but-unsupported input
  (already the pattern for BSDF fallbacks; extend to textures, light params,
  camera/world settings surfaced by Phase A).
- **A per-render report** — "N features approximated / M ignored" — surfaced in
  the **addon UI** (a panel line and/or operator report) **and** the logs, listing
  the specific features and their disposition.
- Every `DROPPED-SILENT` cell from Phase A becomes one of: `SUPPORTED`,
  `APPROXIMATED`-with-warning, or explicitly-reported-ignored. **Zero silent drops
  remain.**

**Acceptance (Phase C):**
- [ ] Re-running the Phase A matrix after Phase C shows **zero `DROPPED-SILENT`
      cells** (each reclassified to supported / approximated-with-warning /
      reported-ignored).
- [ ] A render of a scene containing an unsupported feature produces a
      user-visible "N approximated / M ignored" report in both the addon UI and
      the logs (test asserts the report content for a synthetic
      unsupported-feature scene — no Blender GUI needed).
- [ ] No regression: existing addon tests
      (`tests/test_blender*.py`) stay green.

---

## Acceptance criteria (program-level)

- [ ] Phase A matrix: 100% of enumerable node types + allow-listed render
      settings covered; zero `UNKNOWN-CRASH` in the final artifact; artifacts
      checked in; regeneration is a suite target.
- [ ] Phase B harness: runs the full matrix + composites unattended; triage
      report generated; no crash on any feature.
- [ ] Phase C policy: zero `DROPPED-SILENT` cells remain; per-render
      approximated/ignored report visible in addon UI + logs; existing addon
      tests green.
- [ ] Each residual red cell (NOT-IMPLEMENTED / TRANSLATION-BUG) is enumerated in
      the Phase B triage report as a follow-up-package candidate for round close.

---

## Non-goals (hard stops)

- **No corpus / `.blend`-file runner.** Explicitly **cut by the owner
  (2026-07-18)** as overkill; the curated COMPOSITE scenes in Phase B are the
  approved replacement for combination coverage. Do not add a `.blend` corpus.
- **Not fixing every red cell.** This package builds the *measurement system*, not
  all the fixes. Each NOT-IMPLEMENTED / TRANSLATION-BUG cell becomes a follow-up
  package candidate prioritised at round close — not scope here. (Phase C's fallback
  work is bounded to *degradation*, not full feature implementation.)
- **No OSL / script nodes.** Out of scope for the matrix and the harness.
- **No new metric stack and no new render driver.** Reuse `benchmarks/reference_bank/`
  (pkg104) metrics and the pkg71/pkg115 paired-still machinery.
- **No engine/kernel changes.** This is addon + tooling. If a red cell needs a
  kernel fix, that is the follow-up package, not this one.

---

## Dependencies & sequencing notes

- **Independent of pkg55 Phase C** (wavefront) — no shared surface; they can run
  concurrently. This package is addon/CPU-heavy; only the Phase B render legs need
  GPU, and those **serialize with other GPU work** per the repo one-GPU rule.
- **Relates to pkg89 gaps.** pkg89's known deferrals are pre-classified red cells
  the matrix will surface, not defects to fix here: dedicated-light **GPU upload**
  (dedicated lights not uploaded to the GPU — pkg115 finding 1) and the
  **energy-scale** gap (uniform ~3× exposure vs Cycles — pkg115 findings 1 & 5).
  Phase B should tag these `INTENTIONAL-DIVERGENCE`-pending-or-`NOT-IMPLEMENTED`
  and reference pkg89, not attempt the GPU port.
- **Relates to pkg115 follow-ups** (per-object texture instancing for shared
  materials; the dedicated-light energy audit) — cross-reference, don't absorb.
- **Build/verify discipline:** headless-Blender legs need
  `-DASTRORAY_DISABLE_OPENMP=ON` (pkg115 finding 2: OpenMP deadlock inside Blender)
  and the correct F12 `samples` property (pkg115 finding 3), and must load the
  canonical `.pyd` (CLAUDE.md Build & Verification). Follow pkg115's verify script
  as the reference environment.

---

## Provenance

Filed on direct owner request in the 2026-07-18 session (not a package finding).
Owner's verbatim concern: the engine is near Cycles parity but the addon
integration "seemed miles behind — shader nodes a mess, most settings still not
available," and they can neither think of nor test every Cycles feature they rely
on. Strategy (coverage matrix + differential harness + graceful degradation)
proposed by the lead session and **owner-approved with one amendment: the corpus
runner is cut** (combination coverage moves to Phase B composite scenes).

---

## Progress

- [x] **Phase A — coverage matrix generator + regeneration target + checked-in artifacts.** (PR #487, 2026-07-19)
- [ ] Phase B — per-feature + composite differential harness; triage report.
- [ ] Phase C — graceful-degradation policy + per-render UI/log report; zero silent drops.

---

## Lessons

*(Fill in after the package is done.)*
