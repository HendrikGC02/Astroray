# pkg211 — Advanced dispersive-caustic convergence: per-bounce spectral MIS / spectral ray differentials (prototype-first)

**Pillar:** 3 (light transport / spectral rendering research)
**Track:** A
**Estimated effort:** L (research prototype → decide → productionize; multi-session,
CPU-first).
**Status:** open (filed 2026-08-19).
**Depends on:** the existing hero-wavelength + SMS spectral-MIS caustic path
(Hanika 2015). Best sequenced AFTER pkg206 (luminance-weighted hero proposal) so
the two variance levers are measured against a common, improved baseline — but not
hard-blocked by it.

## Goal

Astroray collapses to ONE hero wavelength per path at the first dispersive event.
In dispersive caustics this hero-per-path structure is the source of a
characteristic firefly/chromatic-noise pattern: a single wavelength carries the
whole path's colour, so the caustic converges slowly and noisily. Two research
techniques attack exactly this, and neither is in Astroray's corpus:

- **Spectral ray differentials — Elek et al. 2014** (CGF 33(4),
  DOI 10.1111/cgf.12418): track `dλ` (and `∂direction/∂λ`) along the ray so
  dispersion can be *filtered* instead of point-sampled, and concentrate wavelength
  samples where `|∂θ/∂λ|` is large (i.e. in the caustic, where dispersion actually
  spreads). "Dispersion-only-in-caustics" sampling.
- **Per-bounce spectral MIS — Petitjean & Bauszat 2018** (CGF, DOI 10.1111/cgf.13474,
  spectral gradient sampling) and **Pediredla et al. 2020** (ACM TOG,
  DOI 10.1145/3414685.3417793): re-sample λ *per dispersive bounce* with spectral
  MIS weights rather than committing to one hero for the whole path.

**This package is a prototype-first evaluation, not a commit-to-one-technique
build.** The deliverable of Stage 1 is a measured decision; Stage 2 productionizes
only the winner (or parks if neither beats the pkg206 baseline enough to justify
the register/complexity cost).

## Specification

### Stage 1 — diagnosis + prototype spike (CPU-first, may recommend PARK)

1. **Invoke `cite-algorithm`** and write a research note under
   `.astroray_plan/docs/` (a `pkg211-*-research.md`) covering: Elek 2014 (spectral
   ray differentials), Petitjean 2018 + Pediredla 2020 (per-bounce spectral MIS),
   and how each maps onto Astroray's `SampledWavelengths` / SMS caustic path. Cite
   Wilkie 2014 for the hero-MIS baseline. Identify a license-compatible reference
   implementation for the chosen technique (or state that only the paper exists and
   the math is ported from it).
2. **Instrument the baseline.** On the dispersive-prism / SMS spectral-caustic
   scene, quantify the current hero-per-path chromatic noise vs a high-spp
   reference (MSE / per-channel variance vs sample count). This is the number both
   candidates must beat. State the `.pyd` mtime.
3. **Prototype ONE technique CPU-only, behind a flag/build define** (the reviewer
   picks per the research note; **per-bounce spectral MIS is the higher-value
   default** because it directly targets the caustic firefly, with spectral ray
   differentials as the alternative if per-bounce MIS proves too invasive). Measure
   the same noise-vs-spp curve. **If it does not materially beat the pkg206
   baseline, recommend PARK and stop** — a well-argued negative result is a valid
   Stage-1 closeout (cf. pkg167 Part 2, pkg182 follow-up: falsified premises are
   acceptable outcomes, documented not buried).

### Stage 2 — productionize the winner (only if Stage 1 is positive; separate PR)

4. GPU port with the **mandatory register probe first** (memory
   `wavefront-shade-kernels-register-saturated`): per-bounce λ re-sampling adds
   per-hit live state, which historically spills the pinned shade kernel — the
   probe decides whether it fits the 254/3352 envelope or needs a
   `template<bool HasSpectralMIS>` isolation axis (same discipline as
   `HasPrincipled`/`HasPhotons`/`HasDispersion`). CPU+GPU byte-mirrored per the
   established convention. May still park at the GPU probe even if CPU was positive.

## Acceptance

### Stage 1 (this spec's primary deliverable)
- [ ] `cite-algorithm` invoked; research note lands in `.astroray_plan/docs/` with
  the Elek / Petitjean / Pediredla citations and the technique-selection rationale.
- [ ] Baseline hero-per-path chromatic-noise-vs-spp curve measured on the
  dispersive-caustic scene (LINEAR EXRs, seed-pinned, `.pyd` mtime stated).
- [ ] The prototyped technique's noise-vs-spp curve measured on the SAME scene; a
  clear GO / PARK recommendation with the measured delta. Unbiasedness checked
  (converged result matches the baseline within MC noise — render LINEAR with an
  upper bound).
- [ ] If GO: Stage 2 filed/scoped with the register-probe gate. If PARK: the
  negative result is documented in the note and STATUS.md, spec flipped to a
  parked/closed state.

### Stage 2 (only if GO)
- [ ] GPU register HARD gate satisfied or a justified isolation axis added; CPU↔GPU
  parity; CI green + RTX leg.

## Non-goals

- **Not both techniques** — Stage 1 picks one to prototype; the other stays a
  documented alternative unless the winner explicitly composes with it.
- **No wave-optics / Gaussian dispersion** (Steinberg & Pharr 2025, §6.8) — tracked
  as frontier, explicitly out of scope here.
- **No hero-proposal change** (pkg206) and **no reflection-companion change**
  (pkg210) — orthogonal levers.

## Provenance

Filed by the architect 2026-08-19 from the dispersion research report
(`...2026-08-19-cycles-dispersion-research.html` §6.4/§6.5, ranked recommendation
#5 — "the two research gaps most aligned with Astroray's caustic work"). Grounded
in the existing hero-collapse (`src/spectrum.cpp:102`) + SMS caustic path.
**Claude/careful-tier, prototype-and-measure-first** — this is exploratory
research with a legitimate PARK outcome, NOT well-specified open-model implement
work; route to Claude. Only Stage 2 (a proven, precisely-scoped port) could later
route to the open-model tier behind gates.
