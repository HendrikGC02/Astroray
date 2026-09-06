# pkg239 — Backdrop local-highlight parity diagnosis

**Pillar:** 5
**Track:** A
**Status:** open — detailed architect review required before implementation
**Estimated effort:** TBD
**Depends on:** none

---

## Goal

Before: standalone Diffuse export/material routing, light visibility/transport, and spatial metric sensitivity are undiagnosed. After: the diagnosis uses independent closure/light oracles, retains competing hypotheses until evidence supports a cause, and preserves fixed-seed matched main/feature/Cycles captures, raw linear floats, a fixed highlight crop, and convergence outputs.

---

## Context

Pillar 5 here is Blender/Cycles visual parity, and this package is a diagnosis of existing behavior. The code surface under diagnosis: `_apply_solid_diffuse` in `benchmarks/blender_parity/scene_library.py` creates `ShaderNodeBsdfDiffuse`, and `_add_backdrop` builds solid-color quads without VM. This is a baseline-reproduced local visual mismatch, not established pkg230 causation; a global metric pass does NOT establish full visual parity, and no root-cause claim is made.

---

## Evidence

- Astra qualitative inspection of `test_results/pkg230-p2/backdrop_convergence.png` shows a small bright white highlight at the top of the green band in BOTH fresh main and pkg230 renders, absent in Cycles; it persists at 64 and 256 spp.
- Recorded normalized global SSIM gate threshold 0.90: at 256 spp main 0.91410756, feature 0.91410750 (both pass); at 64 spp both 0.8395174 (fail), while the local highlight persists.
- Source metrics retained in `test_results/pkg230-p2/backdrop-convergence.json`.

---

## Reference

None.

---

## Prerequisites

- [ ] TBD

---

## Specification

### Files to create

None.

### Files to modify

None.

### Key design decisions

- Detailed architect review sets the diagnostic scope before any implementation.
- Owner queue priority stays unchanged; Pillar 4 remains PAUSED.
- Coordinate with pkg233 only for a shared exporter: pkg233 owns texture omission; pkg239 owns the solid-color highlight.

---

## Acceptance criteria

All implementation gates UNRUN:

- [ ] Repeat baseline/feature/Cycles at 64 and 256 spp plus a justified convergence extension with fixed seeds/configs.
- [ ] Raw linear arrays, matched crop, and localized error statistics alongside global SSIM.
- [ ] Independent Diffuse/light-visibility oracles localize the cause.
- [ ] Saved full-frame/crop/convergence outputs receive Astra/Claude qualitative review.
- [ ] Existing global gate retained unchanged.
- [ ] Any implementation requires documented regressions, fresh intended native-import/ABI/resource checks, GPU lock, and at most two isolated worktrees.
- [ ] Independent Astra/Claude causal review and sign-off.

---

## Non-goals

- No SSIM threshold relaxation, VM/math change, broad transport rewrite, queue promotion, or paused Pillar 4 work.
- No claim of whole-baseline visual parity.

---

## Progress

- (none yet)

---

## Lessons

- (none yet)
