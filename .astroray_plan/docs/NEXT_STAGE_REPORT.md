# Astroray Next Stage Report

**Date:** 2026-05-21 (Round 11 mid-cycle — 5 PRs landed in one day; pkg55-B' Session N+1 done, CUDA-port track now the lead live work)
**Prepared by:** Claude (Anthropic Code) — updated mid-Round-11 after orchestrator-meta + pkg55 + pkg64 wave
**Scope:** Round 11 mid-cycle checkpoint + remaining set.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C; Pillar 4
> has been actively shipping since. Strategy in
> [`ROADMAP.md`](ROADMAP.md), status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

**Done in Round 11 mid-cycle wave (5 PRs merged, 2026-05-21):**

- **pkg55-B' Session N+1** (PR #327) — env-map miss + complete CPU wavefront pipeline. Bit-identity gate PASS (max abs diff 0.0 across all 5 snapshot stages). Acceptance gate swapped SSIM≥0.985 → per-channel mean-ratio ≤0.05 (windowed SSIM unreachable for independent MC streams at modest spp; bit-identity is the load-bearing gate; owner-approved at architect stage). **Closes the CPU-only growing-oracle track; Sessions N+2..M (CUDA port) is now the top live track.**
- **pkg64-gpu Phase 1** (PR #323) — device `sms_attempt_device.cuh` + `GSphere.isCausticCaster` + scene_upload mirror + minimal probe harness. RTX 5070 Ti `/verify` confirmed gate #2 (caster-flag round-trip) PASS, gate #3 (regression, 40 GPU tests) PASS. Gate #1 (CPU↔GPU rel-err ≤ 1e-3) spec-deferred to Phase 1.1 follow-up (minimal probe is inert for that gate). classify.py PARTIAL routing landed direct-to-main to surface regressions of this kind.
- **pkg90 hw-verifier buildenv** (PR #333) — `build_cuda_worktree.bat` worktree-parameterized CUDA build with vcvars bootstrap (vswhere + fallback), head-SHA contamination guard. CPU-only carve-out in `classify.py` (CI-green CPU-only PRs route to Ready, bypass phantom HW gate). 13 tests pass. **Orchestrator HW gate functional unattended.**
- **pkg97 orchestrator auto-GC** (PR #331) — merged-worktree auto-GC with three-gate safety. Standup "Shipped today" `(none)` bug fixed. 47 orchestrator tests green. **IMPL_CAP no longer silently saturates after 2 ships.**
- **pkg98 orchestrator independent-review gate** (PR #332, in flight) — on-failure SIGN-OFF/BLOCK + pre-merge review for non-HW-gated PRs; pure-docs fast-path preserved. CI re-running on clean rebase `a3fad5b`.

**Direct-to-main orchestrator hygiene (commit cd32ddb, 2026-05-21):** `classify.py` accepts PARTIAL hw_result (routes via hw_failed); `codex-implementer.md` does a liveness check (first-commit on branch + remote branch exists) before treating Codex as delivered, falls back to package-implementer on Codex death (triggered by pkg90 Codex dispatches dying silently twice).

**Done in Round 10 (8 PRs merged, 2026-05-17):**

- **pkg44 ADAF accretion model** (PR #310) — Narayan & Yi 1995
  self-similar ADAF solution + Yuan & Narayan 2014 prefactors;
  synchrotron (Pandya 2016 reused from pkg42) + bremsstrahlung thermal
  emission; 19 tests pass (power-law exponents exact, Sgr A* profiles
  within tolerance). Pillar 4 → ~50%.
- **pkg94 addon build-integrity guard** (PR #304) — Stage 1 / P1 of the
  addon remediation track. Core build-ID guard implemented:
  `astroray.__build__` attribute exposed, `register()` guard fires on
  mismatch, unit tests pass. Install-script lock/`.~stale~` GC deferred
  to integration test follow-up. The verifiability multiplier for all
  subsequent addon fixes.
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

**Round 10 complete (2026-05-17).** 8 PRs merged: pkg44 ADAF, pkg94
addon build-integrity guard, pkg99 spec, pkg55-B' Sessions 7/8, pkg90
spec, pkg55-B-prime-cuda-gate-derivation, pkg100 spec.

**Round 11 priorities** (based on owner direction: **CUDA-port path
leads** to close the still-unmet viewport-parity claim; pkg100 .blend
importer fix explicitly deprioritized relative to wavefront work):

**Top priority (lead track — CUDA-port path):**

- ~~**pkg55-B' Session N+1 — Shadow/miss/terminate stages on CPU**~~ **DONE
  2026-05-21 (PR #327).** Env-map miss + complete CPU wavefront pipeline;
  bit-identity gate PASS. Acceptance gate swapped to per-channel
  mean-ratio ≤0.05 (architect-stage approval).
- **pkg55-B' Sessions N+2..M — CUDA port of wavefront shade kernels**
  (multi-session, ~4 weeks total per spec Phase B estimate). **Now the
  top live work.** Port the CPU wavefront shade kernels to GPU; Session
  N+2 measures and pins ULP/p99.9/SSIM thresholds before any CUDA code
  change (two-tier gate enforcement per design decision #9). This is
  the path to the **viewport-parity acceptance gate** (CUDA pan-frame
  p99 ≤ 1.2× Cycles-CUDA on the pkg81 harness scene) — the still-unmet
  competitive claim that pkg55 Phase B formally owns.

**Second tier (unblocked, lower priority than CUDA-port track):**

- **pkg95 / pkg96** — Blender addon Stage 2/3 (both depend on pkg94
  which already shipped PR #304; independent of each other except for
  same-file coordination in `blender_addon/__init__.py`). pkg95:
  dead-UI-wires (BUG-15/13/09) + Blender-native camera (BUG-08). pkg96:
  reconcile-then-upload sync (BUG-04/05) + honesty guard (UX-only).
- **pkg89 Phase B** (Blender addon for dedicated lights) — full-scene
  G8 + G1–G5; the Phase A interface landed PR #294. **First attempt PR
  #317 (DRAFT) is BLOCKED**: `cycles-parity-reviewer` 2026-05-21 found
  three real physics defects in commit 29f5645 (invented
  `light_normalize_factor` math + hallucinated Cycles citation + linear
  cone falloff vs Cycles `smoothstepf`). **Implementer brief:**
  `.astroray_plan/docs/pkg89-phase-b-cycles-parity-2026-05-21.md` —
  paste-ready with Cycles file:line citations and patch sketches.
  Original test thresholds (G2 < 0.10, G4 center > 1.0, G4 corner <
  0.01) MUST be restored — no threshold relaxation. Re-dispatch
  `package-implementer` with this doc when an IMPL_CAP slot frees.
- **pkg99 — ADAF quasi-spherical glow re-investigation** (~1 day
  including RTX render iteration). pkg44 wiring correct but visual gate
  only partial (crisp shadow + faint emission sliver vs the specified
  quasi-spherical glow). Requires empirical render iteration on RTX
  hardware (visual gate); not verifiable by CI alone.

**Third tier (deferred / lower priority):**

- **pkg100 — .blend importer camera-intrinsics fix** (small, well under
  a day). Every `.blend` import fails with `AttributeError:
  'astroray.Renderer' object has no attribute '_cam_intrinsics'`.
  Blocks pkg76 §3.5 CSV follow-up (Classroom / Junkshop / BMW27 RTX
  parity rows). Three fix axes laid out in spec (py::dynamic_attr vs
  return-up-chain vs thin wrapper); small localized C++/Python
  correctness fix. **Owner decision: DEPRIORITIZED relative to
  CUDA-port work** — the project accepts continued real-scene parity
  blindness in the near term to close the performance/viewport-parity
  claim first.
- ~~**pkg90 — Hardware-verifier build-env bootstrap**~~ **DONE 2026-05-21
  (PR #333).** Worktree-parameterized CUDA build with vcvars bootstrap +
  CPU-only carve-out in classify.py. Orchestrator HW gate functional
  unattended.
- **pkg76 CSV** — Classroom / Junkshop / BMW27 parity rows on RTX
  (~½ day). Blocked on pkg100 (the .blend import AttributeError fix).
- **pkg86 Light Tree** — pkg89 Phase A now ships
  `Light::orientationCone()` + `power()` accessors.
- **pkg87a / pkg87b / pkg87c** Cryptomatte — independent; pkg87a is on a
  branch awaiting review per its spec; pkg87b/pkg87c follow.
- ~~**pkg64-gpu Phase 1**~~ **DONE 2026-05-21 (PR #323).** Device SMS
  attempt header + caster-flag plumbing + minimal probe; gate #2 + #3
  PASS on RTX, gate #1 spec-deferred to Phase 1.1 follow-up. Phase 2
  (megakernel integration) and Phase 3 follow.

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

### 3.1 ~~pkg55-B' Session N+1~~ — DONE 2026-05-21 (PR #327)

Env-map miss + complete CPU wavefront pipeline. Bit-identity gate PASS.
Sessions N+2..M (CUDA port) is now the top live track — see §3.2.

### 3.2 Claude Code (Track A) — pkg55-B' Sessions N+2..M (CUDA port, TOP LIVE TRACK 2026-05-21)

```
You are Claude Code on the RTX box. pkg55-B' CUDA-port track (Sessions
N+2..M). Session N+1 (shadow/miss/terminate CPU stages) is complete;
now port the wavefront shade kernels to GPU.

Read first:
  - .astroray_plan/packages/pkg55-wavefront-soa-refactor.md (Phase B'
    Sessions N+2..M + two-tier gate definition §4.2 table)
  - src/cpu/wavefront/path_kernel.{h,cpp} (shared per-bounce kernel —
    the bit-identical CPU baseline)
  - src/gpu/cuda_renderer.cu (existing megakernel — the performance
    baseline to beat)
  - tests/wavefront_diff/ (per-stage diff harness)

Goal: port CPU wavefront shade kernels to GPU. Session N+2 MUST
measure-then-pin ULP/p99.9/SSIM thresholds before any CUDA code change
(two-tier gate enforcement per design decision #9). Each subsequent
session ports one material-type shade kernel. Maintain coalesced
memory access; sort paths by material type before shade. Target: CUDA
pan-frame p99 ≤ 1.2× Cycles-CUDA on the pkg81 harness scene (the
viewport-parity acceptance gate pkg55 Phase B owns).

Constraints: CLAUDE.md 1,2,3,6. Multi-session (~4 weeks total per spec
Phase B estimate). Session N+2 gates on threshold pinning; later
sessions gate on staying within those thresholds.

When done: pkg55 spec Session N+2..M status + PR refs + gate numbers
(ULP/p99.9/SSIM per session). PR titles follow the pattern
"feat(pkg55-B'): Session N+2 — threshold pinning + Lambertian CUDA" →
"feat(pkg55-B'): Session N+3 — Metal CUDA", etc.
```

### 3.3 Claude Code (Track A) — pkg95 addon dead-UI-wires + camera (second tier)

```
You are Claude Code on the RTX box. Round 11 addon track, second tier
(lower priority than CUDA-port track). pkg94 already shipped PR #304;
pkg95 is now unblocked.

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

### 3.4 Claude Code (Track A) — pkg96 reconcile-then-upload sync + P5 guard (second tier)

```
You are Claude Code on the RTX box. Round 11 addon track, second tier
(lower priority than CUDA-port track). pkg94 already shipped PR #304;
pkg96 is now unblocked. Independent of pkg95 (same file, different
surfaces — coordinate edits, no logical dependency).

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

> **Round-11 direction RESOLVED (2026-05-17).** Owner decision: **Round
> 11 leads with the pkg55 wavefront CUDA port** (the path to the
> still-unmet viewport-parity claim). pkg100 (.blend importer fix) is
> explicitly DEPRIORITIZED relative to the CUDA-port work — the owner
> accepts continued real-scene parity blindness in the near term to close
> the performance/viewport-parity claim first. pkg94 shipped in Round 10
> (PR #304); pkg55-B' Sessions N+1 (shadow/miss/terminate CPU stages) →
> N+2..M (CUDA port) is the top-priority track.

### 3.5 Codex (RTX hardware) — pkg99 ADAF quasi-spherical glow re-investigation (second tier)

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

### 3.6 Claude Code (Track A) — pkg100 .blend importer camera-intrinsics fix (third tier, DEPRIORITIZED)

```
You are Claude Code on the RTX box. Every .blend import fails at
camera-emit time with AttributeError: 'astroray.Renderer' object has no
attribute '_cam_intrinsics' and no __dict__. Blocks pkg76 §3.5 CSV
follow-up (Classroom / Junkshop / BMW27 RTX parity rows).

**Owner decision: DEPRIORITIZED relative to CUDA-port work** (§2). Pick
up only if CUDA-port sessions stall or after Session N+1 ships.

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

### 3.7 Codex (RTX hardware, small) — pkg76 CSV rows (third tier, blocked on pkg100)

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
| pkg55-B' Session N+1 | `src/cpu/wavefront/*`, `tests/wavefront_diff/*`, pkg55 spec, STATUS.md |
| pkg55-B' Sessions N+2..M | `src/gpu/*`, `src/cpu/wavefront/path_kernel.{h,cpp}` (shared), `tests/wavefront_diff/*`, pkg55 spec, STATUS.md |
| pkg95 | `blender_addon/__init__.py` (preview/IR-UV/camera), `blender_addon/nodes/__init__.py`, new test, pkg95 spec, STATUS.md |
| pkg96 | `blender_addon/__init__.py` (depsgraph dispatcher + P5 guard), new test, pkg96 spec, STATUS.md |
| pkg99 | `plugins/volumetric_emission/adaf_plugin.cpp`, pkg99 spec, STATUS.md |
| pkg100 | `tools/blend_import/*`, `module/blender_module.cpp` (or design-dependent), new test, pkg100 spec, STATUS.md |
| pkg89 Phase B | Blender addon files, pkg89 spec, STATUS.md |
| pkg90 | `build_cuda_run.bat` (or worktree-parameterized equivalent), orchestrator hw-verifier, pkg90 spec, STATUS.md |
| pkg76 CSV | parity CSV, pkg76 spec Lessons, STATUS.md |

**Conflict points:**

1. **`STATUS.md`** — multiple sessions touch it; rebase + manual
   resolution as always.
2. **pkg55 wavefront sources** — single-owner (Track A); **Session N+1
   (CPU) has zero contention with pkg95/pkg96** (addon Python vs
   `src/cpu/wavefront/*`). Sessions N+2..M (CUDA port) also touch
   `src/gpu/*` and may run concurrently with addon track but have no
   file overlap.
3. **`blender_addon/__init__.py`** — pkg95 and pkg96 **both edit it in
   disjoint surfaces** (pkg95: preview/IR-UV/camera; pkg96: depsgraph
   dispatcher + P5 guard) and **require same-file coordination/rebase —
   they are logically parallel, not contention-free.** No logical
   dependency between them. Both depend on pkg94 (already shipped PR
   #304).
4. **pkg100 vs pkg76 CSV** — pkg76 CSV (Classroom/Junkshop/BMW27) is
   **blocked on pkg100** (the .blend import AttributeError fix); both
   explicitly DEPRIORITIZED per owner decision (§2).

**Recommended merge order:** **pkg55-B' Session N+1** (top priority,
CUDA-port path lead) → **Sessions N+2..M** (multi-session CUDA port) ∥
**pkg95 ∥ pkg96** (second tier, concurrent with CUDA-port track) →
**pkg99** (ADAF glow, RTX iteration, second tier) → **pkg89 Phase B** →
**pkg100** (third tier, deprioritized) → **pkg76 CSV** (third tier,
blocked on pkg100) → **pkg90** (orchestrator HW gate bootstrap, third
tier).

---

## 5. After Round 11 lands

When Round 11 closes:

- **pkg55-B' Session N+1** done — shadow/miss/terminate stages on CPU;
  growing-oracle expansion complete for all CPU wavefront stages. **CUDA-
  port sessions N+2..M ready to begin** (two-tier gate definition landed
  PR #320). This is the critical path to the **viewport-parity acceptance
  gate** (CUDA pan-frame p99 ≤ 1.2× Cycles-CUDA on the pkg81 harness
  scene) — the still-unmet competitive claim that pkg55 Phase B now
  formally owns.
- **pkg55-B' Sessions N+2..M** in flight or partially done — multi-
  session CUDA port (~4 weeks total per spec Phase B estimate). Session
  N+2 pins ULP/p99.9/SSIM thresholds; later sessions port one material-
  type shade kernel each. When complete: **viewport-parity claim
  closes** and Pillar 5 is fully done.
- **Blender addon remediation** — pkg94 done (Round 10, PR #304); pkg95
  ∥ pkg96 in flight or done (second tier). All three specs filed and
  dispatchable; no open owner decision on the addon track.
- **pkg100** (optional, third tier) — .blend import AttributeError
  fixed; pkg76 §3.5 CSV follow-up (Classroom/Junkshop/BMW27 RTX parity
  rows) unblocked. **Explicitly DEPRIORITIZED** per owner decision —
  pick up only if CUDA-port sessions stall or after they complete.
- **pkg44** done (Round 10) — Pillar 4 has four emission models
  (synchrotron, slim disk, ADAF, thermal/blackbody); real astrophysical
  scenes are composable. Pillar 4 ~50%.
- **pkg99** in flight or done (second tier) — ADAF quasi-spherical glow
  re-investigation (RTX visual gate); pkg44 wiring correct but visual
  gate only partial.
- **pkg89 Phase B** in flight or done — dedicated lights usable from
  the Blender addon end-to-end; pkg86 Light Tree fully unblocked.
- **pkg90** (optional, third tier) — hardware-verifier build-env
  bootstrap; orchestrator HW gate for unattended operation.

Bump this report when pkg55-B' CUDA-port sessions N+2..M complete
(viewport-parity claim closure) or when a new major pillar milestone is
reached.
