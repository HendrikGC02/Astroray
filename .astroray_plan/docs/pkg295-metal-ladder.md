# pkg295 — Disney metal vs Cycles ladder (#934, lane ak-295, 2026-09-29)

Scene: pkg292 sun ladder (80×80 plane, `disney` metallic 1, dedicated sun
0.526° strength 1, camera 20 up, vfov 40, 48², mean over [4:44]). Astroray CPU
3 seeds × 64 spp; Cycles = Blender 5.2 Principled (specular tint white), 256 spp,
same camera (per-pixel profiles checked). Harness: `astra_run/AK/ak-295/`
(`ladder934.py`, `ladder934b.py`, `cycles_metal_ref.py`).

| rung | baseline CPU / Cycles | fixed CPU / Cycles |
|---|---|---|
| grey 0.5 r0.5 sun ↓ (#934's rung) | 0.997 | 0.997 |
| grey 0.8 r0.5 ↓ / oblique | 0.992 / 0.985 | — / 0.998 |
| grey 0.8 r0.1 ↓ / oblique | **0.076 / 0.058** | 0.99 / 1.01 |
| copper r0.5 ↓ (R/G/B) | **0.939** / 0.998 / 0.997 | 0.998 / 0.998 / 0.997 |
| half metal (0.5) ↓ / oblique | 0.927 / 0.910 | unchanged (not a metal-lobe term) |
| dielectric default ↓ / oblique | 0.976 / 0.974 | unchanged |

**#934's premise does not reproduce.** A fresh Cycles 5.2 render of the pkg292
"metal" rung reads 0.4779, not 0.5628; Astroray reads 0.476 (and a numpy
evaluation of Cycles' GGX + F82-tint + `microfacet_ggx_preserve_energy` gives
0.478). At metallic 1 the damped-Schlick scale is 1 and Cycles' F82-tint with a
white tint is plain Schlick, so the Fresnel is already Cycles'.

**Convicted term: the spectral upsample clamp.** `DisneyPlugin::evalSpectral`
(and the GPU twin `gpu_material_eval_spectral`) upsampled the RGB eval `f·cos`
through the Jakob–Hanika ALBEDO LUT, which clamps rgb to [0,1]. A GGX peak
under a sun is far above 1 (r0.1 Cycles peak pixel 344), so sun NEE was capped
at 1 (Astroray peak pixel ~1.0). `sampleSpectral` already magnitude-factored
(`upsample(rgb/m)·m`, m = max(rgb,1)); `evalSpectral` now does the same on both
backends. Identical when rgb ≤ 1, so the white furnace (no NEE) is unchanged:
metallic 1 base 1 linear 0.999 / 0.999 / 0.997 / 1.000 / 0.981 at r 0.05 / 0.1 /
0.3 / 0.5 / 1.0.

**Not fixed here (follow-up):** half-metal −7…9 %. Astroray's half-metal reads
6 % below its own linear mix of the metal and dielectric rungs, while Cycles'
Principled mixes the conductor and dielectric closures linearly by metallic.
Disney 2012 blends F0 into one specular lobe, damps its grazing term
(0.8 + 0.2·metallic) and attenuates the diffuse layer by the MIXED (metal-
including) specular albedo. A Cycles-style split is a model change to the
dielectric lobes (spec non-goal). Disney `specular_tint` is Burley's scalar
dielectric tint, not Cycles' F82 colour, so the spec's F82 ≠ 1 rung has no
Disney input; Blender Principled exports to the native `principled` material,
which already implements F82-tint.
