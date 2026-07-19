# Blender Parity Coverage Matrix — Phase A (AST-Scanned Evidence)

**Generated:** 5.1.2

## Summary

- **SUPPORTED**: 122 features
- **APPROXIMATED**: 1 features
- **DROPPED-SILENT**: 401 features ⚠️
- **UNKNOWN**: 0 features
- **Total**: 524 features

## ⚠️ Stale Socket Name Findings (Latent Addon Bugs)

These socket names appear in addon handlers but do NOT exist on the live node in this Blender version.
The addon believes it supports these sockets, but `node.inputs.get('...')` returns None at runtime,
so the default silently wins. Each entry is a real latent bug.

- **BRIGHTCONTRAST**: socket `Bright` (addon __init__.py line 2168, line 2356)
- **HUE_SAT**: socket `Fac` (addon __init__.py line 2168, line 2338)
- **INVERT**: socket `Fac` (addon __init__.py line 2324)
- **MATH**: socket `0` (addon __init__.py line 2222)
- **MATH**: socket `1` (addon __init__.py line 2222)
- **MATH**: socket `2` (addon __init__.py line 2222)
- **MIX**: socket `1` (addon __init__.py line 2312)
- **MIX**: socket `Color1` (addon __init__.py line 2312)
- **MIX**: socket `2` (addon __init__.py line 2312)
- **MIX**: socket `Color2` (addon __init__.py line 2312)
- **MIX**: socket `Fac` (addon __init__.py line 2312)
- **MIX_RGB**: socket `1` (addon __init__.py line 2312)
- **MIX_RGB**: socket `A` (addon __init__.py line 2312)
- **MIX_RGB**: socket `2` (addon __init__.py line 2312)
- **MIX_RGB**: socket `B` (addon __init__.py line 2312)
- **MIX_RGB**: socket `Fac` (addon __init__.py line 2312)
- **NORMAL_MAP**: socket `Normal` (addon __init__.py line 2168, line 2499)
- **TEX_BRICK**: socket `Offset` (addon __init__.py line 2848)
- **TEX_BRICK**: socket `Color3` (addon __init__.py line 2848)
- **VALTORGB**: socket `Fac` (addon __init__.py line 2366)

## DROPPED-SILENT Features (Failure Mode)

These features are silently ignored by the addon with no warning:

### camera

- **Camera**: `aperture_blades`
- **Camera**: `aperture_rotation`
- **Camera**: `aperture_ratio`
- **Camera**: `type`
- **Camera**: `clip_start`
- **Camera**: `clip_end`

### light

- **POINT**: `specular_factor`
- **SUN**: `specular_factor`
- **SPOT**: `specular_factor`
- **SPOT**: `show_cone`
- **AREA**: `specular_factor`

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
- **ADD_SHADER**: `input:Shader`
- **AMBIENT_OCCLUSION**: `input:Color` — no handler in addon translation layer
- **AMBIENT_OCCLUSION**: `input:Distance` — no handler in addon translation layer
- **AMBIENT_OCCLUSION**: `input:Normal` — no handler in addon translation layer
- **AMBIENT_OCCLUSION**: `prop:inside` — property BOOLEAN
- **AMBIENT_OCCLUSION**: `prop:only_local` — property BOOLEAN
- **AMBIENT_OCCLUSION**: `prop:samples` — property INT
- **ATTRIBUTE**: `prop:attribute_type` — property ENUM
- **BACKGROUND**: `input:Weight`
- **BEVEL**: `input:Radius` — no handler in addon translation layer
- **BEVEL**: `input:Normal` — no handler in addon translation layer
- **BEVEL**: `prop:samples` — property INT
- **BRIGHTCONTRAST**: `input:Brightness`
- **BSDF_GLOSSY**: `input:Color`
- **BSDF_GLOSSY**: `input:Roughness`
- **BSDF_GLOSSY**: `input:Rotation`
- **BSDF_GLOSSY**: `input:Normal`
- **BSDF_GLOSSY**: `input:Tangent`
- **BSDF_GLOSSY**: `input:Weight`
- **BSDF_GLOSSY**: `prop:distribution` — property ENUM
- **BSDF_DIFFUSE**: `input:Color`
- **BSDF_DIFFUSE**: `input:Roughness`
- **BSDF_DIFFUSE**: `input:Normal`
- **BSDF_DIFFUSE**: `input:Weight`
- **BSDF_GLASS**: `input:Color`
- **BSDF_GLASS**: `input:Roughness`
- **BSDF_GLASS**: `input:IOR`
- **BSDF_GLASS**: `input:Normal`
- **BSDF_GLASS**: `input:Weight`
- **BSDF_GLASS**: `input:Thin Film Thickness`
- **BSDF_GLASS**: `input:Thin Film IOR`
- **BSDF_GLASS**: `prop:distribution` — property ENUM
- **BSDF_HAIR**: `input:Color` — no handler in addon translation layer
- **BSDF_HAIR**: `input:Offset` — no handler in addon translation layer
- **BSDF_HAIR**: `input:RoughnessU` — no handler in addon translation layer
- **BSDF_HAIR**: `input:RoughnessV` — no handler in addon translation layer
- **BSDF_HAIR**: `input:Tangent` — no handler in addon translation layer
- **BSDF_HAIR**: `input:Weight` — no handler in addon translation layer
- **BSDF_HAIR**: `prop:component` — property ENUM
- **BSDF_HAIR_PRINCIPLED**: `input:Color` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `input:Melanin` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `input:Melanin Redness` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `input:Tint` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `input:Absorption Coefficient` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `input:Aspect Ratio` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `input:Roughness` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `input:Radial Roughness` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `input:Coat` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `input:IOR` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `input:Offset` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `input:Random Color` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `input:Random Roughness` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `input:Random` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `input:Weight` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `input:Reflection` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `input:Transmission` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `input:Secondary Reflection` — no handler in addon translation layer
- **BSDF_HAIR_PRINCIPLED**: `prop:model` — property ENUM
- **BSDF_HAIR_PRINCIPLED**: `prop:parametrization` — property ENUM
- **BSDF_METALLIC**: `input:Edge Tint`
- **BSDF_METALLIC**: `input:IOR`
- **BSDF_METALLIC**: `input:Extinction`
- **BSDF_METALLIC**: `input:Roughness`
- **BSDF_METALLIC**: `input:Anisotropy`
- **BSDF_METALLIC**: `input:Rotation`
- **BSDF_METALLIC**: `input:Normal`
- **BSDF_METALLIC**: `input:Tangent`
- **BSDF_METALLIC**: `input:Weight`
- **BSDF_METALLIC**: `input:Thin Film Thickness`
- **BSDF_METALLIC**: `input:Thin Film IOR`
- **BSDF_METALLIC**: `prop:distribution` — property ENUM
- **BSDF_METALLIC**: `prop:fresnel_type` — property ENUM
- **BSDF_PRINCIPLED**: `input:Base Color`
- **BSDF_PRINCIPLED**: `input:Metallic`
- **BSDF_PRINCIPLED**: `input:Roughness`
- **BSDF_PRINCIPLED**: `input:IOR`
- **BSDF_PRINCIPLED**: `input:Alpha`
- **BSDF_PRINCIPLED**: `input:Normal`
- **BSDF_PRINCIPLED**: `input:Weight`
- **BSDF_PRINCIPLED**: `input:Diffuse Roughness`
- **BSDF_PRINCIPLED**: `input:Subsurface Weight`
- **BSDF_PRINCIPLED**: `input:Subsurface Radius`
- **BSDF_PRINCIPLED**: `input:Subsurface Scale`
- **BSDF_PRINCIPLED**: `input:Subsurface IOR`
- **BSDF_PRINCIPLED**: `input:Subsurface Anisotropy`
- **BSDF_PRINCIPLED**: `input:Specular IOR Level`
- **BSDF_PRINCIPLED**: `input:Specular Tint`
- **BSDF_PRINCIPLED**: `input:Anisotropic`
- **BSDF_PRINCIPLED**: `input:Anisotropic Rotation`
- **BSDF_PRINCIPLED**: `input:Tangent`
- **BSDF_PRINCIPLED**: `input:Transmission Weight`
- **BSDF_PRINCIPLED**: `input:Coat Weight`
- **BSDF_PRINCIPLED**: `input:Coat Roughness`
- **BSDF_PRINCIPLED**: `input:Coat IOR`
- **BSDF_PRINCIPLED**: `input:Coat Tint`
- **BSDF_PRINCIPLED**: `input:Coat Normal`
- **BSDF_PRINCIPLED**: `input:Sheen Weight`
- **BSDF_PRINCIPLED**: `input:Sheen Roughness`
- **BSDF_PRINCIPLED**: `input:Sheen Tint`
- **BSDF_PRINCIPLED**: `input:Emission Color`
- **BSDF_PRINCIPLED**: `input:Emission Strength`
- **BSDF_PRINCIPLED**: `input:Thin Film Thickness`
- **BSDF_PRINCIPLED**: `input:Thin Film IOR`
- **BSDF_PRINCIPLED**: `prop:distribution` — property ENUM
- **BSDF_PRINCIPLED**: `prop:subsurface_method` — property ENUM
- **BSDF_RAY_PORTAL**: `input:Color` — no handler in addon translation layer
- **BSDF_RAY_PORTAL**: `input:Position` — no handler in addon translation layer
- **BSDF_RAY_PORTAL**: `input:Direction` — no handler in addon translation layer
- **BSDF_RAY_PORTAL**: `input:Weight` — no handler in addon translation layer
- **BSDF_REFRACTION**: `input:Color`
- **BSDF_REFRACTION**: `input:Roughness`
- **BSDF_REFRACTION**: `input:IOR`
- **BSDF_REFRACTION**: `input:Normal`
- **BSDF_REFRACTION**: `input:Weight`
- **BSDF_REFRACTION**: `prop:distribution` — property ENUM
- **BSDF_SHEEN**: `input:Color`
- **BSDF_SHEEN**: `input:Roughness`
- **BSDF_SHEEN**: `input:Normal`
- **BSDF_SHEEN**: `input:Weight`
- **BSDF_SHEEN**: `prop:distribution` — property ENUM
- **BSDF_TOON**: `input:Color` — no handler in addon translation layer
- **BSDF_TOON**: `input:Size` — no handler in addon translation layer
- **BSDF_TOON**: `input:Smooth` — no handler in addon translation layer
- **BSDF_TOON**: `input:Normal` — no handler in addon translation layer
- **BSDF_TOON**: `input:Weight` — no handler in addon translation layer
- **BSDF_TOON**: `prop:component` — property ENUM
- **BSDF_TRANSLUCENT**: `input:Color`
- **BSDF_TRANSLUCENT**: `input:Normal`
- **BSDF_TRANSLUCENT**: `input:Weight`
- **BSDF_TRANSPARENT**: `input:Color`
- **BSDF_TRANSPARENT**: `input:Weight`
- **BUMP**: `input:Strength`
- **BUMP**: `input:Distance`
- **BUMP**: `input:Filter Width`
- **BUMP**: `prop:invert` — property BOOLEAN
- **CLAMP**: `prop:clamp_type` — property ENUM
- **COMBINE_COLOR**: `input:Red` — no handler in addon translation layer
- **COMBINE_COLOR**: `input:Green` — no handler in addon translation layer
- **COMBINE_COLOR**: `input:Blue` — no handler in addon translation layer
- **COMBINE_COLOR**: `prop:mode` — property ENUM
- **COMBXYZ**: `input:X` — no handler in addon translation layer
- **COMBXYZ**: `input:Y` — no handler in addon translation layer
- **COMBXYZ**: `input:Z` — no handler in addon translation layer
- **DISPLACEMENT**: `input:Height` — no handler in addon translation layer
- **DISPLACEMENT**: `input:Midlevel` — no handler in addon translation layer
- **DISPLACEMENT**: `input:Scale` — no handler in addon translation layer
- **DISPLACEMENT**: `input:Normal` — no handler in addon translation layer
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
- **EMISSION**: `input:Color`
- **EMISSION**: `input:Strength`
- **EMISSION**: `input:Weight`
- **CURVE_FLOAT**: `input:Factor` — no handler in addon translation layer
- **CURVE_FLOAT**: `input:Value` — no handler in addon translation layer
- **FRESNEL**: `input:IOR` — no handler in addon translation layer
- **FRESNEL**: `input:Normal` — no handler in addon translation layer
- **HOLDOUT**: `input:Weight` — no handler in addon translation layer
- **HUE_SAT**: `input:Factor`
- **INVERT**: `input:Factor`
- **LAYER_WEIGHT**: `input:Blend` — no handler in addon translation layer
- **LAYER_WEIGHT**: `input:Normal` — no handler in addon translation layer
- **LIGHT_FALLOFF**: `input:Strength` — no handler in addon translation layer
- **LIGHT_FALLOFF**: `input:Smooth` — no handler in addon translation layer
- **MAP_RANGE**: `input:Steps`
- **MAP_RANGE**: `input:Vector`
- **MAP_RANGE**: `input:Steps`
- **MAP_RANGE**: `prop:data_type` — property ENUM
- **MAPPING**: `prop:vector_type` — property ENUM
- **MATH**: `input:Value`
- **MATH**: `input:Value`
- **MATH**: `input:Value`
- **MIX**: `prop:clamp_factor` — property BOOLEAN
- **MIX**: `prop:clamp_result` — property BOOLEAN
- **MIX**: `prop:data_type` — property ENUM
- **MIX**: `prop:factor_mode` — property ENUM
- **MIX_RGB**: `prop:use_alpha` — property BOOLEAN
- **MIX_RGB**: `prop:use_clamp` — property BOOLEAN
- **MIX_SHADER**: `input:Factor`
- **MIX_SHADER**: `input:Shader`
- **MIX_SHADER**: `input:Shader`
- **NORMAL**: `input:Normal` — no handler in addon translation layer
- **NORMAL_MAP**: `input:Strength`
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
- **OUTPUT_MATERIAL**: `input:Surface`
- **OUTPUT_MATERIAL**: `input:Volume`
- **OUTPUT_MATERIAL**: `input:Displacement`
- **OUTPUT_MATERIAL**: `input:Thickness`
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
- **TEX_ENVIRONMENT**: `input:Vector`
- **TEX_ENVIRONMENT**: `prop:interpolation` — property ENUM
- **TEX_ENVIRONMENT**: `prop:projection` — property ENUM
- **TEX_GABOR**: `input:Vector` — no handler in addon translation layer
- **TEX_GABOR**: `input:Scale` — no handler in addon translation layer
- **TEX_GABOR**: `input:Frequency` — no handler in addon translation layer
- **TEX_GABOR**: `input:Anisotropy` — no handler in addon translation layer
- **TEX_GABOR**: `input:Orientation` — no handler in addon translation layer
- **TEX_GABOR**: `input:Orientation` — no handler in addon translation layer
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
- **TEX_NOISE**: `input:Scale`
- **TEX_NOISE**: `input:Detail`
- **TEX_NOISE**: `input:Roughness`
- **TEX_NOISE**: `input:Lacunarity`
- **TEX_NOISE**: `input:Offset`
- **TEX_NOISE**: `input:Gain`
- **TEX_NOISE**: `input:Distortion`
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
- **TEX_VORONOI**: `input:Scale`
- **TEX_VORONOI**: `input:Detail`
- **TEX_VORONOI**: `input:Roughness`
- **TEX_VORONOI**: `input:Lacunarity`
- **TEX_VORONOI**: `input:Smoothness`
- **TEX_VORONOI**: `input:Exponent`
- **TEX_VORONOI**: `input:Randomness`
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
- **VECT_MATH**: `input:Vector` — no handler in addon translation layer
- **VECT_MATH**: `input:Vector` — no handler in addon translation layer
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
- **VOLUME_ABSORPTION**: `input:Color`
- **VOLUME_ABSORPTION**: `input:Density`
- **VOLUME_ABSORPTION**: `input:Weight`
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
- **PRINCIPLED_VOLUME**: `input:Color`
- **PRINCIPLED_VOLUME**: `input:Color Attribute`
- **PRINCIPLED_VOLUME**: `input:Density`
- **PRINCIPLED_VOLUME**: `input:Density Attribute`
- **PRINCIPLED_VOLUME**: `input:Anisotropy`
- **PRINCIPLED_VOLUME**: `input:Absorption Color`
- **PRINCIPLED_VOLUME**: `input:Emission Strength`
- **PRINCIPLED_VOLUME**: `input:Emission Color`
- **PRINCIPLED_VOLUME**: `input:Blackbody Intensity`
- **PRINCIPLED_VOLUME**: `input:Blackbody Tint`
- **PRINCIPLED_VOLUME**: `input:Temperature`
- **PRINCIPLED_VOLUME**: `input:Temperature Attribute`
- **PRINCIPLED_VOLUME**: `input:Weight`
- **VOLUME_SCATTER**: `input:Color`
- **VOLUME_SCATTER**: `input:Density`
- **VOLUME_SCATTER**: `input:Anisotropy`
- **VOLUME_SCATTER**: `input:IOR`
- **VOLUME_SCATTER**: `input:Backscatter`
- **VOLUME_SCATTER**: `input:Alpha`
- **VOLUME_SCATTER**: `input:Diameter`
- **VOLUME_SCATTER**: `input:Weight`
- **VOLUME_SCATTER**: `prop:phase` — property ENUM
- **WIREFRAME**: `input:Size` — no handler in addon translation layer
- **WIREFRAME**: `prop:use_pixel_size` — property BOOLEAN

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
| ADD_SHADER | input:Shader | DROPPED-SILENT |  |
| AMBIENT_OCCLUSION | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| AMBIENT_OCCLUSION | input:Distance | DROPPED-SILENT | no handler in addon translation layer |
| AMBIENT_OCCLUSION | input:Normal | DROPPED-SILENT | no handler in addon translation layer |
| AMBIENT_OCCLUSION | prop:inside | DROPPED-SILENT | property BOOLEAN |
| AMBIENT_OCCLUSION | prop:only_local | DROPPED-SILENT | property BOOLEAN |
| AMBIENT_OCCLUSION | prop:samples | DROPPED-SILENT | property INT |
| ATTRIBUTE | prop:attribute_type | DROPPED-SILENT | property ENUM |
| BACKGROUND | input:Color | SUPPORTED |  |
| BACKGROUND | input:Strength | SUPPORTED |  |
| BACKGROUND | input:Weight | DROPPED-SILENT |  |
| BEVEL | input:Radius | DROPPED-SILENT | no handler in addon translation layer |
| BEVEL | input:Normal | DROPPED-SILENT | no handler in addon translation layer |
| BEVEL | prop:samples | DROPPED-SILENT | property INT |
| BLACKBODY | input:Temperature | SUPPORTED |  |
| BRIGHTCONTRAST | input:Color | SUPPORTED |  |
| BRIGHTCONTRAST | input:Brightness | DROPPED-SILENT |  |
| BRIGHTCONTRAST | input:Contrast | SUPPORTED |  |
| BSDF_GLOSSY | input:Color | DROPPED-SILENT |  |
| BSDF_GLOSSY | input:Roughness | DROPPED-SILENT |  |
| BSDF_GLOSSY | input:Anisotropy | SUPPORTED |  |
| BSDF_GLOSSY | input:Rotation | DROPPED-SILENT |  |
| BSDF_GLOSSY | input:Normal | DROPPED-SILENT |  |
| BSDF_GLOSSY | input:Tangent | DROPPED-SILENT |  |
| BSDF_GLOSSY | input:Weight | DROPPED-SILENT |  |
| BSDF_GLOSSY | prop:distribution | DROPPED-SILENT | property ENUM |
| BSDF_DIFFUSE | input:Color | DROPPED-SILENT |  |
| BSDF_DIFFUSE | input:Roughness | DROPPED-SILENT |  |
| BSDF_DIFFUSE | input:Normal | DROPPED-SILENT |  |
| BSDF_DIFFUSE | input:Weight | DROPPED-SILENT |  |
| BSDF_GLASS | input:Color | DROPPED-SILENT |  |
| BSDF_GLASS | input:Roughness | DROPPED-SILENT |  |
| BSDF_GLASS | input:IOR | DROPPED-SILENT |  |
| BSDF_GLASS | input:Normal | DROPPED-SILENT |  |
| BSDF_GLASS | input:Weight | DROPPED-SILENT |  |
| BSDF_GLASS | input:Thin Film Thickness | DROPPED-SILENT |  |
| BSDF_GLASS | input:Thin Film IOR | DROPPED-SILENT |  |
| BSDF_GLASS | prop:distribution | DROPPED-SILENT | property ENUM |
| BSDF_HAIR | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR | input:Offset | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR | input:RoughnessU | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR | input:RoughnessV | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR | input:Tangent | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR | input:Weight | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR | prop:component | DROPPED-SILENT | property ENUM |
| BSDF_HAIR_PRINCIPLED | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | input:Melanin | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | input:Melanin Redness | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | input:Tint | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | input:Absorption Coefficient | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | input:Aspect Ratio | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | input:Roughness | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | input:Radial Roughness | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | input:Coat | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | input:IOR | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | input:Offset | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | input:Random Color | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | input:Random Roughness | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | input:Random | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | input:Weight | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | input:Reflection | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | input:Transmission | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | input:Secondary Reflection | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_HAIR_PRINCIPLED | prop:model | DROPPED-SILENT | property ENUM |
| BSDF_HAIR_PRINCIPLED | prop:parametrization | DROPPED-SILENT | property ENUM |
| BSDF_METALLIC | input:Base Color | APPROXIMATED |  |
| BSDF_METALLIC | input:Edge Tint | DROPPED-SILENT |  |
| BSDF_METALLIC | input:IOR | DROPPED-SILENT |  |
| BSDF_METALLIC | input:Extinction | DROPPED-SILENT |  |
| BSDF_METALLIC | input:Roughness | DROPPED-SILENT |  |
| BSDF_METALLIC | input:Anisotropy | DROPPED-SILENT |  |
| BSDF_METALLIC | input:Rotation | DROPPED-SILENT |  |
| BSDF_METALLIC | input:Normal | DROPPED-SILENT |  |
| BSDF_METALLIC | input:Tangent | DROPPED-SILENT |  |
| BSDF_METALLIC | input:Weight | DROPPED-SILENT |  |
| BSDF_METALLIC | input:Thin Film Thickness | DROPPED-SILENT |  |
| BSDF_METALLIC | input:Thin Film IOR | DROPPED-SILENT |  |
| BSDF_METALLIC | prop:distribution | DROPPED-SILENT | property ENUM |
| BSDF_METALLIC | prop:fresnel_type | DROPPED-SILENT | property ENUM |
| BSDF_PRINCIPLED | input:Base Color | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Metallic | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Roughness | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:IOR | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Alpha | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Normal | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Weight | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Diffuse Roughness | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Subsurface Weight | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Subsurface Radius | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Subsurface Scale | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Subsurface IOR | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Subsurface Anisotropy | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Specular IOR Level | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Specular Tint | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Anisotropic | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Anisotropic Rotation | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Tangent | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Transmission Weight | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Coat Weight | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Coat Roughness | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Coat IOR | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Coat Tint | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Coat Normal | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Sheen Weight | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Sheen Roughness | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Sheen Tint | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Emission Color | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Emission Strength | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Thin Film Thickness | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Thin Film IOR | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | prop:distribution | DROPPED-SILENT | property ENUM |
| BSDF_PRINCIPLED | prop:subsurface_method | DROPPED-SILENT | property ENUM |
| BSDF_RAY_PORTAL | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_RAY_PORTAL | input:Position | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_RAY_PORTAL | input:Direction | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_RAY_PORTAL | input:Weight | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_REFRACTION | input:Color | DROPPED-SILENT |  |
| BSDF_REFRACTION | input:Roughness | DROPPED-SILENT |  |
| BSDF_REFRACTION | input:IOR | DROPPED-SILENT |  |
| BSDF_REFRACTION | input:Normal | DROPPED-SILENT |  |
| BSDF_REFRACTION | input:Weight | DROPPED-SILENT |  |
| BSDF_REFRACTION | prop:distribution | DROPPED-SILENT | property ENUM |
| BSDF_SHEEN | input:Color | DROPPED-SILENT |  |
| BSDF_SHEEN | input:Roughness | DROPPED-SILENT |  |
| BSDF_SHEEN | input:Normal | DROPPED-SILENT |  |
| BSDF_SHEEN | input:Weight | DROPPED-SILENT |  |
| BSDF_SHEEN | prop:distribution | DROPPED-SILENT | property ENUM |
| BSDF_TOON | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_TOON | input:Size | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_TOON | input:Smooth | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_TOON | input:Normal | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_TOON | input:Weight | DROPPED-SILENT | no handler in addon translation layer |
| BSDF_TOON | prop:component | DROPPED-SILENT | property ENUM |
| BSDF_TRANSLUCENT | input:Color | DROPPED-SILENT |  |
| BSDF_TRANSLUCENT | input:Normal | DROPPED-SILENT |  |
| BSDF_TRANSLUCENT | input:Weight | DROPPED-SILENT |  |
| BSDF_TRANSPARENT | input:Color | DROPPED-SILENT |  |
| BSDF_TRANSPARENT | input:Weight | DROPPED-SILENT |  |
| BUMP | input:Strength | DROPPED-SILENT |  |
| BUMP | input:Distance | DROPPED-SILENT |  |
| BUMP | input:Filter Width | DROPPED-SILENT |  |
| BUMP | input:Height | SUPPORTED |  |
| BUMP | input:Normal | SUPPORTED |  |
| BUMP | prop:invert | DROPPED-SILENT | property BOOLEAN |
| CLAMP | input:Value | SUPPORTED |  |
| CLAMP | input:Min | SUPPORTED |  |
| CLAMP | input:Max | SUPPORTED |  |
| CLAMP | prop:clamp_type | DROPPED-SILENT | property ENUM |
| COMBINE_COLOR | input:Red | DROPPED-SILENT | no handler in addon translation layer |
| COMBINE_COLOR | input:Green | DROPPED-SILENT | no handler in addon translation layer |
| COMBINE_COLOR | input:Blue | DROPPED-SILENT | no handler in addon translation layer |
| COMBINE_COLOR | prop:mode | DROPPED-SILENT | property ENUM |
| COMBXYZ | input:X | DROPPED-SILENT | no handler in addon translation layer |
| COMBXYZ | input:Y | DROPPED-SILENT | no handler in addon translation layer |
| COMBXYZ | input:Z | DROPPED-SILENT | no handler in addon translation layer |
| DISPLACEMENT | input:Height | DROPPED-SILENT | no handler in addon translation layer |
| DISPLACEMENT | input:Midlevel | DROPPED-SILENT | no handler in addon translation layer |
| DISPLACEMENT | input:Scale | DROPPED-SILENT | no handler in addon translation layer |
| DISPLACEMENT | input:Normal | DROPPED-SILENT | no handler in addon translation layer |
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
| EMISSION | input:Color | DROPPED-SILENT |  |
| EMISSION | input:Strength | DROPPED-SILENT |  |
| EMISSION | input:Weight | DROPPED-SILENT |  |
| CURVE_FLOAT | input:Factor | DROPPED-SILENT | no handler in addon translation layer |
| CURVE_FLOAT | input:Value | DROPPED-SILENT | no handler in addon translation layer |
| FRESNEL | input:IOR | DROPPED-SILENT | no handler in addon translation layer |
| FRESNEL | input:Normal | DROPPED-SILENT | no handler in addon translation layer |
| GAMMA | input:Color | SUPPORTED |  |
| GAMMA | input:Gamma | SUPPORTED |  |
| HOLDOUT | input:Weight | DROPPED-SILENT | no handler in addon translation layer |
| HUE_SAT | input:Hue | SUPPORTED |  |
| HUE_SAT | input:Saturation | SUPPORTED |  |
| HUE_SAT | input:Value | SUPPORTED |  |
| HUE_SAT | input:Factor | DROPPED-SILENT |  |
| HUE_SAT | input:Color | SUPPORTED |  |
| INVERT | input:Factor | DROPPED-SILENT |  |
| INVERT | input:Color | SUPPORTED |  |
| LAYER_WEIGHT | input:Blend | DROPPED-SILENT | no handler in addon translation layer |
| LAYER_WEIGHT | input:Normal | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_FALLOFF | input:Strength | DROPPED-SILENT | no handler in addon translation layer |
| LIGHT_FALLOFF | input:Smooth | DROPPED-SILENT | no handler in addon translation layer |
| MAP_RANGE | input:Value | SUPPORTED |  |
| MAP_RANGE | input:From Min | SUPPORTED |  |
| MAP_RANGE | input:From Max | SUPPORTED |  |
| MAP_RANGE | input:To Min | SUPPORTED |  |
| MAP_RANGE | input:To Max | SUPPORTED |  |
| MAP_RANGE | input:Steps | DROPPED-SILENT |  |
| MAP_RANGE | input:Vector | DROPPED-SILENT |  |
| MAP_RANGE | input:From Min | SUPPORTED |  |
| MAP_RANGE | input:From Max | SUPPORTED |  |
| MAP_RANGE | input:To Min | SUPPORTED |  |
| MAP_RANGE | input:To Max | SUPPORTED |  |
| MAP_RANGE | input:Steps | DROPPED-SILENT |  |
| MAP_RANGE | prop:clamp | SUPPORTED |  |
| MAP_RANGE | prop:data_type | DROPPED-SILENT | property ENUM |
| MAP_RANGE | prop:interpolation_type | SUPPORTED |  |
| MAPPING | input:Vector | SUPPORTED |  |
| MAPPING | input:Location | SUPPORTED |  |
| MAPPING | input:Rotation | SUPPORTED |  |
| MAPPING | input:Scale | SUPPORTED |  |
| MAPPING | prop:vector_type | DROPPED-SILENT | property ENUM |
| MATH | input:Value | DROPPED-SILENT |  |
| MATH | input:Value | DROPPED-SILENT |  |
| MATH | input:Value | DROPPED-SILENT |  |
| MATH | prop:operation | SUPPORTED |  |
| MATH | prop:use_clamp | SUPPORTED |  |
| MIX | input:Factor | SUPPORTED |  |
| MIX | input:Factor | SUPPORTED |  |
| MIX | input:A | SUPPORTED |  |
| MIX | input:B | SUPPORTED |  |
| MIX | input:A | SUPPORTED |  |
| MIX | input:B | SUPPORTED |  |
| MIX | input:A | SUPPORTED |  |
| MIX | input:B | SUPPORTED |  |
| MIX | input:A | SUPPORTED |  |
| MIX | input:B | SUPPORTED |  |
| MIX | prop:blend_type | SUPPORTED |  |
| MIX | prop:clamp_factor | DROPPED-SILENT | property BOOLEAN |
| MIX | prop:clamp_result | DROPPED-SILENT | property BOOLEAN |
| MIX | prop:data_type | DROPPED-SILENT | property ENUM |
| MIX | prop:factor_mode | DROPPED-SILENT | property ENUM |
| MIX_RGB | input:Factor | SUPPORTED |  |
| MIX_RGB | input:Color1 | SUPPORTED |  |
| MIX_RGB | input:Color2 | SUPPORTED |  |
| MIX_RGB | prop:blend_type | SUPPORTED |  |
| MIX_RGB | prop:use_alpha | DROPPED-SILENT | property BOOLEAN |
| MIX_RGB | prop:use_clamp | DROPPED-SILENT | property BOOLEAN |
| MIX_SHADER | input:Factor | DROPPED-SILENT |  |
| MIX_SHADER | input:Shader | DROPPED-SILENT |  |
| MIX_SHADER | input:Shader | DROPPED-SILENT |  |
| NORMAL | input:Normal | DROPPED-SILENT | no handler in addon translation layer |
| NORMAL_MAP | input:Strength | DROPPED-SILENT |  |
| NORMAL_MAP | input:Color | SUPPORTED |  |
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
| OUTPUT_MATERIAL | input:Surface | DROPPED-SILENT |  |
| OUTPUT_MATERIAL | input:Volume | DROPPED-SILENT |  |
| OUTPUT_MATERIAL | input:Displacement | DROPPED-SILENT |  |
| OUTPUT_MATERIAL | input:Thickness | DROPPED-SILENT |  |
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
| TEX_ENVIRONMENT | input:Vector | DROPPED-SILENT |  |
| TEX_ENVIRONMENT | prop:interpolation | DROPPED-SILENT | property ENUM |
| TEX_ENVIRONMENT | prop:projection | DROPPED-SILENT | property ENUM |
| TEX_GABOR | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| TEX_GABOR | input:Scale | DROPPED-SILENT | no handler in addon translation layer |
| TEX_GABOR | input:Frequency | DROPPED-SILENT | no handler in addon translation layer |
| TEX_GABOR | input:Anisotropy | DROPPED-SILENT | no handler in addon translation layer |
| TEX_GABOR | input:Orientation | DROPPED-SILENT | no handler in addon translation layer |
| TEX_GABOR | input:Orientation | DROPPED-SILENT | no handler in addon translation layer |
| TEX_GABOR | prop:gabor_type | DROPPED-SILENT | property ENUM |
| TEX_GRADIENT | input:Vector | DROPPED-SILENT |  |
| TEX_GRADIENT | prop:gradient_type | SUPPORTED |  |
| TEX_IES | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| TEX_IES | input:Strength | DROPPED-SILENT | no handler in addon translation layer |
| TEX_IES | prop:mode | DROPPED-SILENT | property ENUM |
| TEX_IMAGE | input:Vector | SUPPORTED |  |
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
| TEX_NOISE | input:Scale | DROPPED-SILENT |  |
| TEX_NOISE | input:Detail | DROPPED-SILENT |  |
| TEX_NOISE | input:Roughness | DROPPED-SILENT |  |
| TEX_NOISE | input:Lacunarity | DROPPED-SILENT |  |
| TEX_NOISE | input:Offset | DROPPED-SILENT |  |
| TEX_NOISE | input:Gain | DROPPED-SILENT |  |
| TEX_NOISE | input:Distortion | DROPPED-SILENT |  |
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
| TEX_VORONOI | input:Scale | DROPPED-SILENT |  |
| TEX_VORONOI | input:Detail | DROPPED-SILENT |  |
| TEX_VORONOI | input:Roughness | DROPPED-SILENT |  |
| TEX_VORONOI | input:Lacunarity | DROPPED-SILENT |  |
| TEX_VORONOI | input:Smoothness | DROPPED-SILENT |  |
| TEX_VORONOI | input:Exponent | DROPPED-SILENT |  |
| TEX_VORONOI | input:Randomness | DROPPED-SILENT |  |
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
| VECT_MATH | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| VECT_MATH | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
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
| VOLUME_ABSORPTION | input:Color | DROPPED-SILENT |  |
| VOLUME_ABSORPTION | input:Density | DROPPED-SILENT |  |
| VOLUME_ABSORPTION | input:Weight | DROPPED-SILENT |  |
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
| PRINCIPLED_VOLUME | input:Color | DROPPED-SILENT |  |
| PRINCIPLED_VOLUME | input:Color Attribute | DROPPED-SILENT |  |
| PRINCIPLED_VOLUME | input:Density | DROPPED-SILENT |  |
| PRINCIPLED_VOLUME | input:Density Attribute | DROPPED-SILENT |  |
| PRINCIPLED_VOLUME | input:Anisotropy | DROPPED-SILENT |  |
| PRINCIPLED_VOLUME | input:Absorption Color | DROPPED-SILENT |  |
| PRINCIPLED_VOLUME | input:Emission Strength | DROPPED-SILENT |  |
| PRINCIPLED_VOLUME | input:Emission Color | DROPPED-SILENT |  |
| PRINCIPLED_VOLUME | input:Blackbody Intensity | DROPPED-SILENT |  |
| PRINCIPLED_VOLUME | input:Blackbody Tint | DROPPED-SILENT |  |
| PRINCIPLED_VOLUME | input:Temperature | DROPPED-SILENT |  |
| PRINCIPLED_VOLUME | input:Temperature Attribute | DROPPED-SILENT |  |
| PRINCIPLED_VOLUME | input:Weight | DROPPED-SILENT |  |
| VOLUME_SCATTER | input:Color | DROPPED-SILENT |  |
| VOLUME_SCATTER | input:Density | DROPPED-SILENT |  |
| VOLUME_SCATTER | input:Anisotropy | DROPPED-SILENT |  |
| VOLUME_SCATTER | input:IOR | DROPPED-SILENT |  |
| VOLUME_SCATTER | input:Backscatter | DROPPED-SILENT |  |
| VOLUME_SCATTER | input:Alpha | DROPPED-SILENT |  |
| VOLUME_SCATTER | input:Diameter | DROPPED-SILENT |  |
| VOLUME_SCATTER | input:Weight | DROPPED-SILENT |  |
| VOLUME_SCATTER | prop:phase | DROPPED-SILENT | property ENUM |
| WAVELENGTH | input:Wavelength | SUPPORTED |  |
| WIREFRAME | input:Size | DROPPED-SILENT | no handler in addon translation layer |
| WIREFRAME | prop:use_pixel_size | DROPPED-SILENT | property BOOLEAN |

### world

| Feature | Socket/Property | Classification | Notes |
|---------|-----------------|----------------|-------|
| World | use_nodes | SUPPORTED | node tree handled separately |

