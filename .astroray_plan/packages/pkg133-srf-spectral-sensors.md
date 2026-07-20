# pkg133 — SRF spectral sensors (Mitsuba `specfilm` — detector QE × filter curves)

**Pillar:** 2 (spectral core) — **Pillar-4-adjacent** (activates the astronomical-detector story)
**Track:** A (SRF distribution build + wavelength-importance-sampling change is CPU-gated; wavefront spectral leg verified on RTX)
**Codex-paste-ready:** no (touches the hero-wavelength-aware spectral sampling pdf + film accumulation — spectral-core surgery, needs care)
**Status:** open
**Estimated effort:** M (2–3 sessions per the research doc — the SRF distribution build is simple CDF inversion; the sampling-pdf + film changes are the delicate part)
**Depends on:** the spectral wavelength sampler (Pillar-2 core, already present — hero-wavelength per Wilkie 2014). **Pillar-4-adjacent dependency note:** this is the *render-time* half of the paused **pkg51** telescope post-process — it activates when the owner lifts the Pillar-4 pause **or** ships standalone as a spectral-camera feature. Sequence after pkg51 resumes, or fold in as **pkg51-B**.

---

## Goal

**Before:** Astroray samples path wavelengths uniformly across the band and weights
at the end. A JWST/NIRCam-style channel (filter transmission × detector QE) is
narrow, so uniform sampling wastes most samples outside the channel's sensitivity
and leaves narrow-band output noisy. There is no per-instrument-channel output.

**After:** Port Mitsuba 3's **`specfilm`** (BSD-3, verified): the film takes N named
**Sensor Response Functions** (one per output channel — e.g. filter transmission ×
detector QE), builds a combined continuous distribution over all SRFs, and
**importance-samples path wavelengths where the instruments are actually sensitive**
instead of uniformly. Output is a multichannel EXR (one channel per SRF). Correct
per-channel photon statistics and far lower spectral noise in narrow bands.

---

## Design sketch (cite the research doc; don't duplicate it)

Full source record: `.astroray_plan/docs/2026-07-other-engines-research.md` §3.

- **SRF channels:** each output channel is a spectral response curve (filter × QE),
  supplied as a tabulated `spectrum` per channel (Mitsuba's nested-`spectrum`
  model). N channels → N EXR layers (alphabetical, per `specfilm`).
- **Combined importance distribution:** build one continuous distribution over the
  union of all SRFs via inverse-transform sampling (simple CDF inversion), and draw
  path wavelengths from it. This is the render-time correctness win — it must be
  **hero-wavelength-aware** (Astroray's basis is hero-wavelength, Wilkie 2014), so
  the pdf feeds the existing hero machinery rather than replacing it.
- **Film accumulation:** each sampled wavelength deposits into the channels whose SRF
  is non-zero there, weighted by SRF value / sampling pdf.

**Boundary with pkg51 (from the research doc):** `specfilm` is the render-time half —
SRF-importance-sampled per-channel radiance. pkg51's PSF convolution + Poisson/read
noise stay **image-space** (pkg51 design decision 1). This package does not touch
those; it feeds them cleaner per-channel input.

---

## Implementation plan

- **A. SRF channel representation + combined distribution.** Per-channel tabulated
  SRF; build the combined CDF; expose channel definitions through the scene/exporter.
- **B. Hero-aware wavelength importance sampling.** Replace uniform band sampling with
  draws from the combined SRF distribution, wired through the existing hero-wavelength
  pdf so weights stay unbiased. CPU-first, then wavefront spectral mirror.
- **C. Multichannel EXR output + gate.** Write one EXR layer per SRF; gate that a
  narrow-band channel reaches target noise in far fewer samples than uniform
  sampling, and that a flat/full-band SRF reproduces today's output.

---

## Acceptance criteria

- [ ] N named SRF channels (tabulated filter × QE) definable per scene; combined
      importance distribution built by CDF inversion.
- [ ] Path-wavelength sampling draws from the combined SRF distribution, hero-aware,
      and remains **unbiased** (a flat full-band SRF reproduces the current uniform
      result within noise).
- [ ] Narrow-band channel reaches a target noise level in materially fewer samples
      than uniform sampling (measured variance-reduction reported).
- [ ] Multichannel EXR output (one layer per SRF, alphabetical per `specfilm`).
- [ ] CPU↔GPU wavefront-diff parity for the spectral sampling change.
- [ ] Dependency note honored: does not touch pkg51's image-space PSF/noise passes.

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
  adoption rank 5 ("pair with pkg51 resume — pkg51-B").

---

## Provenance

Filed from the **other-engines technique sweep (2026-07-19)**
(`.astroray_plan/docs/2026-07-other-engines-research.md` §3, adoption rank 5). Owner
goal: render what the **instrument** actually sees — filter × detector-QE channels
with correct per-channel photon statistics — the render-time complement to the paused
pkg51 telescope pipeline.

---

## Progress

- [ ] A — SRF channel representation + combined-distribution build.
- [ ] B — hero-aware wavelength importance sampling (CPU + wavefront).
- [ ] C — multichannel EXR + narrow-band variance-reduction gate.

---

## Lessons

*(Fill in after the package is done.)*
