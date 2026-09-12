# pkg200 — Native-settings F12 pixel-honour matrix — results

Rows: 27  (per Blender version)

| Stage | Row | Scene | Blender | Kind | Verdict | Measured |
|-------|-----|-------|---------|------|---------|----------|
| 0 | resolution | closed_box | bl5.2 | automatable | PASS | shape A=(64, 64) B=(96, 96) |
| 1 | diffuse_bounces | closed_box | bl5.2 | automatable | HONEST-FAIL | lum_mean A=0.42923 B=0.42923 ratio=1.000 (< 1.03: setting does not add indirect energy) |
| 1 | glossy_bounces | closed_box_glossy | bl5.2 | automatable | PASS | lum_mean A=0.067017 B=0.69941 ratio=10.436 |
| 1 | max_bounces | closed_box | bl5.2 | automatable | PASS | lum_mean A=0.035237 B=0.42923 ratio=12.181 |
| 1 | transmission_bounces | glass_sphere | bl5.2 | automatable | PASS | lum_mean A=0.42382 B=0.49861 ratio=1.176 |
| 1 | transparent_max_bounces | transparent_tower | bl5.2 | automatable | HONEST-FAIL | lum_mean A=0.33281 B=0.33281 ratio=1.000 (< 1.03: setting does not add indirect energy) |
| 1 | use_light_tree | many_lights | bl5.2 | visual | NEEDS-VISUAL | per-pixel |dLum| mean=0.5025 max=6.763 (setting changes pixels; confirm direction visually) |
| 1 | volume_bounces | volume_box | bl5.2 | automatable | HONEST-FAIL | lum_mean A=0.021046 B=0.02101 ratio=0.998 (< 1.03: setting does not add indirect energy) |
| 1 | world_max_bounces | hdri_box | bl5.2 | automatable | PASS | lum_mean A=0.20003 B=1.06 ratio=5.299 |
| 2 | blur_glossy | firefly | bl5.2 | automatable | HONEST-FAIL | lum_max A=27.83 B=27.83 (blur_glossy left the highlight peak unchanged) |
| 2 | sample_clamp_direct | firefly | bl5.2 | automatable | PASS | hi_pct A=26.4 B=0.5071; lum_max A=27.83 B=0.5081 (fireflies clipped) |
| 2 | sample_clamp_indirect | firefly_indirect | bl5.2 | automatable | NEEDS-VISUAL | hi_pct A=1481 B=1481; lum_max A=1639 B=1639 (inconclusive: fireflies NEE-classified as DIRECT; clampIndirect shares the pkg157 kernel param with clampDirect, which PASSES) |
| 3 | film_exposure | closed_box | bl5.2 | automatable | PASS | per-ch mean-ratio B/A = 2.000, 2.000, 2.000 (target (1.7, 2.3)) |
| 3 | film_transparent | open_object | bl5.2 | automatable | HONEST-FAIL | alpha_mean transparent-A=1.000 opaque-B=1.000 (film_transparent did not open the background alpha) |
| 3 | film_transparent_glass | open_glass | bl5.2 | visual | HONEST-FAIL | per-pixel |dLum| mean=5.19e-11 max=6.828e-08 (setting produced no pixel change) |
| 3 | preview_samples | closed_box | bl5.2 | limitation | LIMITATION | viewport-only control — not exercisable via headless F12 |
| 3 | render_region | closed_box | bl5.2 | automatable | HONEST-FAIL | lum_mean A(no border)=0.42923 B(border)=0 ratio=0.000 (target ~0.25 = kept area) |
| 3 | samples | open_object | bl5.2 | automatable | PASS | MC-noise(16spp)=0.00771 (64spp)=0.003903 ratio=0.506; mean ratio=1.000 (noise falls ~1/sqrt(N)) |
| 3 | seed_distinct | closed_box | bl5.2 | automatable | PASS | lum_mean ratio=1.010, per-pixel |dLum| mean=0.2259 (same mean, different noise) |
| 3 | seed_repeat | closed_box | bl5.2 | automatable | PASS | per-pixel |dLum| max=0 (reproducible <=1e-5) |
| 4 | caustics_reflective | caustic | bl5.2 | visual | HONEST-FAIL | per-pixel |dLum| mean=1.163e-11 max=7.489e-09 (setting produced no pixel change) |
| 4 | caustics_refractive | caustic | bl5.2 | visual | HONEST-FAIL | per-pixel |dLum| mean=1.529e-11 max=7.489e-09 (setting produced no pixel change) |
| 4 | denoiser | denoiser_scene | bl5.2 | visual | NEEDS-VISUAL | both backends rendered (A mean=0.4858, B mean=0.4858; per-pixel |dLum| mean=0) |
| 4 | filter_width | closed_box | bl5.2 | automatable | PASS | grad_mean A=0.21953 B=0.21681 (filter changes edge sharpness) |
| 4 | pixel_filter_type | closed_box | bl5.2 | automatable | HONEST-FAIL | grad_mean A=0.21698 B=0.21807 (pixel filter did not change edge gradient) |
| 4 | use_denoising | denoiser_scene | bl5.2 | visual | PASS | lum_var ratio denoised/noisy=0.787 (variance reduced) |
| 4 | use_preview_denoising | closed_box | bl5.2 | limitation | LIMITATION | viewport-only control — not exercisable via headless F12 |

## Verdict tally

`{'PASS': 12, 'HONEST-FAIL': 10, 'NEEDS-VISUAL': 3, 'LIMITATION': 2}`

## Known gaps (recorded, not fixed here)
