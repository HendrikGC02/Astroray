"""pkg176 Stage 0 — Cycles-settings -> Astroray-parameter mapping table.

This module is the SINGLE SOURCE OF TRANSLATION POLICY for the "Blender as the
steering wheel" work (pkg176). It records, for every native Blender/Cycles
setting the steering wheel needs, which host-neutral engine/session parameter it
drives, and whether the mapping is direct, approximated, dropped, or has no
native home (ASTRORAY-ONLY).

Route-2 session-boundary discipline (dcc-integration-decision-2026-08 §6):
  * This module lives on the TRANSLATOR side and is pure DATA — it MUST NOT
    ``import bpy`` and MUST NOT call the engine. (Rule 1, Rule 3.)
  * ``neutral_param`` names the HOST-NEUTRAL session target (a pybind
    ``Renderer`` setter or a ``render()`` argument), never a Blender datablock.
    A second host (Houdini adapter / hdAstroray) reads THIS table to learn what
    Blender's steering wheel *meant*, then maps its own controls to the same
    neutral values. (Rule 2, Rule 3.)
  * It is inert in Stage 0: nothing imports it yet. Stage 1 makes the exporter
    read native properties per this table; Stage 4 collapses the custom_prop
    duplicates into the native read *above* the boundary without removing any
    neutral_param capability below it. (Rule 4.)
  * No framework, no C API — this is a data module and a naming rule only.
    (Rule 5.)

Grounding: the ``status`` / ``pkg119a`` columns reuse the pkg119 Phase A
coverage matrix (docs/blender_parity/coverage_matrix.json — 117 SUPPORTED /
22 APPROXIMATED / 385 DROPPED-SILENT as of PR #487). Where the current addon
has since diverged from the matrix (some native reads were added by later
packages, e.g. pkg88/pkg103b wired ``scene.cycles.seed`` / ``film_exposure`` /
``filter_width`` natively), the ``note`` says so — the matrix classification is
kept verbatim in ``pkg119a`` as the audit anchor, and ``status`` reflects the
current translation reality the owner is asked to ratify.
"""

from __future__ import annotations

from typing import NamedTuple

# Mapping status vocabulary (opinionated, owner-ratified in Stage 0 review):
#   "direct"        - native value drives the neutral param 1:1 (unit-exact or
#                     documented trivial conversion).
#   "approximated"  - native value drives a nearest engine behaviour; lossy or
#                     semantically narrower/wider. MUST warn (pkg119-C) once wired.
#   "dropped"       - native value has no engine target today; DROPPED-SILENT in
#                     pkg119-A. The steering wheel must stop dropping these
#                     silently (Stage 1/3 + pkg119-C).
#   "astroray-only" - genuinely engine-unique control with no native Blender
#                     home; stays on the one custom "Astroray" panel (Stage 4).
STATUS_VALUES = ("direct", "approximated", "dropped", "astroray-only")

# pkg119-A classification vocabulary, reused verbatim as the audit anchor.
PKG119A_VALUES = ("SUPPORTED", "APPROXIMATED", "DROPPED-SILENT", "n/a")


class MappingEntry(NamedTuple):
    category: str        # render/sampling/light_paths/film/color_mgmt/world/camera/light/material
    native_prop: str     # Blender/Cycles property id (matches pkg119-A socket_or_prop for settings)
    cycles_path: str     # full native access path, e.g. "scene.cycles.samples"
    custom_prop: str     # current shadowing custom prop, "" if native-only / ASTRORAY-ONLY
    neutral_param: str   # host-neutral session target (Renderer setter / render() arg / "(none)")
    status: str          # one of STATUS_VALUES
    pkg119a: str         # one of PKG119A_VALUES
    note: str            # one-line note where non-obvious or lossy


# ---------------------------------------------------------------------------
# Render / sampling  (scene.cycles.* + scene.render.*)
# ---------------------------------------------------------------------------
_RENDER_SAMPLING = [
    MappingEntry("render", "resolution_x", "scene.render.resolution_x", "",
                 "render(width=...)", "direct", "n/a",
                 "Read natively today (x resolution_percentage); not a custom duplicate."),
    MappingEntry("render", "resolution_y", "scene.render.resolution_y", "",
                 "render(height=...)", "direct", "n/a",
                 "Read natively today (x resolution_percentage)."),
    MappingEntry("sampling", "samples", "scene.cycles.samples", "custom_raytracer.samples",
                 "render(samples=...)", "direct", "SUPPORTED",
                 "Custom duplicate shadows native; Stage 1 reads scene.cycles.samples."),
    MappingEntry("sampling", "preview_samples", "scene.cycles.preview_samples",
                 "custom_raytracer.preview_samples", "render(samples=...) [viewport]",
                 "direct", "n/a", "Viewport spp; native Cycles preview_samples is the counterpart."),
    MappingEntry("sampling", "use_adaptive_sampling", "scene.cycles.use_adaptive_sampling",
                 "custom_raytracer.use_adaptive_sampling", "(none)", "dropped", "DROPPED-SILENT",
                 "Custom toggle exists but is not plumbed to the engine; no adaptive-sampling session arg yet."),
    MappingEntry("sampling", "adaptive_threshold", "scene.cycles.adaptive_threshold",
                 "custom_raytracer.adaptive_threshold", "(none)", "dropped", "DROPPED-SILENT",
                 "Noise threshold; no engine target (adaptive sampling not wired)."),
    MappingEntry("sampling", "adaptive_min_samples", "scene.cycles.adaptive_min_samples", "",
                 "(none)", "dropped", "DROPPED-SILENT", "No custom prop and no engine target."),
    MappingEntry("sampling", "seed", "scene.cycles.seed", "",
                 "renderer.set_seed", "direct", "DROPPED-SILENT",
                 "pkg119-A marked DROPPED; addon NOW reads scene.cycles.seed natively (+use_animated_seed). "
                 "Seed 0 = engine random sentinel (raytracer.h)."),
    MappingEntry("sampling", "sample_offset", "scene.cycles.sample_offset", "",
                 "(none)", "dropped", "DROPPED-SILENT", "Sample-offset for tiled/distributed render; no engine target."),
    MappingEntry("sampling", "pixel_filter_type", "scene.cycles.pixel_filter_type", "",
                 "renderer.set_pixel_filter", "direct", "n/a",
                 "Read natively today; BOX/GAUSSIAN/BLACKMAN_HARRIS -> 0/1/2."),
    MappingEntry("sampling", "filter_width", "scene.cycles.filter_width", "",
                 "renderer.set_pixel_filter", "direct", "DROPPED-SILENT",
                 "pkg119-A marked DROPPED; addon NOW reads scene.cycles.filter_width natively."),
    MappingEntry("sampling", "light_sampling", "scene.cycles.use_light_tree",
                 "custom_raytracer.light_sampler", "renderer.set_light_sampler", "approximated", "n/a",
                 "SEMANTIC MISMATCH: Astroray's UI has a uniform/power/light_tree tri-state; Cycles exposes only "
                 "a use_light_tree bool, and the ENGINE's set_light_sampler accepts only 'power'/'tree' (no uniform "
                 "sampler). pkg201 Stage 1 reconciles in native_settings.resolve_light_sampler: native True -> "
                 "'tree', native False -> 'power'. Stays APPROXIMATED (neither Cycles nor the engine can express "
                 "uniform vs power)."),
]

# ---------------------------------------------------------------------------
# Light paths / bounces  (scene.cycles.*_bounces)
# ---------------------------------------------------------------------------
_LIGHT_PATHS = [
    MappingEntry("light_paths", "max_bounces", "scene.cycles.max_bounces",
                 "custom_raytracer.max_bounces", "render(max_bounces=...)", "direct", "DROPPED-SILENT",
                 "Custom duplicate shadows native; Stage 1 reads scene.cycles.max_bounces."),
    MappingEntry("light_paths", "diffuse_bounces", "scene.cycles.diffuse_bounces",
                 "custom_raytracer.diffuse_bounces", "render(diffuse_bounces=...)", "direct", "DROPPED-SILENT",
                 "Custom duplicate shadows native."),
    MappingEntry("light_paths", "glossy_bounces", "scene.cycles.glossy_bounces",
                 "custom_raytracer.glossy_bounces", "render(glossy_bounces=...)", "direct", "DROPPED-SILENT",
                 "Custom duplicate shadows native."),
    MappingEntry("light_paths", "transmission_bounces", "scene.cycles.transmission_bounces",
                 "custom_raytracer.transmission_bounces", "render(transmission_bounces=...)", "direct", "DROPPED-SILENT",
                 "Custom duplicate shadows native."),
    MappingEntry("light_paths", "volume_bounces", "scene.cycles.volume_bounces",
                 "custom_raytracer.volume_bounces", "render(volume_bounces=...)", "direct", "DROPPED-SILENT",
                 "Custom duplicate shadows native; volume transport is itself only partially implemented."),
    MappingEntry("light_paths", "transparent_max_bounces", "scene.cycles.transparent_max_bounces",
                 "custom_raytracer.transparent_bounces", "render(transparent_bounces=...)", "direct", "DROPPED-SILENT",
                 "NAME MISMATCH: custom prop is 'transparent_bounces', Cycles is 'transparent_max_bounces'."),
    MappingEntry("light_paths", "sample_clamp_direct", "scene.cycles.sample_clamp_direct",
                 "custom_raytracer.clamp_direct", "renderer.set_clamp_direct", "direct", "n/a",
                 "Cycles prop is 'sample_clamp_direct'; 0 disables. Custom duplicate shadows it."),
    MappingEntry("light_paths", "sample_clamp_indirect", "scene.cycles.sample_clamp_indirect",
                 "custom_raytracer.clamp_indirect", "renderer.set_clamp_indirect", "direct", "n/a",
                 "Cycles prop is 'sample_clamp_indirect'; 0 disables. Custom duplicate shadows it."),
    MappingEntry("light_paths", "blur_glossy", "scene.cycles.blur_glossy",
                 "custom_raytracer.filter_glossy", "renderer.set_filter_glossy", "direct", "n/a",
                 "Cycles 'Filter Glossy' is the 'blur_glossy' prop. Custom duplicate shadows it."),
    MappingEntry("light_paths", "caustics_reflective", "scene.cycles.caustics_reflective",
                 "custom_raytracer.use_reflective_caustics", "renderer.set_use_reflective_caustics",
                 "direct", "DROPPED-SILENT", "Custom duplicate shadows native."),
    MappingEntry("light_paths", "caustics_refractive", "scene.cycles.caustics_refractive",
                 "custom_raytracer.use_refractive_caustics", "renderer.set_use_refractive_caustics",
                 "direct", "DROPPED-SILENT", "Custom duplicate shadows native."),
    MappingEntry("light_paths", "use_fast_gi", "scene.cycles.use_fast_gi", "",
                 "(none)", "dropped", "DROPPED-SILENT",
                 "Fast GI approximation not implemented; no engine target."),
    MappingEntry("light_paths", "world_max_bounces", "scene.world.cycles.max_bounces", "",
                 "renderer.set_world_max_bounces", "direct", "n/a",
                 "Read natively from world.cycles.max_bounces (pkg201 Finding B; the "
                 "prior read used world.light_settings.max_bounces, the AO datablock "
                 "which has no max_bounces member, so the control was inert)."),
]

# ---------------------------------------------------------------------------
# Film / color management  (scene.render.* + scene.cycles.film_* + scene.view_settings.*)
# ---------------------------------------------------------------------------
_FILM_COLOR = [
    MappingEntry("film", "film_exposure", "scene.cycles.film_exposure", "",
                 "renderer.set_film_exposure", "direct", "DROPPED-SILENT",
                 "pkg119-A marked DROPPED; addon NOW reads scene.cycles.film_exposure natively."),
    MappingEntry("film", "film_transparent", "scene.render.film_transparent", "",
                 "renderer.set_use_transparent_film", "direct", "SUPPORTED",
                 "Read natively from scene.render.film_transparent."),
    MappingEntry("film", "film_transparent_glass", "scene.cycles.film_transparent_glass", "",
                 "renderer.set_transparent_glass", "direct", "n/a",
                 "Read natively from scene.cycles.film_transparent_glass."),
    MappingEntry("color_mgmt", "view_transform", "scene.view_settings.view_transform", "",
                 "(none)", "dropped", "n/a",
                 "GAP: engine applies its own gamma (render applyGamma) and ignores AgX/Filmic view "
                 "transforms. Not in pkg119-A allow-list; steering wheel needs it (Stage 3 + pkg119-C)."),
    MappingEntry("color_mgmt", "look", "scene.view_settings.look", "",
                 "(none)", "dropped", "n/a", "Color-management 'look' contrast presets ignored."),
    MappingEntry("color_mgmt", "exposure", "scene.view_settings.exposure", "",
                 "(none)", "dropped", "n/a",
                 "View-transform exposure (stops) is distinct from cycles.film_exposure; currently ignored."),
    MappingEntry("color_mgmt", "gamma", "scene.view_settings.gamma", "",
                 "(none)", "dropped", "n/a", "Color-management gamma ignored (engine gamma is fixed)."),
]

# ---------------------------------------------------------------------------
# Denoising  (scene.cycles.*)
# ---------------------------------------------------------------------------
_DENOISING = [
    MappingEntry("denoising", "use_denoising", "scene.cycles.use_denoising",
                 "custom_raytracer.use_denoising", "render_denoise_pass", "direct", "SUPPORTED",
                 "Custom duplicate shadows native final-render denoise toggle."),
    MappingEntry("denoising", "denoiser", "scene.cycles.denoiser",
                 "custom_raytracer.denoiser_backend", "resolve_denoiser_pass", "approximated", "SUPPORTED",
                 "Cycles enum OPTIX/OPENIMAGEDENOISE maps to Astroray auto/optix/oidn; Astroray adds 'auto'."),
    MappingEntry("denoising", "use_preview_denoising", "scene.cycles.use_preview_denoising",
                 "custom_raytracer.viewport_oidn", "viewport denoise", "approximated", "n/a",
                 "Viewport denoise toggle; native counterpart is use_preview_denoising."),
    MappingEntry("denoising", "denoising_input_passes", "scene.cycles.denoising_input_passes", "",
                 "(none)", "dropped", "DROPPED-SILENT",
                 "Albedo/normal guide-pass selection not exposed to the denoiser call."),
]

# ---------------------------------------------------------------------------
# World  (scene.world node tree)
# ---------------------------------------------------------------------------
_WORLD = [
    MappingEntry("world", "use_nodes", "scene.world.use_nodes", "",
                 "setup_world (node walk)", "direct", "SUPPORTED",
                 "World node tree is the sole source; TEX_ENVIRONMENT/BACKGROUND/MAPPING walked (pkg63)."),
    MappingEntry("world", "background_strength", "world BACKGROUND node Strength", "",
                 "load_environment_map / set_background_color", "direct", "n/a",
                 "Read from the world node tree, not a datablock prop."),
    MappingEntry("world", "background_color", "world BACKGROUND node Color", "",
                 "set_background_color / HDRI tint", "direct", "n/a",
                 "Solid bg when no HDRI; multiplicative tint when HDRI present."),
    MappingEntry("world", "mapping_rotation", "world MAPPING node Rotation", "",
                 "load_environment_map (baked rotation)", "direct", "n/a",
                 "XYZ Euler baked into HDRI rotation matrix."),
]

# ---------------------------------------------------------------------------
# Camera datablock  (scene.camera.data.*)
# ---------------------------------------------------------------------------
_CAMERA = [
    MappingEntry("camera", "lens", "camera.data.lens", "", "setup_camera(vfov)", "direct", "SUPPORTED",
                 "Focal length -> vertical FOV via sensor fit."),
    MappingEntry("camera", "sensor_width", "camera.data.sensor_width", "", "setup_camera", "direct", "SUPPORTED", ""),
    MappingEntry("camera", "sensor_height", "camera.data.sensor_height", "", "setup_camera", "direct", "SUPPORTED", ""),
    MappingEntry("camera", "shift_x", "camera.data.shift_x", "", "setup_camera", "direct", "SUPPORTED", ""),
    MappingEntry("camera", "shift_y", "camera.data.shift_y", "", "setup_camera", "direct", "SUPPORTED", ""),
    MappingEntry("camera", "aperture_fstop", "camera.data.dof.aperture_fstop", "",
                 "setup_camera (DoF)", "direct", "SUPPORTED", "Thin-lens f-stop -> aperture radius."),
    MappingEntry("camera", "aperture_blades", "camera.data.dof.aperture_blades", "",
                 "(none)", "dropped", "DROPPED-SILENT", "Bokeh blade count ignored (circular aperture only)."),
    MappingEntry("camera", "aperture_rotation", "camera.data.dof.aperture_rotation", "",
                 "(none)", "dropped", "DROPPED-SILENT", "Bokeh rotation ignored."),
    MappingEntry("camera", "aperture_ratio", "camera.data.dof.aperture_ratio", "",
                 "(none)", "dropped", "DROPPED-SILENT", "Anamorphic bokeh ratio ignored."),
    MappingEntry("camera", "type", "camera.data.type", "",
                 "(none)", "dropped", "DROPPED-SILENT",
                 "PERSP/ORTHO/PANO ignored; engine assumes perspective."),
    MappingEntry("camera", "clip_start", "camera.data.clip_start", "",
                 "(none)", "dropped", "DROPPED-SILENT", "Near clip ignored."),
    MappingEntry("camera", "clip_end", "camera.data.clip_end", "",
                 "(none)", "dropped", "DROPPED-SILENT", "Far clip ignored."),
]

# ---------------------------------------------------------------------------
# Light datablocks  (one row per distinct property; applies across light types)
# ---------------------------------------------------------------------------
_LIGHT = [
    MappingEntry("light", "energy", "light.data.energy", "", "add_*_light (power)", "direct", "SUPPORTED",
                 "Applies to POINT/SUN/SPOT/AREA. Known ~3x energy-scale divergence vs Cycles (pkg89/pkg115)."),
    MappingEntry("light", "color", "light.data.color", "", "add_*_light", "direct", "SUPPORTED",
                 "All light types."),
    MappingEntry("light", "use_temperature", "light.data.use_temperature", "", "add_*_light", "direct", "SUPPORTED",
                 "Blackbody toggle; all types."),
    MappingEntry("light", "temperature", "light.data.temperature", "", "add_*_light", "direct", "SUPPORTED",
                 "Blackbody Kelvin; all types."),
    MappingEntry("light", "shadow_soft_size", "light.data.shadow_soft_size", "", "add_point_light (radius)",
                 "direct", "SUPPORTED", "POINT soft size."),
    MappingEntry("light", "angle", "light.data.angle", "", "add_sun_light (angular radius)", "direct", "SUPPORTED",
                 "SUN angular diameter."),
    MappingEntry("light", "spot_size", "light.data.spot_size", "", "add_spot_light", "direct", "SUPPORTED", "SPOT cone."),
    MappingEntry("light", "spot_blend", "light.data.spot_blend", "", "add_spot_light", "direct", "SUPPORTED", "SPOT falloff."),
    MappingEntry("light", "shape", "light.data.shape", "", "add_area_light", "direct", "SUPPORTED", "AREA shape."),
    MappingEntry("light", "size", "light.data.size", "", "add_area_light", "direct", "SUPPORTED", "AREA size."),
    MappingEntry("light", "size_y", "light.data.size_y", "", "add_area_light", "direct", "SUPPORTED", "AREA size Y."),
    MappingEntry("light", "spread", "light.data.spread", "", "add_area_light", "direct", "SUPPORTED", "AREA spread."),
    MappingEntry("light", "specular_factor", "light.data.specular_factor", "",
                 "(none)", "dropped", "DROPPED-SILENT",
                 "Per-light specular multiplier ignored; all light types (POINT/SUN/SPOT/AREA)."),
    MappingEntry("light", "show_cone", "light.data.show_cone", "",
                 "(none)", "dropped", "DROPPED-SILENT", "SPOT viewport-only gizmo; not render-relevant."),
]

# ---------------------------------------------------------------------------
# Material / socket layer (steering wheel = Principled BSDF sockets).
# The FULL socket-level classification (461 shader-node rows) is the pkg119-A
# matrix (docs/blender_parity/coverage_matrix.json / report.md) — the authoritative
# source; it is NOT re-typed here. Below is the primary material steering wheel:
# the Principled BSDF sockets Astroray honours, plus the notable dropped ones.
# ---------------------------------------------------------------------------
_MATERIAL_PRINCIPLED = [
    MappingEntry("material", "Base Color", "Principled BSDF: Base Color", "",
                 "material spec base_color", "direct", "SUPPORTED", ""),
    MappingEntry("material", "Metallic", "Principled BSDF: Metallic", "",
                 "material spec metallic", "direct", "SUPPORTED", ""),
    MappingEntry("material", "Roughness", "Principled BSDF: Roughness", "",
                 "material spec roughness", "direct", "SUPPORTED", ""),
    MappingEntry("material", "IOR", "Principled BSDF: IOR", "",
                 "material spec ior", "direct", "SUPPORTED", ""),
    MappingEntry("material", "Normal", "Principled BSDF: Normal", "",
                 "material spec normal map", "direct", "SUPPORTED", ""),
    MappingEntry("material", "Anisotropic", "Principled BSDF: Anisotropic", "",
                 "material spec anisotropy", "direct", "SUPPORTED", ""),
    MappingEntry("material", "Subsurface Weight", "Principled BSDF: Subsurface Weight", "",
                 "material spec subsurface", "direct", "SUPPORTED", ""),
    MappingEntry("material", "Transmission Weight", "Principled BSDF: Transmission Weight", "",
                 "material spec transmission", "direct", "SUPPORTED", ""),
    MappingEntry("material", "Coat Weight", "Principled BSDF: Coat Weight", "",
                 "material spec coat", "direct", "SUPPORTED", ""),
    MappingEntry("material", "Coat Roughness", "Principled BSDF: Coat Roughness", "",
                 "material spec coat_roughness", "direct", "SUPPORTED", ""),
    MappingEntry("material", "Sheen Weight", "Principled BSDF: Sheen Weight", "",
                 "material spec sheen", "direct", "SUPPORTED", ""),
    MappingEntry("material", "Emission Color", "Principled BSDF: Emission Color", "",
                 "material spec emission", "direct", "SUPPORTED", ""),
    MappingEntry("material", "Emission Strength", "Principled BSDF: Emission Strength", "",
                 "material spec emission_strength", "direct", "SUPPORTED", ""),
    MappingEntry("material", "Alpha", "Principled BSDF: Alpha", "",
                 "(none)", "dropped", "DROPPED-SILENT",
                 "Alpha transparency socket ignored; representative of the DROPPED Principled sockets "
                 "(Specular IOR Level, Coat IOR/Tint/Normal, Sheen Roughness/Tint, Thin Film, "
                 "Subsurface Radius/Scale/IOR/Anisotropy, Anisotropic Rotation, Diffuse Roughness). "
                 "See pkg119-A matrix for the full per-socket list."),
]

# ---------------------------------------------------------------------------
# ASTRORAY-ONLY  (genuinely engine-unique; no native Blender home; stays on the
# single custom 'Astroray' panel after Stage 4 retirement).
# ---------------------------------------------------------------------------
_ASTRORAY_ONLY = [
    MappingEntry("astroray_only", "wavelength_preset", "", "custom_raytracer.wavelength_preset",
                 "wavelength band + integrator selection", "astroray-only", "n/a",
                 "Spectral render band (visible/near_ir/uv/custom); no Cycles equivalent."),
    MappingEntry("astroray_only", "wavelength_min", "", "custom_raytracer.wavelength_min",
                 "wavelength band min (nm)", "astroray-only", "n/a", "Custom spectral band lower bound."),
    MappingEntry("astroray_only", "wavelength_max", "", "custom_raytracer.wavelength_max",
                 "wavelength band max (nm)", "astroray-only", "n/a", "Custom spectral band upper bound."),
    MappingEntry("astroray_only", "colourmap", "", "custom_raytracer.colourmap",
                 "output colourmap", "astroray-only", "n/a", "False-colour palette for non-visible renders."),
    MappingEntry("astroray_only", "integrator_type", "", "custom_raytracer.integrator_type",
                 "render(integrator=...)", "astroray-only", "n/a",
                 "Plugin-registry integrator selector; Cycles has no equivalent (progressive/branched removed)."),
    MappingEntry("astroray_only", "device_mode", "scene.cycles.device", "custom_raytracer.device_mode",
                 "renderer.set_use_gpu", "astroray-only", "n/a",
                 "SEMANTIC MISMATCH: native scene.cycles.device is CPU/GPU only; Astroray adds an 'auto' "
                 "safe-fallback tri-state. Kept custom until reconciled (Stage 1 mismatch rule)."),
    MappingEntry("astroray_only", "viewport_display_pass", "", "custom_raytracer.viewport_display_pass",
                 "viewport pass selector", "astroray-only", "n/a", "Which AOV to show in the viewport; engine-specific."),
    MappingEntry("astroray_only", "cryptomatte_depth", "view_layer.pass_cryptomatte_depth",
                 "custom_raytracer.cryptomatte_depth", "cryptomatte depth", "approximated", "n/a",
                 "Native counterpart exists (view_layer.pass_cryptomatte_depth); currently a custom duplicate."),
    MappingEntry("astroray_only", "black_hole", "", "object.astroray_black_hole (PropertyGroup)",
                 "GR/accretion object params", "astroray-only", "n/a",
                 "GR/Kerr black-hole objects (mass/spin/accretion model/jets); wholly engine-unique."),
    MappingEntry("astroray_only", "is_caustic_caster", "", "object.astroray (is_caustic_caster)",
                 "SMS caustic caster opt-in", "astroray-only", "n/a",
                 "Loosely mirrors Cycles is_caustics_caster but is an Astroray SMS opt-in (behaviour only)."),
]


MAPPING: list[MappingEntry] = (
    _RENDER_SAMPLING
    + _LIGHT_PATHS
    + _FILM_COLOR
    + _DENOISING
    + _WORLD
    + _CAMERA
    + _LIGHT
    + _MATERIAL_PRINCIPLED
    + _ASTRORAY_ONLY
)


def by_status(status: str) -> list[MappingEntry]:
    """All mapping entries with the given translation status."""
    return [e for e in MAPPING if e.status == status]


def by_category(category: str) -> list[MappingEntry]:
    """All mapping entries in the given category."""
    return [e for e in MAPPING if e.category == category]
