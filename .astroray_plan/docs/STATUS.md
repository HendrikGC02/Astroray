# Astroray Status

**Last updated:** 2026-05-17 (Round 10 closeout — pkg44 ADAF + pkg55-B' Sessions 3/4/5/6/7/8 + pkg55-B-prime-cuda-gate-derivation + pkg100 spec all merged; growing-oracle expansion (metal/dielectric/disney/thin_glass/diffuse_light/closure_graph) complete; all bit-identity gates PASS. Prior: addon first-principles plan landed (#300); pkg94/95/96 filed; pkg90/99/100 specs queued)

This is the source-of-truth for "where are we?" Updated by the overseer
at the start of each week, and by the project owner when a significant
event happens (pillar transition, major failure, scope change).

If you are reading this to start a coding session: check **Pillar
status** for what's active, then check **This week** for what you
personally should pick up.

---

## Current snapshot

- Pillars 1 and 2 are complete. Package headers for pkg12-pkg14 were reconciled
  on 2026-05-09 after lagging behind the changelog.
- Pillar 3 has its ReSTIR/NRC package sequence implemented through pkg28, but
  it remains in validation because NRC has not yet proven the 30% batched
  inference speedup/quality target and ReSTIR/NRC are CPU-integrator plugins,
  not CUDA kernels.
- Pillar 5 (Cycles parity / Blender integration / denoiser story) is
  **feature-complete on planned scope**, but the user-facing
  competitive-parity claim (viewport pan/zoom feeling like Cycles) is
  **not** met yet — pkg81 Phase 1+2 measured **CUDA 104 ms vs CPU
  58 ms on identical 100k-tri load** on the user's RTX 5070 Ti, which
  makes pkg55 Phase A's 158 regs/thread cliff measurably user-facing.
  pkg55 Phase B (wavefront per-material shade kernels) now formally
  owns the viewport-parity acceptance gate ("CUDA pan-frame p99 ≤
  1.2× Cycles-CUDA on the pkg81 harness scene"). Done as of
  **2026-05-11**:
  - **Cycles parity wave**: pkg52/53/57/58/59/60/61/62/63/65/66.
  - **GPU multi-wavelength parity**: pkg54/54a/54b/54c/54d.
  - **Denoiser story closed end-to-end**: pkg33 → pkg68 (**2.77×
    viewport speedup**) → pkg69 (compositor Albedo) → pkg70 (OptiX,
    **1.86× faster than OIDN-CUDA**) → pkg72 (motion vector AOV) →
    pkg75 (first-hit normal buffer fix) → **pkg73 OptiX TEMPORAL_AOV
    fixed and verified** (PR #249, 2026-05-11; **53.1% inter-frame
    variance reduction vs ≥30% gate** on RTX 5070 Ti / OptiX 9.1 /
    CUDA 12.8). Two compounding root causes: plugin's
    `OptixDenoiserParams::temporalModeUsePreviousLayers` was never
    set, AND the AOV-reference test was silently upgraded to
    TEMPORAL_AOV by sub-pixel float dust in `projectToPrevPixel`.
  - **Caustics flagship done**: pkg64 Phases 1+2+3 (**+8.83 dB PSNR
    delta**, 1.18× receiver-energy ratio, +0.26 dB PSNR floor, 2.0%
    empty-hook overhead).
  - **Cycles parity benchmark**: pkg71 framework + first Cornell
    baseline (**Astroray-CPU SSIM 0.9536, GPU SSIM 0.9548 vs
    Cycles-CPU EXR; Astroray-GPU 5.2× faster than Cycles-CUDA**);
    **pkg76 .blend importer done** (PR #240, SDNA-walking Python
    reader, no `bpy` runtime); CSV row population on Classroom /
    Junkshop / BMW27 carried to Round 7 as a ½-day RTX session.
  - **Showcase framework**: pkg74 all phases (interactive PBRT-style
    HTML + weekly self-hosted CI).
  - **Viewport sync done**: pkg52 + pkg56 Phases A+B+C — depsgraph-
    driven dispatch, idle frame ≤5 ms p99 on a 99k-tri scene
    (gate-releasing package).
  - **Wavefront SoA scaffold landed**: **pkg55 Phase A** (gated CUDA
    events + NVTX, baseline.json with 158 regs/thread + 1 active
    block/SM measured) AND **pkg55 Phase A.1** (PR #250, 2026-05-11
    — SoA path state + intersect queue, gated behind
    `-DASTRORAY_WAVEFRONT_INTERSECT=ON`, bit-identical AoS megakernel
    output verified). Phase B (per-material shade kernels) is the
    next big Round-7 deliverable and now owns the viewport-parity
    acceptance gate.
  - **Blender daily workflow unblocked**: **pkg80** (PR #246, 2026-
    05-11) resolves `'auto'` integrator dropdown to a registered
    plugin before C++ calls; the GPU-mode crash on viewport
    rendered-view is gone.
  - **Viewport-parity measurement complete**: **pkg81 Phase 1+2** (PR
    #248, 2026-05-11) — harness + 16-config Cycles A/B sweep +
    diagnosis note. H4 (megakernel register pressure) dominates;
    Phase 3 routes to pkg55 Phase B per spec escape. Smaller H2
    (accumulator-reset-per-pan) and H5 (12 s cold-start) findings
    split out as **pkg83** + **pkg84** for immediate addon-side
    Round-7 wins.
- **Pillar 4 strategic gate RELEASED (2026-05-10) and shipping.**
  pkg40 Kerr metric (pre-gate), **pkg41 Kerr validation** (PR #236, BPT
  1972 + Chandrasekhar + 39 tests), **pkg42 synchrotron emission** (PR
  #245, VolumetricEmission interface + Pandya 2016 power-law/thermal
  fits + bipolar jet plugin + Blender jet controls + 9 focused tests).
  **pkg43 (slim disk, done PR #271)** + **pkg44 (ADAF, done PR #310)** shipped.
  pkg45–51 paste-ready specs queued.
- Pytest collection (`runtime_setup.py` `os.add_dll_directory` dedupe
  in PR #225): **801 tests collected** on the Windows MSVC `build_cuda`
  configuration. New since Round 3: pkg64-3 default-integrator + no-
  regression, pkg56 Phase B uploaders + Phase C dispatch,
  pkg73 temporal denoiser, pkg74-3 HTML, pkg76 blend-import
  format + roundtrip, pkg41 Kerr validation (39), pkg55 Phase A
  baseline harness.
- Known unrelated CI flake: `tests/test_restir_validation.py
  ::TestSpatialMSE::test_spatial_reduces_mse` failed on PR #236 at
  margin 0.000004 (no-reuse 0.009215 vs spatial 0.009219). Margin is
  RNG noise floor; queued as **pkg79** to widen the seed-averaging
  count or assertion margin.
- Tracking issue [#237](https://github.com/HendrikGC02/Astroray/issues/237):
  **CLOSED by pkg82** (PR #261, 2026-05-13). pkg54c visible-band SSIM gate
  re-baselined from 0.999 to 0.998 after measured cross-build variance
  characterization (intra-binary perfect determinism, cross-build delta 0.0006).
  pkg78 verifier proved bit-identical CPU+GPU output; pkg82 confirmed the drift
  is NVCC build-time non-determinism, not a code regression.
- `NEXT_STAGE_REPORT.md` is the live action queue (Round 7 prompts);
  this file is the source of truth for completion state. `production.md`
  remains historical (pkg50+ placeholder names that conflict with live
  package numbers are marked obsolete in-place).

---

## Pillar status

| # | Name | Status | % | Next milestone | Blocked on |
|---|---|---|---|---|---|
| 1 | Plugin architecture | **Done** | 100% | — | — |
| 2 | Spectral core | **Done** | 100% | — | — |
| 3 | Light transport | **Validation** | 90% | NRC batched-inference speedup target; pkg89 Phase B (Blender addon) | CUDA kernels for ReSTIR/NRC are not implemented; pkg89 Phase A done (PR #294) |
| 4 | Astrophysics platform | **Active, shipping** | 50% | pkg45/46 CLOUDY/HII region | gate released; pkg40 + pkg41 + pkg42 + pkg43 + pkg44 + pkg47 (FITS loader) done; pkg45–51 queued (pkg47 FITS loader landed PR #292; FITSVolume registration deferred to pkg48) |
| 5 | Production polish / Blender parity | **Feature-complete on planned scope; viewport-parity gate now owned by pkg55 Phase B; addon-remediation track spec-ready and dispatchable** | ~98% (counter) | pkg55 Phase B (per-material shade kernels — owns the viewport-parity claim) **+ addon remediation: pkg94 (first, no deps) → pkg95 ∥ pkg96 (depend on pkg94) — spec-ready, dispatchable now (owner ruled concurrent, pkg94 first)** | pkg73 ✓ + pkg80 ✓ + pkg81 P1+P2 ✓ + pkg55-A.1 ✓ all done 2026-05-11; pkg55-B is the long-tail; addon track unblocked (plan #300 landed; P5 folded into pkg55-B' + pkg85-D) |

**Pillar 1 package summary:**

| Package | Description | Status |
|---|---|---|
| pkg01 | Registry skeleton | done |
| pkg02 | Migrate Lambertian | done |
| pkg03 | Migrate remaining materials | done |
| pkg04 | Migrate textures + shapes | done |
| pkg05 | Integrator interface | done |
| pkg06 | Pass registry | done |

**Pillar 2 package summary:**

| Package | Description | Status |
|---|---|---|
| pkg10 | Spectral types (scaffolding) | done |
| pkg11 | Spectral path tracer | done |
| pkg12 | Spectral Lambertian override | done |
| pkg13 | Spectral remaining materials & textures (all threads: physics/infra, pkg13a, pkg13b, pkg13c) | **done** |
| pkg14 | Spectral environment map + flip default | **done** |

**Pillar 3 package summary:**

| Package | Description | Status |
|---|---|---|
| pkg20 | ReSTIR reservoir core | implemented |
| pkg21 | ReSTIR light sample abstraction | implemented |
| pkg22 | ReSTIR initial sampling | implemented |
| pkg23 | ReSTIR temporal/spatial reuse design | implemented |
| pkg24 | ReSTIR validation | implemented |
| pkg25 | tiny-cuda-nn prototype | implemented |
| pkg26 | NRC prototype | implemented |
| pkg27 | NRC integrator plugin | implemented |
| pkg27a | NRC training observability | implemented |
| pkg27b | NRC indirect validation + graphs | implemented |
| pkg28 | NRC training buffer | implemented |

**Spectral dielectric chain (Pillar 2 follow-up):**

| Package | Description | Status |
|---|---|---|
| pkg30 | Spectral BSDF sampling interface (`sampleSpectral` on Material) | implemented |
| pkg31 | Spectral dielectric with Sellmeier dispersion | implemented |
| pkg29 | Spectral dielectric prism validation | implemented |
| pkg29a | Scoped caustic validation for spectral optics | implemented |

**Material backend parity bridge (Pillar 2/5 follow-up):**

| Package | Description | Status |
|---|---|---|
| pkg34 | Material backend capabilities + no silent GPU fallback | **done** |
| pkg35 | Spectral GPU material kernels | **done** |
| pkg36 | Shared material closure graph | **done** |
| pkg37 | Blender addon backend refresh + runtime diagnostics | **done** |

**Visual diagnostics & production polish (Pillar 5):**

| Package | Description | Status |
|---|---|---|
| pkg32 | Visual diagnostics & benchmark renders | **done** |
| pkg33 | OIDN FetchContent integration | **done** |
| pkg68 | OIDN persistent device + CUDA backend selection | **done** |
| pkg38 | Spectral material profile database | **done** |
| pkg39 | Multi-wavelength rendering (IR/UV) | **done** |

**Cycles parity & Blender integration (added 2026-05-08, Pillar 5):**

These packages close the gap between the engine and the addon — the
engine is mostly Cycles-equivalent, but the Blender integration layer
is currently the weakest link.

| Package | Description | Status | Track |
|---|---|---|---|
| pkg52 | Persistent viewport session (persistent renderer, viewport camera invalidation, progressive accumulation, CAMERA zoom/pan) | **done** | A |
| pkg53 | GPU integrator capability diagnostics | **done** | B/E |
| pkg54 | GPU multi-wavelength path tracer (CPU/GPU parity) | **done** | A |
| pkg57 | Native Astroray shader nodes (with Cycles compat) | **done** | A |
| pkg58 | Spectral profile dropdown + IR/UV reference scenes | **done** | B |
| pkg59 | Shader-graph vector / UV plumbing (texture routing, Mapping scale/offset/rotation, coord_mode, uv_debug_aov, named UV layers) | **done** | A |
| pkg60 | Disney v2 energy compensation (no-glow materials) | **done** | A/E |
| pkg61 | GPU per-vertex normals (shade-smooth parity) | **done** | A/E |
| pkg62 | Viewport pass selector + live OIDN preview | **done** | B |
| pkg63 | World / HDRI parity (Mapping XYZ rotation, color tint, MIS env-map) | **done** | A |
| pkg64 | Spectral caustics (prism-accurate, refractive + reflective) — SMS skeleton + spectral MNEE extension | **Phases 1 + 2 + 3 done** — RGB + spectral SMS folded into the default `path_tracer` via per-bounce SMS hook gated by `use_refractive_caustics` AND per-object `is_caustic_caster` (Cycles-style opt-in); **pkg64-gpu spec filed** (PR #258) for GPU megakernel port | A |
| pkg64-gpu | GPU SMS caustics port — targets AoS megakernel, not wavefront (pkg55-C will move to shade kernels later). | **open** — ready to implement after pkg55-B architectural review + pkg82 register-pressure baseline. Spec PR #258 (docs-only, 2026-05-13). | A |
| pkg67 | Metric-aware path tracer (GR + spectral unification) — Option α: MinkowskiMetric + `SampledWavelengths::redshift` + `GRSpectralResult::frequencyShift` | **done** — PR #262, 2026-05-13. Ratifies existing `BlackHole::isGRObject()` dispatch architecture. 9 unit tests + flat regression + Schwarzschild deflection. | A |
| pkg69 | Albedo pass for Blender compositor denoise node | **done** | A |
| pkg70 | OptiX AI denoiser backend (HDR/AOV, persistent state, OIDN fallback) — verified 2026-05-10 on RTX 5070 Ti + OptiX 9.1.0; see pkg70 Lessons + pkg75 spec for upstream AOV-degradation defect found during verification | **done** | A |
| pkg71 | Cycles parity benchmark framework | **implemented** (first full baseline CSV pending CUDA + Cycles 4.x runner) | A |
| pkg56 | Incremental scene sync (depsgraph diff) — Phase A (instrument) + Phase B (per-domain uploaders + transform-update) + Phase C (depsgraph-driven dispatch in `view_update`, idle frame ≤ 5 ms p99 on 99k-tri scene). **Gate-releasing package.** | **done (all phases)** | A |
| pkg74 | Engine benchmark + visual showcase framework (material zoo, convergence grid, stats CSV, HTML index) | **done (all phases)** | A |
| pkg75 | First-hit normal buffer population for denoiser AOV guides — surfaced during pkg70 verification | **done** | A |
| pkg72 | Per-pixel motion vector AOV (camera-only screen-space flow; OptiX prev→curr convention; `Renderer.get_motion_buffer()` zero-copy NumPy view; `motion_vector_aov` visualisation pass) — unblocks pkg73 OptiX temporal denoiser | **done** | A |
| pkg73 | OptiX TEMPORAL_AOV denoiser mode (auto-upgrade from pkg70 AOV when pkg72 motion buffer is non-zero; destroy + recreate on model-kind transition; ping-pong internal-guide-layer pair; previous-output cache + first-frame fallback; clean fallback to AOV on static cameras). Mirrors Cycles `intern/cycles/integrator/path_trace_work_gpu.cpp` (Apache-2.0). | **done** — defect fixed in PR #249 (2026-05-11). Two compounding root causes: (1) plugin: `OptixDenoiserParams::temporalModeUsePreviousLayers` was zero-init and never set → OptiX silently treated every frame as a new sequence start and dropped temporal accumulation, (2) test: AOV reference was silently upgraded to TEMPORAL_AOV by sub-pixel float dust (~2e-5) in `projectToPrevPixel` even when prev-pose == curr-pose → `rms_t == rms_a` by construction, masking root cause 1. Hardware-verified on RTX 5070 Ti / OptiX 9.1 / CUDA 12.8: **53.1% inter-frame variance reduction (gate ≥30%), 5/5 tests pass**. Diagnostic prints from PR #241 removed. **Denoiser story closes here** (pkg33 → pkg68 → pkg69 → pkg70 → pkg72 → pkg73). | A |
| pkg76 | Astroray `.blend` importer (parity scope) — offline SDNA-walking Python reader, no `bpy` runtime dependency; supports Blender 5.1's 17-byte file header + 32-byte block header + new `attribute_storage`; returns `astroray.Scene`. `tools/blend_import/{sdna,reader,scene_builder,blend_to_astroray}.py`. | **done** (PR #240; CSV row population on Classroom/Junkshop/BMW27 carried to Round 7 as a ½-day RTX follow-up) | A |
| pkg80 | Blender addon: resolve `'auto'` integrator dropdown to a registered plugin before C++ calls — daily-workflow blocker surfaced 2026-05-10 by owner. | **done** (PR #246, 2026-05-11 — `_effective_integrator_name` now resolves `'auto'` against `astroray.integrator_registry_names()` filtered by device-mode capability; new `tests/test_blender_auto_integrator.py` covers the four resolution cases) | A |
| pkg81 | Viewport interactivity parity with Cycles — Phase 1 harness + Phase 2 diagnosis + Phase 3 fix. | **Phase 1+2 done 2026-05-11** (PR #248); harness + 16-config sweep + pkg81-diagnosis.md committed. Headline: **CUDA 104 ms vs CPU 58 ms on 100k tris** — H4 (megakernel register pressure, the pkg55-A 158 regs/thread cliff) dominates. **Phase 3 routes to pkg55 Phase B** per spec escape clause; Phase B now owns the viewport-parity acceptance gate. H2 + H5 follow-ups split out as pkg83 + pkg84. | A |
| pkg82 | pkg54c visible-band SSIM gate variance characterisation — gate re-baselined 0.999→0.998 based on measured cross-build delta 0.0006. | **done** — PR #261, 2026-05-13. Closes issue #237. Intra-binary perfect determinism (20 runs, stddev=0); cross-build O(10⁻⁴) variance. | A |
| pkg83 | Progressive accumulation continuation — addon-only fix for H2 from pkg81. Reset only on substantive camera changes (focal length, DoF, lens shift), not pure transforms. | **done** — PR #259, 2026-05-13. `spp_trace = [1,2,3,4,5,6,7,8]` measured on CPU + CUDA. | A |
| pkg84 | CUDA kernel pre-warm at viewport start — addon-only fix for H5 from pkg81. First frame 83.3 ms (was 12,079 ms cold). | **done** — PR #260, 2026-05-13. **145× improvement** vs pkg81 baseline. Cites Cycles `reserve_local_memory` (Apache-2.0). | A |
| pkg85 | Test-harness CUDA state leak — `pytest tests/` crashes at test #370 (isolated test passes); bisect candidate range tests 360–369. | **partial** — PR #268 (2026-05-14) conftest autouse fixture + cuda_renderer error clearing; robustness improvement only; spec gate NOT met; full CUDA-call audit queued as pkg85-B follow-up | A |
| pkg55 | Wavefront SoA GPU refactor — Phase A.0 (`ASTRORAY_PROFILE=1`-gated CUDA events + NVTX + baseline.json; **158 regs/thread + 1 active block/SM** documented as the occupancy cliff) **+ Phase A.1** (SoA path-state struct + intersect queue gated behind `-DASTRORAY_WAVEFRONT_INTERSECT=ON`, default OFF, bit-identical AoS megakernel output verified, PR #250 2026-05-11). **Phase B held on origin/pkg55-phase-b (HELD, NOT merged)**; cascading radiance bugs regressed 2.5× → 21× brightness. **Phase B' (restart) spec amendment** (PR #266, 2026-05-14) is now authoritative on main: CPU-first methodical rebuild with 8 design decisions. **Phase B' Session 2b** (PR #281, 2026-05-14 — two reference PT oracles, both close gates green). **Phase B' Session 2c** (PR #297, 2026-05-15 — CPU wavefront skeleton; EXACT bit-identity by shared-kernel construction, max abs diff 0.0 across all 5 snapshot stages on 1 spp Lambertian Cornell, verified MinGW + Linux-GCC CI; production codegen byte-unchanged). | **Phases A.0 + A.1 + B' Sessions 2b + 2c done; Sessions 3..N (growing-oracle expansion) open. Two-tier gate (exact CPU↔CPU / bounded+SSIM CPU↔GPU) must be re-derived before CUDA-port sessions per the spec NOTE.** | A |
| pkg86 | Light Tree (Conty 2018 many-lights importance sampling) — CPU first, GPU follow-up pkg86-B. | **open** — spec on main (PR #265); blocked on pkg89 Phase A for Light::orientationCone() + power() accessors | A |
| pkg87 | Cryptomatte passes (CryptoObject / CryptoMaterial) — Psyop BSD-3 + Cycles Apache-2.0. | **open** — spec on main (PR #264); independent; ready to implement | A |
| pkg88 | Motion blur (Cycles parity) — camera + object + deformation + wavefront hook. | **open** — research signed off (PR #267); DRAFT spec; design questions deferred per owner ("get to that later") | A |
| pkg89 | Dedicated Light objects (Point / Spot / Distant / Area / Background) — first-class Light interface, emission spectrum composable, pkg86 unblocking accessors. | **Phase A done** (PR #294, 2026-05-15 — interface + 5 light types + integrator wiring; G6/G9 pass; G8 spectral fidelity 0.41% error < 1% threshold; MinGW large-struct heap-corruption fix re-applied). Full-scene G8 + G1–G5 explicitly Phase B (Blender addon). | A |

**Deferred / not-yet-spec'd from the 2026-05-08 triage** (mentioned in the
original roadmap but no full spec written; capture intent before they're
forgotten):

| Pkg | Title | Why no spec yet |
|---|---|---|
| ~~pkg55~~ | ~~Wavefront SoA GPU refactor~~ | Spec'd; Phase A (instrumentation + baseline.json) **done** — see Pillar 5 table. Phase A.1 + B + C still open. |
| ~~pkg56~~ | ~~Incremental scene sync (depsgraph diff, BVH refit-only)~~ | Spec'd as a 3-phase package; **all three phases done** — see Pillar 5 table. |
| pkg65 | scripts/ directory cleanup (`build/`, `diagnostics/`, `benchmarks/`, `data/`, `dev/` subfolders) | Trivial — can be done from a one-line description; no spec needed. |
| pkg66 | Material iteration UX (one-sphere-per-material live preview operator) | Small; partly covered by `scripts/diagnostics/material_contact_sheet.py`. |

**Astrophysics platform (Pillar 4):**

| Package | Description | Status |
|---|---|---|
| pkg40 | Kerr metric plugin and Schwarzschild extraction | **done** |
| pkg41 | Kerr geodesic validation | **done** (PR #236 — 39 tests; BPT 1972 + Chandrasekhar analytic + null circular photon residuals + Kerr a=0 vs Schwarzschild identity + shadow-contour image-plane regression) |
| pkg42 | Synchrotron emission and relativistic jets | **done** (PR #245, 2026-05-11 — VolumetricEmission interface, `synchrotron_jet` plugin, Pandya 2016 power-law/thermal fits, bipolar jet plugin, Blender jet controls, 9 focused tests) |
| pkg43 | Slim disk accretion model | **done** (PR #271, 2026-05-14 — Abramowicz 1988 / Sadowski 2009, 14/14 tests, T(9M,mdot=1) = 7.45e6 K) |
| pkg44 | ADAF accretion model | **done** |
| pkg45 | CLOUDY emissivity table preprocessing | open |
| pkg46 | HII region emission plugin | open |
| pkg47 | FITS loader | **done** (PR #292, 2026-05-15 — FITS I/O wrapper + FITSTexture plugin + CMake gate `ASTRORAY_ENABLE_FITS` default OFF; FITSVolume registration+test deferred to pkg48 per owner ruling) |
| pkg48 | HDF5/NumPy simulation-volume loader | open |
| pkg49 | SPH-to-volume preprocessing | open |
| pkg50 | Weak lensing pass | open |
| pkg51 | Synthetic telescope post-process | open |

---

## This week

**Week of:** 2026-05-17 (Round 10 closeout — 8 PRs merged since Round 9; Round 11 direction set)

### Track A (Claude Code)

- **Round 11 direction (2026-05-17):** **CUDA-port path leads** to close
  the still-unmet viewport-parity claim. Owner decision: pkg55-B'
  Sessions N+1 (shadow/miss/terminate CPU stages) → N+2..M (CUDA port of
  wavefront shade kernels) is top priority. pkg100 (.blend importer
  camera-intrinsics fix) is **explicitly DEPRIORITIZED** relative to
  CUDA-port work — the project accepts continued real-scene parity
  blindness in the near term to close the performance/viewport-parity
  claim first. Rationale: the viewport-parity acceptance gate (CUDA
  pan-frame p99 ≤ 1.2× Cycles-CUDA on the pkg81 harness scene) is the
  critical path to Pillar 5 completion and the competitive claim Astroray
  makes publicly; real-scene CSV rows (blocked on pkg100) are a secondary
  validation artifact, not the gate-releaser.

- **Round 10 complete (2026-05-17)** — 8 PRs merged. Headline wins:
  - **pkg44 ADAF accretion model** (PR #310) — Narayan & Yi 1995 self-similar ADAF solution + Yuan & Narayan 2014 prefactors; synchrotron + bremsstrahlung thermal emission; 19 tests pass; power-law exponents exact; Sgr A* profiles within tolerance. Pillar 4 → ~50%.
  - **pkg94 addon build-integrity guard** (PR #304) — Stage 1 / P1 of the addon remediation track. Core build-ID guard implemented: `astroray.__build__` attribute exposed, `register()` guard fires on mismatch, unit tests pass. The verifiability multiplier for all subsequent addon fixes.
  - **pkg55-B' Sessions 6/7/8** — growing-oracle expansion complete for thin_glass (PR #312), diffuse_light (PR #316), closure_graph (PR #318). All three: EXACT bit-identity (max abs diff 0.0, diverging fields = 0); production codegen byte-unchanged.
  - **pkg55-B-prime-cuda-gate-derivation** (PR #320) — two-tier CPU↔CPU / CPU↔GPU gate definition now authoritative in pkg55 spec; design decision #9 added; A.1 ray-normalization checklist item added. Unblocks CUDA-port Sessions N+2..M.
  - **Doc-only specs filed:** pkg99 (ADAF quasi-spherical glow re-investigation, PR #315), pkg90 (hardware-verifier build-env bootstrap, PR #319), pkg100 (.blend importer camera-intrinsics dynamic-attr defect, PR #321).

- **Round 9 complete (2026-05-16)** — 6 PRs merged. Headline wins:
  - **pkg91 integrator param lifecycle** (PR #290) — `Integrator::setMaxDepth` + integrator rebuild on `set_integrator_param`; closes the Q1/Q2 silent-no-op footguns.
  - **pkg47 FITS loader** (PR #292) — FITS I/O wrapper + FITSTexture plugin, gated `ASTRORAY_ENABLE_FITS` default OFF; FITSVolume deferred to pkg48.
  - **pkg87 split** (PR #293) — original pkg87 superseded; pkg87a/pkg87b/pkg87c now the Cryptomatte work units.
  - **pkg92 GPU wavefront RNG foundation** (PR #291) — PCG32 + `(pixel,sample,dim)` keying; PractRand CI-enforced statistical gate (TestU01 unbuildable on MinGW).
  - **pkg89 Phase A** (PR #294) — dedicated Light objects (interface + 5 types + integrator wiring); G6/G9 pass; full-scene G8 + G1–G5 deferred to Phase B.
  - **pkg55-B' Session 2c** (PR #297) — CPU wavefront skeleton; EXACT bit-identity by shared-kernel construction (0.0 across all 5 stages, MinGW + Linux-GCC CI).
  - **Doc-pass corrections:** pkg85-D status corrected to done (PR #283, SSIM 0.9793 ≥ 0.97); ReSTIR `test_spatial_reduces_mse` flake filed as issue #298.

- **Round 11 next-up** (per updated NEXT_STAGE_REPORT.md §2; owner direction: **CUDA-port path leads**):
  - **Top priority (lead track):** **pkg55-B' Session N+1** (shadow/miss/terminate stages on CPU — final CPU-only session before CUDA-port begins), then **Sessions N+2..M** (CUDA port of wavefront shade kernels — multi-session, ~4 weeks total; the path to viewport-parity acceptance gate closure).
  - **Second tier (lower priority than CUDA-port track):** pkg94/95/96 addon remediation **all done** (PR #304/305/307, 2026-05-16 — missed in Round 10 closeout; corrected by unblocker run #5, 2026-05-20). Active second tier: **pkg89 Phase B** (Blender addon full-scene lights, PR #317 DRAFT/CI-green — **BLOCKED on real physics defects**; `cycles-parity-reviewer` 2026-05-21 found three invented-algorithm bugs in commit 29f5645; implementer brief at `.astroray_plan/docs/pkg89-phase-b-cycles-parity-2026-05-21.md`; original thresholds G2 < 0.10 / G4 center > 1.0 / G4 corner < 0.01 MUST be restored — no threshold relaxation), **pkg99** (ADAF quasi-spherical glow re-investigation, RTX visual gate required).
  - **Third tier (DEPRIORITIZED):** **pkg100** (.blend importer camera-intrinsics fix — small, unblocks pkg76 CSV rows; **owner decision: DEPRIORITIZED relative to CUDA-port work**), **pkg90** (hardware-verifier build-env bootstrap — unblocks orchestrator HW gate for unattended operation), **pkg76 CSV** (blocked on pkg100).
  - **Deferred:** Issue #276 clearcoat flake (owner triage); issue #298 ReSTIR MC-noise strict-inequality flake (recommend seed-pin or tolerance).
  - **Later:**
    - pkg86 Light Tree (pkg89 Phase A accessors now available)
    - pkg87a/pkg87b/pkg87c Cryptomatte implementation (independent)
    - pkg64-gpu Phase 1 (megakernel target; acknowledged pkg55-C will re-port)
    - pkg85-B full audit (when prioritized)
- **Open items to file when prioritized:**
  - pkg85-B (full CUDA-call audit; multi-day systematic pass)
  - `test_disney_clearcoat_adds_gloss` variance investigation (owner: "always been flakey; clearcoat may not be working well")

### Track A (Claude Code) — previous

- pkg29 prism validation is complete.
- Complete: pkg32 visual diagnostics, pkg33 OIDN, pkg34 backend capability
  guardrails, pkg35 spectral GPU material payloads, and pkg36 shared closure
  graphs.
- Pillar 4 has begun: pkg40 landed Kerr/Schwarzschild metric plugins with
  BPT 1972 analytic gates green. pkg41 adds 39 closed-form metric and
  image-plane validation tests plus static Kerr reference fixtures.

### Track B (Copilot cloud)

- Currently inactive. Most Track B-friendly work has been folded into
  Codex sessions (Track E) since they now have the comprehensive
  package specs and license-fence research notes that Copilot couldn't
  produce reliably from cold context. Track B can resume on pattern-
  matching follow-ups (e.g., Pillar 4 plugins after the strategic gate
  releases) once pkg42-49 specs prove themselves Codex-paste-ready.

### Track C (Cline prototype)

- Active: no
- Current exploration: none

### Track D (Ralph loop)

- Last run: —
- Queue depth: —

### Track E (Codex)

- Round 6 Codex haul (2026-05-11): **pkg42 synchrotron emission**
  (#245, first second-wave Pillar-4 deliverable — VolumetricEmission
  interface now available for pkg43+pkg44 to build on), **pkg80**
  (#246), pkg82 spec filed, pkg78 bisect § 1 refusal documented.
- Round 7 Codex queue (per `NEXT_STAGE_REPORT.md`):
  - **pkg43 slim disk accretion model** (Pillar 4; pkg42 interface
    now available)
  - **pkg44 ADAF accretion model** (Pillar 4; after pkg43)
  - **pkg82 variance characterisation** for issue [#237](https://github.com/HendrikGC02/Astroray/issues/237)
    (~1 day on RTX)
  - **pkg83** addon-only H2 fix (~½ day)
  - **pkg84** addon-only H5 fix (~½ day)
  - **pkg76 CSV** rows for Classroom / Junkshop / BMW27 on RTX
    (~½ day; carries from Round 6 — needed pkg73 fixed first, now
    is)
  - **pkg79** ReSTIR `test_spatial_reduces_mse` flake fix
- Active: coordination, Pillar 4 throughput, CI hygiene.

---

- **2026-05-09** — pkg60 complete on `codex/pkg60-disney-energy-compensation`.
  Added a research note for Kulla & Conty / Burley / Cycles, ported Cycles GGX
  and sheen compensation tables into `data/disney_compensation/`, replaced the
  Disney plugin's old additive multi-scatter boost with LUT-driven
  compensation, corrected Disney specular/clearcoat eval's grazing denominator,
  fixed the mixed-lobe Disney sampler to return the combined PDF instead of the
  selected branch PDF, and added a C++ Halton furnace integration helper plus
  `tests/test_disney_energy_conservation.py`. Measured worst-case directional
  hemispherical reflectance is **1.015891** over the 90 listed
  roughness/metallic/sheen/clearcoat combinations × 3 outgoing cosines at 4096
  samples; regenerated contact sheet reference at
  `tests/reference/disney_contact_sheet_post_compensation.png`.

---

## Historical merge log

This section is a chronological log, not a live "this week" queue. Newer
events are summarized in the changelog below.

| Date | PR | Track | Pillar | Description |
|---|---|---|---|---|
| 2026-04-26 | pkg14-spectral-env-map | A | 2 | Spectral HDRI atlas (`spectralAtlas_` in `EnvironmentMap`, bilinear spectral-space interpolation); env-miss wired to `evalSpectral`; legacy `PathTracer` plugin + `pathTrace()` deleted; `"spectral_path_tracer"` renamed `"path_tracer"`; `IntegratorKind`/`spectralMode_` removed; `Material::eval` virtual deleted; `Material::evalSpectral` made pure virtual. **Pillar 2 complete.** |
| 2026-04-26 | pkg13c-missing-material-plugins | A | 2 | Created 4 missing material plugins: `oren_nayar` (OrenNayar diffuse + spectral override), `isotropic` (uniform volumetric phase function + spectral override), `two_sided` (wraps inner material, renders both faces + spectral delegation), `emissive` (two-sided omnidirectional emitter + `emittedSpectral`). Closes issue #105. 5 new tests; 223 passed, 1 skipped. **pkg13 fully complete.** |
| 2026-04-26 | #106 pkg13b Copilot | B | 2 | 8 procedural texture `sampleSpectral` overrides (checker, noise, gradient, voronoi, brick, musgrave, magic, wave). |
| 2026-04-26 | #104 pkg13a Copilot | B | 2 | `evalSpectral` overrides for Phong, Disney, NormalMapped, `emittedSpectral` for DiffuseLight. |
| 2026-04-26 | #103 pkg13 physics/infra | A | 2 | `Texture::sampleSpectral` virtual + ImageTexture eager cache; Metal per-λ Schlick Fresnel; Dielectric/Mirror delta overrides; Subsurface cached albedo + transmission spectrum. 206 passed (+8 new). |
| 2026-04-25 | pkg12-spectral-lambertian | A | 2 | First concrete `evalSpectral` override: `LambertianPlugin` gains `RGBAlbedoSpectrum albedo_spec_` (eager ctor cache) and `evalSpectral` returning `albedo_spec_.sample(lambdas) * cosTheta / PI`. Cache eliminates per-call Jakob-Hanika LUT lookup. Cornell A/B within 3%. 5 new tests; 198 passed, 1 skipped. |
| 2026-04-25 | pkg11-spectral-path-tracer | A | 2 | Spectral path tracer plugin (`set_integrator("spectral_path_tracer")`), `IntegratorKind` enum, `Material::evalSpectral`/`emittedSpectral` defaults via Jakob-Hanika upsample, `Renderer::pathTraceSpectral` helper + XYZ accumulator + single sRGB conversion. Cornell A/B match within ~3% per channel; 1.34× wall-clock vs RGB. Legacy `path` integrator stays the default. 193 tests (+4 new). |
| 2026-04-24 | pkg10-spectral-types | A | 2 | Spectral scaffolding: `SampledWavelengths`, `SampledSpectrum`, three `RGB*Spectrum` upsamplers over a shipped Jakob-Hanika LUT, CIE 1964 10° CMF + D65 SPD, Python bindings, 189 tests (+20 new). No integration — renderer is untouched. |
| 2026-04-22 | feat/pkg06-pass-registry | A | 1 | Pass registry; OIDN + 3 AOV plugins; Framebuffer API; add_pass/clear_passes bindings; 169 tests passing. **Pillar 1 complete.** |
| 2026-04-22 | feat/pkg05-integrator-interface | A | 1 | Integrator base class, PathTracer + AO plugins, Blender UI selector; 165 tests passing |
| 2026-04-21 | feat/pkg04-migrate-textures-shapes | A | 1 | Migrate 9 textures + 5 shapes to plugin files; 161 tests passing |
| 2026-04-21 | feat/pkg03-migrate-remaining-materials | A | 1 | Migrate remaining materials to plugin files |

---

## Package board

| Package | Track | Status | Blocker |
|---|---|---|---|
| pkg34 | A | **done** | — |
| pkg37 | A/E | **done** | — |
| pkg32 | A+B | **done** | — |
| pkg33 | A | **done** | — |
| pkg38 | B | **done** | — |
| pkg39 | A | **done** | — |
| pkg40 | A | **done** | Kerr/Schwarzschild metric plugins; BPT 1972 analytic gates green |
| pkg41 | A | **done** | PR #236; 39-test `tests/test_kerr_validation.py` suite green; Bardeen/Chandrasekhar references; no GPL/CeCILL code mirrored |
| pkg52 | A | **done** | — |
| pkg53 | B/E | **done** | — |
| pkg54 | A | **done** | pkg54/54a/54b/54c/54d all verified on hardware; pkg54c visible-band SSIM 0.999 gate clears at 0.999263 (spp=8192); GPU `gpu_rgbSpectrumAt` ILLUMINANT renormalization bug found and fixed during verification; frame-time regression +0.45 % (pkg54e not needed) |
| pkg57 | A | **done** | native Astroray shader nodes (Output, Spectral Profile, Sellmeier Glass, IR/UV Response, NRC Hint) with engine-switch survival via `mat.astroray` PointerProperty and Cycles-precedence fallback (existing BsdfPrincipled path unchanged) |
| pkg58 | B | **done** | — |
| pkg59 | A | done | broader vector/UV/Mapping plumbing, named UV layers, and UV debug AOV |
| pkg61 | A/E | **done** | broader CPU/GPU spectral parity tracked separately |
| pkg62 | B | **done** | — |
| pkg64 | A | **done** | PR #230; pkg64-gpu spec PR #258 |
| pkg64-gpu | A | open — ready to implement | Spec PR #258; blocked on pkg55-B architectural review |
| pkg67 | A | **done** | PR #262 Option α — MinkowskiMetric + redshift + frequencyShift |
| pkg82 | A | **done** | PR #261; gate 0.999→0.998; closes issue #237 |
| pkg83 | A | **done** | PR #259; spp_trace accumulates across camera pans |
| pkg84 | A | **done** | PR #260; first frame 83.3 ms (was 12,079 ms) |
| pkg85 | A | **done** | PR #278 (pkg85-C) — 901 passed, 0 CUDA illegal-access crashes; GPU/CPU BVH primitive-array index misalignment fixed; material-lowering bugs fixed; world-only GPU render trigger fixed; pkg85-D filed for HDRI world-only SSIM parity |
| pkg86 | A | open — ready to implement | Light Tree after pkg89 Phase A ships Light::orientationCone() + power() |
| pkg87 | A | **superseded — split into pkg87a/pkg87b/pkg87c** (PR #293, 2026-05-15, owner decision) | Original pkg87 Cryptomatte spec superseded; see pkg87a (infrastructure) / pkg87b (integrator integration) / pkg87c (Blender acceptance) |
| pkg38-light-source-spectra | A | open — ready to implement | Amendment to pkg38: 7 emission SPDs (CIE F2/F3 fluorescent, LED 3000/5000/6500K, sodium vapor, mercury vapor); unblocks pkg89 Phase A MeasuredSPD presets |
| pkg85-D | A | **done** | PR #283, 2026-05-14 — GPU XYZ→sRGB ordering fix closed the 3× green bias; `test_gpu_cpu_ssim_hdri` SSIM 0.9793 ≥ 0.97 gate. (Status corrected during Round 9 closeout — spec had lagged at `open`.) |
| pkg88 | A | Phase A done | Phase A camera motion blur landed PR #284 (Round 8); Phase D blocked by pkg55-B/C |
| pkg89 | A | **Phase A done; Phase B BLOCKED** | PR #294 (Phase A, 2026-05-15) — Light interface + 5 types + integrator wiring; G6/G9 pass, G8 0.41% < 1%; MinGW large-struct heap-corruption fix re-applied. Unblocks pkg86 Light Tree accessors. **Phase B**: PR #317 DRAFT/CI-green; `cycles-parity-reviewer` (2026-05-21) identified three real defects in commit 29f5645 — invented `light_normalize_factor` math (G2 AreaLight D65 6× dim + blue cast), missing `M_1_PI_F` + wrong spectrum class (G4 SpotLight 2.2× dim), linear cone falloff vs Cycles `smoothstepf` (G4 corner 0.43× center). Implementer brief: `.astroray_plan/docs/pkg89-phase-b-cycles-parity-2026-05-21.md`. Original thresholds (G2 < 0.10, G4 center > 1.0, G4 corner < 0.01) MUST be restored — no threshold relaxation. |
| pkg91 | A | **done** | PR #290, 2026-05-15 — Fork A.1 + B.1: `Integrator::setMaxDepth(int)` virtual + integrator rebuild on `set_integrator_param`; 4 tests pass; post-construction param change verified (3.6% brightness diff proves max_depth now takes effect). Closes Q1+Q2 footguns surfaced during pkg55-B' Session 2b. |
| pkg92 | A | **done** | PR #291, 2026-05-15 — PCG32 keyed by `(pixel, sample, dim)`; equivalence test passes at 64 spp (per-channel mean ratios within 5%). PractRand statistical gate CI-enforced; stream-disjointness threshold 0.03 @1024 with documented 1/√N rationale; TestU01 documented unbuildable on MinGW, PractRand substituted per owner decision. |
| pkg94 | A | **done** | PR #304, 2026-05-16 — build-integrity guard: `astroray.__build__` attribute exposed, `register()` guard fires on stale-module mismatch, unit tests pass. Verifiability multiplier for all subsequent addon fixes. |
| pkg95 | A | **done** | PR #305, 2026-05-16 — P3-a: preview-path TypeError fix (standalone converter, no `RenderEngine()` construct); P3-c: custom-node defensive detection (checks both flattened + original trees); P3-b: `if False` gate removed + `set_material_spectral_profile` wired; P4: Blender-native `perspective_matrix` vfov (hardcoded 32 mm deleted). |
| pkg96 | A | **done** | PR #307, 2026-05-16 — P2: reconcile-then-upload sync (world/device_mode domains re-derive state before push); P5: GPU+AOV honesty guard (warning when GPU mode + CPU-only AOV pass, no silent routing change). |
| pkg55-B-prime-cuda-gate-derivation | A/E | **done** | PR #320, 2026-05-17 — two-tier CPU↔CPU / CPU↔GPU gate definition now authoritative in pkg55 spec; design decision #9 (shared-kernel, never re-transcribe); A.1 ray-normalization checklist item added to Session-2c design doc. Unblocks pkg55-B' CUDA-port Sessions N+2..M. |
| pkg90 | A | open — ready to implement | Hardware-verifier build-env bootstrap (MSVC + worktree-parameterized CUDA build); unblocks orchestrator HW gate for unattended operation. Spec PR #319. |
| pkg99 | A | open — ready to implement | ADAF quasi-spherical glow re-investigation; pkg44 wiring correct but visual gate only partial (faint emission sliver vs quasi-spherical glow). Spec PR #315. |
| pkg100 | A | open — ready to implement | .blend importer camera-intrinsics dynamic-attr defect fix; blocks pkg76 §3.5 CSV follow-up. Spec PR #321. |
| pkg68 | A | **done** | persistent OIDN device, CUDA-first init, member-cached filter; CUDA verifier session 2026-05-10 on RTX 5070 Ti: 13/13 pytest green (incl. `test_cuda_capable_build_reports_cuda_device`), `[OIDN] Using CUDA device` confirmed, single device init across N=4 renders verified; viewport timing 256×256 spp=2: OIDN-on 50.67 ms/frame vs OIDN-off baseline 23.81 ms/frame (Δ=26.86 ms persistent-device overhead) |
| pkg69 | A | **done** | Blender compositor denoise Albedo/Normal data passes |
| pkg70 | A | **done** | OptiX denoiser plugin co-equal with OIDN; persistent OptixDeviceContext + OptixDenoiser handle, lazy init, HDR vs AOV model selection by guide presence; `gpu_optix_available()` Python probe; addon `denoiser_backend` Auto/OptiX/OIDN with OptiX preferred when both present. **Verified 2026-05-10 on RTX 5070 Ti + OptiX 9.1.0**: 17/17 pytest green; 5.31× synthetic-noise reduction at 256×256; 1.86× faster than OIDN-CUDA at 1080p (728.94 ms vs 1356.09 ms); SSIM(OptiX, OIDN) = 0.9987. Empty-normal-buffer defect surfaced upstream during verification → tracked as pkg75 |
| pkg71 | A | **implemented** | benchmark framework done; first full baseline CSV pending CUDA/Cycles hardware |
| pkg74 | A | **done (all phases)** | Phase 1: framework + material zoo + Cornell convergence grid + log-log RMSE curve + stats CSV + HTML index. Phase 2: full stat catalog from research note §2 (geometry / memory / timing / sampling / quality / spectral / GPU / integrator-specific) per-row, paired-seed variance render, log-log convergence-rate slope on the curve (measured −0.453 vs MC target −0.5 on the implementer machine), new `integrator_compare` scene + bar-chart timing artefact, `--gpu` flag with clean fallback when CUDA absent. Phase 3: self-contained PBRT-style HTML dashboard with inlined artefacts/RMSE plots, sortable stats tables, scene filter, run-history navigation, and weekly self-hosted CI guarded by `ASTRORAY_RUN_SHOWCASE_WEEKLY`. Pure Python — no engine bindings added (per spec design decision #7); forward-compat probes populate BVH/GPU-mem/per-ray-type columns the moment those bindings land. Pytest gates: `test_benchmark_showcase_runs.py`, `test_benchmark_showcase_phase2.py`, and `test_pkg74_phase3_html.py`. |
| pkg75 | A | **done** | first-hit normal buffer population for denoiser AOV guides; root cause was a missing `r.normal = rec.normal` in `plugins/integrators/spectral_path_tracer.cpp::sampleFull` (the integrator registered as `path_tracer`, the actual default per `src/default_integrator.cpp`). Canonical render loop at `include/raytracer.h:2452` was already copying `ir.normal` faithfully — the upstream value was just `Vec3(0)`. Fix is one line, cites Cycles `intern/cycles/integrator/pass.cpp` PASS_NORMAL semantics. New `tests/test_normal_buffer_populated.py` asserts unit-length world-space normals at every hit pixel and `Vec3(0)` at misses. Re-baseline (PR #223) confirms post-pkg75 OIDN-on −7.3% (50.67→46.98 ms), pkg68 headline win up 2.57×→2.77× |
| pkg72 | A | **done** | per-pixel motion vector AOV (camera-only screen-space flow); `Camera::motionBuffer` (float2/pixel, OptiX prev→curr convention) populated by primary-ray write site in `Renderer::render`; `Camera::snapshotForMotion()` runs at end of every frame; `setup_camera` carries the prev-projection snapshot across re-uploads so Blender viewport pans produce non-zero flow on frame 2+; `Renderer.get_motion_buffer()` returns a zero-copy NumPy view shaped `(H, W, 2)`; `motion_vector_aov` plugin visualises the buffer; mirrors Cycles `intern/cycles/integrator/pass.cpp` PASS_MOTION (Apache-2.0). Unblocks pkg73 OptiX temporal denoiser |

---

## Known issues

- **pkg55-B wavefront radiance accounting bugs (HELD on origin/pkg55-phase-b)** —
  NOT merged. Three cascading bugs discovered: Bug 1 (`path_alive` initialization,
  fixed in 15d98f0), Bugs 2+3 (sample accumulation order + NEE×throughput)
  attempted fix REGRESSED from 2.5× brightness vs megakernel pre-fix to 21×
  brightness post-fix. **Superseded by the Phase B' CPU-first restart on main**
  (PR #266 amendment; Sessions 2b PR #281 + 2c PR #297 landed — CPU wavefront
  now bit-identical to `reference_pt_wavefront` by shared-kernel construction).
  origin/pkg55-phase-b remains a HELD reference only.
- **pkg55-B' two-tier gate re-derivation DONE** — the program-wide "bit-identity
  gates each port" line (Sessions N+2..M) has been re-derived into a **two-tier**
  gate (exact CPU↔CPU / bounded+SSIM CPU↔GPU) per PR #296 §4.4. The pkg55 spec
  now carries the authoritative two-tier definition (§4.2 table), design decision
  #9 (shared-kernel, never re-transcribe), and the GATE-THRESHOLDS-PINNED named
  gate (Session N+2 must measure-then-pin ULP/p99.9/SSIM bounds before any CUDA
  code change). The A.1 ray-normalization checklist item has been added to the
  Session-2c design doc. **Unblocks Sessions N+2..M** (CUDA-port sessions); Sessions
  3..N (growing-oracle expansion on CPU) were never blocked and proceed with the
  existing exact-0.0 CPU↔CPU gate.
- **ReSTIR `test_spatial_reduces_mse` MC-noise flake** —
  [Issue #298](https://github.com/HendrikGC02/Astroray/issues/298):
  `tests/test_restir_validation.py::TestSpatialMSE::test_spatial_reduces_mse`
  non-deterministically fails on a strict inequality (observed
  `no-reuse=0.008578` vs `spatial=0.008593`, ~0.2% inversion). MC-noise on a
  too-tight assertion, not a correctness regression. Distinct from #276.
  Recommended fix: seed-pin or tolerance/seed-averaging. Supersedes the
  informal "pkg79" note.
- **Disney clearcoat flake + suspected correctness defect** — [Issue #276](https://github.com/HendrikGC02/Astroray/issues/276): `test_disney_clearcoat_adds_gloss` chronic variance flake (PASSED/FAILED on identical scenes), owner notes clearcoat "may not be working well." Suggested package number `pkg90` in the issue body. Labels: bug, material.
- **Pyd-shadow-guard hook upgrade** — `.claude/hooks/pre-pytest` warns on shadow pyds but doesn't auto-delete. Stale `astroray.pyd` (pkg84-era legacy name) at repo root shadowed fresh `astroray.cp313-win_amd64.pyd` from `build_cuda/Release/` twice in 2026-05-14 sessions. Potential follow-up package to upgrade hook to auto-delete before pytest.
- **Stale orphan worktree directories** — 18 in `.claude/worktrees/*` from 2026-05-14 sessions: git registry removed them but OneDrive perm-denied the directory unlink. Cosmetic; clean later with non-sandboxed shell.
- `include/raytracer.h` and `include/advanced_features.h` still contain texture class bodies (`CheckerTexture`, `NoiseTexture`, etc.). These are used directly by `blender_module.cpp` and will be cleaned up in a future package if the plan calls for it.
- ReSTIR/NRC work is implemented through pkg28 but remains in validation:
  the target NRC batched-inference speedup is not proven, and `restir-di` /
  `neural-cache` currently report CPU-only GPU capability reasons.
- Windows verification is sensitive to stale build caches; test bootstrap now supports `ASTRORAY_BUILD_DIR` and standard `build/Release` layouts, but the old `build/` cache on this workstation still points at a missing MinGW install.
- ReSTIR temporal variance has a known tiny deterministic inversion on this
  workstation (`0.0723` temporal vs `0.0719` no-reuse). The test now xfails
  only this narrow <2% baseline condition while still failing larger regressions.
- Prism-style spectral dispersion now has a deterministic validation scene and
  saved render outputs. pkg29a adds caustic validation scenes, metrics, and an
  opt-in specular-chain connection experiment; it is still not a final
  caustic-perfect showcase.
- GPU material support is now capability-gated, so unsupported materials no
  longer silently lower to approximate CUDA records. pkg35 adds sampled
  wavelength payloads and `gpu_spectral` metadata for the core GPU material
  set. pkg54/54a/54b are done: pkg54 landed a CUDA megakernel mirror of
  `multiwavelength_path_tracer` (visible/NIR/UV bands, luminance + sRGB
  output, `gpuSupported = true`); pkg54a added per-material spectral-profile
  dispatch on the GPU; pkg54b replaced the Wyman 2013 1931 2° CMF fit with
  the same baked CIE 1964 10° table the CPU uses, and a D65-SPD parity bug
  (Gaussian stand-in for the true SPD) was fixed during hardware
  verification. pkg54d added a direct `gpu_profile_reflectance` binding for
  unconfounded liveness gating, with CPU/GPU lookup max delta `0` across all
  loaded profiles on the 300-1000 nm grid. pkg54c (Jakob-Hanika spectral
  upsampling on GPU, SSIM ceiling 0.985→0.999) is now implemented:
  `gpu_jhEvalSpectrum` mirrors `RGBAlbedoSpectrum::sample` via the same
  shared `jhEvalSpectrumF` evaluator, the sRGB sigmoid LUT is uploaded to
  device global memory once per process via `uploadJakobHanikaLut`
  (cudaMalloc + cudaMemcpyToSymbol of pointers, 9 MB — overflows the
  64 KB constant cap), and `gpu_rgbSpectrumAt` upsamples through it for
  both `GSPEC_RGB_ALBEDO` and `GSPEC_RGB_ILLUMINANT`. Verified on CUDA
  hardware 2026-05-10: visible-band CPU↔GPU SSIM = 0.999263 at spp=8192
  on the parity scene (gate ≥ 0.999), per-channel mean ratios within
  0.4 %, frame-time regression +0.45 % at 1080p / 64 spp / depth 4.
  A real GPU bug — `gpu_rgbSpectrumAt` ILLUMINANT mode missed the
  CPU's `2·max(rgb)` renormalize-then-rescale step, causing wrong
  absolute spectra for any HDR emitter — was found and fixed during
  verification (see pkg54c Lessons). The 0.999 SSIM gate is unreachable
  at the original 64 spp regardless of evaluator correctness because
  CPU OpenMP and GPU warp-parallel integrators place MC samples on
  different per-pixel sub-streams; the test now runs at spp=8192
  (~5 s on RTX-class hardware) where the noise floor drops below
  the gate by ~26 %.
  Sellmeier direction-splitting and true spectral emitter parameter
  upload also remain CPU-only follow-ups. pkg36 expands shared closure
  lowering.
- The Blender addon backend UI/packaging refresh from pkg37 is complete.
  Remaining Blender parity work is narrower: pkg57 shader graph
  fidelity and pkg54 multi-wavelength GPU parity. pkg52 persistent viewport
  sessions and pkg62 viewport pass/OIDN UX are complete on `origin/main` plus
  the current pkg52 branch.
- Documentation drift found on 2026-05-09: `NEXT_STAGE_REPORT.md` is a
  historical 2026-04-29 snapshot; `production.md` had old pkg50+ placeholders
  that conflicted with live package numbers; package headers for pkg12-pkg14
  still said open despite Pillar 2 being complete. These were reconciled in
  this docs pass.

---

## Decisions pending (for project owner)

- Confirm whether lights should be migrated to plugins (currently out of scope per pkg04 non-goals) and if so, which package handles it.

---

## Changelog

Brief notes on notable events.

- **2026-05-20 (doc-drift correction — unblocker run #5)** — pkg94/95/96 retroactively added to package board; second-tier dispatch queue corrected. All three addon-remediation packages shipped 2026-05-16 (pkg94 PR #304, pkg95 PR #305, pkg96 PR #307) but were omitted from the Round 10 closeout docs (PR #322, 2026-05-17). Unblocker runs #1–#4 incorrectly flagged pkg95/pkg96 as not-started and queued them for dispatch. **PR #327** (`pkg55-B' Session N+1`): two CI bugs fixed (bare `skimage` import, then `render()` wrong positional args → SIGABRT); CI rerun in progress as of 20:35 UTC. Gate-failure-reviewer (dispatched by orchestrator at 19:16 UTC) diagnosed and pushed the SIGABRT fix (commit `f78ad87`). Once CI passes, PR #327 is CPU-only and can be merged without HW gate — then Session N+2 (CUDA port, requires local Windows RTX) is the next dispatch.

- **2026-05-17 (Round 10 closeout)** — 7 PRs merged; Pillar 4 → 50%; pkg55-B' growing-oracle expansion complete.
  - **pkg44 ADAF accretion model** (PR #310, 2026-05-17) — Narayan & Yi 1995 self-similar ADAF solution + Yuan & Narayan 2014 prefactors; synchrotron (Pandya 2016 reused from pkg42) + bremsstrahlung thermal emission; 19 tests pass (power-law exponents exact, Sgr A* profiles within tolerance). Pillar 4 → ~50%.
  - **pkg99 spec — ADAF quasi-spherical glow re-investigation** (PR #315, 2026-05-17, doc-only) — pkg44 wiring correct but visual gate only partial (crisp shadow + faint emission sliver vs the specified quasi-spherical glow). Unblocks RTX visual-iteration follow-up.
  - **pkg55-B' Session 7 — Diffuse Light** (PR #316, 2026-05-17) — scope guard extended to `lambertian + metal + dielectric + disney + thin_glass + diffuse_light`. Emissive sphere test coverage (distinct from area light triangles). Bit-identity gate: PASS (max abs diff 0.0, diverging fields 0). Full suite: 1006 passed. Production codegen: byte-unchanged.
  - **pkg55-B' Session 8 — Closure Graph** (PR #318, 2026-05-17) — scope guard extended to all seven material types (`lambertian + metal + dielectric + disney + thin_glass + diffuse_light + closure_graph`). Closure_matte sphere (blue-tinted diffuse). Bit-identity gate: PASS (max abs diff 0.0, diverging fields 0). Full suite: 1006 passed. Production codegen: byte-unchanged. **Growing-oracle expansion now complete before Session N+1 (shadow/miss/terminate stages).**
  - **pkg90 spec — Hardware-verifier build-env bootstrap** (PR #319, 2026-05-17, doc-only) — MSVC + worktree-parameterized CUDA build; unblocks orchestrator HW gate for unattended operation (currently `hw_blocked_buildenv` on every HW-gated PR).
  - **pkg55-B-prime-cuda-gate-derivation** (PR #320, 2026-05-17, doc-only) — two-tier CPU↔CPU / CPU↔GPU gate definition now authoritative in pkg55 spec (exact bit-identity for CPU↔CPU, ULP-bounded + SSIM for CPU↔GPU); design decision #9 added (shared-kernel, never re-transcribe); A.1 ray-normalization checklist item added to Session-2c design doc. Unblocks CUDA-port Sessions N+2..M.
  - **pkg100 spec — .blend importer camera-intrinsics dynamic-attr defect** (PR #321, 2026-05-17, doc-only) — every `.blend` import fails with `AttributeError: 'astroray.Renderer' object has no attribute '_cam_intrinsics' and no __dict__`; blocks pkg76 §3.5 CSV follow-up (Classroom / Junkshop / BMW27 RTX parity rows).

- **2026-05-16 (Round 9 closeout)** — 6 PRs merged; status corrections + 1 flake issue filed.
  - **pkg91 integrator parameter lifecycle** (PR #290, 2026-05-15) — Fork A.1 + B.1: `Integrator::setMaxDepth(int)` virtual + integrator rebuild on `set_integrator_param`. Closes Q1 (`Renderer.render(max_depth=N)` silently ignored under integrators) + Q2 (`set_integrator_param` after `set_integrator` no-op). 4 tests pass; post-construction change verified (3.6% brightness diff).
  - **pkg47 FITS data loader** (PR #292, 2026-05-15) — FITS I/O wrapper + FITSTexture plugin + CMake gate `ASTRORAY_ENABLE_FITS` (default OFF). FITSVolume registration + test deferred to pkg48 per owner ruling. Pillar 4 → ~45%.
  - **pkg87 split** (PR #293, 2026-05-15) — owner decision: original pkg87 Cryptomatte spec superseded; split into **pkg87a** (infrastructure), **pkg87b** (integrator integration), **pkg87c** (Blender acceptance). All three specs on main.
  - **pkg92 GPU wavefront RNG foundation** (PR #291, 2026-05-15) — PCG32 keyed by `(pixel, sample, dim)`; equivalence test passes at 64 spp (per-channel mean ratios within 5%). PractRand statistical gate CI-enforced; stream-disjointness threshold 0.03 @1024 with documented 1/√N rationale; TestU01 documented unbuildable on MinGW → PractRand substituted per owner decision.
  - **pkg89 Phase A — dedicated Light objects** (PR #294, 2026-05-15) — Light interface + 5 types (Point/Spot/Distant/Area/Background) + integrator wiring. G6/G9 pass; G8 spectral fidelity 0.41% < 1% threshold; MinGW large-struct heap-corruption fix re-applied. Full-scene G8 + G1–G5 explicitly Phase B (Blender addon). Unblocks pkg86 Light Tree accessors.
  - **pkg55-B' Session 2c — CPU wavefront skeleton** (PR #297, 2026-05-15) — EXACT bit-identity **by shared-kernel construction** (one per-bounce kernel called by both `reference_pt_wavefront` and the `cpu_wavefront` driver): max abs diff exactly 0.0 across all 5 snapshot stages on 1 spp Lambertian Cornell, verified MinGW + Linux-GCC CI; production codegen byte-unchanged; scaffold `-ffp-contract=off` is a documented guard only. Spec's two-tier-gate NOTE preserved for the upcoming CUDA sessions.
  - **Status corrections in this doc pass:** pkg85-D flipped open → done (PR #283, 2026-05-14 — GPU XYZ→sRGB ordering fix; `test_gpu_cpu_ssim_hdri` SSIM 0.9793 ≥ 0.97; spec had lagged at `open`).
  - **Flake issue filed:** [#298](https://github.com/HendrikGC02/Astroray/issues/298) — ReSTIR `test_spatial_reduces_mse` MC-noise strict-inequality flake (distinct from #276); recommend seed-pin or tolerance.
  - **Open doc PRs (context only, not round-work):** #295 (Blender addon bug triage), #296 (pkg55-2c technique review). Addon-bug fixes are owner-gated on review + the forthcoming architect first-principles plan.

- **2026-05-15 (architect — Q1/Q2/Q3 from pkg55-B' Session 2b)** — doc-only PR. Two specs filed (status: open, spec-promotion pending owner answers on the listed forks):
  - **pkg91 integrator-param-lifecycle** — unifies Q1 (`Renderer.render(max_depth=N)` silently ignored) + Q2 (`set_integrator_param` after `set_integrator` is a no-op). Same architectural bug: `ParamDict` read-once-at-construction with no API contract. Recommendation: `Integrator::setMaxDepth(int)` virtual + `setIntegratorParam` rebuilds on registered-integrator. Forks A/B listed; owner picks at promotion. Cites Cycles `intern/cycles/integrator/path_trace.h` (live-setter) and PBRT-v4 `src/pbrt/integrators.cpp` (rebuild-only). Apache-2.0.
  - **pkg92 gpu-wavefront-rng-foundation** — replaces `reference_pt_wavefront`'s `mt19937(FNV1a(pixel, sample, 0))` keying with PCG32 + PBRT-v4-style `(seed, stream(pixel, sample, dim))`. Cites Cycles `intern/cycles/util/hash.h` `hash_pcg*_uint` family (Apache-2.0), PBRT-v4 `src/pbrt/util/rng.h` `RNG` class (Apache-2.0), Mitsuba 3 `random.h` (BSD-3), PCG paper (O'Neill 2014, public reference impl at `imneme/pcg-cpp` Apache-2.0/MIT). Forks A (PCG32 vs Philox), B (PBRT vs Cycles keying), C (per-draw vs per-bounce dim counter) listed; recommendation = PCG32 + PBRT keying + per-draw dim. Retrofits CPU oracle BEFORE the CUDA port starts so the bit-identity diff harnesses baseline against the final keying once.
  - **Recommended priority/ordering:** pkg91 first (~½–1 session, blocks no further Phase-B' sessions but pays back the next time anyone changes `max_depth` mid-session). pkg92 before any CUDA-port session of pkg55 Phase B' (~2 sessions; one rebaseline of the equivalence test). Both parallel-safe with each other and with current Wave-1/Wave-2 PRs (no file-touching overlap).

- **2026-05-14 (Round 8 mid-cycle sync #2)** — implementation wave in progress. **7 PRs merged since previous sync:**
  - **PR #271** (5e081ee) — **pkg43 slim disk accretion model** (Abramowicz 1988 / Sadowski 2009). Includes `SampledWavelengths::fromLambdas` factory addition to `spectrum.h`. Units fix: r_s → r_g convention. Spec measurement-corrected: 1.62e8 K → 7.45e6 K at canonical point. 14/14 tests pass + pkg42 no regression.
  - **PR #273** (e093a70) — **pkg88 + pkg89 DRAFT specs promoted to real specs** (architect spec-promotion pass + owner answers locked in). pkg88: box-shutter only, scene-wide steps, Cycles default 0.5 frame center, single consistent stratification policy. pkg89: extended 4-mode emission UX with blackbody+color-as-filter, RGB upsample, MeasuredSPD presets, Composite. DRAFT files deleted.
  - **PR #274** (81a1b18) — **pkg38-light-source-spectra amendment spec filed** (7 SPDs: CIE F2/F3 fluorescent, LED 3000/5000/6500K, sodium vapor, mercury vapor; all public-domain / CC; unblocks pkg89 Phase A).
  - **PR #275** (2f03ee6) — repo cleanup (moved 3 dev measurement scripts to `dev/measurement-scripts/`; `sitecustomize.py` correctly kept at root for Windows DLL discovery bootstrap).
  - **PR #277** (59fb543) — **pkg85 partial follow-up** (wrap autouse GC fixture cleanup in try/except so cleanup exceptions don't surface as test teardown ERROR).
  - **PR #278** (063bd42) — **pkg85-C closes pkg85 spec gate**. Two root causes: (1) GPU/CPU BVH primitive-array index misalignment (`scene_upload.cu` silently dropped non-{Triangle,Sphere} primitives but CPU BVH was built from full scene; localized via compute-sanitizer as 1-byte OOB read at +8 past 8-byte allocation; fixed by introducing `GPRIM_SKIP` placeholder). (2) World-only GPU render rejected with "Scene not uploaded" (gate fixed to `(!d_bvhNodes && !envMap.loaded)`). Result: **901 passed, 0 CUDA illegal-access crashes**. Material contact sheet now renders cleanly at 480×480 / 1024 spp. pkg85-D filed as new follow-up (HDRI world-only SSIM parity bug surfaced once the original blockers cleared).
  - **Direct pushes** (ec28667, 4ae14d7, eff21fd, 28ea478) — pkg43 handoff notes restoration, round8 dispatch queue + owner answers, CLAUDE.md workflow sections, `/pkg-ship` skill + design notes codification.
  **Status changes:** pkg85 → done (pkg85-C gate cleared); pkg43 → done (PR #271); pkg88 + pkg89 → open with promoted specs; pkg38-light-source-spectra → open (new amendment spec). **New issues/follow-ups:** pkg85-D (HDRI world-only SSIM parity, SSIM ≈0.35 vs 0.97 gate), [Issue #276](https://github.com/HendrikGC02/Astroray/issues/276) (`test_disney_clearcoat_adds_gloss` chronic flake + suspected clearcoat correctness defect, suggested pkg90). **Hardware verification headline (RTX 5070 Ti, commit 063bd42):** 910/911 pytest passed (1 known ReSTIR spatial MSE flake), build 4m20s / 52 MB, caustics + material contact sheet rendered cleanly at 8192 spp + 1024 spp respectively.

- **2026-05-14 (Round 8 mid-cycle docs sync)** — doc/spec/research wave landed; implementation wave starts next session. **8 PRs merged:**
  - **PR #263** (c476308) — Round 8 strategy pass (architect assessment of pkg55-B fork decision, Cycles-parity gap decomposition, top 3 non-pkg55 follow-ups ranked: Light Tree + Cryptomatte highest leverage).
  - **PR #266** (fa896ff) — pkg55 Phase B' amendment (CPU-first restart spec now authoritative on main; 8 design decisions; session 1 summary at `.astroray_plan/docs/pkg55-B-restart-session1-summary.md`).
  - **PR #265** (9cc920f) — pkg86 Light Tree spec (Conty 2018 + Cycles Apache-2.0; status open, ready to implement after pkg89 Phase A).
  - **PR #264** (9403a8b) — pkg87 Cryptomatte spec (Psyop BSD-3 + Cycles Apache-2.0; status open, ready to implement; independent).
  - **PR #267** (e3d5d1b) — pkg88 motion blur research note + DRAFT spec (research signed off; design Qs deferred).
  - **PR #268** (5583bc0) — **pkg85 partial fix** — conftest autouse fixture + cuda_renderer error clearing; robustness improvement only; spec gate NOT met (full pytest sweep crash still reproduces); full CUDA-call audit queued as pkg85-B follow-up.
  - **PR #269** (bd13a03) — pkg89 dedicated lights research note + DRAFT spec (research signed off; Q1/Q6/Q7/Q11 answered in round8-dispatch-queue.md).
  - **Direct push** (4ae14d7) — Round 8 dispatch queue capturing owner's session-close answers.
  **Status changes:** pkg85 → partial (not done); pkg86/87/88/89 → open (new specs/research). **pkg55-B Phase B' CPU-first restart** is now the authoritative path forward on main; origin/pkg55-phase-b HELD as reference. **Open items to file when prioritized:** pkg85-B (full CUDA-call audit, multi-day), `test_disney_clearcoat_adds_gloss` variance investigation (owner notes "always been flakey; clearcoat may not be working well").

- **2026-05-14 (Round 7 closeout)** — four packages landed; pkg55-B held
  on branch for architectural review; pkg85 follow-up filed. **pkg82
  variance characterisation** (PR #261) — gate re-baselined 0.999→0.998
  based on measured cross-build delta 0.0006; intra-binary perfect
  determinism (20 runs, stddev=0); closes issue #237. **pkg83 progressive
  accumulation** (PR #259) — viewport accumulator continues across pure
  camera transforms (pan/orbit/dolly); `spp_trace = [1,2,3,4,5,6,7,8]`
  measured on CPU + CUDA; substantive changes (focal length, DoF, lens
  shift) still reset correctly. **pkg84 CUDA pre-warm** (PR #260) — first
  CUDA frame 83.3 ms (≤100ms gate), **145× faster than pkg81 cold-start
  baseline** (12,079 ms→83 ms); cites Cycles `reserve_local_memory`
  pattern (Apache-2.0). **pkg67 GR spectral unification** (PR #262,
  Option α) — `MinkowskiMetric` + `SampledWavelengths::redshift(g)` +
  `GRSpectralResult::frequencyShift`; all 9 unit tests + flat regression
  + Schwarzschild deflection passing; ratifies existing `BlackHole`-as-
  `Hittable` architecture. **pkg64-gpu spec filed** (PR #258, docs-only)
  — GPU SMS port targeting AoS megakernel; 4 fork-point decisions +
  register-pressure baseline baked in via architect review. **pkg55-B
  HELD** on `origin/pkg55-phase-b` — cascading wavefront radiance bugs
  (Bug 1 `path_alive` init ✓, Bugs 2+3 sample-accumulation-order +
  NEE×throughput — REGRESSED 2.5×→21× brightness post-fix); needs
  architectural review. **pkg85 filed** — test-harness CUDA state leak
  (`pytest tests/` crashes at test #370; isolated test passes); bisect
  candidate range tests 360–369.

- **2026-05-11 (Round 6 close)** — six of eight Round-6 sessions
  shipped on planned scope: **pkg42 synchrotron emission** (#245,
  Pillar 4), **pkg80 Blender `'auto'` integrator fix** (#246,
  daily-blocker), **pkg73 fix** (#249, denoiser story closes end-
  to-end at **53.1% variance reduction**), **pkg81 Phase 1+2** (#248,
  viewport-parity harness + diagnosis: **CUDA 104 ms vs CPU 58 ms**
  on 100k-tri load), **pkg55 Phase A.1** (#250, SoA path state +
  intersect queue gated). pkg82 spec filed (#247) after pkg78 bisect
  refused on §1 grounds; pkg83+pkg84 specs filed (#253) for the
  small H2/H5 follow-ups from pkg81. **Pillar 5 viewport-parity
  acceptance gate is now formally owned by pkg55 Phase B**, the
  long-tail Round-7 deliverable. Four small Round-6 leftovers
  (pkg82 variance, pkg76 CSV, pkg83, pkg84) carried into Round 7.

- **2026-05-11 (pkg81 measurement-complete)** — first honest
  Astroray-vs-Cycles viewport numbers exist. Harness + 16-config
  sweep + diagnosis note shipped (PR #248). Headline: **CUDA 104 ms
  vs CPU 58 ms on identical 100k-tri load** — pkg55 Phase A's
  158 regs/thread + 1 active block/SM cliff is now measurably
  costing the user, not just a documented number. **H4 (megakernel
  register pressure) dominates;** H5 (12 s cold-start), H2
  (accumulator-reset-per-pan), H3 (OIDN blocking on CPU) all
  confirmed at smaller magnitudes. H1 ruled out. **Phase 3 routes
  to pkg55 Phase B** per spec escape; Phase B now owns the
  viewport-parity acceptance gate (CUDA pan-frame p99 ≤ 1.2×
  Cycles-CUDA). H2 + H5 split out as **pkg83** + **pkg84** for
  immediate addon-side wins.

- **2026-05-11 (pkg73 closeout)** — pkg73 OptiX TEMPORAL_AOV defect
  fixed in PR #249. Hardware-verified on RTX 5070 Ti / OptiX 9.1 /
  CUDA 12.8: **53.1% inter-frame variance reduction (gate ≥30%),
  5/5 tests pass**. Two compounding root causes both fixed: plugin's
  `OptixDenoiserParams::temporalModeUsePreviousLayers` was never set
  (OptiX silently treated every frame as a new sequence start), and
  the test's AOV reference was silently upgraded to TEMPORAL_AOV by
  sub-pixel float dust in `projectToPrevPixel`. Diagnostic prints
  from PR #241 removed. **Denoiser story closes end-to-end** (pkg33
  → pkg68 → pkg69 → pkg70 → pkg72 → pkg73). Cited Cycles
  `intern/cycles/integrator/path_trace_work_gpu.cpp` (Apache-2.0).

- **2026-05-10 (Round 5 close)** — Strategic gate **released**.
  Seven PRs landed: pkg56 Phase C depsgraph dispatch (#233 — the
  gate-releaser, idle ≤5 ms p99), pkg74 Phase 3 interactive HTML +
  weekly CI (#232), pkg76 `.blend` importer (#240 — SDNA-walking
  offline reader, no `bpy` runtime), pkg55 Phase A wavefront baseline
  (#238 — 158 regs/thread + 1 active block/SM cliff documented),
  pkg41 Kerr validation (#236, **first post-gate Pillar-4
  deliverable**), pkg73 diag instrumentation (#241), pkg64-3 hardware
  re-baseline rebuild (#239 — 1.18× receiver-energy, +0.26 dB PSNR,
  2.0% overhead, all gates met). pkg73 itself shipped in Round 4 but
  failed hardware verification: 0% inter-frame variance reduction;
  diag prints captured the chain end-to-end for a Round 6 fix.
  pkg78 verifier ran the spec's defect path correctly — proved the
  drift PRE-DATES pkg75 — filed as issue [#237](https://github.com/HendrikGC02/Astroray/issues/237)
  for Round 6 bisect.

- **2026-05-10 (Round 4 close)** — Five PRs landed: pkg73 OptiX
  TEMPORAL_AOV denoiser (#228), pkg56 Phase B uploadScene split
  + transform-refit fast path (#229), pkg64 Phase 3 SMS folded into
  default `path_tracer` (#230), pkg76 spec (#227), pkg72 + pkg64-2
  hardware verifier (#226). Test bootstrap fix in #225 unblocked
  pytest collection (0 → 801 tests). All five Round-4 PRs cited
  Apache-2.0 Cycles references where applicable; CLAUDE.md §6
  license fence held end-to-end.

- **2026-05-10 (Round 3 close)** — Five packages landed in one round:
  pkg72 motion vectors, pkg64 Phase 2 spectral SMS (+8.83 dB PSNR delta,
  0.98× runtime), pkg74 Phase 2 full stat coverage (8 categories,
  convergence rate slope −0.453), pkg75 normal-buffer fix (verified
  via visual diff: detail preservation, not regression), and pkg71
  first canonical Cornell baseline (**Astroray-CPU SSIM 0.9536,
  Astroray-GPU SSIM 0.9548 vs Cycles-CPU EXR; Astroray-GPU 5.2× faster
  than Cycles-CUDA at the same Cornell sample budget; Astroray uses
  3-4× less memory than Cycles**). pkg68 headline OIDN-on speedup vs
  pre-pkg68 strengthened from 2.57× to **2.77×** post-pkg75. Build
  hygiene fixed (Windows OptiX, OIDN DLL bootstrap, harness EXR-vs-EXR
  parity). Round 4 (pkg73 OptiX temporal denoiser, pkg56 Phase B
  uploadScene split, pkg64 Phase 3 default-integrator fold, pkg74
  Phase 3 interactive HTML+CI, pkg76 .blend importer spec) queued in
  NEXT_STAGE_REPORT.md.

- **2026-05-10** — pkg70 **verified and promoted to done** on RTX 5070 Ti +
  OptiX 9.1.0 (Windows MSVC `build_cuda`). 17/17 pytest green
  (4 OptiX + 3 OIDN-pass + 3 OIDN-persistence + 7 AOV); first
  `[OptiX] Using CUDA device 0 (NVIDIA GeForce RTX 5070 Ti)` printed
  exactly once across N=4 renders; synthetic-noise reduction at 256×256
  Cornell scene = **5.31× OptiX, 5.58× OIDN** (both ≥5× gate);
  1080p timing on pkg54a/b parity scene = **728.94 ms/frame OptiX vs
  1356.09 ms/frame OIDN-CUDA = 1.86× speedup** (≥1.5× gate);
  **SSIM(OptiX, OIDN) = 0.9987** at spp=16 Reinhard-tone-mapped
  (≥0.95 gate). The synthetic-noise test fixture in
  `tests/test_optix_denoise_reduces_noise_on_synthetic_input` was
  bumped 64×64 → 256×256 to separate the gate from sliding-window
  variance-estimator boundary artifacts and from the empty-normal-buffer
  defect (next bullet). Two unrelated build-hygiene issues caught
  during the round and fixed by Codex pkg71-baseline session PR #215
  (NOMINMAX guard for Windows max macro + FindOptiX glob for OptiX 9.x;
  already merged to main).
- **2026-05-10** — pkg75 **opened** (Track A, status open). First-hit
  normal buffer population for denoiser AOV guides. `Camera::normalBuffer`
  is sized unconditionally but the integrator path the default `Renderer`
  walks leaves it filled with `Vec3(0)`; `fb.hasBuffer("normal")` returns
  true so OIDN's AOV mode and OptiX's AOV mode both bind a degenerate
  guide image and silently behave as HDR + albedo only. Surfaced during
  pkg70 verification 2026-05-10. Acceptance criteria include re-running
  the pkg70 5.31× / pkg68 2.57× baselines after the fix to capture the
  full denoiser win once normals are populated. Spec at
  `.astroray_plan/packages/pkg75-integrator-normal-guide-aov.md`.
- **2026-05-10** — pkg70 implemented (pending OptiX SDK + CUDA hardware
  verification). New `optix_denoiser` pass plugin co-equal with
  `oidn_denoiser`: persistent `OptixDeviceContext` + `OptixDenoiser`
  handle as class members, lazy init on first `execute()`, HDR model
  when no guides / AOV model when albedo+normal present (Cycles
  `OptiXDevice::denoise_buffer` shape, Apache-2.0). State + scratch
  device buffers cached per-dimension. `cmake/FindOptiX.cmake` locates
  the SDK via `OPTIX_INSTALL_DIR` or default Windows path; SDK headers
  are NOT bundled (NVIDIA license forbids redistribution). New
  `astroray.gpu_optix_available()` Python probe. Blender addon gains
  `denoiser_backend` Auto/OptiX/OIDN dropdown — Auto prefers OptiX when
  both backends are compiled in and a CUDA device is visible at
  runtime. New `tests/test_optix_denoiser.py` mirrors
  `test_oidn_denoiser_persistence.py` shape; skips cleanly when SDK or
  CUDA absent. CPU pytest unaffected; OptiX timing vs OIDN-CUDA gate
  pending verifier session with the SDK installed.
- **2026-05-10** — pkg68 implemented (pending CUDA verification). OIDN
  device + filter hoisted to `OIDNDenoiser` class members and lazy-initialised
  on first `execute()`; init tries `oidn::DeviceType::CUDA` first and falls
  back to `oidn::DeviceType::CPU` (Cycles `denoiser_oidn_gpu.cpp::create_device`
  shape, Apache-2.0). Filter is rebound only when the framebuffer geometry
  or source pointers change. CMakeLists FetchContent fallback bumped from
  oidn-2.3.3 to oidn-2.4.1 (latest with CUDA backend). New
  `tests/test_oidn_denoiser_persistence.py` pins: device init runs once
  across N renders, CUDA selected on CUDA-capable builds, albedo/normal
  guides present without explicit AOV pass. CPU pytest run: 12 passed,
  1 CUDA-only test skipped. CUDA SSIM/timing verification pending.
- **2026-05-10** — pkg68 verified on RTX 5070 Ti (Windows MSVC `build_cuda`).
  All 13 tests in `test_oidn_denoiser_persistence.py + test_oidn_denoiser.py
  + test_aov_passes.py` pass, including the previously-skipped
  `test_cuda_capable_build_reports_cuda_device` (`[OIDN] Using CUDA device`
  observed) and `test_device_initialised_once_across_n_frames` (single
  init across N=4 renders). Viewport timing at 256×256, spp=2, max_depth=3,
  N=100 frames after 3-frame warmup: OIDN-on mean 50.67 ms/frame
  vs OIDN-off baseline 23.81 ms/frame, Δ=26.86 ms/frame for the persistent
  CUDA OIDN pass. (No A/B against pre-pkg68 was run — would require a
  second build at `1253894^`; persistent-device path is now the steady
  state.) Promoted to **done**.

- **2026-05-09** — pkg59 done. Named UV layers now upload through
  `add_triangle_layers`, textures can select a layer via Texture
  Coordinate/UV Map node names, and the same image used with different UV
  layers gets distinct texture cache entries.

- **2026-05-09** — pkg60 complete (PR #178, Codex). Disney v2 energy
  compensation: ported Cycles-derived GGX + sheen LUTs, replaced Disney's
  additive roughness boost with Kulla-Conty/Cycles compensation, top-layer
  attenuation, and a local diffuse furnace normalization. Worst-case
  directional-hemispherical reflectance 1.0159 across the 90-point
  parameter grid × 3 outgoing cosines × 4096 Halton samples — under the
  1.02 acceptance gate. Bonus: Codex caught and fixed a pre-existing
  Disney specular/clearcoat Smith-G denominator bug while doing the
  furnace test, plus a combined-sampler PDF regression during owner
  review. Closes the project-owner-reported "materials seem to glow" bug.

- **2026-05-09** — pkg59 mostly done (PR #173 + PR #176). Vector input
  walking honors Mapping(Location, Rotation.z, Scale) and Texture
  Coordinate.UV/Generated/Object. New `uv_debug_aov` pass plugin renders
  first-hit UVs as RG colors. Named UV layers (multiple per-mesh UV sets)
  remain a separate package — needs structural per-triangle upload change.

- **2026-05-09** — pkg64 caustics research signed off (PR #177 + PR #179).
  Recommendation: vendor SMS reference code (BSD-3, MIT-compatible) +
  per-wavelength Newton residual derived from Hanika et al. 2015. Cycles
  MNEE source NOT used — GPL-2.0+ incompatible with Astroray's MIT.
  Reflective caustics in scope; opt-in caster UX; both numerical + visual
  acceptance gates.

- **2026-05-09** — pkg52 complete. The Blender viewport session now keeps a
  persistent renderer, re-renders on view/camera/region/zoom/pan changes,
  progressively accumulates chunked preview samples to `preview_samples`, and
  applies CAMERA-view pan through image-plane camera shift. Focused Blender
  viewport tests and `test_camera_setup` pass on the local MSVC build.
- **2026-05-09** — Documentation reconciliation. `STATUS.md` now reflects
  pkg59 as partial, pkg52/pkg53/pkg58/pkg61/pkg62 as done, the live
  Cycles-parity queue as the active Pillar 5 focus, and the current 435-test
  collection count. Package headers for pkg12-pkg14 and pkg36 were aligned
  with their completed state. `production.md` now flags obsolete pkg50+
  placeholder names that collided with the live package sequence, and
  `NEXT_STAGE_REPORT.md` is explicitly marked historical.
- **2026-05-09** — pkg62 complete on `origin/main` via PR #165. Viewport
  preview now has a pass selector and optional viewport OIDN toggle. Package
  docs were still open in the merged branch and were reconciled here.
- **2026-05-09** — pkg59 partial via PR #164. Principled BSDF image-texture
  routing is fixed, but the broader vector input / named UV / Mapping node /
  UV debug AOV package remains open.
- **2026-05-09** — pkg53 complete. Integrators now expose
  `IntegratorCapabilities` with GPU support metadata; Python binding
  `astroray.integrator_capabilities(name)` returns the same source-of-truth
  data; Blender `device_mode='gpu'` now errors instead of silently falling
  back for unsupported integrators or CUDA init failures; Auto falls back to
  CPU with an INFO report; Diagnostics panel lists per-integrator GPU/CPU
  support. New `tests/test_integrator_capabilities.py` plus backend-policy
  coverage.
- **2026-05-09** — pkg61 complete. CUDA scene upload now preserves per-vertex
  triangle normals (`n0/n1/n2`) and falls back to face normals when absent.
  The GPU hit path already interpolated those fields. Added deterministic GPU
  seed plumbing and `tests/test_gpu_shade_smooth.py`; full-image SSIM remains
  a strict xfail diagnostic due to broader CPU/GPU spectral parity divergence.

- **2026-05-08** — Cycles parity / Blender integration roadmap added in
  response to project-owner triage. 9 new packages drafted: pkg52
  (persistent viewport session), pkg53 (GPU integrator capability
  diagnostics), pkg54 (GPU multi-wavelength path tracer), pkg57 (native
  Astroray shader nodes with Cycles compat), pkg58 (spectral profile
  dropdown + IR/UV reference scenes), pkg59 (shader-graph vector / UV
  plumbing), pkg61 (GPU per-vertex normals), pkg62 (viewport pass
  selector), pkg64 (spectral caustics, research-blocked), pkg67
  (metric-aware path tracer, research-blocked). CLAUDE.md §6 added: no
  invented algorithms, cite-and-borrow policy. Main repo git cleanup:
  aborted-rebase markers cleared, `dist/` gitignored and untracked
  (914 MB tcnn build was about to land in git).

- **2026-05-03** — pkg37 complete. Blender addon backend refresh: `device_mode` EnumProperty (Auto/GPU/CPU) replaces old `use_gpu` BoolProperty; shared `configure_backend()` helper called from both final render and viewport; viewport now applies wavelength range/output mode (Near IR/UV/Custom) matching final render; Diagnostics panel shows module path, version, `__features__`, GPU availability, integrator list, and post-render stats; `build_blender_addon.py` gains `--backend cpu/cuda/tcnn/auto` flag, per-backend build dirs (`build_blender_addon`, `build_blender_addon_cuda`, `build_blender_addon_tcnn`), and a `build_report.json` in the packaged zip. 11 new tests in `test_blender_backend_policy.py`.
- **2026-05-03** — pkg39 complete. Multi-wavelength rendering: configurable wavelength band (380-780 nm visible unchanged; IR/UV via `multiwavelength_path_tracer`), `SpectralProfile`/`SpectralProfileDatabase` C++ API loading profiles.bin, `evalSpectralExt`/`sampleSpectralExt` profile dispatch on Material base class, `ColourmapOutput` post-process pass (grayscale/hot/inferno/viridis/ir_false_colour), Python API (`set_wavelength_range`, `set_material_spectral_profile`, `spectral_profile_names`), Blender UI (Wavelength panel with presets, colourmap selector). 15 tests; all pass.
- **2026-05-03** — pkg38 complete. Spectral material profile database built from USGS Spectral Library v7, ECOSTRESS/JHU spectra, Rakic 1998 Lorentz-Drude model for polished metals (Al, Au), and Bashkatov 2005 digitised skin measurements. 40 materials across 7 categories (vegetation, earth, building, metal, fabric, paint, human), 441 wavelengths at 5nm from 300-2500nm. ASPR binary format (72 KB), profiles_metadata.json, sources.md provenance. 18 tests all pass; Wood effect 3.8x/5.9x, water R(1000nm)=0.008, Al/Au mean R>0.90.
- **2026-05-03** — pkg36 complete. Added shared material closure graphs,
  Python graph inspection, and CUDA closure-graph lowering. Lambertian,
  metal, flat dielectric, Disney plastic/glass, and a new `closure_matte`
  plugin now exercise the same graph path for backend metadata and GPU upload;
  graphless materials remain explicit CPU-only escape hatches. Focused
  validation: CUDA build passed; closure/backend/GPU material tests passed.
- **2026-05-03** — pkg35 complete. Added compact CUDA sampled-wavelength and
  sampled-spectrum payloads, spectral BSDF/emitter dispatch helpers for core
  RGB-derived GPU materials, Python `gpu_spectral` capability metadata, and
  contact-sheet CSV reporting. Flat-IOR dielectric/glass is spectral-GPU
  capable; Sellmeier dispersion plus line/blackbody emitters remain explicit
  CPU-only until dedicated GPU parameter lowering exists. Focused validation:
  CUDA build passed; pkg35/backend/GPU parity tests passed.
- **2026-05-03** — pkg33 complete. OIDN auto-detection (env var, common Windows paths, FetchContent 2.3.3 fallback) added to CMakeLists.txt. OIDN 2.4.1 found at C:/oidn; `ASTRORAY_OIDN_ENABLED` now active. Duplicate function definitions from the rough-Disney-glass merge fixed in `disney.cpp`. Blender addon `__init__.py` probes `addon_dir/oidn/` and `C:/oidn/bin` for DLLs; `build_blender_addon.py` copies them into the zip. New `tests/test_oidn_denoiser.py` verifies: registry presence, variance reduction (30× at 4 spp), and side-by-side PNG in `test_results/oidn_before_after.png`. 3 new tests; all pass.
- **2026-05-03** — pkg32 complete. Visual AOVs now have non-trivial output
  coverage, convergence/showcase scripts are verified, and
  `scripts/diagnostics/oidn_comparison.py` writes noisy/denoised/side-by-side OIDN PNGs
  when OIDN is compiled in.
- **2026-05-03** — pkg34 complete. Materials now expose backend capability
  metadata, CUDA upload rejects unsupported materials instead of silently
  lowering them to grey Lambertian/generic metal/generic glass, Python exposes
  `get_material_backend_capabilities()`, and the material contact sheet records
  backend choice and fallback reasons from C++ metadata.
- **2026-05-03** — Pillar 4 prep cleanup. Added `MetricRegistry`,
  `EmissionRegistry`, `ASTRORAY_REGISTER_METRIC`, and
  `ASTRORAY_REGISTER_EMISSION` scaffolding to `register.h`; captured the
  pre-refactor Schwarzschild reference render at
  `tests/reference/schwarzschild_baseline_256.png`; updated Pillar 4 package
  numbering to pkg40-pkg51; added pkg34-pkg36 specs for material CPU/GPU
  backend parity.
- **2026-05-03** — Optical material cleanup started for pkg29 follow-up. Added
  a scoped pkg29a caustic-validation design for issue #145, plus issue #142/#146
  work on optical-glass presets and thin architectural glass.
- **2026-05-03** — pkg29a complete. Added `caustic_path_tracer`, three caustic
  validation scenes, saved PNG diagnostics, JSON/CSV stats, and
  `scripts/benchmarks/benchmark_caustic_transport.py`. The opt-in integrator records
  `caustic_connections` and `caustic_energy` while leaving `path_tracer` as
  the default/reference.
- **2026-05-03** — Codex material triage recorded: convergence tracker repair,
  GGX/rough-metal sampling cleanup, and Disney rough-glass transmission with
  CPU/CUDA material support and high-sample GPU contact-sheet diagnostics.
- **2026-05-02** — pkg29 complete. Added
  `tests/scenes/prism_reference.py` and `tests/test_spectral_prism.py`.
  The test renders flat-IOR and BK7 triangular prisms, saves visual artifacts,
  and verifies measurable red/blue centroid spread in the dispersive render.
  Focused validation: `tests/test_spectral_prism.py` passed.
- **2026-05-01** — Created pkg30–pkg33 specs. pkg30: `sampleSpectral()` virtual
  on Material (interface-only, no material changes). pkg31: Sellmeier dispersion
  in DielectricPlugin with `terminateSecondary()`. pkg32: visual diagnostics
  suite (AOV passes, convergence tracker, showcase renders). pkg33: OIDN
  FetchContent fallback so the denoiser actually builds. Opened GitHub issues
  #121–#127 for Copilot-scoped Track B work (3 AOV stub implementations,
  2 heatmap passes, convergence tracker, showcase script). pkg29 (prism
  validation) unblocked once pkg30+pkg31 land.
- **2026-05-01** — pkg28 complete. `neural-cache` now performs backend
  readiness once per frame, buffers warmup samples, pads and trains from
  `endFrame()`, exposes `backend_ready`/`enable_inference` stats, and keeps
  cache inference behind an explicit parameter because current per-sample
  inference is slower than the spectral path tracer. Auto/default therefore
  stays on the fastest validated path-tracer fallback until batched inference
  is performance-positive. Latest 64x64 opt-in benchmark with one untimed
  warmup render: path tracer 0.0391s/frame, auto default 0.0499s/frame, NRC
  fallback 0.0420s/frame, NRC training backend 0.0318s/frame (1.23x, but not
  yet the original 30% speedup/quality target).
- **2026-05-01** — pkg27b complete. Added
  `scripts/benchmarks/benchmark_light_transport.py`,
  `tests/scenes/neural_cache_indirect.py`, and
  `tests/test_neural_cache_validation.py`. The benchmark writes JSON/CSV stats
  and PNG charts comparing path tracer, auto default, NRC fallback, and NRC
  backend. `Renderer::render()` now auto-selects the fastest validated default;
  Blender exposes `Auto (Best Available)` first. The first
  32x32 opt-in benchmark proves training/finiteness but not speedup:
  `neural_cache_backend` was 0.86x path-tracer speed and `auto_default` was
  dominated by first-use training/init overhead on the tiny scene, so pkg28
  remains in validation for performance tuning.
- **2026-05-01** — pkg28 split into explicit completion gates. Added
  `pkg27a-nrc-training-observability.md` and
  `pkg27b-nrc-indirect-validation.md`; pkg27a is complete with
  `get_integrator_stats()` and NRC queue/train/fallback counters. The existing
  pkg28 implementation still buffers warmup training samples during
  `sampleFull()` and performs one padded tiny-cuda-nn training step in
  `Integrator::endFrame()`; pkg27b now owns the indirect-scene validation data.
- **2026-05-01** — pkg27 complete. Added `plugins/integrators/neural_cache.cpp`
  and registered `neural-cache`. Default builds keep the plugin selectable via
  a spectral path-tracer fallback; `ASTRORAY_TINY_CUDA_NN=ON` now builds a
  reusable `astroray_neural_cache` backend from `src/neural_cache.cu` and links
  it into production targets. Focused tests cover registry exposure and Python
  selection.
- **2026-05-01** — pkg26 complete. `NeuralCache` (16-in/16-out FullyFusedMLP, Adam, RelativeL2) + `nrc_smoke_render` Cornell box harness both working on RTX 5070 Ti (sm_120). Two tcnn master gotchas resolved: (1) `TCNN_MIN_GPU_ARCH=120` static_assert override for sm_89 build; (2) `BATCH_SIZE_GRANULARITY=256` in master (was 128 in v1.x) — `BATCH_ALIGN` updated to 256. Luminance: 0.2841 (frame 1) → 0.4317 (frame 50), Δ+52%. See `.astroray_plan/docs/nrc-prototype-notes.md`.
- **2026-05-01** — pkg25 fully complete. Driver updated from 576.57 to 596.36; CUDA 13.2 runtime now supported. Switched `GIT_TAG` to master (fixes sm_89 FullyFusedMLP crash); added `set_params()` call before `forward()` (required in tcnn master). `tcnn_smoke.exe` reports `OK (non-finite: 0 / 4096 outputs)`. VS Code cmake settings updated to use VS 2022 generator with `BUILD_PYTHON_MODULE=ON`; conftest extended to check `build_tcnn/Release`. pkg26 spec drafted. See `.astroray_plan/docs/tiny-cuda-nn-prototype-notes.md` for full resolution log.
- **2026-04-30** — pkg25 build complete; runtime initially blocked by driver version. tiny-cuda-nn master FetchContent integration works; `tiny-cuda-nn.lib` and `tcnn_smoke.exe` build cleanly via MSVC+CUDA 13.2.
- **2026-04-30** — pkg24 complete. Temporal and spatial reservoir reuse implemented in `restir_di.cpp` (Bitterli et al. 2020, Algorithms 1–3). `targetLuminanceRGB()` added to `ReSTIRCandidate` for wavelength-independent cross-frame W values. `set_integrator_param` Python binding added. 13-test validation suite covers all 6 design-note criteria (finitude, determinism, temporal variance, spatial MSE, bias magnitude for both passes, default-mode regression). 287 passed, 1 skipped, 16 xfailed.
- **2026-04-29** — Verification/docs pass: pytest collection restored to 229 tests when pointed at a valid Windows build via `ASTRORAY_BUILD_DIR`; full suite baseline on the fresh MSVC build is `211 passed, 1 skipped, 16 xfailed, 1 xpassed`. Test bootstrap now understands standard `build/Release` layouts and custom build dirs. Drafted `pkg25` and aligned status docs with the already-landed Pillar 2 stabilization work and ReSTIR package sequence.
- **2026-04-28** — PR #116 and PR #117 merged. Codex docs/local-agent scaffolding, render-output triage, refreshed deterministic spectral tests, and restored spectral black-hole GR dispatch are now on `main`. PR #119 is in review for native spectral GR disk emission; issue #114 is active for Pillar 3 ReSTIR package specs.
- **2026-04-26** — pkg14 complete. Spectral HDRI atlas built at load time; env-miss path wired to `evalSpectral`; legacy RGB `PathTracer` plugin and `pathTrace()` kernel deleted; registry entry renamed `"path_tracer"`; `Material::evalSpectral` is now pure virtual; `Material::eval` virtual removed. **Pillar 2 is 100% complete (pkg10–pkg14).**
- **2026-04-26** — pkg13 fully complete. All four threads merged: (1) physics/infra PR #103 — Texture::sampleSpectral, ImageTexture cache, Metal/Dielectric/Mirror/Subsurface evalSpectral; (2) Copilot PR #104 — Phong/Disney/NormalMapped/DiffuseLight evalSpectral/emittedSpectral; (3) Copilot PR #106 — 8 procedural texture sampleSpectral overrides; (4) pkg13c PR — 4 new plugins: oren_nayar, isotropic, two_sided, emissive. Every shading event in the spectral pipeline now has a concrete override. Test suite: 223 passed, 1 skipped. Pillar 2 ~90%.
- **2026-04-24** — pkg10 merged: Pillar 2 scaffolding. New `include/astroray/spectrum.h` defines `SampledWavelengths`, `SampledSpectrum`, `RGBAlbedoSpectrum`, `RGBUnboundedSpectrum`, `RGBIlluminantSpectrum` (float, 4 samples, 360-830 nm). `src/spectrum.cpp` loads the shipped Jakob-Hanika sRGB LUT lazily from `data/spectra/rgb_to_spectrum_srgb.coeff` and embeds the CIE 1964 10° CMF and D65 SPD as `constexpr` tables. New `astroray_core_impl` CMake target; `ASTRORAY_DATA_DIR` compile definition + env-var override for runtime data discovery. Python bindings expose every type plus a top-level `rgb_to_spectrum()` helper. No integration into any material, integrator, pass, or env map — that is pkg11+. Test suite: 189 passed, 1 skipped (20 new spectrum tests).
- **2026-04-22** — pkg06 merged: Pass registry closes Pillar 1. `Pass` abstract base + `Framebuffer` named-buffer API in `include/astroray/pass.h` / `raytracer.h`. Five plugins in `plugins/passes/` (OIDN denoiser, depth/normal/albedo AOV). `add_pass`/`clear_passes` Python bindings. `pass_registry_names()` module function. Blender `use_denoising` property wired to `add_pass("oidn_denoiser")`. Inline OIDN code removed from `blender_module.cpp`. Test suite: 169 passed, 1 skipped.
- **2026-04-22** — pkg05 merged: `Integrator` abstract base class in `include/astroray/integrator.h`; PathTracer and AmbientOcclusion plugins in `plugins/integrators/`; `SampleResult` + `Renderer::traceFull()` for AOV preservation; `set_integrator` Python binding + `integrator_registry_names()`; Blender `integrator_type` EnumProperty wired into render. Test suite: 165 passed, 1 skipped.
- **2026-04-21** — pkg04 merged: 9 texture plugin files + 5 shape plugin files. `Sphere`/`Triangle` bodies moved to `include/astroray/shapes.h`. Python bindings `sample_texture()`, `texture_registry_names()`, `shape_registry_names()` added. Test suite: 161 passed, 1 skipped.
- **2026-04-21** — pkg03 merged: all remaining material types (Metal, Dielectric, Phong, Disney, DiffuseLight, NormalMapped, Emissive, Isotropic, OrenNayar, TwoSided) migrated to plugin files.
- **Earlier** — pkg01/02 merged: registry skeleton and Lambertian plugin established the pattern.
