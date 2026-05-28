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
