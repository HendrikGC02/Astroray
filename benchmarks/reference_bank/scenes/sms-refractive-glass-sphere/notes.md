# sms-refractive-glass-sphere

**Vision:** Clear non-dispersive glass sphere illuminated by an area emitter,
casting a sharp focused caustic on the floor below. Tests refractive-caustic
seed finding in the scalar-IOR mode (spectral_newton=0).

**pkg127 re-bless (2026-09-04):** this scene now sets `sms_specular_poly=1`, so
it exercises the **deterministic Specular-Polynomials** seed stage (Fan et al.
2024) with the physically-correct **MNEE geometry-term** weight. The previous
reference (2026-05-27) was rendered with the stochastic single-vertex Newton
seeding, whose estimator (a) over-brightened the caustic (~1.5x total ROI energy;
same focus/peak) and (b) double-counts the receiver cosine — `evalSpectral`
already returns `albedo*cos/pi`, and `runSMSAttempt` multiplies `cosX0` again.
The caustic focus/peak is unchanged; the excess spread energy is gone
(bright_coverage 0.61 -> 0.19). The `runSMSAttempt` cos^2/biased-weight issue is
filed separately as an existing-Newton-path bug (poly is unaffected).

**Paired with** `prism-bk7-collimated` — that scene exercises the per-wavelength
(triangle mesh) Newton chain; this one isolates the achromatic single-vertex
sphere path.

**Reference notes:** 384×256, 1024 spp CPU, ~30 s.
