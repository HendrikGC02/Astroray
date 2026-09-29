# Env-map reflection lookup
Chrome sphere reflecting an HDRI: Cycles, Astroray, and the per-pixel luminance ratio map.
Verdict: lookup unchanged, no visual regression; the ratio is ~flat except the sun-glint corner
(F82 was rejected; the residual is the #795 chrome G +8% spectral skew).
Provenance: pkg275 (env-map reflection lookup gap), issue #795, 2026-09.
