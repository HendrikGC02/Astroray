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

> **Thaw notice (2026-05-10) + shipping (2026-05-11):** the strategic
> gate released, and Pillar 4 is actively shipping. pkg40 (Kerr
> metric) + **pkg41 (Kerr validation, PR #236)** + **pkg42 (synchrotron
> emission, PR #245 — VolumetricEmission interface, Pandya 2016 fits,
> bipolar jet plugin, 9 tests)** all done. **pkg43 (slim disk)** is
> the next Codex pickup; pkg44–pkg49 specs unfrozen and queued.

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

Open Pillar 5 long-tail (Round 7+): **pkg55 Phase B + Phase C**
(wavefront migration proper — Phase B is the user-facing parity
unlock), **pkg82** variance characterisation, **pkg76 CSV** rows on
RTX, **pkg83**/**pkg84** addon-only viewport polish. pkg67 (metric-
aware path tracer) is now unblocked alongside Pillar 4; revisit once
pkg40 + pkg55 maturity is in place.

**Pillar 4 thawed and shipping (2026-05-11).** pkg40 (Kerr metric),
**pkg41 Kerr validation** (PR #236), and **pkg42 synchrotron
emission** (PR #245 — VolumetricEmission interface, Pandya 2016 fits,
bipolar jet plugin) all done. **pkg43 (slim disk)** + **pkg44 (ADAF)**
are next in series for Round 7 Codex; pkg45–pkg49 paste-ready specs
queued.

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
