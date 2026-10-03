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

**pkg305 re-bless (2026-09-30):** the stratified camera group (Sobol-Burley filter/lens/hero
lambda) changes the seed-17 noise realization. The old reference was that realization of the old
sampler: at seeds 11/22/33 the old engine itself scored phash 16/10/20 against it (gate 16), the new
engine 14/14/16. Re-blessed with `runner --bless`; image mean unchanged (60.52/62.99/65.69 vs
60.52/62.99/65.70 sRGB).

**#1040 re-bless (2026-10-03):** the 09-30 reference was blessed with the CPU adaptive sampler on
(the default), which retired pixels before they caught rare camera->glass->light paths (#1036). The
reference matched that bias exactly. CPU, seed 17 unless noted:

| render | image mean | caustic ROI mean | bright_coverage |
|---|---|---|---|
| 09-30 reference | 0.24732 | 0.32520 | - |
| old engine, adaptive on (seeds 11/17/22/33) | 0.2473 | 0.3252 | 0.165 |
| adaptive off, 1024 spp (old == new, byte-identical) | 0.24888 | 0.32778 | 0.196 |
| adaptive off, 4096 spp (independent, 3 seeds) | 0.24906 | 0.32804 | 0.185-0.186 |
| #1040 engine, adaptive on (seeds 11/17/22/33) | 0.2488 | 0.3278 | 0.194-0.197 |

The fixed engine agrees with the independent adaptive-off renders, and the old reference was dark by
0.9 % in the caustic ROI. Re-blessed with `runner --bless` (seed 17, fixed engine). This is a
same-engine re-bless (pkg305 precedent) validated against the adaptive-off table above, not an
independent reference: the phash gate is at the MC noise floor (two independent 4096-spp renders
differ by phash 14; 1024-spp seeds by 12-22). Against the 3-seed 4096-spp average the fixed engine
scores phash 16/12/16/12 at seeds 17/11/22/33 (seed 17 exactly on the gate; 20 against a 2-seed
average) with SSIM 0.90, dE 1.33, bright_coverage 0.194-0.197. Follow-up: #1052.
