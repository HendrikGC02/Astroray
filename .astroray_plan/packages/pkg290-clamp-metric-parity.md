# pkg290 — Firefly clamp removes 3–5× more energy than Cycles in media (#884)

**Pillar:** 2
**Track:** A
**Status:** open
**Estimated effort:** 1 session (~3 h) + GPU build
**Depends on:** pkg144

---

## Goal

Before: with Blender's default `sample_clamp_indirect = 10`, the geometry_zoo
volume cabinet renders 0.92 of Cycles (clamp off: 0.99); the clamp removes
9–10 % of the cabinet's energy on Astroray vs 2 % on Cycles, 21 % vs 5 % on the
scatter cube, and 3/5/7.5 % (blue-heavy) vs 0 % on the Principled cube. After:
a per-sample contribution histogram A/B against Cycles identifies whether the
excess is the clamp metric (Astroray XYZ Y vs Cycles Σ|RGB|) or spikier
spectral per-sample contributions; the metric is aligned with Cycles'
`film_clamp_light`; if spectral spikiness remains, the clamp is applied to the
RGB-projected contribution after lane averaging so that its bias matches
Cycles' within 2 % on the three cabinet ROIs.

---

## Context

The clamp is on by default in every Blender scene, so this bias sits in
every parity number involving media or bright indirect light. It is a
bounded, well-instrumented item (Batch U left `vb4_clamp_effect.txt`) and a
prerequisite for pkg284's `v2_media` gates, which would otherwise have to run
clamp-off and miss what users see.

---

## Evidence

- 2026-09-25 (#884): `astra_run\batchU\u842\vb4_clamp_effect.txt` — cabinet 0.921/0.915/0.908 clamp-on vs 0.991/0.990/0.994 clamp-off; energy removed Cycles 2 % vs Astroray 9–10 %.
- `include/raytracer.h:2686-2716`: `clampContribSpectral` clamps `toXYZ(lambdas).Y` against the limit; Cycles clamps `reduce_add(fabs(L))` (sum of RGB).
- `src/gpu/gpu_spectral_tables.h:223` `gpu_clampContribMW` is the GPU twin.

---

## Reference

- Cycles `intern/cycles/kernel/film/light_passes.h` `film_clamp_light` (Apache-2.0): `sum = reduce_add(fabs(L)); if (sum > limit) L *= limit/sum`.
- Cycles `kernel/integrator/shade_surface.h` / `shade_volume.h` call sites (clamp applied per contribution, bounce-indexed).
- `.astroray_plan/docs/pkg144-firefly-clamp-research.md`, `issue860-emission-hit-clamp-attribution.md`.
- Wilkie et al. 2014 (hero-wavelength lane variance is the spectral-spikiness candidate).

---

## Prerequisites

- [ ] PR #916 merged (medium NEE respects NEE flag, #877) so the clamp A/B is not confounded.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg290_clamp_energy_parity.py` | Cabinet fixture (geometry_zoo cabinet crop or a 3-cube reduction): clamp-removed fraction Astroray vs Cycles per ROI, |Δ| ≤ 2 points at `sample_clamp_indirect=10`, CPU and GPU; a white-furnace slab shows the clamp removes 0 % at limit 10 for both engines. |
| `scripts/dev/clamp_histogram.py` | One-off: per-sample contribution histograms (Y and Σ|RGB|) for Astroray, and Cycles via a `sample_clamp_indirect` sweep (1, 3, 10, 30, off) since Cycles exposes no per-sample dump; deleted when the package closes (§5b one-off rule). |

### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` | `clampContribSpectral`: metric = Σ|RGB| of the contribution's RGB projection (`toRGB(lambdas)`), matching Cycles; if the histogram shows the spectral estimate itself is the spike source, apply the clamp to the lane-averaged RGB projection and scale the spectral contribution by the same factor (documented fork below). |
| `src/gpu/gpu_spectral_tables.h` | `gpu_clampContribMW` mirrors the CPU metric byte-for-byte. |
| `tests/test_pkg144_firefly_clamp_direct_indirect_split.py` | Re-pin anything calibrated on the Y metric, with attribution. |
| `tests/test_pkg230_gpu_clamp_parity.py` | Same; CPU/GPU byte-consistency stays. |

### Key design decisions

- **Metric first.** A white contribution of luminance Y has Σ|RGB| ≈ 3Y, so Cycles clamps a white spike at Y ≈ 3.3 where Astroray clamps at Y = 10; for saturated blue, Σ|RGB| ≈ Y/0.07, the other way. The Principled cube's blue-heavy loss says the metric matters; the histogram says how much.
- **Fork (a):** metric change closes the gap to ≤ 2 points → done.
- **Fork (b):** spectral per-sample spikiness dominates (4-lane estimate of a smooth RGB value has higher kurtosis than Cycles' RGB sample). Then clamp on the RGB projection of the full 4-lane contribution (already what `toXYZ` does) but compute the limit test on the *expected* RGB (lane average of per-lane RGB projections), which reduces false clamps without changing the unclamped estimator. Record the choice in the research doc.
- **No new knobs.** Blender's two clamp values remain the only inputs.

---

## Acceptance criteria

- [ ] Histogram A/B saved under `test_results/pkg290/` with the fork decision written in `pkg144-firefly-clamp-research.md` (appended section).
- [ ] `test_pkg290_clamp_energy_parity.py` passes CPU and GPU (≤ 2 points on each cabinet ROI; furnace 0 %).
- [ ] geometry_zoo cabinet clamp-on ratio ≥ 0.97 of Cycles on five seeds (was 0.92).
- [ ] CPU/GPU clamp parity test (pkg230) still passes byte-consistent.

---

## Non-goals

- No adaptive/denoise interactions; no change to clamp defaults.
- No change to which contributions are clamped (bounce indexing from #860 stays).

---

## Progress

- [ ] Histograms + fork decision.
- [ ] Metric change CPU + GPU + tests.
- [ ] Re-pins.

---

## Lessons

*(Fill in after the package is done.)*
