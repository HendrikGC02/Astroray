# Blender Parity Coverage Matrix — Phase A (AST-Scanned Evidence)

**Generated:** 5.2.0 LTS

**Evidence sources:**
- Shader nodes: AST-scanned from addon source (helper-method reads included)
- RenderSettings/Light/Camera: static evidence, hand-verified by review, not scanner-derived

**Note:** Integer-literal socket names (e.g., MATH '0'/'1'/'2' positional) excluded from counts.

## Summary

- **SUPPORTED**: 122 features
- **APPROXIMATED**: 61 features
- **DROPPED-SILENT**: 403 features ⚠️
- **UNKNOWN**: 0 features
- **Total**: 586 features

## ⚠️ Stale Socket Reads — Latent Bugs (Unguarded, Name Not in Blender 5.1)

These socket names appear in UNGUARDED addon reads but do NOT exist on the live node.
The addon's `node.inputs.get('...')` returns None at runtime, default silently wins.
**Each entry is a real latent bug.**

- **BSDF_PRINCIPLED**: socket `Transmission Dispersion Abbe Number` (addon __init__.py line 4197)
- **BSDF_PRINCIPLED**: socket `Transmission Dispersion Scale` (addon __init__.py line 4197)
- **INVERT**: socket `Fac` (addon __init__.py line 2776)
- **MIX_SHADER**: socket `Fac` (addon __init__.py line 4204, line 4342)
- **TEX_BRICK**: socket `Color3` (addon __init__.py line 3623)
- **TEX_BRICK**: socket `Offset` (addon __init__.py line 3623)
- **VALTORGB**: socket `Fac` (addon __init__.py line 2818)

## Dormant Cross-Version Fallbacks (Intentional, Informational)

These socket names appear in FALLBACK position of cross-version reads (second arg in `_float_with_fallback(node, 'New', 'Old')`) but do NOT exist in Blender 5.1. They are dormant — only activate if the primary name also doesn't exist. Informational, not bugs.

- **BSDF_PRINCIPLED**: socket `Dispersion Scale` (addon __init__.py line 4197)
- **BSDF_PRINCIPLED**: socket `Subsurface` (addon __init__.py line 4197)
- **BSDF_PRINCIPLED**: socket `Dispersion` (addon __init__.py line 4197)
- **BSDF_PRINCIPLED**: socket `Clearcoat Roughness` (addon __init__.py line 4197)
- **BSDF_PRINCIPLED**: socket `Dispersion Abbe Number` (addon __init__.py line 4197)
- **BSDF_PRINCIPLED**: socket `Sheen` (addon __init__.py line 4197)
- **BSDF_PRINCIPLED**: socket `Clearcoat` (addon __init__.py line 4197)
- **BSDF_PRINCIPLED**: socket `Transmission` (addon __init__.py line 4197)
- **BSDF_PRINCIPLED**: socket `Specular` (addon __init__.py line 4197)
- **MIX**: socket `Color1` (addon __init__.py line 2764)
- **MIX**: socket `Color2` (addon __init__.py line 2764)
- **MIX**: socket `Fac` (addon __init__.py line 2764)
- **MIX_RGB**: socket `A` (addon __init__.py line 2764)
- **MIX_RGB**: socket `B` (addon __init__.py line 2764)
- **MIX_RGB**: socket `Fac` (addon __init__.py line 2764)

## DROPPED-SILENT Features (Failure Mode)

These features are silently ignored by the addon with no warning:

### camera

- **Camera**: `aperture_blades`
- **Camera**: `aperture_rotation`
- **Camera**: `aperture_ratio`
- **Camera**: `type`
- **Camera**: `clip_start`
- **Camera**: `clip_end`
- **Camera**: `ortho_scale`

### image_property

- **Image**: `colorspace_settings.name`
- **Image**: `alpha_mode`
- **Image**: `source==TILED (UDIM)`
- **ShaderNodeTexImage**: `interpolation`
- **ShaderNodeTexImage**: `extension`
- **ShaderNodeTexImage**: `projection`

### input_node

- **NEW_GEOMETRY**: `output:Position` — no handler in addon translation layer
- **NEW_GEOMETRY**: `output:Normal` — no handler in addon translation layer
- **NEW_GEOMETRY**: `output:Tangent` — no handler in addon translation layer
- **NEW_GEOMETRY**: `output:True Normal` — no handler in addon translation layer
- **NEW_GEOMETRY**: `output:Incoming` — no handler in addon translation layer
- **NEW_GEOMETRY**: `output:Parametric` — no handler in addon translation layer
- **NEW_GEOMETRY**: `output:Backfacing` — no handler in addon translation layer
- **NEW_GEOMETRY**: `output:Pointiness` — no handler in addon translation layer
- **NEW_GEOMETRY**: `output:Random Per Island` — no handler in addon translation layer
- **OBJECT_INFO**: `output:Location` — no handler in addon translation layer
- **OBJECT_INFO**: `output:Color` — no handler in addon translation layer
- **OBJECT_INFO**: `output:Alpha` — no handler in addon translation layer
- **OBJECT_INFO**: `output:Object Index` — no handler in addon translation layer
- **OBJECT_INFO**: `output:Material Index` — no handler in addon translation layer
- **OBJECT_INFO**: `output:Random` — no handler in addon translation layer
- **ATTRIBUTE**: `output:Color` — no handler in addon translation layer
- **ATTRIBUTE**: `output:Vector` — no handler in addon translation layer
- **ATTRIBUTE**: `output:Factor` — no handler in addon translation layer
- **ATTRIBUTE**: `output:Alpha` — no handler in addon translation layer
- **VERTEX_COLOR**: `output:Color` — no handler in addon translation layer
- **VERTEX_COLOR**: `output:Alpha` — no handler in addon translation layer
- **HAIR_INFO**: `output:Is Strand` — no handler in addon translation layer
- **HAIR_INFO**: `output:Intercept` — no handler in addon translation layer
- **HAIR_INFO**: `output:Length` — no handler in addon translation layer
- **HAIR_INFO**: `output:Thickness` — no handler in addon translation layer
- **HAIR_INFO**: `output:Tangent Normal` — no handler in addon translation layer
- **HAIR_INFO**: `output:Random` — no handler in addon translation layer
- **LIGHT_PATH**: `output:Is Camera Ray` — no handler in addon translation layer
- **LIGHT_PATH**: `output:Is Shadow Ray` — no handler in addon translation layer
- **LIGHT_PATH**: `output:Is Diffuse Ray` — no handler in addon translation layer
- **LIGHT_PATH**: `output:Is Glossy Ray` — no handler in addon translation layer
- **LIGHT_PATH**: `output:Is Singular Ray` — no handler in addon translation layer
- **LIGHT_PATH**: `output:Is Reflection Ray` — no handler in addon translation layer
- **LIGHT_PATH**: `output:Is Transmission Ray` — no handler in addon translation layer
- **LIGHT_PATH**: `output:Is Volume Scatter Ray` — no handler in addon translation layer
- **LIGHT_PATH**: `output:Ray Length` — no handler in addon translation layer
- **LIGHT_PATH**: `output:Ray Depth` — no handler in addon translation layer
- **LIGHT_PATH**: `output:Diffuse Depth` — no handler in addon translation layer
- **LIGHT_PATH**: `output:Glossy Depth` — no handler in addon translation layer
- **LIGHT_PATH**: `output:Transparent Depth` — no handler in addon translation layer
- **LIGHT_PATH**: `output:Transmission Depth` — no handler in addon translation layer
- **LIGHT_PATH**: `output:Portal Depth` — no handler in addon translation layer

### light

- **POINT**: `specular_factor`
- **SUN**: `specular_factor`
- **SPOT**: `specular_factor`
- **SPOT**: `show_cone`
- **AREA**: `specular_factor`

### object

- **Object**: `instance_collection`

### render_settings

- **RenderSettings**: `use_adaptive_sampling`
- **RenderSettings**: `adaptive_threshold`
- **RenderSettings**: `adaptive_min_samples`
- **RenderSettings**: `seed`
- **RenderSettings**: `sample_offset`
- **RenderSettings**: `film_exposure`
- **RenderSettings**: `filter_width`
- **RenderSettings**: `max_bounces`
- **RenderSettings**: `diffuse_bounces`
- **RenderSettings**: `glossy_bounces`
- **RenderSettings**: `transparent_max_bounces`
- **RenderSettings**: `transmission_bounces`
- **RenderSettings**: `volume_bounces`
- **RenderSettings**: `caustics_reflective`
- **RenderSettings**: `caustics_refractive`
- **RenderSettings**: `use_fast_gi`
- **RenderSettings**: `denoising_input_passes`

### shader_node

- **ADD_SHADER**: `input:Shader`
- **ADD_SHADER**: `input:Shader[Shader_001]`
- **AMBIENT_OCCLUSION**: `input:Color` — no handler in addon translation layer
- **AMBIENT_OCCLUSION**: `input:Distance` — no handler in addon translation layer
- **AMBIENT_OCCLUSION**: `input:Normal` — no handler in addon translation layer
- **AMBIENT_OCCLUSION**: `prop:inside` — property BOOLEAN
- **AMBIENT_OCCLUSION**: `prop:only_local` — property BOOLEAN
- **AMBIENT_OCCLUSION**: `prop:samples` — property INT
- **ATTRIBUTE**: `prop:attribute_type` — property ENUM
- **BACKGROUND**: `input:Color` — no handler in addon translation layer
- **BACKGROUND**: `input:Strength` — no handler in addon translation layer
- **BACKGROUND**: `input:Weight` — no handler in addon translation layer
- **BEVEL**: `input:Radius` — no handler in addon translation layer
- **BEVEL**: `input:Normal` — no handler in addon translation layer
- **BEVEL**: `prop:samples` — property INT
- **BSDF_GLOSSY**: `input:Anisotropy`
- **BSDF_GLOSSY**: `input:Rotation`
- **BSDF_GLOSSY**: `input:Normal`
- **BSDF_GLOSSY**: `input:Tangent`
- **BSDF_GLOSSY**: `input:Weight`
- **BSDF_GLOSSY**: `prop:distribution` — property ENUM
- **BSDF_DIFFUSE**: `input:Normal`
- **BSDF_DIFFUSE**: `input:Weight`
- **BSDF_GLASS**: `input:Normal`
- **BSDF_GLASS**: `input:Weight`
- **BSDF_GLASS**: `input:Thin Film Thickness`
- **BSDF_GLASS**: `input:Thin Film IOR`
- **BSDF_GLASS**: `prop:distribution` — property ENUM
- **BSDF_HAIR**: `input:Color`
- **BSDF_HAIR**: `input:Offset`
- **BSDF_HAIR**: `input:RoughnessU`
- **BSDF_HAIR**: `input:RoughnessV`
- **BSDF_HAIR**: `input:Tangent`
- **BSDF_HAIR**: `input:Weight`
- **BSDF_HAIR**: `prop:component` — property ENUM
- **BSDF_HAIR_PRINCIPLED**: `input:Color`
- **BSDF_HAIR_PRINCIPLED**: `input:Melanin`
- **BSDF_HAIR_PRINCIPLED**: `input:Melanin Redness`
- **BSDF_HAIR_PRINCIPLED**: `input:Tint`
- **BSDF_HAIR_PRINCIPLED**: `input:Absorption Coefficient`
- **BSDF_HAIR_PRINCIPLED**: `input:Aspect Ratio`
- **BSDF_HAIR_PRINCIPLED**: `input:Roughness`
- **BSDF_HAIR_PRINCIPLED**: `input:Radial Roughness`
- **BSDF_HAIR_PRINCIPLED**: `input:Coat`
- **BSDF_HAIR_PRINCIPLED**: `input:IOR`
- **BSDF_HAIR_PRINCIPLED**: `input:Offset`
- **BSDF_HAIR_PRINCIPLED**: `input:Random Color`
- **BSDF_HAIR_PRINCIPLED**: `input:Random Roughness`
- **BSDF_HAIR_PRINCIPLED**: `input:Random`
- **BSDF_HAIR_PRINCIPLED**: `input:Weight`
- **BSDF_HAIR_PRINCIPLED**: `input:Reflection`
- **BSDF_HAIR_PRINCIPLED**: `input:Transmission`
- **BSDF_HAIR_PRINCIPLED**: `input:Secondary Reflection`
- **BSDF_HAIR_PRINCIPLED**: `prop:model` — property ENUM
- **BSDF_HAIR_PRINCIPLED**: `prop:parametrization` — property ENUM
- **BSDF_METALLIC**: `input:IOR`
- **BSDF_METALLIC**: `input:Extinction`
- **BSDF_METALLIC**: `input:Normal`
- **BSDF_METALLIC**: `input:Tangent`
- **BSDF_METALLIC**: `input:Weight`
- **BSDF_PRINCIPLED**: `input:Weight`
- **BSDF_PRINCIPLED**: `input:Subsurface IOR`
- **BSDF_PRINCIPLED**: `input:Tangent`
- **BSDF_PRINCIPLED**: `input:Coat Normal`
- **BSDF_PRINCIPLED**: `prop:distribution` — property ENUM
- **BSDF_PRINCIPLED**: `prop:subsurface_method` — property ENUM
- **BSDF_RAY_PORTAL**: `input:Color` — no handler in addon translation layer
- **BSDF_RAY_PORTAL**: `input:Position` — no handler in addon translation layer
- **BSDF_RAY_PORTAL**: `input:Direction` — no handler in addon translation layer
- **BSDF_RAY_PORTAL**: `input:Weight` — no handler in addon translation layer
- **BSDF_REFRACTION**: `input:Normal`
- **BSDF_REFRACTION**: `input:Weight`
- **BSDF_REFRACTION**: `prop:distribution` — property ENUM
- **BSDF_SHEEN**: `input:Normal`
- **BSDF_SHEEN**: `prop:distribution` — property ENUM
- **BSDF_TOON**: `input:Color` — no handler in addon translation layer
- **BSDF_TOON**: `input:Size` — no handler in addon translation layer
- **BSDF_TOON**: `input:Smooth` — no handler in addon translation layer
- **BSDF_TOON**: `input:Normal` — no handler in addon translation layer
- **BSDF_TOON**: `input:Weight` — no handler in addon translation layer
- **BSDF_TOON**: `prop:component` — property ENUM
- **BSDF_TRANSLUCENT**: `input:Normal`
- **BSDF_TRANSLUCENT**: `input:Weight`
- **BSDF_TRANSPARENT**: `input:Weight`
- **BUMP**: `prop:invert` — property BOOLEAN
- **CLAMP**: `input:Value` — no handler in addon translation layer
- **CLAMP**: `input:Min` — no handler in addon translation layer
- **CLAMP**: `input:Max` — no handler in addon translation layer
- **CLAMP**: `prop:clamp_type` — property ENUM
- **COMBINE_COLOR**: `input:Red` — no handler in addon translation layer
- **COMBINE_COLOR**: `input:Green` — no handler in addon translation layer
- **COMBINE_COLOR**: `input:Blue` — no handler in addon translation layer
- **COMBINE_COLOR**: `prop:mode` — property ENUM
- **COMBXYZ**: `input:X` — no handler in addon translation layer
- **COMBXYZ**: `input:Y` — no handler in addon translation layer
- **COMBXYZ**: `input:Z` — no handler in addon translation layer
- **DISPLACEMENT**: `input:Normal` — Height/Scale approximated as a bump perturbation via the pkg223b bump machinery (pkg257); Midlevel is read but mathematically inert for a gradient-based bump; Normal and displacement_method/space are read only to emit the DISPLACEMENT warning, never consumed
- **DISPLACEMENT**: `prop:space` — property ENUM
- **EEVEE_SPECULAR**: `input:Base Color` — no handler in addon translation layer
- **EEVEE_SPECULAR**: `input:Specular` — no handler in addon translation layer
- **EEVEE_SPECULAR**: `input:Roughness` — no handler in addon translation layer
- **EEVEE_SPECULAR**: `input:Emissive Color` — no handler in addon translation layer
- **EEVEE_SPECULAR**: `input:Transparency` — no handler in addon translation layer
- **EEVEE_SPECULAR**: `input:Normal` — no handler in addon translation layer
- **EEVEE_SPECULAR**: `input:Clear Coat` — no handler in addon translation layer
- **EEVEE_SPECULAR**: `input:Clear Coat Roughness` — no handler in addon translation layer
- **EEVEE_SPECULAR**: `input:Clear Coat Normal` — no handler in addon translation layer
- **EEVEE_SPECULAR**: `input:Weight` — no handler in addon translation layer
- **EMISSION**: `input:Weight`
- **CURVE_FLOAT**: `input:Factor` — no handler in addon translation layer
- **CURVE_FLOAT**: `input:Value` — no handler in addon translation layer
- **FRESNEL**: `input:IOR` — no handler in addon translation layer
- **FRESNEL**: `input:Normal` — no handler in addon translation layer
- **HOLDOUT**: `input:Weight` — no handler in addon translation layer
- **INVERT**: `input:Factor`
- **LAYER_WEIGHT**: `input:Blend` — no handler in addon translation layer
- **LAYER_WEIGHT**: `input:Normal` — no handler in addon translation layer
- **LIGHT_FALLOFF**: `input:Strength` — no handler in addon translation layer
- **LIGHT_FALLOFF**: `input:Smooth` — no handler in addon translation layer
- **MAP_RANGE**: `input:Value` — no handler in addon translation layer
- **MAP_RANGE**: `input:From Min` — no handler in addon translation layer
- **MAP_RANGE**: `input:From Max` — no handler in addon translation layer
- **MAP_RANGE**: `input:To Min` — no handler in addon translation layer
- **MAP_RANGE**: `input:To Max` — no handler in addon translation layer
- **MAP_RANGE**: `input:Steps` — no handler in addon translation layer
- **MAP_RANGE**: `input:Vector` — no handler in addon translation layer
- **MAP_RANGE**: `input:From Min[From_Min_FLOAT3]` — no handler in addon translation layer
- **MAP_RANGE**: `input:From Max[From_Max_FLOAT3]` — no handler in addon translation layer
- **MAP_RANGE**: `input:To Min[To_Min_FLOAT3]` — no handler in addon translation layer
- **MAP_RANGE**: `input:To Max[To_Max_FLOAT3]` — no handler in addon translation layer
- **MAP_RANGE**: `input:Steps[Steps_FLOAT3]` — no handler in addon translation layer
- **MAP_RANGE**: `prop:clamp` — property BOOLEAN
- **MAP_RANGE**: `prop:data_type` — property ENUM
- **MAP_RANGE**: `prop:interpolation_type` — property ENUM
- **MAPPING**: `input:Vector` — no handler in addon translation layer
- **MAPPING**: `input:Location` — no handler in addon translation layer
- **MAPPING**: `input:Rotation` — no handler in addon translation layer
- **MAPPING**: `input:Scale` — no handler in addon translation layer
- **MAPPING**: `prop:vector_type` — property ENUM
- **MATH**: `input:Value` — no handler in addon translation layer
- **MATH**: `input:Value[Value_001]` — no handler in addon translation layer
- **MATH**: `input:Value[Value_002]` — no handler in addon translation layer
- **MATH**: `prop:operation` — property ENUM
- **MATH**: `prop:use_clamp` — property BOOLEAN
- **MIX**: `input:Factor[Factor_Float]`
- **MIX**: `input:Factor[Factor_Vector]`
- **MIX**: `input:A[A_Float]`
- **MIX**: `input:B[B_Float]`
- **MIX**: `input:A[A_Vector]`
- **MIX**: `input:B[B_Vector]`
- **MIX**: `input:A[A_Color]`
- **MIX**: `input:B[B_Color]`
- **MIX**: `input:A[A_Rotation]`
- **MIX**: `input:B[B_Rotation]`
- **MIX**: `prop:clamp_factor` — property BOOLEAN
- **MIX**: `prop:clamp_result` — property BOOLEAN
- **MIX**: `prop:data_type` — property ENUM
- **MIX**: `prop:factor_mode` — property ENUM
- **MIX_RGB**: `input:Factor`
- **MIX_RGB**: `input:Color1`
- **MIX_RGB**: `input:Color2`
- **MIX_RGB**: `prop:use_alpha` — property BOOLEAN
- **MIX_RGB**: `prop:use_clamp` — property BOOLEAN
- **MIX_SHADER**: `input:Factor`
- **MIX_SHADER**: `input:Shader`
- **MIX_SHADER**: `input:Shader[Shader_001]`
- **NORMAL**: `input:Normal` — no handler in addon translation layer
- **NORMAL_MAP**: `prop:base` — property ENUM
- **NORMAL_MAP**: `prop:convention` — property ENUM
- **NORMAL_MAP**: `prop:space` — property ENUM
- **OUTPUT_AOV**: `input:Color` — no handler in addon translation layer
- **OUTPUT_AOV**: `input:Value` — no handler in addon translation layer
- **OUTPUT_LIGHT**: `input:Surface` — no handler in addon translation layer
- **OUTPUT_LIGHT**: `prop:is_active_output` — property BOOLEAN
- **OUTPUT_LIGHT**: `prop:target` — property ENUM
- **OUTPUT_LINESTYLE**: `input:Color` — no handler in addon translation layer
- **OUTPUT_LINESTYLE**: `input:Color Fac` — no handler in addon translation layer
- **OUTPUT_LINESTYLE**: `input:Alpha` — no handler in addon translation layer
- **OUTPUT_LINESTYLE**: `input:Alpha Fac` — no handler in addon translation layer
- **OUTPUT_LINESTYLE**: `prop:blend_type` — property ENUM
- **OUTPUT_LINESTYLE**: `prop:is_active_output` — property BOOLEAN
- **OUTPUT_LINESTYLE**: `prop:target` — property ENUM
- **OUTPUT_LINESTYLE**: `prop:use_alpha` — property BOOLEAN
- **OUTPUT_LINESTYLE**: `prop:use_clamp` — property BOOLEAN
- **OUTPUT_MATERIAL**: `input:Surface` — no handler in addon translation layer
- **OUTPUT_MATERIAL**: `input:Volume` — no handler in addon translation layer
- **OUTPUT_MATERIAL**: `input:Displacement` — no handler in addon translation layer
- **OUTPUT_MATERIAL**: `input:Thickness` — no handler in addon translation layer
- **OUTPUT_MATERIAL**: `prop:is_active_output` — property BOOLEAN
- **OUTPUT_MATERIAL**: `prop:target` — property ENUM
- **OUTPUT_WORLD**: `input:Surface` — no handler in addon translation layer
- **OUTPUT_WORLD**: `input:Volume` — no handler in addon translation layer
- **OUTPUT_WORLD**: `prop:is_active_output` — property BOOLEAN
- **OUTPUT_WORLD**: `prop:target` — property ENUM
- **CURVE_RGB**: `input:Factor` — no handler in addon translation layer
- **CURVE_RGB**: `input:Color` — no handler in addon translation layer
- **ShaderNodeRadialTiling**: `input:Vector` — no handler in addon translation layer
- **ShaderNodeRadialTiling**: `input:Sides` — no handler in addon translation layer
- **ShaderNodeRadialTiling**: `input:Roundness` — no handler in addon translation layer
- **ShaderNodeRadialTiling**: `prop:normalize` — property BOOLEAN
- **MATERIAL_RAYCAST**: `input:Position` — no handler in addon translation layer
- **MATERIAL_RAYCAST**: `input:Direction` — no handler in addon translation layer
- **MATERIAL_RAYCAST**: `input:Length` — no handler in addon translation layer
- **MATERIAL_RAYCAST**: `input:` — no handler in addon translation layer
- **MATERIAL_RAYCAST**: `prop:active_index` — property INT
- **MATERIAL_RAYCAST**: `prop:only_local` — property BOOLEAN
- **SCRIPT**: `prop:mode` — property ENUM
- **SCRIPT**: `prop:use_auto_update` — property BOOLEAN
- **SEPARATE_COLOR**: `input:Color` — no handler in addon translation layer
- **SEPARATE_COLOR**: `prop:mode` — property ENUM
- **SEPXYZ**: `input:Vector` — no handler in addon translation layer
- **SHADERTORGB**: `input:Shader` — no handler in addon translation layer
- **SQUEEZE**: `input:Value` — no handler in addon translation layer
- **SQUEEZE**: `input:Width` — no handler in addon translation layer
- **SQUEEZE**: `input:Center` — no handler in addon translation layer
- **SUBSURFACE_SCATTERING**: `input:Color` — no handler in addon translation layer
- **SUBSURFACE_SCATTERING**: `input:Scale` — no handler in addon translation layer
- **SUBSURFACE_SCATTERING**: `input:Radius` — no handler in addon translation layer
- **SUBSURFACE_SCATTERING**: `input:IOR` — no handler in addon translation layer
- **SUBSURFACE_SCATTERING**: `input:Roughness` — no handler in addon translation layer
- **SUBSURFACE_SCATTERING**: `input:Anisotropy` — no handler in addon translation layer
- **SUBSURFACE_SCATTERING**: `input:Normal` — no handler in addon translation layer
- **SUBSURFACE_SCATTERING**: `input:Weight` — no handler in addon translation layer
- **SUBSURFACE_SCATTERING**: `prop:falloff` — property ENUM
- **TANGENT**: `prop:axis` — property ENUM
- **TANGENT**: `prop:direction_type` — property ENUM
- **TEX_BRICK**: `input:Vector`
- **TEX_BRICK**: `input:Mortar`
- **TEX_BRICK**: `prop:offset` — property FLOAT
- **TEX_CHECKER**: `input:Vector`
- **TEX_COORD**: `prop:from_instancer` — property BOOLEAN
- **TEX_ENVIRONMENT**: `input:Vector` — no handler in addon translation layer
- **TEX_ENVIRONMENT**: `prop:interpolation` — property ENUM
- **TEX_ENVIRONMENT**: `prop:projection` — property ENUM
- **TEX_GABOR**: `input:Vector` — no handler in addon translation layer
- **TEX_GABOR**: `input:Scale` — no handler in addon translation layer
- **TEX_GABOR**: `input:Frequency` — no handler in addon translation layer
- **TEX_GABOR**: `input:Anisotropy` — no handler in addon translation layer
- **TEX_GABOR**: `input:Orientation[Orientation 2D]` — no handler in addon translation layer
- **TEX_GABOR**: `input:Orientation[Orientation 3D]` — no handler in addon translation layer
- **TEX_GABOR**: `prop:gabor_type` — property ENUM
- **TEX_GRADIENT**: `input:Vector`
- **TEX_IES**: `input:Vector` — no handler in addon translation layer
- **TEX_IES**: `input:Strength` — no handler in addon translation layer
- **TEX_IES**: `prop:mode` — property ENUM
- **TEX_IMAGE**: `prop:extension` — property ENUM
- **TEX_IMAGE**: `prop:interpolation` — property ENUM
- **TEX_IMAGE**: `prop:projection` — property ENUM
- **TEX_IMAGE**: `prop:projection_blend` — property FLOAT
- **TEX_MAGIC**: `input:Vector`
- **TEX_NOISE**: `input:Vector`
- **TEX_NOISE**: `input:W`
- **TEX_NOISE**: `prop:noise_dimensions` — property ENUM
- **TEX_SKY**: `input:Vector` — no handler in addon translation layer
- **TEX_SKY**: `prop:aerosol_density` — property FLOAT
- **TEX_SKY**: `prop:air_density` — property FLOAT
- **TEX_SKY**: `prop:altitude` — property FLOAT
- **TEX_SKY**: `prop:ground_albedo` — property FLOAT
- **TEX_SKY**: `prop:ozone_density` — property FLOAT
- **TEX_SKY**: `prop:sky_type` — property ENUM
- **TEX_SKY**: `prop:sun_direction` — property FLOAT
- **TEX_SKY**: `prop:sun_disc` — property BOOLEAN
- **TEX_SKY**: `prop:sun_elevation` — property FLOAT
- **TEX_SKY**: `prop:sun_intensity` — property FLOAT
- **TEX_SKY**: `prop:sun_rotation` — property FLOAT
- **TEX_SKY**: `prop:sun_size` — property FLOAT
- **TEX_SKY**: `prop:turbidity` — property FLOAT
- **TEX_VORONOI**: `input:Vector`
- **TEX_VORONOI**: `input:W`
- **TEX_VORONOI**: `prop:voronoi_dimensions` — property ENUM
- **TEX_WAVE**: `input:Vector`
- **TEX_WHITE_NOISE**: `input:Vector` — no handler in addon translation layer
- **TEX_WHITE_NOISE**: `input:W` — no handler in addon translation layer
- **TEX_WHITE_NOISE**: `prop:noise_dimensions` — property ENUM
- **UVALONGSTROKE**: `prop:use_tips` — property BOOLEAN
- **UVMAP**: `prop:from_instancer` — property BOOLEAN
- **VALTORGB**: `input:Factor`
- **CURVE_VEC**: `input:Factor` — no handler in addon translation layer
- **CURVE_VEC**: `input:Vector` — no handler in addon translation layer
- **VECTOR_DISPLACEMENT**: `input:Vector` — no handler in addon translation layer
- **VECTOR_DISPLACEMENT**: `input:Midlevel` — no handler in addon translation layer
- **VECTOR_DISPLACEMENT**: `input:Scale` — no handler in addon translation layer
- **VECTOR_DISPLACEMENT**: `prop:space` — property ENUM
- **VECT_MATH**: `input:Vector` — no handler in addon translation layer
- **VECT_MATH**: `input:Vector[Vector_001]` — no handler in addon translation layer
- **VECT_MATH**: `input:Vector[Vector_002]` — no handler in addon translation layer
- **VECT_MATH**: `input:Scale` — no handler in addon translation layer
- **VECT_MATH**: `prop:operation` — property ENUM
- **VECTOR_ROTATE**: `input:Vector` — no handler in addon translation layer
- **VECTOR_ROTATE**: `input:Center` — no handler in addon translation layer
- **VECTOR_ROTATE**: `input:Axis` — no handler in addon translation layer
- **VECTOR_ROTATE**: `input:Angle` — no handler in addon translation layer
- **VECTOR_ROTATE**: `input:Rotation` — no handler in addon translation layer
- **VECTOR_ROTATE**: `prop:invert` — property BOOLEAN
- **VECTOR_ROTATE**: `prop:rotation_type` — property ENUM
- **VECT_TRANSFORM**: `input:Vector` — no handler in addon translation layer
- **VECT_TRANSFORM**: `prop:convert_from` — property ENUM
- **VECT_TRANSFORM**: `prop:convert_to` — property ENUM
- **VECT_TRANSFORM**: `prop:vector_type` — property ENUM
- **VOLUME_ABSORPTION**: `input:Weight` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_COEFFICIENTS**: `input:Weight` — no handler in addon translation layer
- **VOLUME_COEFFICIENTS**: `input:Absorption Coefficients` — no handler in addon translation layer
- **VOLUME_COEFFICIENTS**: `input:Scatter Coefficients` — no handler in addon translation layer
- **VOLUME_COEFFICIENTS**: `input:Anisotropy` — no handler in addon translation layer
- **VOLUME_COEFFICIENTS**: `input:IOR` — no handler in addon translation layer
- **VOLUME_COEFFICIENTS**: `input:Backscatter` — no handler in addon translation layer
- **VOLUME_COEFFICIENTS**: `input:Alpha` — no handler in addon translation layer
- **VOLUME_COEFFICIENTS**: `input:Diameter` — no handler in addon translation layer
- **VOLUME_COEFFICIENTS**: `input:Emission Coefficients` — no handler in addon translation layer
- **VOLUME_COEFFICIENTS**: `prop:phase` — property ENUM
- **PRINCIPLED_VOLUME**: `input:Color Attribute` — mapped to glass IOR=1.0 (volume not fully implemented)
- **PRINCIPLED_VOLUME**: `input:Density Attribute` — mapped to glass IOR=1.0 (volume not fully implemented)
- **PRINCIPLED_VOLUME**: `input:Absorption Color` — mapped to glass IOR=1.0 (volume not fully implemented)
- **PRINCIPLED_VOLUME**: `input:Blackbody Tint` — mapped to glass IOR=1.0 (volume not fully implemented)
- **PRINCIPLED_VOLUME**: `input:Temperature Attribute` — mapped to glass IOR=1.0 (volume not fully implemented)
- **PRINCIPLED_VOLUME**: `input:Weight` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_SCATTER**: `input:IOR` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_SCATTER**: `input:Backscatter` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_SCATTER**: `input:Alpha` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_SCATTER**: `input:Diameter` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_SCATTER**: `input:Weight` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_SCATTER**: `prop:phase` — property ENUM
- **WIREFRAME**: `input:Size` — no handler in addon translation layer
- **WIREFRAME**: `prop:use_pixel_size` — property BOOLEAN

### world

- **World**: `light_linking_shadow_linking` — per-object light-linking / shadow-linking collections have no Astroray equivalent; declared out of scope by owner decision 2026-09-08 -- one gap-card row, not per-object rows

## Full Matrix by Category

### camera

| Feature | Socket/Property | Classification | Notes |
|---------|-----------------|----------------|-------|
| Camera | lens | SUPPORTED |  |
| Camera | sensor_width | SUPPORTED |  |
| Camera | sensor_height | SUPPORTED |  |
| Camera | shift_x | SUPPORTED |  |
| Camera | shift_y | SUPPORTED |  |
| Camera | aperture_fstop | SUPPORTED |  |
| Camera | aperture_blades | DROPPED-SILENT |  |
| Camera | aperture_rotation | DROPPED-SILENT |  |
| Camera | aperture_ratio | DROPPED-SILENT |  |
| Camera | type | DROPPED-SILENT |  |
| Camera | clip_start | DROPPED-SILENT |  |
| Camera | clip_end | DROPPED-SILENT |  |
| Camera | focus_distance | SUPPORTED |  |
| Camera | focus_object | SUPPORTED |  |
| Camera | ortho_scale | DROPPED-SILENT |  |
| Camera | sensor_fit | SUPPORTED |  |

### image_property

| Feature | Socket/Property | Classification | Notes |
|---------|-----------------|----------------|-------|
| Image | colorspace_settings.name | DROPPED-SILENT |  |
| Image | alpha_mode | DROPPED-SILENT |  |
| Image | source==TILED (UDIM) | DROPPED-SILENT |  |
| ShaderNodeTexImage | interpolation | DROPPED-SILENT |  |
| ShaderNodeTexImage | extension | DROPPED-SILENT |  |
| ShaderNodeTexImage | projection | DROPPED-SILENT |  |

### input_node

| Feature | Socket/Property | Classification | Notes |
|---------|-----------------|----------------|-------|
| NEW_GEOMETRY | output:Position | DROPPED-SILENT | no handler in addon translation layer |
| NEW_GEOMETRY | output:Normal | DROPPED-SILENT | no handler in addon translation layer |
| NEW_GEOMETRY | output:Tangent | DROPPED-SILENT | no handler in addon translation layer |
| NEW_GEOMETRY | output:True Normal | DROPPED-SILENT | no handler in addon translation layer |
| NEW_GEOMETRY | output:Incoming | DROPPED-SILENT | no handler in addon translation layer |
| NEW_GEOMETRY | output:Parametric | DROPPED-SILENT | no handler in addon translation layer |
| NEW_GEOMETRY | output:Backfacing | DROPPED-SILENT | no handler in addon translation layer |
| NEW_GEOMETRY | output:Pointiness | DROPPED-SILENT | no handler in addon translation layer |
| NEW_GEOMETRY | output:Random Per Island | DROPPED-SILENT | no handler in addon translation layer |
| OBJECT_INFO | output:Location | DROPPED-SILENT | no handler in addon translation layer |
| OBJECT_INFO | output:Color | DROPPED-SILENT | no handler in addon translation layer |
| OBJECT_INFO | output:Alpha | DROPPED-SILENT | no handler in addon translation layer |
| OBJECT_INFO | output:Object Index | DROPPED-SILENT | no handler in addon translation layer |
| OBJECT_INFO | output:Material Index | DROPPED-SILENT | no handler in addon translation layer |
| OBJECT_INFO | output:Random | DROPPED-SILENT | no handler in addon translation layer |
| ATTRIBUTE | output:Color | DROPPED-SILENT | no handler in addon translation layer |
| ATTRIBUTE | output:Vector | DROPPED-SILENT | no handler in addon translation layer |
| ATTRIBUTE | output:Factor | DROPPED-SILENT | no handler in addon translation layer |
| ATTRIBUTE | output:Alpha | DROPPED-SILENT | no handler in addon translation layer |
| VERTEX_COLOR | output:Color | DROPPED-SILENT | no handler in addon translation layer |
| VERTEX_COLOR | output:Alpha | DROPPED-SILENT | no handler in addon translation layer |
| HAIR_INFO | output:Is Strand | DROPPED-SILENT | no handler in addon translation layer |
| HAIR_INFO | output:Intercept | DROPPED-SILENT | no handler in addon translation layer |
| HAIR_INFO | output:Length | DROPPED-SILENT | no handler in addon translation layer |
| HAIR_INFO | output:Thickness | DROPPED-SILENT | no handler in addon translation layer |
| HAIR_INFO | output:Tangent Normal | DROPPED-SILENT | no handler in addon translation layer |
| HAIR_INFO | output:Random | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_PATH | output:Is Camera Ray | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_PATH | output:Is Shadow Ray | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_PATH | output:Is Diffuse Ray | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_PATH | output:Is Glossy Ray | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_PATH | output:Is Singular Ray | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_PATH | output:Is Reflection Ray | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_PATH | output:Is Transmission Ray | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_PATH | output:Is Volume Scatter Ray | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_PATH | output:Ray Length | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_PATH | output:Ray Depth | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_PATH | output:Diffuse Depth | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_PATH | output:Glossy Depth | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_PATH | output:Transparent Depth | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_PATH | output:Transmission Depth | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_PATH | output:Portal Depth | DROPPED-SILENT | no handler in addon translation layer |

### light

| Feature | Socket/Property | Classification | Notes |
|---------|-----------------|----------------|-------|
| POINT | energy | SUPPORTED |  |
| POINT | color | SUPPORTED |  |
| POINT | use_temperature | SUPPORTED |  |
| POINT | temperature | SUPPORTED |  |
| POINT | specular_factor | DROPPED-SILENT |  |
| POINT | shadow_soft_size | SUPPORTED |  |
| SUN | energy | SUPPORTED |  |
| SUN | color | SUPPORTED |  |
| SUN | use_temperature | SUPPORTED |  |
| SUN | temperature | SUPPORTED |  |
| SUN | specular_factor | DROPPED-SILENT |  |
| SUN | angle | SUPPORTED |  |
| SPOT | energy | SUPPORTED |  |
| SPOT | color | SUPPORTED |  |
| SPOT | use_temperature | SUPPORTED |  |
| SPOT | temperature | SUPPORTED |  |
| SPOT | specular_factor | DROPPED-SILENT |  |
| SPOT | spot_size | SUPPORTED |  |
| SPOT | spot_blend | SUPPORTED |  |
| SPOT | show_cone | DROPPED-SILENT |  |
| AREA | energy | SUPPORTED |  |
| AREA | color | SUPPORTED |  |
| AREA | use_temperature | SUPPORTED |  |
| AREA | temperature | SUPPORTED |  |
| AREA | specular_factor | DROPPED-SILENT |  |
| AREA | shape | SUPPORTED |  |
| AREA | size | SUPPORTED |  |
| AREA | size_y | SUPPORTED |  |
| AREA | spread | SUPPORTED |  |

### object

| Feature | Socket/Property | Classification | Notes |
|---------|-----------------|----------------|-------|
| Object | instance_type | SUPPORTED | read only to detect nested collection/dupli instancers (_register_instanced_groups); depsgraph.object_instances enumeration is what actually resolves VERTS/FACES/COLLECTION instancing, independent of this read |
| Object | instance_collection | DROPPED-SILENT |  |
| Object | modifiers | SUPPORTED | hand-verified: depsgraph.object_instances is the sole geometry source in convert_objects, so the evaluated modifier stack is already baked in |
| Object | use_motion_blur | SUPPORTED |  |
| Object | split_normals | SUPPORTED | covers smooth / flat / auto-smooth shading uniformly |
| Object | type:CURVES | SUPPORTED |  |

### render_settings

| Feature | Socket/Property | Classification | Notes |
|---------|-----------------|----------------|-------|
| RenderSettings | samples | SUPPORTED |  |
| RenderSettings | use_adaptive_sampling | DROPPED-SILENT |  |
| RenderSettings | adaptive_threshold | DROPPED-SILENT |  |
| RenderSettings | adaptive_min_samples | DROPPED-SILENT |  |
| RenderSettings | seed | DROPPED-SILENT |  |
| RenderSettings | sample_offset | DROPPED-SILENT |  |
| RenderSettings | film_exposure | DROPPED-SILENT |  |
| RenderSettings | film_transparent | SUPPORTED |  |
| RenderSettings | filter_width | DROPPED-SILENT |  |
| RenderSettings | max_bounces | DROPPED-SILENT |  |
| RenderSettings | diffuse_bounces | DROPPED-SILENT |  |
| RenderSettings | glossy_bounces | DROPPED-SILENT |  |
| RenderSettings | transparent_max_bounces | DROPPED-SILENT |  |
| RenderSettings | transmission_bounces | DROPPED-SILENT |  |
| RenderSettings | volume_bounces | DROPPED-SILENT |  |
| RenderSettings | caustics_reflective | DROPPED-SILENT |  |
| RenderSettings | caustics_refractive | DROPPED-SILENT |  |
| RenderSettings | use_fast_gi | DROPPED-SILENT |  |
| RenderSettings | use_denoising | SUPPORTED |  |
| RenderSettings | denoiser | SUPPORTED |  |
| RenderSettings | denoising_input_passes | DROPPED-SILENT |  |

### shader_node

| Feature | Socket/Property | Classification | Notes |
|---------|-----------------|----------------|-------|
| ADD_SHADER | input:Shader | DROPPED-SILENT |  |
| ADD_SHADER | input:Shader[Shader_001] | DROPPED-SILENT |  |
| AMBIENT_OCCLUSION | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| AMBIENT_OCCLUSION | input:Distance | DROPPED-SILENT | no handler in addon translation layer |
| AMBIENT_OCCLUSION | input:Normal | DROPPED-SILENT | no handler in addon translation layer |
| AMBIENT_OCCLUSION | prop:inside | DROPPED-SILENT | property BOOLEAN |
| AMBIENT_OCCLUSION | prop:only_local | DROPPED-SILENT | property BOOLEAN |
| AMBIENT_OCCLUSION | prop:samples | DROPPED-SILENT | property INT |
| ATTRIBUTE | prop:attribute_type | DROPPED-SILENT | property ENUM |
| BACKGROUND | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| BACKGROUND | input:Strength | DROPPED-SILENT | no handler in addon translation layer |
| BACKGROUND | input:Weight | DROPPED-SILENT | no handler in addon translation layer |
| BEVEL | input:Radius | DROPPED-SILENT | no handler in addon translation layer |
| BEVEL | input:Normal | DROPPED-SILENT | no handler in addon translation layer |
| BEVEL | prop:samples | DROPPED-SILENT | property INT |
| BLACKBODY | input:Temperature | SUPPORTED |  |
| BRIGHTCONTRAST | input:Color | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| BRIGHTCONTRAST | input:Brightness | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| BRIGHTCONTRAST | input:Contrast | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| BSDF_GLOSSY | input:Color | SUPPORTED |  |
| BSDF_GLOSSY | input:Roughness | SUPPORTED |  |
| BSDF_GLOSSY | input:Anisotropy | DROPPED-SILENT |  |
| BSDF_GLOSSY | input:Rotation | DROPPED-SILENT |  |
| BSDF_GLOSSY | input:Normal | DROPPED-SILENT |  |
| BSDF_GLOSSY | input:Tangent | DROPPED-SILENT |  |
| BSDF_GLOSSY | input:Weight | DROPPED-SILENT |  |
| BSDF_GLOSSY | prop:distribution | DROPPED-SILENT | property ENUM |
| BSDF_DIFFUSE | input:Color | APPROXIMATED |  |
| BSDF_DIFFUSE | input:Roughness | APPROXIMATED |  |
| BSDF_DIFFUSE | input:Normal | DROPPED-SILENT |  |
| BSDF_DIFFUSE | input:Weight | DROPPED-SILENT |  |
| BSDF_GLASS | input:Color | SUPPORTED |  |
| BSDF_GLASS | input:Roughness | SUPPORTED |  |
| BSDF_GLASS | input:IOR | SUPPORTED |  |
| BSDF_GLASS | input:Normal | DROPPED-SILENT |  |
| BSDF_GLASS | input:Weight | DROPPED-SILENT |  |
| BSDF_GLASS | input:Thin Film Thickness | DROPPED-SILENT |  |
| BSDF_GLASS | input:Thin Film IOR | DROPPED-SILENT |  |
| BSDF_GLASS | prop:distribution | DROPPED-SILENT | property ENUM |
| BSDF_HAIR | input:Color | DROPPED-SILENT |  |
| BSDF_HAIR | input:Offset | DROPPED-SILENT |  |
| BSDF_HAIR | input:RoughnessU | DROPPED-SILENT |  |
| BSDF_HAIR | input:RoughnessV | DROPPED-SILENT |  |
| BSDF_HAIR | input:Tangent | DROPPED-SILENT |  |
| BSDF_HAIR | input:Weight | DROPPED-SILENT |  |
| BSDF_HAIR | prop:component | DROPPED-SILENT | property ENUM |
| BSDF_HAIR_PRINCIPLED | input:Color | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | input:Melanin | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | input:Melanin Redness | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | input:Tint | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | input:Absorption Coefficient | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | input:Aspect Ratio | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | input:Roughness | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | input:Radial Roughness | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | input:Coat | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | input:IOR | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | input:Offset | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | input:Random Color | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | input:Random Roughness | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | input:Random | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | input:Weight | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | input:Reflection | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | input:Transmission | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | input:Secondary Reflection | DROPPED-SILENT |  |
| BSDF_HAIR_PRINCIPLED | prop:model | DROPPED-SILENT | property ENUM |
| BSDF_HAIR_PRINCIPLED | prop:parametrization | DROPPED-SILENT | property ENUM |
| BSDF_METALLIC | input:Base Color | APPROXIMATED |  |
| BSDF_METALLIC | input:Edge Tint | APPROXIMATED |  |
| BSDF_METALLIC | input:IOR | DROPPED-SILENT |  |
| BSDF_METALLIC | input:Extinction | DROPPED-SILENT |  |
| BSDF_METALLIC | input:Roughness | APPROXIMATED |  |
| BSDF_METALLIC | input:Anisotropy | APPROXIMATED |  |
| BSDF_METALLIC | input:Rotation | APPROXIMATED |  |
| BSDF_METALLIC | input:Normal | DROPPED-SILENT |  |
| BSDF_METALLIC | input:Tangent | DROPPED-SILENT |  |
| BSDF_METALLIC | input:Weight | DROPPED-SILENT |  |
| BSDF_METALLIC | input:Thin Film Thickness | APPROXIMATED |  |
| BSDF_METALLIC | input:Thin Film IOR | APPROXIMATED |  |
| BSDF_METALLIC | prop:distribution | APPROXIMATED |  |
| BSDF_METALLIC | prop:fresnel_type | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Base Color | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Metallic | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Roughness | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:IOR | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Alpha | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Thin Wall | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Normal | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Weight | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Diffuse Roughness | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Subsurface Weight | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Subsurface Radius | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Subsurface Scale | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Subsurface IOR | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Subsurface Anisotropy | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Specular IOR Level | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Specular Tint | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Anisotropic | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Anisotropic Rotation | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Tangent | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Transmission Weight | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Coat Weight | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Coat Roughness | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Coat IOR | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Coat Tint | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Coat Normal | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Sheen Weight | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Sheen Roughness | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Sheen Tint | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Emission Color | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Emission Strength | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Thin Film Thickness | APPROXIMATED |  |
| BSDF_PRINCIPLED | input:Thin Film IOR | APPROXIMATED |  |
| BSDF_PRINCIPLED | prop:distribution | DROPPED-SILENT | property ENUM |
| BSDF_PRINCIPLED | prop:subsurface_method | DROPPED-SILENT | property ENUM |
| BSDF_RAY_PORTAL | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_RAY_PORTAL | input:Position | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_RAY_PORTAL | input:Direction | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_RAY_PORTAL | input:Weight | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_REFRACTION | input:Color | APPROXIMATED |  |
| BSDF_REFRACTION | input:Roughness | APPROXIMATED |  |
| BSDF_REFRACTION | input:IOR | APPROXIMATED |  |
| BSDF_REFRACTION | input:Normal | DROPPED-SILENT |  |
| BSDF_REFRACTION | input:Weight | DROPPED-SILENT |  |
| BSDF_REFRACTION | prop:distribution | DROPPED-SILENT | property ENUM |
| BSDF_SHEEN | input:Color | APPROXIMATED |  |
| BSDF_SHEEN | input:Roughness | APPROXIMATED |  |
| BSDF_SHEEN | input:Normal | DROPPED-SILENT |  |
| BSDF_SHEEN | input:Weight | APPROXIMATED |  |
| BSDF_SHEEN | prop:distribution | DROPPED-SILENT | property ENUM |
| BSDF_TOON | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_TOON | input:Size | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_TOON | input:Smooth | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_TOON | input:Normal | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_TOON | input:Weight | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_TOON | prop:component | DROPPED-SILENT | property ENUM |
| BSDF_TRANSLUCENT | input:Color | APPROXIMATED |  |
| BSDF_TRANSLUCENT | input:Normal | DROPPED-SILENT |  |
| BSDF_TRANSLUCENT | input:Weight | DROPPED-SILENT |  |
| BSDF_TRANSPARENT | input:Color | SUPPORTED |  |
| BSDF_TRANSPARENT | input:Weight | DROPPED-SILENT |  |
| BUMP | input:Strength | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| BUMP | input:Distance | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| BUMP | input:Filter Width | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| BUMP | input:Height | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| BUMP | input:Normal | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| BUMP | prop:invert | DROPPED-SILENT | property BOOLEAN |
| CLAMP | input:Value | DROPPED-SILENT | no handler in addon translation layer |
| CLAMP | input:Min | DROPPED-SILENT | no handler in addon translation layer |
| CLAMP | input:Max | DROPPED-SILENT | no handler in addon translation layer |
| CLAMP | prop:clamp_type | DROPPED-SILENT | property ENUM |
| COMBINE_COLOR | input:Red | DROPPED-SILENT | no handler in addon translation layer |
| COMBINE_COLOR | input:Green | DROPPED-SILENT | no handler in addon translation layer |
| COMBINE_COLOR | input:Blue | DROPPED-SILENT | no handler in addon translation layer |
| COMBINE_COLOR | prop:mode | DROPPED-SILENT | property ENUM |
| COMBXYZ | input:X | DROPPED-SILENT | no handler in addon translation layer |
| COMBXYZ | input:Y | DROPPED-SILENT | no handler in addon translation layer |
| COMBXYZ | input:Z | DROPPED-SILENT | no handler in addon translation layer |
| DISPLACEMENT | input:Height | APPROXIMATED | Height/Scale approximated as a bump perturbation via the pkg223b bump machinery (pkg257); Midlevel is read but mathematically inert for a gradient-based bump; Normal and displacement_method/space are read only to emit the DISPLACEMENT warning, never consumed |
| DISPLACEMENT | input:Midlevel | APPROXIMATED | Height/Scale approximated as a bump perturbation via the pkg223b bump machinery (pkg257); Midlevel is read but mathematically inert for a gradient-based bump; Normal and displacement_method/space are read only to emit the DISPLACEMENT warning, never consumed |
| DISPLACEMENT | input:Scale | APPROXIMATED | Height/Scale approximated as a bump perturbation via the pkg223b bump machinery (pkg257); Midlevel is read but mathematically inert for a gradient-based bump; Normal and displacement_method/space are read only to emit the DISPLACEMENT warning, never consumed |
| DISPLACEMENT | input:Normal | DROPPED-SILENT | Height/Scale approximated as a bump perturbation via the pkg223b bump machinery (pkg257); Midlevel is read but mathematically inert for a gradient-based bump; Normal and displacement_method/space are read only to emit the DISPLACEMENT warning, never consumed |
| DISPLACEMENT | prop:space | DROPPED-SILENT | property ENUM |
| EEVEE_SPECULAR | input:Base Color | DROPPED-SILENT | no handler in addon translation layer |
| EEVEE_SPECULAR | input:Specular | DROPPED-SILENT | no handler in addon translation layer |
| EEVEE_SPECULAR | input:Roughness | DROPPED-SILENT | no handler in addon translation layer |
| EEVEE_SPECULAR | input:Emissive Color | DROPPED-SILENT | no handler in addon translation layer |
| EEVEE_SPECULAR | input:Transparency | DROPPED-SILENT | no handler in addon translation layer |
| EEVEE_SPECULAR | input:Normal | DROPPED-SILENT | no handler in addon translation layer |
| EEVEE_SPECULAR | input:Clear Coat | DROPPED-SILENT | no handler in addon translation layer |
| EEVEE_SPECULAR | input:Clear Coat Roughness | DROPPED-SILENT | no handler in addon translation layer |
| EEVEE_SPECULAR | input:Clear Coat Normal | DROPPED-SILENT | no handler in addon translation layer |
| EEVEE_SPECULAR | input:Weight | DROPPED-SILENT | no handler in addon translation layer |
| EMISSION | input:Color | SUPPORTED |  |
| EMISSION | input:Strength | SUPPORTED |  |
| EMISSION | input:Weight | DROPPED-SILENT |  |
| CURVE_FLOAT | input:Factor | DROPPED-SILENT | no handler in addon translation layer |
| CURVE_FLOAT | input:Value | DROPPED-SILENT | no handler in addon translation layer |
| FRESNEL | input:IOR | DROPPED-SILENT | no handler in addon translation layer |
| FRESNEL | input:Normal | DROPPED-SILENT | no handler in addon translation layer |
| GAMMA | input:Color | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| GAMMA | input:Gamma | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| HOLDOUT | input:Weight | DROPPED-SILENT | no handler in addon translation layer |
| HUE_SAT | input:Hue | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| HUE_SAT | input:Saturation | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| HUE_SAT | input:Value | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| HUE_SAT | input:Factor | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| HUE_SAT | input:Color | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| INVERT | input:Factor | DROPPED-SILENT |  |
| INVERT | input:Color | SUPPORTED |  |
| LAYER_WEIGHT | input:Blend | DROPPED-SILENT | no handler in addon translation layer |
| LAYER_WEIGHT | input:Normal | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_FALLOFF | input:Strength | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_FALLOFF | input:Smooth | DROPPED-SILENT | no handler in addon translation layer |
| MAP_RANGE | input:Value | DROPPED-SILENT | no handler in addon translation layer |
| MAP_RANGE | input:From Min | DROPPED-SILENT | no handler in addon translation layer |
| MAP_RANGE | input:From Max | DROPPED-SILENT | no handler in addon translation layer |
| MAP_RANGE | input:To Min | DROPPED-SILENT | no handler in addon translation layer |
| MAP_RANGE | input:To Max | DROPPED-SILENT | no handler in addon translation layer |
| MAP_RANGE | input:Steps | DROPPED-SILENT | no handler in addon translation layer |
| MAP_RANGE | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| MAP_RANGE | input:From Min[From_Min_FLOAT3] | DROPPED-SILENT | no handler in addon translation layer |
| MAP_RANGE | input:From Max[From_Max_FLOAT3] | DROPPED-SILENT | no handler in addon translation layer |
| MAP_RANGE | input:To Min[To_Min_FLOAT3] | DROPPED-SILENT | no handler in addon translation layer |
| MAP_RANGE | input:To Max[To_Max_FLOAT3] | DROPPED-SILENT | no handler in addon translation layer |
| MAP_RANGE | input:Steps[Steps_FLOAT3] | DROPPED-SILENT | no handler in addon translation layer |
| MAP_RANGE | prop:clamp | DROPPED-SILENT | property BOOLEAN |
| MAP_RANGE | prop:data_type | DROPPED-SILENT | property ENUM |
| MAP_RANGE | prop:interpolation_type | DROPPED-SILENT | property ENUM |
| MAPPING | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| MAPPING | input:Location | DROPPED-SILENT | no handler in addon translation layer |
| MAPPING | input:Rotation | DROPPED-SILENT | no handler in addon translation layer |
| MAPPING | input:Scale | DROPPED-SILENT | no handler in addon translation layer |
| MAPPING | prop:vector_type | DROPPED-SILENT | property ENUM |
| MATH | input:Value | DROPPED-SILENT | no handler in addon translation layer |
| MATH | input:Value[Value_001] | DROPPED-SILENT | no handler in addon translation layer |
| MATH | input:Value[Value_002] | DROPPED-SILENT | no handler in addon translation layer |
| MATH | prop:operation | DROPPED-SILENT | property ENUM |
| MATH | prop:use_clamp | DROPPED-SILENT | property BOOLEAN |
| MIX | input:Factor[Factor_Float] | DROPPED-SILENT |  |
| MIX | input:Factor[Factor_Vector] | DROPPED-SILENT |  |
| MIX | input:A[A_Float] | DROPPED-SILENT |  |
| MIX | input:B[B_Float] | DROPPED-SILENT |  |
| MIX | input:A[A_Vector] | DROPPED-SILENT |  |
| MIX | input:B[B_Vector] | DROPPED-SILENT |  |
| MIX | input:A[A_Color] | DROPPED-SILENT |  |
| MIX | input:B[B_Color] | DROPPED-SILENT |  |
| MIX | input:A[A_Rotation] | DROPPED-SILENT |  |
| MIX | input:B[B_Rotation] | DROPPED-SILENT |  |
| MIX | prop:blend_type | SUPPORTED |  |
| MIX | prop:clamp_factor | DROPPED-SILENT | property BOOLEAN |
| MIX | prop:clamp_result | DROPPED-SILENT | property BOOLEAN |
| MIX | prop:data_type | DROPPED-SILENT | property ENUM |
| MIX | prop:factor_mode | DROPPED-SILENT | property ENUM |
| MIX_RGB | input:Factor | DROPPED-SILENT |  |
| MIX_RGB | input:Color1 | DROPPED-SILENT |  |
| MIX_RGB | input:Color2 | DROPPED-SILENT |  |
| MIX_RGB | prop:blend_type | SUPPORTED |  |
| MIX_RGB | prop:use_alpha | DROPPED-SILENT | property BOOLEAN |
| MIX_RGB | prop:use_clamp | DROPPED-SILENT | property BOOLEAN |
| MIX_SHADER | input:Factor | DROPPED-SILENT |  |
| MIX_SHADER | input:Shader | DROPPED-SILENT |  |
| MIX_SHADER | input:Shader[Shader_001] | DROPPED-SILENT |  |
| NORMAL | input:Normal | DROPPED-SILENT | no handler in addon translation layer |
| NORMAL_MAP | input:Strength | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| NORMAL_MAP | input:Color | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| NORMAL_MAP | prop:base | DROPPED-SILENT | property ENUM |
| NORMAL_MAP | prop:convention | DROPPED-SILENT | property ENUM |
| NORMAL_MAP | prop:space | DROPPED-SILENT | property ENUM |
| OUTPUT_AOV | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_AOV | input:Value | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_LIGHT | input:Surface | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_LIGHT | prop:is_active_output | DROPPED-SILENT | property BOOLEAN |
| OUTPUT_LIGHT | prop:target | DROPPED-SILENT | property ENUM |
| OUTPUT_LINESTYLE | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_LINESTYLE | input:Color Fac | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_LINESTYLE | input:Alpha | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_LINESTYLE | input:Alpha Fac | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_LINESTYLE | prop:blend_type | DROPPED-SILENT | property ENUM |
| OUTPUT_LINESTYLE | prop:is_active_output | DROPPED-SILENT | property BOOLEAN |
| OUTPUT_LINESTYLE | prop:target | DROPPED-SILENT | property ENUM |
| OUTPUT_LINESTYLE | prop:use_alpha | DROPPED-SILENT | property BOOLEAN |
| OUTPUT_LINESTYLE | prop:use_clamp | DROPPED-SILENT | property BOOLEAN |
| OUTPUT_MATERIAL | input:Surface | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_MATERIAL | input:Volume | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_MATERIAL | input:Displacement | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_MATERIAL | input:Thickness | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_MATERIAL | prop:is_active_output | DROPPED-SILENT | property BOOLEAN |
| OUTPUT_MATERIAL | prop:target | DROPPED-SILENT | property ENUM |
| OUTPUT_WORLD | input:Surface | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_WORLD | input:Volume | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_WORLD | prop:is_active_output | DROPPED-SILENT | property BOOLEAN |
| OUTPUT_WORLD | prop:target | DROPPED-SILENT | property ENUM |
| CURVE_RGB | input:Factor | DROPPED-SILENT | no handler in addon translation layer |
| CURVE_RGB | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| RGBTOBW | input:Color | SUPPORTED |  |
| ShaderNodeRadialTiling | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| ShaderNodeRadialTiling | input:Sides | DROPPED-SILENT | no handler in addon translation layer |
| ShaderNodeRadialTiling | input:Roundness | DROPPED-SILENT | no handler in addon translation layer |
| ShaderNodeRadialTiling | prop:normalize | DROPPED-SILENT | property BOOLEAN |
| MATERIAL_RAYCAST | input:Position | DROPPED-SILENT | no handler in addon translation layer |
| MATERIAL_RAYCAST | input:Direction | DROPPED-SILENT | no handler in addon translation layer |
| MATERIAL_RAYCAST | input:Length | DROPPED-SILENT | no handler in addon translation layer |
| MATERIAL_RAYCAST | input: | DROPPED-SILENT | no handler in addon translation layer |
| MATERIAL_RAYCAST | prop:active_index | DROPPED-SILENT | property INT |
| MATERIAL_RAYCAST | prop:only_local | DROPPED-SILENT | property BOOLEAN |
| SCRIPT | prop:mode | DROPPED-SILENT | property ENUM |
| SCRIPT | prop:use_auto_update | DROPPED-SILENT | property BOOLEAN |
| SEPARATE_COLOR | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| SEPARATE_COLOR | prop:mode | DROPPED-SILENT | property ENUM |
| SEPXYZ | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| SHADERTORGB | input:Shader | DROPPED-SILENT | no handler in addon translation layer |
| SQUEEZE | input:Value | DROPPED-SILENT | no handler in addon translation layer |
| SQUEEZE | input:Width | DROPPED-SILENT | no handler in addon translation layer |
| SQUEEZE | input:Center | DROPPED-SILENT | no handler in addon translation layer |
| SUBSURFACE_SCATTERING | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| SUBSURFACE_SCATTERING | input:Scale | DROPPED-SILENT | no handler in addon translation layer |
| SUBSURFACE_SCATTERING | input:Radius | DROPPED-SILENT | no handler in addon translation layer |
| SUBSURFACE_SCATTERING | input:IOR | DROPPED-SILENT | no handler in addon translation layer |
| SUBSURFACE_SCATTERING | input:Roughness | DROPPED-SILENT | no handler in addon translation layer |
| SUBSURFACE_SCATTERING | input:Anisotropy | DROPPED-SILENT | no handler in addon translation layer |
| SUBSURFACE_SCATTERING | input:Normal | DROPPED-SILENT | no handler in addon translation layer |
| SUBSURFACE_SCATTERING | input:Weight | DROPPED-SILENT | no handler in addon translation layer |
| SUBSURFACE_SCATTERING | prop:falloff | DROPPED-SILENT | property ENUM |
| TANGENT | prop:axis | DROPPED-SILENT | property ENUM |
| TANGENT | prop:direction_type | DROPPED-SILENT | property ENUM |
| TEX_BRICK | input:Vector | DROPPED-SILENT |  |
| TEX_BRICK | input:Color1 | SUPPORTED |  |
| TEX_BRICK | input:Color2 | SUPPORTED |  |
| TEX_BRICK | input:Mortar | DROPPED-SILENT |  |
| TEX_BRICK | input:Scale | SUPPORTED |  |
| TEX_BRICK | input:Mortar Size | SUPPORTED |  |
| TEX_BRICK | input:Mortar Smooth | SUPPORTED |  |
| TEX_BRICK | input:Bias | SUPPORTED |  |
| TEX_BRICK | input:Brick Width | SUPPORTED |  |
| TEX_BRICK | input:Row Height | SUPPORTED |  |
| TEX_BRICK | prop:offset | DROPPED-SILENT | property FLOAT |
| TEX_BRICK | prop:offset_frequency | SUPPORTED |  |
| TEX_BRICK | prop:squash | SUPPORTED |  |
| TEX_BRICK | prop:squash_frequency | SUPPORTED |  |
| TEX_CHECKER | input:Vector | DROPPED-SILENT |  |
| TEX_CHECKER | input:Color1 | SUPPORTED |  |
| TEX_CHECKER | input:Color2 | SUPPORTED |  |
| TEX_CHECKER | input:Scale | SUPPORTED |  |
| TEX_COORD | prop:from_instancer | DROPPED-SILENT | property BOOLEAN |
| TEX_ENVIRONMENT | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| TEX_ENVIRONMENT | prop:interpolation | DROPPED-SILENT | property ENUM |
| TEX_ENVIRONMENT | prop:projection | DROPPED-SILENT | property ENUM |
| TEX_GABOR | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| TEX_GABOR | input:Scale | DROPPED-SILENT | no handler in addon translation layer |
| TEX_GABOR | input:Frequency | DROPPED-SILENT | no handler in addon translation layer |
| TEX_GABOR | input:Anisotropy | DROPPED-SILENT | no handler in addon translation layer |
| TEX_GABOR | input:Orientation[Orientation 2D] | DROPPED-SILENT | no handler in addon translation layer |
| TEX_GABOR | input:Orientation[Orientation 3D] | DROPPED-SILENT | no handler in addon translation layer |
| TEX_GABOR | prop:gabor_type | DROPPED-SILENT | property ENUM |
| TEX_GRADIENT | input:Vector | DROPPED-SILENT |  |
| TEX_GRADIENT | prop:gradient_type | SUPPORTED |  |
| TEX_IES | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| TEX_IES | input:Strength | DROPPED-SILENT | no handler in addon translation layer |
| TEX_IES | prop:mode | DROPPED-SILENT | property ENUM |
| TEX_IMAGE | input:Vector | SUPPORTED | op-VM / vector-input path (pkg219/pkg223) |
| TEX_IMAGE | prop:extension | DROPPED-SILENT | property ENUM |
| TEX_IMAGE | prop:interpolation | DROPPED-SILENT | property ENUM |
| TEX_IMAGE | prop:projection | DROPPED-SILENT | property ENUM |
| TEX_IMAGE | prop:projection_blend | DROPPED-SILENT | property FLOAT |
| TEX_MAGIC | input:Vector | DROPPED-SILENT |  |
| TEX_MAGIC | input:Scale | SUPPORTED |  |
| TEX_MAGIC | input:Distortion | SUPPORTED |  |
| TEX_MAGIC | prop:turbulence_depth | SUPPORTED |  |
| TEX_NOISE | input:Vector | DROPPED-SILENT |  |
| TEX_NOISE | input:W | DROPPED-SILENT |  |
| TEX_NOISE | input:Scale | SUPPORTED |  |
| TEX_NOISE | input:Detail | SUPPORTED |  |
| TEX_NOISE | input:Roughness | SUPPORTED |  |
| TEX_NOISE | input:Lacunarity | SUPPORTED |  |
| TEX_NOISE | input:Offset | SUPPORTED |  |
| TEX_NOISE | input:Gain | SUPPORTED |  |
| TEX_NOISE | input:Distortion | SUPPORTED |  |
| TEX_NOISE | prop:noise_dimensions | DROPPED-SILENT | property ENUM |
| TEX_NOISE | prop:noise_type | SUPPORTED |  |
| TEX_NOISE | prop:normalize | SUPPORTED |  |
| TEX_SKY | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| TEX_SKY | prop:aerosol_density | DROPPED-SILENT | property FLOAT |
| TEX_SKY | prop:air_density | DROPPED-SILENT | property FLOAT |
| TEX_SKY | prop:altitude | DROPPED-SILENT | property FLOAT |
| TEX_SKY | prop:ground_albedo | DROPPED-SILENT | property FLOAT |
| TEX_SKY | prop:ozone_density | DROPPED-SILENT | property FLOAT |
| TEX_SKY | prop:sky_type | DROPPED-SILENT | property ENUM |
| TEX_SKY | prop:sun_direction | DROPPED-SILENT | property FLOAT |
| TEX_SKY | prop:sun_disc | DROPPED-SILENT | property BOOLEAN |
| TEX_SKY | prop:sun_elevation | DROPPED-SILENT | property FLOAT |
| TEX_SKY | prop:sun_intensity | DROPPED-SILENT | property FLOAT |
| TEX_SKY | prop:sun_rotation | DROPPED-SILENT | property FLOAT |
| TEX_SKY | prop:sun_size | DROPPED-SILENT | property FLOAT |
| TEX_SKY | prop:turbidity | DROPPED-SILENT | property FLOAT |
| TEX_VORONOI | input:Vector | DROPPED-SILENT |  |
| TEX_VORONOI | input:W | DROPPED-SILENT |  |
| TEX_VORONOI | input:Scale | SUPPORTED |  |
| TEX_VORONOI | input:Detail | SUPPORTED |  |
| TEX_VORONOI | input:Roughness | SUPPORTED |  |
| TEX_VORONOI | input:Lacunarity | SUPPORTED |  |
| TEX_VORONOI | input:Smoothness | SUPPORTED |  |
| TEX_VORONOI | input:Exponent | SUPPORTED |  |
| TEX_VORONOI | input:Randomness | SUPPORTED |  |
| TEX_VORONOI | prop:distance | SUPPORTED |  |
| TEX_VORONOI | prop:feature | SUPPORTED |  |
| TEX_VORONOI | prop:normalize | SUPPORTED |  |
| TEX_VORONOI | prop:voronoi_dimensions | DROPPED-SILENT | property ENUM |
| TEX_WAVE | input:Vector | DROPPED-SILENT |  |
| TEX_WAVE | input:Scale | SUPPORTED |  |
| TEX_WAVE | input:Distortion | SUPPORTED |  |
| TEX_WAVE | input:Detail | SUPPORTED |  |
| TEX_WAVE | input:Detail Scale | SUPPORTED |  |
| TEX_WAVE | input:Detail Roughness | SUPPORTED |  |
| TEX_WAVE | input:Phase Offset | SUPPORTED |  |
| TEX_WAVE | prop:bands_direction | SUPPORTED |  |
| TEX_WAVE | prop:rings_direction | SUPPORTED |  |
| TEX_WAVE | prop:wave_profile | SUPPORTED |  |
| TEX_WAVE | prop:wave_type | SUPPORTED |  |
| TEX_WHITE_NOISE | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| TEX_WHITE_NOISE | input:W | DROPPED-SILENT | no handler in addon translation layer |
| TEX_WHITE_NOISE | prop:noise_dimensions | DROPPED-SILENT | property ENUM |
| UVALONGSTROKE | prop:use_tips | DROPPED-SILENT | property BOOLEAN |
| UVMAP | prop:from_instancer | DROPPED-SILENT | property BOOLEAN |
| VALTORGB | input:Factor | DROPPED-SILENT |  |
| CURVE_VEC | input:Factor | DROPPED-SILENT | no handler in addon translation layer |
| CURVE_VEC | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| VECTOR_DISPLACEMENT | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| VECTOR_DISPLACEMENT | input:Midlevel | DROPPED-SILENT | no handler in addon translation layer |
| VECTOR_DISPLACEMENT | input:Scale | DROPPED-SILENT | no handler in addon translation layer |
| VECTOR_DISPLACEMENT | prop:space | DROPPED-SILENT | property ENUM |
| VECT_MATH | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| VECT_MATH | input:Vector[Vector_001] | DROPPED-SILENT | no handler in addon translation layer |
| VECT_MATH | input:Vector[Vector_002] | DROPPED-SILENT | no handler in addon translation layer |
| VECT_MATH | input:Scale | DROPPED-SILENT | no handler in addon translation layer |
| VECT_MATH | prop:operation | DROPPED-SILENT | property ENUM |
| VECTOR_ROTATE | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| VECTOR_ROTATE | input:Center | DROPPED-SILENT | no handler in addon translation layer |
| VECTOR_ROTATE | input:Axis | DROPPED-SILENT | no handler in addon translation layer |
| VECTOR_ROTATE | input:Angle | DROPPED-SILENT | no handler in addon translation layer |
| VECTOR_ROTATE | input:Rotation | DROPPED-SILENT | no handler in addon translation layer |
| VECTOR_ROTATE | prop:invert | DROPPED-SILENT | property BOOLEAN |
| VECTOR_ROTATE | prop:rotation_type | DROPPED-SILENT | property ENUM |
| VECT_TRANSFORM | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| VECT_TRANSFORM | prop:convert_from | DROPPED-SILENT | property ENUM |
| VECT_TRANSFORM | prop:convert_to | DROPPED-SILENT | property ENUM |
| VECT_TRANSFORM | prop:vector_type | DROPPED-SILENT | property ENUM |
| VOLUME_ABSORPTION | input:Color | APPROXIMATED | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_ABSORPTION | input:Density | APPROXIMATED | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_ABSORPTION | input:Weight | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_COEFFICIENTS | input:Weight | DROPPED-SILENT | no handler in addon translation layer |
| VOLUME_COEFFICIENTS | input:Absorption Coefficients | DROPPED-SILENT | no handler in addon translation layer |
| VOLUME_COEFFICIENTS | input:Scatter Coefficients | DROPPED-SILENT | no handler in addon translation layer |
| VOLUME_COEFFICIENTS | input:Anisotropy | DROPPED-SILENT | no handler in addon translation layer |
| VOLUME_COEFFICIENTS | input:IOR | DROPPED-SILENT | no handler in addon translation layer |
| VOLUME_COEFFICIENTS | input:Backscatter | DROPPED-SILENT | no handler in addon translation layer |
| VOLUME_COEFFICIENTS | input:Alpha | DROPPED-SILENT | no handler in addon translation layer |
| VOLUME_COEFFICIENTS | input:Diameter | DROPPED-SILENT | no handler in addon translation layer |
| VOLUME_COEFFICIENTS | input:Emission Coefficients | DROPPED-SILENT | no handler in addon translation layer |
| VOLUME_COEFFICIENTS | prop:phase | DROPPED-SILENT | property ENUM |
| PRINCIPLED_VOLUME | input:Color | APPROXIMATED | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Color Attribute | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Density | APPROXIMATED | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Density Attribute | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Anisotropy | APPROXIMATED | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Absorption Color | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Emission Strength | APPROXIMATED | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Emission Color | APPROXIMATED | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Blackbody Intensity | APPROXIMATED | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Blackbody Tint | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Temperature | APPROXIMATED | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Temperature Attribute | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Weight | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | input:Color | APPROXIMATED | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | input:Density | APPROXIMATED | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | input:Anisotropy | APPROXIMATED | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | input:IOR | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | input:Backscatter | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | input:Alpha | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | input:Diameter | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | input:Weight | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | prop:phase | DROPPED-SILENT | property ENUM |
| WAVELENGTH | input:Wavelength | SUPPORTED |  |
| WIREFRAME | input:Size | DROPPED-SILENT | no handler in addon translation layer |
| WIREFRAME | prop:use_pixel_size | DROPPED-SILENT | property BOOLEAN |

### world

| Feature | Socket/Property | Classification | Notes |
|---------|-----------------|----------------|-------|
| World | use_nodes | SUPPORTED | node tree handled separately |
| World | light_linking_shadow_linking | DROPPED-SILENT | per-object light-linking / shadow-linking collections have no Astroray equivalent; declared out of scope by owner decision 2026-09-08 -- one gap-card row, not per-object rows |

