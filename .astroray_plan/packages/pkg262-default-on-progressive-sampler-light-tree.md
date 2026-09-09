# pkg262 — Turn on the landed samplers by default: progressive Sobol sampler, light tree, GPU adaptive sampling

**Pillar:** 5
**Track:** A
**Status:** done — 2026-09-09, PR #788 (merged dedd4853). GPU adaptive sampling now actually engages: fixed a dead `adaptiveOn` gate in `gpu_wavefront_snapshot.cu` that required `alphaOut == nullptr`, unconditionally false at the real call site since pkg201; addon enables the pkg224 progressive sampler only when GPU adaptive sampling is requested (fork (b) — the engine-default fork (a) was tried and reverted after measuring a wavefront perf-ceiling and CPU/GPU snapshot-parity regression, see the A/B doc); `light_sampler` fallback default flipped to `'light_tree'`; degradation report now flags GPU-ignored adaptive cases. A/B: `.astroray_plan/docs/pkg262-default-flip-ab-2026-09.md`.
**Estimated effort:** 2 sessions (~6 h; A/B measurement on the RTX + parity sweeps + addon change)
**Depends on:** pkg224, pkg131, pkg86, pkg81

---

## Goal

Before: three landed features are inert in every Blender render: the pkg224
progressive Sobol sampler (engine default off, never enabled by the addon), the
pkg86 light tree (addon `light_sampler` defaults to `power` although the Phase 3
gates cleared in June and Cycles defaults to its light tree), and — because the
GPU wavefront activates adaptive sampling only when the progressive sampler is
also on — the pkg131 GPU adaptive-sampling leg, so the native "Adaptive
Sampling" toggle changes nothing on GPU (issue #759). After: the progressive
sampler and the light tree are on by default on both backends with measured
A/B evidence (noise at equal spp, frame time, parity suites), GPU adaptive
sampling actually engages from the native panel and is proven by an
output-effect test (sample-count AOV differs, flat-region noise falls), and the
addon's degradation report never claims a setting is honoured when the engine
ignores it.

---

## Context

Owner audit 2026-09-08: "some features were implemented but turned off by
default for now and never fully turned on." The lead's sweep found exactly
these three (pkg206 hero sampling and pkg178 native Principled are on; pkg136
guiding and pkg127 poly-SMS stay off by decision). Gate (d) of the north star
(adaptive + denoise from native panels) cannot be green on GPU while #759
stands, and the pkg241 viewport work measures noise-per-frame that the
progressive sampler changes. Serves Pillar 5.

---

## Evidence

- 2026-09-08: `src/gpu/wavefront/gpu_wavefront_snapshot.cu:1778-1780` —
  `adaptiveOn = getUseAdaptiveSampling() && getUseProgressiveSampler() && …`;
  `include/raytracer.h:2310` `useProgressiveSampler = false`; no
  `set_use_progressive_sampler` call in `blender_addon/`.
- 2026-09-08: `blender_addon/__init__.py:254-263` `light_sampler` default
  `'power'`; pkg86 spec: "default off until Phase 3 acceptance gates clear;
  then default on" — gates cleared 2026-06-11 (PRs #434/#436/#438), never flipped.
- pkg224 spec: opt-in was an owner fork decision on 2026-08-29 with no written
  flip condition; pkg131 GPU leg byte-identical when off, HW-verified on.

---

## Reference

- Specs: pkg224 (sampler, `__constant__` runtime flag), pkg131 (adaptive, both
  legs), pkg86/pkg86-B (light tree CPU/GPU), pkg81 (viewport bench used for the
  frame-time A/B).
- Issue #759.
- `benchmarks/viewport_parity/run.py` (pkg81 bench), `benchmarks/blender_parity/harness.py`,
  `tests/test_pkg224_*.py`, `tests/test_pkg131_*.py`, `tests/test_pkg86*.py`.

---

## Prerequisites

- [ ] Build passes on main; `.pyd` newer than HEAD before any GPU number.
- [ ] GPU lock held for every RTX measurement.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg262_gpu_adaptive_effect.py` | Output-effect gate for gate (d): on GPU, with the native adaptive toggle on vs off at equal max spp, the per-pixel sample-count buffer differs and flat-region variance falls; skips without CUDA; must FAIL on main today (#759). |
| `.astroray_plan/docs/pkg262-default-flip-ab-2026-09.md` | The A/B evidence: per-scene noise (RMSE vs a high-spp reference) at equal spp, frame time on the pkg81 bench, parity-suite results, with the progressive sampler and light tree off vs on, CPU and GPU; plus the equal-spp RMSE ratio Astroray/Cycles per pkg259 corpus scene (#763 — tracked, no gate; owner 2026-09-08). |

### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` | `useProgressiveSampler` default → true once the A/B is in-band (or the addon enables it, see decisions). |
| `blender_addon/__init__.py` | `light_sampler` default → `'tree'`; when adaptive sampling is requested on GPU ensure the progressive sampler is enabled; the degradation report marks GPU adaptive as unavailable whenever the wavefront would ignore it (passes/cryptomatte/transparent film). |
| `blender_addon/settings_map.py` | Rows for adaptive sampling and light tree reflect the new effective behaviour. |
| `tests/test_pkg224_progressive_sobol_gpu.py` | Byte-identity tests that assume the sampler is off must pin the flag explicitly (same for `test_pkg224_progressive_sobol.py`). |
| `.astroray_plan/packages/pkg224-progressive-sampler.md` | Progress: default flipped here. |
| `.astroray_plan/packages/pkg86-light-tree.md` | Progress: default flipped here. |

### Key design decisions

- **Measure before flipping.** Each flip needs the A/B doc row: no regression
  in the pkg81 frame time beyond +5 %, no parity-suite failure, noise at equal
  spp equal or better. A flip that fails its row stays off and the reason is
  recorded.
- **Engine default vs addon enable** for the progressive sampler: prefer the
  engine default (one behaviour everywhere); fall back to "addon enables it
  whenever adaptive is requested on GPU" only if the A/B shows a non-adaptive
  regression.
- **Never claim honour silently** (pkg200 rule): any remaining case where the
  GPU ignores the adaptive toggle is reported through the degradation report.

---

## Acceptance criteria

- [x] `tests/test_pkg262_gpu_adaptive_effect.py` red on main, green after; runs
      on the RTX under the lock.
- [x] A/B doc complete for both flips, CPU and GPU, with the pkg81 bench numbers.
- [x] Full pytest suite + `benchmarks/blender_parity` smoke green with the new
      defaults; byte-identity tests updated, not deleted. (CPU: 1864 passed/0
      failed; GPU: 766 passed/0 failed, `tests/test_blender_parity_harness.py`
      included in both runs.)
- [x] Addon degradation report correct for the ignored-adaptive cases; #759
      closed by the PR.

---

## Non-goals

- Do not turn on pkg136 guiding or pkg127 poly-SMS (owner decisions).
- Do not change the sampler or light-tree algorithms; defaults and wiring only.
- Do not relax any parity band to absorb a regression.

---

## Progress

- [x] 2026-09-08 — filed by the lead; owner approved the direction; not started.
- [x] 2026-09-08 evening — owner: proceed as filed; #763 equal-spp noise ratio added to the A/B doc (no gate).
- [x] 2026-09-09 — implemented. Red test written and confirmed red on main
      (build_cuda @ SHA 1108b918). Fork (a) (engine default) tried, built,
      measured, and REVERTED after breaking the wavefront perf ceiling
      (1.629s > 1.5s) and the CPU/GPU snapshot-parity gate (PostInit ULP
      2.1B > 4). Fork (b) shipped instead: addon enables the progressive
      sampler only when GPU adaptive sampling is requested. Found and fixed
      an independent pkg131-introduced bug (`adaptiveOn` gated on
      `alphaOut == nullptr`, unconditionally false at the real call site
      since pkg201, so GPU adaptive sampling never engaged under ANY flag
      combination before this fix). `light_sampler` fallback default
      flipped to `'light_tree'`. Full A/B in
      `.astroray_plan/docs/pkg262-default-flip-ab-2026-09.md`. CPU suite:
      1864 passed/0 failed. GPU suite: 766 passed/0 failed (was 758/9-failed
      under fork (a), confirming the revert fixed every regression).

---

## Lessons

- **Measure the fork before committing to the spec's stated preference.**
  The spec preferred the engine default (fork (a)) as "one behaviour
  everywhere", but it silently assumed the CPU/GPU snapshot-parity harness
  and the wavefront perf-gate would tolerate a default RNG algorithm change.
  They didn't (ULP gate blew from 4 to 2.1 billion; perf ceiling blew by
  2.3x). The spec's own "a flip that fails its row stays off" rule caught
  this cleanly once actually measured — don't skip the A/B because a fork
  has a stated preference.
- **A gate's `alphaOut == nullptr` check can be dead code without anyone
  noticing** when every real call site always passes a non-null pointer
  (the pointer's nullity stopped being a useful proxy for "transparent film
  requested" once pkg201 made the buffer unconditional). Prefer the
  semantic flag (`getUseTransparentFilm()`) the sibling `coverageOn` check
  two lines above already used, over a raw pointer check, when both exist
  in the same function.
