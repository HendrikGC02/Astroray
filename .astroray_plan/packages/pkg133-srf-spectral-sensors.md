# pkg133 — SRF spectral sensors (Mitsuba `specfilm` — detector QE × filter curves)

**Pillar:** 2 (spectral core) — **Pillar-4-adjacent** (activates the astronomical-detector story)
**Track:** A (SRF distribution build + wavelength-importance-sampling change is CPU-gated; wavefront spectral leg verified on RTX)
**Codex-paste-ready:** no (touches the hero-wavelength-aware spectral sampling pdf + film accumulation — spectral-core surgery, needs care)
**Status:** superseded — merged into pkg51 (instrument pipeline design, 2026-09-22 planning session); implementation lands as pkg51 Phase 1
**Estimated effort:** M (2–3 sessions per the research doc — the SRF distribution build is simple CDF inversion; the sampling-pdf + film changes are the delicate part)
**Depends on:** the spectral wavelength sampler (Pillar-2 core, already present — hero-wavelength per Wilkie 2014). **Pillar-4-adjacent dependency note:** this is the *render-time* half of the paused **pkg51** telescope post-process — it activates when the owner lifts the Pillar-4 pause **or** ships standalone as a spectral-camera feature. Implementation lands as pkg51 **Phase 1** when pkg51 resumes.

---

## Goal

**Before:** Astroray samples path wavelengths uniformly across the band and weights
at the end. A JWST/NIRCam-style channel (filter throughput `T(λ)` × detector `QE(λ)`)
is narrow, so uniform sampling wastes most samples outside the channel's sensitivity
and leaves narrow-band output noisy. There is no per-instrument-channel output.

**After:** Port Mitsuba 3's **`specfilm`** (BSD-3, verified): the film takes N named
**Sensor Response Functions** (one per output channel, built from independently
retained `T(λ)` and `QE(λ)`), builds a combined continuous distribution over all
SRFs, and **importance-samples path wavelengths where the instruments are actually
sensitive** instead of uniformly. Output is wavelength-resolved raw bins handed to
pkg51 Phase 2 for chromatic PSF-before-integration, plus named SRF layers. Phase 1
emits **unbiased relative radiance accumulation with provenance** — not calibrated
photon/electron/ADU statistics, blocked on pkg243 Phase 2 — with far lower spectral
noise in narrow bands.

---

## Evidence

- 2026-09-22: rewritten in the planning session (stage-plan-2026-09-22.md §4); previous text superseded.
- 2026-09-22: Codex Terra review defects applied (planning session).

---

## Design sketch (cite the research doc; don't duplicate it)

Full source record: `.astroray_plan/docs/2026-07-other-engines-research.md` §3.

- **T(λ) and QE(λ) stay separate:** store filter throughput `T(λ)` and detector
  quantum efficiency `QE(λ)` independently (Stage-3 plan, `stage-plan-2026-09-22.md`;
  pkg51 applies them separately in μ_e). A channel's SRF is `SRF_k(λ) = T(λ)·QE(λ)`,
  tabulated as a Mitsuba nested `spectrum`, used **only** as the Phase-1 importance
  proposal and response weight — never as the retained quantity.
- **Wavelength-resolved bins + named outputs:** never collapse to one value per SRF.
  Retain raw radiance in wavelength bins across the 360–830 nm grid (default 5 nm;
  frozen 2026-09-22, lead may adjust), and additionally emit the named SRF layers
  (alphabetical, per `specfilm`). Hand-off to pkg51 Phase 2: the raw bins are
  convolved with the per-band PSF **before** spectral integration — a broadband SRF
  image cannot receive the correct chromatic PSF afterwards. Halving the bin width
  must change pkg51 Phase-3 μ_e by < 1 % (bin-convergence test).
- **Combined proposal (normalized support):** `q(λ) = Σ_k SRF_k(λ) / ∫Σ_k SRF_k dλ`
  over the union of the SRF supports, zero elsewhere — a proper PDF with `∫q = 1`,
  built by inverse-transform sampling (CDF inversion).
- **Composition with the hero-wavelength PDF:** the hero wavelength draws from `q`;
  its companion offsets keep the existing Wilkie-2014 shifts. A shift can move a
  companion off `q`'s support, so the sampler uses the mixture
  `p(λ) = α·q(λ) + (1−α)·u(λ)` (`u` uniform on the band, `α = 0.5` — frozen
  2026-09-22, lead may adjust): `supp(p)` is the full band and `∫p = 1`. This feeds
  the existing hero machinery rather than replacing it.
- **Exact likelihood-ratio estimator:** a path wavelength λ contributes with weight
  `f(λ)/p(λ)` (`f` the incident spectral radiance); channel k deposits
  `f(λ)·SRF_k(λ)/p(λ)`. No extra cosine factor enters here.

**Boundary with pkg51:** `specfilm` is the render-time half — SRF-importance-sampled
wavelength-resolved radiance. pkg51's per-band PSF convolution + Poisson/read noise
stay **image-space**; this package hands pkg51 Phase 2 the raw bins it needs, plus
named SRF layers, and does not touch those passes.

---

## Implementation plan

- **A. T(λ)/QE(λ) + SRF representation + combined proposal.** Store throughput and QE
  independently; derive `SRF_k = T·QE` per channel; build the combined CDF `q`; expose
  channel definitions through the scene/exporter.
- **B. Hero-composed wavelength importance sampling.** Draw path wavelengths from the
  mixture `p = α q + (1−α) u` under the existing hero-wavelength shifts, weighted by
  `f(λ)·SRF_k(λ)/p(λ)` so weights stay unbiased. CPU-first, then wavefront spectral
  mirror.
- **C. Wavelength-resolved bins + multichannel EXR + gate.** Write raw spectral bins
  and one EXR layer per SRF (alphabetical); gate analytic flat/narrow/multi-channel
  unbiasedness and that a narrow-band channel reaches target noise in far fewer
  samples than uniform sampling.

---

## Acceptance criteria

- [ ] `T(λ)` and `QE(λ)` stored independently per instrument; `SRF_k = T·QE` used only
      as the Phase-1 proposal/response weight.
- [ ] N named SRF channels definable per scene; combined normalized proposal `q`
      (`supp` = SRF union, `∫q = 1`) built by CDF inversion and composed with the hero
      pdf as the mixture `p = α q + (1−α) u`.
- [ ] **Analytic unbiasedness** with the likelihood-ratio estimator
      `f(λ)·SRF_k(λ)/p(λ)`: (a) a flat full-band SRF reproduces the analytic flat
      integral; (b) a narrow single-channel SRF reproduces its analytic narrow-band
      integral; (c) multiple channels are simultaneously unbiased with no
      cross-channel leakage. Each within stated MC uncertainty (≥ 64 spp).
- [ ] Raw wavelength-resolved bins retained across 360–830 nm and handed to pkg51
      Phase 2; halving the bin width changes pkg51 Phase-3 μ_e by < 1 %
      (bin-convergence).
- [ ] Narrow-band channel reaches a target noise level in materially fewer samples
      than uniform sampling (measured variance-reduction reported).
- [ ] Multichannel EXR output: raw bin layers + one named layer per SRF (alphabetical
      per `specfilm`).
- [ ] CPU↔GPU wavefront-diff parity for the spectral sampling change.
- [ ] Dependency note honored: Phase 1 emits only relative radiance with provenance,
      no photon/electron/ADU claim before pkg243 Phase 2, and does not touch pkg51's
      image-space PSF/noise passes.

---

## Non-goals

- **Not the telescope PSF / noise pipeline.** PSF convolution + Poisson/read noise are
  pkg51 (image-space); this is the render-time SRF half only.
- **Not polarization / fluorescence.** ART-style bi-spectral features are
  literature-only (GPL) and out of scope.
- **Not a lens/aperture camera model.** Mitsuba `thinlens`/aperture is a separate
  low-cost add — file a follow-up if wanted; not bundled here.

---

## Algorithm sourcing (CLAUDE.md §6)

- **Mitsuba 3 `specfilm`** `github.com/mitsuba-renderer/mitsuba3` — **BSD-3-Clause
  (verified)**. Film plugin: N SRF `spectrum` channels → combined continuous
  distribution via inverse-transform sampling → wavelength importance sampling →
  multichannel EXR. Docs: mitsuba.readthedocs.io → Plugins → Films.
- **Wilkie, Nawaz, Droske, Weidlich, Hanika**, "Hero Wavelength Spectral Sampling",
  EGSR 2014, CGF 33(4), DOI 10.1111/cgf.12419 — Astroray's existing hero basis the
  SRF pdf must compose with.
- **Fascione et al.**, "Manuka: A Batch-Shading Architecture for Spectral Path
  Tracing", ACM TOG 37(3):32, 2018, DOI 10.1145/3182161 (preprint
  jo.dreggn.org/home/2018_manuka.pdf) — camera-space measured spectral-response
  sensor model (**literature only**; skim §sensor before citing in the article, per
  the research doc's coverage-gap note).
- **"Spectral imaging in production"**, SIGGRAPH 2021 Courses,
  DOI 10.1145/3450508.3464582 — production sensor-response handling (literature).
- **ART** (cgg.mff.cuni.cz/ART) — GPL → **literature/concept only**, do not port.
- **Research doc:** `.astroray_plan/docs/2026-07-other-engines-research.md` §3 +
  adoption rank 5 ("pair with pkg51 resume — pkg51 Phase 1").

---

## Provenance

Filed from the **other-engines technique sweep (2026-07-19)**
(`.astroray_plan/docs/2026-07-other-engines-research.md` §3, adoption rank 5). Owner
goal: render what the **instrument** actually sees — channels built from separately
retained filter `T(λ)` and detector `QE(λ)`, with unbiased relative radiance
accumulation and provenance. Calibrated photon/electron/ADU statistics are blocked on
pkg243 Phase 2. Render-time complement to the paused pkg51 telescope pipeline.

---

## Progress

- [ ] A — separate T(λ)/QE(λ) + SRF representation + combined-proposal build.
- [ ] B — hero-composed wavelength importance sampling (CPU + wavefront).
- [ ] C — raw bins + multichannel EXR + analytic-unbiasedness + narrow-band gate.

---

## Lessons

*(Fill in after the package is done.)*
