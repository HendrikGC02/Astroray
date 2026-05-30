# pkg115 — Adopt Blender's shader node tree for textures/UVs; retire addon-side texture duplication

**Pillar:** 5 (addon) + 2 (materials/textures)
**Track:** A
**Codex-paste-ready:** no (large, staged; RTX visual verify)
**Status:** open — proposed 2026-05-30. **Strategic/large.** Owner-endorsed:
gut the engine-side texture redundancy on the Blender path, keep a slim
standalone texturing API.
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
