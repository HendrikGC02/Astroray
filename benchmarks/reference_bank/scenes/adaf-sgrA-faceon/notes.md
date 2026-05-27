# adaf-sgrA-faceon

**Vision:** A Sgr A*-like ADAF glow — quasi-spherical electron-thermal +
synchrotron emission around a moderately-spinning Kerr BH — rendered
near face-on. Visual signature: a bright fuzzy halo of accretion glow
with a sharp circular dark region in the centre (the BH shadow).

**Phase 2b status:** Owner deferred astrophysics scenes to low-priority
2026-05-27, but explicitly wanted to see what they currently look like.
The reference was captured at this commit; gates are permissive enough
to catch a total regression (ADAF emission vanishing, BH dispatch
breaking) but not a tuning regression. A future tuning pass should
tighten thresholds once visual aesthetics are blessed.

**Reference notes:** 256×256, 32 spp, ~few sec render. pkg44 ADAF
plugin via `add_black_hole(... enable_adaf=True ...)` with Sgr A*
intensity_scale 1e30. Uses pkg107 `r_obs_M=20` so the shadow + glow
scale appropriately.
