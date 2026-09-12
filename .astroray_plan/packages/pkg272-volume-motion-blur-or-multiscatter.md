# pkg272 — (OPTIONAL) Volume velocity-grid motion blur OR multi-scatter approximation

**Pillar:** 3
**Track:** A
**Status:** open
**Estimated effort:** TBD
**Depends on:** pkg268

---

## Goal

Before: heterogeneous volumes render, emit, and are Cycles-parity-complete for
still frames (pkg267–271), but velocity-grid motion blur and a dense-media
multiple-scattering shortcut are not implemented. After (IF filed): EITHER a
velocity grid drives per-sample advection for motion-blurred smoke/fire, OR a
multiple-scattering approximation brightens dense clouds closer to Cycles'
`multiple_scattering` look — whichever a real corpus scene demonstrably needs.

---

## Context

This is an explicitly **optional** slot, held open only so a demonstrated need
from pkg271's corpus has a home rather than being smuggled into an unrelated diff
(AGENTS.md continuous-improvement lane). It stays `open`/unscheduled until the
owner picks a fork (research note §6 open question 3) and a corpus scene shows the
gap. Neither sub-feature is a Cycles-parity blocker: motion blur is a polish/
production feature; multi-scatter is a look-match for very dense media that
single-scatter under-lights. Research: `docs/volumes-track-research-2026-09-12.md` §5, §6.

---

## Evidence

- 2026-09-12: filed as a placeholder; no corpus scene yet demonstrates the need.
  Do not implement until pkg271 lands and one of the two forks is chosen.

---

## Reference

- Design doc: `.astroray_plan/docs/volumes-track-research-2026-09-12.md` §6 (open question 3)
- External (motion blur): Cycles volume `velocity` attribute + shutter advection.
- External (multi-scatter): Wrenninge et al. / Cycles `volume` multiple-scattering
  approximation; Jensen/Christensen dipole-style shortcuts (cite via
  `cite-algorithm` when the fork is chosen).

---

## Prerequisites

- [ ] pkg271 is done and a corpus scene demonstrates either a motion-blur or a
      dense-media under-lighting gap.
- [ ] Owner has chosen the fork (motion blur vs multi-scatter).
- [ ] `cite-algorithm` run for the chosen algorithm.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg272_volume_optional.py` | Motion-blur A/B vs Cycles, OR multi-scatter energy vs a reference — per the chosen fork |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/volume/volume_transport.h` | Velocity-grid advection at the sample time, OR a multi-scatter gain term — per the chosen fork |

### Key design decisions

#### Fork (a): velocity-grid motion blur

Consume the `velocity` grid carried through since pkg267; advect the density
lookup by `velocity · (t - t_shutter_open)` per sub-frame sample. Gate: a
motion-blurred smoke A/B against Cycles within a look band.

#### Fork (b): multiple-scattering approximation

Add a cited dense-media multi-scatter gain (not brute-force high-order tracking)
so thick clouds match Cycles' brighter look. Gate: energy vs a brute-force
high-order-scatter reference on a dense slab; single-scatter stays the default.

Do NOT implement both. Do NOT start until the owner picks the fork and a corpus
scene proves the need.

---

## Acceptance criteria

- [ ] `test_pkg272_volume_optional.py` passes for the chosen fork (motion-blur A/B
      band, OR multi-scatter energy vs reference).
- [ ] The default look is unchanged when the feature is off (byte-identical or
      within noise).
- [ ] Full CPU (+ GPU if the fork touches the device) suites green.

---

## Non-goals

- Do not implement this package before pkg271 demonstrates the need.
- Do not implement both forks.
- Do not add brute-force high-order path tracing for multi-scatter (approximation
  only).
- Do not change the still-frame scattering/absorption/emission physics.

---

## Progress

- [ ] Wait for pkg271 corpus evidence + owner fork choice.
- [ ] cite-algorithm for the chosen algorithm.
- [ ] Implement the single chosen fork + its gate.

---

## Lessons

*(Fill in after the package is done.)*
</content>
