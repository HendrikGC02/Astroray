# Noise per time: spectral arbitration scenes (Mitsuba 3 reference)

Tests: prism under a 4 degree sun (dispersive caustic), chromatic homogeneous medium, narrow-band (sodium) lamp on a
coloured wall; Cycles, Astroray CPU/GPU and Mitsuba 3.9.1 `cuda_ad_spectral` (16384 spp reference, lamp scale anchored per scene).

Verdict: medium agrees 1-4 % (Cycles up to 20 % off in blue); narrow-band luminance agrees, Astroray R/G is 14 % below the
CIE integral of its own SPD; prism floor caustic Astroray 11-17 % above Mitsuba. `arbitration_roi_means.json` has the z-scores.

Provenance: pkg307, Astroray build 94992cb1; Cycles is RGB: dispersion/narrow-band Cycles rows are the "RGB reference limit".
