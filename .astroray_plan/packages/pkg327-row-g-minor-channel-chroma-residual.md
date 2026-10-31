# pkg327 — Row (g) minor-channel chroma residual: attribution, Mitsuba arbitration, per-channel divergence

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 2 sessions (~7 h): Phase A 1 session (CPU Blender legs + Mitsuba CPU), Phase B ~3 h; Opus session if Phase A finds an engine bug
**Depends on:** pkg307, pkg310

---

## Goal

Before: four production scenes fail row (g) on the channel their albedo has least of. curves_geometry inner_backface r reads
0.84/0.85, wood b 0.91-0.96 in four ROIs, car_paint CPU lit_front b 0.92 and upper_flake b 0.96, pbr_group lower b
0.92/0.94. All are low on both backends with CPU ≈ GPU, and nobody knows which part is spectral transport and which is an
engine bug. light_path floor_near r 0.974 (#1199) and wood grain_center r 0.958 are unexplained major-channel misses.
After: every one of these channels has a measured cause.
- Spectral behaviour confirmed by an independent spectral renderer → a per-channel `expected_divergence` pin that cites the
  arbitration artefact.
- Any other cause → an engine fix or an issue.
Row (g) then counts what remains.

---

## Context

Row (g) needs 6/8 on CPU and GPU and reads 2/8. #1141 measured the mechanism on curves. The spectral product ρ(λ)² of a
near-gamut-edge cyan has a negative red tristimulus that the film clips, while Cycles' RGB product 0.05² stays positive.
Grey albedo matches (0.997), and one bounce under a white world is exact. The other scenes show the same signature (minor
channel, a few percent, both backends), but nobody has measured it there. #767's open candidate, HDRI illuminant
upsampling, could add a term. Without this package curves cannot pass at any engine cost, and the other cluster scenes have
no fix to aim at. Owner rule 2026-09-29 (memory `physics-over-cycles-look-parity`): document physical divergences, never
mimic Cycles. Owner 2026-10-31 (`architect-plan-2026-11-01.md` §5, answer 5): pin a channel as an expected divergence
when Mitsuba spectral reproduces the shift; an unconfirmed shift gets an engine fix.

---

## Evidence

- 2026-10-31: re-score of `%LOCALAPPDATA%\astroray-evidence\2026-10-31\g\renders` (build `f477f02+20261031T110236Z`,
  seed 278, 64 spp). Cycles means show the failing channel is the smallest every time: curves inner_backface
  (0.031, 0.241, 0.296); wood grain_center (0.487, 0.244, 0.082); car_paint lit_front (0.632, 0.080, 0.056); pbr_group lower
  (0.228, 0.059, 0.024). light_path floor_near (0.739, 0.440, 0.555) fails on its largest channel, r.
- 2026-10-18: #1141. Bowl inner_backface R ratio vs albedo R: 0.05 → 0.117, 0.10 → 0.656, 0.20 → 0.925, 0.40 → 1.013.
  Astroray R = 0 on 50 % of ROI pixels. Evidence `astra_run/2026-10-18/i1117/partB_evidence.txt`.
- 2026-10-31: the observer is CIE 1931 2° (`include/astroray/spectrum.h` `cieCmf1931_2deg`), so #767's observer candidate
  is already closed.

---

## Reference

- Mechanism and upsampling: Jakob & Hanika 2019, "A Low-Dimensional Function Space for Efficient Spectral Upsampling"
  (Astroray LUT and Mitsuba 3 both use it). Memory `spectral-upsample-nonlinearity-scaled-bsdf`.
- Arbitration harness to extend, not fork: `benchmarks/reference_corpus/arbitration/{build_arbitration.py,mitsuba_scenes.py,manifest.json,calibration.json}` and `mc_tolerance.py --suite arbitration` (pkg307 Phase 2). Mitsuba venv
  `C:/Users/hgcom/tools/venv-mitsuba`.
- Counterfactual controls: the pkg323 control-kind mechanism in `benchmarks/blender_parity/render_leg.py` (receipts,
  no-op guards).
- Divergence pins today: `mc_tolerance.score_material` (whole-ROI `expected_divergence`), `gates_v2.toml` examples,
  `benchmarks/reference_corpus/README.md` "Documented divergences".
- Issues: #1141, #1199, #767 (closed; the test recipe is in its comments), #1024.

---

## Prerequisites

- [ ] Lanes #1153 and #1178 merged, or their branches measured, so car_paint numbers are taken on the post-lane engine.
- [ ] Staged CPU addon at main HEAD (`dist/astroray`); Mitsuba venv imports `scalar_spectral` and `scalar_rgb`.
- [ ] `python scripts/project_index.py query "arbitration"` read; `scripts/README.md` checked (CLAUDE.md §5b).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `.astroray_plan/docs/pkg327-chroma-residual-attribution.md` | Per-channel attribution table (variant ratios, Mitsuba ratios, verdict, evidence paths), with contact sheets referenced, not committed |
| `tests/test_pkg327_channel_divergence.py` | Fast tests: a per-channel pin moves only its channels; every pin names an arbitration artefact that exists; un-pinned channels of the same ROI still compare to Cycles |

### Files to modify

| File | What changes |
|---|---|
| `benchmarks/blender_parity/render_leg.py` | Two attribution control kinds next to the pkg323 kinds: `albedo_grey` (named material's Base Color → equal-luminance grey; no-op guard) and `world_flat_white` (world → constant white of equal mean luminance); receipts as pkg323 |
| `benchmarks/reference_corpus/arbitration/mitsuba_scenes.py` | `PARAMS` gains proxy scenes: `arb_chroma_bowl` (the #1141 bowl, albedo (0.05, 0.4, 0.55), white world) and `arb_chroma_warm` (wood-like albedo (0.49, 0.24, 0.08) floor + occluder, white world and one coloured-sky variant); renders under `scalar_spectral` and `scalar_rgb` (CPU variants; never `cuda_*` while the lead holds the GPU) |
| `benchmarks/reference_corpus/arbitration/build_arbitration.py` | Builds the same proxies for the Cycles and Astroray legs from the shared `PARAMS` |
| `benchmarks/reference_corpus/arbitration/manifest.json` | Proxy entries |
| `benchmarks/reference_corpus/mc_tolerance.py` | `score_material`: `expected_divergence` may carry `channels = [...]` and must carry `arbitration = "<repo path>"`. Listed channels pin to the leg's own N-seed mean; the rest stay on Cycles. Whole-ROI pins in `gates_v2.toml` keep working unchanged |
| `benchmarks/reference_corpus/gates_production.toml` | Phase B: per-channel pins for confirmed channels only, with seed-calibrated `cpu_mean`/`gpu_mean`/`*_pin_tol` from the existing calibration path |
| `benchmarks/reference_corpus/provisional_production.toml` | xfail reasons re-pointed to the attribution doc / issues |
| `benchmarks/reference_corpus/README.md` | Documented-divergence rules: per-channel, arbitration artefact required, list of pinned channels |

### Key design decisions

#### Phase A: attribution (evidence only, no engine or gate change)

For each target channel (the cluster channels above, plus light_path floor_near r and wood grain_center r as controls),
render CPU Astroray and CPU Cycles at the gate seed and spp, with 4 seeds each, for: baseline, `albedo_grey`,
`world_flat_white`. Reading:
- residual gone under `albedo_grey` → chroma-dependent;
- under `world_flat_white` → separates albedo multi-bounce from illuminant upsampling;
- neither moves it → a non-spectral engine cause, so file an issue and stop for that channel.

Then the Mitsuba proxies: the arbitration ratio is `(Mitsuba scalar_spectral / Mitsuba scalar_rgb)` on the proxy ROI,
compared with `(Astroray / Cycles)` on the same proxy built from the same `PARAMS`. Agreement within the combined MC band
counts as "spectral behaviour confirmed". Mitsuba uses the same Jakob-Hanika upsampler in independent code, so this
proves agreement with a reference spectral renderer, not that the upsampled spectrum is the true one (memory
`clean-room-oracle-is-self-consistency-not-ground-truth`). The doc says so. GPU legs are not needed in Phase A because the
cluster reads CPU ≈ GPU.

#### Phase B: gate treatment

- A channel is pinned when Phase A shows it chroma-dependent and the Mitsuba ratio agrees (owner 2026-10-31; no further
  sign-off). Pin per channel, never per ROI.
- A shift Mitsuba does not reproduce (e.g. an illuminant-upsampling term) gets an engine fix, per the owner: file it and
  route it to an Opus lane that cites the method before any code (cite-algorithm skill). Do not pin it.
- Never widen a tolerance or clamp to make a channel pass.

---

## Acceptance criteria

- [ ] Attribution doc covers every target channel with variant ratios on 4 seeds, the Mitsuba ratio for the proxies and a
      verdict (spectral-confirmed / engine bug + issue / unexplained).
- [ ] `tests/test_pkg327_channel_divergence.py` passes. `tests/test_production_corpus.py -k "parity or silent"` on CPU and
      GPU (lead's lock) shows every pinned channel inside its pin band, and every non-pinned channel still compared to
      Cycles.
- [ ] Row (g) re-run recorded in `stage0-gate-scoring-*.md` with before/after counts per scene and backend.
- [ ] No pin without an `arbitration` path that exists in the repo or the evidence manifest; no whole-ROI pin added to
      `gates_production.toml`.

---

## Non-goals

- Do not change the upsampler, the film gamut handling (#1024) or the observer in this package; the engine fix for an
  unconfirmed shift gets its own issue and lane.
- Do not touch shader_stack (its 1/n² Cycles reference is a separate item) or the GPU-only residuals (light_path floor_far,
  #1156).
- Do not run Mitsuba `cuda_*` variants or GPU Astroray legs outside the lead's lock.

---

## Progress

- [ ] Control kinds + proxies + attribution legs (Phase A)
- [ ] Attribution doc
- [ ] Per-channel pins for confirmed channels, issues for unconfirmed ones, tests, row (g) re-run (Phase B)

---

## Lessons

*(Fill in after the package is done.)*
