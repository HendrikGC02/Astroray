# Known issues — Blender addon

Generated 2026-09-08 06:27 UTC by `scripts/dev/known_issues_report.py` from GitHub issues labelled `addon-bug` / `addon-gap`. Do not edit by hand; file or close issues instead.

Pillar-4 exit-gate (e): open `addon-bug` at P0/P1 = **3** (target 0).

## Open defects (`addon-bug`)

| # | Severity | Title | Updated |
|---|---|---|---|
| [721](https://github.com/HendrikGC02/Astroray/issues/721) | P1-high | Viewport: camera events block ~155 ms each; progressive refinement idles at ~1.3 Hz | 2026-09-07 |
| [759](https://github.com/HendrikGC02/Astroray/issues/759) | P1-high | GPU adaptive sampling is a silent no-op in Blender: the wavefront requires the progressive sampler, which the addon never enables | 2026-09-08 |
| [769](https://github.com/HendrikGC02/Astroray/issues/769) | P1-high | Addon zip never ships data/disney_compensation/*.bin â€” a redistributed addon silently runs with ALL energy compensation disabled | 2026-09-08 |

## Open gaps (`addon-gap`)

| # | Severity | Title | Updated |
|---|---|---|---|
| [762](https://github.com/HendrikGC02/Astroray/issues/762) | P1-high | Procedural texture nodes wired directly into Emission render flat white on Astroray (Cycles shows the pattern); no degradation warning | 2026-09-08 |
| [722](https://github.com/HendrikGC02/Astroray/issues/722) | P2-medium | Native Cycles Device (scene.cycles.device) is ignored; device only via custom_raytracer.device_mode | 2026-09-06 |
| [723](https://github.com/HendrikGC02/Astroray/issues/723) | P2-medium | Missing environment/image texture file is dropped silently (no degradation warning) | 2026-09-06 |
| [757](https://github.com/HendrikGC02/Astroray/issues/757) | P2-medium | Diffuse BSDF is exported as Principled with the default dielectric specular layer (Cycles' Diffuse BSDF has none) | 2026-09-08 |
| [724](https://github.com/HendrikGC02/Astroray/issues/724) | P3-low | Camera clip_start/clip_end are ignored (documented degradation) | 2026-09-06 |

## Recently closed

| # | Severity | Title | Updated |
|---|---|---|---|
| [746](https://github.com/HendrikGC02/Astroray/issues/746) | P1-high | Bump/Displacement relief far fainter through the Blender F12 pipeline than through the direct Renderer API | 2026-09-07 |
| [753](https://github.com/HendrikGC02/Astroray/issues/753) | P2-medium | Bump relief ~1.8-2x stronger than Cycles at equal Distance, with faint ring banding (pkg223b normal_mapped.cpp calibration) | 2026-09-08 |
