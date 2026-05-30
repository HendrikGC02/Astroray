# prism-sf11-collimated

**Vision:** Same setup as `prism-bk7-collimated` but with SF11 flint glass
(Abbe ~25 vs BK7's ~64). Direct A/B contrast against the BK7 scene catches
a class of bug where the sellmeier preset dispatcher silently shares the
BK7 coefficients across all `dielectric` materials.

**Why two prism scenes:** if BK7 regresses and SF11 doesn't (or vice versa),
that narrows the defect domain quickly. If both regress identically,
the upstream spectral pipeline broke; if only one, the preset table or
material-param plumbing broke.

**Geometry differs from BK7 in two ways, both forced by SF11's high index**
(re-authored 2026-05-30 — the old scene was an SMS glass *sphere*, now retired):
1. **Shallower apex — 15deg half-angle vs BK7's 30deg.** SF11's critical angle is
   only ~34deg (arcsin 1/1.785); a 30deg prism puts the internal ray right at TIR,
   so SF11 deposits *zero* light on the floor (verified: max floor luminance 0.001).
   A 15deg apex keeps the ray below critical so the full spectrum transmits.
2. **Thinner entry aperture — half_u 0.15 vs 0.62.** SF11's ~4x dispersion fans the
   wavelengths so wide that a fat beam's colors overlap into a washed-out white
   salt-and-pepper core (the pkg110 noise failure mode). A thin beam keeps each
   wavelength separated -> a clean continuous rainbow.

**Distinguisher (verified):** SF11 `hue_spread` = 0.892 vs BK7 0.753 — SF11's band
is measurably wider/fuller, exactly the A/B signal. If the preset dispatcher ever
shared BK7 coefficients, both bands would collapse to the same spread.

**Reference render:** 512x512, 96 camera spp, 6M photons, integrator
`light_tracer_caustic`, re-blessed 2026-05-30. Measured baselines (deterministic —
baked caustic, fixed photon seed): hue_spread 0.892, bright_coverage 0.789,
SSIM 0.997 (band ROI y[90,430] x[70,410]).
