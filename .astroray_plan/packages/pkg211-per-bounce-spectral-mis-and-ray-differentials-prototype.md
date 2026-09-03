# pkg211 — Per-bounce spectral MIS + spectral ray-differentials (prototype-first, PARK-legitimate)

**Pillar:** 3 (light transport / spectral rendering research)
**Track:** A
**Estimated effort:** M–L. Stage 1 (the deliverable) is M: one CPU-only prototype
+ a measured A/B on one scene. Stage 2 is L and CONDITIONAL — it only exists if
Stage 1 wins.
**Status:** open (re-scoped 2026-09-03; supersedes the 2026-08-19 filing whose
citations were wrong — see §Citations).
**Depends on:** pkg206 (luminance-weighted hero) — its `sampleImportance` IS the
baseline this package must beat. Not hard-blocked, but the A/B is meaningless
against the old uniform hero, so pkg206 must be the active baseline in the build
under test.
**Routing:** Claude-only, careful tier. This is prototype-and-measure judgment
with a legitimate negative outcome — NOT well-specified open-model implement work.
Only a GO'd Stage 2 (a proven, precisely-scoped GPU port) could later route to the
open-model tier behind gates.
**Research note:** `.astroray_plan/docs/pkg211-spectral-mis-research.md`
(web-verified; citations below corrected against it and re-spot-checked in this
session via Crossref).

---

## Goal + honest uncertainty

**What Astroray does today.** One hero wavelength is importance-drawn per path
(pkg206, `SampledWavelengths::sampleImportance`, `spectrum.h:115`); 3 companion
lanes ride along. At the FIRST wavelength-dependent (dispersive/volumetric) event
the path collapses to the hero alone — `terminateSecondary()` zeroes the secondary
pdfs (`spectrum.cpp:180-186`; GPU write-back `stage_advance.cu:975-990`,
`:1750-1759`). So a single wavelength carries the whole colour of every
multi-bounce dispersive path. That hero-per-path structure is the source of the
characteristic chromatic-firefly / slow-convergence pattern in dispersive caustics.

**What "per-bounce spectral MIS" is.** Instead of choosing the hero once at
primary generation and collapsing companions at the first dispersive hit,
RE-DECIDE (re-draw / re-weight) the wavelength sample at each dispersive bounce,
and combine the per-bounce sampling strategies via MIS so the estimator stays
unbiased. Concretely: each dispersive vertex becomes its own λ-sampling strategy;
the path's contribution is the MIS-weighted combination over the strategies that
could have produced it. This directly attacks the spot where hero-collapse throws
away spectral information — the second and later dispersive bounces.

**Why it MIGHT cut chromatic noise.** On multi-bounce dispersive paths (prism →
floor bounce → caustic), the single surviving hero after collapse means most
lanes contribute zero past the first dispersive event; variance in the caustic is
dominated by which wavelength happened to survive. Re-selecting λ at the bounce
that actually spreads dispersion, weighted by MIS, keeps more than one lane
carrying energy deeper into the path — in principle lower per-channel variance at
equal spp exactly where hero-per-path is weakest.

**Why it might NOT beat pkg206 (be honest).** The literature does not support a
strong prior here:

- There is **no published, peer-reviewed technique** named or matching "re-decide
  the hero per bounce + MIS across bounces." The research note (§0, §2) confirms
  the two sources the original filing leaned on were mis-cited and describe
  different families entirely (gradient-domain spectral sampling; refractive RTE).
- Wilkie 2014 ALREADY computes per-vertex joint MIS weights while keeping ONE hero
  across the path, and explicitly frames hero sampling as "a simplified and
  optimised version" of Radziszewski 2009's full per-strategy spectral MIS. In
  other words, the field converged ON hero-per-path AWAY from per-strategy MIS
  because the extra strategies cost more than they saved in the common case.
- At a Dirac dispersive interface Wilkie 2014 (Fig. 6) notes the method "falls back
  to single wavelength behaviour" — i.e. hero-collapse is a KNOWN, accepted
  degradation, not obviously a bug worth an expensive fix.
- pkg206 already spent much of the available chromatic-noise budget on the FIRST
  dispersive event. Per-bounce MIS only helps the residual on the SECOND+ bounce,
  which is a smaller slice of the total.

So the honest prior is: **PARK is the more likely outcome.** This package exists to
convert that intuition into a measured number, cheaply, before anyone touches the
register-saturated shade kernel.

---

## Citations (URL-backed; corrected and re-verified this session)

The original filing cited three sources that verification showed are NOT
per-bounce spectral MIS. Corrected set:

**Baseline (what we must beat):**
- Wilkie, Nawaz, Droske, Weidlich, Hanika. "Hero Wavelength Spectral Sampling."
  *Computer Graphics Forum* 33(4), 123–131, EGSR 2014. DOI 10.1111/cgf.12419.
  Crossref re-verified 2026-09-03 (title/authors/pages/DOI exact).
  Free author PDF: https://cgg.mff.cuni.cz/~wilkie/Website/EGSR_14_files/WNDWH14HWSS.pdf

**Per-vertex / per-strategy spectral MIS prior art (the real lineage):**
- Radziszewski, Boryczko, Alda. "An Improved Technique for Full Spectral
  Rendering." *Journal of WSCG* 17(1), 9–16, 2009. The original spectral MIS
  (each wavelength = a distinct sampling strategy, combined by MIS). Cited as
  `[RBA09]` inside Wilkie 2014.
  https://www.researchgate.net/publication/228938842_An_Improved_Technique_for_Full_Spectral_Rendering
- Evans & McCool. "Stratified Wavelength Clusters for Efficient Spectral Monte
  Carlo Rendering." *Graphics Interface* 1999 — precursor: propagate a cluster,
  split/discard at wavelength-dependent surfaces.

**Explicitly NOT the technique (corrections — do not cite as per-bounce MIS):**
- Petitjean, Bauszat & Eisemann 2018 (CGF, DOI 10.1111/cgf.13474) is spectral
  *gradient-domain* sampling — a different, competing variance-reduction family
  that COMPOSES with hero sampling. https://publications.graphics.tudelft.nl/papers/207
- Pediredla et al. 2020 (ACM TOG 39(6), DOI 10.1145/3414685.3417793) is "Path
  tracing estimators for refractive radiative transfer" — curved light paths in
  heterogeneous IOR media, unrelated to wavelength sampling.

**Ray differentials (for the separate sub-thread, §Spectral ray-differentials):**
- Igehy. "Tracing Ray Differentials." *SIGGRAPH '99*, 179–186.
  DOI 10.1145/311535.311555. Crossref re-verified 2026-09-03.
  Author PDF: https://graphics.stanford.edu/papers/trd_jpg.pdf
- Elek, Bauszat, Ritschel, Magnor, Seidel. "Spectral Ray Differentials."
  *Computer Graphics Forum* 33(4), 113–122, EGSR 2014. DOI 10.1111/cgf.12418.
  Crossref re-verified 2026-09-03. Tracks `∂direction/∂λ` and `dλ` along the ray
  to FILTER in the spectral domain. No public reference code found (paper-only;
  math ported from the paper).

---

## Stage 1 — the prototype + measurement plan (the whole point)

Stage 1 is the deliverable. It produces a GO/PARK decision, nothing else ships.

### S1.1 — Prototype (CPU-only, behind a flag)
- Add `SampledWavelengths::resampleHeroPerBounce(float u, const HitRecord& rec)`
  (CPU only) invoked at a dispersive BSDF draw INSTEAD OF `terminateSecondary()`.
  It re-draws the hero from the same luminance-weighted logistic density pkg206
  uses (reuse the `heroCdf` machinery, `spectrum.cpp:140`), re-weights the per-lane
  pdfs to the density at each lane's own wavelength (Wilkie 2014 §4.1), and
  accumulates the per-bounce MIS weight product along the path (balance heuristic
  over {previous-vertex strategy, this-vertex strategy}).
- Gate behind a flag/build define (`--spectral-mis-per-bounce`, default OFF). The
  default path stays byte-identical to pkg206.
- **Do NOT touch the GPU shade kernel in Stage 1.** The register probe is a
  Stage-2 gate only. Keeping Stage 1 CPU-only is what makes PARK cheap.

### S1.2 — Scene
- The multi-bounce dispersive-caustic configuration from the existing suite:
  `tests/test_sms_caustic_spectral.py` / `tests/test_spectral_prism.py` /
  `tests/test_prism_caustic_rainbow.py`, arranged as prism + floor bounce feeding
  the caustic (the config where hero-per-path chromatic fireflies dominate — the
  second dispersive event is the one per-bounce MIS attacks). Same scene pkg206
  re-baselined, so the A/B is apples-to-apples.

### S1.3 — Metric (per-channel variance at fixed spp; LINEAR EXR, seed-pinned)
- Render LINEAR (`apply_gamma=False`) — a gamma furnace cannot detect energy gain
  and clamps chroma (memory: gamma-furnace-hides-energy-gain). State the `.pyd`
  mtime vs `git log -1 HEAD` before any render (build-staleness discipline).
- Compute, at a fixed low spp, on the SAME seed: (a) per-channel variance / MSE vs
  a high-spp reference render, and (b) a chromatic-noise proxy — per-pixel chroma
  RMSE / hue-spread, matching pkg206's own reported "−42% RMSE / −38% chroma"
  methodology so the numbers are directly comparable.
- Plot A/B noise-vs-spp curves for {pkg206 hero, per-bounce MIS} on one seed +
  scene. Pin the seed to a nonzero value (seed 0 = random sentinel — memory:
  seed-zero-is-random-sentinel).

### S1.4 — Unbiasedness guard (the half-blind trap)
- The converged (high-spp) per-bounce-MIS render MUST match the pkg206 hero render
  to within MC noise on a per-channel mean-ratio band (windowed SSIM is the WRONG
  gate for independent RNG streams — memory: ssim-wrong-gate-for-independent-rng;
  use per-channel mean-ratio). Reuse `_linear_render_guard.py`. Any unbiasedness
  failure is an automatic PARK regardless of the variance number.

### S1.5 — GO / PARK criterion (explicit, measured)
- **GO** only if per-bounce MIS beats pkg206 by a MATERIAL margin: **≥ 10%
  relative reduction in per-channel variance AND chroma RMSE at equal spp** on the
  dispersive-caustic scene, AND the unbiasedness guard passes.
- **PARK** (a first-class, well-defined exit — NOT a failure) if the reduction is
  < 10% at equal spp, OR any unbiasedness failure, OR the CPU prototype shows the
  gain is confined to a regime too narrow to justify the Stage-2 register cost. A
  well-argued negative result documented in the note + STATUS.md is a valid,
  complete Stage-1 closeout (precedent: pkg167 Pt.2, pkg182 follow-up — falsified
  premises are acceptable, documented outcomes). On PARK, flip this spec to
  `parked` with the measured delta recorded; Stage 2 is never filed.

---

## Stage 2 — productionize the winner (CONDITIONAL on Stage 1 GO; separate PR)

Only exists if S1.5 returned GO. Design sketch so the GO decision knows the cost:

- **Where the hero is chosen today:** `sampleImportance` (`spectrum.h:115`,
  `spectrum.cpp:103-186`) on CPU; `sampleImportanceWavelength`
  (`stage_init.cu:166-186`, called from primary-ray gen `:278`, pdfs persisted to
  `PathState` SoA `lambda_pdf_0..3` `:347-350`) on GPU.
- **Where the per-bounce re-decision hooks:** the BSDF draw inside
  `stageShadeBucketedKernel` (`stage_advance.cu:2072`), replacing the
  hero-collapse write-back at the dispersive branch (`:975-990`, `:1750-1759`).
- **Register-cost concern (mandatory FIRST gate):** the shade fleet is pinned at
  REG 254 / STACK 3352 / CONSTANT[0] 1700 and MUST stay byte-identical for the
  non-dispersive fleet (memory: wavefront-shade-kernels-register-saturated; PR #620
  probe). Per-bounce λ re-selection adds per-hit live state at the BSDF draw — the
  MOST invasive place possible. Almost certainly needs a `template<bool
  HasSpectralMIS>` isolation axis, mirroring the existing
  `<HasPrincipled,HasPhotons,HasDispersion,HasProgram,HasNormalPerturb>` axes
  (`stage_advance.cu:2633-2641`), routed through the `__constant__` side-table /
  `__noinline__` runtime-flag pattern proven zero-cost on pkg223/pkg224 (memories:
  shade-axis-side-table-avoids-spill, noinline-runtime-flag-avoids-shade-spill).
- **Second, independent PARK gate:** even after a positive CPU S1, the GPU
  register probe can PARK Stage 2 if the axis spills the fleet and cannot be
  isolated within the 254/3352 envelope.
- CPU↔GPU byte-mirror per the established convention; CI green + RTX leg at close.

---

## Spectral ray-differentials — SEPARATE sub-thread (recommend SPLIT OUT)

Elek 2014 (spectral ray differentials) tracks `∂direction/∂λ` + `dλ` along the ray
to FILTER dispersion in the spectral domain rather than point-sample it, and to
concentrate wavelength samples where `|∂θ/∂λ|` is large (inside the caustic). It
is a genuinely DIFFERENT mechanism from per-bounce MIS — a filtering/importance
scheme, not a per-vertex strategy-combination.

**Recommendation: do NOT bundle it into pkg211. Split it out.** Reasons:
- Different mechanism, different measurement, different failure modes — bundling
  doubles Stage 1's surface area and blurs the GO/PARK signal.
- It carries the SAME register pressure as per-bounce MIS (adds `∂dir/∂λ` + `dλ`
  live state to the same REG-254 kernel), so it does not amortize the cost.
- No public reference code (paper-only), so it's a from-scratch math port —
  higher Stage-1 cost than the MIS prototype which reuses pkg206's `heroCdf`.
- It is arguably the LOWER-value of the two for Astroray's caustic focus: it wins
  most where dispersion is smoothly filterable, whereas Astroray's pain is
  discrete chromatic fireflies in SMS caustics.

Action: this spec drops ray-differentials from scope. If desired, file it as a
sibling `pkg211b-spectral-ray-differentials` prototype-first spec with its own
scene (smooth glass slab / thick prism where `|∂θ/∂λ|` filtering pays) and its own
PARK criterion. Left unfiled here — one open question for the owner (below).

---

## Acceptance

### Stage 1 (this spec's primary deliverable)
- [ ] CPU-only `resampleHeroPerBounce` prototype behind `--spectral-mis-per-bounce`,
  default path byte-identical to pkg206.
- [ ] Baseline pkg206 hero noise-vs-spp curve on the dispersive-caustic scene
  (LINEAR EXR, seed pinned nonzero, `.pyd` mtime stated).
- [ ] Per-bounce-MIS noise-vs-spp curve on the SAME scene/seed; A/B plotted.
- [ ] Unbiasedness guard passes (per-channel mean-ratio band; `_linear_render_guard.py`).
- [ ] Explicit GO/PARK per S1.5 with the measured variance + chroma delta.
- [ ] If GO: Stage 2 filed/scoped with the register-probe gate. If PARK: negative
  result documented in the research note + STATUS.md; spec flipped to `parked`.

### Stage 2 (only if GO)
- [ ] GPU register HARD probe satisfied within 254/3352, OR a justified
  `template<bool HasSpectralMIS>` isolation axis added; CPU↔GPU parity;
  CI green + RTX leg.

## Non-goals
- **Not both techniques.** Ray differentials are split out (see above); this spec
  is per-bounce MIS only.
- **No wave-optics / Gaussian dispersion** (Steinberg & Pharr 2025 §6.8) — frontier,
  out of scope.
- **No pkg206 hero-proposal change** and **no pkg210 reflection-companion change** —
  orthogonal levers, held fixed as the baseline.

## Open question for the owner
- Split ray-differentials into a sibling `pkg211b`, or drop it entirely? (My read:
  file it low-priority behind pkg211's own GO/PARK, since it shares the same
  register wall and has weaker fit to the firefly problem.)

## Provenance
Re-scoped by the architect 2026-09-03 from the web-verified research note
(`.astroray_plan/docs/pkg211-spectral-mis-research.md`), correcting the three
mis-citations in the 2026-08-19 filing. Grounded in the live hero-collapse path
(`spectrum.cpp:180`) + SMS caustic path (`photon_caustic.cu:251`). Claude/careful
tier, prototype-and-measure-first, **PARK is a first-class expected outcome.**
