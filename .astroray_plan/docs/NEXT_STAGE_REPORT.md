# Astroray Next Stage Report

**Date:** 2026-05-17 (Round 10 closed — Round 11 planning)
**Prepared by:** Claude (Anthropic Code, Sonnet 4.5)
**Scope:** Round 10 closeout + Round 11 recommended set.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C; Pillar 4
> has been actively shipping since. Strategy in
> [`ROADMAP.md`](ROADMAP.md), status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

**Done in Round 10 (7 PRs merged, 2026-05-17):**

- **pkg44 ADAF accretion model** (PR #310) — Narayan & Yi 1995
  self-similar ADAF solution + Yuan & Narayan 2014 prefactors;
  synchrotron (Pandya 2016 reused from pkg42) + bremsstrahlung thermal
  emission; 19 tests pass (power-law exponents exact, Sgr A* profiles
  within tolerance). Pillar 4 → ~50%.
- **pkg99 spec — ADAF quasi-spherical glow re-investigation** (PR #315,
  doc-only) — pkg44 wiring correct but visual gate only partial (crisp
  shadow + faint emission sliver vs the specified quasi-spherical
  glow). Unblocks RTX visual-iteration follow-up.
- **pkg55-B' Session 7 — Diffuse Light** (PR #316) — scope guard
  extended to `lambertian + metal + dielectric + disney + thin_glass +
  diffuse_light`. Emissive sphere test coverage (distinct from area
  light triangles). Bit-identity gate: PASS (max abs diff 0.0,
  diverging fields 0). Full suite: 1006 passed. Production codegen:
  byte-unchanged.
- **pkg55-B' Session 8 — Closure Graph** (PR #318) — scope guard
  extended to all seven material types (`lambertian + metal +
  dielectric + disney + thin_glass + diffuse_light + closure_graph`).
  Closure_matte sphere (blue-tinted diffuse). Bit-identity gate: PASS
  (max abs diff 0.0, diverging fields 0). Full suite: 1006 passed.
  Production codegen: byte-unchanged. **Growing-oracle expansion now
  complete before Session N+1 (shadow/miss/terminate stages).**
- **pkg90 spec — Hardware-verifier build-env bootstrap** (PR #319,
  doc-only) — MSVC + worktree-parameterized CUDA build; unblocks
  orchestrator HW gate for unattended operation (currently
  `hw_blocked_buildenv` on every HW-gated PR).
- **pkg55-B-prime-cuda-gate-derivation** (PR #320, doc-only) — two-tier
  CPU↔CPU / CPU↔GPU gate definition now authoritative in pkg55 spec
  (exact bit-identity for CPU↔CPU, ULP-bounded + SSIM for CPU↔GPU);
  design decision #9 added (shared-kernel, never re-transcribe); A.1
  ray-normalization checklist item added to Session-2c design doc.
  Unblocks CUDA-port Sessions N+2..M.
- **pkg100 spec — .blend importer camera-intrinsics dynamic-attr
  defect** (PR #321, doc-only) — every `.blend` import fails with
  `AttributeError: 'astroray.Renderer' object has no attribute
  '_cam_intrinsics' and no __dict__`; blocks pkg76 §3.5 CSV follow-up
  (Classroom / Junkshop / BMW27 RTX parity rows).

**HELD on branch (do not merge):**

- **pkg55 Phase B** (origin/pkg55-phase-b, NOT merged) — superseded by
  the Phase B' CPU-first restart on main; reference only.

**Carried / deferred (stable across rounds):**

| Pkg | Effort | Notes |
|---|---|---|
| pkg76 CSV | ~½ day RTX | Classroom / Junkshop / BMW27 baseline rows |
| pkg45 / pkg46 | weeks each | CLOUDY / HII region (Pillar 4) — after pkg44 |
| pkg48 / 49 | weeks each | HDF5 / SPH loaders (pkg48 also owns deferred FITSVolume registration) |
| pkg50 / 51 | weeks each | Weak lensing / telescope post-process (late Pillar 4) |

---

## 2. Recommended next deployable set (Round 11)

**Round 10 complete (2026-05-17).** 7 PRs merged: pkg44 ADAF, pkg99
spec, pkg55-B' Sessions 7/8, pkg90 spec, pkg55-B-prime-cuda-gate-
derivation, pkg100 spec.

**Round 11 priorities** (based on unblock graph and payback):

**Top priority (should land first):**

- **pkg94 — Blender addon build-integrity guard** (~½ day, **first
  pickup, depends on nothing**). Stage 1 / P1 of the addon remediation
  track. Collapses BUG-01/03(crash)/07; the verifiability multiplier —
  every later addon fix is unverifiable until it lands. After pkg94
  ships, **pkg95 ∥ pkg96** can run concurrently (both depend on pkg94;
  independent of each other except for same-file coordination in
  `blender_addon/__init__.py`).
- **pkg55-B' Session N+1 — Shadow/miss/terminate stages on CPU.** With
  the growing-oracle expansion complete (Sessions 3–8 done), add the
  remaining stages (shadow ray, miss, terminate/accumulate). Still
  CPU-only; CUDA-port sessions N+2..M are now unblocked by
  pkg55-B-prime-cuda-gate-derivation (two-tier gate definition landed PR
  #320) but not yet the next session.
- **pkg100 — .blend importer camera-intrinsics fix** (small, well under
  a day). Every `.blend` import fails with `AttributeError:
  'astroray.Renderer' object has no attribute '_cam_intrinsics'`.
  Blocks pkg76 §3.5 CSV follow-up (Classroom / Junkshop / BMW27 RTX
  parity rows). Three fix axes laid out in spec (py::dynamic_attr vs
  return-up-chain vs thin wrapper); small localized C++/Python
  correctness fix.

**Second tier (unblocked):**

- **pkg95 / pkg96** — Blender addon Stage 2/3 (both depend on pkg94;
  independent of each other). pkg95: dead-UI-wires (BUG-15/13/09) +
  Blender-native camera (BUG-08). pkg96: reconcile-then-upload sync
  (BUG-04/05) + honesty guard (UX-only).
- **pkg89 Phase B** (Blender addon for dedicated lights) — full-scene
  G8 + G1–G5; the Phase A interface landed PR #294.
- **pkg99 — ADAF quasi-spherical glow re-investigation** (~1 day
  including RTX render iteration). pkg44 wiring correct but visual gate
  only partial (crisp shadow + faint emission sliver vs the specified
  quasi-spherical glow). Requires empirical render iteration on RTX
  hardware (visual gate); not verifiable by CI alone.

**Third tier:**

- **pkg90 — Hardware-verifier build-env bootstrap** (~½ day). MSVC +
  worktree-parameterized CUDA build; unblocks orchestrator HW gate for
  unattended operation (currently `hw_blocked_buildenv` on every
  HW-gated PR).
- **pkg76 CSV** — Classroom / Junkshop / BMW27 parity rows on RTX
  (~½ day). Now unblocked once pkg100 ships.
- **pkg86 Light Tree** — pkg89 Phase A now ships
  `Light::orientationCone()` + `power()` accessors.
- **pkg87a / pkg87b / pkg87c** Cryptomatte — independent; pkg87a is on a
  branch awaiting review per its spec; pkg87b/pkg87c follow.
- **pkg64-gpu Phase 1** — GPU SMS caustics, megakernel target
  (acknowledged pkg55-C will re-port).

**Known flakes (not blocking):**

- **Issue [#298](https://github.com/HendrikGC02/Astroray/issues/298)** —
  ReSTIR `test_spatial_reduces_mse` MC-noise on a strict inequality;
  recommend a seed-pin or a tolerance/seed-averaging margin.
- **Issue #276** — `test_disney_clearcoat_adds_gloss` chronic flake +
  suspected clearcoat correctness defect; owner triage recommended.

**Owner decisions — RESOLVED for the Round-10 addon track:**

- ~~Round 10 direction: continue the inherited backlog vs prioritising
  the Blender addon remediation track.~~ **RESOLVED (2026-05-16): Round
  10 = concurrent, pkg94 first.** pkg94 (P1 build-integrity guard) lands
  first as the verifiability multiplier; then pkg95 ∥ pkg96 run
  concurrently with pkg55-B' Session 3. **Zero contention with pkg55-B'
  Session 3** (addon Python vs `src/cpu/wavefront/*`); **however pkg95
  and pkg96 both edit `blender_addon/__init__.py` in disjoint surfaces
  and require same-file coordination/rebase — they are logically
  parallel, not contention-free.** **No open owner decisions remain for
  the Round-10 addon track.**
- Resolved (pkg96-internal, Round-10 review): the PR #300 §9 question on
  the P5 guard *behavior* is **decided — show a clear, specific CPU-only
  notice; do NOT auto-route AOV/denoise/world-only passes to CPU** (no
  silent backend switch). This is a settled pkg96 implementation
  detail, not a Round-10 sequencing gate.

---

## 3. Drop-in prompts per agent

### 3.1 Claude Code (Track A) — pkg94 addon build-integrity guard (Round 11 FIRST pickup)

```
You are Claude Code on the RTX box. Round 11 addon track, FIRST pickup.
pkg94 depends on NOTHING and is the verifiability multiplier for
pkg95/pkg96.

Read first:
  - .astroray_plan/packages/pkg94-addon-build-integrity-guard.md
  - .astroray_plan/docs/addon-remediation-first-principles-plan-2026-05-16.md (§2 P1, §4 Stage 1)
  - .astroray_plan/docs/blender-addon-bug-triage-2026-05-15.md (§1, §5 Phase 0)
  - blender_addon/__init__.py register(); build_blender_addon.py;
    module/blender_module.cpp (__version__/__features__ surface)

Goal: addon emits a build stamp; register() compares vs astroray.__build__
and raises ONE loud "RESTART BLENDER — stale module loaded" on mismatch;
install script refuses/warns on locked .pyd and GCs .~stale~NNNN. Reuse
the existing build_report.json hash — no new stamping scheme. ZERO
engine-logic change.

Constraints: CLAUDE.md 1,2,3. Packaging + observability only. Do NOT
"fix" BUG-01/03/07 in C++/Python — they are a stale-loaded-module
artifact. Test per the spec's acceptance criteria.

When done: pkg94 spec status -> done + PR + the guard-fires smoke note.
PR titled "feat(pkg94): addon build-integrity guard".
```

### 3.2 Claude Code (Track A) — pkg55-B' Session N+1 (shadow/miss/terminate stages)

```
You are Claude Code on the RTX box. pkg55-B' growing-oracle expansion
complete (Sessions 3–8, all seven material types). Session N+1 adds the
remaining CPU wavefront stages: shadow ray, miss, terminate/accumulate.

Read first:
  - .astroray_plan/packages/pkg55-wavefront-soa-refactor.md (Phase B'
    Session N+1 + two-tier gate definition)
  - src/cpu/wavefront/path_kernel.{h,cpp} (shared per-bounce kernel) +
    cpu_wavefront_state.{h,cpp}
  - tests/wavefront_diff/ (per-stage diff harness)

Goal: extend the shared kernel + both reference PTs to cover shadow ray
(occlusion test for NEE), miss (environment miss), and
terminate/accumulate (final radiance write) stages. Keep EXACT
bit-identity CPU↔CPU via the shared kernel. Production codegen must
stay byte-unchanged.

Constraints: CLAUDE.md 1,2,3,6. Still CPU-only; CUDA-port sessions
N+2..M are unblocked (two-tier gate landed PR #320) but not yet the
next session.

When done: pkg55 spec Session N+1 status + PR ref + diff numbers.
```

### 3.3 Claude Code (Track A) — pkg100 .blend importer camera-intrinsics fix

```
You are Claude Code on the RTX box. Every .blend import fails at
camera-emit time with AttributeError: 'astroray.Renderer' object has no
attribute '_cam_intrinsics' and no __dict__. Blocks pkg76 §3.5 CSV
follow-up (Classroom / Junkshop / BMW27 RTX parity rows).

Read first:
  - .astroray_plan/packages/pkg100-blend-importer-camera-intrinsics-fix.md
  - tools/blend_import/scene_builder.py (line 175, _cam_intrinsics
    assignment)
  - tools/blend_import/blend_to_astroray.py (line 68,
    _blend_import_stats)
  - module/blender_module.cpp (line 1595, py::class_<PyRenderer>)
  - tests/test_blend_import_roundtrip.py (_FakeRenderer stub)

Goal: fix the dynamic-attr defect so .blend imports reach rendering.
Three fix axes in spec (py::dynamic_attr vs return-up-chain vs thin
wrapper); spec recommends Axis 2 as defensible but leaves choice to
implementer. Acceptance: regression test exercising real pybind11
astroray.Renderer (not stub) covering both _cam_intrinsics and
_blend_import_stats.

Constraints: CLAUDE.md 1,2,3. Small localized C++/Python correctness
fix; well under a day.

When done: pkg100 spec status -> done + PR. PR titled "fix(pkg100):
.blend importer camera-intrinsics dynamic-attr defect".
```

### 3.4 Claude Code (Track A) — pkg95 addon dead-UI-wires + camera (depends on pkg94)

```
You are Claude Code on the RTX box. Round 11 addon track. Pick up AFTER
pkg94 merges (so fixes are verifiable on a known-current module). Runs
concurrently with pkg96 and pkg55-B' Session N+1.

Read first:
  - .astroray_plan/packages/pkg95-addon-dead-ui-wires-and-camera.md
  - .astroray_plan/docs/addon-remediation-first-principles-plan-2026-05-16.md (§2 P3/P4, §4 Stage 2)
  - .astroray_plan/docs/blender-addon-bug-triage-2026-05-15.md (BUG-15/13/09/08)
  - blender_addon/__init__.py (preview path L676; if False L1865;
    camera L1547-1554/L1639); blender_addon/nodes/__init__.py:163

Goal: P3-c probe FIRST (does inline_shader_nodes() keep custom nodes?);
P3-a de-RenderEngine() the preview path (BUG-15); P3-b remove `if False`
+ call set_material_spectral_profile on the IR/UV path (BUG-13, gated by
P3-c); P4 replace BOTH FOV derivations with rv3d.window_matrix /
perspective_matrix (BUG-08). CPU-path only; no GPU.

Constraints: CLAUDE.md 1,2,3. Do NOT build the IR/UV multi-band closure
(pkg-future) or re-architect inline_shader_nodes(). Test per spec.

When done: pkg95 spec status -> done + PR + recorded P3-c probe result.
PR titled "fix(pkg95): addon dead-UI-wires + Blender-native camera".
```

### 3.5 Claude Code (Track A) — pkg96 reconcile-then-upload sync + P5 guard (depends on pkg94)

```
You are Claude Code on the RTX box. Round 11 addon track. Pick up AFTER
pkg94 merges. Independent of pkg95 (same file, different surfaces —
coordinate edits, no logical dependency). Concurrent with pkg55-B'
Session N+1.

Read first:
  - .astroray_plan/packages/pkg96-addon-reconcile-then-upload-sync.md
  - .astroray_plan/docs/addon-remediation-first-principles-plan-2026-05-16.md (§2 P2/P5, §4 Stage 3, §5, §9)
  - .astroray_plan/docs/blender-addon-bug-triage-2026-05-15.md (BUG-04/05; Cluster B/D)
  - blender_addon/__init__.py _apply_depsgraph_updates (L1158-1237),
    _classify_depsgraph_update, setup_world, _configure_backend_for_context

Goal: P2 — _apply_depsgraph_updates gains per-domain RECONCILE before
upload (World edit re-parses world tree before upload_environment;
device_mode gets a real domain calling _configure_backend_for_context,
NOT accumulation_only) → BUG-04/05. P5 GUARD ONLY — honest non-crashing
notice (or CPU auto-route per owner §9) for GPU AOV/denoise/world-only;
NO GPU kernel code. P5's real fix is folded into pkg55-B', not here.

Constraints: CLAUDE.md 1,2,3. Do NOT implement P5's GPU architecture or
touch cuda_renderer.cu / the GPU render() branch. Do NOT edit pkg85-D
or the pkg55 spec from this package (those are separate doc edits).
Test per spec.

When done: pkg96 spec status -> done + PR + the live-update smoke note.
PR titled "fix(pkg96): reconcile-then-upload sync + P5 honesty guard".
```

> **Round-10 dispatch RESOLVED.** PR #300 landed the first-principles
> plan, pkg94/95/96 + pkg55-B-prime-cuda-gate-derivation + pkg90/99/100
> specs all filed. pkg44 ADAF + pkg55-B' Sessions 3–8 + two-tier gate
> derivation all shipped in Round 10. No open owner decision remains for
> the Round-11 dispatch; pkg94 is first pickup.

### 3.6 Codex (RTX hardware) — pkg99 ADAF quasi-spherical glow re-investigation

```
You are Codex on the RTX 5070 Ti box. pkg44 wiring correct (enable_adaf
branch, adaf_ prefix mapping, render-unit camera all present), but
visual gate only partial: crisp shadow + faint emission sliver vs the
specified quasi-spherical glow.

Read first:
  - .astroray_plan/packages/pkg99-adaf-quasi-spherical-glow.md
  - .astroray_plan/packages/pkg44-adaf.md (acceptance L243, the missing
    glow)
  - plugins/volumetric_emission/adaf_plugin.cpp (existing implementation)
  - gate renders: astroray-wt-pkg44/test_results/adaf_sgra_gate_*.png

Goal: empirical render iteration on RTX to achieve the quasi-spherical
glow around the black hole. Requires visual gate (CI cannot verify).
Spec §2 hypotheses: normalization scaling, temperature floor,
density/emissivity interplay, transfer tau accumulation.

Constraints: CLAUDE.md 1,2,3,6. DO NOT re-do the scene wiring (it is
correct). ~1 day including RTX iteration.

When done: pkg99 spec status -> done + PR + visual-gate comparison
note. PR titled "fix(pkg99): ADAF quasi-spherical glow".
```

### 3.7 Codex (RTX hardware, small) — pkg76 CSV rows (unblocked after pkg100)

```
You are Codex on the RTX 5070 Ti box. Small ~½-day follow-up. Now
unblocked: pkg100 fixes the .blend import AttributeError.

Read first:
  - benchmarks/cycles-parity/README.md + scripts/run_parity.py
  - .astroray_plan/packages/pkg76-blend-importer-parity-scope.md Lessons
  - tools/blend_import/ (the working importer, post-pkg100)

Procedure: populate the .blend cache; run scripts/run_parity.py for
Classroom + Junkshop + BMW27 vs Cycles-CPU EXR at the manifest's
reference SPP. Acceptance per spec: SSIM ≥ 0.85.

Output: rows appended to the dated parity CSV.

Constraints: CLAUDE.md 1,4. Doc + CSV only; no source touched.

When done: PR titled
"verify(pkg76): Classroom/Junkshop/BMW27 parity rows on RTX".
```

---

## 4. Coordination

**File-touching map:**

| Session | Files |
|---|---|
| pkg94 | `blender_addon/__init__.py` (register), `build_blender_addon.py`, `module/blender_module.cpp` (__build__), new test, pkg94 spec, STATUS.md |
| pkg55-B' Session N+1 | `src/cpu/wavefront/*`, `tests/wavefront_diff/*`, pkg55 spec, STATUS.md |
| pkg100 | `tools/blend_import/*`, `module/blender_module.cpp` (or design-dependent), new test, pkg100 spec, STATUS.md |
| pkg95 | `blender_addon/__init__.py` (preview/IR-UV/camera), `blender_addon/nodes/__init__.py`, new test, pkg95 spec, STATUS.md |
| pkg96 | `blender_addon/__init__.py` (depsgraph dispatcher + P5 guard), new test, pkg96 spec, STATUS.md |
| pkg99 | `plugins/volumetric_emission/adaf_plugin.cpp`, pkg99 spec, STATUS.md |
| pkg89 Phase B | Blender addon files, pkg89 spec, STATUS.md |
| pkg90 | `build_cuda_run.bat` (or worktree-parameterized equivalent), orchestrator hw-verifier, pkg90 spec, STATUS.md |
| pkg76 CSV | parity CSV, pkg76 spec Lessons, STATUS.md |

**Conflict points:**

1. **`STATUS.md`** — multiple sessions touch it; rebase + manual
   resolution as always.
2. **pkg55 wavefront CPU sources** — single-owner (Track A); no
   cross-track contention while Phase B' is CPU-only. The addon track
   (pkg94/95/96, Python/packaging) has **zero contention with pkg55-B'
   Session N+1** (addon Python vs `src/cpu/wavefront/*`) — they run
   concurrently.
3. **`blender_addon/__init__.py`** — pkg95 and pkg96 **both edit it in
   disjoint surfaces** (pkg95: preview/IR-UV/camera; pkg96: depsgraph
   dispatcher + P5 guard) and **require same-file coordination/rebase —
   they are logically parallel, not contention-free.** No logical
   dependency between them. Both depend on pkg94 (which touches
   `register()` only).
4. **pkg100 vs pkg76 CSV** — pkg76 CSV (Classroom/Junkshop/BMW27) is
   **blocked on pkg100** (the .blend import AttributeError fix).

**Recommended merge order:** **pkg94** (addon verifiability multiplier,
no deps — land FIRST) → pkg100 (small, unblocks pkg76 CSV) → pkg55-B'
Session N+1 ∥ pkg95 ∥ pkg96 (concurrent; pkg95/pkg96 gated on pkg94) →
pkg99 (ADAF glow, RTX iteration) → pkg89 Phase B → pkg76 CSV → pkg90
(orchestrator HW gate bootstrap).

---

## 5. After Round 11 lands

When Round 11 closes:

- **pkg55-B' Session N+1** done — shadow/miss/terminate stages on CPU;
  growing-oracle expansion complete for all CPU wavefront stages. Ready
  for CUDA-port sessions N+2..M (two-tier gate definition landed PR
  #320).
- **Blender addon remediation** — pkg94 landed (the verifiability
  multiplier); pkg95 ∥ pkg96 in flight or done. All three specs filed
  and dispatchable; no open owner decision on the addon track.
- **pkg100** done — .blend import AttributeError fixed; pkg76 §3.5 CSV
  follow-up (Classroom/Junkshop/BMW27 RTX parity rows) unblocked.
- **pkg44** done (Round 10) — Pillar 4 has four emission models
  (synchrotron, slim disk, ADAF, thermal/blackbody); real astrophysical
  scenes are composable. Pillar 4 ~50%.
- **pkg99** in flight or done — ADAF quasi-spherical glow
  re-investigation (RTX visual gate); pkg44 wiring correct but visual
  gate only partial.
- **pkg89 Phase B** in flight or done — dedicated lights usable from
  the Blender addon end-to-end; pkg86 Light Tree fully unblocked.
- **pkg90** (optional) — hardware-verifier build-env bootstrap;
  orchestrator HW gate for unattended operation.

Bump this report when pkg55-B' CUDA-port sessions begin or when a new
major pillar milestone is reached.
