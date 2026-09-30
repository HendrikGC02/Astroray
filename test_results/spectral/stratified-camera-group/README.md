# Stratified camera group (pixel filter, lens, hero wavelength)

Tests: the per-pixel Sobol-Burley camera draws (pkg305) against the white-noise
camera, corpus v2 on CPU and GPU at 64 spp (seeds 278-282 vs Cycles; means
with independent seeds 278 + 10000 k).

Verdict: sky_upper R/B relVar 1.9e-3/2.6e-3 -> 2.4e-5/3.7e-5 on both backends;
v2_sky_sun bulk luminance variance 190x -> 4.2x Cycles; world-background chroma
56x lower; chroma variance lower in every scene. ROI means: worst |z| 2.9 CPU,
3.9 GPU (one ortho floor ROI; block-level z shows no shift). Crops show no
structured patterns.

Provenance: pkg305, base main f0f8b5f6; renders and scripts in `astra_run/AP/ap-305`.
