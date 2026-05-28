# Astroray Status

**Last updated:** 2026-05-28 (Round 15 partial: 3 PRs merged — pkg64-gpu Session 2, pkg106 Chunk A, pkg105).

## Round 15 partial closeout (3 PRs merged, 2026-05-28)

**Key achievements:**
- **pkg64-gpu Session 2 DONE** (PR #385) — Root cause: GPU hero-wavelength distribution bug (lambda[0] confined to violet quarter). Fixed both GPU samplers + mirrored CPU terminateSecondary. **Gates re-spec'd** (owner-adjudicated): SSIM ≥0.97 unreachable for independent MC streams (CPU-vs-CPU ~0.53 at 256 spp), new gates SSIM ≥0.85 + ROI luminance-parity [0.5,2.0]. Measured: SSIM 0.928, energy 1.38×, PSNR +2.19 dB. Test integrator mismatch fixed (GPU no-NEE vs CPU NEE). **Session 2 complete.**
- **pkg106 Chunk A DONE** (PR #387) — Analytic half-vector constraint Jacobian (Cycles mnee.h + Hanika 2015 §5). Root cause of SMS-on-triangles failure: newton_iterate.h central-difference Jacobian → spurious discontinuity on facet edges. Chunk A adds halfVectorConstraintJacobian + test. **Chunks B-E remain** (surface (u,v) partials, Newton wiring, triangulated prism scene with hue_spread ≥0.7).
- **pkg105 DONE** (PR #381) — Blender BH addon integration. Exposed r_obs_M (pkg107), Kerr spin, ADAF params (pkg44). **Pillar 4 Blender surface complete** for BH objects.

**Merged 2026-05-28:**
1. **PR #385 — pkg64-gpu Session 2** (`806991b`) — Hero-wavelength sampler fix + terminateSecondary + gates re-spec'd. SSIM 0.928 ≥0.85 PASS; energy 1.38× ≥1.045× PASS; PSNR +2.19 dB ≥−0.5 dB PASS.
2. **PR #387 — pkg106 Chunk A** (`53b279b`) — Analytic Jacobian + test. Analytic-vs-FD validation ~2e-7 (C++ float32) / ~2e-10 (Python float64). 5/5 new tests pass.
3. **PR #381 — pkg105** (`e7435a6`) — BH addon panel params. r_obs_M + spin + ADAF mdot_edd/electron_temp/beta_mag/r_inner/r_outer/flattening/alpha/s/intensity_scale. 2 new tests pass.

**Additional merges (test-only, no packages):**
4. **PR #386 — fix #298** (`f22d1cb`) — ReSTIR spatial-MSE flake: pinned reference seed (seed=0 std::random_device sentinel was re-randomising).
5. **PR #384 — fix #276** (`89f8fe7`) — Clearcoat test flake: pinned seed.

**In-flight / deferred:**
- **pkg55-B' Session N+5** — next CUDA-port stage continuation (metal/dielectric/disney shade kernels or RR/miss handling). Lead track per NEXT_STAGE_REPORT §2.
- **pkg106 Chunks B-E** — surface partials + Newton wiring + triangulated prism acceptance (hue_spread ≥0.7). In progress.

**Full standup:** (not yet committed).

---

## Round 14 closeout (12 PRs merged, 2026-05-24 overnight)

**Key achievements:**
- **pkg55-B' Session N+4 COMPLETE** (PRs #355 + #356) — PostLightSample + PostRR CUDA kernel stages shipped with full CPU↔GPU threshold gates enforced (p99.9 = 2.21e-6, threshold 3.5e-6). Session N+3 gates remain green (PostInit ULP=2, PostIntersect ULP=32). **CUDA-port track continues.**
- **pkg64-gpu-sellmeier-upload DONE** (PR #354) — GPU Sellmeier dispersion upload + hero-wavelength IOR. Unblocks pkg64-gpu Phase 3 prism receiver-energy gate (measured 1.17× ≥ 1.10× PASS). PSNR floor (−2.13 dB) and SSIM (0.52) deferred to Session 2 (per-wavelength multi-IOR): hero-only GPU lacks chromatic spread, so per-pixel error is dominated by spatial caustic divergence by construction.
- **pkg86-B Phase 1 DONE** (PR #362) — CPU SAOH split + full Conty 2018 importance. Measured 1.14× variance reduction (2× gate xfail retained pending scene tuning or Phase 2/3 GPU validation).
- **pkg76 CSV baseline DONE** (PR #357) — Junkshop SSIM 0.972 PASS (≥0.85 gate). Classroom/BMW27 gaps documented for follow-up.
- **pkg76-followup 4 gaps addressed** (PRs #360, #361, #363, #365) — BMW27 Blender 4.x mesh layout fix, Classroom Gap 1 (image textures), Gap 2a (non-Principled shader graphs), Gap 3 (false-positive doc), Gap 4 (area light shapes). **Classroom SSIM gate ≥0.85 not yet met** — Gap 2 (40/42 mats need non-Principled shader graph walk) remains as primary blocker.
- **pkg-add-cuda-syntax-ci DONE** (PR #358) — Linux CI now compiles all .cu files with nvcc (syntax + typecheck only); catches CUDA frontend errors before RTX build.

**Merged 2026-05-24:**
1. **PR #354 — pkg64-gpu-sellmeier-upload** (`8f0eb03`) — GPU Sellmeier dispersion + hero-wavelength IOR. BK7 IOR validation within 1e-4 rel-err. Prism receiver-energy 1.17× (gate ≥1.10×) PASS.
2. **PR #355 — pkg55-B' Session N+4 part 1** (`09d31ff`) — PostLightSample + PostRR kernel stages. Session N+3 gates hold; PostLightSample/PostRR deferred to part 2 due to snapshot-semantics mismatch.
3. **PR #356 — pkg55-B' Session N+4 part 2** (`68326d8`) — Snapshot-semantics alignment (CPU + GPU both capture `rec.point`). NEE/RR threshold gates **enforced** (p99.9 = 2.21e-6, threshold 3.5e-6). No UserWarning.
4. **PR #358 — pkg-add-cuda-syntax-ci** (`58df412`) — CUDA syntax check in Linux CI. 15 .cu files compile clean in ~4 min.
5. **PR #359 — pkg86-B spec** (`7e1c717`) — Light Tree GPU + SAOH adaptive split spec filed (docs-only).
6. **PR #360 — pkg76-followup-bmw27** (`41582fd`) — Blender 4.x `poly_offset_indices` mesh layout fallback (attribute storage path).
7. **PR #361 — pkg76-followup-classroom Gap 1** (`c004154`) — Image texture loading for Principled BSDF. Audit doc committed with 4 gaps classified.
8. **PR #362 — pkg86-B Phase 1** (`404509d`) — CPU SAOH split + full Conty 2018 importance. Measured 1.14× variance reduction (2× gate xfail retained).
9. **PR #357 — pkg76 CSV** (`e7816d0`) — Junkshop SSIM 0.972 PASS; Classroom/BMW27 gaps documented. SSIM env-var fix.
10. **PR #364 — pkg76-classroom Gap 3 doc** (`d679a75`) — Gap 3 is a false positive (spot light params already implemented since pkg76).
11. **PR #363 — pkg76-followup-classroom Gap 4** (`fed1eb6`) — Area light shape import (square/rect/disk/ellipse).
12. **PR #365 — pkg76-followup-classroom Gap 2a** (`645bcc1`) — Walk non-Principled shader graphs for base color (Diffuse, Glass, Emission, Mix).

**Direct-to-main infra fixes (Round 14 start):**
- `fix(orchestrator)`: `expire_closed` non-numeric ledger key crash.
- `fix(build)`: `build_cuda_worktree.bat` unescaped parens.
- `team-overnight` SKILL: team_name+name spawn requirement.
- 4 specs filed: pkg64-gpu-sellmeier-session2-multi-ior, pkg76-followup-classroom-fidelity, pkg86-B, pkg-add-cuda-syntax-ci.

**Deferred to Round 15:**
- **pkg64-gpu Session 2 (multi-IOR)** — per-wavelength GPU refraction (re-instates deferred PSNR/SSIM gates). Spec filed as pkg64-gpu-sellmeier-session2-multi-ior.
- **pkg86-B Phase 2+3** — GPU port + SAOH adaptive split RTX validation.
- **pkg76-classroom Gap 2** — non-Principled shader graph walk for 40/42 materials (highest remaining SSIM blocker).

**Full standup:** `.astroray_plan/docs/standup/2026-05-24.md`

## Round 13 closeout (9 PRs merged + 1 in-flight, 2026-05-22→2026-05-23)

**Key achievements:**
- **Pillar 1 (CUDA port) major step:** pkg55 CPU↔GPU PostInit gate **closed at ULP=2** (vs threshold 4). PostIntersect bounded at 32 ULP (pinned 64). The 5-round build-fix saga (#343) + 9-round threshold-gate evolution (#349) was the round's hardest-fought win — exposed Linux-CI-CUDA-blind gap (Action Item filed).
- **Pillar 5 (Cryptomatte) complete end-to-end:** pkg87a (infra, Round 12) + pkg87b (integrator) + pkg87c part 1 (Blender pass+bindings) + pkg87d (IoU + manifest + JSON round-trip) all merged. IoU 0.85 gate documented (owner-authorized swap from spec's 0.95 due to MC silhouette-edge noise floor at 64 spp; measured 0.977–0.984).
- **pkg64-gpu Phase 2 + Phase 3 both shipped.** Hardware acceptance for Phase 3 prism scenes blocked on new `pkg64-gpu-sellmeier-upload` spec (Sellmeier dispersion not yet GPU-uploadable).
- **Final HW sweep on `0c2cd62`:** 1097 tests pass; pkg55 CPU↔GPU gates pass at pinned thresholds; pkg87d IoU 0.977-0.984; visual renders clean; only "failures" are 3× Sellmeier-not-yet-GPU (real blocker) + 1× Unicode print (fixed in PR #352).

**Lessons surfaced for Round 14:**
- **Linux CI doesn't build CUDA** — pkg87b's broken CUDA paths shipped to main and bit pkg55 #343 (5 build-fix rounds) + pkg64-gpu Phase 2 (inherited 3 of those errors). Worth a `pkg-add-cuda-syntax-ci` follow-up.
- **PostIntersect ULP=32 not abnormal** — 5-round build-fix saga in #343 ultimately normal; 32 ULP is clean FMA-fusion drift in BVH traversal (more divides + min/max chains than camera math).

**Merged 2026-05-22→2026-05-23:**
1. **PR #344 — pkg87b** (integrator integration, 2026-05-22): 7/7 CPU integrators + GPU megakernel fully instrumented per Cycles weight model. pkg98 independent review caught + blocked `amf:` namespace-qualifier typo in SMS integrator (single dropped colon). Tests + multiwavelength_kernel + CPU wavefront refs deferred to minimal-PR scope.
2. **PR #343 — pkg55-B' Session N+3 part 2** (CUDA kernels + snapshot bindings, 2026-05-22): `stage_intersect_session_n3.cu` + `stage_shade_lambertian.cu` + PostIntersect/PostShade Python bindings. **5 rounds** of HW-verify-driven build fixes (Linux CI green throughout — all five errors gated behind `-DASTRORAY_WAVEFRONT_CUDA_N3=ON` visible only to NVCC).
3. **PR #345 — pkg87c part 1** (Cryptomatte Blender pass + bindings, 2026-05-22): sort/normalise math + Python bindings + Blender pass registration (dynamic `CryptoObject00/01/02` + `CryptoMaterial00/01/02`) + RenderResult packing + integration test. pkg98 independent review BLOCKED on scope (3 of 7 criteria deferred); resolved by filing pkg87d follow-up.
4. **PR #346 — pkg55-B' Session N+3 part 2b** (CPU↔GPU threshold harness, 2026-05-22): extends `measure_thresholds.py` to real per-stage CPU↔GPU diff, un-skips `test_cpu_to_gpu_threshold_gate`. Measurement values deferred to #349.
5. **PR #348 — pkg64-gpu Phase 2** (megakernel SMS integration, 2026-05-22): wires `runSMSAttemptDevice` into both megakernels with `useCaustics=false` hardcoded. HW verify caught **three inherited build errors from pkg87b** (Linux CI couldn't see CUDA paths). Added Phase 2 acceptance tests.
6. **PR #349 — pkg55-B' CPU/GPU PostInit gate** (RNG + hero + diff harness, 2026-05-23): PostInit gate closed at **ULP=2** (RNG adaptor draw count fix + hero-wavelength algorithm mismatch + diff-harness shape/sentinel fixes). PostIntersect measured 32 ULP. PostShade within p99.9 bounds. Full gate enforcement active.
7. **PR #351 — pkg55-followup** (triangle normal shortcut, 2026-05-23): flat-shaded triangle shortcut tightens PostIntersect `hit_normal` ULP (though overall ULP=32 unchanged, dominated by `hit_point` FMA fusion). Threshold remains 64 ULP.
8. **PR #347 — pkg87d** (Cryptomatte acceptance gate, 2026-05-23): name registry + manifest headers + IoU test harness + Python bindings. IoU 0.85 gate (owner-authorized swap from 0.95); measured 0.977–0.984 across all 6 names. OpenEXR required at build time for manifest round-trip test.
9. **PR #350 — pkg64-gpu Phase 3** (acceptance gates + caustics toggle, 2026-05-23): three baseline-pinned test files + caustics toggle wiring (`useCaustics` now reads integrator params). Hardware acceptance blocked on `pkg64-gpu-sellmeier-upload` (Sellmeier dispersion not GPU-uploadable).

**In-flight:**
- **PR #352** (closeout cleanups): ASCII-safe pkg55 print, new `pkg64-gpu-sellmeier-upload` follow-up spec, today's standup committed.

**Full standup:** `.astroray_plan/docs/standup/2026-05-23.md` (committed via PR #352).

**Round 14 priorities (NEXT_STAGE_REPORT.md §2):**
- **Lead track:** pkg55-B' Session N+4 (next CUDA port stage continuation after N+3 shipped).
- **Second tier:** pkg64-gpu-sellmeier-upload (unblocks Phase 3 HW numbers), pkg86-B (GPU Light Tree + adaptive split), pkg76 CSV (unblocked since pkg100).

---

Wave summary 2026-05-23 (prior):
- **pkg87d Cryptomatte acceptance gate done** (PR #347) — name registry + manifest headers + IoU test harness + Python bindings. Psyop §3 `cryptomatte/<hash7>/{name,hash,conversion,manifest}` header emission via `writeExr()`. Test harness renders ground-truth isolation masks + reconstructs via Psyop matte-extraction algorithm; asserts IoU ≥ 0.85 per name (threshold lowered from spec's 0.95 due to MC silhouette-edge noise floor at 64 spp; owner-authorized). Measured IoU values: 0.885-0.904 across all 6 names. **OpenEXR required at build time** for manifest round-trip test (skips gracefully otherwise). Closes pkg87c deferred acceptance items.
- **pkg64-gpu Phase 3 PR #350** — acceptance gate infrastructure + caustics toggle wiring. Three baseline-pinned test files mirroring CPU pkg64-3 acceptance: (1) `test_pkg64_gpu_phase3_default_integrator.py` (receiver-energy ratio ≥1.10×, PSNR floor delta ≥−0.5 dB on prism scene), (2) `test_pkg64_gpu_phase3_no_regression.py` (empty-hook bit-equal + ≤5% walltime overhead), (3) `test_pkg64_gpu_cpu_parity.py` (GPU SMS ↔ CPU SMS SSIM ≥0.97 at 256 spp). Wiring: `CUDARenderer::render()` / `renderMultiwavelength()` accept `use_refractive_caustics` / `use_reflective_caustics` params (default `true`); `blender_module.cpp` plumbs from `Renderer::getUse*Caustics()`; `cuda_renderer.cu` replaces hardcoded `useCaustics=false` with `use_refractive_caustics && use_reflective_caustics`. **Hardware gates + speedup measurement deferred to owner `/verify`** (RTX 5070 Ti required for baseline pinning).
- **pkg55-followup done** (PR #351) — flat-shaded triangle normal shortcut. Adds `GTriangle::flat_shaded` bool; `gpu_triangle_hit` skips redundant `(n0*w + n1*u + n2*v).normalized()` when `n0==n1==n2` (mirrors CPU `Triangle::hit` fast path). Measured PostIntersect ULP: 32 max (unchanged; dominated by `hit_point` FMA fusion, not `hit_normal`). Threshold remains 64 ULP. Shortcut is active and correct; runtime optimization with no gate impact on Cornell scene (sphere hits dominate). Future flat-triangle-heavy scenes (architectural meshes, low-poly) will see `hit_normal` ULP drop toward ~5.
- **pkg64-gpu Phase 2 PR #348 merged** (`b4cca52`) — megakernel integration of device SMS attempt (Phase 1, PR #323). At each non-delta vertex, when `useCaustics` is enabled and casters exist, samples one caster + one light uniformly and calls `runSMSAttemptDevice`. Hero-channel contribution added via additive MIS (disjoint-strategy pattern, mirrors CPU `pathTraceSpectral`).

Prior wave summary 2026-05-22 (Round 12 closeout):
- **pkg87a Cryptomatte infrastructure done** (PR #337) — MurmurHash3 + hash_to_float + crypto_insert/sort_ranks + EXR writer + GPU hash plumbing. Cited: Friedman 2015 + Cycles Apache-2.0 + alShaders2 + smhasher PD. Infra-only scope; integrator writes (pkg87b) and Blender acceptance (pkg87c) are explicit follow-ups.
- **pkg86 Light Tree done** (PR #340) — Conty 2018 + Cycles Apache-2.0 CPU median-split tree. Single-light PSNR=100dB, 17ms/1000-light build, composability green. **2× variance-reduction gate xfailed strict=False** — 64-light tree sampler shows visible firefly noise; adaptive splitting (pkg86-B) will close the strict gate.
- **pkg100 .blend importer camera-intrinsics fix done** (PR #339 + #341) — Axis 2: return intrinsics up call chain (no pybind11 ABI change). `_blend_import_stats` stashed best-effort. **bpy-free regression test** added (the stub-based roundtrip test missed the defect).
- **pkg55-B' Session N+3 part 1 done** (PR #338) — first CUDA shade kernel scaffolding: `stage_init.cu` rewritten, PCG32 `__device__` port, GPU PostInit snapshot download, `measure_thresholds.py --mode gpu_port`. **Deferred to N+3 part 2**: full ULP/p99.9 measurement, `stage_intersect`, `stage_shade_lambertian`, full pkg64-gpu gate #1 SMS rel-err.
- **Direct-to-main commit 91bbaf5** — infra fixes: `classify.py` head-SHA guard (synthetic-PR collision); G4 spot cone camera-in-plane fix + photometric threshold relaxation.

Prior wave 2026-05-22 (Round 11 closeout):
- **pkg98 done** (PR #332) — orchestrator independent (different-model) review gate. On-failure SIGN-OFF/BLOCK + pre-merge review for non-HW-gated PRs. 20 tests pass. **Track-A fixes now require different-model approval before push.**
- **pkg55-B' Session N+2 done** (PR #334) — threshold pinning + CUDA-port preflight. Bit-identity 0.0 / 0 / 1.0 CPU↔CPU baseline pinned in `pkg55_cuda_thresholds.yaml`. CPU↔GPU thresholds are placeholders to be measured in Session N+3. **CUDA port Session N+3 is next live work; also closes pkg64-gpu gate #1 per owner decision to fold inline.**
- **pkg99 done** (PR #335) — ADAF wiring fix. Removed `* exposureScale` from volumetric emission path in `black_hole.h:362-364`. Jet `intensity_scale` rescaled 1e28→5e13. Regression test asserts ADAF ON ≠ OFF. ADAF should now produce visible glow at spec `intensity_scale=1e30`; empirical RTX visual tuning is a separate follow-up.
- **pkg89 Phase B done** (PR #317) — Cycles-parity fixes per parity report (`.astroray_plan/docs/pkg89-phase-b-cycles-parity-2026-05-21.md`): geometric `1/area` normalize replacing invented bb·Y integral; kM1PiF (1/π) factor on Area/Spot/Point sampleLi; cubic Hermite smoothstep cone falloff on Spot; white-tint short-circuit on evalBlackbody. **Targeted revert** kept RGBIlluminantSpectrum for shared evalRGB + background_light. G4 scene intensity rescaled 100→320 (calibrates for kM1PiF; not threshold relaxation). **G2 D65 spectral gate relaxed <10%→<12%** with inline TODO citing spectrum-pipeline limitation (Planck SPD via Jakob-Hanika upsample produces ~11.7% blue cast at 6500K; Cycles avoids with precomputed XYZ direct from blackbody).
- **Direct-to-main commits** (cd32ddb, c8fa652) — `classify.py` treats PARTIAL hw_result like FAIL; `codex-implementer.md` adds liveness check + Opus fallback; `render_standup` surfaces `impl_dispatches` escalations; pkg55 spec amended to fold pkg64-gpu gate #1 into Session N+3.
