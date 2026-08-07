# pkg176 Stage 0 — Cycles-settings -> Astroray mapping table (owner-review artifact)

**Human-readable mirror of** `blender_addon/settings_map.py` — that module is the machine-readable single source of truth. Edit the `.py` and re-mirror; do not hand-edit the rows below.

This is the **owner-review anchor** for pkg176. It records, for every native Blender/Cycles setting the steering wheel needs, the host-neutral Astroray engine/session target and whether the mapping is **direct**, **approximated**, **dropped**, or has no native home (**astroray-only**). No silent mapping decisions: every opinionated call (which `scene.cycles.*` props Astroray may read; every semantic mismatch) is a row here for the owner to ratify.

**Grounding:** the `status` / `pkg119a` columns reuse the pkg119 Phase A coverage matrix (`docs/blender_parity/coverage_matrix.json` — 117 SUPPORTED / 22 APPROXIMATED / 385 DROPPED-SILENT). `pkg119a` is kept verbatim as the audit anchor; `status` reflects current translation reality (some natives were wired after PR #487 — noted per-row).

## Summary

- **direct**: 58
- **approximated**: 4
- **dropped**: 19
- **astroray-only**: 9
- **total rows**: 90

The full 461-row shader-node socket classification is NOT duplicated here; it is the pkg119-A matrix (`docs/blender_parity/report.md`). The Material section below is the primary material steering wheel (Principled BSDF).

## Status vocabulary

| status | meaning |
|---|---|
| `direct` | native value drives the neutral param 1:1 (unit-exact / trivial conversion). |
| `approximated` | drives a nearest engine behaviour; lossy or semantically narrower/wider — must warn (pkg119-C) once wired. |
| `dropped` | no engine target today; DROPPED-SILENT in pkg119-A. Steering wheel must stop dropping silently (Stage 1/3 + pkg119-C). |
| `astroray-only` | engine-unique control, no native Blender home; stays on the single custom Astroray panel (Stage 4). |

## Render (scene.render.*)

| Native Blender/Cycles | Current custom prop | Astroray target (neutral) | Status | pkg119-A | Note |
|---|---|---|---|---|---|
| `scene.render.resolution_x` | `—` | `render(width=...)` | direct | n/a | Read natively today (x resolution_percentage); not a custom duplicate. |
| `scene.render.resolution_y` | `—` | `render(height=...)` | direct | n/a | Read natively today (x resolution_percentage). |

## Sampling (scene.cycles.* / scene.render.*)

| Native Blender/Cycles | Current custom prop | Astroray target (neutral) | Status | pkg119-A | Note |
|---|---|---|---|---|---|
| `scene.cycles.samples` | `custom_raytracer.samples` | `render(samples=...)` | direct | SUPPORTED | Custom duplicate shadows native; Stage 1 reads scene.cycles.samples. |
| `scene.cycles.preview_samples` | `custom_raytracer.preview_samples` | `render(samples=...) [viewport]` | direct | n/a | Viewport spp; native Cycles preview_samples is the counterpart. |
| `scene.cycles.use_adaptive_sampling` | `custom_raytracer.use_adaptive_sampling` | `(none)` | dropped | DROPPED-SILENT | Custom toggle exists but is not plumbed to the engine; no adaptive-sampling session arg yet. |
| `scene.cycles.adaptive_threshold` | `custom_raytracer.adaptive_threshold` | `(none)` | dropped | DROPPED-SILENT | Noise threshold; no engine target (adaptive sampling not wired). |
| `scene.cycles.adaptive_min_samples` | `—` | `(none)` | dropped | DROPPED-SILENT | No custom prop and no engine target. |
| `scene.cycles.seed` | `—` | `renderer.set_seed` | direct | DROPPED-SILENT | pkg119-A marked DROPPED; addon NOW reads scene.cycles.seed natively (+use_animated_seed). Seed 0 = engine random sentinel (raytracer.h). |
| `scene.cycles.sample_offset` | `—` | `(none)` | dropped | DROPPED-SILENT | Sample-offset for tiled/distributed render; no engine target. |
| `scene.cycles.pixel_filter_type` | `—` | `renderer.set_pixel_filter` | direct | n/a | Read natively today; BOX/GAUSSIAN/BLACKMAN_HARRIS -> 0/1/2. |
| `scene.cycles.filter_width` | `—` | `renderer.set_pixel_filter` | direct | DROPPED-SILENT | pkg119-A marked DROPPED; addon NOW reads scene.cycles.filter_width natively. |
| `scene.cycles.use_light_tree` | `custom_raytracer.light_sampler` | `renderer.set_light_sampler` | approximated | n/a | SEMANTIC MISMATCH: Astroray has uniform/power/light_tree tri-state; Cycles exposes only a use_light_tree bool (+light_sampling_threshold). Stays custom-only until reconciled (Stage 1 rule). |

## Light Paths & Clamping (scene.cycles.*)

| Native Blender/Cycles | Current custom prop | Astroray target (neutral) | Status | pkg119-A | Note |
|---|---|---|---|---|---|
| `scene.cycles.max_bounces` | `custom_raytracer.max_bounces` | `render(max_bounces=...)` | direct | DROPPED-SILENT | Custom duplicate shadows native; Stage 1 reads scene.cycles.max_bounces. |
| `scene.cycles.diffuse_bounces` | `custom_raytracer.diffuse_bounces` | `render(diffuse_bounces=...)` | direct | DROPPED-SILENT | Custom duplicate shadows native. |
| `scene.cycles.glossy_bounces` | `custom_raytracer.glossy_bounces` | `render(glossy_bounces=...)` | direct | DROPPED-SILENT | Custom duplicate shadows native. |
| `scene.cycles.transmission_bounces` | `custom_raytracer.transmission_bounces` | `render(transmission_bounces=...)` | direct | DROPPED-SILENT | Custom duplicate shadows native. |
| `scene.cycles.volume_bounces` | `custom_raytracer.volume_bounces` | `render(volume_bounces=...)` | direct | DROPPED-SILENT | Custom duplicate shadows native; volume transport is itself only partially implemented. |
| `scene.cycles.transparent_max_bounces` | `custom_raytracer.transparent_bounces` | `render(transparent_bounces=...)` | direct | DROPPED-SILENT | NAME MISMATCH: custom prop is 'transparent_bounces', Cycles is 'transparent_max_bounces'. |
| `scene.cycles.sample_clamp_direct` | `custom_raytracer.clamp_direct` | `renderer.set_clamp_direct` | direct | n/a | Cycles prop is 'sample_clamp_direct'; 0 disables. Custom duplicate shadows it. |
| `scene.cycles.sample_clamp_indirect` | `custom_raytracer.clamp_indirect` | `renderer.set_clamp_indirect` | direct | n/a | Cycles prop is 'sample_clamp_indirect'; 0 disables. Custom duplicate shadows it. |
| `scene.cycles.blur_glossy` | `custom_raytracer.filter_glossy` | `renderer.set_filter_glossy` | direct | n/a | Cycles 'Filter Glossy' is the 'blur_glossy' prop. Custom duplicate shadows it. |
| `scene.cycles.caustics_reflective` | `custom_raytracer.use_reflective_caustics` | `renderer.set_use_reflective_caustics` | direct | DROPPED-SILENT | Custom duplicate shadows native. |
| `scene.cycles.caustics_refractive` | `custom_raytracer.use_refractive_caustics` | `renderer.set_use_refractive_caustics` | direct | DROPPED-SILENT | Custom duplicate shadows native. |
| `scene.cycles.use_fast_gi` | `—` | `(none)` | dropped | DROPPED-SILENT | Fast GI approximation not implemented; no engine target. |
| `scene.world.light_settings.max_bounces` | `—` | `renderer.set_world_max_bounces` | direct | n/a | Read natively today from world.light_settings.max_bounces. |

## Film (scene.render.* / scene.cycles.film_*)

| Native Blender/Cycles | Current custom prop | Astroray target (neutral) | Status | pkg119-A | Note |
|---|---|---|---|---|---|
| `scene.cycles.film_exposure` | `—` | `renderer.set_film_exposure` | direct | DROPPED-SILENT | pkg119-A marked DROPPED; addon NOW reads scene.cycles.film_exposure natively. |
| `scene.render.film_transparent` | `—` | `renderer.set_use_transparent_film` | direct | SUPPORTED | Read natively from scene.render.film_transparent. |
| `scene.cycles.film_transparent_glass` | `—` | `renderer.set_transparent_glass` | direct | n/a | Read natively from scene.cycles.film_transparent_glass. |

## Color Management (scene.view_settings.*)  — GAP class

| Native Blender/Cycles | Current custom prop | Astroray target (neutral) | Status | pkg119-A | Note |
|---|---|---|---|---|---|
| `scene.view_settings.view_transform` | `—` | `(none)` | dropped | n/a | GAP: engine applies its own gamma (render applyGamma) and ignores AgX/Filmic view transforms. Not in pkg119-A allow-list; steering wheel needs it (Stage 3 + pkg119-C). |
| `scene.view_settings.look` | `—` | `(none)` | dropped | n/a | Color-management 'look' contrast presets ignored. |
| `scene.view_settings.exposure` | `—` | `(none)` | dropped | n/a | View-transform exposure (stops) is distinct from cycles.film_exposure; currently ignored. |
| `scene.view_settings.gamma` | `—` | `(none)` | dropped | n/a | Color-management gamma ignored (engine gamma is fixed). |

## Denoising (scene.cycles.*)

| Native Blender/Cycles | Current custom prop | Astroray target (neutral) | Status | pkg119-A | Note |
|---|---|---|---|---|---|
| `scene.cycles.use_denoising` | `custom_raytracer.use_denoising` | `render_denoise_pass` | direct | SUPPORTED | Custom duplicate shadows native final-render denoise toggle. |
| `scene.cycles.denoiser` | `custom_raytracer.denoiser_backend` | `resolve_denoiser_pass` | approximated | SUPPORTED | Cycles enum OPTIX/OPENIMAGEDENOISE maps to Astroray auto/optix/oidn; Astroray adds 'auto'. |
| `scene.cycles.use_preview_denoising` | `custom_raytracer.viewport_oidn` | `viewport denoise` | approximated | n/a | Viewport denoise toggle; native counterpart is use_preview_denoising. |
| `scene.cycles.denoising_input_passes` | `—` | `(none)` | dropped | DROPPED-SILENT | Albedo/normal guide-pass selection not exposed to the denoiser call. |

## World (scene.world node tree)

| Native Blender/Cycles | Current custom prop | Astroray target (neutral) | Status | pkg119-A | Note |
|---|---|---|---|---|---|
| `scene.world.use_nodes` | `—` | `setup_world (node walk)` | direct | SUPPORTED | World node tree is the sole source; TEX_ENVIRONMENT/BACKGROUND/MAPPING walked (pkg63). |
| `world BACKGROUND node Strength` | `—` | `load_environment_map / set_background_color` | direct | n/a | Read from the world node tree, not a datablock prop. |
| `world BACKGROUND node Color` | `—` | `set_background_color / HDRI tint` | direct | n/a | Solid bg when no HDRI; multiplicative tint when HDRI present. |
| `world MAPPING node Rotation` | `—` | `load_environment_map (baked rotation)` | direct | n/a | XYZ Euler baked into HDRI rotation matrix. |

## Camera datablock (camera.data.*)

| Native Blender/Cycles | Current custom prop | Astroray target (neutral) | Status | pkg119-A | Note |
|---|---|---|---|---|---|
| `camera.data.lens` | `—` | `setup_camera(vfov)` | direct | SUPPORTED | Focal length -> vertical FOV via sensor fit. |
| `camera.data.sensor_width` | `—` | `setup_camera` | direct | SUPPORTED |  |
| `camera.data.sensor_height` | `—` | `setup_camera` | direct | SUPPORTED |  |
| `camera.data.shift_x` | `—` | `setup_camera` | direct | SUPPORTED |  |
| `camera.data.shift_y` | `—` | `setup_camera` | direct | SUPPORTED |  |
| `camera.data.dof.aperture_fstop` | `—` | `setup_camera (DoF)` | direct | SUPPORTED | Thin-lens f-stop -> aperture radius. |
| `camera.data.dof.aperture_blades` | `—` | `(none)` | dropped | DROPPED-SILENT | Bokeh blade count ignored (circular aperture only). |
| `camera.data.dof.aperture_rotation` | `—` | `(none)` | dropped | DROPPED-SILENT | Bokeh rotation ignored. |
| `camera.data.dof.aperture_ratio` | `—` | `(none)` | dropped | DROPPED-SILENT | Anamorphic bokeh ratio ignored. |
| `camera.data.type` | `—` | `(none)` | dropped | DROPPED-SILENT | PERSP/ORTHO/PANO ignored; engine assumes perspective. |
| `camera.data.clip_start` | `—` | `(none)` | dropped | DROPPED-SILENT | Near clip ignored. |
| `camera.data.clip_end` | `—` | `(none)` | dropped | DROPPED-SILENT | Far clip ignored. |

## Lights (light.data.*, across POINT/SUN/SPOT/AREA)

| Native Blender/Cycles | Current custom prop | Astroray target (neutral) | Status | pkg119-A | Note |
|---|---|---|---|---|---|
| `light.data.energy` | `—` | `add_*_light (power)` | direct | SUPPORTED | Applies to POINT/SUN/SPOT/AREA. Known ~3x energy-scale divergence vs Cycles (pkg89/pkg115). |
| `light.data.color` | `—` | `add_*_light` | direct | SUPPORTED | All light types. |
| `light.data.use_temperature` | `—` | `add_*_light` | direct | SUPPORTED | Blackbody toggle; all types. |
| `light.data.temperature` | `—` | `add_*_light` | direct | SUPPORTED | Blackbody Kelvin; all types. |
| `light.data.shadow_soft_size` | `—` | `add_point_light (radius)` | direct | SUPPORTED | POINT soft size. |
| `light.data.angle` | `—` | `add_sun_light (angular radius)` | direct | SUPPORTED | SUN angular diameter. |
| `light.data.spot_size` | `—` | `add_spot_light` | direct | SUPPORTED | SPOT cone. |
| `light.data.spot_blend` | `—` | `add_spot_light` | direct | SUPPORTED | SPOT falloff. |
| `light.data.shape` | `—` | `add_area_light` | direct | SUPPORTED | AREA shape. |
| `light.data.size` | `—` | `add_area_light` | direct | SUPPORTED | AREA size. |
| `light.data.size_y` | `—` | `add_area_light` | direct | SUPPORTED | AREA size Y. |
| `light.data.spread` | `—` | `add_area_light` | direct | SUPPORTED | AREA spread. |
| `light.data.specular_factor` | `—` | `(none)` | dropped | DROPPED-SILENT | Per-light specular multiplier ignored; all light types (POINT/SUN/SPOT/AREA). |
| `light.data.show_cone` | `—` | `(none)` | dropped | DROPPED-SILENT | SPOT viewport-only gizmo; not render-relevant. |

## Material — Principled BSDF steering wheel (full socket list: pkg119-A matrix)

| Native Blender/Cycles | Current custom prop | Astroray target (neutral) | Status | pkg119-A | Note |
|---|---|---|---|---|---|
| `Principled BSDF: Base Color` | `—` | `material spec base_color` | direct | SUPPORTED |  |
| `Principled BSDF: Metallic` | `—` | `material spec metallic` | direct | SUPPORTED |  |
| `Principled BSDF: Roughness` | `—` | `material spec roughness` | direct | SUPPORTED |  |
| `Principled BSDF: IOR` | `—` | `material spec ior` | direct | SUPPORTED |  |
| `Principled BSDF: Normal` | `—` | `material spec normal map` | direct | SUPPORTED |  |
| `Principled BSDF: Anisotropic` | `—` | `material spec anisotropy` | direct | SUPPORTED |  |
| `Principled BSDF: Subsurface Weight` | `—` | `material spec subsurface` | direct | SUPPORTED |  |
| `Principled BSDF: Transmission Weight` | `—` | `material spec transmission` | direct | SUPPORTED |  |
| `Principled BSDF: Coat Weight` | `—` | `material spec coat` | direct | SUPPORTED |  |
| `Principled BSDF: Coat Roughness` | `—` | `material spec coat_roughness` | direct | SUPPORTED |  |
| `Principled BSDF: Sheen Weight` | `—` | `material spec sheen` | direct | SUPPORTED |  |
| `Principled BSDF: Emission Color` | `—` | `material spec emission` | direct | SUPPORTED |  |
| `Principled BSDF: Emission Strength` | `—` | `material spec emission_strength` | direct | SUPPORTED |  |
| `Principled BSDF: Alpha` | `—` | `(none)` | dropped | DROPPED-SILENT | Alpha transparency socket ignored; representative of the DROPPED Principled sockets (Specular IOR Level, Coat IOR/Tint/Normal, Sheen Roughness/Tint, Thin Film, Subsurface Radius/Scale/IOR/Anisotropy, Anisotropic Rotation, Diffuse Roughness). See pkg119-A matrix for the full per-socket list. |

## ASTRORAY-ONLY (no native home; stays on the one custom panel)

| Native Blender/Cycles | Current custom prop | Astroray target (neutral) | Status | pkg119-A | Note |
|---|---|---|---|---|---|
| `wavelength_preset` | `custom_raytracer.wavelength_preset` | `wavelength band + integrator selection` | astroray-only | n/a | Spectral render band (visible/near_ir/uv/custom); no Cycles equivalent. |
| `wavelength_min` | `custom_raytracer.wavelength_min` | `wavelength band min (nm)` | astroray-only | n/a | Custom spectral band lower bound. |
| `wavelength_max` | `custom_raytracer.wavelength_max` | `wavelength band max (nm)` | astroray-only | n/a | Custom spectral band upper bound. |
| `colourmap` | `custom_raytracer.colourmap` | `output colourmap` | astroray-only | n/a | False-colour palette for non-visible renders. |
| `integrator_type` | `custom_raytracer.integrator_type` | `render(integrator=...)` | astroray-only | n/a | Plugin-registry integrator selector; Cycles has no equivalent (progressive/branched removed). |
| `scene.cycles.device` | `custom_raytracer.device_mode` | `renderer.set_use_gpu` | astroray-only | n/a | SEMANTIC MISMATCH: native scene.cycles.device is CPU/GPU only; Astroray adds an 'auto' safe-fallback tri-state. Kept custom until reconciled (Stage 1 mismatch rule). |
| `viewport_display_pass` | `custom_raytracer.viewport_display_pass` | `viewport pass selector` | astroray-only | n/a | Which AOV to show in the viewport; engine-specific. |
| `view_layer.pass_cryptomatte_depth` | `custom_raytracer.cryptomatte_depth` | `cryptomatte depth` | approximated | n/a | Native counterpart exists (view_layer.pass_cryptomatte_depth); currently a custom duplicate. |
| `black_hole` | `object.astroray_black_hole (PropertyGroup)` | `GR/accretion object params` | astroray-only | n/a | GR/Kerr black-hole objects (mass/spin/accretion model/jets); wholly engine-unique. |
| `is_caustic_caster` | `object.astroray (is_caustic_caster)` | `SMS caustic caster opt-in` | astroray-only | n/a | Loosely mirrors Cycles is_caustics_caster but is an Astroray SMS opt-in (behaviour only). |

## Route-2 session-boundary compliance (dcc-integration-decision-2026-08 §6)

The Stage-0 design was checked against all five owner-ratified (2026-08-08) hard rules:

1. **No `bpy` below the translation line.** `settings_map.py` is pure data and imports no `bpy`; enforced by `test_source_has_no_bpy_import`.
2. **Session surface stays host-neutral.** The `Astroray target` column names Renderer setters / `render()` args / neutral phrases — never a `scene.cycles.*` property group or datablock; spot-checked by `test_neutral_targets_are_host_neutral`.
3. **The mapping table is the single source of translation policy, on the translator side.** It lives in `blender_addon/settings_map.py` (translator side); later stages import it. A second host reads this table to learn what Blender's steering wheel meant.
4. **Retirement preserves neutral values.** Every `direct`/`approximated` row already names a durable `neutral_param`; Stage 4 collapses the `custom_prop` duplicate into the native read *above* the boundary without removing any engine capability below it.
5. **No standalone C API / second-consumer framework.** Stage 0 adds a data module, a doc, and a test — no framework, no C API.

