# Astroray Next Stage Report

**Date:** 2026-05-23 (Round 14 pickup — Round 13 complete; pkg55-B' Session N+4 continuation is top live track)
**Prepared by:** Claude (Anthropic Code) — updated after Round 13 closeout
**Scope:** Round 14 pickup set.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C; Pillar 4
> has been actively shipping since. Strategy in
> [`ROADMAP.md`](ROADMAP.md), status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

**Done in Round 13 (9 PRs merged + 1 in-flight, 2026-05-22→2026-05-23):**

**Key achievements:**
- **Pillar 1 (CUDA port) major step:** pkg55 CPU↔GPU PostInit gate **closed at ULP=2** (vs threshold 4). PostIntersect bounded at 32 ULP (pinned 64). The 5-round build-fix saga (#343) + 9-round threshold-gate evolution (#349) was the round's hardest-fought win.
- **Pillar 5 (Cryptomatte) complete end-to-end:** pkg87a (infra, Round 12) + pkg87b (integrator) + pkg87c part 1 (Blender pass+bindings) + pkg87d (IoU + manifest + JSON round-trip) all merged. IoU 0.85 gate; measured 0.977–0.984.
- **pkg64-gpu Phase 2 + Phase 3 both shipped.** Hardware acceptance for Phase 3 prism scenes blocked on new `pkg64-gpu-sellmeier-upload` spec.
- **Final HW sweep on `0c2cd62`:** 1097 tests pass; pkg55 CPU↔GPU gates pass at pinned thresholds; visual renders clean.

**Merged:**
1. **PR #344 — pkg87b** (integrator integration): 7/7 CPU integrators + GPU megakernel instrumented per Cycles weight model.
2. **PR #343 — pkg55-B' Session N+3 part 2** (CUDA kernels + snapshot bindings): `stage_intersect_session_n3.cu` + `stage_shade_lambertian.cu`. 5 rounds of build fixes.
3. **PR #345 — pkg87c part 1** (Cryptomatte Blender pass + bindings): sort/normalise + dynamic pass registration + RenderResult packing.
4. **PR #346 — pkg55-B' Session N+3 part 2b** (CPU↔GPU threshold harness): extends `measure_thresholds.py`, un-skips gate.
5. **PR #348 — pkg64-gpu Phase 2** (megakernel SMS integration): wires device SMS attempt into both megakernels.
6. **PR #349 — pkg55-B' CPU/GPU PostInit gate** (RNG + hero + diff harness): PostInit ULP=2, PostIntersect=32, PostShade in bound.
7. **PR #351 — pkg55-followup** (triangle normal shortcut): flat-shaded triangle shortcut active; ULP=32 unchanged.
8. **PR #347 — pkg87d** (Cryptomatte acceptance gate): IoU 0.977–0.984; manifest + JSON round-trip.
9. **PR #350 — pkg64-gpu Phase 3** (acceptance gates + caustics toggle): test infrastructure + toggle wiring; HW blocked on Sellmeier.

**Lessons for Round 14:**
- **Linux CI doesn't build CUDA** — pkg87b's broken CUDA paths shipped to main and bit pkg55 #343 (5 build-fix rounds) + pkg64-gpu Phase 2. Worth `pkg-add-cuda-syntax-ci` follow-up.

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

## 2. Recommended next deployable set (Round 14)

**Round 13 complete (2026-05-23).** 9 PRs merged + 1 in-flight: pkg87b/c/d Cryptomatte end-to-end, pkg55-B' Session N+3 parts 1/2/2b + RNG/hero/harness fixes + triangle-normal-shortcut, pkg64-gpu Phase 2+3. **CPU↔GPU PostInit gate CLOSED at ULP=2.** PostIntersect bounded at 32 ULP (pinned 64). Cryptomatte IoU 0.977–0.984 (0.85 gate). **CUDA-port track continues.**

**Round 14 priorities** (owner decision 2026-05-23 evening: **interleave Sellmeier first**, then resume the CUDA-port lead track):

**Top priority (1-week diversion before resuming CUDA-port lead):**

- **pkg64-gpu-sellmeier-upload** (spec filed in PR #352, merged on Round-13 closeout)
  — GPU upload of Sellmeier dispersion coefficients. Unblocks pkg64-gpu Phase 3 hardware
  baseline-pinning (prism rainbow + mirror-pool acceptance scenes), so Round 14's closeout
  HW sweep can include a GPU dispersion render alongside Session N+4 progress. BK7 prism
  currently falls back to const IOR=1.5; no rainbow baseline-pinnable. Estimated ~1 week.
  **Owner directive: ship this BEFORE Session N+4.**

**Lead track (resumes after Sellmeier ships):**

- **pkg55-B' Session N+4 — next CUDA port stage continuation**
  (multi-session continuation after Session N+3 complete).
  Session N+3 shipped PostInit (ULP=2 PASS), PostIntersect (32 ULP, pinned 64), PostShade
  (p99.9 in bound). **Session N+4 scope**: continue CUDA kernel port for remaining stages
  (PostLightSample / PostRR) or widen material coverage beyond Lambertian (metal/dielectric/
  disney per growing-oracle expansion pattern). This is the path to the **viewport-parity
  acceptance gate** (CUDA pan-frame p99 ≤ 1.2× Cycles-CUDA on the pkg81 harness scene) —
  the still-unmet competitive claim that pkg55 Phase B formally owns. Architect estimate:
  ~4-6 sessions to parity claim (2 stage ports + ~4 material kernels).

**Second tier (unblocked, lower priority):**

- **pkg86-B Light Tree GPU + adaptive split** — pkg86 CPU done but 2× variance-reduction
  gate xfailed strict=False; pkg86-B owns GPU port + SAOH adaptive splitting to close
  the strict gate. Still needs a spec filed.
- **pkg76 CSV** — Classroom / Junkshop / BMW27 parity rows on RTX (~½ day). **Unblocked
  since pkg100** (Round 12).

**Third tier (deferred / lower priority):**

- **pkg-add-cuda-syntax-ci** (not yet spec'd) — Linux CI matrix job building CUDA paths
  to catch syntax errors before main. Round 13 Lesson: pkg87b's broken CUDA paths shipped
  to main (Linux CI green) and bit pkg55 #343 (5 build-fix rounds) + pkg64-gpu Phase 2.

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

### 3.0 Claude Code (Track A) — pkg64-gpu-sellmeier-upload (TOP PRIORITY 2026-05-24, ship BEFORE Session N+4)

```
You are Claude Code on the RTX box. pkg64-gpu-sellmeier-upload — owner directive: ship this BEFORE pkg55-B' Session N+4. Unblocks pkg64-gpu Phase 3 hardware baseline-pinning (prism rainbow + mirror-pool acceptance scenes).

Read first:
  - .astroray_plan/packages/pkg64-gpu-sellmeier-upload.md (full spec; ~1 week effort)
  - include/astroray/gpu_types.h (GMaterial struct — add GDispersion sub-struct)
  - src/gpu/scene_upload.cu (material-pack code that currently rejects Sellmeier)
  - include/astroray/gpu_materials.h / gpu_bsdf.h (dielectric BSDF — branch on mat.isDispersive)
  - tests/test_pkg64_gpu_phase3_*.py (the three tests currently blocked on this)

Goal: GPU upload of Sellmeier dispersion coefficients (B1,B2,B3,C1,C2,C3) + device-callable gpu_sellmeier_ior(coeffs, lambda_nm) per Sellmeier 1871 closed form. Hero-channel-only refraction is sufficient for Session 1 (per-wavelength multi-IOR is non-goal). After this lands, pkg64-gpu Phase 3 prism receiver-energy, PSNR-floor, and GPU↔CPU SSIM parity gates all run end-to-end on RTX.

Acceptance (per spec):
  - gpu_sellmeier_ior matches Schott BK7 datasheet at 587.6/486.1/656.3 nm within 1e-4 rel-err.
  - scene_upload.cu accepts Sellmeier materials without raising.
  - Three Phase 3 HW gates pass: receiver-energy ≥1.10×, PSNR-floor delta ≥−0.5 dB, GPU↔CPU SSIM ≥0.97.
  - Existing scalar-IOR dielectric path remains bit-identical (no regression).

Constraints: CLAUDE.md 1,2,3,6. Cite Sellmeier 1871 (public domain), Cycles closure_principled.h (Apache-2.0), PBRT-v4 DielectricBxDF (Apache-2.0). Watch the MinGW large-struct-by-value memo (`mingw_large_struct_byval`) — GDispersion is 24 B but GMaterial growth may push the total over 32 B; pass-by-const-ref where it appears as a parameter.

When done: pkg64-gpu-sellmeier-upload spec status → done + PR. PR titled
"feat(pkg64-gpu): GPU Sellmeier dispersion upload + per-wavelength IOR (hero)".
```

### 3.1 Claude Code (Track A) — pkg55-B' Session N+4 (next CUDA port stage continuation, RESUMES AFTER SELLMEIER)

```
You are Claude Code on the RTX box. pkg55-B' CUDA-port track Session N+4. Session N+3 (PRs #338/#343/#346/#349/#351) COMPLETE — PostInit ULP=2 PASS, PostIntersect=32 (pinned 64), PostShade in bound. Now continue CUDA kernel port.

Read first:
  - .astroray_plan/packages/pkg55-wavefront-soa-refactor.md (Phase B'
    Sessions N+2..M + two-tier gate definition §4.2 table; Session N+3
    status updated with parts 1/2/2b + RNG/hero/harness fixes)
  - .astroray_plan/packages/pkg55_cuda_thresholds.yaml (CPU↔CPU baseline
    0.0/0/1.0 pinned; CPU↔GPU PostInit/PostIntersect/PostShade measured
    and pinned)
  - src/cpu/wavefront/path_kernel.{h,cpp} (shared per-bounce kernel —
    the bit-identical CPU baseline)
  - src/gpu/wavefront/stage_init.cu + stage_intersect_session_n3.cu +
    stage_shade_lambertian.cu (Session N+3 output)
  - tests/wavefront_diff/ (per-stage diff harness)

Goal: Continue CUDA kernel port. Two expansion axes available:
  (A) Port remaining stages (PostLightSample / PostRR) to CUDA, OR
  (B) Widen material coverage beyond Lambertian (metal/dielectric/disney
      per growing-oracle expansion pattern from Sessions 3..8 CPU track).

Recommend Axis A (stage completion) before Axis B (material widening) to
close the full per-stage diff harness coverage and prove the two-tier
gate holds across all five stages before widening material surface.

Target: CUDA pan-frame p99 ≤ 1.2× Cycles-CUDA on the pkg81 harness scene
(the viewport-parity acceptance gate pkg55 Phase B owns).

Constraints: CLAUDE.md 1,2,3,6. Multi-session continuation. Session N+4
gates on staying within pinned thresholds (PostInit/PostIntersect/PostShade)
and measuring new stages (PostLightSample/PostRR if Axis A).

When done: pkg55 spec Session N+4 status + PR ref + gate numbers (new
stage thresholds if Axis A, or new material coverage if Axis B). PR title:
"feat(pkg55-B'): Session N+4 — <scope>".
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
| pkg55-B' Session N+4..M | `src/gpu/*`, `src/cpu/wavefront/path_kernel.{h,cpp}` (shared), `tests/wavefront_diff/*`, pkg55 spec, STATUS.md |
| pkg64-gpu-sellmeier-upload | `src/gpu/scene_upload.cu`, `include/astroray/gpu_types.h`, `plugins/materials/*` (Sellmeier sources), pkg64-gpu-sellmeier-upload spec, STATUS.md |
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

**Recommended merge order (owner directive 2026-05-23, reaffirmed for Round 14 pickup):** **pkg64-gpu-sellmeier-upload** (TOP PRIORITY — ship before Session N+4) → **pkg55-B' Session N+4** (CUDA-port lead resumes) → **Sessions N+5..M** (multi-session CUDA port continues) → **pkg86-B** (GPU Light Tree, needs spec) → **pkg76 CSV** (RTX parity rows).

---

## 5. After Round 13 lands

When Round 13 closes:

- **pkg55-B' Session N+3 COMPLETE** — PostInit ULP=2 (threshold 4) PASS, PostIntersect=32 (pinned 64) PASS, PostShade p99.9 in bound. **Session N+4** continues the CUDA port (~4 weeks total per spec Phase B estimate). This is the critical path to the **viewport-parity acceptance gate** (CUDA pan-frame p99 ≤ 1.2× Cycles-CUDA on the pkg81 harness scene) — the still-unmet competitive claim that pkg55 Phase B formally owns.
- **Cryptomatte end-to-end complete** — pkg87a (infra, Round 12) + pkg87b (integrator integration) + pkg87c part 1 (Blender pass+bindings) + pkg87d (IoU + manifest + JSON round-trip) all shipped. IoU 0.977–0.984 (0.85 gate).
- **pkg64-gpu Phase 2 + Phase 3 both shipped** — megakernel SMS integration + acceptance gates + caustics toggle wiring complete. Hardware baseline-pinning blocked on **pkg64-gpu-sellmeier-upload** (new spec filed in PR #352; Sellmeier dispersion not GPU-uploadable).
- **pkg86 Light Tree** (CPU median-split, Round 12) done — 2× variance-reduction gate xfailed strict=False; pkg86-B (GPU + adaptive split) queued for second tier.
- **Orchestrator fully autonomous** — pkg90/97/98 done (Round 11). HW gate runs unattended, IMPL_CAP no longer stalls, Track-A fixes require different-model SIGN-OFF/BLOCK.
- **pkg100** (Round 12) done — .blend import AttributeError fixed; pkg76 §3.5 CSV follow-up unblocked.
- **Pillar 4 ~50%** — pkg40/41/42/43/44/47/99 done; synchrotron, slim disk, ADAF, thermal/blackbody emission all shipped.
- **pkg89 done** (Round 11) — dedicated lights usable from Blender addon end-to-end; pkg86 Light Tree fully unblocked.

**Round 14 carry-forward:**
- **pkg55-B' Session N+4** (CUDA port continuation, top track)
- **pkg64-gpu-sellmeier-upload** (unblocks Phase 3 HW numbers, second tier)
- **pkg86-B** (GPU Light Tree + adaptive split, second tier)
- **pkg76 CSV** (RTX parity rows, second tier, unblocked)

Bump this report when pkg55-B' CUDA-port sessions complete (viewport-parity claim closure) or when a new major pillar milestone is reached.
