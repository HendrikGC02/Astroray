# pkg262 — Turn on the landed samplers by default: progressive Sobol sampler, light tree, GPU adaptive sampling

**Pillar:** 5
**Track:** A
**Status:** open — filed 2026-09-08 from the owner's "off for now" audit (owner approved the direction 11:50)
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
| `.astroray_plan/docs/pkg262-default-flip-ab-2026-09.md` | The A/B evidence: per-scene noise (RMSE vs a high-spp reference) at equal spp, frame time on the pkg81 bench, parity-suite results, with the progressive sampler and light tree off vs on, CPU and GPU. |

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

- [ ] `tests/test_pkg262_gpu_adaptive_effect.py` red on main, green after; runs
      on the RTX under the lock.
- [ ] A/B doc complete for both flips, CPU and GPU, with the pkg81 bench numbers.
- [ ] Full pytest suite + `benchmarks/blender_parity` smoke green with the new
      defaults; byte-identity tests updated, not deleted.
- [ ] Addon degradation report correct for the ignored-adaptive cases; #759
      closed by the PR.

---

## Non-goals

- Do not turn on pkg136 guiding or pkg127 poly-SMS (owner decisions).
- Do not change the sampler or light-tree algorithms; defaults and wiring only.
- Do not relax any parity band to absorb a regression.

---

## Progress

- [ ] 2026-09-08 — filed by the lead; owner approved the direction; not started.

---

## Lessons

- (none yet)
