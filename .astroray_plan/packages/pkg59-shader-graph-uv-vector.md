# pkg59 — Shader-Graph Vector / UV Plumbing

**Pillar:** 5
**Track:** A
**Status:** partial
**Estimated effort:** 1-2 sessions (~6 h)
**Depends on:** none

---

## Goal

**Before:** Image Texture and procedural texture nodes drive a material's albedo, but the converter ignores the `Vector` input — it always uses `mesh.uv_layers.active`. `Texture Coordinate` outputs (UV, Generated, Object) are dropped. `Mapping` nodes between coordinate sources and image textures are dropped. As a result, the default-cube + default-unwrap + default-Image-Texture node graph (the one in the user's screenshot) does not show the texture; non-default UV layers are unreachable; and PBR workflows that rely on UV scaling/offset via Mapping nodes produce wrong UVs.

**After:** The converter walks the `Vector` input chain on `TEX_IMAGE`, `TEX_NOISE`, `TEX_VORONOI`, `TEX_BRICK`, `TEX_GRADIENT`, `TEX_CHECKER`, `TEX_WAVE`, `TEX_MAGIC`, `TEX_MUSGRAVE`. Honors `Texture Coordinate.UV` (named UV layer), `Texture Coordinate.Generated`, and `Mapping(Location/Rotation/Scale)`. Adds a debug AOV that visualizes the UV that actually reaches the shader, so users can tell at a glance whether the issue is the unwrap or the wiring.

---

## Context

This is the texture / PBR bug from your screenshot. The black face is a separate issue (GPU env-light or shadow); the missing texture pattern is here. PBR production rendering is impossible without this. Cycles handles it via `ShaderManager::add_node` walking each node's vector input.

---

## Reference

- Current converter: [`load_blender_image`](blender_addon/__init__.py:1077), [`load_procedural_texture`](blender_addon/__init__.py:1125), [`get_base_color_texture`](blender_addon/__init__.py:1221).
- Texture sampling on the C++ side: `include/advanced_features.h` (CheckerTexture, ImageTexture, etc. — STATUS.md known-issue).
- Per-triangle UV upload: [`renderer.add_triangle(... uv0, uv1, uv2 ...)`](blender_addon/__init__.py:1737).

---

## Prerequisites

- [ ] Confirm what coordinate spaces the Astroray sampler supports today. Likely only "UV from active layer". This package adds: named UV layers, Generated, Object, plus Mapping transforms.
- [ ] Confirm whether the C++ side already supports per-texture UV transform (scale/offset/rotation). If not, add a `TextureTransform` struct or fold the transform into the sampler call site.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_blender_uv_plumbing.py` | UV-coverage tests on a cube with default unwrap + Image Texture, and on a sphere with named UV + Mapping(scale=2). |
| `tests/scenes/uv_debug.py` | Test scene that produces a known UV pattern on the default cube. |
| `plugins/passes/uv_debug_aov.cpp` | New AOV pass that writes the active UV as RG to the framebuffer. |

### Files to modify

| File | What changes |
|---|---|
| [blender_addon/__init__.py](blender_addon/__init__.py) | New `_resolve_vector_input(node, renderer)` that returns `(coord_space, uv_layer_name, transform)`. Plumb the result into `load_blender_image` and `load_procedural_texture`. Update `convert_objects` to upload all named UV layers (currently only the active one is uploaded). |
| `module/blender_module.cpp` | Add `add_triangle_with_uv_layers(...)` or extend `add_triangle` to take a list of named UV layers. |
| `include/advanced_features.h` (or wherever `ImageTexture` lives) | Take a `TextureTransform` (scale/offset/rotation) per sampling call site. |

### Key design decisions

1. **Named UV layers.** Cycles passes the layer name through. We do too. Default layer name is "UVMap".
2. **Generated coords = local-space position normalized into the object's bounding-box unit cube.** Cycles convention. Cheap to compute on the fly.
3. **Object coords = local-space position untransformed.** Useful for tri-planar mapping later; cheap.
4. **Mapping node = pre-multiplied 4x4 transform applied to the resulting (u,v,0) before sampling.** Avoid a full vector pipeline; pre-bake at convert time.
5. **Limit chain depth.** `_resolve_vector_input` walks at most 4 nodes deep; a deeper chain reports a fallback warning and uses defaults. We are not building a node graph evaluator here.
6. **UV debug AOV.** The fastest diagnostic for "is this a wiring bug or an unwrap bug" is to render the UVs as colors. Adds one ~30-line plugin.

---

## Acceptance criteria

- [x] Principled BSDF with Image Texture wired to Base Color routes to a textured material instead of a grey Disney fallback.
- [ ] Default cube + default unwrap + Image Texture (Vector ← Texture Coordinate.UV) renders with the texture visible on every face.
- [ ] A Mapping node with scale=2 between Texture Coordinate.UV and Image Texture doubles the texture frequency.
- [ ] A material that references a non-active UV layer by name renders correctly.
- [ ] `uv_debug` AOV (when enabled) writes a UV-as-color image that matches Blender's UV editor.
- [ ] Tests pass.

---

## Non-goals

- Do not implement Generated/Object/Camera/Window/Reflection coords beyond UV + Generated + Object. Camera/Window/Reflection can be a follow-up.
- Do not evaluate arbitrary vector-math node graphs. Mapping + direct Texture Coordinate is enough.
- Do not change the C++ texture sampling math beyond accepting a transform.

---

## Progress

- [x] Trace the screenshot's first failure: Image Texture → Principled Base Color was not reaching a textured material.
- [ ] Add `_resolve_vector_input` and the named-UV upload path.
- [ ] Add `TextureTransform` to the sampler call site.
- [ ] Implement Generated and Object coord spaces.
- [ ] Add the `uv_debug` AOV.
- [ ] Tests.

---

## Lessons

- PR #164 fixed the first production blocker by routing Image Texture →
  Principled Base Color into a textured Lambertian material and adding
  `tests/test_blender_principled_texture.py`.
- The package is still partial: named UV layers, Mapping transforms,
  Generated/Object coordinates, and the UV debug AOV remain open.
