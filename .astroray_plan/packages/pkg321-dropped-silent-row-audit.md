# pkg321 — DROPPED-SILENT row audit: verify the engine or reclassify (#1089)

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 1 session (~3-4 h); CPU probes, GPU confirmation legs via the lead
**Depends on:** pkg320

---

## Goal

Before: 76 (nine-scene) / 63 (candidate) of the gate (b) weight sits in DROPPED-SILENT rows whose status nobody has
checked (Hair Principled, BSDF Normal/Tangent/Coat Normal, `distribution`/`subsurface_method`/Anisotropic, Principled
Volume attributes, Sky props, Glass thin film). Each one is either a stale row or a real silent drop.
After: every family has a verdict backed by a counterfactual probe: stale rows are credited through the scanner, real
drops emit an attributable DegradationReport warning (silent -> reported, b4) and have an issue.

---

## Context

pkg318 causes 6, 7, 9 and 10. Gate (b) cannot reach 0.95 while these rows stay unknown, and every real one is also an
engine gap a user would hit silently. This lane audits and reports; it does not fix engine gaps (they get issues and
go to later batches). No owner decision is involved.

---

## Evidence

- 2026-10-06: #1089 family table (weights nine / candidate): Hair 27 / 9, BSDF Normal/Tangent 20 / 11, enums + Anisotropic 15 / 12, Principled Volume 5 / 10, Sky 4 / 4, Glass thin film + misc 5 / 17.

---

## Reference

- Issue #1089; `.astroray_plan/docs/gate-b-provisional-score-2026-10.md`.
- Counterfactual probe method: pkg318 `effect` check (feature present vs mutated) and the au-coords lesson in
  `pkg310-production-corpus-burndown.md` (coplanar geometry under a uniform world isolates a texture/BSDF input).
- Cycles semantics per family: `kernel/svm/closure.h` (Normal/Tangent per closure, `distribution`, `subsurface_method`), `kernel/closure/bsdf_principled_hair_*.h`, `scene/shader_nodes.cpp` (Apache-2.0).

---

## Prerequisites

- [ ] pkg320 merged (same generator file; identities resolve).
- [ ] #1093 (pkg316 hair) merged before the Hair family is probed.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg321_dropped_row_probes.py` | One counterfactual probe per family: mutate the input, assert the CPU render changes (or the warning is emitted); GPU leg marked `gpu` |
| `.astroray_plan/docs/pkg321-dropped-row-audit.md` | Per-row verdict table (stale / real drop / partial), evidence path, issue link |

### Files to modify

| File | What changes |
|---|---|
| `scripts/generate_blender_parity_matrix.py` | Credit handling the scanner misses, only where the probe proves it (mechanical evidence, #1028 discipline) |
| `blender_addon/__init__.py` | DegradationReport entries for proven real drops (report only, no new export behaviour) |
| `docs/blender_parity/coverage_matrix.json` | Regenerated, never hand-edited |

### Key design decisions

- **Probe before classifying.** A row changes class only with a probe that shows the input moves pixels (credit) or
  does not (warn + issue). Reading the exporter is not enough.
- **Report, don't fix.** A real drop gets a warning and an issue with the probe as its repro; fixing it here would
  make the lane unbounded.
- **Bump-path credit for Normal inputs:** if the Normal input is honoured only through the Bump/Normal Map path,
  credit exactly that path and leave other sources as reported.

---

## Acceptance criteria

- [ ] Every #1089 row has a verdict in the audit doc with its probe and evidence path.
- [ ] Probe tests pass on CPU; GPU legs run once under `gpu_locked_run.py` (lead).
- [ ] `silent_drop_audit.py coverage` matrix-silent count falls by the stale rows; real drops read "reported" with an issue each.
- [ ] Renders of production + corpus v2 scenes are unchanged (warnings only): CPU byte-identical on two scenes.
- [ ] `python scripts/project_index.py lint` passes.

---

## Non-goals

- Do not implement missing engine features (file them).
- Do not change the witness predicate or the frozen inputs.
- Do not hand-edit matrix rows.

---

## Progress

- [ ] Hair family (after #1093)
- [ ] BSDF Normal / Tangent / Coat Normal
- [ ] Enum props + Anisotropic
- [ ] Principled Volume, Sky, Glass thin film, misc
- [ ] Regenerate, audit doc, PR

---

## Lessons

*(Fill in after the package is done.)*
