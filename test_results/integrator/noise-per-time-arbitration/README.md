# Noise per time: spectral arbitration scenes (Mitsuba 3 reference)

Tests: prism under a 4 degree sun (dispersive caustic), chromatic homogeneous medium, narrow-band (sodium) lamp on a
coloured wall; Cycles, Astroray CPU/GPU and Mitsuba 3.9.1 `cuda_ad_spectral` (16384 spp reference; sun in physical units, rectangle lamps anchored per scene).

Verdict: medium agrees 1-4 % (Cycles up to 20 % off in blue); narrow band R/G agrees after #1020 (R within 3 sigma, G -0.3 %,
Mitsuba's own offset from the CIE integral); sun-lit floor_far agrees within 3 sigma after #1021 (Mitsuba in physical sun
units); prism floor caustic Astroray GPU -8 %, CPU -26 % (#1025). `arbitration_roi_means.json` has the z-scores
(prism + narrow-band rows re-run 2026-10-03, build e584ad85).

Provenance: pkg307, Astroray build 94992cb1; Cycles is RGB: dispersion/narrow-band Cycles rows are the "RGB reference limit".
