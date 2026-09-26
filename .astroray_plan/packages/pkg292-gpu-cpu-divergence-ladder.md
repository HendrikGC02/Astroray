# pkg292 — GPU/CPU divergence ladder: Disney under a sun 1.84× (#876), env-Cornell red +12 % (#862), principled_hair ±11 % (#853)

**Pillar:** 2
**Track:** A
**Status:** open
**Estimated effort:** 3 sessions (~9 h): one per item, each a separate lane
**Depends on:** pkg275, pkg123, pkg225

---

## Goal

Before: three GPU-vs-CPU per-channel disagreements sit outside the ±5 %
convention: `disney` under a single dedicated sun GPU/CPU ≈ 1.84 (#876); the
pkg55 `session_n1_envmap_cornell` red channel 1.122 and creeping (#862);
`principled_hair` GPU +11 % unpigmented, −13 % blue when pigmented (#853).
After: each has a texel/lobe-exact ladder (pkg275 pattern) that names the
diverging term, the term is fixed on the wrong side (attributed against a
baseline build, not by reasoning), and the pkg55/pkg123/pkg225 gates pass at
their original bands without widening.

---

## Context

CPU is the correctness oracle; a GPU that disagrees by 12–84 % on the
default Blender material or on hair means every GPU parity number is
suspect. #876 in particular is the most common material under the most common
light. These are Opus-lane items (memory `delegate-tier-stalls-on-hard-packages`).

---

## Evidence

- 2026-09-24 (#876): `disney` default params, one dedicated sun, GPU/CPU ~1.84; repro in `astra_run\batchU\u859\`.
- 2026-09-20 (#862): CPU [0.20795, 0.22505, 0.26959] vs GPU [0.23337, 0.22808, 0.27423] → [1.122, 1.014, 1.017]; 9.1 % at gate creation (2026-06-11, PR #444), 11.4 % pre-observer, 12.2 % now; `world_max_bounces=0` leaves it at 1.120.
- 2026-09-19 (#853): melanin 0 → 1.113/1.115/1.117; melanin 0.6 → 0.963/0.944/0.865 (6 seeds pooled).

---

## Reference

- Burley 2015, "Extending the Disney BRDF to Integration and Subsurface Scattering"; `plugins/materials/disney.cpp` vs `include/astroray/gpu_materials.h` (`GMAT_DISNEY`/closure-graph lowering, memory `gpu-dielectric-lowers-to-closure-graph`).
- pkg275 ladder method (`.astroray_plan/packages/pkg275-*.md`): texel-exact probes, one term per rung, both backends.
- Chiang et al. 2016, "A Practical and Controllable Hair and Fur Model" (`plugins/materials/principled_hair.cpp`, `include/astroray/gpu_hair.cuh`); pbrt-v3 `hair.cpp` (BSD-2) per-lobe (R/TT/TRT) evaluation to use as a third oracle.
- `tests/wavefront_diff/test_pkg55_gpu_wavefront_image.py`, `test_pkg55_megakernel_env_open_scene.py`; `tests/test_pkg123_disney_metal_gpu_cpu_parity.py`; `tests/test_pkg225_spectral_hair.py`.
- Memory: `verify-attribution-with-a-baseline-build`, `gpu-perf-ab-clock-drift` (not relevant to means, relevant to any perf claim), `gpu-spectral-curves-render-black` (integrator-name-derived flags class of bug).

---

## Prerequisites

- [ ] Batch AC merged; baseline worktree build of main for attribution.
- [ ] GPU lock discipline: one lane on the GPU at a time (memory `cuda_verifier_concurrency`).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg292_disney_sun_parity.py` | `disney` default + one sun, 64×64, 3 seeds: GPU/CPU per channel within ±5 %; per-lobe rungs (diffuse only, specular only, sheen/clearcoat off) as parametrised cases so the failing lobe is named by the test. |
| `tests/test_pkg292_env_cornell_red.py` | The #862 scene split into rungs: env-only miss, env NEE only (`world_max_bounces=0`), one diffuse bounce, full; per-rung GPU/CPU within ±5 % red. |
| `tests/test_pkg292_hair_lobes.py` | Single fibre, single light, per-lobe (R/TT/TRT) GPU vs CPU vs a numpy pbrt-v3 hair port within ±5 %; melanin 0 and 0.6. |
| `.astroray_plan/docs/pkg292-gpu-cpu-ladders.md` | Rung tables for all three; the named term per item; baseline attribution. |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/gpu_materials.h` | The diverging Disney term (candidates: sun `isDelta` MIS weight on the closure-graph path, `wasSpecular` after a delta lamp, sheen/clearcoat lobe weights, the pkg141 near-delta clamp) — fixed on whichever side the ladder convicts. |
| `include/astroray/gpu_env_spectral.cuh` | (and `gpu_bvh.h` env lookup) If #862's red is the env lookup/MIS (candidates: env-NEE pdf vs CPU CDF sampler after #747, spectral upsample of the red-heavy map, texel-edge offset #832 interacting with a sharp red boundary). |
| `include/astroray/gpu_hair.cuh` | Lobe count / path-length divergence in the GPU hair walk. |
| `tests/wavefront_diff/test_pkg55_gpu_wavefront_image.py` | Band stays; expectations re-pinned only with attribution. |
| `tests/wavefront_diff/test_pkg55_megakernel_env_open_scene.py` | Same. |
| `tests/test_pkg225_spectral_hair.py` | Same; record the measured GPU/CPU number. |

### Key design decisions

- **Three lanes, one method.** Each item is its own lane and PR; they share `pkg292-gpu-cpu-ladders.md`. #876 first (largest, most common).
- **Ladders isolate one term per rung**; a rung that removes the gap names the term. No fix is applied to a term a rung did not convict.
- **Third oracle for hair** (numpy pbrt-v3 port, ~150 lines) because CPU vs GPU disagreeing does not say which is right; memory `clean-room-oracle-is-self-consistency-not-ground-truth` — the port is an independent implementation of the same paper, which is enough to break the tie.
- **#862 may end as a CPU fix** (the CPU env sampler landed later than the gate); the 12 % band is not widened either way.

---

## Acceptance criteria

- [ ] `test_pkg292_disney_sun_parity.py` all rungs within ±5 % on the RTX 5070 Ti; pkg123/pkg160 parity tests unchanged.
- [ ] `test_pkg292_env_cornell_red.py` full rung ≤ 1.05 red; both pkg55 gates pass at ±0.12 with margin recorded.
- [ ] `test_pkg292_hair_lobes.py` within ±5 % per lobe; pkg225 gate passes at ±15 % with the measured number < 5 %.
- [ ] Ladder doc complete; every fix attributed against the baseline build.

---

## Non-goals

- No new materials or lobes; no changes to the Disney/Principled CPU model unless the ladder convicts the CPU.
- No widening of any band.

---

## Progress

- [ ] #876 ladder + fix.
- [ ] #862 ladder + fix.
- [ ] #853 ladder + oracle + fix.

---

## Lessons

*(Fill in after the package is done.)*
