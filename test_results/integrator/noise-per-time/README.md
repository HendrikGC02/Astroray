# Noise per time: Astroray vs Cycles, corpus v2

Tests: equal-spp and equal-time (2/10/60 s per 1280x720 frame) relMSE, relVar, chroma, tail share, N x relVar slope and
efficiency 1/(relMSE x t); Astroray CPU/GPU vs Cycles CPU/OptiX, 8 scenes, 5 seeds, render-only time by spp differencing.
Settings: `blur_glossy = 0`, `sample_clamp_indirect = 0` (authored, not Blender defaults), adaptive/denoise off.

Verdict: Astroray GPU efficiency is 0.006-0.31 of Cycles OptiX (3-167x worse MSE at equal time); gap = 1.4-3.8x per-spp
time x variance (heavy tails in media/dispersion, chroma noise, no QMC gain). Two quiet runs agree within 10 %.

Provenance: pkg307, Astroray build 94992cb1, Blender 5.2, RTX 5070 Ti; analysis in `.astroray_plan/docs/noise-per-time-findings-2026-10-02.md`.
