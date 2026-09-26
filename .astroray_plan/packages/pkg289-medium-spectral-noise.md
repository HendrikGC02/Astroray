# pkg289 — Chromatic noise in scattering media and hero-λ collapse propagation (#913, #917, #904 gap)

**Pillar:** 2
**Track:** A
**Status:** open
**Estimated effort:** 2 sessions (~6 h): 1 diagnostic ladder, 1 fix + tests
**Depends on:** pkg270, pkg268

---

## Goal

Before: the showcase fog light shaft on CPU at 64 spp shows strong green
colour speckle that Cycles does not (#913); the caustic walk's hero-λ collapse
is never propagated to the main path's wavelengths (#904 gap); the
path-guiding brightness snapshot can be taken before a collapse and compared
after it (#917). After: a measured per-channel variance ladder (CPU vs GPU vs
Cycles on the shaft ROI, spp 16→256) names the mechanism; medium free-flight,
transmittance and NEE use a consistent spectral-MIS estimator across all four
wavelengths (pbrt-v4 `SampleT_maj` + `r_u`/`r_l` form or the existing
one-sample channel MIS, chosen by the ladder); every collapse site propagates
to the path's `lambdas`; guided variance on a dispersive scene never exceeds
unguided.

---

## Context

Media are foundational for Pillar 4 (nebulae are scattering media lit by
narrow sources) and the volumes showcase is a README image. A colour speckle
that does not average at 4096 spp on GPU but does on CPU (or vice versa) is a
CPU/GPU estimator difference, which pkg284's `v2_media` scene must gate.
Grouping the three items: all are "which wavelengths does this estimate
belong to" bugs in the same integrator file.

---

## Evidence

- 2026-09-26 (#913): `astra_run\f908\sc_compare_cycles_before_after.png` — green speckle in the shaft, CPU 320×180 64 spp; GPU 4096 spp final much cleaner.
- `include/raytracer.h:3459-3475`: free-flight samples one channel `ch`, pdf = mean over channels of σ_t·Tr (one-sample spectral MIS); `:3495-3523` medium NEE uses `worldTransmittanceSpectral` (full σ_t) and clamps at `bounce`.
- 2026-09-25 (#904): `pathTraceSpectralCaustic` collapses `walkLambdas` without propagating to the main path.
- 2026-09-26 (#917): `Csnap`/`betaSnap` in guide training taken before a collapse.

---

## Reference

- Wilkie, Nawaz, Droske, Weidlich, Hanika 2014, "Hero Wavelength Spectral Sampling" (EGSR) — spectral MIS over the 4 lanes.
- pbrt-v4 `src/pbrt/integrators.cpp` `VolPathIntegrator::Li`/`SampleLd` (Apache-2.0): `T_maj`, `r_u`, `r_l` pdf-ratio tracking, `SampledWavelengths::TerminateSecondary()` on chromatic interactions.
- Kutz, Habel, Li, Novák 2017, "Spectral and decomposition tracking".
- `.astroray_plan/docs/pkg270-spectral-tracking-volume-emission-research.md`, `pkg268-volume-transport-research.md`.
- Cycles `kernel/integrator/shade_volume.h` (RGB; `volume_integrate_heterogeneous` with per-channel `channel` selection via `volume_sample_channel`) — the reference behaviour is RGB one-channel MIS, so Cycles' speckle floor is the target.
- Memory: `adaptive-sampling-colour-blind-stop-metric`, `mc-noise-vs-deterministic`.

---

## Prerequisites

- [ ] PR #916 (#908 fire fix) merged so the volumes showcase is the current baseline.
- [ ] Batch AC (#912) merged (GPU medium emitter excess would confound the GPU leg).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg289_medium_chromatic_variance.py` | Shaft ROI per-channel variance vs spp (16/64/256) CPU and GPU on a reduced showcase-volumes fixture; asserts variance ∝ 1/spp per channel (slope −1 ± 0.15) and G/R variance ratio within 1.5× of Cycles' at 64 spp (Cycles reference rendered once via `render_leg.py`, committed as a number). |
| `tests/test_pkg289_collapse_propagation.py` | Dispersive glass inside fog: a collapse inside the caustic walk leaves the main path's `lambdas` with `secondaryTerminated`; guided render variance ≤ unguided on the same scene (#917). |
| `.astroray_plan/docs/pkg289-medium-chromatic-noise-ladder.md` | The ladder results (rung, number, verdict) and the chosen estimator. |

### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` | Per the ladder: (a) if the free-flight/NEE pdfs are inconsistent across lanes, move to pbrt-v4's `r_u`/`r_l` ratio tracking for homogeneous fog and the grid medium; (b) if a chromatic interaction (σ_s(λ) with a narrow lamp SPD) is the cause, terminate secondaries there (`SampledWavelengths::terminateSecondary`) like pbrt-v4; (c) if the speckle is the clamp at `bounce` on medium NEE, align with pkg290. |
| `src/gpu/wavefront/stage_advance.cu` | Byte-mirror the chosen estimator (world fog). |
| `src/gpu/wavefront/stage_volume_hetero.cu` | Byte-mirror the chosen estimator (grid medium). |
| `plugins/integrators/spectral_path_tracer.cpp` | `pathTraceSpectralCaustic`: propagate `walkLambdas` collapse to the caller's `lambdas` (#904 gap); guide training stores spectra in `GuideVtx` and evaluates with the final `lambdas` at replay (#917). |

### Key design decisions

- **Ladder before fix.** Rungs: (1) variance vs spp per channel CPU/GPU/Cycles; (2) fog σ_s achromatic vs chromatic A/B; (3) lamp SPD white vs narrow; (4) NEE off; (5) clamp off; (6) hero-only (kSpectrumSamples=1 build flag) to see whether secondaries add or remove variance. The first rung that removes the speckle names the mechanism; write it down before coding.
- **Do not add a new tracking scheme unless rung 2/6 implicate lane inconsistency**; the existing one-sample channel MIS is Cycles' own method.
- **Collapse propagation** is a contract: any function that collapses a `SampledWavelengths` copy must return it; add an assert in debug builds that the path's `lambdas` never has more live lanes than any spectrum multiplied into `throughput`.

---

## Acceptance criteria

- [ ] Ladder doc names the mechanism with a number per rung.
- [ ] `test_pkg289_medium_chromatic_variance.py` passes CPU and GPU; showcase volumes shaft at 64 spp visually free of green speckle (side-by-side saved).
- [ ] `test_pkg289_collapse_propagation.py` passes; guided ≤ unguided variance.
- [ ] Corpus `v2_media` ROI ratios unchanged within tolerance (bias-free change) or re-pinned with attribution.
- [ ] Shade kernel REG/STACK unchanged or delta justified.

---

## Non-goals

- No multi-scatter approximation, no volume motion blur (pkg272).
- No change to Principled Volume emission (landed in #908).
- #904's access violation is Batch AC's; this package only closes the two "gaps" listed in #904.

---

## Progress

- [x] Ladder rungs 1–6 + doc (2026-09-27): cause is medium NEE only at analog scatter vertices, not chromatic lanes; see `docs/pkg289-medium-chromatic-noise-ladder.md`.
- [ ] Fix + GPU mirror: deferred by the lead to the equiangular direct-light follow-up; `test_913_shaft_variance_vs_cycles_*` is xfail(strict).
- [x] Collapse propagation (#904, efc9f89a) + guide snapshot (#917).

---

## Lessons

*(Fill in after the package is done.)*
