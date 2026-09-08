# Reference corpus (pkg259)

A version-pinned corpus of representative, deliberately attractive Blender
scenes that together exercise every Cycles feature Astroray is meant to
support (materials, textures/mapping, lights, world, geometry, camera,
render settings, passes). Each scene carries a manifest of the matrix
features it demonstrates, so a Cycles feature Astroray silently drops is
found by a test, not by someone happening to wire it. Design record:
`.astroray_plan/docs/reference-corpus-design-2026-09.md`. Spec:
`.astroray_plan/packages/pkg259-cycles-feature-coverage-reference-scenes.md`.

**Phase 1 of 4** (this state): `materials_hall` and `textures_mapping` only.
`lighting_studio`, `world_sky`, `geometry_zoo`, `camera_lens`,
`render_settings`, the harness/bench integration, and `coverage_report.py`
are later phases -- see the spec's Progress log.

## Families

| Family | Concept | Status |
|---|---|---|
| `materials_hall` | Every BSDF/closure Cycles ships, staged as a gallery corridor: one alcove per closure family (Diffuse, Glossy/Metallic, Dielectric, the Principled wall, Sheen/Translucent, Emission & spectral, an OSL gap-card placard), one shared 3-point + practical light rig. | Phase 1 (built) |
| `textures_mapping` | A printmaker's workshop: a print table plus small independent proof cards (one `<node> -> Emission -> Output` per required node) for the procedural-texture, pattern, image/coordinate, bump/normal/displacement, and colour-grade/converter node families. | Phase 1 (built) |
| `lighting_studio` | Photography-studio still life shot four ways, one per light type. | Phase 2 |
| `world_sky` | HDRI vs Sky-texture exterior, "three independent opportunities" (background/reflection/indirect). | Phase 2 |
| `geometry_zoo` | Instancing, hair, modifiers, motion blur, volumes (solid + volume cabinets). | Phase 3 |
| `camera_lens` | DoF/orthographic/panoramic/clip 2x2 contact sheet. | Phase 3 |
| `render_settings` | Six-panel pass sheet, convergence/denoise, bounce-limit rig. | Phase 3 |

## Naming and files

- `scenes/<family>.blend` -- the built scene (one `.blend` per family this
  phase; a family may later split into `<family>_<part>.blend` files sharing
  one family tag if a single frame becomes illegible, per the design doc
  Sec 6.2 item 8 -- not needed for either Phase-1 scene).
- `scenes/manifest.json` -- one entry per family: `family`, `builder_fn`,
  `blend_path`, `sha256`, `settings` (res/spp/engine), `reopen_verified`,
  `triangle_count`, `curve_count`/`curve_point_count`, `object_counts`,
  `node_ids`, `feature_tags`, `assets`, `crops`. Schema design:
  `.astroray_plan/docs/reference-corpus-design-2026-09.md` Sec 4.1.
- `scenes/gap_registry.json` -- machine copy of every DROPPED-SILENT matrix
  row a family owns that is *not* given an in-scene gap card; the Markdown
  version is the "Gap registry" section below. Regenerated every
  `build_corpus.py` run (`--print-gap-registry` to reprint it to stdout).
- `refs/` -- rendered PNGs (`<family>_<engine>_cpu.png`) and a side-by-side
  contact sheet per scene. **Gitignored globally** (`*.png`); committed
  copies use `git add -f`.

## Manifest schema (`feature_tags` entries)

```jsonc
{
  "category": "shader_node", "feature": "BSDF_GLASS",
  "bl_idname": "ShaderNodeBsdfGlass", "socket_or_prop": "input:IOR",
  "classification": "SUPPORTED", "gap_card": false
}
```

Shape mirrors a `docs/blender_parity/coverage_matrix.json` row exactly, so
a future `coverage_report.py` (Phase 4) can join on the same tuple key.
`"gap_card": true` marks a DROPPED-SILENT feature the scene deliberately
makes visible (e.g. the OSL placard in `materials_hall`); every other
DROPPED-SILENT row for the family is *not* in `feature_tags` -- it is listed
in the Gap registry below instead.

## Coverage-claim rule (binding)

A `feature_tags` entry is only valid if the socket/prop is **connected or
set to a non-default, effect-producing value** *and* its effect falls inside
a documented crop region (`crops` in the manifest) -- not merely "the node
exists somewhere in the scene". `build_corpus.py` enforces the SUPPORTED/
APPROXIMATED half of this mechanically: each scene builder in
`benchmarks/blender_parity/scene_library.py` returns the exact
`(bl_idname, socket_or_prop)` pairs it actively wires, and `build_corpus.py`
cross-checks that list against every SUPPORTED/APPROXIMATED
`coverage_matrix.json` row assigned to the family (via the Phase-0
allocation table's `ASSIGN` map) -- it raises loudly (`SystemExit`) if a
required row is missing, or if a builder claims a row that isn't actually
assigned to that family. This is why building the corpus is called
"proving" coverage rather than "asserting" it.

## Coverage totals (Phase 1, post-pkg253 matrix)

| Family | Rows owned | SUPPORTED | APPROXIMATED | tagged (feature_tags) | gap-carded | gap registry |
|---|---|---|---|---|---|---|
| `materials_hall` | 166 | 10 | 46 | 56 | 1 (SCRIPT) | 109 |
| `textures_mapping` | 263 | 69 | 3 | 72 | 0 | 181 |

("Rows owned" = every matrix row the Phase-0 allocation table assigns to
that family as primary owner; DROPPED-SILENT rows make up the remainder.
Re-run `.astroray_plan/docs/pkg259-phase0/build_allocation_table.py` if
`coverage_matrix.json` changes -- these totals will drift with it. pkg260's
scanner extension (#758, merged 2026-09-08) landed 42 new rows for
`textures_mapping` (`image_property`/`input_node` categories: Image /
`ShaderNodeTexImage` colour-management properties, `NEW_GEOMETRY`,
`OBJECT_INFO`, `ATTRIBUTE`, `VERTEX_COLOR`, `LIGHT_PATH`), all
DROPPED-SILENT; 10 of them (`Image`/`ShaderNodeTexImage`/`ATTRIBUTE`) are
already documented under the same `bl_idname` elsewhere in this file, the
other 32 are newly listed in the gap registry below. `materials_hall` is
unaffected by the pkg260 merge -- no new rows were assigned to it.)

## How a new Cycles feature gets a home

1. Add/extend a row in `docs/blender_parity/coverage_matrix.json` (owned by
   pkg229/pkg119 Phase A's scanner, not this package).
2. Assign it to a family in `.astroray_plan/docs/pkg259-phase0/build_allocation_table.py`'s
   `ASSIGN` map, re-run the script, and check `allocation_table.md` picked it up.
3. Wire it into that family's builder in `benchmarks/blender_parity/scene_library.py`
   (`build_<family>_scene`), returning the new `(bl_idname, socket_or_prop)`
   pair in the builder's `tags` list, with a documented crop region.
4. Re-run `build_corpus.py --families <family>` -- it fails loudly if the row
   isn't actually wired, or if `tags` claims something the allocation table
   doesn't assign to this family.
5. Re-render both engines (`render_leg.py --load-blend`) and update `refs/`.

## How to regenerate

```
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b --factory-startup \
    --python benchmarks/reference_corpus/build_corpus.py -- \
    --families materials_hall textures_mapping \
    --out-dir benchmarks/reference_corpus/scenes
```

Then render both engines per scene via `render_leg.py --load-blend` (absolute
paths for `--load-blend`/`--out` -- Blender's relative-path resolution after
`bpy.ops.wm.open_mainfile` does not reliably match the invoking shell's
working directory):

```
blender.exe -b --factory-startup --python benchmarks/blender_parity/render_leg.py -- \
    --load-blend <abs>/benchmarks/reference_corpus/scenes/<family>.blend \
    --engine CYCLES --out <abs>/benchmarks/reference_corpus/refs/<family>_cycles_cpu \
    --res 512 --res-y 288 --samples 128 --device cpu
```

(swap `--engine CUSTOM_RAYTRACER` and set `ASTRORAY_PYD_DIR` to the staged
OpenMP-off CPU addon module for the Astroray leg). `render_leg.py` writes a
linear `.npy`; convert to a display PNG with any sRGB-encode helper (Blender's
own Python often lacks Pillow -- the repo's normal Python environment does not).

## Asset licences

None yet. Phase 1 uses only procedural geometry/textures (per the design
doc's "procedural builders over hand-authored files" decision) plus
Blender's bundled Suzanne monkey mesh (`materials_hall` Alcove D bust --
ships with every Blender install, no licence needed). The one deferred item:
a real CC0 file-based image for the `TEX_IMAGE` file-loading proof (the
Phase-1 `TEX_IMAGE` row is instead covered by a procedural stripe pixel
buffer, which proves the `Vector` input row but not file I/O) -- tracked as
a Phase 1 gap, see "Known Phase-1 gaps" below. When added, its exact
filename, resolution, source URL, licence and sha256 go in a table here
(matching `.astroray_plan/docs/reference-corpus-design-2026-09.md` Sec 3's
format) before the asset is committed.

## Known Phase-1 gaps (deliberate, not oversights)

- **`TEX_IMAGE` file-based loading** is deferred (spec's binding Phase-1
  scope: "no external downloads in this phase"); the procedural stripe
  buffer covers the `input:Vector` row honestly but not file-I/O behaviour.
- **`materials_hall` Alcoves F (Hair BSDFs) and G (shader-graph utility:
  Add/Mix Shader, Holdout, ShaderToRGB, Material Raycast)** are not built:
  every row those nodes own in the current matrix is DROPPED-SILENT (no
  SUPPORTED/APPROXIMATED row would go untagged by skipping them), so they
  are gap-registry entries only, not in-scene content. `BSDF_RAY_PORTAL`'s
  "impossible doorway" concept from the design doc is likewise gap-registry
  only for the same reason.
- **One `.blend` per family** (not split into sub-scenes) -- both Phase-1
  frames render legibly at the coverage-report's thumbnail size; see the
  design doc Sec 6.2 item 8's open decision, resolved here as "no split
  needed."
- **Crop rectangles** (`manifest.json`'s `crops`) are a linear pinhole
  approximation (`scene_library._crop_rect`), not a perspective-accurate
  projection -- adequate for Phase 4's coverage report; refine there if a
  crop render disagrees with the documented rectangle.

## Gap registry

Every DROPPED-SILENT `coverage_matrix.json` row a Phase-1 family owns that
is *not* given an in-scene gap card (machine copy: `scenes/gap_registry.json`,
regenerated by `build_corpus.py`).

### `materials_hall` (109 rows)

- `ADD_SHADER` (`ShaderNodeAddShader`): input:Shader, input:Shader
- `BSDF_DIFFUSE` (`ShaderNodeBsdfDiffuse`): input:Normal, input:Weight
- `BSDF_GLASS` (`ShaderNodeBsdfGlass`): input:Normal, input:Weight, input:Thin Film Thickness, input:Thin Film IOR, prop:distribution
- `BSDF_GLOSSY` (`ShaderNodeBsdfAnisotropic`): input:Anisotropy, input:Rotation, input:Normal, input:Tangent, input:Weight, prop:distribution
- `BSDF_HAIR` (`ShaderNodeBsdfHair`): input:Color, input:Offset, input:RoughnessU, input:RoughnessV, input:Tangent, input:Weight, prop:component
- `BSDF_HAIR_PRINCIPLED` (`ShaderNodeBsdfHairPrincipled`): input:Color, input:Melanin, input:Melanin Redness, input:Tint, input:Absorption Coefficient, input:Aspect Ratio, input:Roughness, input:Radial Roughness, input:Coat, input:IOR, input:Offset, input:Random Color, input:Random Roughness, input:Random, input:Weight, input:Reflection, input:Transmission, input:Secondary Reflection, prop:model, prop:parametrization
- `BSDF_METALLIC` (`ShaderNodeBsdfMetallic`): input:IOR, input:Extinction, input:Normal, input:Tangent, input:Weight
- `BSDF_PRINCIPLED` (`ShaderNodeBsdfPrincipled`): input:Weight, input:Subsurface IOR, input:Tangent, input:Coat Normal, prop:distribution, prop:subsurface_method
- `BSDF_RAY_PORTAL` (`ShaderNodeBsdfRayPortal`): input:Color, input:Position, input:Direction, input:Weight
- `BSDF_REFRACTION` (`ShaderNodeBsdfRefraction`): input:Normal, input:Weight, prop:distribution
- `BSDF_SHEEN` (`ShaderNodeBsdfSheen`): input:Normal, prop:distribution
- `BSDF_TOON` (`ShaderNodeBsdfToon`): input:Color, input:Size, input:Smooth, input:Normal, input:Weight, prop:component
- `BSDF_TRANSLUCENT` (`ShaderNodeBsdfTranslucent`): input:Normal, input:Weight
- `BSDF_TRANSPARENT` (`ShaderNodeBsdfTransparent`): input:Weight
- `EEVEE_SPECULAR` (`ShaderNodeEeveeSpecular`): input:Base Color, input:Specular, input:Roughness, input:Emissive Color, input:Transparency, input:Normal, input:Clear Coat, input:Clear Coat Roughness, input:Clear Coat Normal, input:Weight
- `EMISSION` (`ShaderNodeEmission`): input:Weight
- `HOLDOUT` (`ShaderNodeHoldout`): input:Weight
- `MATERIAL_RAYCAST` (`ShaderNodeRaycast`): input:Position, input:Direction, input:Length, input:, prop:active_index, prop:only_local
- `MIX_SHADER` (`ShaderNodeMixShader`): input:Factor, input:Shader, input:Shader
- `OUTPUT_MATERIAL` (`ShaderNodeOutputMaterial`): input:Surface, input:Volume, input:Displacement, input:Thickness, prop:is_active_output, prop:target
- `SCRIPT` (`ShaderNodeScript`): prop:use_auto_update (`prop:mode` is gap-carded in-scene, Alcove I placard)
- `SHADERTORGB` (`ShaderNodeShaderToRGB`): input:Shader
- `SUBSURFACE_SCATTERING` (`ShaderNodeSubsurfaceScattering`): input:Color, input:Scale, input:Radius, input:IOR, input:Roughness, input:Anisotropy, input:Normal, input:Weight, prop:falloff

### `textures_mapping` (181 rows)

- `AMBIENT_OCCLUSION` (`ShaderNodeAmbientOcclusion`): input:Color, input:Distance, input:Normal, prop:inside, prop:only_local, prop:samples
- `ATTRIBUTE` (`ShaderNodeAttribute`): prop:attribute_type
- `BEVEL` (`ShaderNodeBevel`): input:Radius, input:Normal, prop:samples
- `BUMP` (`ShaderNodeBump`): prop:invert
- `CLAMP` (`ShaderNodeClamp`): input:Value, input:Min, input:Max, prop:clamp_type
- `COMBINE_COLOR` (`ShaderNodeCombineColor`): input:Red, input:Green, input:Blue, prop:mode
- `COMBXYZ` (`ShaderNodeCombineXYZ`): input:X, input:Y, input:Z
- `CURVE_FLOAT` (`ShaderNodeFloatCurve`): input:Factor, input:Value
- `CURVE_RGB` (`ShaderNodeRGBCurve`): input:Factor, input:Color
- `CURVE_VEC` (`ShaderNodeVectorCurve`): input:Factor, input:Vector
- `DISPLACEMENT` (`ShaderNodeDisplacement`): input:Normal, prop:space
- `FRESNEL` (`ShaderNodeFresnel`): input:IOR, input:Normal
- `INVERT` (`ShaderNodeInvert`): input:Factor
- `LAYER_WEIGHT` (`ShaderNodeLayerWeight`): input:Blend, input:Normal
- `LIGHT_FALLOFF` (`ShaderNodeLightFalloff`): input:Strength, input:Smooth
- `LIGHT_PATH` (`ShaderNodeLightPath`, pkg260): output:Is Camera Ray, output:Is Shadow Ray, output:Is Diffuse Ray, output:Is Glossy Ray, output:Is Singular Ray, output:Is Reflection Ray, output:Is Transmission Ray, output:Is Volume Scatter Ray, output:Ray Length, output:Ray Depth, output:Diffuse Depth, output:Glossy Depth, output:Transparent Depth, output:Transmission Depth, output:Portal Depth
- `MAPPING` (`ShaderNodeMapping`): input:Vector, input:Location, input:Rotation, input:Scale, prop:vector_type
- `MAP_RANGE` (`ShaderNodeMapRange`): input:Value, input:From Min, input:From Max, input:To Min, input:To Max, input:Steps, input:Vector, input:From Min, input:From Max, input:To Min, input:To Max, input:Steps, prop:clamp, prop:data_type, prop:interpolation_type
- `MATH` (`ShaderNodeMath`): input:Value, input:Value, input:Value, prop:operation, prop:use_clamp
- `MIX` (`ShaderNodeMix`): input:Factor, input:Factor, input:A, input:B, input:A, input:B, input:A, input:B, input:A, input:B, prop:clamp_factor, prop:clamp_result, prop:data_type, prop:factor_mode
- `MIX_RGB` (`ShaderNodeMixRGB`): input:Factor, input:Color1, input:Color2, prop:use_alpha, prop:use_clamp
- `NEW_GEOMETRY` (`ShaderNodeNewGeometry`, pkg260): output:Position, output:Normal, output:Tangent, output:True Normal, output:Incoming, output:Parametric, output:Backfacing, output:Pointiness, output:Random Per Island
- `NORMAL` (`ShaderNodeNormal`): input:Normal
- `NORMAL_MAP` (`ShaderNodeNormalMap`): prop:base, prop:convention, prop:space
- `OBJECT_INFO` (`ShaderNodeObjectInfo`, pkg260): output:Location, output:Color, output:Alpha, output:Object Index, output:Material Index, output:Random
- `SEPARATE_COLOR` (`ShaderNodeSeparateColor`): input:Color, prop:mode
- `SEPXYZ` (`ShaderNodeSeparateXYZ`): input:Vector
- `SQUEEZE` (`ShaderNodeSqueeze`): input:Value, input:Width, input:Center
- `ShaderNodeRadialTiling` (`ShaderNodeRadialTiling`): input:Vector, input:Sides, input:Roundness, prop:normalize
- `TANGENT` (`ShaderNodeTangent`): prop:axis, prop:direction_type
- `TEX_BRICK` (`ShaderNodeTexBrick`): input:Vector, input:Mortar, prop:offset
- `TEX_CHECKER` (`ShaderNodeTexChecker`): input:Vector
- `TEX_COORD` (`ShaderNodeTexCoord`): prop:from_instancer
- `TEX_GABOR` (`ShaderNodeTexGabor`): input:Vector, input:Scale, input:Frequency, input:Anisotropy, input:Orientation, input:Orientation, prop:gabor_type
- `TEX_GRADIENT` (`ShaderNodeTexGradient`): input:Vector
- `TEX_IMAGE` (`ShaderNodeTexImage`): prop:extension, prop:interpolation, prop:projection, prop:projection_blend
- `TEX_MAGIC` (`ShaderNodeTexMagic`): input:Vector
- `TEX_NOISE` (`ShaderNodeTexNoise`): input:Vector, input:W, prop:noise_dimensions
- `TEX_VORONOI` (`ShaderNodeTexVoronoi`): input:Vector, input:W, prop:voronoi_dimensions
- `TEX_WAVE` (`ShaderNodeTexWave`): input:Vector
- `TEX_WHITE_NOISE` (`ShaderNodeTexWhiteNoise`): input:Vector, input:W, prop:noise_dimensions
- `UVMAP` (`ShaderNodeUVMap`): prop:from_instancer
- `VALTORGB` (`ShaderNodeValToRGB`): input:Factor
- `VECTOR_DISPLACEMENT` (`ShaderNodeVectorDisplacement`): input:Vector, input:Midlevel, input:Scale, prop:space
- `VECTOR_ROTATE` (`ShaderNodeVectorRotate`): input:Vector, input:Center, input:Axis, input:Angle, input:Rotation, prop:invert, prop:rotation_type
- `VECT_MATH` (`ShaderNodeVectorMath`): input:Vector, input:Vector, input:Vector, input:Scale, prop:operation
- `VECT_TRANSFORM` (`ShaderNodeVectorTransform`): input:Vector, prop:convert_from, prop:convert_to, prop:vector_type
- `VERTEX_COLOR` (`ShaderNodeVertexColor`, pkg260): output:Color, output:Alpha
- `WIREFRAME` (`ShaderNodeWireframe`): input:Size, prop:use_pixel_size
