# Astroray Next Stage Report

**Date:** 2026-05-22 (Round 13 pickup — Round 12 complete; pkg55-B' Session N+3 part 2 is top live track)
**Prepared by:** Claude (Anthropic Code) — updated after Round 12 closeout
**Scope:** Round 13 pickup set.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C; Pillar 4
> has been actively shipping since. Strategy in
> [`ROADMAP.md`](ROADMAP.md), status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

**Done in Round 12 (6 PRs merged + 1 direct-to-main, 2026-05-22):**

- **pkg87a Cryptomatte infrastructure** (PR #337) — MurmurHash3 + hash_to_float + crypto_insert/sort_ranks + EXR writer + GPU hash plumbing. Cited: Friedman 2015 + Cycles Apache-2.0 + alShaders2 + smhasher PD. Infra-only scope; integrator writes (pkg87b) and Blender acceptance (pkg87c) are explicit follow-ups.
- **pkg86 Light Tree** (PR #340) — Conty 2018 + Cycles Apache-2.0 CPU median-split tree. Single-light PSNR=100dB, 17ms/1000-light build, composability green. **2× variance-reduction gate xfailed strict=False** — 64-light tree sampler shows visible firefly noise vs power sampler; adaptive splitting (pkg86-B GPU + SAOH) queued.
- **pkg100 .blend importer camera-intrinsics fix** (PR #339 + #341) — Axis 2: return intrinsics up call chain (no pybind11 ABI change). `_blend_import_stats` stashed best-effort. **bpy-free regression test** added. **Unblocks pkg76 §3.5 CSV rows** (Classroom / Junkshop / BMW27 RTX parity).
- **pkg55-B' Session N+3 part 1** (PR #338) — first CUDA shade kernel scaffolding: `stage_init.cu` rewritten, PCG32 `__device__` port, GPU PostInit snapshot download, `measure_thresholds.py --mode gpu_port`. **Deferred to N+3 part 2**: full ULP/p99.9 measurement, `stage_intersect`, `stage_shade_lambertian`, full pkg64-gpu gate #1 SMS rel-err.
- **Direct-to-main commit 91bbaf5** — infra fixes: `classify.py` head-SHA guard; G4 spot cone camera-in-plane fix + photometric threshold relaxation.

**Done in Round 11 (9 PRs merged, 2026-05-21 + 2026-05-22, historical):**

- **Orchestrator-meta complete**: pkg90 (hw-verifier buildenv, PR #333), pkg97 (merged-worktree auto-GC, PR #331), pkg98 (independent-review gate, PR #332). **Orchestrator now fully autonomous** — HW gate runs unattended, IMPL_CAP no longer stalls after 2 ships, Track-A fixes require different-model SIGN-OFF/BLOCK before push.
- **pkg55-B' Session N+1** (PR #327) — env-map miss + complete CPU wavefront pipeline. Bit-identity gate PASS (max abs diff 0.0). **CPU-only growing-oracle track complete.**
- **pkg55-B' Session N+2** (PR #334) — threshold pinning + CUDA-port preflight. Bit-identity 0.0/0/1.0 CPU↔CPU baseline pinned in `pkg55_cuda_thresholds.yaml`. CPU↔GPU thresholds are placeholders for Session N+3. Two-tier gate enforcement active.
- **pkg64-gpu Phase 1** (PR #323) — device SMS attempt + caster flag. RTX 5070 Ti gate #2 + #3 PASS. Gate #1 (CPU↔GPU rel-err) **folded into pkg55-B' Session N+3** per owner decision instead of filing Phase 1.1 follow-up.
- **pkg99 ADAF wiring fix** (PR #335) — removed `* exposureScale` from volumetric emission path. Jet `intensity_scale` rescaled 1e28→5e13. Regression test asserts ADAF ON ≠ OFF. ADAF should now glow at spec `intensity_scale=1e30`; empirical RTX visual tuning is a separate follow-up.
- **pkg89 Phase B** (PR #317) — Cycles-parity fixes per parity report: geometric `1/area` normalize, kM1PiF factor, Hermite Spot cone falloff, white-tint blackbody short-circuit. G2 D65 gate relaxed <10%→<12% with TODO citing spectrum-pipeline limitation. **Blender addon can now use dedicated lights end-to-end; pkg86 Light Tree fully unblocked.**
- **Direct-to-main commits** (cd32ddb, c8fa652) — `classify.py` treats PARTIAL hw_result like FAIL; `codex-implementer.md` adds liveness check + Opus fallback; `render_standup` surfaces `impl_dispatches` escalations; pkg55 spec amended to fold pkg64-gpu gate #1 into Session N+3.

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

## 2. Recommended next deployable set (Round 13)

**Round 12 complete (2026-05-22).** 6 PRs merged + 1 direct-to-main: pkg87a Cryptomatte infra, pkg86 Light Tree (CPU median-split, pkg86-B GPU deferred), pkg100 .blend importer fix (unblocks pkg76 §3.5 CSV), pkg55-B' Session N+3 part 1 (CUDA shade scaffolding). **CUDA-port track continues.**

**Round 13 priorities** (owner direction: **CUDA-port path leads** to close the still-unmet viewport-parity claim):

**Top priority (lead track — CUDA-port path):**

- **pkg55-B' Session N+3 part 2 — full CUDA Lambertian shade + intersect + pkg64-gpu gate #1**
  (multi-session, ~4 weeks total per spec Phase B estimate; part 1 complete). **Now the
  top live work.** Session N+3 part 1 shipped the CUDA shade scaffold (`stage_init.cu` rewritten, PCG32 `__device__` port, GPU PostInit snapshot download). **Part 2 scope**: full ULP/p99.9 measurement at all stages (PostInit/PostIntersect/PostShade/PostLightSample/PostRR), `stage_intersect`, `stage_shade_lambertian`, full pkg64-gpu gate #1 SMS CPU↔GPU rel-err (owner decision folded gate #1 into Session N+3 instead of filing Phase 1.1 follow-up). This is the path to the **viewport-parity acceptance gate** (CUDA pan-frame p99 ≤ 1.2× Cycles-CUDA on the pkg81 harness scene) — the still-unmet competitive claim that pkg55 Phase B formally owns.

**Second tier (unblocked, lower priority than CUDA-port track):**

- **pkg87b/pkg87c Cryptomatte** — pkg87a infra done; integrator writes (pkg87b) and Blender acceptance (pkg87c) ready to implement. Known gaps captured in pkg87b spec: `Renderer.set_material_name` Python binding missing, `get_render_pass_buffer` doesn't surface crypto keys yet.
- **pkg86-B Light Tree GPU + adaptive split** — pkg86 CPU done but 2× variance-reduction gate xfailed strict=False; pkg86-B owns GPU port + SAOH adaptive splitting to close the strict gate.
- **pkg76 CSV** — Classroom / Junkshop / BMW27 parity rows on RTX (~½ day). **Now unblocked** (pkg100 done).

**Third tier (deferred / lower priority):**

- **pkg64-gpu Phase 2** (megakernel integration) → **Phase 3** (gate #1 now folded into pkg55-B' Session N+3 per owner decision).

**Known flakes (not blocking):**

- **Issue [#298](https://github.com/HendrikGC02/Astroray/issues/298)** —
  ReSTIR `test_spatial_reduces_mse` MC-noise on a strict inequality;
  recommend a seed-pin or a tolerance/seed-averaging margin.
- **Issue #276** — `test_disney_clearcoat_adds_gloss` chronic flake +
  suspected clearcoat correctness defect; owner triage recommended.

**Owner decisions — all resolved:**

- Round 11/12 direction: **CUDA-port path leads** (confirmed 2026-05-17, reaffirmed through Round 12). pkg100 .blend importer fix deprioritized relative to wavefront work (now done in Round 12, unblocking pkg76 CSV for future pickup).
- pkg64-gpu gate #1: **folded into pkg55-B' Session N+3** (confirmed 2026-05-21 direct-to-main commit c8fa652) instead of filing separate Phase 1.1 package. Session N+3 part 2 will measure SMS CPU↔GPU rel-err inline.

---

## 3. Drop-in prompts per agent

### 3.1 Claude Code (Track A) — pkg55-B' Session N+3 part 2 (full CUDA Lambertian + intersect + pkg64-gpu gate #1, TOP LIVE TRACK 2026-05-22)

```
You are Claude Code on the RTX box. pkg55-B' CUDA-port track Session N+3 part 2. Session N+3 part 1 (PR #338) shipped the CUDA shade scaffold; now measure full thresholds and complete Lambertian shade + intersect kernels.

Read first:
  - .astroray_plan/packages/pkg55-wavefront-soa-refactor.md (Phase B'
    Sessions N+2..M + two-tier gate definition §4.2 table)
  - .astroray_plan/packages/pkg55_cuda_thresholds.yaml (CPU↔CPU baseline
    0.0/0/1.0 pinned; CPU↔GPU placeholders to measure)
  - src/cpu/wavefront/path_kernel.{h,cpp} (shared per-bounce kernel —
    the bit-identical CPU baseline)
  - src/gpu/wavefront/stage_init.cu (Session N+3 part 1 output — rewritten
    init kernel, PCG32 device port, PostInit snapshot)
  - tests/wavefront_diff/ (per-stage diff harness)

Goal: (1) measure actual CPU↔GPU thresholds (ULP/p99.9/SSIM) at ALL stages (PostInit/PostIntersect/PostShade/PostLightSample/PostRR) — Session N+2 pinned CPU↔CPU baseline but CPU↔GPU thresholds are placeholders; (2) complete `stage_intersect` CUDA kernel; (3) complete `stage_shade_lambertian` CUDA kernel; (4) validate pkg64-gpu gate #1 SMS CPU↔GPU rel-err inline (owner decision folded into Session N+3). Maintain coalesced memory access; sort paths by material type before shade. Target: CUDA pan-frame p99 ≤ 1.2× Cycles-CUDA on the pkg81 harness scene (the viewport-parity acceptance gate pkg55 Phase B owns).

Constraints: CLAUDE.md 1,2,3,6. Multi-session (~4 weeks total per spec Phase B estimate). Session N+3 part 2 gates on measured thresholds + full intersect + shade kernels. Later sessions (N+4..M) gate on staying within those thresholds.

When done: pkg55 spec Session N+3 status + PR ref + gate numbers (ULP/p99.9/SSIM measured). PR title: "feat(pkg55-B'): Session N+3 part 2 — full Lambertian CUDA + intersect + threshold measurement + pkg64-gpu gate #1".
```

### 3.2 Claude Code (Track A) — pkg86 Light Tree (second tier)

```
You are Claude Code on the RTX box. pkg89 Phase A + Phase B done; `Light::orientationCone()` + `power()` accessors available. Ready to implement Light Tree.

Read first:
  - .astroray_plan/packages/pkg86-light-tree.md (Conty 2018 + Cycles Apache-2.0)
  - .astroray_plan/docs/pkg86-light-tree-research.md (if present)
  - include/astroray/light.h (Light interface with orientationCone(), power(), bounds())
  - src/integrators/path_tracer.cpp (NEE sampling site)

Goal: implement Conty 2018 Light Tree for many-lights importance sampling. CPU first; GPU follow-up pkg86-B. Use Light accessors from pkg89. Acceptance: measured improvement on many-lights scene (e.g., 100+ lights).

Constraints: CLAUDE.md 1,2,3,6. Cite Conty 2018 + Cycles Apache-2.0 references.

When done: pkg86 spec status -> done + PR. PR titled "feat(pkg86): Light Tree (Conty 2018, CPU)".
```

### 3.3 Claude Code (Track A) — pkg100 .blend importer camera-intrinsics fix (third tier, DEPRIORITIZED)

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

### 3.4 Codex (RTX hardware, small) — pkg76 CSV rows (third tier, blocked on pkg100)

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

**Recommended merge order:** **pkg55-B' Session N+3** (top priority, CUDA-port path lead) → **Sessions N+4..M** (multi-session CUDA port continues) ∥ **pkg86** (Light Tree, second tier) → **pkg87a/pkg87b/pkg87c** (Cryptomatte, second tier) → **pkg100** (third tier, deprioritized) → **pkg76 CSV** (third tier, blocked on pkg100) → **pkg64-gpu Phase 2/3** (later).

---

## 5. After Round 12 lands

When Round 12 closes:

- **pkg55-B' Session N+3** done — first CUDA shade kernel (Lambertian) ported, actual CPU↔GPU thresholds measured and pinned, pkg64-gpu gate #1 (CPU↔GPU rel-err) validated inline. **Sessions N+4..M continue** the CUDA port (~4 weeks total per spec Phase B estimate). This is the critical path to the **viewport-parity acceptance gate** (CUDA pan-frame p99 ≤ 1.2× Cycles-CUDA on the pkg81 harness scene) — the still-unmet competitive claim that pkg55 Phase B now formally owns.
- **pkg86 Light Tree** in flight or done (second tier) — Conty 2018 many-lights importance sampling, CPU first. Unblocked by pkg89 Phase A + Phase B accessors.
- **pkg87a/pkg87b/pkg87c Cryptomatte** in flight or done (second tier) — independent; ready to implement.
- **Orchestrator fully autonomous** — pkg90/97/98 done (Round 11). HW gate runs unattended, IMPL_CAP no longer stalls, Track-A fixes require different-model SIGN-OFF/BLOCK.
- **pkg100** (optional, third tier) — .blend import AttributeError fixed; pkg76 §3.5 CSV follow-up unblocked. **Explicitly DEPRIORITIZED** per owner decision — pick up only if CUDA-port sessions stall or after they complete.
- **Pillar 4 ~50%** — pkg40/41/42/43/44/47/99 done; synchrotron, slim disk, ADAF, thermal/blackbody emission all shipped. pkg99 ADAF wiring fix (Round 11) resolved `exposureScale` multiplication bug.
- **pkg89 done** (Round 11) — dedicated lights usable from Blender addon end-to-end; pkg86 Light Tree fully unblocked.

Bump this report when pkg55-B' CUDA-port sessions N+3..M complete (viewport-parity claim closure) or when a new major pillar milestone is reached.
