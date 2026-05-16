# pkg95 — Blender addon: re-connect dead UI wires + single Blender-native camera

**Pillar:** 5
**Track:** A (core quality / correctness — addon Python)
**Status:** open — Stage 2 / P3 + P4 of the addon first-principles plan (PR #300). **Depends on pkg94.**
**Estimated effort:** ~1.5–2 days; P3-a / P4 independent and parallelizable, P3-b gated on the P3-c probe
**Depends on:** **pkg94** (build-integrity guard — so every fix here is verifiable on a known-current module). Independent of pkg96 and of pkg55-B'.

---

## Goal

**Before:** A class of UI-presented features is wired to a dead path —
the control the UI shows as functional never reaches the engine, even
though the shipped binary fully supports the feature:

- **BUG-15 (P3-a):** the preview-render button constructs a
  `RenderEngine()` directly (`__init__.py:676`), which Blender forbids;
  the whole preview path dies with
  `TypeError: bpy_struct.__new__(struct): expected a single argument`
  before any node conversion runs. The class's own comment (L706–709)
  says they deliberately do not override `__init__` because Blender
  forbids constructing a `RenderEngine` directly — yet this code does.
- **BUG-13 wire (P3-b):** the IR/UV Response node's spectral profile is
  hard-disabled by `if False` at `__init__.py:1865`
  (`'profile': self._astroray_read_profile(node, mat) if False else ''`),
  and the `astroray_ir_uv` / native-output path never calls
  `set_material_spectral_profile`, so the material renders black outside
  the visible band and C++ logs "0 profiles uploaded" — on **CPU and
  GPU** (it is not a GPU bug).
- **BUG-09 (P3-c):** custom `ShaderNode` subclasses
  (`AstrorayOutputNode` / IR-UV / Sellmeier) may not survive
  `inline_shader_nodes()` flattening, so the native-output detection
  `next(...)` finds nothing and silently falls through to the standard
  path — the Astroray node "doesn't work." This **gates P3-b** (if the
  node does not survive flattening, fixing `if False` still won't get the
  profile to the converter).
- **BUG-08 (P4):** two divergent FOV derivations. `_apply_camera`
  (`:1639`, F12 / scene-camera / CAMERA-view) uses the real camera
  datablock (default 36 mm); the free-orbit path `_setup_viewport_camera`
  (`:1547–1554`) **hardcodes `sensor_width = 32.0`** and re-derives hFOV
  from `space_data.lens`, ignoring lens shift and `view_camera_offset`.
  The rendered framing disagrees with Blender's own viewport/overlay.

**After:** Every UI-presented control either has a live, tested wire to
the engine or is not presented. The preview button runs without
constructing a `RenderEngine`. An IR-band material renders non-black
with a profile actually uploaded (C++ no longer logs "0 profiles"). A
probe confirms custom nodes survive flattening (or the converter is fed
the pre-flatten tree). The engine camera frustum is taken from Blender's
own projection matrices, so viewport == F12 == Blender's overlay in
PERSP / ORTHO / CAMERA.

---

## Context

This is **Stage 2 / primitives P3 + P4** of the addon remediation
first-principles plan (PR #300 §4 Stage 2), grouped because both are
small, real, CPU-path / Python-addon defects with no GPU-architecture
contention, parallelizable once Stage 1 (pkg94) lands.

- **P3 (PR #300 §2):** violated invariant — *"a control the UI presents
  as functional actually feeds the engine."* Three distinct dead-path
  mechanisms, same essence (a severed wire): (a) a forbidden
  `RenderEngine()` construction; (b) a hard `if False` gate plus a
  missing `set_material_spectral_profile` call; (c) custom nodes possibly
  stripped by flattening. The binary already supports each feature.
  *Boundary note:* the *multi-band closure* half of BUG-13 (a full
  spectral response material) is genuinely pkg-future and stays
  documented-not-fixed; only the `if False` + missing-call half is in
  scope here — it is the cleanest single defect in the triage.
- **P4 (PR #300 §2):** violated invariant — *"the engine's camera
  frustum equals the frustum Blender is drawing."* Any re-derivation that
  does not start from `rv3d.window_matrix` / `perspective_matrix` is a
  guess that cannot match Blender's overlay. Best-fix direction from the
  triage (PR #295 BUG-08): derive the frustum from Blender's native
  matrices instead of re-deriving FOV from a guessed sensor.

The collapse proof (PR #300 §3): closing P3 eliminates BUG-15, BUG-13
(`if False` half), BUG-09; closing P4 eliminates BUG-08. P4 is a single
defect / single symptom but is its own irreducible primitive (a distinct
invariant) and must not be folded into the sync work (pkg96).

Per PR #300 §7 item 2, P3+P4 are recommended as **one package** (shared
review surface, all CPU-path). Filed here as pkg95.

---

## Reference

- First-principles plan: `.astroray_plan/docs/addon-remediation-first-principles-plan-2026-05-16.md`
  (PR #300) — §2 P3 & P4 (formal/efficient/final cause), §3 collapse
  table (P3, P4 rows), §4 Stage 2 (work breakdown P3-a/b/c + P4,
  dependency on Stage 1, the P3-c probe gating P3-b).
- Triage: `.astroray_plan/docs/blender-addon-bug-triage-2026-05-15.md`
  (PR #295) — BUG-15 (RC-8, definitive root cause, fix direction:
  factor node-conversion off the `RenderEngine` subclass), BUG-13
  (RC-5, the `if False` line + missing `set_material_spectral_profile`),
  BUG-09 (RC-6, the `inline_shader_nodes()` flatten hypothesis +
  disambiguating experiment), BUG-08 (RC-7, the two FOV derivations +
  the `rv3d.window_matrix` fix direction).
- `blender_addon/__init__.py` — `_create_live_preview_material`
  (~L674–678, the `CustomRaytracerRenderEngine()` at L676);
  `CustomRaytracerRenderEngine` class comment (L706–709);
  `_astroray_ir_uv_spec` / the `if False` at L1865;
  `_create_astroray_material` `kind == 'astroray_ir_uv'` (L1909–1915);
  `_apply_spectral_profile` (L1709) / native-output path (L1742);
  `convert_node_material` + `material.inline_shader_nodes()`
  (docstring L1698–1704); native-output detection (L1737–1740);
  IR-UV / Sellmeier / NRC detection (L1789–1804);
  `_apply_camera` (L1639) / `_compute_vfov_degrees`;
  `_setup_viewport_camera` (L1547–1554, hardcoded `sensor_width = 32.0`
  at L1549).
- `blender_addon/nodes/__init__.py:163` — custom `bpy.types.ShaderNode`
  subclass registration.
- `module/blender_module.cpp` — `set_material_spectral_profile` binding
  (the call P3-b must reach).
- Blender API: `bpy.types.RegionView3D.window_matrix` /
  `perspective_matrix` (the Blender-native projection P4 consumes).

## Prerequisites

- [ ] **pkg94 merged** — fixes here must be verifiable on a
      known-current module (P1 otherwise masks/disguises results).
- [ ] Build passes on main.
- [ ] No active addon-Python work mid-session on `__init__.py` material
      conversion / camera path.

## Specification

### Key design decisions

1. **P3-c probe first; it gates P3-b.** Before touching the `if False`,
   confirm whether `inline_shader_nodes()` preserves `AstrorayOutputNode`
   / IR-UV / Sellmeier subclasses (the triage's disambiguating
   experiment: print `[n.bl_idname for n in
   mat.inline_shader_nodes().nodes]`). If they do **not** survive, feed
   the converter the pre-flatten tree (or detect on the original) — the
   minimum change that makes the node reach the converter. Do not
   re-architect the flattener. *Rationale:* PR #300 §4 — P3-b's profile
   still won't reach the engine if the node is stripped first.
2. **P3-a: factor node-conversion off the `RenderEngine` subclass.** The
   preview path only wants `convert_node_material` / `convert_volume_node`
   — it does not need a `RenderEngine` instance. Extract those into a
   module-level helper (or a lightweight non-`RenderEngine` converter)
   the preview path calls without constructing a `RenderEngine()`.
   Self-contained; crash → fixed. *Rationale:* PR #295 BUG-15 fix
   direction; the class comment already documents that direct
   construction is forbidden.
3. **P3-b: remove `if False`, thread the node profile through, call
   `set_material_spectral_profile`.** Replace
   `... if False else ''` at `__init__.py:1865` with the real
   `_astroray_read_profile(node, mat)`; ensure the `astroray_ir_uv` /
   native-output path actually calls `set_material_spectral_profile`
   with that profile. Scope is the `if False` + missing-call half only —
   **not** the multi-band closure material (pkg-future). *Rationale:* PR
   #295 RC-5 — the cleanest real defect in the report (one `if False` +
   one missing call).
4. **P4: one Blender-native projection.** Replace **both** FOV
   derivations (`_apply_camera` and `_setup_viewport_camera`) with a
   single path that consumes `rv3d.window_matrix` /
   `perspective_matrix` so viewport == F12 == Blender's overlay by
   construction. Delete the hardcoded `sensor_width = 32.0`. *Rationale:*
   PR #300 §2 P4 final cause + PR #295 BUG-08 best-fix direction —
   reconstruction from guessed intrinsics cannot match Blender; consume
   Blender's matrix instead of re-deriving.
5. **Surgical, CPU-path only.** No GPU path, no depsgraph dispatcher, no
   new material model. Each sub-fix is independently shippable; P3-a and
   P4 are parallelizable; P3-b waits on the P3-c probe.

### Files to modify

| File | What changes |
|---|---|
| `blender_addon/__init__.py` | **P3-a:** factor `convert_node_material`/`convert_volume_node` off the `RenderEngine` subclass; `_create_live_preview_material` calls the helper without `CustomRaytracerRenderEngine()`. **P3-b:** remove the `if False` @ L1865; thread `_astroray_read_profile(node, mat)`; call `set_material_spectral_profile` on the `astroray_ir_uv` / native-output path. **P3-c:** if the probe shows custom nodes don't survive flattening, feed the converter the pre-flatten tree (or detect on the original). **P4:** replace both FOV derivations with one `rv3d.window_matrix`/`perspective_matrix`-based projection; delete the hardcoded `sensor_width = 32.0` @ L1549. |
| `blender_addon/nodes/__init__.py` | Only if the P3-c probe shows custom subclasses must be detected pre-flatten (minimal change to surface them; no flattener re-architecture). |

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg95_addon_ui_wires_camera.py` | (1) **P3-a:** the preview-material code path runs without raising `TypeError` and without constructing a `RenderEngine`; (2) **P3-c:** assert custom node subclasses (`AstrorayOutputNode` / IR-UV / Sellmeier) are reachable by the converter (post-flatten present, or pre-flatten path taken); (3) **P3-b:** an `astroray_ir_uv` material with a Response→Output node graph produces a non-empty spectral profile and triggers `set_material_spectral_profile` (≥ 1 profile uploaded; C++ no longer reports "0 profiles"); (4) **P4:** the projection derived for a known `rv3d` matches the matrix Blender would draw (frustum from `window_matrix`/`perspective_matrix`, not the 32 mm guess) for PERSP and ORTHO. |

## Acceptance criteria

- [ ] **P3-a:** invoking the preview path no longer raises
      `TypeError: bpy_struct.__new__(struct): expected a single argument`
      and does not construct a `RenderEngine`.
- [ ] **P3-c:** the custom-node probe is recorded in the PR; the
      converter provably sees `AstrorayOutputNode` / IR-UV / Sellmeier
      (post-flatten or via the pre-flatten path).
- [ ] **P3-b:** an IR/UV Response→Output material yields a non-empty
      profile and `set_material_spectral_profile` is called; the C++
      "0 profiles uploaded" log no longer appears for that material
      (verified on CPU; the defect was never GPU-specific).
- [ ] **P4:** object-mode camera gizmo and free orbit align with the
      rendered framing in PERSP/ORTHO/CAMERA; the single projection is
      derived from `rv3d.window_matrix`/`perspective_matrix`; the
      hardcoded `sensor_width = 32.0` is gone.
- [ ] All existing tests still pass; no regressions; no new public addon
      API beyond the extracted converter helper.

## Non-goals

- Do **not** implement the IR/UV *multi-band closure* material (a full
  spectral response material). That half of BUG-13 is genuinely
  pkg-future — document the limitation, do not build it here.
- Do **not** re-architect `inline_shader_nodes()`. If P3-c shows custom
  nodes are stripped, the fix is the minimum to surface them to the
  converter, not a flattener rewrite.
- Do **not** touch the GPU path, the depsgraph dispatcher, or any
  backend selection — that is pkg96 / pkg55-B'.
- Do **not** address BUG-14 (colored-glass absorption) or BUG-16
  (subsurface) — fidelity-model gaps, deliberately out of the next 2–3
  stages (PR #300 §6); a follow-up probe package if ever.
- Do **not** add a generic node-conversion framework — extract exactly
  the methods the preview path needs and no more.

## Progress

- [ ] **pkg94 merged** (prerequisite).
- [ ] P3-c probe run + result recorded; flatten-survival fix applied if
      needed.
- [ ] P3-a: node-conversion factored off `RenderEngine`; preview path
      no longer constructs one.
- [ ] P3-b: `if False` removed; profile threaded;
      `set_material_spectral_profile` called.
- [ ] P4: both FOV derivations replaced with one Blender-native
      projection; hardcoded 32 mm deleted.
- [ ] `tests/test_pkg95_addon_ui_wires_camera.py` written + passing.
- [ ] CI green; no regressions.

## Lessons

*(Fill in after the package is done.)*

These are the highest fix-value-per-effort *real* defects in the addon
triage: each currently presents as "feature totally broken / button
crashes," each is a one-to-few-line change, and none depends on the
expensive GPU-architecture work. They were grouped because they share a
review surface (all CPU-path Python) and are independent of the
wavefront track — so they can land concurrently with pkg55-B'.

---

## Track routing / acceptance gate

- **Track A.** Addon Python; CPU-path only. No GPU / hardware-verifier
  pass required; the acceptance gate is the pytest above plus the
  recorded P3-c probe result and a manual Blender smoke note in the PR
  (preview button runs; IR-band material non-black; camera aligns).
- **Round-10 sequencing:** **depends on pkg94** (verifiability). Runs
  **concurrently with pkg96** (independent — different defect surfaces in
  the same file; coordinate edits but no logical dependency) and
  **concurrently with, and independent of, pkg55-B' Session 3** (zero
  file contention — addon Python vs CPU wavefront sources).
- **Acceptance gate (one line):** preview button runs (no `TypeError`),
  an IR-band material renders non-black with a profile actually uploaded
  (no "0 profiles" log), and the object-mode/orbit camera aligns with the
  render in PERSP/ORTHO/CAMERA via a single Blender-native projection.
