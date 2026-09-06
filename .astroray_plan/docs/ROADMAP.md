# Astroray Master Roadmap

**One document to navigate the whole plan.** Every other document exists
because this roadmap points at it. New to the project? Read this first.

---

## Vision in one paragraph

Astroray is a C++/CUDA path tracer with a Blender 5.2+ addon. Near-term delivery
prioritizes a production-capable Blender/DCC renderer: responsive GPU interaction,
trustworthy CPU fallback, and Cycles-compatible behavior where appropriate.
The long-term target remains research-grade astrophysical rendering and
scientific visualization. Spectral transport, dispersion, infrared/band-aware
outputs and robust physical transport are foundations of both goals; Pillar 4
remains paused under the current sequencing below. The design goal is **pluggability** — new materials, shapes,
light transport techniques, and astrophysical phenomena should be
drop-in plugins that register into a small set of factory registries,
not patches to core files. A veteran engineer looking at the codebase
should think "this is the obvious way to do it," not "this is clever."

**Performance goal:** rival Cycles in simple enough cases on a single
RTX 5070 Ti (CUDA). **Fidelity goal:** surpass Cycles on spectral and
astrophysical scenes. **Simplicity tax:** every abstraction pays for
itself with a concrete caller today.

---

## Current sequencing

**Authoritative direction lives in
[`north-star-and-integration-gate-2026-09-07.md`](north-star-and-integration-gate-2026-09-07.md)**
(owner-approved north star + the measurable Pillar-4 exit gate + the next
4–6-week sequencing). Read that first; the summary below is a pointer, not a
second source of truth.

- **North star:** a spectral C++/CUDA path tracer for research-grade
  astrophysical rendering, driven from inside Blender as the steering wheel.
  Near-term bar: a production-capable Blender renderer with a fast interactive
  GPU viewport on the RTX 5070 Ti, CPU as correctness oracle, Cycles-compatible
  where Cycles is right. **correctness > fidelity > speed.**
- **Pillar 4 stays PAUSED** until the exit gate (§2 of the north-star doc) is
  met — viewport present p95 ≤ 100 ms, shader-socket coverage, three reference
  scenes rendering CPU+GPU parity-clean, native adaptive-sampling + denoise,
  zero high-severity addon bugs, a documented one-command install.
- **Science-foundational side lane** (allowed while Pillar 4 is paused, ordered
  behind the gate work): pkg243 raw band provenance, pkg133 SRF spectral
  sensors, pkg130 light groups, pkg251 spectral reachability.
- **Next rounds (~3 packages each):** R1 pkg241 Phase 0 + pkg237/238 +
  pkg242; R2 pkg253 + pkg245 + pkg234/233; R3 pkg241 behavior + pkg251 +
  pkg243; R4 pkg133 + pkg130 + pkg136 GPU. Full ranking and dependencies in the
  north-star doc §4.

**Explicitly de-prioritized (owner-endorsed):** the sub-percent GPU/CPU parity
tail — pkg172 effect (B) / pkg173 and the pkg153 remainder — sits below the
integration gate unless a paper requires bit-level parity.

---

## The agent tracks

Work happens on independent tracks. Each has its own agent and acceptance
criteria. Progress on one track rarely blocks another — that is by design, so
your single-developer throughput multiplies without coordination overhead.

| Track | Owner agent | Runs on | Purpose |
|---|---|---|---|
| **A. Core quality** | Claude Code (local) | Your RTX 5070 Ti | Correctness, foundational refactors — all package specs route here |
| **B. Feature breadth** | Retired 2026-04 era (was Copilot cloud) | — | Legacy `Track: B` specs route to Claude Code (`package-implementer`) |
| **C. Experiments** | Retired 2026-04 era (was Cline) | — | Same routing |
| **D. Grind work** | Open-weight models via the `delegate` skill (opencode) | Your machine | Bounded mechanical work; evidence-verified by Claude (CLAUDE.md §5) |
| **E. Coordination/review** | Retired 2026-07 (was Codex) | — | Legacy `Track: E` specs route to Claude Code (`package-implementer`) |

Coordination is done by the Claude Code `architect` and
`roadmap-orchestrator` agents (`.claude/agents/`), not by a separate
overseer. Retired-track handbooks are archived in
`docs/archive/agents-multitrack-2026-04/`.

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

> **PAUSED (2026-06-08, owner; reaffirmed 2026-09-07) — unpause is gated on the
> MEASURABLE Pillar-4 exit checklist in
> [`north-star-and-integration-gate-2026-09-07.md`](north-star-and-integration-gate-2026-09-07.md)
> §2**, not a prose judgement. The gate covers viewport responsiveness,
> shader-socket coverage, three reference scenes rendering CPU+GPU parity-clean,
> native adaptive-sampling + denoise, zero high-severity addon bugs, and a
> documented one-command install. As of 2026-09-07 the gate is NOT MET
> (DROPPED-SILENT sockets 64.5%, real viewport present latency unmeasured, one
> of three reference scenes NOT GREEN on GPU). The Pillar-4-era specs are
> outdated and get a full audit pass at unpause. Do not unpause unilaterally.

> **Pre-pause groundwork (2026-05):** pkg40 Kerr metric, pkg41 Kerr validation
> (#236), pkg42 synchrotron emission (#245), pkg43 slim disk (#271), pkg44 ADAF
> (#310), pkg47 FITS loader (#292, `ASTRORAY_ENABLE_FITS` default OFF), pkg67
> metric-aware tracer, pkg99, pkg105 landed before the pause (~50 % of the
> original Pillar-4 scope). Their specs and the 2026-05→08 round history are in
> [`archive/roadmap-history-2026-05-to-2026-08.md`](archive/roadmap-history-2026-05-to-2026-08.md).

Kerr metric, synchrotron emission, HII recombination lines, simulation
data import (FITS, HDF5, yt), telescope PSF. Each phenomenon is a
plugin. This is Astroray's unique niche.

- Design: [`astrophysics.md`](astrophysics.md)
- Duration: 6–10 weeks, parallel with other pillars
- Depends on Pillars 1, 2.

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
