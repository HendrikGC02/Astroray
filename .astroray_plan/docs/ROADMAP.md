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

> **Thaw notice (2026-05-10):** the strategic gate has released. pkg56
> Phases B+C and pkg64 Phase 3 have all landed; pkg41 Kerr validation
> and the queued pkg42–pkg49 specs are unfrozen. pkg40 (Kerr metric)
> already shipped pre-gate.

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

**Status as of 2026-05-10 (Round 3 close):** the pkg34-pkg37 backend
bridge is complete. The Cycles-parity / Blender integration / denoiser
push is **approaching feature-complete** for Pillar 5:

- **Cycles parity wave done:** pkg52/53/57/58/59/60/61/62/63/65/66.
- **GPU multi-wavelength parity done end-to-end:** pkg54/54a/54b/54c/54d
  (all hardware-verified on RTX 5070 Ti; visible-band SSIM 0.999263 at
  spp=8192).
- **Denoiser story (mostly) closed:** pkg33 (OIDN integration, done),
  pkg68 (OIDN persistent device + CUDA backend, **measured 2.77×
  viewport speedup** post-pkg75), pkg69 (compositor Albedo pass, done),
  pkg70 (OptiX denoiser, **1.86× faster than OIDN-CUDA, SSIM 0.9987 vs
  OIDN**), pkg72 (motion vector AOV, done), pkg75 (AOV normal-guide
  defect fixed and verified). pkg73 OptiX temporal denoiser is
  unblocked and queued for Round 4.
- **Caustics flagship:** pkg64 Phases 1+2 done (RGB SMS skeleton +
  spectral wavelength-Newton, **+8.83 dB PSNR delta**); Phase 3
  (default-integrator MIS fold) is a Round 4 Codex pickup.
- **Cycles parity benchmark:** pkg71 framework + first canonical
  Cornell baseline shipped — **Astroray-CPU SSIM 0.9536 vs
  Cycles-CPU EXR; Astroray-GPU SSIM 0.9548 and 5.2× faster than
  Cycles-CUDA on Cornell**. pkg76 (Astroray .blend importer for
  parity scope) is the next pickup so non-Cornell scenes can produce
  rows.
- **Showcase framework:** pkg74 Phases 1+2 done (material zoo,
  convergence grid, RMSE plot, full stat coverage); Phase 3
  (interactive HTML + weekly CI) is a Round 4 Codex pickup.
- **Viewport sync:** pkg52 (persistent viewport) + pkg56 Phase A
  (instrumentation, baseline 129.92 ms) + pkg56 Phase B (uploadScene
  split into per-domain uploaders) + pkg56 Phase C (depsgraph-driven
  dispatch in `view_update`, idle frame ≤ 5 ms gate met) all **done**.

Open Pillar 5: **pkg73 + pkg56-B + pkg64-3 + pkg74-3 + pkg76 spec**
(Round 4); **pkg56 Phase C + pkg76 implementation + pkg55 Phase A**
(Round 5). pkg67 (metric-aware path tracer) stays research-blocked
until Pillar 4 thaws. pkg55 (wavefront SoA refactor) starts after
pkg56+pkg64 land for measured baselines to compare against.

**Pillar 4 has thawed (2026-05-10).** pkg56 Phases B+C and pkg64
Phase 3 have all landed. The Codex-paste-ready specs for pkg41 (Kerr
validation) and pkg42–pkg49 (synchrotron, slim disk, ADAF, FITS, HDF5,
SPH, etc.) are unblocked; pkg40 (Kerr metric) already landed during
the pre-strategic-shift round.

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
