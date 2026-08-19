# pkg208 — Chromatic-light-source dispersion oracle (line emitter through a prism)

**Pillar:** 3 (spectral rendering) + Integration Milestone (parity/superiority oracle)
**Track:** A (test-authoring + oracle; no engine algorithm change expected).
**Estimated effort:** S.
**Status:** open (filed 2026-08-19).
**Depends on:** the spectral line-emitter path (already shipped — the research
report §9 gallery shows a working 635 nm line emitter render) and the existing
dispersive-prism scene (`tests/test_spectral_prism.py`). No new algorithm.

## Goal

Cycles' merged dispersion is RGB-with-one-hero-wavelength and **cannot know the
source SPD**: with a spectrally-narrow light (e.g. a Rec.2020 red light), a
physically-correct prism shows only the red slice of the rainbow, but Cycles
"solves for the full D65 SPD" and then tints the whole dispersed rainbow red (the
PR author acknowledges this as a known non-physical limitation). Astroray is a
true spectral renderer that carries the source SPD to the observer, so it renders
this case **correctly** — a concrete differentiator. Turn that into a standing
**oracle test**: a narrow-line emitter refracted through a dispersive prism must
produce a spectrally-narrow spread (a single-hue band near the emitter's
wavelength), NOT a full ROYGBIV rainbow.

## Specification

1. **No new algorithm — this is an oracle over existing behaviour.** Invoke
   `cite-algorithm` only to *cite* the physics being asserted (dispersion at a
   dielectric interface: n(λ) from Sellmeier/Cauchy, the same models already
   shipped; and the reason a monochromatic input yields a single deflected ray,
   not a spread — cite a standard optics reference and the Cycles PR-thread
   limitation quote). Save a short note under `.astroray_plan/docs/` framing this
   as a superiority oracle (Cycles fails by design). If the test surfaces a REAL
   engine bug (the narrow-line case does NOT render narrow), STOP and file that as
   a separate defect spec — do not paper over it in the oracle.

2. **Scene:** reuse the dispersive-prism geometry from `tests/test_spectral_prism.py`
   (BK7 Sellmeier preset), but replace the broadband/white illuminant with a
   **narrow-line emitter** (reuse the shipped line-emitter path from the §9
   gallery — e.g. a ~635 nm red line; parameterize the line wavelength so the test
   can sweep at least two lines, e.g. red ~635 nm and blue ~470 nm).

3. **Oracle predicates** (LINEAR EXRs, seed-pinned, sentinel-gated — not exit code):
   - The dispersed band's **dominant hue tracks the emitter wavelength** (a
     red-line prism produces a red-dominant band; a blue-line prism a blue-dominant
     band) — assert via a hue/centroid metric on the refracted region, contrasting
     the two line wavelengths against each other.
   - The **spectral spread is narrow**, not full-rainbow: measure the hue variance
     / red-blue centroid separation in the refracted band and assert it is well
     below what the SAME prism produces under a broadband white source (render that
     broadband control in the same test as the wide-spread reference). This
     "narrow << broadband" contrast is the crux — it is exactly the assertion
     Cycles would fail.

4. Register the scene/driver in `scripts/README.md` if it adds a reusable harness
   entry (CLAUDE.md §5b — check the index first; prefer extending
   `test_spectral_prism.py` with a parametrized line-emitter case over a new file).

## Acceptance

- [ ] The oracle test PASSES on current `main`: red-line and blue-line prisms
  render hue-correct, narrow bands; the broadband control renders a measurably
  wider spread. Report the measured hue-centroid / spread numbers for all three
  (red line, blue line, broadband). State the `.pyd` mtime next to the render leg.
- [ ] The test is deterministic (seed-pinned) and runs in the standard suite; the
  `.astroray_plan/docs/` note frames it as a Cycles-superiority oracle with the
  cited limitation.
- [ ] CI green on all matrix jobs; RTX leg run if the scene renders on GPU (memory
  `cpu-suites-auto-use-cuda` — a "CPU" render may auto-route to CUDA; verify which
  backend produced the numbers and state it).

## Non-goals

- **No dispersion-model change** — Sellmeier/Cauchy stay as-is; this only asserts
  the already-correct spectral behaviour.
- **No Cycles-side render** — the experimental Cycles build is not installed; the
  contrast is against Astroray's own broadband control, with the Cycles limitation
  cited from the PR thread, not rendered.

## Provenance

Filed by the architect 2026-08-19 from the dispersion research report
(`.astroray_plan/docs/reports/2026-08-19-cycles-dispersion-research.html` §6 /
§04 "Acknowledged limitation" / ranked recommendation #4). Grounded in the §9
gallery's working 635 nm line-emitter render and `tests/test_spectral_prism.py`.
Open-model IMPLEMENT-tier (test authoring) behind CI (+RTX) gates; Claude owns the
"is this a real oracle or is it masking a bug" judgment.
