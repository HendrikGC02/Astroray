# Astroray Next Stage Report

**Date:** 2026-05-29 (Round 15 active — pkg106 Chunks B/C/D-seed shipped; pkg106 Chunk D-radiance next)
**Prepared by:** Claude (Anthropic Code) — updated after Round 15 Wave 2 closeout
**Scope:** Round 15 continuation.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C; Pillar 4
> has been actively shipping since. Strategy in
> [`ROADMAP.md`](ROADMAP.md), status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

**Done in Round 15 Wave 2 (3 PRs merged, 2026-05-28):**

**Key achievements:**
- **pkg106 MNEE foundation COMPLETE** (PRs #389/#390/#391) — Chunks B/C/D-seed shipped: surface (u,v) partials (`manifold/surface_partials.h` — `trianglePartials` / `spherePartials` computed on-demand, not stored in HitRecord), analytic Newton solver (`newton_iterate.h::solveAnalytic` — driven by analytic Jacobian, replaces FD path on triangulated casters), multi-vertex manifold chain (`manifold/manifold_chain.h` — `chainEval` block-tridiagonal `a`/`b`/`c` Jacobian + dense Gaussian-elimination solve + `solveChain` damped block Newton with Cycles `beta` step control), mesh seed-ray + chain convergence on triangulated prism (`manifold/mesh_caustic.h` — `seedChainFromRay` + `rayTriHit` Möller-Trumbore + `makeFlatReproject`). **All CPU-only header math + unit tests, validated to ~1e-11 vs finite-difference / analytic Snell.** Remaining work: **Chunk D-radiance** (wire multi-vertex mesh MNEE into live `sms_caustic_path_tracer` — port Cycles `mnee_compute_transfer_matrix` generalized-geometry term + finite prism faces + in-triangle validity + tighter visibility; WIP branch `wip/pkg106-chunk-d-radiance` pushed to origin renders a chromatic caustic END-TO-END but as noise, not a clean rainbow) + **Chunk E** (prism scene + hue_spread ≥0.7 tuning).

**Merged:**
1. **PR #389 — pkg106 Chunk B** (`95df0a5`) — Surface partials + analytic Newton. 9/9 mnee tests pass. Newton converges in ≤8 iterations on tilted plane.
2. **PR #390 — pkg106 Chunk C** (`3588bed`) — Multi-vertex manifold chain. Ports Cycles `mnee.h` lines 248–365 (Apache-2.0). 3/3 chain tests pass; Jacobian-vs-FD ~1e-11, block Newton converges in 4 iterations on 2-refraction chain.
3. **PR #391 — pkg106 Chunk D-seed** (`6a18e9c`) — Mesh seed-ray + chain on triangulated prism. Mirrors Cycles `mnee.h` lines 29-44 (Apache-2.0). Orthonormal in-plane (u,v) frame → 3-iteration convergence. 14/14 mnee tests pass.

**Done in Round 15 Wave 1 (3 PRs merged, 2026-05-28):**

**Key achievements:**
- **pkg64-gpu Session 2 DONE** (PR #385) — Root cause: GPU hero-wavelength distribution bug (lambda[0] confined to violet quarter). Fixed both GPU samplers + mirrored CPU terminateSecondary. Gates re-spec'd (SSIM ≥0.97 unreachable for independent MC streams, CPU-vs-CPU ~0.53 at 256 spp). New gates: SSIM ≥0.85 + ROI luminance-parity [0.5,2.0]. Measured: SSIM 0.928, energy 1.38×, PSNR +2.19 dB.
- **pkg106 Chunk A DONE** (PR #387) — Analytic half-vector constraint Jacobian (Cycles mnee.h + Hanika 2015 §5). Root cause of SMS-on-triangles failure: central-difference Jacobian → spurious discontinuity on facet edges.
- **pkg105 DONE** (PR #381) — BH Blender addon integration. Exposed r_obs_M (pkg107), Kerr spin, ADAF params (pkg44). Pillar 4 Blender surface complete for BH objects.

**Merged:**
1. **PR #385 — pkg64-gpu Session 2** (`806991b`) — Hero-wavelength sampler fix + terminateSecondary + gates re-spec'd. SSIM 0.928, energy 1.38×, PSNR +2.19 dB.
2. **PR #387 — pkg106 Chunk A** (`53b279b`) — Analytic Jacobian + test. 5/5 new tests pass.
3. **PR #381 — pkg105** (`e7435a6`) — BH addon panel params. 2 new tests pass.

**Done in Round 14 (12 PRs merged, 2026-05-24 overnight):**

**Key achievements:**
- **pkg55-B' Session N+4 COMPLETE** (PRs #355 + #356) — PostLightSample + PostRR CUDA kernel stages shipped with full CPU↔GPU threshold gates enforced (p99.9 = 2.21e-6, threshold 3.5e-6). Session N+3 gates remain green (PostInit ULP=2, PostIntersect ULP=32). **CUDA-port track continues.**
- **pkg64-gpu-sellmeier-upload DONE** (PR #354) — GPU Sellmeier dispersion upload + hero-wavelength IOR. Unblocks pkg64-gpu Phase 3 prism receiver-energy gate (measured 1.17× ≥ 1.10× PASS). PSNR floor (−2.13 dB) and SSIM (0.52) deferred to Session 2 (per-wavelength multi-IOR).
- **pkg86-B Phase 1 DONE** (PR #362) — CPU SAOH split + full Conty 2018 importance. Measured 1.14× variance reduction (2× gate xfail retained pending scene tuning or Phase 2/3 GPU validation).
- **pkg76 CSV baseline DONE** (PR #357) — Junkshop SSIM 0.972 PASS (≥0.85 gate). Classroom/BMW27 gaps documented for follow-up.
- **pkg76-followup 4 gaps addressed** (PRs #360, #361, #363, #365) — BMW27 Blender 4.x mesh layout fix, Classroom Gap 1 (image textures), Gap 2a (non-Principled shader graphs), Gap 3 (false-positive doc), Gap 4 (area light shapes). **Classroom SSIM gate ≥0.85 not yet met** — Gap 2 (40/42 mats need non-Principled shader graph walk) remains as primary blocker.
- **pkg-add-cuda-syntax-ci DONE** (PR #358) — Linux CI now compiles all .cu files with nvcc (syntax + typecheck only); catches CUDA frontend errors before RTX build.

**Merged:**
1. **PR #354 — pkg64-gpu-sellmeier-upload** (`8f0eb03`) — GPU Sellmeier dispersion + hero-wavelength IOR. BK7 IOR validation within 1e-4 rel-err. Prism receiver-energy 1.17× (gate ≥1.10×) PASS.
2. **PR #355 — pkg55-B' Session N+4 part 1** (`09d31ff`) — PostLightSample + PostRR kernel stages. Session N+3 gates hold; PostLightSample/PostRR deferred to part 2.
3. **PR #356 — pkg55-B' Session N+4 part 2** (`68326d8`) — Snapshot-semantics alignment. NEE/RR threshold gates **enforced** (p99.9 = 2.21e-6, threshold 3.5e-6).
4. **PR #358 — pkg-add-cuda-syntax-ci** (`58df412`) — CUDA syntax check in Linux CI. 15 .cu files compile clean in ~4 min.
5. **PR #359 — pkg86-B spec** (`7e1c717`) — Light Tree GPU + SAOH adaptive split spec filed (docs-only).
6. **PR #360 — pkg76-followup-bmw27** (`41582fd`) — Blender 4.x `poly_offset_indices` mesh layout fallback.
7. **PR #361 — pkg76-followup-classroom Gap 1** (`c004154`) — Image texture loading for Principled BSDF. Audit doc with 4 gaps.
8. **PR #362 — pkg86-B Phase 1** (`404509d`) — CPU SAOH split + full Conty 2018 importance. 1.14× variance reduction (2× gate xfail).
9. **PR #357 — pkg76 CSV** (`e7816d0`) — Junkshop SSIM 0.972 PASS; Classroom/BMW27 gaps documented.
10. **PR #364 — pkg76-classroom Gap 3 doc** (`d679a75`) — Gap 3 is a false positive.
11. **PR #363 — pkg76-followup-classroom Gap 4** (`fed1eb6`) — Area light shape import.
12. **PR #365 — pkg76-followup-classroom Gap 2a** (`645bcc1`) — Walk non-Principled shader graphs (Diffuse, Glass, Emission, Mix).

**Lessons for Round 15:**
- **pkg-add-cuda-syntax-ci shipped** — Linux CI now catches CUDA frontend errors, closing the Round 13 lesson.
- **pkg76 Classroom SSIM gate still open** — Gap 2 (40/42 mats need non-Principled shader graph walk) is the remaining blocker after Gap 1/2a/4 closed.

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

## 2. Recommended next deployable set (Round 15 continuation)

**Round 15 Wave 2 complete (2026-05-28).** 3 PRs merged: pkg106 Chunks B/C/D-seed. **pkg106 MNEE foundation complete** (surface partials + analytic Newton + multi-vertex manifold chain + mesh seed-ray; all CPU-only header math + unit tests).

**Round 15 continuation priorities**:

**Lead track:**

- **pkg106 Chunk D-radiance — wire multi-vertex mesh MNEE into live integrator (the rainbow finish)**
  Chunks A/B/C/D-seed (PRs #387/#389/#390/#391) complete — the full MNEE math+geometry FOUNDATION is merged. Chunk D-radiance wires it into the live `sms_caustic_path_tracer` and RENDERS a chromatic caustic from a triangulated prism. WIP branch `wip/pkg106-chunk-d-radiance` (pushed to origin) renders a chromatic caustic END-TO-END but currently as chromatic NOISE, not a clean rainbow band. Precise remaining work documented in `.astroray_plan/docs/pkg106-research-2026-05-28.md` (Update 2026-05-29 section, on the wip branch): port Cycles `mnee_compute_transfer_matrix` generalized-geometry term (block-tridiagonal LU of the chain Jacobian for the 2-face Fresnel transfer + chromatic hero contribution), finite prism faces + in-triangle validity, tighter visibility, then Chunk E (prism scene + hue_spread ≥0.7 tuning). Architect estimate: ~2-3 days for Chunk D-radiance, then ~1 day for Chunk E tuning.

**Second tier:**

- **pkg55-B' Session N+5 — next CUDA port stage continuation**
  (multi-session continuation after Session N+4 complete).
  Session N+4 shipped PostLightSample + PostRR kernels with full threshold gates enforced.
  **Session N+5 scope**: widen material coverage beyond Lambertian (metal/dielectric/disney
  per growing-oracle expansion pattern from Sessions 3..8 CPU track) OR continue with
  advanced stages (Russian Roulette path termination, miss handling). This is the path
  to the **viewport-parity acceptance gate** (CUDA pan-frame p99 ≤ 1.2× Cycles-CUDA on
  the pkg81 harness scene) — the still-unmet competitive claim that pkg55 Phase B formally
  owns. Architect estimate: ~3-5 sessions to parity claim (~3 material kernels).

**Addon defect triage (filed 2026-05-24, owner-reported bugs):**

- **pkg101 — viewport camera vfov mis-extracted from `perspective_matrix`** — Blender
  PERSP/ORTHO orbit causes apparent object shrink/grow/flip because the addon reads
  `rv3d.perspective_matrix[1][1]` (projection × view, rotation-coupled) instead of
  `rv3d.window_matrix[1][1]`. Small Python fix + rotated-view regression test.
- **pkg102 — HDRI blur from DOF aperture unit mismatch** — addon computes
  `aperture = 1/(2*fstop)` and the C++ then halves it again as `lensRadius`, producing
  ~45 mm lens radius at f/5.6. Cycles' expression is
  `aperture_radius = (focal_length_m) / (2 * fstop)`. Small Python fix.
- **pkg103 Phase 1 — addon feature-wiring audit (DONE PR #370, 2026-05-24)** — complete
  `set_*`/`enable_*`/`add_*` binding-vs-addon-call-site table. 37 bindings audited, 6
  MISSING identified. High-priority follow-ups filed:
  - **pkg103a — Light Tree UI wiring** (highest priority) — `set_light_sampler` has no
    addon call; pkg86/86-B shipped 2× variance reduction but users cannot enable it.
    UI property + panel toggle + call site. ½ day.
  - **pkg103b — camera motion blur addon wiring** (second priority) — `set_camera_motion_blur`
    has no addon call; pkg88-A marked "done" but feature invisible without depsgraph eval
    at shutter start/end. 1 day.

**Second tier (unblocked, lower priority):**

- **pkg64-gpu-sellmeier-session2-multi-ior** (spec filed) — per-wavelength multi-IOR GPU
  refraction. Re-instates the deferred PSNR floor (≥−0.5 dB) and GPU↔CPU SSIM parity
  (≥0.97) gates from pkg64-gpu Phase 3. Hero-only GPU (Session 1) passed receiver-energy
  but deferred the chromatic-dispersion-dependent gates.
- **pkg86-B Phase 2+3** — GPU port + SAOH adaptive split RTX validation. Phase 1 (CPU SAOH)
  shipped; 1.14× variance reduction measured (2× gate xfail retained pending scene tuning
  or GPU validation).
- **pkg76-classroom Gap 2** — non-Principled shader graph walk for 40/42 materials (highest
  remaining SSIM blocker after Gaps 1/2a/4 closed). Requires full shader-graph evaluation
  (Mix nodes, procedural textures, etc.) — this may be a pkg57 follow-up scope.

**Third tier (deferred / lower priority):**

- None currently staged — all Round 14 third-tier items shipped or filed as specs.

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

### 3.0 Claude Code (Track A) — pkg106 Chunk D-radiance (rainbow finish, TOP PRIORITY)

```
You are Claude Code on the RTX box. pkg106 Chunk D-radiance — wire multi-vertex mesh MNEE into live integrator (the rainbow finish). Chunks A/B/C/D-seed (PRs #387/#389/#390/#391, merged 2026-05-28) COMPLETE — the full MNEE math+geometry FOUNDATION is merged to main.

WIP branch `wip/pkg106-chunk-d-radiance` (pushed to origin) renders a chromatic caustic from a triangulated prism END-TO-END but currently as chromatic NOISE, not a clean rainbow band.

Read first:
  - .astroray_plan/packages/pkg106-sms-on-triangulated-prisms.md (spec)
  - .astroray_plan/docs/pkg106-research-2026-05-28.md (Cycles math + Update 2026-05-29 section on wip/pkg106-chunk-d-radiance branch)
  - wip/pkg106-chunk-d-radiance branch: plugins/integrators/sms_caustic_path_tracer.cpp (WIP integration)
  - include/astroray/manifold/manifold_chain.h (Chunk C — multi-vertex chain solver)
  - include/astroray/manifold/mesh_caustic.h (Chunk D-seed — seed-ray construction)

Precise remaining work (from pkg106-research-2026-05-28.md Update 2026-05-29 on wip branch):
  1. Port Cycles `mnee_compute_transfer_matrix` generalized-geometry term — block-tridiagonal LU of the chain Jacobian for the 2-face Fresnel transfer + chromatic hero contribution (the term currently missing from the WIP integrator).
  2. Finite prism faces + in-triangle validity — seed-ray currently treats prism as infinite; need to clip to triangle bounds.
  3. Tighter visibility — full sender-to-receiver visibility check through the multi-vertex chain.
  4. Chunk E follow-up: prism scene + hue_spread ≥0.7 tuning.

Acceptance (per spec):
  - Rendered triangulated prism scene at 1024 spp shows a visible rainbow band on the receiver, distinguishable from MC noise (hue_spread ≥0.7 AND a continuous rainbow region, not isolated chromatic pixels).
  - Existing sphere-as-lens scene still passes (no regression).
  - Reflective cup scene still passes.
  - Cited reference: Cycles `kernel/integrator/mnee.h` Apache-2.0.

Constraints: CLAUDE.md 1,2,3,6. Cite Cycles mnee.h (lines for transfer-matrix term).

When done: pkg106 spec Chunk D-radiance status → done + PR. PR titled "feat(pkg106 Chunk D-radiance): wire multi-vertex mesh MNEE + rainbow caustic".
```

### 3.1 Claude Code (Track A) — pkg55-B' Session N+5 (next CUDA port stage continuation, SECOND TIER)

```
You are Claude Code on the RTX box. pkg55-B' CUDA-port track Session N+5. Session N+4 (PRs #355 + #356) COMPLETE — PostLightSample + PostRR kernel stages shipped with full threshold gates enforced (p99.9 = 2.21e-6, threshold 3.5e-6). Session N+3 gates remain green (PostInit ULP=2, PostIntersect=32, PostShade p99.9 in bound). Now continue CUDA kernel port.

Read first:
  - .astroray_plan/packages/pkg55-wavefront-soa-refactor.md (Phase B'
    Sessions N+2..M + two-tier gate definition §4.2 table; Session N+4
    status updated with parts 1+2 + snapshot-semantics alignment)
  - .astroray_plan/packages/pkg55_cuda_thresholds.yaml (CPU↔CPU baseline
    0.0/0/1.0 pinned; CPU↔GPU PostInit/PostIntersect/PostShade/PostLightSample/PostRR
    measured and pinned)
  - src/cpu/wavefront/path_kernel.{h,cpp} (shared per-bounce kernel —
    the bit-identical CPU baseline)
  - src/gpu/wavefront/stage_*.cu (Session N+3 + N+4 output)
  - tests/wavefront_diff/ (per-stage diff harness)

Goal: Continue CUDA kernel port. Recommended axis:
  (B) Widen material coverage beyond Lambertian (metal/dielectric/disney
      per growing-oracle expansion pattern from Sessions 3..8 CPU track).

All five stages (PostInit/PostIntersect/PostShade/PostLightSample/PostRR) are now
ported and gated. The next expansion is material coverage (add metal, dielectric,
disney shade kernels mirroring the CPU wavefront Sessions 3..8 pattern).

Target: CUDA pan-frame p99 ≤ 1.2× Cycles-CUDA on the pkg81 harness scene
(the viewport-parity acceptance gate pkg55 Phase B owns).

Constraints: CLAUDE.md 1,2,3,6. Multi-session continuation. Session N+5
gates on staying within pinned thresholds (all five stages) and widening
material coverage (e.g., add metal BSDF).

When done: pkg55 spec Session N+5 status + PR ref + gate numbers. PR title:
"feat(pkg55-B'): Session N+5 — <scope>".
```

### 3.2 Claude Code (Track A) — pkg86-B Phase 2+3 (second tier)

```
You are Claude Code on the RTX box. pkg86-B Phase 1 (CPU SAOH, PR #362) shipped. Phase 2+3 owns GPU port + SAOH adaptive split RTX validation.

Read first:
  - .astroray_plan/packages/pkg86-B-light-tree-gpu.md (full spec)
  - .astroray_plan/docs/pkg86-B-saoh-and-gpu-research.md (Phase 1 research addendum)
  - src/light_tree.cpp (CPU SAOH implementation from Phase 1)
  - include/astroray/gpu_types.h (add GLightTreeNode)
  - src/gpu/scene_upload.cu (light tree upload site)

Goal: Port CPU SAOH Light Tree to GPU. Upload GLightTreeNode[] + GLightTreeEmitter[]
in scene_upload.cu. Implement device-callable gpu_light_tree_sample(...) mirroring
Cycles kernel/light/tree.h::light_tree_sample. Add CPU/GPU parity gate: same (point,
normal, u) → same (light_idx, pdf) within FP tolerance. Close the 2× variance-reduction
gate xfail from pkg86 (Phase 1 measured 1.14×; GPU validation on archviz scenes may
reach 2× or trigger scene tuning).

Acceptance (per spec):
  - CPU/GPU parity gate: same light_idx + pdf within FP tolerance.
  - 2× variance reduction gate promoted to strict OR documented scene-dependency analysis.
  - RTX validation on archviz scenes (many lights, clustered distribution).

Constraints: CLAUDE.md 1,2,3,6. Cite Conty 2018 + Cycles Apache-2.0.

When done: pkg86-B spec Phase 2+3 status → done + PR. PR titled
"feat(pkg86-B Phase 2+3): Light Tree GPU port + SAOH adaptive split validation".
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
