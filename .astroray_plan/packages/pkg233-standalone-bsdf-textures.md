# pkg233 — Standalone BSDF texture and scalar plumbing

**Pillar:** 5
**Track:** A
**Status:** open — detailed architect review required before dispatch
**Estimated effort:** TBD at detailed architect review
**Depends on:** none

---

## Goal

**Before:** the standalone Diffuse node drops linked ImageTexture color inputs in the observed chart — an `ImageTexture → BSDF_DIFFUSE` chain and an `ImageTexture → VectorMath/Rotate → Diffuse` chain both render gray, and vectorMath/Rotate changes leave numerical channels unchanged.
**After:** an architect-reviewed supported subset of standalone BSDF nodes routes color textures and scalar parameters through physically correct closure carriers; unsupported combinations warn visibly instead of silently rendering gray/constant.

---

## Context & evidence

Parent's real Blender 5.1 CPU chart found plain `ImageTexture → BSDF_DIFFUSE` and `ImageTexture → VectorMath/Rotate → Diffuse` rendered gray; vectorMath/Rotate changes left numerical channels unchanged. Retained feature artifacts: `test_results/pkg230-p2/blender_cpu_cycles_failed_diffuse.png` and `blender-cpu-metrics_failed_diffuse.json`. Source `_standalone_bsdf_spec` in `blender_addon/__init__.py`, BSDF_DIFFUSE branch (around 3832 in feature checkout; 3817 in this base) calls `get_color_input` and `get_float_input` only, never `get_base_color_texture`; this code is unchanged from main. Current pkg230 verified VM scope uses the Principled route. This is evidence for a standalone-node consumer gap, not failure of the shared VM or proof every standalone node fails.

---

## Specification

Architect-first audit of standalone Diffuse/Glossy/Glass carrier selection and color texture/scalar parameter plumbing; trace ordinary ImageTexture and image→opVM chains through upload/actual closures. Decide the exact supported subset and files before implementation; no newly claimed full coverage; do not just route everything through Principled and assume physical equivalence. Preserve constant/unlinked semantics; require a physically correct closure carrier and explicit review of any carrier correction. Reuse existing addon `get_base_color_texture`/scalar paths and the canonical headless Blender parity harness where valid; warn visibly when textures/scalars cannot be represented instead of silently gray/constant. No changes to transport physics, shaderVM, coordinateVM, new UI, or Pillar 4.

---

## Acceptance criteria (future — all UNRUN)

- [ ] Reproduce real headless Blender CPU plain-image + vector-chain A/B vs Cycles in common linear space; images must show linked textures affect channels.
- [ ] Per-node color/scalar routing matrix; constant/unlinked regressions; unsupported-warning tests; CPU/GPU parity.
- [ ] Freshly built intended module; source freshness/import path/native arch/ABI/register checks if the engine is touched.
- [ ] Representative actual-Blender saved renders qualitatively reviewed by Astra/Claude; GPU lock and max 2 isolated implementation worktrees.
- [ ] Full documented tests/caller-binding review and independent Astra/Claude sign-off. Parent reviews draft scope; all coverage claims await evidence.

---

## Non-goals

This follow-up does not change owner queue priority. Glossy/Glass and scalar
inputs require audit; their failure is not established by the Diffuse chart.

- No transport-physics, shaderVM, coordinateVM, or new-UI changes; no Pillar 4 work.
- No claimed full standalone-node coverage; no silent gray/constant fallbacks.

---

## Progress

- [ ] Detailed architect review of scope, supported subset, and files (all implementation gates UNRUN).
- [ ] Implementation + gates (future).
Independent Claude filing review: SIGN-OFF TO FILE ONLY, 2026-09-06.
Evidence: `test_results/pkg232-235/claude-filing-review.txt`.
