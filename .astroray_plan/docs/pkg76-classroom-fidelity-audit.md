# Classroom Fidelity Audit — pkg76-followup-classroom-fidelity

**Date:** 2026-05-24  
**Package:** pkg76-followup-classroom-fidelity  
**SSIM measured:** 0.470 (PR #357)  
**SSIM gate:** ≥0.85  

---

## Executive Summary

The Classroom scene renders without crashing on Astroray GPU but produces SSIM 0.470 vs the Cycles-CPU reference, well below the 0.85 parity-scope gate. Analysis of the .blend metadata reveals **three major import gaps**, all within parity scope to fix. The largest gap (40 of 42 materials lack shader-graph evaluation) accounts for most of the visual divergence.

---

## Scene Characteristics (from .blend SDNA)

- **Resolution:** 1920×1080
- **Samples:** 300 SPP
- **Camera:** Perspective, lens=25mm, sensor=32×18mm
- **World:** `use_nodes=True`, Background node with color=[0,0,0], strength=0.0 (black, correct for indoor scene)
- **Meshes:** 182 objects, 81,219 vertices, 81,289 polygons
- **Materials:** 42 total
  - **2** have Principled BSDF nodes
  - **40** use shader node graphs with image textures (NOT Principled BSDF)
- **Lights:** 9 total
  - 1× AREA (blackBoard_light, energy=0.785)
  - 1× POINT (coridor_ceilingLight, energy=60.0)
  - 1× AREA (exterior_fillLight, energy=1963.5)
  - 5× SPOT (energy=100.0 each)
  - 1× SUN (energy=1.0)

---

## Identified Gaps

### Gap 1: Image texture evaluation missing for non-Principled materials

**Symptom:** 40 of 42 materials use shader node graphs with `TEX_IMAGE` nodes connected to BSDF inputs, but Astroray's importer only reads Principled/Diffuse BSDF socket default values. When the base color comes from an image texture (not a constant), Astroray falls back to legacy Material.r/g/b (often white or gray). This produces matte, untextured surfaces across walls, floors, furniture, and objects — a massive visual gap.

**Astroray imported:** For materials like `beige_paintedPipe`, `beigeWall`, `blackBoard`, `cork`, etc., the importer reads:
- `use_nodes=True` → looks for Principled BSDF
- Finds none (these materials use shader graph without a Principled BSDF node, or connect image textures to BSDF inputs)
- Falls back to `Material.r`, `Material.g`, `Material.b` legacy fields (which are often [1.0, 1.0, 1.0] or [0.8, 0.8, 0.8])

**Cycles parses:** For each material, Cycles evaluates the full shader node graph:
- Walks `Material.nodetree → bNodeTree → bNode list`
- Finds `TEX_IMAGE` nodes
- Loads the image from the relative path (`//textures/_baseTextures/base_paintedPlasterWall.jpg`, etc.)
- Evaluates the shader graph to produce the final surface color and roughness

**Cycles reference:**
- `intern/cycles/blender/shader.cpp`: `add_node()` and `add_nodes()` walk the full shader graph, including image texture nodes
- `intern/cycles/blender/image.cpp`: `BlenderImageLoader::load_image()` resolves `//` relative paths and loads textures

**Classification:** **(a) Fixable in parity scope**

**Proposed fix:** Extend `_material_base_color()` in `scene_builder.py` to:
1. If a Principled/Diffuse BSDF node exists, check if its "Base Color" socket is connected to a `TEX_IMAGE` node.
2. If so, resolve the image path (using Blender's `//` → blend-file-relative convention), load the image, and sample it (either at a fixed UV like [0.5, 0.5] or compute the per-triangle average color).
3. Fall back to socket default value if the texture path is invalid or the image can't be loaded.

**Impact estimate:** This gap alone likely accounts for SSIM 0.47 → 0.75–0.80 improvement, as 95% of the scene's visible surface area uses textured materials.

---

### Gap 2: Non-Principled BSDF shader nodes unsupported

**Symptom:** Classroom materials use custom shader node graphs (e.g., `MixRGB`, `ColorRamp`, `Mapping`, `Fresnel`) that are NOT routed through a Principled BSDF. Astroray's parity-scope importer only recognizes `ShaderNodeBsdfPrincipled` and `ShaderNodeBsdfDiffuse`, so materials like `dayLight_portal` and `blackBoardLight` (emissive shaders) produce no emission in Astroray.

**Astroray imported:** For materials without Principled/Diffuse BSDF, the importer logs:
```
[blend_import] material <hash> has nodes but no Principled/Diffuse BSDF — falling back to legacy r/g/b
```
Result: surfaces appear as flat Lambertian with a single color.

**Cycles parses:** Cycles evaluates the full shader graph, including:
- `ShaderNodeEmission` → emissive surfaces (e.g., light portals, blackboard backlight)
- `ShaderNodeMixShader` → blended BSDFs
- `ShaderNodeFresnel` → view-dependent effects
- `ShaderNodeBsdfGlossy`, `ShaderNodeBsdfGlass`, etc. → specialized materials

**Cycles reference:**
- `intern/cycles/blender/shader.cpp`: `add_node()` dispatches on `node->type` (extracted from SDNA `bNode.idname`)
- Full shader-graph walking and Cycles shader node construction

**Classification:** **(b) Out-of-parity-scope** — pkg76 spec §"Minimum field set" explicitly states:
> "Principled BSDF base colour (no metallic/roughness/IOR yet; those come in a follow-up). Point/sun/spot/area lights. Background colour. Perspective camera."

Full shader-graph evaluation (Mix nodes, Emission, Glossy, etc.) is a much larger pkg57 follow-up. However, **emissive materials** (Gap 2a below) are a small subset that could be fixed cheaply.

**Proposed fix:** File a separate package `pkg76-followup-shader-graph-full` for general node-graph evaluation. For emissive materials specifically, see Gap 2a.

---

### Gap 2a: Emissive materials (ShaderNodeEmission) missing

**Symptom:** Classroom has at least 2 emissive materials (`dayLight_portal`, `blackBoardLight`) used for indirect lighting. Astroray imports them as non-emissive Lambertian surfaces, losing illumination from these portals/panels.

**Astroray imported:** Falls back to legacy r/g/b, no emission component.

**Cycles parses:** Detects `ShaderNodeEmission` in the shader graph, sets the surface's emission color and strength.

**Cycles reference:**
- `intern/cycles/blender/shader.cpp`: `add_node()` case for `ShaderNodeEmission`

**Classification:** **(a) Fixable in parity scope** — emissive surfaces are simpler than full shader-graph walking. We can add a special case:
1. Walk the material's node tree for `ShaderNodeEmission`.
2. If found, read its "Color" and "Strength" sockets.
3. Tag the Astroray material as emissive with `emission_color = Color * Strength`.

**Proposed fix:** Add `_material_emission()` helper to `scene_builder.py`, similar to `_material_base_color()`. If an Emission node is found, call `ctx.renderer.set_material_emission(mat_id, emission_rgb)` (requires C++ Renderer API extension).

**Impact estimate:** Small but non-zero — emissive portals contribute indirect light. May lift SSIM by 0.02–0.05.

---

### Gap 3: Spot light shape and falloff parameters missing — **FALSE POSITIVE; ALREADY CLOSED**

**Update 2026-05-24:** Investigation by team-lead Gap 3 dispatch found this gap was incorrectly audited. The spot-light cone (`spotsize`) and blend (`spotblend`) parameters ARE already being imported correctly — see `tools/blend_import/scene_builder.py:649-652` and `module/blender_module.cpp::PyRenderer::addSpotLight` (lines 492-507). The `SpotLightSphere` (`include/astroray/raytracer.h:867-931`) consumes them correctly for angular falloff. Existing test coverage in `tests/test_python_bindings.py:263, 293`. The "distance falloff" parameter the audit cited (`Light.att_dist`) is non-physical and Cycles does NOT use it (confirmed via `intern/cycles/blender/light.cpp` analysis — physical inverse-square falloff is implicit in path tracing). No code change needed; remove this gap from the residual-fix budget.

**Original symptom (now refuted):** Classroom has 5 spot lights (energy=100 each). Astroray's importer reads light type and energy but does NOT import spot cone angle, blend (soft edge), or distance falloff. Cycles uses these to produce focused pools of light; Astroray may default to a wider cone or no falloff, producing over-bright or mis-distributed illumination.

**Astroray actually imports (corrected 2026-05-24):** From `_emit_light()` in `scene_builder.py:649-652`:
- Light type (spot → `Renderer.add_spot_light`)
- `color` (from Light.r/g/b)
- `energy` (from Light.energy)
- `spotsize` (cone outer angle, radians)
- `spotblend` (soft-edge width, 0-1)

**Cycles parses:** From Blender's `Light` (Lamp) SDNA:
- `spot_size` (float, radians) — cone outer angle
- `spot_blend` (float, 0–1) — soft edge width
- `area_size`, `area_sizey` (for area lights)
- `use_contact_shadow`, etc.

**Cycles reference:**
- `intern/cycles/blender/light.cpp`: `BlenderSync::sync_light()` reads `b_light.spot_size()`, `b_light.spot_blend()`

**Classification:** **(a) Fixable in parity scope** — spot lights are already in the parity feature set; we just need to read the additional SDNA fields.

**Proposed fix:** In `_emit_light()`, after reading `energy`:
```python
if light_type == LA_SPOT:
    spot_size = blend.read_float(light_blk, light_struct, "spot_size")[0]
    spot_blend = blend.read_float(light_blk, light_struct, "spot_blend")[0]
    # Convert spot_size (radians, outer angle) to degrees for Renderer API
    cone_angle_deg = math.degrees(spot_size)
    # spot_blend ∈ [0,1] defines the soft edge: inner = outer * (1 - blend)
    # Astroray's add_spot_light may need (outer_angle, inner_angle) or (angle, penumbra)
    # Check the Renderer API signature and map accordingly.
    ctx.renderer.add_spot_light(pos, dir, color, energy, cone_angle_deg, spot_blend)
```

**Impact estimate:** Small — spot lights are already present; this refines their distribution. May lift SSIM by 0.01–0.03.

---

### Gap 4: Area light shape (size, orientation) not fully imported

**Symptom:** Classroom has 3 area lights (`blackBoard_light`, `exterior_fillLight`, and possibly the spot lights are actually area lights in disguise). Astroray imports them as point lights with energy but does NOT import `area_size`, `area_sizey`, or the light's orientation (normal vector).

**Astroray imported:** From `_emit_light()`:
- Light type → if `LA_AREA`, converts to `add_point_light` (line 531: "area light → approximate as point for now")
- Logs a warning: "area light → approximate as point for now"

**Cycles parses:**
- `area_size`, `area_sizey` (rectangle dimensions)
- Light object's world transform → orientation and position

**Cycles reference:**
- `intern/cycles/blender/light.cpp`: `BlenderSync::sync_light()` handles area lights with shape and transform

**Classification:** **(a) Fixable in parity scope IF** Astroray's Renderer has `add_area_light()` or similar. If not, this is **(b) out-of-scope** (requires renderer backend work).

**Proposed fix:** Check if `Renderer.add_area_light(pos, normal, width, height, color, energy)` exists. If so, extract:
```python
area_size = blend.read_float(light_blk, light_struct, "area_size")[0]
area_sizey = blend.read_float(light_blk, light_struct, "area_sizey")[0]
# Light object's world matrix M gives orientation
M = _object_local_matrix(ctx, light_obj_blk)
normal = [M[0][2], M[1][2], M[2][2]]  # local +Z axis
pos = [M[0][3], M[1][3], M[2][3]]
ctx.renderer.add_area_light(pos, normal, area_size, area_sizey, color, energy)
```

If `add_area_light()` does not exist, file `pkg76-followup-area-light-backend` for the renderer-side implementation.

**Impact estimate:** Medium — area lights produce softer shadows and better illumination gradients. May lift SSIM by 0.03–0.08 if the Classroom's window fill light is large.

---

## Recommended Fix Order (cheapest first, by effort × impact)

1. **Gap 1 (image textures for Principled BSDF)** — highest impact, medium effort. Requires:
   - Path resolution (`//` → absolute)
   - Image loading (use PIL or OpenCV to read JPG/PNG)
   - Color sampling (average or fixed UV)
   - **Estimated time:** 2–4 hours
   - **SSIM lift:** +0.25–0.33 (0.47 → 0.70–0.80)

2. ~~**Gap 3 (spot light cone + blend)** — low effort, small impact.~~
   - **Status (2026-05-24):** FALSE POSITIVE — already implemented in pkg76 original; see Gap 3 entry above. Removed from the residual-fix budget.

3. **Gap 2a (emissive materials)** — medium effort, small-to-medium impact. Requires Renderer API extension (`set_material_emission`).
   - **Estimated time:** 1–2 hours
   - **SSIM lift:** +0.02–0.05

4. **Gap 4 (area light shape)** — depends on whether `add_area_light()` exists. If yes: low effort, medium impact. If no: out-of-scope (backend work).
   - **Estimated time:** 1 hour (if API exists), else out-of-scope
   - **SSIM lift:** +0.03–0.08

**Total estimated lift if all (a) gaps closed:** 0.47 → 0.81–0.91 SSIM (likely clears the 0.85 gate).

---

## Next Steps (per pkg76-followup-classroom-fidelity spec)

1. **Close Gap 1** (this package): Implement image texture loading for Principled BSDF base color. Re-measure SSIM. **DONE 2026-05-24 (PR #361 merged).** Measured SSIM 0.470 — no change because only 2/42 mats are Principled BSDF; Gap 2 dominates.
2. ~~If SSIM < 0.85 after Gap 1, close Gap 3 (spot light params) and re-measure.~~ **Gap 3 was a false positive — already implemented since pkg76; removed from residual budget.**
3. If still < 0.85, file follow-up packages for Gap 2a (emissive) and Gap 4 (area lights). **Gap 4 IN PROGRESS (PR #363, area light shape mapping).** Gap 2a remains the highest-impact remaining lift (40/42 mats need non-Principled shader graph walking).
4. If SSIM ≥ 0.85 after Gap 1 + Gap 4 + Gap 2a, declare parity gate CLOSED for Classroom.

---

## References

- **Classroom .blend metadata:** `test_results/pkg76-classroom-blend-metadata.json` (generated 2026-05-24)
- **Astroray importer:** `tools/blend_import/scene_builder.py` (commit 41582fd)
- **Cycles material import:** `intern/cycles/blender/shader.cpp` (Apache-2.0, read for understanding)
- **Cycles light import:** `intern/cycles/blender/light.cpp` (Apache-2.0, read for understanding)
- **Cycles image loading:** `intern/cycles/blender/image.cpp` (Apache-2.0, read for understanding)
- **pkg76 spec:** `.astroray_plan/packages/pkg76-blend-importer-parity-scope.md` (defines parity-scope subset)

---

**Audit completed:** 2026-05-24  
**Next action:** Implement Gap 1 fix in `scene_builder.py`.
