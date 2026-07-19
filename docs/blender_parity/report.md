# Blender Parity Coverage Matrix — Phase A

**Generated:** 5.1.2

## Summary

- **SUPPORTED**: 163 features
- **APPROXIMATED**: 9 features
- **DROPPED-SILENT**: 250 features ⚠️
- **UNKNOWN-CRASH**: 0 features
- **Total**: 422 features

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

- **BSDF_PRINCIPLED**: `input:Alpha`
- **BSDF_PRINCIPLED**: `input:Weight`
- **BSDF_PRINCIPLED**: `input:Diffuse Roughness`
- **BSDF_PRINCIPLED**: `input:Subsurface Radius`
- **BSDF_PRINCIPLED**: `input:Subsurface Scale`
- **BSDF_PRINCIPLED**: `input:Subsurface IOR`
- **BSDF_PRINCIPLED**: `input:Subsurface Anisotropy`
- **BSDF_PRINCIPLED**: `input:Specular IOR Level`
- **BSDF_PRINCIPLED**: `input:Specular Tint`
- **BSDF_PRINCIPLED**: `input:Anisotropic Rotation`
- **BSDF_PRINCIPLED**: `input:Tangent`
- **BSDF_PRINCIPLED**: `input:Coat IOR`
- **BSDF_PRINCIPLED**: `input:Coat Tint`
- **BSDF_PRINCIPLED**: `input:Coat Normal`
- **BSDF_PRINCIPLED**: `input:Sheen Roughness`
- **BSDF_PRINCIPLED**: `input:Sheen Tint`
- **BSDF_PRINCIPLED**: `input:Thin Film Thickness`
- **BSDF_PRINCIPLED**: `input:Thin Film IOR`
- **BSDF_PRINCIPLED**: `prop:distribution` — property ENUM
- **BSDF_PRINCIPLED**: `prop:subsurface_method` — property ENUM
- **BSDF_DIFFUSE**: `input:Normal` — Oren-Nayar diffuse approximated with Disney rough diffuse
- **BSDF_DIFFUSE**: `input:Weight` — Oren-Nayar diffuse approximated with Disney rough diffuse
- **BSDF_GLOSSY**: `input:Anisotropy`
- **BSDF_GLOSSY**: `input:Rotation`
- **BSDF_GLOSSY**: `input:Normal`
- **BSDF_GLOSSY**: `input:Tangent`
- **BSDF_GLOSSY**: `input:Weight`
- **BSDF_GLOSSY**: `prop:distribution` — property ENUM
- **BSDF_GLOSSY**: `input:Anisotropy`
- **BSDF_GLOSSY**: `input:Rotation`
- **BSDF_GLOSSY**: `input:Normal`
- **BSDF_GLOSSY**: `input:Tangent`
- **BSDF_GLOSSY**: `input:Weight`
- **BSDF_GLOSSY**: `prop:distribution` — property ENUM
- **BSDF_GLASS**: `input:Normal`
- **BSDF_GLASS**: `input:Weight`
- **BSDF_GLASS**: `input:Thin Film Thickness`
- **BSDF_GLASS**: `input:Thin Film IOR`
- **BSDF_GLASS**: `prop:distribution` — property ENUM
- **BSDF_TRANSLUCENT**: `input:Normal` — true normal-flipped diffuse transmission approximated with rough transmission
- **BSDF_TRANSLUCENT**: `input:Weight` — true normal-flipped diffuse transmission approximated with rough transmission
- **BSDF_TRANSPARENT**: `input:Weight`
- **BSDF_REFRACTION**: `input:Normal` — pure refraction without Fresnel reflection approximated with Disney transmission
- **BSDF_REFRACTION**: `input:Weight` — pure refraction without Fresnel reflection approximated with Disney transmission
- **BSDF_REFRACTION**: `prop:distribution` — property ENUM
- **BSDF_SHEEN**: `input:Normal` — Cycles microfiber sheen approximated with Disney sheen
- **BSDF_SHEEN**: `prop:distribution` — property ENUM
- **EMISSION**: `input:Weight`
- **BACKGROUND**: `input:Color` — no handler in addon translation layer
- **BACKGROUND**: `input:Strength` — no handler in addon translation layer
- **BACKGROUND**: `input:Weight` — no handler in addon translation layer
- **HOLDOUT**: `input:Weight` — no handler in addon translation layer
- **VOLUME_ABSORPTION**: `input:Color` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_ABSORPTION**: `input:Density` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_ABSORPTION**: `input:Weight` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_SCATTER**: `input:Color` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_SCATTER**: `input:Density` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_SCATTER**: `input:Anisotropy` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_SCATTER**: `input:IOR` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_SCATTER**: `input:Backscatter` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_SCATTER**: `input:Alpha` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_SCATTER**: `input:Diameter` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_SCATTER**: `input:Weight` — mapped to glass IOR=1.0 (volume not fully implemented)
- **VOLUME_SCATTER**: `prop:phase` — property ENUM
- **PRINCIPLED_VOLUME**: `input:Color` — mapped to glass IOR=1.0 (volume not fully implemented)
- **PRINCIPLED_VOLUME**: `input:Color Attribute` — mapped to glass IOR=1.0 (volume not fully implemented)
- **PRINCIPLED_VOLUME**: `input:Density` — mapped to glass IOR=1.0 (volume not fully implemented)
- **PRINCIPLED_VOLUME**: `input:Density Attribute` — mapped to glass IOR=1.0 (volume not fully implemented)
- **PRINCIPLED_VOLUME**: `input:Anisotropy` — mapped to glass IOR=1.0 (volume not fully implemented)
- **PRINCIPLED_VOLUME**: `input:Absorption Color` — mapped to glass IOR=1.0 (volume not fully implemented)
- **PRINCIPLED_VOLUME**: `input:Emission Strength` — mapped to glass IOR=1.0 (volume not fully implemented)
- **PRINCIPLED_VOLUME**: `input:Emission Color` — mapped to glass IOR=1.0 (volume not fully implemented)
- **PRINCIPLED_VOLUME**: `input:Blackbody Intensity` — mapped to glass IOR=1.0 (volume not fully implemented)
- **PRINCIPLED_VOLUME**: `input:Blackbody Tint` — mapped to glass IOR=1.0 (volume not fully implemented)
- **PRINCIPLED_VOLUME**: `input:Temperature` — mapped to glass IOR=1.0 (volume not fully implemented)
- **PRINCIPLED_VOLUME**: `input:Temperature Attribute` — mapped to glass IOR=1.0 (volume not fully implemented)
- **PRINCIPLED_VOLUME**: `input:Weight` — mapped to glass IOR=1.0 (volume not fully implemented)
- **MIX_SHADER**: `input:Factor`
- **TEX_IMAGE**: `input:Vector` — load_blender_image path
- **TEX_IMAGE**: `prop:extension` — property ENUM
- **TEX_IMAGE**: `prop:interpolation` — property ENUM
- **TEX_IMAGE**: `prop:projection` — property ENUM
- **TEX_IMAGE**: `prop:projection_blend` — property FLOAT
- **TEX_ENVIRONMENT**: `input:Vector` — no handler in addon translation layer
- **TEX_ENVIRONMENT**: `prop:interpolation` — property ENUM
- **TEX_ENVIRONMENT**: `prop:projection` — property ENUM
- **TEX_NOISE**: `input:W`
- **TEX_NOISE**: `input:Lacunarity`
- **TEX_NOISE**: `input:Offset`
- **TEX_NOISE**: `input:Gain`
- **TEX_NOISE**: `prop:noise_dimensions` — property ENUM
- **TEX_NOISE**: `prop:noise_type` — property ENUM
- **TEX_NOISE**: `prop:normalize` — property BOOLEAN
- **TEX_VORONOI**: `input:W`
- **TEX_VORONOI**: `input:Detail`
- **TEX_VORONOI**: `input:Roughness`
- **TEX_VORONOI**: `input:Lacunarity`
- **TEX_VORONOI**: `input:Smoothness`
- **TEX_VORONOI**: `input:Exponent`
- **TEX_VORONOI**: `prop:distance` — property ENUM
- **TEX_VORONOI**: `prop:feature` — property ENUM
- **TEX_VORONOI**: `prop:normalize` — property BOOLEAN
- **TEX_VORONOI**: `prop:voronoi_dimensions` — property ENUM
- **TEX_WAVE**: `input:Detail Scale`
- **TEX_WAVE**: `input:Detail Roughness`
- **TEX_WAVE**: `input:Phase Offset`
- **TEX_WAVE**: `prop:bands_direction` — property ENUM
- **TEX_WAVE**: `prop:rings_direction` — property ENUM
- **TEX_BRICK**: `input:Mortar Size`
- **TEX_BRICK**: `input:Mortar Smooth`
- **TEX_BRICK**: `input:Bias`
- **TEX_BRICK**: `input:Brick Width`
- **TEX_BRICK**: `input:Row Height`
- **TEX_BRICK**: `prop:offset` — property FLOAT
- **TEX_BRICK**: `prop:offset_frequency` — property INT
- **TEX_BRICK**: `prop:squash` — property FLOAT
- **TEX_BRICK**: `prop:squash_frequency` — property INT
- **TEX_COORD**: `prop:from_instancer` — property BOOLEAN
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
- **TEX_IES**: `input:Vector` — no handler in addon translation layer
- **TEX_IES**: `input:Strength` — no handler in addon translation layer
- **TEX_IES**: `prop:mode` — property ENUM
- **TEX_WHITE_NOISE**: `input:Vector` — no handler in addon translation layer
- **TEX_WHITE_NOISE**: `input:W` — no handler in addon translation layer
- **TEX_WHITE_NOISE**: `prop:noise_dimensions` — property ENUM
- **MIX**: `prop:blend_type` — property ENUM
- **MIX**: `prop:clamp_factor` — property BOOLEAN
- **MIX**: `prop:clamp_result` — property BOOLEAN
- **MIX**: `prop:data_type` — property ENUM
- **MIX**: `prop:factor_mode` — property ENUM
- **HUE_SAT**: `input:Hue` — no handler in addon translation layer
- **HUE_SAT**: `input:Saturation` — no handler in addon translation layer
- **HUE_SAT**: `input:Value` — no handler in addon translation layer
- **HUE_SAT**: `input:Factor` — no handler in addon translation layer
- **HUE_SAT**: `input:Color` — no handler in addon translation layer
- **GAMMA**: `input:Color` — no handler in addon translation layer
- **GAMMA**: `input:Gamma` — no handler in addon translation layer
- **BRIGHTCONTRAST**: `input:Color` — no handler in addon translation layer
- **BRIGHTCONTRAST**: `input:Brightness` — no handler in addon translation layer
- **BRIGHTCONTRAST**: `input:Contrast` — no handler in addon translation layer
- **MAPPING**: `prop:vector_type` — property ENUM
- **NORMAL_MAP**: `prop:base` — property ENUM
- **NORMAL_MAP**: `prop:convention` — property ENUM
- **NORMAL_MAP**: `prop:space` — property ENUM
- **BUMP**: `prop:invert` — property BOOLEAN
- **DISPLACEMENT**: `prop:space` — property ENUM
- **VECTOR_DISPLACEMENT**: `prop:space` — property ENUM
- **VECT_TRANSFORM**: `input:Vector` — no handler in addon translation layer
- **VECT_TRANSFORM**: `prop:convert_from` — property ENUM
- **VECT_TRANSFORM**: `prop:convert_to` — property ENUM
- **VECT_TRANSFORM**: `prop:vector_type` — property ENUM
- **VECTOR_ROTATE**: `prop:invert` — property BOOLEAN
- **VECTOR_ROTATE**: `prop:rotation_type` — property ENUM
- **MATH**: `prop:operation` — property ENUM
- **MATH**: `prop:use_clamp` — property BOOLEAN
- **VECT_MATH**: `prop:operation` — property ENUM
- **SEPXYZ**: `input:Vector` — no handler in addon translation layer
- **COMBXYZ**: `input:X` — no handler in addon translation layer
- **COMBXYZ**: `input:Y` — no handler in addon translation layer
- **COMBXYZ**: `input:Z` — no handler in addon translation layer
- **SEPARATE_COLOR**: `input:Color` — no handler in addon translation layer
- **SEPARATE_COLOR**: `prop:mode` — property ENUM
- **COMBINE_COLOR**: `input:Red` — no handler in addon translation layer
- **COMBINE_COLOR**: `input:Green` — no handler in addon translation layer
- **COMBINE_COLOR**: `input:Blue` — no handler in addon translation layer
- **COMBINE_COLOR**: `prop:mode` — property ENUM
- **BLACKBODY**: `input:Temperature` — no handler in addon translation layer
- **CLAMP**: `prop:clamp_type` — property ENUM
- **MAP_RANGE**: `prop:clamp` — property BOOLEAN
- **MAP_RANGE**: `prop:data_type` — property ENUM
- **MAP_RANGE**: `prop:interpolation_type` — property ENUM
- **ATTRIBUTE**: `prop:attribute_type` — property ENUM
- **TANGENT**: `prop:axis` — property ENUM
- **TANGENT**: `prop:direction_type` — property ENUM
- **UVMAP**: `prop:from_instancer` — property BOOLEAN
- **WIREFRAME**: `prop:use_pixel_size` — property BOOLEAN
- **BEVEL**: `input:Radius` — no handler in addon translation layer
- **BEVEL**: `input:Normal` — no handler in addon translation layer
- **BEVEL**: `prop:samples` — property INT
- **AMBIENT_OCCLUSION**: `input:Color` — no handler in addon translation layer
- **AMBIENT_OCCLUSION**: `input:Distance` — no handler in addon translation layer
- **AMBIENT_OCCLUSION**: `input:Normal` — no handler in addon translation layer
- **AMBIENT_OCCLUSION**: `prop:inside` — property BOOLEAN
- **AMBIENT_OCCLUSION**: `prop:only_local` — property BOOLEAN
- **AMBIENT_OCCLUSION**: `prop:samples` — property INT
- **OUTPUT_MATERIAL**: `input:Surface` — no handler in addon translation layer
- **OUTPUT_MATERIAL**: `input:Volume` — no handler in addon translation layer
- **OUTPUT_MATERIAL**: `input:Displacement` — no handler in addon translation layer
- **OUTPUT_MATERIAL**: `input:Thickness` — no handler in addon translation layer
- **OUTPUT_MATERIAL**: `prop:is_active_output` — property BOOLEAN
- **OUTPUT_MATERIAL**: `prop:target` — property ENUM
- **OUTPUT_LIGHT**: `input:Surface` — no handler in addon translation layer
- **OUTPUT_LIGHT**: `prop:is_active_output` — property BOOLEAN
- **OUTPUT_LIGHT**: `prop:target` — property ENUM
- **OUTPUT_WORLD**: `input:Surface` — no handler in addon translation layer
- **OUTPUT_WORLD**: `input:Volume` — no handler in addon translation layer
- **OUTPUT_WORLD**: `prop:is_active_output` — property BOOLEAN
- **OUTPUT_WORLD**: `prop:target` — property ENUM
- **OUTPUT_LINESTYLE**: `input:Color` — no handler in addon translation layer
- **OUTPUT_LINESTYLE**: `input:Color Fac` — no handler in addon translation layer
- **OUTPUT_LINESTYLE**: `input:Alpha` — no handler in addon translation layer
- **OUTPUT_LINESTYLE**: `input:Alpha Fac` — no handler in addon translation layer
- **OUTPUT_LINESTYLE**: `prop:blend_type` — property ENUM
- **OUTPUT_LINESTYLE**: `prop:is_active_output` — property BOOLEAN
- **OUTPUT_LINESTYLE**: `prop:target` — property ENUM
- **OUTPUT_LINESTYLE**: `prop:use_alpha` — property BOOLEAN
- **OUTPUT_LINESTYLE**: `prop:use_clamp` — property BOOLEAN
- **SCRIPT**: `prop:mode` — property ENUM
- **SCRIPT**: `prop:use_auto_update` — property BOOLEAN

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
| BSDF_PRINCIPLED | input:Base Color | SUPPORTED |  |
| BSDF_PRINCIPLED | input:Metallic | SUPPORTED |  |
| BSDF_PRINCIPLED | input:Roughness | SUPPORTED |  |
| BSDF_PRINCIPLED | input:IOR | SUPPORTED |  |
| BSDF_PRINCIPLED | input:Alpha | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Normal | SUPPORTED |  |
| BSDF_PRINCIPLED | input:Weight | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Diffuse Roughness | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Subsurface Weight | SUPPORTED |  |
| BSDF_PRINCIPLED | input:Subsurface Radius | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Subsurface Scale | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Subsurface IOR | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Subsurface Anisotropy | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Specular IOR Level | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Specular Tint | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Anisotropic | SUPPORTED |  |
| BSDF_PRINCIPLED | input:Anisotropic Rotation | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Tangent | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Transmission Weight | SUPPORTED |  |
| BSDF_PRINCIPLED | input:Coat Weight | SUPPORTED |  |
| BSDF_PRINCIPLED | input:Coat Roughness | SUPPORTED |  |
| BSDF_PRINCIPLED | input:Coat IOR | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Coat Tint | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Coat Normal | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Sheen Weight | SUPPORTED |  |
| BSDF_PRINCIPLED | input:Sheen Roughness | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Sheen Tint | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Emission Color | SUPPORTED |  |
| BSDF_PRINCIPLED | input:Emission Strength | SUPPORTED |  |
| BSDF_PRINCIPLED | input:Thin Film Thickness | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | input:Thin Film IOR | DROPPED-SILENT |  |
| BSDF_PRINCIPLED | prop:distribution | DROPPED-SILENT | property ENUM |
| BSDF_PRINCIPLED | prop:subsurface_method | DROPPED-SILENT | property ENUM |
| BSDF_DIFFUSE | input:Color | APPROXIMATED | Oren-Nayar diffuse approximated with Disney rough diffuse |
| BSDF_DIFFUSE | input:Roughness | APPROXIMATED | Oren-Nayar diffuse approximated with Disney rough diffuse |
| BSDF_DIFFUSE | input:Normal | DROPPED-SILENT | Oren-Nayar diffuse approximated with Disney rough diffuse |
| BSDF_DIFFUSE | input:Weight | DROPPED-SILENT | Oren-Nayar diffuse approximated with Disney rough diffuse |
| BSDF_GLOSSY | input:Color | SUPPORTED |  |
| BSDF_GLOSSY | input:Roughness | SUPPORTED |  |
| BSDF_GLOSSY | input:Anisotropy | DROPPED-SILENT |  |
| BSDF_GLOSSY | input:Rotation | DROPPED-SILENT |  |
| BSDF_GLOSSY | input:Normal | DROPPED-SILENT |  |
| BSDF_GLOSSY | input:Tangent | DROPPED-SILENT |  |
| BSDF_GLOSSY | input:Weight | DROPPED-SILENT |  |
| BSDF_GLOSSY | prop:distribution | DROPPED-SILENT | property ENUM |
| BSDF_GLOSSY | input:Color | SUPPORTED |  |
| BSDF_GLOSSY | input:Roughness | SUPPORTED |  |
| BSDF_GLOSSY | input:Anisotropy | DROPPED-SILENT |  |
| BSDF_GLOSSY | input:Rotation | DROPPED-SILENT |  |
| BSDF_GLOSSY | input:Normal | DROPPED-SILENT |  |
| BSDF_GLOSSY | input:Tangent | DROPPED-SILENT |  |
| BSDF_GLOSSY | input:Weight | DROPPED-SILENT |  |
| BSDF_GLOSSY | prop:distribution | DROPPED-SILENT | property ENUM |
| BSDF_GLASS | input:Color | SUPPORTED |  |
| BSDF_GLASS | input:Roughness | SUPPORTED |  |
| BSDF_GLASS | input:IOR | SUPPORTED |  |
| BSDF_GLASS | input:Normal | DROPPED-SILENT |  |
| BSDF_GLASS | input:Weight | DROPPED-SILENT |  |
| BSDF_GLASS | input:Thin Film Thickness | DROPPED-SILENT |  |
| BSDF_GLASS | input:Thin Film IOR | DROPPED-SILENT |  |
| BSDF_GLASS | prop:distribution | DROPPED-SILENT | property ENUM |
| BSDF_TRANSLUCENT | input:Color | APPROXIMATED | true normal-flipped diffuse transmission approximated with rough transmission |
| BSDF_TRANSLUCENT | input:Normal | DROPPED-SILENT | true normal-flipped diffuse transmission approximated with rough transmission |
| BSDF_TRANSLUCENT | input:Weight | DROPPED-SILENT | true normal-flipped diffuse transmission approximated with rough transmission |
| BSDF_TRANSPARENT | input:Color | SUPPORTED |  |
| BSDF_TRANSPARENT | input:Weight | DROPPED-SILENT |  |
| BSDF_REFRACTION | input:Color | APPROXIMATED | pure refraction without Fresnel reflection approximated with Disney transmission |
| BSDF_REFRACTION | input:Roughness | APPROXIMATED | pure refraction without Fresnel reflection approximated with Disney transmission |
| BSDF_REFRACTION | input:IOR | APPROXIMATED | pure refraction without Fresnel reflection approximated with Disney transmission |
| BSDF_REFRACTION | input:Normal | DROPPED-SILENT | pure refraction without Fresnel reflection approximated with Disney transmission |
| BSDF_REFRACTION | input:Weight | DROPPED-SILENT | pure refraction without Fresnel reflection approximated with Disney transmission |
| BSDF_REFRACTION | prop:distribution | DROPPED-SILENT | property ENUM |
| BSDF_SHEEN | input:Color | APPROXIMATED | Cycles microfiber sheen approximated with Disney sheen |
| BSDF_SHEEN | input:Roughness | APPROXIMATED | Cycles microfiber sheen approximated with Disney sheen |
| BSDF_SHEEN | input:Normal | DROPPED-SILENT | Cycles microfiber sheen approximated with Disney sheen |
| BSDF_SHEEN | input:Weight | APPROXIMATED | Cycles microfiber sheen approximated with Disney sheen |
| BSDF_SHEEN | prop:distribution | DROPPED-SILENT | property ENUM |
| EMISSION | input:Color | SUPPORTED |  |
| EMISSION | input:Strength | SUPPORTED |  |
| EMISSION | input:Weight | DROPPED-SILENT |  |
| BACKGROUND | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| BACKGROUND | input:Strength | DROPPED-SILENT | no handler in addon translation layer |
| BACKGROUND | input:Weight | DROPPED-SILENT | no handler in addon translation layer |
| HOLDOUT | input:Weight | DROPPED-SILENT | no handler in addon translation layer |
| VOLUME_ABSORPTION | input:Color | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_ABSORPTION | input:Density | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_ABSORPTION | input:Weight | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | input:Color | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | input:Density | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | input:Anisotropy | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | input:IOR | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | input:Backscatter | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | input:Alpha | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | input:Diameter | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | input:Weight | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| VOLUME_SCATTER | prop:phase | DROPPED-SILENT | property ENUM |
| PRINCIPLED_VOLUME | input:Color | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Color Attribute | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Density | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Density Attribute | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Anisotropy | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Absorption Color | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Emission Strength | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Emission Color | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Blackbody Intensity | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Blackbody Tint | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Temperature | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Temperature Attribute | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| PRINCIPLED_VOLUME | input:Weight | DROPPED-SILENT | mapped to glass IOR=1.0 (volume not fully implemented) |
| MIX_SHADER | input:Factor | DROPPED-SILENT |  |
| MIX_SHADER | input:Shader | SUPPORTED |  |
| MIX_SHADER | input:Shader | SUPPORTED |  |
| ADD_SHADER | input:Shader | SUPPORTED |  |
| ADD_SHADER | input:Shader | SUPPORTED |  |
| TEX_IMAGE | input:Vector | DROPPED-SILENT | load_blender_image path |
| TEX_IMAGE | prop:extension | DROPPED-SILENT | property ENUM |
| TEX_IMAGE | prop:interpolation | DROPPED-SILENT | property ENUM |
| TEX_IMAGE | prop:projection | DROPPED-SILENT | property ENUM |
| TEX_IMAGE | prop:projection_blend | DROPPED-SILENT | property FLOAT |
| TEX_ENVIRONMENT | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| TEX_ENVIRONMENT | prop:interpolation | DROPPED-SILENT | property ENUM |
| TEX_ENVIRONMENT | prop:projection | DROPPED-SILENT | property ENUM |
| TEX_CHECKER | input:Vector | SUPPORTED |  |
| TEX_CHECKER | input:Color1 | SUPPORTED |  |
| TEX_CHECKER | input:Color2 | SUPPORTED |  |
| TEX_CHECKER | input:Scale | SUPPORTED |  |
| TEX_GRADIENT | input:Vector | SUPPORTED |  |
| TEX_GRADIENT | prop:gradient_type | SUPPORTED | property ENUM —  |
| TEX_MAGIC | input:Vector | SUPPORTED |  |
| TEX_MAGIC | input:Scale | SUPPORTED |  |
| TEX_MAGIC | input:Distortion | SUPPORTED |  |
| TEX_MAGIC | prop:turbulence_depth | SUPPORTED | property INT —  |
| TEX_NOISE | input:Vector | SUPPORTED |  |
| TEX_NOISE | input:W | DROPPED-SILENT |  |
| TEX_NOISE | input:Scale | SUPPORTED |  |
| TEX_NOISE | input:Detail | SUPPORTED |  |
| TEX_NOISE | input:Roughness | SUPPORTED |  |
| TEX_NOISE | input:Lacunarity | DROPPED-SILENT |  |
| TEX_NOISE | input:Offset | DROPPED-SILENT |  |
| TEX_NOISE | input:Gain | DROPPED-SILENT |  |
| TEX_NOISE | input:Distortion | SUPPORTED |  |
| TEX_NOISE | prop:noise_dimensions | DROPPED-SILENT | property ENUM |
| TEX_NOISE | prop:noise_type | DROPPED-SILENT | property ENUM |
| TEX_NOISE | prop:normalize | DROPPED-SILENT | property BOOLEAN |
| TEX_VORONOI | input:Vector | SUPPORTED |  |
| TEX_VORONOI | input:W | DROPPED-SILENT |  |
| TEX_VORONOI | input:Scale | SUPPORTED |  |
| TEX_VORONOI | input:Detail | DROPPED-SILENT |  |
| TEX_VORONOI | input:Roughness | DROPPED-SILENT |  |
| TEX_VORONOI | input:Lacunarity | DROPPED-SILENT |  |
| TEX_VORONOI | input:Smoothness | DROPPED-SILENT |  |
| TEX_VORONOI | input:Exponent | DROPPED-SILENT |  |
| TEX_VORONOI | input:Randomness | SUPPORTED |  |
| TEX_VORONOI | prop:distance | DROPPED-SILENT | property ENUM |
| TEX_VORONOI | prop:feature | DROPPED-SILENT | property ENUM |
| TEX_VORONOI | prop:normalize | DROPPED-SILENT | property BOOLEAN |
| TEX_VORONOI | prop:voronoi_dimensions | DROPPED-SILENT | property ENUM |
| TEX_WAVE | input:Vector | SUPPORTED |  |
| TEX_WAVE | input:Scale | SUPPORTED |  |
| TEX_WAVE | input:Distortion | SUPPORTED |  |
| TEX_WAVE | input:Detail | SUPPORTED |  |
| TEX_WAVE | input:Detail Scale | DROPPED-SILENT |  |
| TEX_WAVE | input:Detail Roughness | DROPPED-SILENT |  |
| TEX_WAVE | input:Phase Offset | DROPPED-SILENT |  |
| TEX_WAVE | prop:bands_direction | DROPPED-SILENT | property ENUM |
| TEX_WAVE | prop:rings_direction | DROPPED-SILENT | property ENUM |
| TEX_WAVE | prop:wave_profile | SUPPORTED | property ENUM —  |
| TEX_WAVE | prop:wave_type | SUPPORTED | property ENUM —  |
| TEX_BRICK | input:Vector | SUPPORTED |  |
| TEX_BRICK | input:Color1 | SUPPORTED |  |
| TEX_BRICK | input:Color2 | SUPPORTED |  |
| TEX_BRICK | input:Mortar | SUPPORTED |  |
| TEX_BRICK | input:Scale | SUPPORTED |  |
| TEX_BRICK | input:Mortar Size | DROPPED-SILENT |  |
| TEX_BRICK | input:Mortar Smooth | DROPPED-SILENT |  |
| TEX_BRICK | input:Bias | DROPPED-SILENT |  |
| TEX_BRICK | input:Brick Width | DROPPED-SILENT |  |
| TEX_BRICK | input:Row Height | DROPPED-SILENT |  |
| TEX_BRICK | prop:offset | DROPPED-SILENT | property FLOAT |
| TEX_BRICK | prop:offset_frequency | DROPPED-SILENT | property INT |
| TEX_BRICK | prop:squash | DROPPED-SILENT | property FLOAT |
| TEX_BRICK | prop:squash_frequency | DROPPED-SILENT | property INT |
| TEX_COORD | prop:from_instancer | DROPPED-SILENT | property BOOLEAN |
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
| TEX_IES | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| TEX_IES | input:Strength | DROPPED-SILENT | no handler in addon translation layer |
| TEX_IES | prop:mode | DROPPED-SILENT | property ENUM |
| TEX_WHITE_NOISE | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| TEX_WHITE_NOISE | input:W | DROPPED-SILENT | no handler in addon translation layer |
| TEX_WHITE_NOISE | prop:noise_dimensions | DROPPED-SILENT | property ENUM |
| VALTORGB | input:Factor | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MIX | input:Factor | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MIX | input:Factor | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MIX | input:A | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MIX | input:B | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MIX | input:A | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MIX | input:B | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MIX | input:A | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MIX | input:B | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MIX | input:A | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MIX | input:B | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MIX | prop:blend_type | DROPPED-SILENT | property ENUM |
| MIX | prop:clamp_factor | DROPPED-SILENT | property BOOLEAN |
| MIX | prop:clamp_result | DROPPED-SILENT | property BOOLEAN |
| MIX | prop:data_type | DROPPED-SILENT | property ENUM |
| MIX | prop:factor_mode | DROPPED-SILENT | property ENUM |
| RGBTOBW | input:Color | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| INVERT | input:Factor | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| INVERT | input:Color | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| HUE_SAT | input:Hue | DROPPED-SILENT | no handler in addon translation layer |
| HUE_SAT | input:Saturation | DROPPED-SILENT | no handler in addon translation layer |
| HUE_SAT | input:Value | DROPPED-SILENT | no handler in addon translation layer |
| HUE_SAT | input:Factor | DROPPED-SILENT | no handler in addon translation layer |
| HUE_SAT | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| GAMMA | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| GAMMA | input:Gamma | DROPPED-SILENT | no handler in addon translation layer |
| BRIGHTCONTRAST | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| BRIGHTCONTRAST | input:Brightness | DROPPED-SILENT | no handler in addon translation layer |
| BRIGHTCONTRAST | input:Contrast | DROPPED-SILENT | no handler in addon translation layer |
| CURVE_RGB | input:Factor | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| CURVE_RGB | input:Color | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MAPPING | input:Vector | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MAPPING | input:Location | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MAPPING | input:Rotation | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MAPPING | input:Scale | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MAPPING | prop:vector_type | DROPPED-SILENT | property ENUM |
| NORMAL_MAP | input:Strength | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| NORMAL_MAP | input:Color | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| NORMAL_MAP | prop:base | DROPPED-SILENT | property ENUM |
| NORMAL_MAP | prop:convention | DROPPED-SILENT | property ENUM |
| NORMAL_MAP | prop:space | DROPPED-SILENT | property ENUM |
| NORMAL | input:Normal | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| BUMP | input:Strength | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| BUMP | input:Distance | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| BUMP | input:Filter Width | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| BUMP | input:Height | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| BUMP | input:Normal | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| BUMP | prop:invert | DROPPED-SILENT | property BOOLEAN |
| DISPLACEMENT | input:Height | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| DISPLACEMENT | input:Midlevel | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| DISPLACEMENT | input:Scale | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| DISPLACEMENT | input:Normal | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| DISPLACEMENT | prop:space | DROPPED-SILENT | property ENUM |
| VECTOR_DISPLACEMENT | input:Vector | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| VECTOR_DISPLACEMENT | input:Midlevel | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| VECTOR_DISPLACEMENT | input:Scale | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| VECTOR_DISPLACEMENT | prop:space | DROPPED-SILENT | property ENUM |
| VECT_TRANSFORM | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| VECT_TRANSFORM | prop:convert_from | DROPPED-SILENT | property ENUM |
| VECT_TRANSFORM | prop:convert_to | DROPPED-SILENT | property ENUM |
| VECT_TRANSFORM | prop:vector_type | DROPPED-SILENT | property ENUM |
| VECTOR_ROTATE | input:Vector | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| VECTOR_ROTATE | input:Center | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| VECTOR_ROTATE | input:Axis | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| VECTOR_ROTATE | input:Angle | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| VECTOR_ROTATE | input:Rotation | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| VECTOR_ROTATE | prop:invert | DROPPED-SILENT | property BOOLEAN |
| VECTOR_ROTATE | prop:rotation_type | DROPPED-SILENT | property ENUM |
| CURVE_VEC | input:Factor | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| CURVE_VEC | input:Vector | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MATH | input:Value | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MATH | input:Value | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MATH | input:Value | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MATH | prop:operation | DROPPED-SILENT | property ENUM |
| MATH | prop:use_clamp | DROPPED-SILENT | property BOOLEAN |
| VECT_MATH | input:Vector | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| VECT_MATH | input:Vector | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| VECT_MATH | input:Vector | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| VECT_MATH | input:Scale | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| VECT_MATH | prop:operation | DROPPED-SILENT | property ENUM |
| SEPXYZ | input:Vector | DROPPED-SILENT | no handler in addon translation layer |
| COMBXYZ | input:X | DROPPED-SILENT | no handler in addon translation layer |
| COMBXYZ | input:Y | DROPPED-SILENT | no handler in addon translation layer |
| COMBXYZ | input:Z | DROPPED-SILENT | no handler in addon translation layer |
| SEPARATE_COLOR | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| SEPARATE_COLOR | prop:mode | DROPPED-SILENT | property ENUM |
| COMBINE_COLOR | input:Red | DROPPED-SILENT | no handler in addon translation layer |
| COMBINE_COLOR | input:Green | DROPPED-SILENT | no handler in addon translation layer |
| COMBINE_COLOR | input:Blue | DROPPED-SILENT | no handler in addon translation layer |
| COMBINE_COLOR | prop:mode | DROPPED-SILENT | property ENUM |
| WAVELENGTH | input:Wavelength | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| BLACKBODY | input:Temperature | DROPPED-SILENT | no handler in addon translation layer |
| CLAMP | input:Value | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| CLAMP | input:Min | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| CLAMP | input:Max | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| CLAMP | prop:clamp_type | DROPPED-SILENT | property ENUM |
| MAP_RANGE | input:Value | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MAP_RANGE | input:From Min | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MAP_RANGE | input:From Max | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MAP_RANGE | input:To Min | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MAP_RANGE | input:To Max | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MAP_RANGE | input:Steps | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MAP_RANGE | input:Vector | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MAP_RANGE | input:From Min | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MAP_RANGE | input:From Max | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MAP_RANGE | input:To Min | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MAP_RANGE | input:To Max | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MAP_RANGE | input:Steps | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| MAP_RANGE | prop:clamp | DROPPED-SILENT | property BOOLEAN |
| MAP_RANGE | prop:data_type | DROPPED-SILENT | property ENUM |
| MAP_RANGE | prop:interpolation_type | DROPPED-SILENT | property ENUM |
| CURVE_FLOAT | input:Factor | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| CURVE_FLOAT | input:Value | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| ATTRIBUTE | prop:attribute_type | DROPPED-SILENT | property ENUM |
| FRESNEL | input:IOR | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| FRESNEL | input:Normal | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| LAYER_WEIGHT | input:Blend | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| LAYER_WEIGHT | input:Normal | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| TANGENT | prop:axis | DROPPED-SILENT | property ENUM |
| TANGENT | prop:direction_type | DROPPED-SILENT | property ENUM |
| UVMAP | prop:from_instancer | DROPPED-SILENT | property BOOLEAN |
| WIREFRAME | input:Size | SUPPORTED | utility/input node (intermediate; processed if feeding supported BSDF) |
| WIREFRAME | prop:use_pixel_size | DROPPED-SILENT | property BOOLEAN |
| BEVEL | input:Radius | DROPPED-SILENT | no handler in addon translation layer |
| BEVEL | input:Normal | DROPPED-SILENT | no handler in addon translation layer |
| BEVEL | prop:samples | DROPPED-SILENT | property INT |
| AMBIENT_OCCLUSION | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| AMBIENT_OCCLUSION | input:Distance | DROPPED-SILENT | no handler in addon translation layer |
| AMBIENT_OCCLUSION | input:Normal | DROPPED-SILENT | no handler in addon translation layer |
| AMBIENT_OCCLUSION | prop:inside | DROPPED-SILENT | property BOOLEAN |
| AMBIENT_OCCLUSION | prop:only_local | DROPPED-SILENT | property BOOLEAN |
| AMBIENT_OCCLUSION | prop:samples | DROPPED-SILENT | property INT |
| OUTPUT_MATERIAL | input:Surface | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_MATERIAL | input:Volume | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_MATERIAL | input:Displacement | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_MATERIAL | input:Thickness | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_MATERIAL | prop:is_active_output | DROPPED-SILENT | property BOOLEAN |
| OUTPUT_MATERIAL | prop:target | DROPPED-SILENT | property ENUM |
| OUTPUT_LIGHT | input:Surface | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_LIGHT | prop:is_active_output | DROPPED-SILENT | property BOOLEAN |
| OUTPUT_LIGHT | prop:target | DROPPED-SILENT | property ENUM |
| OUTPUT_WORLD | input:Surface | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_WORLD | input:Volume | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_WORLD | prop:is_active_output | DROPPED-SILENT | property BOOLEAN |
| OUTPUT_WORLD | prop:target | DROPPED-SILENT | property ENUM |
| OUTPUT_LINESTYLE | input:Color | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_LINESTYLE | input:Color Fac | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_LINESTYLE | input:Alpha | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_LINESTYLE | input:Alpha Fac | DROPPED-SILENT | no handler in addon translation layer |
| OUTPUT_LINESTYLE | prop:blend_type | DROPPED-SILENT | property ENUM |
| OUTPUT_LINESTYLE | prop:is_active_output | DROPPED-SILENT | property BOOLEAN |
| OUTPUT_LINESTYLE | prop:target | DROPPED-SILENT | property ENUM |
| OUTPUT_LINESTYLE | prop:use_alpha | DROPPED-SILENT | property BOOLEAN |
| OUTPUT_LINESTYLE | prop:use_clamp | DROPPED-SILENT | property BOOLEAN |
| SCRIPT | prop:mode | DROPPED-SILENT | property ENUM |
| SCRIPT | prop:use_auto_update | DROPPED-SILENT | property BOOLEAN |

### world

| Feature | Socket/Property | Classification | Notes |
|---------|-----------------|----------------|-------|
| World | use_nodes | SUPPORTED | node tree handled separately |

