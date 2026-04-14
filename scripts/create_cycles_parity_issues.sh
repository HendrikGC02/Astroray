#!/usr/bin/env bash
# =============================================================================
# create_cycles_parity_issues.sh
#
# Creates GitHub Issues for FULL Cycles feature parity in Astroray.
# Organized by Blender UI panel, covering every setting visible when
# Cycles is the active render engine.
#
# KEY PRINCIPLE: Wherever Blender already handles something (color management,
# output formats, resolution), we DON'T reimplement it — we just make sure
# our engine cooperates properly with Blender's pipeline.
#
# Usage:
#   gh auth login
#   chmod +x scripts/create_cycles_parity_issues.sh
#   ./scripts/create_cycles_parity_issues.sh
#
# Then assign issues to Copilot:
#   gh issue edit <NUMBER> --add-assignee @copilot
# =============================================================================
set -euo pipefail

create_labels() {
    echo "Creating labels..."
    gh label create "cycles-parity" --description "Cycles feature parity" --color "0E8A16" 2>/dev/null || true
    gh label create "render-settings" --description "Render properties panel" --color "1D76DB" 2>/dev/null || true
    gh label create "material" --description "Material/BSDF/shader nodes" --color "D4C5F9" 2>/dev/null || true
    gh label create "lighting" --description "Light sources" --color "FBCA04" 2>/dev/null || true
    gh label create "textures" --description "Texture/image nodes" --color "F9D0C4" 2>/dev/null || true
    gh label create "geometry" --description "Mesh/geometry/hair" --color "C5DEF5" 2>/dev/null || true
    gh label create "integrator" --description "Path tracing core" --color "BFD4F2" 2>/dev/null || true
    gh label create "blender-export" --description "Blender scene export/conversion" --color "FEF2C0" 2>/dev/null || true
    gh label create "passes" --description "Render passes and AOVs" --color "E6E6E6" 2>/dev/null || true
    gh label create "world" --description "World/environment settings" --color "006B75" 2>/dev/null || true
    gh label create "volume" --description "Volume rendering" --color "B60205" 2>/dev/null || true
    gh label create "film" --description "Film/output settings" --color "5319E7" 2>/dev/null || true
    gh label create "performance" --description "Performance/optimization" --color "FF6600" 2>/dev/null || true
    gh label create "blender-native" --description "Leverage Blender-native feature" --color "C2E0C6" 2>/dev/null || true
    echo "Labels created."
}

ci() {
    local title="$1"
    local labels="$2"
    local body="$3"
    echo "  Creating: $title"
    gh issue create --title "$title" --label "$labels" --body "$body"
    sleep 1
}

create_labels

echo ""
echo "=== SECTION 1: RENDER PROPERTIES — Sampling ==="
echo ""

ci "feat: Per-bounce-type max bounces (diffuse, glossy, transmission, volume, transparent)" \
   "cycles-parity,render-settings,integrator" \
'## Summary
Cycles allows separate max bounce limits per light path type. Astroray currently has only a single `max_depth` for all bounces.

## Cycles UI location
Render Properties → Light Paths → Max Bounces (Total, Diffuse, Glossy, Transmission, Volume, Transparent)

## Cycles reference
- `intern/cycles/kernel/integrator/path_state.h` — bounce counting per type
- `intern/cycles/kernel/integrator/shade_surface.h` — bounce limit checks
- `intern/cycles/scene/integrator.cpp` — `max_diffuse_bounce`, `max_glossy_bounce`, etc.

## What to implement
1. Add per-type bounce counters to the path state in `pathTrace()`: `diffuse_bounces`, `glossy_bounces`, `transmission_bounces`, `volume_bounces`, `transparent_bounces`
2. After each material interaction, increment the appropriate counter based on `isDelta` and material type
3. Terminate the path if any per-type counter exceeds its limit OR the total exceeds `max_depth`
4. Add these settings to `CustomRaytracerRenderSettings` in the Blender addon
5. Add a "Light Paths" panel in the Render Properties UI

## Blender export
Read from `scene.cycles.max_bounces`, `scene.cycles.diffuse_bounces`, etc. — but since we use our own settings PropertyGroup, mirror these as custom properties.

## Acceptance criteria
- [ ] Setting glossy_bounces=0 eliminates all specular reflections
- [ ] Setting transmission_bounces=0 makes glass opaque
- [ ] Setting transparent_bounces=8 allows seeing through 8 layers of alpha-masked geometry
- [ ] Total bounce limit still works as an overall cap'

ci "feat: Separate direct and indirect clamping" \
   "cycles-parity,render-settings,integrator" \
'## Summary
Cycles clamps direct and indirect lighting contributions separately. Astroray currently has only the per-sample firefly clamp at luminance 20.

## Cycles UI location
Render Properties → Light Paths → Clamping → Direct Light, Indirect Light

## Cycles reference
- `intern/cycles/kernel/integrator/shade_surface.h` — `INTEGRATOR_STATE(state, path, throughput)` clamped separately for direct/indirect
- `intern/cycles/scene/integrator.cpp` — `sample_clamp_direct`, `sample_clamp_indirect`

## What to implement
1. Add `clamp_direct` and `clamp_indirect` float settings (0 = disabled)
2. In `sampleDirect()`: if `clamp_direct > 0`, clamp the NEE contribution luminance to that value
3. In the BSDF sampling path (indirect): clamp the accumulated throughput × radiance
4. Replace the current hardcoded `luminance > 20` clamp with these configurable values
5. Add to render settings panel

## Acceptance criteria
- [ ] clamp_direct=0, clamp_indirect=0 matches current behavior (only the per-sample clamp)
- [ ] clamp_direct=1.0 significantly reduces fireflies from bright specular highlights
- [ ] Indirect clamping reduces noise from caustics without eliminating them entirely'

ci "feat: Caustics control (filter glossy, reflective/refractive caustics toggle)" \
   "cycles-parity,render-settings,integrator" \
'## Summary
Cycles can disable reflective and/or refractive caustics to reduce noise, and has a "filter glossy" parameter that clamps roughness of secondary bounces.

## Cycles UI location
Render Properties → Light Paths → Caustics

## Cycles reference
- `intern/cycles/kernel/integrator/shade_surface.h` — caustic checks, blur_roughness application
- `intern/cycles/scene/integrator.cpp` — `caustics_reflective`, `caustics_refractive`, `filter_glossy`

## What to implement
1. Add `filter_glossy` float setting: after bounce 0, increase roughness of glossy interactions by this amount
   - Effectively: `roughness = max(roughness, filter_glossy * bounce)` or `roughness += filter_glossy`
2. Add `use_reflective_caustics` and `use_refractive_caustics` booleans
   - When disabled: if a diffuse bounce is followed by a specular bounce, terminate the path
3. Add to the Light Paths panel in render settings

## Acceptance criteria
- [ ] filter_glossy=1.0 makes mirror reflections slightly blurry after first bounce (reduces noise)
- [ ] Disabling reflective caustics removes caustic patterns from mirrors on diffuse surfaces
- [ ] Disabling refractive caustics removes glass caustic patterns'

ci "feat: Seed control and animated seed for noise variation" \
   "cycles-parity,render-settings,integrator" \
'## Summary
Cycles allows setting the random seed and has an "animated seed" option that varies the noise pattern per frame (useful for denoising animation).

## Cycles UI location
Render Properties → Sampling → Advanced → Seed

## What to implement
1. Add `seed` integer setting (default 0)
2. Use it to initialize the per-pixel RNG: `std::mt19937 gen(seed + pixelIndex)`
3. Add `use_animated_seed` boolean: when true, add the frame number to the seed
4. Expose via Python API: `renderer.set_seed(int)` and in render settings

## Acceptance criteria
- [ ] Same seed produces identical renders (deterministic)
- [ ] Different seeds produce different noise patterns
- [ ] Animated seed changes pattern per frame in animation'

echo ""
echo "=== SECTION 2: FILM SETTINGS ==="
echo ""

ci "feat: Film exposure setting" \
   "cycles-parity,film,blender-native" \
'## Summary
Cycles has a Film Exposure setting that scales the final pixel values. This is simple but must be read from Blender and applied.

## Cycles UI location
Render Properties → Film → Exposure

## What to implement
1. Read `scene.cycles.film_exposure` (float, default 1.0) during scene conversion
2. Apply as a multiplier to final pixel values BEFORE gamma correction: `color *= exposure`
3. Note: Blender'\''s Color Management also has an Exposure slider — that one is applied by Blender'\''s OCIO pipeline automatically. The Film exposure is the renderer'\''s own pre-OCIO scale.

## Acceptance criteria
- [ ] exposure=1.0 matches current output
- [ ] exposure=2.0 produces a brighter image (approximately 1 stop)
- [ ] exposure=0.5 produces a darker image'

ci "feat: Transparent film (transparent background for compositing)" \
   "cycles-parity,film,integrator" \
'## Summary
Cycles can render with a transparent background so the result can be composited over another image. The alpha channel contains the scene coverage.

## Cycles UI location
Render Properties → Film → Transparent

## Cycles reference
- `intern/cycles/kernel/integrator/path_state.h` — `PATH_RAY_TRANSPARENT_BACKGROUND`
- `intern/cycles/kernel/film/passes.h` — alpha computation

## What to implement
1. Add `use_transparent_film` boolean setting
2. When enabled: rays that miss all geometry (hit the environment/sky) set alpha=0 instead of writing the background color
3. The RGB channels still contain the environment contribution for "Transparent Glass" mode
4. Add `transparent_glass` boolean: when true, glass objects are also treated as transparent for alpha
5. Update `write_pixels()` in the Blender addon to pass alpha correctly to the render result

## Acceptance criteria
- [ ] With transparent film: a sphere on a transparent background has alpha=1 on the sphere, alpha=0 elsewhere
- [ ] The resulting image composites correctly over a different background in Blender'\''s compositor
- [ ] Without transparent film: current behavior (opaque background)'

ci "feat: Pixel filter type and width" \
   "cycles-parity,film" \
'## Summary
Cycles supports different pixel reconstruction filters (Box, Gaussian, Blackman-Harris) with configurable width.

## Cycles UI location
Render Properties → Film → Pixel Filter

## Cycles reference
- `intern/cycles/kernel/film/passes.h` — filter weight computation
- `intern/cycles/scene/film.cpp` — `filter_type`, `filter_width`

## What to implement
1. Currently each pixel samples a single jittered point within the pixel. A reconstruction filter weights contributions from neighboring pixels.
2. For Box filter (width 1.0): current behavior (uniform random within pixel)
3. For Gaussian filter: weight samples by `exp(-2 * d²)` where d is distance from pixel center
4. For Blackman-Harris: standard windowed sinc
5. Filter width controls the support radius (default 1.5 pixels for Gaussian)
6. Simplest implementation: just adjust the jitter distribution to match the filter shape (importance sampling the filter)

## Acceptance criteria
- [ ] Box 1.0px matches current output
- [ ] Gaussian 1.5px produces slightly softer edges than Box
- [ ] Filter width=0.01 produces very sharp (aliased) edges'

echo ""
echo "=== SECTION 3: COLOR MANAGEMENT (Blender-native — minimal engine work) ==="
echo ""

ci "feat: Proper linear output for Blender color management pipeline" \
   "cycles-parity,film,blender-native" \
'## Summary
Blender'\''s color management (OCIO) handles view transforms (AgX, Filmic, Standard), exposure, gamma, and look. The render engine'\''s job is simply to output **linear scene-referred float RGBA** and let Blender do the rest.

Currently Astroray applies gamma correction (pow 1/2.2) inside the renderer, which double-transforms when Blender'\''s OCIO pipeline also applies a view transform.

## What Blender handles natively
- View Transform (AgX, Filmic, Standard, Raw) — configured in Render Properties → Color Management
- Display Device, Look, Exposure, Gamma sliders
- All of this is applied by Blender'\''s compositor/display pipeline AFTER the render engine returns pixels

## What to implement
1. **Remove the internal gamma correction** from `Renderer::render()`: output linear float RGB, NOT gamma-corrected
2. Keep the gamma correction in the standalone binary (`apps/main.cpp`) since it writes directly to PNG/PPM
3. In `write_pixels()`: the float data passed to Blender'\''s render result should be linear (Blender applies its own view transform)
4. For the Python API (non-Blender use): add an optional `apply_gamma` parameter to `render()`, defaulting to True for standalone, False for Blender

## CRITICAL
This is a breaking change to the pixel output. All existing tests check gamma-corrected values. Tests must be updated to expect either linear values or must apply gamma themselves.

## Acceptance criteria
- [ ] Renders in Blender look correct with AgX view transform (not washed out or too dark)
- [ ] Switching between AgX, Filmic, and Standard in Blender produces different looks from the same render
- [ ] Standalone binary still produces correct PNG output
- [ ] Raw view transform in Blender shows the linear render data directly'

echo ""
echo "=== SECTION 4: WORLD SETTINGS ==="
echo ""

ci "feat: World volume support (fog, atmospheric scattering)" \
   "cycles-parity,world,volume" \
'## Summary
Cycles supports a world volume shader — connecting a Volume Scatter or Principled Volume to the World Output Volume socket creates global fog/atmosphere.

## Cycles UI location
World Properties → Volume

## Cycles reference
- `intern/cycles/kernel/integrator/volume_stack.h` — world volume tracking
- `intern/cycles/blender/blender_shader.cpp` — world volume export

## What to implement
1. In `setup_world()`: check the World Output node for a Volume socket connection
2. If connected to a Principled Volume or Volume Scatter node: read density, color, anisotropy
3. Create a global volume that all rays traverse: for every ray segment in free space, apply Beer-Lambert absorption with the world volume density
4. This creates global fog/haze effects

## Acceptance criteria
- [ ] A scene with world volume density=0.01 shows visible atmospheric haze
- [ ] Objects far from camera are more fogged than nearby objects
- [ ] No world volume = current behavior (clear atmosphere)'

ci "feat: World settings — MIS map resolution, max bounces, homogeneous sampling" \
   "cycles-parity,world,render-settings" \
'## Summary
Cycles has several world-specific settings that control how the environment map is sampled.

## Cycles UI location
World Properties → Settings → Surface (Map Resolution, Max Bounces, Sampling Method)

## What to implement
1. **Map Resolution**: downsample the environment CDF to this resolution for faster importance sampling (default 1024). Currently Astroray uses the full HDRI resolution.
2. **Max Bounces**: limit how many indirect bounces can see the world background. Setting to 1 means only camera rays and first-bounce rays see the HDRI; deeper bounces see black. Reduces indoor noise.
3. **Sampling Method**: "Automatic" vs "Manual" — for Astroray, just ensure the MIS-weighted environment sampling is properly integrated (should already work from Phase 1).

## Acceptance criteria
- [ ] map_resolution=256 produces similar quality to full-res but faster CDF construction
- [ ] max_bounces=0 makes only camera rays see the environment (useful for interior scenes)
- [ ] max_bounces=1024 (default) has no practical limit'

echo ""
echo "=== SECTION 5: MATERIAL/SHADER NODES ==="
echo ""

ci "feat: Multi-scatter GGX for energy-conserving specular" \
   "cycles-parity,material" \
'## Summary
Replace single-scatter GGX with multi-scatter GGX (Kulla-Conty) for energy conservation at high roughness.

## Cycles reference
- `intern/cycles/kernel/closure/bsdf_microfacet.h` — `Fms`, `Eavg` energy compensation
- Paper: Kulla & Conty 2017, "Revisiting Physically Based Shading at Imageworks"

## What to implement
1. Precompute 2D LUT of directional albedo E(μ, roughness) at startup (32×32)
2. Add multi-scatter compensation: `F_ms = (1-E(wo)) * (1-E(wi)) / (π * (1-E_avg))`
3. Apply to Metal and DisneyBRDF specular lobes

## Acceptance criteria
- [ ] White metal at roughness=1.0 is NOT dark (current energy loss bug)
- [ ] Furnace test (white sphere in uniform emitter) returns >0.85 for all roughness values'

ci "feat: All standalone BSDF shader nodes (Diffuse, Glossy, Glass, Translucent, Transparent, Refraction, Sheen, Metallic)" \
   "cycles-parity,material" \
'## Summary
Cycles has individual BSDF nodes beyond the Principled BSDF. The material export currently handles some but not all.

## Cycles reference
- `intern/cycles/kernel/closure/bsdf_diffuse.h` — Diffuse BSDF
- `intern/cycles/kernel/closure/bsdf_microfacet.h` — Glossy, Glass, Refraction
- `intern/cycles/kernel/closure/bsdf_transparent.h` — Transparent
- `intern/cycles/kernel/closure/bsdf_sheen.h` — Sheen (Microfiber model)
- `intern/cycles/kernel/closure/bsdf_ashikhmin_shirley.h` — legacy anisotropic

## What to implement
1. In `convert_shader_node()`, handle each node type:
   - `BSDF_DIFFUSE` → Lambertian with roughness (Oren-Nayar)
   - `BSDF_GLOSSY`/`BSDF_ANISOTROPIC` → Metal with roughness
   - `BSDF_GLASS` → Dielectric with roughness and IOR
   - `BSDF_TRANSLUCENT` → Lambertian that transmits (flip normal)
   - `BSDF_TRANSPARENT` → Perfect transparency (weight controls blend)
   - `BSDF_REFRACTION` → Dielectric without reflection component
   - `BSDF_SHEEN` → Sheen BSDF (Microfiber model from Zeltner 2022)
   - `BSDF_METALLIC` → Metal with F82 tint
2. For nodes not yet supported in C++: fall back to closest equivalent with a warning

## Acceptance criteria
- [ ] Each BSDF node type produces a visually distinct and physically plausible result
- [ ] Glossy BSDF matches Principled BSDF with metallic=1 at same roughness
- [ ] Glass BSDF matches Principled BSDF with transmission=1 at same IOR'

ci "feat: Principled Volume and Volume Absorption/Scatter shader nodes" \
   "cycles-parity,material,volume" \
'## Summary
Cycles has three volume shader nodes: Principled Volume, Volume Absorption, and Volume Scatter. These create volumetric effects inside meshes.

## Cycles reference
- `intern/cycles/kernel/closure/volume.h` — `CLOSURE_VOLUME_HENYEY_GREENSTEIN_ID`, absorption, emission coefficients
- `intern/cycles/kernel/svm/closure_principled.h` — principled volume setup
- `intern/cycles/blender/blender_shader.cpp` — volume node export

## What to implement
1. **Volume Absorption**: Beer-Lambert attenuation `exp(-σ_a * distance)` with color-dependent σ_a
2. **Volume Scatter**: Henyey-Greenstein phase function with anisotropy g, σ_s coefficient
3. **Principled Volume**: combined absorption + scatter + blackbody emission
   - Color → absorption color, Density → σ_t multiplier, Anisotropy → HG g parameter
   - Temperature → blackbody emission (optional), Emission Strength → emission σ_e
4. In `convert_shader_node()`: detect volume nodes connected to Volume output
5. In `convert_objects()`: when a mesh has a volume material, create a ConstantMedium

## Acceptance criteria
- [ ] A cube with Volume Absorption (density=1, color=blue) tints light passing through blue
- [ ] A cube with Volume Scatter shows visible scattering (light bends inside)
- [ ] A sphere with Principled Volume (emission_strength=1) glows'

ci "feat: Mix Shader and Add Shader node support" \
   "cycles-parity,material,blender-export" \
'## Summary
Cycles materials frequently combine shaders with Mix Shader and Add Shader. Currently Astroray picks only the first shader.

## Cycles reference
- `intern/cycles/kernel/closure/alloc.h` — closure weight blending
- `intern/cycles/blender/blender_shader.cpp` — shader graph flattening

## What to implement
1. **Mix Shader(factor, A, B)**: blend material parameters `param = (1-fac)*A + fac*B`
   - For Principled + Principled: blend all parameters
   - For Principled + Transparent: set alpha = 1 - factor
   - For Principled + Emission: create material with emission weight = factor
2. **Add Shader(A, B)**: sum the contributions (for emission + surface combos)
3. For complex chains: recursive evaluation until reaching leaf BSDF nodes
4. For unsupported combos: fall back to the dominant shader (higher factor)

## Acceptance criteria
- [ ] Mix(0.5, Red Diffuse, Blue Diffuse) → purple
- [ ] Mix(0.3, Glass, Principled) → Disney with transmission ≈ 0.3
- [ ] Add(Principled, Emission) → material with both surface and emission'

ci "feat: Texture coordinate node (Generated, UV, Object, Camera, Window, Reflection, Normal)" \
   "cycles-parity,material,textures" \
'## Summary
Cycles textures receive coordinates from the Texture Coordinate node. Astroray only supports UV coordinates.

## Cycles reference
- `intern/cycles/kernel/svm/tex_coord.h` — all coordinate modes
- `source/blender/nodes/shader/nodes/node_shader_tex_coord.cc`

## What to implement
1. **Generated**: based on the object'\''s bounding box, mapping position to [0,1]³
2. **UV**: current behavior (from mesh UV map)
3. **Object**: hit point in object-local space
4. **Camera**: hit point in camera space
5. **Normal**: shading normal as texture coordinates
6. **Reflection**: reflection vector as texture coordinates (for environment lookups)
7. **Window**: screen-space coordinates (pixel position / resolution)
8. Store the coordinate mode per-texture and compute the appropriate coordinates in `hit()`

## Acceptance criteria
- [ ] Generated coordinates produce a gradient across an object'\''s bounding box
- [ ] Object coordinates stay fixed relative to the object when it moves
- [ ] UV coordinates work as before (unchanged)'

ci "feat: All procedural texture nodes (Noise, Voronoi, Wave, Musgrave, Magic, Checker, Brick, Gradient)" \
   "cycles-parity,textures" \
'## Summary
Cycles has a rich set of procedural textures. Astroray has basic noise and checker but is missing most.

## Cycles reference
- `intern/cycles/kernel/svm/noise.h`, `voronoi.h`, `wave.h`, `musgrave.h`, `magic.h`, `checker.h`, `brick.h`, `gradient.h`

## What to implement (one texture type at a time is fine — this can be split into sub-issues)
1. **Noise**: Perlin noise with scale, detail (octaves), roughness, lacunarity, distortion
2. **Voronoi**: F1, F2, smooth F1, distance metrics (Euclidean, Manhattan, Chebychev, Minkowski)
3. **Wave**: bands/rings, sine/saw/triangle profiles, with distortion
4. **Musgrave**: fBm, multifractal, hetero terrain, hybrid, ridged multifractal
5. **Magic**: swirly psychedelic pattern
6. **Checker**: already exists (verify parameters match Cycles)
7. **Brick**: brick pattern with mortar, offset, squash
8. **Gradient**: linear, quadratic, easing, diagonal, spherical, quadratic sphere, radial

## Acceptance criteria
- [ ] Each texture produces a visually recognizable pattern matching the Cycles reference
- [ ] Noise with 4 detail octaves shows multi-scale structure'

ci "feat: Normal Map and Bump node support" \
   "cycles-parity,textures,material" \
'## Summary
Normal maps and bump maps are essential for surface detail. Neither is currently supported.

## Cycles reference
- `intern/cycles/kernel/svm/normal_map.h` — `svm_node_normal_map()`
- `intern/cycles/kernel/svm/bump.h` — `svm_node_bump()`

## What to implement
1. **Normal Map**: read RGB image, convert to tangent-space normal `n_ts = 2*rgb - 1`, transform by TBN matrix
2. **Bump Map**: evaluate height texture at hit point + two offsets, compute gradient via finite differences, perturb normal
3. In material export: detect Normal Map / Bump nodes connected to Principled BSDF Normal input
4. Load the normal/bump texture image data into the renderer

## Acceptance criteria
- [ ] A flat plane with a brick normal map shows visible surface bumps
- [ ] Normal-mapped specular highlights shift correctly with the perturbed normal
- [ ] Bump strength=0 matches no-bump output'

ci "feat: Color processing nodes (MixRGB, RGB Curves, Hue/Saturation, Invert, Gamma, Bright/Contrast, Color Ramp)" \
   "cycles-parity,textures,blender-export" \
'## Summary
Cycles materials often use color processing nodes between textures and BSDF inputs.

## Cycles reference
- `intern/cycles/kernel/svm/color_util.h` — all color operations
- `intern/cycles/kernel/svm/math.h` — math operations

## What to implement
Two approaches, depending on complexity:
**Approach A (Export-time evaluation)**: When walking the node tree, evaluate constant chains at export time. E.g., if a Color Ramp has a constant input, evaluate it and use the result as the material parameter.
**Approach B (Per-pixel evaluation)**: For texture-driven chains, store the node chain as a mini-program and evaluate per pixel.

Start with Approach A (much simpler). Common patterns to handle:
1. **Color Ramp** with a constant or procedural input → evaluate and use result color
2. **Math node** (multiply, add, power) with constants → apply to the parameter
3. **Map Range** → linear remap of a float value
4. **MixRGB** (Multiply/Mix/Add modes) between two textures → blend the results

## Acceptance criteria
- [ ] Noise Texture → Color Ramp → Base Color exports with the ramp'\''s colors
- [ ] Image Texture → MixRGB(Multiply, solid_color) → Base Color exports tinted'

ci "feat: Converter nodes (Math, Map Range, Clamp, Wavelength, Blackbody, RGB to BW)" \
   "cycles-parity,textures,blender-export" \
'## Summary
Converter nodes transform values between types. Support the most common ones in the export pipeline.

## Cycles reference
- `intern/cycles/kernel/svm/math.h` — all math operations
- `intern/cycles/kernel/svm/wavelength.h`, `blackbody.h`

## What to implement
1. **Math**: add, subtract, multiply, divide, power, sqrt, abs, min, max, floor, ceil, fract, modulo, sin, cos, tan, etc.
2. **Map Range**: linear/stepped/smoothstep remap from [a,b] to [c,d]
3. **Clamp**: min/max clamp
4. **RGB to BW**: luminance conversion
5. **Wavelength**: convert wavelength (nm) to RGB (using CIE spectral data — already have this!)
6. **Blackbody**: convert temperature (K) to RGB (already have Planck function!)

For export-time evaluation: walk the node chain, apply operations to constant values.

## Acceptance criteria
- [ ] Math(Multiply) between a float and a texture scales the texture correctly
- [ ] Blackbody(5778) produces a warm white color matching the sun'

echo ""
echo "=== SECTION 6: LIGHTING ==="
echo ""

ci "feat: Area lights with shapes (Rectangle, Disk, Ellipse) and spread angle" \
   "cycles-parity,lighting" \
'## Summary
Cycles area lights have configurable shapes and a spread parameter. Astroray approximates all lights as spheres.

## Cycles reference
- `intern/cycles/kernel/light/area.h` — `area_light_sample()`, `area_light_pdf()`
- `intern/cycles/scene/light.cpp` — shape enums, spread

## What to implement
1. **Rectangle light**: two triangles, uniform sampling over the quad surface for NEE
2. **Disk light**: rejection sampling or direct disk sampling
3. **Spread parameter**: limit the emission cone angle (1.0 = hemisphere, 0 = laser-like)
4. Each shape needs `sample()`, `pdfValue()`, and `emittedRadiance()` methods
5. Update `convert_lights()` to read `light.shape` and `light.spread`

## Acceptance criteria
- [ ] Rectangle light creates sharp rectangular specular reflections
- [ ] Disk light creates round specular reflections
- [ ] spread=0.1 creates a focused beam effect'

ci "feat: Spot lights with cone angle, blend, and falloff" \
   "cycles-parity,lighting" \
'## Summary
Spot lights with configurable cone, soft edges, and radius.

## Cycles reference
- `intern/cycles/kernel/light/spot.h` — falloff computation
- `intern/cycles/scene/light.cpp` — `spot_angle`, `spot_smooth`

## What to implement
1. Point light with directional falloff: `smoothstep(outer_angle, inner_angle, angle_from_axis)`
2. `spot_angle` = total cone angle, `spot_smooth` = blend ratio for soft edge
3. Optional radius for soft shadow (sphere at the light position)
4. Export: read `light.spot_size`, `light.spot_blend`

## Acceptance criteria
- [ ] Sharp cone on a floor plane
- [ ] Soft edges with blend > 0'

ci "feat: Sun light with angular diameter for soft shadows" \
   "cycles-parity,lighting" \
'## Summary
Directional light with configurable angular size (soft shadows).

## Cycles reference
- `intern/cycles/kernel/light/distant.h` — cone sampling within angular diameter

## What to implement
1. Infinite-distance directional light (parallel rays)
2. Angular diameter controls shadow softness: sample within a cone
3. Replace the current giant-sphere hack for sun lights
4. Export: read `light.angle`

## Acceptance criteria
- [ ] angle=0 → perfectly sharp parallel shadows
- [ ] angle=0.05 → soft shadows matching sun-like lighting'

ci "feat: IES light profiles" \
   "cycles-parity,lighting" \
'## Summary
Cycles supports IES photometric light profiles for realistic architectural lighting.

## Cycles reference
- `intern/cycles/kernel/light/spot.h` — IES texture lookup
- `intern/cycles/scene/light.cpp` — IES file loading

## What to implement
1. Parse IES files (standard text format with candela distribution tables)
2. Create a 2D lookup table of intensity vs (vertical angle, horizontal angle)
3. Multiply light intensity by the IES profile value at the emission direction
4. Apply to point/spot lights that have an IES file assigned

## Acceptance criteria
- [ ] An IES-profiled light creates realistic non-uniform illumination patterns on walls
- [ ] Without IES profile: standard uniform emission (current behavior)'

echo ""
echo "=== SECTION 7: GEOMETRY & OBJECT FEATURES ==="
echo ""

ci "feat: Per-face material assignment (multi-material meshes)" \
   "cycles-parity,geometry,blender-export" \
'## Summary
Meshes can have different materials on different faces. Currently only slot 0 is used.

## What to implement
1. In `convert_objects()`: build a slot_to_id map from `obj.material_slots`
2. For each triangle: use `tri.material_index` to look up the correct material
3. This is pure addon-side work — the C++ renderer already supports different materials per triangle

## Acceptance criteria
- [ ] A cube with red top, green sides, blue bottom renders all three colors
- [ ] A mesh imported from an external file with multiple materials renders correctly'

ci "feat: Per-corner normals from MeshLoopTriangle.split_normals" \
   "cycles-parity,geometry,blender-export" \
'## Summary
Blender 4.1+ provides per-corner normals via `split_normals` that respect sharp edges, custom normals, and smooth shading.

## What to implement
1. Read `tri.split_normals` (3x3 array) for each triangle in `convert_objects()`
2. Transform normals by the inverse-transpose of the model matrix'\''s 3x3 component
3. Pass normals to `add_triangle()` and interpolate via barycentric coordinates in `hit()`
4. This replaces the current face-normal-only approach

## Acceptance criteria
- [ ] A smooth-shaded UV sphere shows no faceting
- [ ] A cube with some sharp edges renders those edges crisply while smooth faces are smooth'

ci "feat: Motion blur (camera and object transform)" \
   "cycles-parity,geometry,integrator" \
'## Summary
Stochastic motion blur via temporal sampling of camera and object transforms.

## Cycles reference
- `intern/cycles/scene/object.cpp` — motion transforms
- `intern/cycles/kernel/geom/motion_triangle.h` — interpolated vertex positions

## What to implement
1. Per ray: sample a random time t in [shutter_open, shutter_close]
2. Camera: interpolate between current and next frame camera transform at time t
3. Objects: store two transforms (current, next), interpolate per ray
4. Read shutter settings from `scene.render.motion_blur_shutter`

## Acceptance criteria
- [ ] A moving sphere shows a motion streak
- [ ] Camera rotation blur smears the scene
- [ ] Motion blur disabled = no blur'

ci "feat: Hair/curves rendering" \
   "cycles-parity,geometry" \
'## Summary
Cycles renders hair/curves as ribbons or thick curves with a dedicated Hair BSDF.

## Cycles reference
- `intern/cycles/kernel/geom/curve.h` — curve intersection
- `intern/cycles/kernel/closure/bsdf_hair.h` — Hair BSDF, Hair Principled BSDF
- `intern/cycles/blender/blender_curves.cpp` — Blender curve export

## What to implement
1. Export Blender curve/hair data: read control points, radius
2. Implement ray-curve intersection (e.g., ribbon approximation — segments of small quads)
3. Implement basic Hair BSDF (Chiang 2015 model as used in Principled Hair BSDF)
4. For initial implementation: convert curves to triangle ribbons at export time (simpler than native curve intersection)

## Acceptance criteria
- [ ] A particle hair system renders visible strands
- [ ] Hair color and roughness controls work
- [ ] Performance is acceptable (may need LOD for dense hair)'

echo ""
echo "=== SECTION 8: RENDER PASSES & VIEW LAYERS ==="
echo ""

ci "feat: Full render pass support (Diffuse/Glossy/Transmission Direct+Indirect+Color, Emission, Environment, AO, Shadow)" \
   "cycles-parity,passes" \
'## Summary
Cycles provides separate render passes for compositing. Astroray only has beauty, albedo, and normal.

## Cycles reference
- `intern/cycles/kernel/film/light_passes.h` — pass accumulation

## What to implement
1. During path tracing, categorize each radiance contribution:
   - Diffuse Direct, Diffuse Indirect, Diffuse Color
   - Glossy Direct, Glossy Indirect, Glossy Color
   - Transmission Direct, Transmission Indirect, Transmission Color
   - Volume Direct, Volume Indirect
   - Emission, Environment, Shadow
2. Accumulate each in a separate buffer
3. Register all passes with Blender'\''s render result via `RenderResult.layers[0].passes`
4. Users enable/disable passes in View Layer Properties → Passes

## Acceptance criteria
- [ ] Diffuse Direct shows only direct illumination on diffuse surfaces
- [ ] Emission pass shows only emissive objects
- [ ] All enabled passes appear in Blender'\''s compositor
- [ ] Beauty ≈ sum of all component passes'

ci "feat: Data passes (Z/Depth, Mist, UV, Normal, Vector/Motion, Object/Material Index)" \
   "cycles-parity,passes" \
'## Summary
Cycles provides data passes for compositing: depth, mist, UV, surface normal, motion vectors, and object/material indices.

## Blender handles
Most of these are straightforward to compute from the primary hit record.

## What to implement
1. **Depth (Z)**: distance from camera to first hit point (already available as rec.t)
2. **Mist**: depth remapped to [0,1] based on scene.world.mist_settings (start, depth, falloff)
3. **Normal**: world-space shading normal (already in normal buffer — just register as a pass)
4. **UV**: texture coordinates at primary hit
5. **Object Index**: `obj.pass_index` from Blender, stored per-primitive
6. **Material Index**: material slot index, stored per-primitive
7. **Vector (Motion)**: requires two-frame rendering — defer to motion blur implementation

## Acceptance criteria
- [ ] Depth pass shows near=white, far=dark (or configurable mapping)
- [ ] Mist pass creates a smooth fog gradient
- [ ] Object Index pass assigns unique values per object'

ci "feat: Cryptomatte passes (Object, Material, Asset)" \
   "cycles-parity,passes" \
'## Summary
Cryptomatte provides automatic ID mattes for compositing.

## Cycles reference
- `intern/cycles/kernel/film/cryptomatte.h` — hash computation, coverage

## What to implement
1. Assign a 32-bit hash to each object and material name during scene conversion
2. At each primary hit, store (hash, coverage) pairs
3. Output as float32 RGBA passes where RGB encodes the hash and A encodes coverage
4. Register with Blender so it appears as a Cryptomatte pass in the compositor

## Acceptance criteria
- [ ] Each object gets a unique ID in the Cryptomatte viewer
- [ ] The matte correctly follows object boundaries with anti-aliased edges'

ci "feat: OIDN denoiser integration" \
   "cycles-parity,passes,performance" \
'## Summary
Integrate Intel Open Image Denoise (OIDN) as a post-render denoising pass, using the existing albedo and normal AOV buffers.

## Cycles reference
- `intern/cycles/integrator/denoiser_oidn.cpp` — OIDN setup

## What to implement
1. Add OIDN as an optional CMake dependency (FetchContent or find_package)
2. After rendering, if denoising enabled: run OIDN with beauty + albedo + normal inputs
3. Replace the beauty buffer with the denoised output
4. Add `use_denoiser` and `denoiser_type` settings (OIDN / None)
5. Build must succeed without OIDN (graceful fallback)

## Acceptance criteria
- [ ] 16spp + OIDN ≈ 256spp quality
- [ ] Denoiser off = identical to current
- [ ] Build works with and without OIDN installed'

echo ""
echo "=== SECTION 9: VIEW LAYER & SCENE SETTINGS ==="
echo ""

ci "feat: View layer support (render only objects in the active view layer)" \
   "cycles-parity,blender-export" \
'## Summary
Blender scenes can have multiple view layers, each controlling which collections are visible for rendering. The render engine should respect these.

## What Blender handles
View layer management, collection visibility toggles, holdout/indirect-only flags.

## What to implement
1. In `convert_objects()`: use `depsgraph.object_instances` (already done) which respects view layer visibility
2. Verify that `obj.visible_get()` correctly filters by the active view layer
3. Support the "Use for Rendering" toggle on view layers — skip view layers where this is False
4. When multiple view layers are enabled: render each one separately and pass results to Blender

## Acceptance criteria
- [ ] Objects in disabled collections do not appear in the render
- [ ] Disabling "Use for Rendering" on a view layer skips it'

ci "feat: Holdout and indirect-only objects" \
   "cycles-parity,blender-export,integrator" \
'## Summary
Cycles supports holdout objects (cut a hole in the render for compositing) and indirect-only objects (visible in reflections/GI but not directly).

## Cycles reference
- `intern/cycles/kernel/integrator/shade_surface.h` — holdout handling
- `intern/cycles/scene/object.cpp` — `is_shadow_catcher`, `use_holdout`

## What to implement
1. **Holdout**: when a camera ray hits a holdout object, set alpha=0 and color=0 (creates a hole)
2. **Indirect only**: object is invisible to camera rays but visible to all other rays (reflections, GI, shadows)
3. Read `obj.is_holdout` and collection `holdout` property during export
4. Store the flag per-primitive and check in `pathTrace()`

## Acceptance criteria
- [ ] A holdout sphere creates a black hole with alpha=0 in the render
- [ ] An indirect-only object appears in mirror reflections but not in the direct camera view'

echo ""
echo "=== SECTION 10: OUTPUT & PERFORMANCE (mostly Blender-native) ==="
echo ""

ci "feat: Output format cooperation — ensure linear float RGBA output is compatible with all Blender output formats" \
   "cycles-parity,film,blender-native" \
'## Summary
Blender handles writing output files (PNG, EXR, JPEG, TIFF, etc.). The render engine just needs to provide correct linear float RGBA data in the render result. Verify this works for all format options.

## What Blender handles
- File format selection (Output Properties → Output → File Format)
- Color depth (8-bit, 16-bit, 32-bit)
- Compression settings
- Metadata stamping
- Frame naming

## What to verify/fix
1. Ensure `write_pixels()` provides float32 RGBA in [0, ∞) linear space (not clamped to [0,1] — EXR needs unclamped values)
2. Verify multi-layer EXR works when render passes are enabled (each pass is a separate layer)
3. Verify alpha channel is correct (1.0 for opaque, <1.0 for transparent film)
4. Test saving as: PNG 8-bit, PNG 16-bit, OpenEXR 32-bit, OpenEXR multilayer

## Acceptance criteria
- [ ] PNG output looks correct (Blender applies view transform + quantization)
- [ ] EXR output preserves full HDR range (values > 1.0 survive)
- [ ] Multi-layer EXR contains all enabled render passes'

ci "feat: Tiled rendering for memory efficiency" \
   "cycles-parity,performance" \
'## Summary
Cycles renders in tiles to manage memory. Astroray renders the full image at once.

## Cycles reference
- `intern/cycles/session/tile.h` — tile management

## What to implement
1. Divide the image into tiles (default 2048×2048 or adaptive based on memory)
2. Render each tile independently, writing results to the output buffer
3. Report per-tile progress to Blender via `self.update_progress()`
4. This enables rendering images larger than GPU memory

## Acceptance criteria
- [ ] A 4K render produces identical results with and without tiling
- [ ] Progress reporting shows tile-by-tile updates in Blender'\''s header bar'

ci "feat: Persistent data for animation rendering" \
   "cycles-parity,performance" \
'## Summary
Cycles "Persistent Data" keeps the BVH and textures in memory between animation frames, avoiding expensive rebuilds.

## What to implement
1. When rendering animation: after the first frame, keep the Renderer object alive
2. Only update objects that changed (moved, material changed, etc.) rather than rebuilding everything
3. This is primarily a Blender addon optimization in the `render()` method
4. For static scenes: reuse BVH entirely. For animated scenes: rebuild only changed geometry.

## Acceptance criteria
- [ ] Second frame of an animation renders faster than the first (no BVH rebuild for static geometry)
- [ ] Moving one object only rebuilds that object'\''s portion of the scene'

echo ""
echo "============================================"
echo "  All issues created!"
echo "============================================"
echo ""
echo "Total: ~35 issues across 10 categories."
echo ""
echo "ASSIGNMENT STRATEGY:"
echo "  Start with these foundational issues first (they affect everything else):"
echo "    1. 'Proper linear output for Blender color management' (CRITICAL — changes pixel output)"
echo "    2. 'Per-face material assignment'"
echo "    3. 'Per-corner normals'"
echo "    4. 'Per-bounce-type max bounces'"
echo ""
echo "  Then Tier 2 (materials + textures):"
echo "    5. Multi-scatter GGX"
echo "    6. Normal Map / Bump support"
echo "    7. All standalone BSDF nodes"
echo "    8. Procedural textures"
echo ""
echo "  Then lighting, passes, and everything else."
echo ""
echo "  Assign 1-2 at a time:"
echo "    gh issue edit <NUM> --add-assignee @copilot"
echo ""
