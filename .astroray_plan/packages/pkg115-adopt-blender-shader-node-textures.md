# pkg115 — Adopt Blender's shader node tree for textures/UVs; retire addon-side texture duplication

**Pillar:** 5 (addon) + 2 (materials/textures)
**Track:** A
**Codex-paste-ready:** no (large, staged; RTX visual verify)
**Status:** Stage 2 chunk 1 done (PR #439, 2026-06-11 — GENERATED coord default for procedural nodes, signed Normal coord, (u,v,0) UV 3D point, Checker floor-parity, Gradient 4 formula fixes, Magic verbatim port, eval_texture_at_3d debug binding). REMAINING chunks (audit §6 order 5–10): util/hash + White Noise, Perlin + fractal stack + Noise node, Wave, Brick, Voronoi, addon translator dedup + standalone CI example + RTX visual verify vs Cycles.
**Depends on:** pkg57 (done — established the additive custom-node pattern and
the `convert_node_material` traversal). Benefits from pkg112.
**Estimated effort:** L (multi-week, staged)

---

## Goal

**Before:** The Blender addon does **not** translate Blender's standard
procedural/coordinate texture nodes onto the engine. pkg57 added Astroray
*physics* nodes additively, but procedural texture nodes are left to the legacy
path. Meanwhile the engine ships its own coordinate-space model and 12 procedural
textures (`include/advanced_features.h`, ~539 LOC) plus a clean standalone
string-factory API (`create_procedural_texture`, `set_texture_coord_mode`,
`set_texture_uv_transform`, `set_texture_uv_layer` —
`module/blender_module.cpp:1907-1919`). Net effect: textures authored as Blender
nodes don't render with native fidelity, and the addon duplicates concepts
Blender already owns.

**After:** The addon walks `material.node_tree` from `ShaderNodeOutputMaterial`
and **translates Blender's standard texture & coordinate nodes onto the engine's
existing evaluators**, matching Blender's parameterization so a Blender
Noise/Voronoi/Mapping node looks the same in Astroray. The standalone
string-factory texture API is **preserved** (engine-native texturing stays usable
without Blender). Addon-side private texture/coordinate-model duplication is
removed. Astroray-specific nodes stay additive (pkg57).

---

## Key reframe (research-verified, parity report 2026-05-30 Q3)

Coordinate spaces (Generated/Object/UV/Camera/Window/Normal/Reflection) and the
shader node tree are **shared Blender-core constructs** — `ShaderNodeTexCoord`
inherits `ShaderNode` (not a Cycles-private type), and EEVEE "uses the same
shader nodes as Cycles." RPR and LuxCore read the *same* tree and add their nodes
additively. The **interface/semantics are shared; numerical evaluation stays
per-engine.** So we **keep our evaluators** and drive them from Blender node
parameters — we are not deleting the kernel math, only the duplication and the
private node/coordinate model on the addon side.

---

## References

### Internal
- `blender_addon/__init__.py:1949+` — `convert_node_material` / node traversal.
- `include/advanced_features.h` — `Texture` base + `CoordMode` + 12 procedurals
  (`:145-450`); `TexturedLambertian` `:507-539`.
- `module/blender_module.cpp:1907-1919` — standalone texture factory bindings (kept).
- pkg57 spec — additive node pattern + non-goal "do not migrate procedural nodes"
  (this package is that deferred migration, done right).

### External (cite per evaluator; match the math)
- Blender Texture Coordinate node + `bpy.types.ShaderNodeTexCoord` (docs.blender.org).
- Blender/Cycles procedural math to reproduce for parity (Apache-2.0):
  `intern/cycles/kernel/svm/noise.h` (Perlin), `voronoi.h`, `musgrave.h`,
  `wave.h`, `magic.h`, `brick.h`, and the `mapping`/`tex_coord` nodes.

CLAUDE.md §6: cite the exact Cycles `svm/*` file each evaluator mirrors; verify
our evaluators against Blender's parameterization (scale/detail/roughness/
lacunarity, Voronoi distance metric, octave count) and fix divergences. Save
`.astroray_plan/docs/blender-procedural-parity-research.md`.

---

## Approach (staged)

1. **Audit.** Diff each engine procedural against the corresponding Cycles
   `svm` node parameterization; record divergences.
2. **Translator.** Map `ShaderNodeTexCoord`, `ShaderNodeUVMap`,
   `ShaderNodeMapping`, `ShaderNodeTexNoise`, `ShaderNodeTexVoronoi`,
   `ShaderNodeTexMusgrave/Wave/Magic/Brick/Gradient/Checker`, and
   `ShaderNodeTexImage` onto `create_procedural_texture` + coord-mode + UV-transform.
3. **Parameter parity.** Align engine evaluators to Blender's math (cite svm).
4. **Remove duplication.** Delete the now-unused addon-side private
   texture-definition paths (CLAUDE.md §3: only orphans this change creates).
5. **Standalone.** Keep the factory API and add/keep a standalone example that
   builds a textured material without Blender (CI-testable).

---

## Stage 2 progress (chunk 1)

Implementation of research-doc items 1-4 (coordinate/mapping wiring, Checker, Gradient, Magic):

1. **Coordinate/Mapping wiring** (audit §6 item 1):
   - [x] Addon: unconnected Vector sockets on procedural texture nodes default to GENERATED
         (`_resolve_vector_input` now takes `default_coord_mode` param; procedural textures pass
         "GENERATED", Image Texture passes "UV"). Blender parity per
         `scene/shader_nodes.cpp:926-1724` `LINK_TEXTURE_GENERATED`.
   - [x] Engine: UV mode 3D coord = (u,v,0) for 3D evaluators (was world hit position `rec.point`).
         Parity per audit §4.
   - [x] Engine: Normal mode = signed object-space normal `rec.objectNormal`, no remap (was
         world-space `rec.normal·0.5+0.5`). Parity per Cycles `svm/tex_coord.h:113-121`
         `object_inverse_normal_transform(sd->N)`. Apache-2.0.
   - [ ] TODO (deferred to next chunk): Full-3D Mapping transform (port `svm_mapping_util.h`
         POINT/TEXTURE/VECTOR/NORMAL types with XYZ euler). Currently 2D-only Z-rotation.

2. **Checker** (audit §5.1):
   - [x] Replaced sine-product with Blender's floor-parity formula. Cycles
         `intern/cycles/kernel/svm/checker.h::svm_checker` (Apache-2.0): precision guard
         `(p+1e-6)·0.999999`, then `((xi%2==yi%2)==(zi%2))` on `floor(p·scale)`.
   - [x] Test: `test_pkg115_procedural_parity.py::test_checker_floor_parity`.

3. **Gradient** (audit §5.3):
   - [x] Fixed 4 formulas per Cycles `intern/cycles/kernel/svm/gradient.h` (Apache-2.0):
     - Quadratic: `max(x,0)²` then saturate (was `clamp(x²,0,1)` — diverged for x<0).
     - Spherical: `max(0.999999 − len, 0)` — decreases outward (was increasing).
     - Quadratic sphere: `(1−len)²` (was `1−len²`).
     - Radial: `atan2/2π + 0.5` (was `+1.0` then fmod — half-turn phase offset).
   - [x] Tests: `test_gradient_quadratic_clamp`, `test_gradient_spherical_inverted`,
         `test_gradient_quadratic_sphere`, `test_gradient_radial_phase`.

4. **Magic** (audit §5.5):
   - [x] Verbatim port of Cycles `intern/cycles/kernel/svm/magic.h::svm_magic` (Apache-2.0):
     - Trig arguments: `fmod(p·scale, 2π)` then `·5` (old: `scale·π`).
     - Distortion: per-branch `*= distortion`, final `/= (2·distortion)` (old: pre-multiply `0.25·distortion`).
     - Depth: ≤ 10 (old: capped at 5).
     - Output: true RGB `(0.5−x, 0.5−y, 0.5−z)` (old: scalar 2-color lerp). Factory
       `color1/color2` kept for backward compat (apply as tint via average).
   - [x] Tests: `test_magic_depth_10`, `test_magic_rgb_output`.

**Files changed:**
- `blender_addon/__init__.py`: `_resolve_vector_input` takes `default_coord_mode`, procedural
  textures default to GENERATED, Image Texture defaults to UV.
- `include/advanced_features.h`: Normal coord = object-space `rec.objectNormal`; UV coord
  3D point = `(u,v,0)`; Checker floor-parity port; Gradient 4 formula fixes; Magic verbatim port.
- `module/blender_module.cpp`: added `eval_texture_at_3d` debug binding for parity tests.
- `tests/test_pkg115_procedural_parity.py`: per-evaluator unit tests against Cycles formulas.

**Next chunk (items 5-9):** Hash family port (`util/hash.h`), White Noise evaluator, Perlin +
fractal stack + Noise node, Wave, Brick, Voronoi — largest ports, require new math.

---

## Acceptance criteria

- [ ] Research notes saved; per-evaluator Cycles citations in code.
- [ ] A Blender material using Noise/Voronoi/Mapping/TexCoord renders in Astroray
      **visually matching** Cycles' node semantics (RTX `/verify`, paired stills).
- [ ] Standalone script still builds a textured material via
      `create_procedural_texture` (CPU test).
- [ ] pkg57 nodes unaffected; per-evaluator parity unit tests where feasible.

## Hard non-goals

- Not full OSL/shader-graph parity. Not a GPU procedural-node compiler. Not
  removing the engine evaluators (kept + shared). Not an image-pipeline overhaul
  beyond wiring.

---

## Provenance

Owner goal-capture this round: *"gut some of it and adopt convention; keep a slim
standalone texturing capability if it isn't too hefty."* Research finding: the
standalone texture layer is separable (only used by `TexturedLambertian` and the
`normal_mapped` plugin), so keeping it is cheap; the real work is Blender-
parameterization parity + removing the addon-side duplication.
