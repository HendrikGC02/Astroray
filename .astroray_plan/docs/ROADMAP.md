# Astroray Master Roadmap

**One document to navigate the whole plan.** Every other document exists
because this roadmap points at it. New to the project? Read this first.

---

## Vision in one paragraph

Astroray is a C++/CUDA path tracer with a Blender 5.1 addon, aiming to be
the best open-source engine for physically-accurate astrophysical
visualization while remaining competitive as a general-purpose PBR
renderer. The design goal is **pluggability** — new materials, shapes,
light transport techniques, and astrophysical phenomena should be
drop-in plugins that register into a small set of factory registries,
not patches to core files. A veteran engineer looking at the codebase
should think "this is the obvious way to do it," not "this is clever."

**Performance goal:** rival Cycles in simple enough cases on a single
RTX 5070 Ti (CUDA). **Fidelity goal:** surpass Cycles on spectral and
astrophysical scenes. **Simplicity tax:** every abstraction pays for
itself with a concrete caller today.

---

## The agent tracks

Work happens on independent tracks. Each has its own agent and acceptance
criteria. Progress on one track rarely blocks another — that is by design, so
your single-developer throughput multiplies without coordination overhead.

| Track | Owner agent | Runs on | Purpose |
|---|---|---|---|
| **A. Core quality** | Claude Code (local) | Your RTX 5070 Ti | Correctness, foundational refactors |
| **B. Feature breadth** | GitHub Copilot cloud | GitHub Actions | Self-contained features shipped as plugins |
| **C. Experiments** | Cline + local model | Your machine, VS Code | Exploratory changes, prototypes |
| **D. Grind work** | Ralph loop + local model | Background on your machine | Test coverage, docs, lint fixes |
| **E. Coordination/review** | Codex | Codex app/CLI + GitHub connector | Repo setup, PR/issue triage, CI/debug, targeted fixes, handoff specs |

The overseer (see `agents/overseer.md`) coordinates by deciding what
goes on which track, not by touching code.

**Simplicity principle per track:**
- Track A handles anything that *has* to be right.
- Track B handles anything that *matches a pattern* that is already right.
- Track C explores things that *might* be right.
- Track D mechanically converts known-right work into more of it.
- Track E keeps the other tracks aligned and turns context into actionable
  issues, reports, and PRs.

---

## Five pillars, in priority order

### Pillar 1 — Plugin architecture [FOUNDATIONAL, DO FIRST]

Convert materials, shapes, lights, textures, integrators, and passes into
plugins registered via `Registry<T>` templates. Everything below assumes
this is in place.

- Design: [`plugin-architecture.md`](plugin-architecture.md)
- Duration: 2–3 weeks of track A sessions
- **Blocks everything else.**

### Pillar 2 — Spectral core

Upgrade from hero-wavelength-at-GR-only to a fully spectral pipeline:
`SampledSpectrum`/`SampledWavelengths`, Jakob-Hanika RGB→spectrum
upsampling, spectral BSDFs and env maps. RGB backward-compat via
upsampling.

- Design: [`spectral-core.md`](spectral-core.md)
- Duration: 3–4 weeks
- Depends on Pillar 1.

### Pillar 3 — Light transport upgrades

ReSTIR DI as drop-in for NEE+MIS direct lighting; Neural Radiance Caching
via tiny-cuda-nn for indirect. Both as plugin integrators; classic path
tracer remains the fallback. When accelerated transport is available and
performance-positive, renderer defaults should pick it automatically and fall
back without user intervention.

- Design: [`light-transport.md`](light-transport.md)
- Duration: 4–6 weeks
- Depends on Pillars 1, 2.

### Pillar 4 — Astrophysics platform

> **Thaw notice (2026-05-10) + shipping (2026-05-11+):** the strategic
> gate released, and Pillar 4 is actively shipping. pkg40 (Kerr
> metric) + **pkg41 (Kerr validation, PR #236)** + **pkg42 (synchrotron
> emission, PR #245 — VolumetricEmission interface, Pandya 2016 fits,
> bipolar jet plugin, 9 tests)** + **pkg43 (slim disk accretion model,
> PR #271 — Abramowicz 1988 / Sadowski 2009, 14/14 tests, T(9M,mdot=1) =
> 7.45e6 K)** + **pkg44 (ADAF accretion model, PR #310 — Narayan & Yi
> 1995 self-similar solution, 19 tests, Sgr A* profiles within tolerance)**
> + **pkg47 (FITS data loader, PR #292 — FITS I/O wrapper + FITSTexture
> plugin, gated `ASTRORAY_ENABLE_FITS` default OFF; FITSVolume deferred to
> pkg48)** all done. **Pillar 4 now ~50% complete.** pkg45–pkg51 specs
> queued.

Kerr metric, synchrotron emission, HII recombination lines, simulation
data import (FITS, HDF5, yt), telescope PSF. Each phenomenon is a
plugin. This is Astroray's unique niche.

- Design: [`astrophysics.md`](astrophysics.md)
- Duration: 6–10 weeks, parallel with other pillars
- Depends on Pillars 1, 2.

### Backend parity bridge — before Pillar 4 acceleration

The plugin and spectral systems are in place, but the CPU/GPU material
boundary still needs an explicit contract. Before leaning harder on
GPU-default rendering and before Pillar 4 adds more spectral phenomena,
material plugins should declare backend capabilities and either lower
to a shared CPU/GPU closure representation or clearly fall back to CPU.

**Status as of 2026-05-11 (Round 6 close, planned scope):** the
pkg34–pkg37 backend bridge is complete. The Cycles-parity / Blender
integration / denoiser push is **feature-complete on planned scope**
for Pillar 5; the user-facing competitive-parity claim (viewport
pan/zoom rivalling Cycles) is **not yet met** — pkg81's measurement
showed CUDA running *slower* than CPU on a 100k-tri viewport scene
(104 ms vs 58 ms), routed to **pkg55 Phase B** as the long-tail
fix:

- **Cycles parity wave done:** pkg52/53/57/58/59/60/61/62/63/65/66.
- **GPU multi-wavelength parity done end-to-end:** pkg54/54a/54b/54c/54d
  (all hardware-verified on RTX 5070 Ti; visible-band SSIM 0.999263 at
  spp=8192).
- **Denoiser story closed end-to-end:** pkg33 (OIDN integration), pkg68
  (OIDN persistent device + CUDA backend, **2.77× viewport speedup**
  post-pkg75), pkg69 (compositor Albedo pass), pkg70 (OptiX,
  **1.86× faster than OIDN-CUDA, SSIM 0.9987 vs OIDN**), pkg72
  (motion vector AOV), pkg75 (AOV normal-guide defect fixed), and
  **pkg73 OptiX TEMPORAL_AOV** (PR #249, 2026-05-11 — **53.1%
  inter-frame variance reduction vs ≥30% gate** on RTX 5070 Ti / OptiX
  9.1 / CUDA 12.8). Two compounding root causes for pkg73:
  `OptixDenoiserParams::temporalModeUsePreviousLayers` was zero-init
  in the plugin, AND the test's AOV reference was silently upgraded
  to TEMPORAL_AOV by sub-pixel float dust in `projectToPrevPixel`.
  Both fixed.
- **Caustics flagship done:** pkg64 Phases 1+2+3 — SMS now folded
  into the default `path_tracer` via per-bounce hook gated by
  `use_refractive_caustics` AND per-object `is_caustic_caster`.
  RTX-verified: **+8.83 dB PSNR delta, 1.18× receiver-energy ratio,
  +0.26 dB PSNR floor, 2.0% empty-hook overhead** — all gates met.
- **Cycles parity benchmark:** pkg71 framework + first canonical
  Cornell baseline shipped — **Astroray-CPU SSIM 0.9536 vs
  Cycles-CPU EXR; Astroray-GPU SSIM 0.9548 and 5.2× faster than
  Cycles-CUDA on Cornell**. **pkg76 .blend importer done** (PR #240,
  SDNA-walking Python reader, no `bpy` runtime); CSV row population
  on Classroom/Junkshop/BMW27 is a Round 6 RTX session.
- **Showcase framework done:** pkg74 Phases 1+2+3 (material zoo +
  full stat coverage + interactive PBRT-style HTML + weekly self-
  hosted CI).
- **Viewport sync done:** pkg52 + pkg56 Phases A+B+C — depsgraph-
  driven dispatch with idle frame ≤5 ms p99 on a 99k-tri scene.
  This was the **gate-releasing package**.
- **Wavefront SoA scaffold:** **pkg55 Phase A.0** (PR #238) —
  `ASTRORAY_PROFILE=1`-gated CUDA events + NVTX, baseline.json with
  **158 regs/thread + 1 active block/SM** measured as the Laine 2013
  occupancy cliff. **pkg55 Phase A.1** (PR #250, 2026-05-11) — SoA
  path-state struct + intersect queue gated behind
  `-DASTRORAY_WAVEFRONT_INTERSECT=ON` (default OFF), bit-identical
  AoS megakernel output verified. **pkg55 Phase B** (per-material
  shade kernels, ~4–6 weeks) is the next major delivery; it formally
  owns the viewport-parity acceptance gate documented by pkg81.
- **Blender daily workflow unblocked:** **pkg80** (PR #246) resolves
  `'auto'` integrator dropdown to a registered plugin before C++
  calls; the GPU-mode crash is gone.
- **Viewport-parity measurement complete:** **pkg81 Phase 1+2** (PR
  #248, 2026-05-11) — harness + 16-config Cycles A/B sweep + pkg81-
  diagnosis.md committed. Headline: **CUDA 104 ms vs CPU 58 ms** on
  identical 100k-tri load on RTX 5070 Ti. H4 (megakernel register
  pressure — pkg55-A.0's documented cliff) dominates. Phase 3 routes
  to pkg55 Phase B per the spec's escape clause; smaller H2/H5
  follow-ups split out as **pkg83** + **pkg84**.

**Round closeout (2026-06-11 afternoon): 8 PRs — pkg115 chunks 2-5 COMPLETE + pkg55-B' Sessions N+6/N+7 COMPLETE.**
**Two packages advanced major steps this round.** All RTX-verified. Final sweep on merged main 5e21bd5: **1271 passed / 0 failed / 23 skipped / 20 xfailed / 3 xpassed**. **pkg115 chunks 2-5 DONE** (PRs #441/#442/#445/#446, 2026-06-11) — Noise/Wave/Brick/Voronoi Cycles parity: Chunk 2 (#441) = Jenkins lookup3 hash (bit-exact) + Perlin core (BSD-3-Clause) + fractal stack + WhiteNoiseTexture + NoiseTextureCycles (Blender "Noise Texture" node); Chunk 3 (#442) = Wave (fixes ~6.4× density bug, signed-fBM detail distortion, band/ring direction enums) + Brick (3D input, `brick_noise` hash bit-identical, per-brick color variation, mortar_smooth smoothstep); Chunk 4 (#445) = full Cycles-parity Voronoi (distance metrics, Features F1/Smooth F1/F2/Distance to Edge/N-Sphere Radius, cell jitter, fractal layering, node conditioning), lead-review fixes (normalize at detail=0, Distance-to-edge midpoint term, fractal position accumulator shadowing); Chunk 5 (#446) = addon `ShaderNodeTexVoronoi` translation + factory full-param wiring (fixes latent regression where addon feature map was stale after #445 enum change — F2 would have rendered Smooth F1), backward-compatible. 1271 passed, 0 failed. pkg98 SIGN-OFF (chunks 2-3, line-by-line vs canonical Cycles `svm/*.h` sources). REMAINING: addon-side private texture-definition duplication removal + Blender-vs-Cycles RTX visual verify. **pkg55-B' Sessions N+6/N+7 DONE** (PRs #443/#444/#447/#448, 2026-06-11) — **GPU wavefront now produces IMAGES at megakernel parity.** N+6 (#443) = end-to-end pipeline with `stage_advance.cu` (one-bounce device twin of CPU `advance_one_bounce`, calls UNMODIFIED megakernel device functions — design decision #9: one generator of sampling math), `gpu_env_spectral.cuh` (env-miss eval factored VERBATIM out of MW kernel), `cuda_wavefront_render` host driver + binding; measured (RTX 5070 Ti, session_n1_envmap_cornell 64²×64spp): GPU-WF/CPU-WF per-channel mean ratio [1.089, 0.991, 1.045] (systematic, inherited from documented megakernel-BSDF↔CPU-plugin divergences); gate ≤0.12. PR #444 root-caused the ~1.85× "MAJOR FINDING" as a measurement artifact (applyGamma=True vs linear oracle) AND fixed a real latent bug (megakernel ignored `worldMaxBounces`); linear-vs-linear [1.091, 0.993, 1.050]. N+7 part 1 (#447) = host-overhead elimination, measured-first: device-side per-sample XYZ accumulation kernel, `launchStageAdvance` sync=false → ONE sync + ONE download per render; wavefront 0.300 s → 0.108 s (2.8× faster), gap to megakernel 1.55× (was 4.0×); WF/MK image ratio unchanged [0.997, 0.999, 0.997]. pkg98 SIGN-OFF (Opus): accumulation-kernel equivalence verified, sync=false safety traced, accumulator race-freedom confirmed. N+7 part 2 (#448) = alive-queue compaction — **MEGAKERNEL PARITY**: shared `advancePathSlot` device function (one generator, decision #9), ping-pong slot queues with device-side counters; measured: wavefront 0.074 s vs megakernel 0.070 s — **1.05×** (from 1.55× part 1, 4.0× N+6); WF/MK image ratio unchanged to 7 decimals [0.997, 0.999, 0.997]; full suite 1271 passed / 0 failed. pkg98 SIGN-OFF (Opus): refactor purity proven byte-identical, ping-pong race-freedom traced, alloc/free leak-safe. REMAINING for B' close: N+7 part 3 (sort-by-material + intersect/shade split — the 254-reg cliff; ≥1.5×-FASTER gate needs warp-coherent shading), wavefront_path_tracer plugin registration, 7-material contact-sheet perf gate, pkg81 viewport-parity gate; deferred from N+6: non-visible-band profile override, TLAS/motion in wavefront, light-tree NEE branch. **Next pickup:** pkg55 Phase B completion (N+7 part 3 + plugin registration + perf gates), pkg115 dedup + RTX visual verify, pkg88 C.1 + Phase B (after pkg114 inc3), pkg64 spectral caustics. **Hardware state:** all verified on RTX 5070 Ti; full suite at #448 merge: 1271 passed / 0 failed / 23 skipped / 20 xfailed / 3 xpassed; the 3 xpassed gates (total_max_depth caps, filter_glossy, reflective-caustics flags) STILL pass, promote next round; pkg114 inc3 (addon instancing) still pending with dedicated agent.

**Round closeout (2026-06-11 morning): 8 PRs — pkg108/pkg86-B/pkg116/pkg88-C.0/pkg115 chunk 1 COMPLETE + pkg114 inc 1+2.**
**Five packages shipped this round (morning).** All RTX-verified. Final sweep on merged main 75185a6: **1214 passed / 0 failed / 23 skipped / 20 xfailed / 3 xpassed**. **pkg108 DONE** (PR #432, 2026-06-10) — Addon residual bug triage: BUG-14 was REAL on CUDA only (`gpu_dielectric_sample` delta refraction dropped tint, fixed `s.f = baseColor*eta²`); BUG-16 GPU half fixed in BOTH shading paths (GMAT_DISNEY + closure-graph diffuse lowering) with Burley §5.3 HK subsurface mix, gated bit-identical at subsurface=0; BUG-09 verified non-reproducing via live headless Blender 5.1 routing. 6 regression tests. **pkg86-B DONE** (PRs #434/#436/#438, 2026-06-11) — GPU light tree Phases 2+3: device traversal mirrors Cycles `kernel/light/tree.h` (Apache-2.0, e52e5eb0) via `src/gpu/light_tree_device.cuh`; bit-trail pdf walk; both megakernels branch on `GLightTreeView`; Power mode bit-identical. RTX: pick parity ≥99.5%/10k queries (pdf rel-err <1e-4), upload 0.09–0.5ms @10k lights, single-light PSNR 100dB, SAOH two-cluster routing >95% both backends. GPU variance 1.110× — 2.0× gate xfail on BOTH backends (Phase-1 scene-structure limitation; parity gate proves GPU mirrors CPU tree). Deferred: wavefront wiring→pkg55-B; dedicated lights→power-CDF fallback+warning. **pkg116 DONE** (PR #435, 2026-06-11) — Exporter/cache refactor: `exporter.py` owns viewport sync; six per-domain caches with `diff()`; `Change` IntFlag aggregator; `RenderEngine` thin shim. 135 addon tests green, zero existing-test edits. **pkg88 Phase C.0 DONE** (PR #437, 2026-06-11) — Deformation motion blur: `add_triangles_bulk_motion` bulk binding, time-aware `Triangle::hit` + `gpu_triangle_hit_motion` (Cycles `motion_triangle.h`), union-AABB BVH, `GRay.time` end-to-end both megakernels. RTX: no-op bit-identity, CPU+GPU streak, union-AABB extremes, cross-backend motion/static energy-shift parity. REMAINING: C.1 per-primitive split (perf-gated), Phase B addon bake (after pkg114 inc3), Phase D wavefront (after pkg55-B). **pkg115 Stage 2 chunk 1 DONE** (PR #439, 2026-06-11) — Procedural texture parity: Stage-1 research audit committed (`.astroray_plan/docs/blender-procedural-parity-research.md`); chunk-1 = GENERATED coord default, signed Normal coord, (u,v,0) UV 3D point, Checker floor-parity, Gradient 4 formula fixes, Magic verbatim port, `eval_texture_at_3d` debug binding. REMAINING chunks: hash/WhiteNoise, Perlin/Noise, Wave, Brick, Voronoi, addon translator dedup + standalone CI example + RTX visual verify vs Cycles. **pkg114 inc 1+2** (PRs #430/#431 by parallel Opus agent, not this session): GPU core landed (structs + `gpu_tlas_hit` + identity + real multi-instance transforms with non-uniform scale/mirror). **Notable test-suite state change:** 3 xpassed gates (total_max_depth caps, filter_glossy, reflective-caustics flags) now PASS and should be promoted next round. Expected: 0 failures / 20 xfails (legacy pkg64-gpu SMS + pkg86 2× variance + others).

**Round closeout (2026-06-10): pkg118 + pkg113 + pkg112 COMPLETE.**
**pkg118 SOLVED** (PR #423, 2026-06-08) — the rough-glass furnace energy deficit was the **η²
albedo-LUT clamp** (the CPU twin of the #404 GPU glass-dark bug): `Material::sampleSpectral`
upsampled glass throughput through `RGBAlbedoSpectrum`, whose Jakob-Hanika ALBEDO LUT clamps
rgb>1 to 1, clipping the exit refraction's eta²=2.25 radiance recovery. Fix: factor the >1
magnitude out as a flat spectral scalar (mirrors GPU #404), upsample only the normalized tint.
CPU furnace 0.77/0.82/0.92/0.97/0.96 → 0.89/0.94/1.00/1.00/1.00; `test_disney_rough_glass_furnace_energy_cpu`
PASSES [0.92,1.03]; no regressions. The spec's Part B (Kulla-Conty multi-scatter table) was a
dead-end (the deficit was NOT single-scatter masking). Full diagnosis:
`.astroray_plan/docs/pkg118-multiscatter-energy-research.md`. **pkg113 DONE** (all 3 phases merged +
RTX-verified, PR #422 store, #424 emission, #425 gather) — GPU photon-map caustics: uniform hash-grid
store, GPU photon emission + bounce → deposit, adaptive k-NN cone gather wired into both GPU
integrators. Phase-3 follow-up resolved: the "GPU caustic 5.6x more spread" was REAL but the diagnosis
was INVERTED — the GPU was correct; the **CPU reference carried an exit-refraction sign bug** (both CPU
caustic loops keyed enter/exit off the ray-ORIENTED `rec.normal`, always taking the "entering" branch;
fix = recover geometric outward normal `ng = frontFace ? rec.normal : -rec.normal`). RTX-verified:
glass-sphere parity ROI ratio 1.09x, SSIM 0.962, peak 0.409; pkg110 conc 32.4; 26 caustic/GPU tests
pass, 0 regressions. Detail: `pkg113-phase3-gather-wiring-research.md` RESOLUTION section. **pkg112
DONE** (PR #427) — batched geometry upload: one `add_triangles_bulk` pybind call per mesh (looping in
C++), replacing the per-triangle `add_triangle` round-trip. Addon fills arrays with Blender's C-speed
`foreach_get`; **31.7× upload speedup** on 100,352 tris (692.7ms→21.9ms). Verified at four layers:
binding pixel-identity (bit-identical CPU render), extraction-parity unit test (non-uniform-scale +
inverse-transpose normals + multi-UV order), and a **real-Blender end-to-end bit-identical render**
(headless Blender 5.1). **Next pickup:** pkg114 (two-level BVH TLAS/BLAS) → pkg55 (wavefront SoA) →
pkg64 (spectral caustics) — all GPU-gated + RTX-verifiable.

**Round 15 Waves 3–5 (2026-05-29→30): forward-light-tracer prism rainbow → general caustics → GPU glass energy + showcase.**
**pkg106 FINISHED** (PR #393) — a triangulated BK7 prism throws a clean continuous rainbow caustic
(hue_spread 0.754 ≥0.7, bright_coverage 0.88) via a NEW forward light-tracer integrator
`plugins/integrators/light_tracer_caustic.cpp` (Arvo 1986 / Jensen 1996); camera-side MNEE is
ABANDONED for flat prisms (the MNEE math is kept for focusing casters). **General-caustics chain
CPU-complete: pkg109** (world-space photon-map kd-tree, PR #395) → **pkg110** (BSDF-driven photon
bounce — hybrid auto-select by caster geometry, PR #397) → **pkg111** (k-NN gather on any receiver,
into the default `path_tracer`, PR #403). "Drop ANY glass + light → caustics on ANY surface through
the default path" now works on CPU. Also: **pkg76 Classroom Gap 2** (non-Principled shader-graph
walk, PR #394), **integrator float-param** ergonomics (PR #396), mesh-caster caustics + scaled-mesh
visibility fix (PR #401), and the **glass-dark frontFace fix** (PR #402 — key enter/exit off
`rec.frontFace`, CPU+GPU). **Wave 5 quality:** **PR #404** fixes the dominant GPU clear-glass
energy bug (delta refraction eta^2 was albedo-clamped to [0,1] by the JH upsampler; white-furnace
0.705 → 0.991 flat @ ior 1.5) and lands a **Heitz-2018 VNDF microfacet-dielectric rough-transmission
rewrite** (PBRT-v4 `DielectricBxDF`, BSD-3-Clause — GPU rough glass now energy-conserving for R≥0.1);
**PR #405** re-authors 6 reference-bank showcase scenes (≥512², gate-green on RTX). The forward
photon-map caustics were CPU-only by design; **pkg113** (the GPU port) is now DONE (2026-06-10, see
closeout section above). The glass-energy fix legitimately moved GPU output, so **two pkg64-gpu HW
gates need re-baselining with written justification** (parity SSIM 0.835 < 0.85; Phase-3 prism PSNR
delta −0.59 < −0.5 dB) — these do not run on CI (no GPU); flagged for the next HW sweep.

**Round 15 Wave 2 (2026-05-28, 3 PRs merged): pkg106 Chunks B/C/D-seed — MNEE foundation complete.**
**pkg106 MNEE foundation COMPLETE** (PRs #389/#390/#391) — Chunks B/C/D-seed shipped: surface (u,v) partials (`manifold/surface_partials.h`), analytic Newton solver (`newton_iterate.h::solveAnalytic`), multi-vertex manifold chain (`manifold/manifold_chain.h` — block-tridiagonal Jacobian + damped Newton), mesh seed-ray + chain convergence on triangulated prism (`manifold/mesh_caustic.h`). All CPU-only header math + unit tests, validated to ~1e-11 vs finite-difference / analytic Snell. **Remaining: Chunk D-radiance** (wire multi-vertex MNEE into live integrator — transfer-matrix geometry term + finite prism faces + in-triangle validity + visibility; currently renders chromatic noise on wip/pkg106-chunk-d-radiance) + **Chunk E** (prism scene + hue_spread ≥0.7).

**Round 15 Wave 1 (2026-05-28, 3 PRs merged): pkg64-gpu Session 2 + pkg106 Chunk A + pkg105.**
**pkg64-gpu Session 2 DONE** (PR #385) — Hero-wavelength distribution bug fixed (lambda[0] violet-only → full-band). Gates re-spec'd (SSIM ≥0.85 + ROI luminance-parity; 0.97 unreachable for independent MC). Measured: SSIM 0.928, energy 1.38×, PSNR +2.19 dB. **pkg106 Chunk A DONE** (PR #387) — Analytic half-vector constraint Jacobian (Cycles mnee.h + Hanika 2015); foundation for Chunks B-E. **pkg105 DONE** (PR #381) — BH Blender addon params (r_obs_M + Kerr spin + ADAF). Pillar 4 Blender surface complete for BH objects.

**Round 14 closeout (2026-05-24, 12 PRs merged): CUDA-port Session N+4 + Sellmeier + pkg76 Classroom audit wave.**
**pkg55-B' Session N+4 COMPLETE** (PRs #355 + #356) — PostLightSample + PostRR CUDA kernel stages
shipped with full CPU↔GPU threshold gates enforced (p99.9 = 2.21e-6, threshold 3.5e-6). Session N+3
gates remain green (PostInit ULP=2, PostIntersect ULP=32). **CUDA-port track continues.**
**pkg64-gpu-sellmeier-upload DONE** (PR #354, `8f0eb03`) — GPU Sellmeier dispersion upload + hero-
wavelength IOR. Unblocks pkg64-gpu Phase 3 prism receiver-energy gate (measured 1.17× ≥ 1.10× PASS).
PSNR floor (−2.13 dB) and SSIM (0.52) deferred to Session 2 (per-wavelength multi-IOR): hero-only GPU
lacks chromatic spread, so per-pixel error is dominated by spatial caustic divergence by construction.
**pkg86-B Phase 1 DONE** (PR #362, `404509d`) — CPU SAOH split + full Conty 2018 importance. Measured
1.14× variance reduction (2× gate xfail retained pending scene tuning or Phase 2/3 GPU validation).
**pkg76 CSV baseline DONE** (PR #357, `e7816d0`) — Junkshop SSIM 0.972 PASS (≥0.85 gate). Classroom/
BMW27 gaps documented for follow-up. **pkg76-followup 4 gaps addressed** (PRs #360, #361, #363, #365) —
BMW27 Blender 4.x mesh layout fix, Classroom Gap 1 (image textures), Gap 2a (non-Principled shader graphs),
Gap 3 (false-positive doc), Gap 4 (area light shapes). **Classroom SSIM gate ≥0.85 not yet met** — Gap 2
(40/42 mats need non-Principled shader graph walk) remains as primary blocker. **pkg-add-cuda-syntax-ci
DONE** (PR #358, `58df412`) — Linux CI now compiles all .cu files with nvcc (syntax + typecheck only);
catches CUDA frontend errors before RTX build. **Deferred to Round 15**: pkg64-gpu Session 2 (multi-IOR),
pkg86-B Phase 2+3 (GPU port), pkg76-classroom Gap 2 (non-Principled shader graphs).

**Round 13 closeout (2026-05-23): CUDA-port milestone + Cryptomatte end-to-end.**
**pkg55-B' Session N+3 COMPLETE** — parts 1/2/2b + RNG/hero/harness fixes (PRs
#338/#343/#346/#349/#351). **CPU↔GPU PostInit gate CLOSED at ULP=2** (vs threshold
4). PostIntersect bounded at 32 ULP (pinned 64). 5-round build-fix saga (#343)
exposed Linux-CI-CUDA-blind gap (Action Item filed). **Session N+4** (next CUDA
port stage continuation) is top Round 14 track. **Cryptomatte end-to-end complete:**
pkg87a (infra, Round 12) + **pkg87b** (integrator integration, PR #344) + **pkg87c
part 1** (Blender pass+bindings, PR #345) + **pkg87d** (IoU + manifest + JSON
round-trip, PR #347) all shipped. IoU 0.85 gate (owner-authorized swap from 0.95
due to MC silhouette-edge noise floor at 64 spp); measured 0.977–0.984 across all 6
names. **pkg64-gpu Phase 2** (megakernel SMS integration, PR #348) + **Phase 3**
(acceptance gates + caustics toggle, PR #350) both shipped; hardware baseline-pinning
blocked on new **pkg64-gpu-sellmeier-upload** spec (Sellmeier dispersion not GPU-
uploadable). **pkg55-followup** (triangle normal shortcut, PR #351) tightens
`hit_normal` ULP on flat-shaded geometry (overall ULP=32 unchanged, dominated by
`hit_point` FMA fusion). **Orchestrator-meta infrastructure complete 2026-05-22**:
**pkg90** (hw-verifier worktree-parameterized CUDA build, PR #333) + **pkg97**
(merged-worktree auto-GC, PR #331) + **pkg98** (independent-review gate, PR #332) —
the HW gate now runs unattended, IMPL_CAP no longer silently saturates, and Track-A
fixes require different-model SIGN-OFF/BLOCK before push. **Blender addon
remediation** (first-principles plan landed PR #300; PR #295 triage): the staged set
is **pkg94** (Stage 1 / P1 build-integrity guard, ~½ day, **Round-10 first pickup,
depends on nothing**) → **pkg95** (Stage 2 / P3+P4 dead-UI-wires + Blender-native
camera, depends on pkg94) ∥ **pkg96** (Stage 3 / P2 reconcile-then-upload sync + P5
honesty guard, depends on pkg94, independent of pkg95). **P5's GPU parity
(BUG-02/10/11/12) is deferred into pkg55-B' as named acceptance gates (BUG-11 ≡
pkg85-D, done), NOT a separate addon GPU package** — pkg96 ships only the cheap
honesty guard. **pkg76 CSV** rows on RTX (unblocked since pkg100). pkg67 (metric-
aware path tracer) shipped PR #262.

**Pillar 4 thawed and shipping (2026-05-11+).** pkg40 (Kerr metric),
**pkg41 Kerr validation** (PR #236), **pkg42 synchrotron emission**
(PR #245 — VolumetricEmission interface, Pandya 2016 fits, bipolar jet
plugin), **pkg43 slim disk accretion model** (PR #271 — Abramowicz
1988 / Sadowski 2009, 14/14 tests), **pkg43 Blender accretion
selector** (PR #285 — black-hole panel dropdown for Novikov-Thorne /
Slim Disk / ADAF), and **pkg47 FITS data loader** (PR #292 — FITS I/O
wrapper + FITSTexture plugin, gated `ASTRORAY_ENABLE_FITS` default OFF;
FITSVolume registration deferred to pkg48 per owner ruling) all done.
**Pillar 4 now ~45% complete.** **pkg44 (ADAF)** is unblocked and
queued for Round 10; pkg45–pkg51 paste-ready specs queued.

- `pkg34-material-backend-capabilities.md` — capability metadata,
  no silent grey-Lambertian GPU fallback, CPU/GPU contact-sheet diffs.
- `pkg35-spectral-gpu-materials.md` — make CUDA material sampling
  spectral for the core material set.
- `pkg36-material-closure-graph.md` — shared material closure graph so
  many new plugins work on CPU and GPU without hand-written duplicates.
- `pkg37-blender-addon-backend-refresh.md` — bring the Blender addon up
  to the backend model: Auto/GPU/CPU device selection, viewport GPU parity,
  CUDA/tiny-cuda-nn-aware packaging, and clear runtime diagnostics.

### Pillar 5 — Production polish

Multi-GPU scaling, OIDN 2.x→3.0, Blender viewport render, motion blur,
output formats, documentation. Ongoing, opportunistic.

- Design: [`production.md`](production.md)
- Duration: ongoing
- Depends on Pillars 1, 3.

---

## The 12-week view

This is the original planning horizon, not a live schedule. For current package
state and next-up order, use `STATUS.md`.

```
Wk 1-2   [A] Plugin registries + migrate one material end-to-end (pkg01, pkg02)
         [D] Ralph begins improving test coverage

Wk 3-4   [A] Migrate remaining materials/shapes/textures (pkg03, pkg04)
         [B] First Copilot plugin as proof

Wk 5-6   [A] Integrator interface (pkg05) + spectral types (pkg10)
         [B] Spectral measured-BRDF loader (RGL database) as plugin
         [C] Cline prototypes tiny-cuda-nn integration

Wk 7-8   [A] Finish spectral migration (pkg11-14)
         [B] Fluorescence plugin, Principled Volume improvements

Wk 9-10  [A] ReSTIR DI integrator plugin
         [B] Kerr geodesic plugin, FITS loader

Wk 11-12 [A] Neural radiance cache (promote Cline prototype)
         [B] HII emission-line plugin, sim-data volumes
         [D] Blender viewport render polish
```

By week 12: spectral everything, ReSTIR, at least one neural integrator,
Kerr + working astrophysical plugins, clean plugin architecture.

---

## How to use this plan

- **Starting a coding session?** Pick an open package from `../packages/`.
- **Launching a cloud agent?** See `../agents/copilot-cloud.md`.
- **Running Claude Code locally?** See `../agents/claude-code.md`.
- **Spinning up Ralph?** See `../agents/ralph-loop.md` and
  `../scripts/ralph_loop.sh`.
- **Overseer duty?** See `../agents/overseer.md`.

When you finish a package: mark it `done` in its file header, update
[`STATUS.md`](STATUS.md), open a PR.

---

## Simplicity tax

Any PR that adds framework, abstraction layer, or "future flexibility"
without a concrete caller **today** gets rejected. The test:

> A veteran CS engineer, reading this diff cold, should say "yeah,
> that's how I'd do it" — not "clever" and not "this should have been a
> function."

Applies to humans and agents equally. Overseer enforces in first-pass
review before merges.

## Visual fidelity vs performance

Top priority is visual fidelity. Performance competitive with Cycles in
simple enough scenes on a single RTX 5070 Ti is a floor, not a ceiling.
When these conflict:
1. Visual fidelity wins for offline renders (F12).
2. Performance wins for interactive viewport preview.
3. Correctness wins over both, always.
