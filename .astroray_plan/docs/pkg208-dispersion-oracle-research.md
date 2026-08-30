# pkg208 — chromatic-light-source dispersion oracle: citations

No new algorithm is introduced by this package (per spec §1, Non-goals). This
note records the physics being *asserted*, not implemented.

## 1. Dispersion at a dielectric interface

Standard textbook physics — refraction angle depends on wavelength through the
material's index of refraction n(λ):

- Snell's law: n1 sin(θ1) = n2 sin(θ2).
- n(λ) for the prism glass is already computed by the shipped Sellmeier model
  (Schott BK7 coefficients, `include/astroray/optical_presets.h`, exercised by
  `tests/test_gpu_sellmeier_ior.py` against the Schott BK7 datasheet at the
  d/F/C lines).
- Reference: E. Hecht, *Optics* (5th ed.), Ch. 3 (dispersion) and Ch. 5
  (refraction at a boundary) — standard undergraduate optics, cited here only
  to ground the assertion, not to justify new code.

## 2. Why a monochromatic (narrow-line) source disperses to a single band, not a rainbow

A prism does not "create" a rainbow out of nothing — it spatially separates
wavelengths that are already present in the incident light by refracting each
one through a slightly different angle (n(λ) varies smoothly with λ, so exit
angle varies smoothly with λ). If the incident spectrum has energy at only one
narrow band of λ (e.g. the sodium D-lines, ~589 nm), then only that one exit
angle carries measurable energy — the output is a single-hue band near the
input wavelength, not a spread of hues. A source with broadband emission
(energy spread across ~380–780 nm) refracts every one of those wavelengths to
its own exit angle simultaneously, producing the familiar continuous
ROYGBIV spread. This is textbook (Hecht, ibid., §5.5) — not a new claim.

## 3. The Cycles limitation this oracle differentiates against

Astroray's own dispersion-research report
(`.astroray_plan/docs/reports/2026-08-19-cycles-dispersion-research.html`,
"Acknowledged limitation" section) quotes the Cycles PR #162041 author
directly on why Cycles cannot do what §2 describes:

> "It's not physically correct, because we don't know the spectrum of the
> light source … in the future if we switch to spectral, then uplifting would
> naturally be added."

Cycles' dispersion pipeline hero-samples ONE wavelength per path from a fixed
D65-luminance CDF and renders RGB throughout — it never carries the actual
light source's SPD to the dispersive event, so a spectrally-narrow light and a
broadband light produce visually similar (full-spread, D65-tinted) rainbows
through the same prism. Astroray's `multiwavelength_path_tracer` carries the
sampled light's measured SPD (`profiles.bin`) through to the dispersive
dielectric BSDF, so the two cases documented above are physically
distinguishable in Astroray but are not in Cycles as shipped. This is the
concrete differentiator pkg208 turns into a standing regression oracle
(`tests/test_spectral_prism.py::test_narrow_line_vs_broadband_dispersion_width`
and `::test_narrow_line_band_is_amber_hued`).

## 4. Scene mechanism (why this doesn't need caustics / photon mapping)

The oracle reuses `tests/scenes/prism_reference.py`'s existing "view colored
panels through a dispersive prism" geometry (proven in `tests/test_spectral_prism.py`,
pkg29) rather than a "beam cast onto a screen" rainbow demo. The point light
illuminates the panels directly and unoccluded by glass (ordinary NEE); the
camera views the panels *through* the dispersive prism. `red_blue_centroid_separation`
already measures the pkg29-proven excess spatial separation this refraction
distortion adds between red- and blue-dominant image regions.

The new physics this oracle adds is on the illuminant side: in a hero-wavelength
spectral path tracer, a camera path's contribution at wavelength λ is weighted
by the light's SPD at λ. For the `sodium_vapor` narrow line, only λ near 589 nm
carries meaningful radiance, so — in expectation — the rendered dispersion
pattern collapses to what a *single* index of refraction n(589 nm) would
produce (near-zero *excess* dispersion vs. a non-dispersive control). For the
`led_6500k` broadband control, every λ in [380, 780] nm carries comparable
radiance, so the full n(λ) spread contributes, reproducing pkg29's already-measured
excess separation (~2.77 px). No caustics, no photon mapping, and no
GPU-only code paths (`src/gpu/photon_caustic.cu`) are needed — this is
ordinary unidirectional path tracing with existing NEE, run CPU-only.

## Sources

- Hecht, E. *Optics*, 5th ed. — standard optics textbook (dispersion, Snell's
  law). No code borrowed; cited for the physics claim only.
- Schott BK7 optical glass datasheet (already the Sellmeier reference in this
  repo, `tests/test_gpu_sellmeier_ior.py`).
- Cycles PR #162041 thread (author reply quoted in
  `.astroray_plan/docs/reports/2026-08-19-cycles-dispersion-research.html`).
