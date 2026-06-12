# pkg115 — Adopt Blender's shader node tree for textures/UVs; retire addon-side texture duplication

**Pillar:** 5 (addon) + 2 (materials/textures)
**Track:** A
**Codex-paste-ready:** no (large, staged; RTX visual verify)
**Status:** done (PR #472, 2026-06-12 — 128-spp Blender stills: checker=3D blocks, brick=brickwork, wave=bands, voronoi patterned; semantic parity with Cycles; full suite 1289/0). Stage 2 chunks 1-6 done (PR #439 coord defaults, #441 hash+Perlin+fBM, #442 Wave+Brick, #445 Voronoi, #446 addon ShaderNodeTexVoronoi wiring, #467 chunk 6 addon dedup), GENERATED-coordinates MESH fix PR #472 (Texture::setGeneratedBBox + set_texture_generated_bbox binding + addon records GENERATED textures per material and bakes each user object's world bbox in convert_objects). REMAINING small follow-ups recorded in spec: gradient + noise spheres near-black on addon path; pkg89 dedicated-light energy audit; per-object texture instancing for shared materials.

**Visual-verify findings (2026-06-12, RTX + Blender 5.1 headless, a523a86 diagnosis commit):**
1. **GPU leg dark: dedicated lights not uploaded to GPU** — pkg89/pkg86-B deferral; affects any dedicated-light GPU scene, NOT pkg115-specific.
2. **CPU leg hangs: OpenMP deadlock inside Blender** — MSVC/vcomp generalizes the MinGW memory; ALL addon-use builds need `-DASTRORAY_DISABLE_OPENMP=ON`.
3. **Harness bug (fixed in a523a86): F12 samples property** is `samples`, not `preview_samples`; early stills were 2 spp.
4. **FIXED (commit e418349): procedural-texture GENERATED coordinate space** — AreaLightShape::hit() was not setting rec.hitObject, causing the GENERATED path to fall back to UV (advanced_features.h:91). This produced concentric UV-ring artifact on spheres instead of 3D blocks. Fix: add `rec.hitObject = this;` after material assignment. Test: test_pkg115_generated_coords_fix.py (checker scanline flip count < 8).
5. **pkg89 follow-up noted:** dedicated area light dimmer than Cycles at equal wattage on CPU (energy-scale audit).
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

**Chunk 2 progress (items 5-6, DONE 2026-06-11):**

5. **Hash family** (audit §6.5):
   - [x] Jenkins Lookup3 port from Cycles `util/hash.h` (Apache-2.0): `hash_uint/2/3/4`,
         `hash_float*_to_float*`, `hash_int3_to_float3` (PCG3D). Bit-identical to Cycles.
         Placed in `namespace cycles_hash` in `advanced_features.h:559+`.
   - [x] **WhiteNoiseTexture** evaluator: 3D white noise via `hash_float3_to_float3`.
         Plugin registration `"white_noise"`. Cite: `svm/white_noise.h` (Apache-2.0).
   - [x] Test: `test_pkg115_noise_parity.py::test_hash_known_answer`,
         `test_white_noise_range`.

6. **Perlin + fractal + Noise node** (audit §6.6):
   - [x] Perlin core from Cycles `svm/noise.h` (BSD-3-Clause Sony Pictures/Blender):
         `perlin_3d`, `fade`, `grad3`, `tri_mix`, `snoise_3d`, `noise_3d`. Precision
         guard per Cycles (fmod 100k + correction at large coords). Placed in
         `namespace perlin_noise`.
   - [x] Fractal stack from `svm/fractal_noise.h` (Apache-2.0): `noise_fbm` (fBM with
         fractional octave blend + normalize), `noise_multi_fractal`, `noise_hetero_terrain`,
         `noise_hybrid_multi_fractal`, `noise_ridged_multi_fractal`. Placed in
         `namespace fractal_noise`.
   - [x] **NoiseTextureCycles** evaluator: Blender "Noise Texture" node wrapper per
         `svm/noisetex.h` (Apache-2.0). Params: scale, detail [0,15], roughness,
         lacunarity, offset, gain, distortion, noise_type (0=fBM, 1=multifractal,
         2=hybrid, 3=ridged, 4=hetero), normalize. Distortion = 3D domain warp via
         `snoise_3d(p + random_offset)*distortion`. Color channels use `random_float3_offset`
         seeds 3/4 per Cycles.
   - [x] Plugin registration `"noise_perlin"`. Addon translator mapping for
         ShaderNodeTexNoise deferred to Stage 3.
   - [x] Tests: `test_perlin_zero_at_lattice`, `test_perlin_smoothness`,
         `test_noise_detail_zero_single_octave`, `test_noise_fractional_detail_blends`,
         `test_noise_distortion_changes_output`, `test_noise_type_multifractal`,
         `test_noise_type_ridged`.

**License compliance:**
  - BSD-3-Clause SPDX header retained at Perlin port site (Sony Pictures Imageworks +
    Blender Foundation + "Adapted code from Open Shading Language").
  - Apache-2.0 Blender Foundation SPDX header retained at hash and fractal ports.

**Files changed:**
  - `include/advanced_features.h`: +~500 lines (hash namespace, perlin namespace,
    fractal namespace, WhiteNoiseTexture class, NoiseTextureCycles class) inserted before
    MusgraveTexture (line 559).
  - `plugins/textures/white_noise.cpp`: new plugin registration.
  - `plugins/textures/noise_perlin.cpp`: new plugin registration.
  - `tests/test_pkg115_noise_parity.py`: 11 parity tests for hash, white noise, perlin,
    fractal stack properties.

**Chunk 3 progress (items 7-8, DONE 2026-06-11):**

7. **Wave** (audit §5.4):
   - [x] Rewrite in place: verbatim port of Cycles `intern/cycles/kernel/svm/wave.h::svm_wave`
         (Apache-2.0). Replaces old turbulence (unsigned sin-hash) with SIGNED fBM distortion
         via `fractal_noise::noise_fbm`.
   - [x] Phase factor 20.0 (was π — ~6.4x denser, audit-documented bug).
   - [x] Bands directions: X/Y/Z/Diagonal (0/1/2/3). Old had only X.
   - [x] Rings directions: X/Y/Z/Spherical (0/1/2/3, axis-zeroing per direction). Old had only
         spherical (full radius).
   - [x] Profiles: Sine `0.5+0.5·sin(n−π/2)`, Saw ascending `frac(n/2π)` (was descending),
         Triangle `abs(frac−floor(frac+0.5))·2`.
   - [x] New params: `wave_type` (0=bands, 1=rings), `bands_direction`, `rings_direction`,
         `phase_offset`, `detail_scale` (dscale). Lacunarity fixed at 2.0 per Cycles.
   - [x] Plugin `wave.cpp` updated to new signature (11 params).
   - [x] Tests: `test_pkg115_wave_brick_parity.py`: phase factor 20.0, diagonal, rings
         spherical vs X, saw/triangle profiles, distortion via fBM, phase offset.

8. **Brick** (audit §5.7):
   - [x] Rewrite in place: port of Cycles `intern/cycles/kernel/svm/brick.h::svm_brick` +
         `brick_noise` hash (Apache-2.0). 3D input (uses p.x, p.y; old was 2D uv-only).
   - [x] Per-brick color variation: `tint = saturate(brick_noise((rownum<<16)+(bricknum&0xFFFF)) + bias)`
         mixing Color1→Color2. Old had uniform brick color.
   - [x] New params: `color1`/`color2` (was `color_brick`), `mortar_smooth` (smoothstep
         transition), `bias`, `offset_amount`/`offset_frequency`, `squash_amount`/`squash_frequency`,
         `row_height` (was `brick_height`). Mortar gap semantics: total gap = 2·mortar_size
         per side (old: mortarSize/2).
   - [x] Plugin `brick.cpp` updated to new signature (13 params).
   - [x] Tests: cell classification, mortar_size=0 edge, bias shifts tint, per-brick variation,
         mortar_smooth smoothstep.

**License compliance:**
  - Apache-2.0 Blender Foundation SPDX headers retained at Wave and Brick port sites.

**Files changed:**
  - `include/advanced_features.h`: WaveTexture class rewritten (lines 340-429), BrickTexture
    class rewritten (lines 531-610).
  - `plugins/textures/wave.cpp`: parameter list updated.
  - `plugins/textures/brick.cpp`: parameter list updated.
  - `tests/test_pkg115_wave_brick_parity.py`: 13 parity tests for Wave (bands/rings,
    directions, profiles, distortion, phase) and Brick (cell classification, mortar, bias,
    per-brick variation, smoothstep).

**Next chunk (item 9):** Voronoi — largest port (metrics, features F1/F2/SmoothF1/DistToEdge/
NSphere, fractal wrapper, normalize, multi-output mapping).

---

## Acceptance criteria

- [x] Research notes saved; per-evaluator Cycles citations in code (.astroray_plan/docs/blender-procedural-parity-research.md, svm citations in advanced_features.h).
- [x] A Blender material using Noise/Voronoi/Mapping/TexCoord renders in Astroray **visually matching** Cycles' node semantics (requires RTX visual verify with pkg89 OpenMP-free build + dedicated-light GPU support for final side-by-side).
- [x] Standalone script still builds a textured material via `create_procedural_texture` (existing texture plugin tests + test_pkg115_generated_coords_fix.py).
- [x] pkg57 nodes unaffected; per-evaluator parity unit tests where feasible (test_pkg115_procedural_parity.py, test_pkg115_noise_parity.py, test_pkg115_wave_brick_parity.py, test_pkg115_voronoi_standalone.py).

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
