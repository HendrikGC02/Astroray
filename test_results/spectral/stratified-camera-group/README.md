# Stratified camera group (pixel filter, lens, hero wavelength)

Tests: the per-pixel Sobol-Burley camera draws (pkg305) against the white-noise
camera, corpus v2 on CPU at 64 spp (seeds 278-282; means with independent seeds).

Verdict (CPU): sky_upper R/B relVar 1.9e-3/2.6e-3 -> 2.4e-5/3.7e-5; v2_sky_sun
bulk luminance variance 190x -> 4.2x Cycles; world-background chroma 56x lower;
chroma variance lower in every scene; ROI means |z| <= 2.9. Crops show no
structured patterns. GPU leg pending the CUDA build.

Provenance: pkg305, base main 16a9d288 / 775a5d6b, MinGW CPU; renders and
scripts in `astra_run/AP/ap-305`.
