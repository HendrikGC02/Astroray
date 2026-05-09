# pkg57 — Native Astroray Shader Nodes (with Cycles Compatibility)

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 2 weeks (~50 h, multiple sessions)
**Depends on:** pkg58 (spectral profile dropdown — cleaner if landed first)

---

## Goal

**Before:** Astroray's material model has grown well past Cycles' Principled BSDF (Sellmeier dispersion, spectral profiles, IR/UV response, NRC controls). The Blender addon converts a `BsdfPrincipled` node tree to Astroray, but Astroray-specific knobs cannot be set inside Blender's Shader Editor — they live as global toggles or are not exposed at all.

**After:** Astroray ships first-class shader nodes that the user can drop into a Blender material's node tree to expose Astroray-only physics (Spectral Profile, Sellmeier Glass, IR/UV Response, NRC Cache hint). The existing Cycles `BsdfPrincipled` auto-conversion stays — open a Cycles scene, switch to Astroray, it just renders. Astroray nodes layer on top *non-destructively*, stored as material custom-properties so a switch back to Cycles silently ignores them.

---

## Context

This is the user's "Cycles parity but with our extras" requirement. Two things have to be true at once:

1. Cycles scenes import without modification.
2. Astroray-specific physics is reachable from inside the shader editor, not just a sidebar.

The non-destructive design point (custom properties on `bpy.types.Material`, not replacement node trees) is what every commercial Blender renderer (LuxCore, Octane, Redshift) ended up doing. We follow the same pattern.

---

## Reference

- Current converter: [`convert_node_material`](blender_addon/__init__.py:610), [`_principled_shader_spec`](blender_addon/__init__.py:1261).
- Blender API: `bpy.types.NodeCustomGroup`, `bpy.types.NodeTreeInterface`, `RenderEngine.bl_use_shading_nodes_custom`.
- LuxCore reference (BSD): https://github.com/LuxCoreRender/BlendLuxCore — `BlendLuxCore/nodes/`.
- C++ side: [include/astroray/spectral_profile.h](include/astroray/spectral_profile.h), [include/astroray/optical_presets.h](include/astroray/optical_presets.h).

---

## Prerequisites

- [ ] pkg58 dropdown landed (so the spectral profile node has a populated picker).
- [ ] Confirm what set of Astroray-only physics actually needs node exposure. The current candidate list:
  - **Spectral Profile** — pick a profile name from `astroray.spectral_profile_names()`.
  - **Sellmeier Glass** — wavelength-dependent IOR via Sellmeier B/C coefficients (Schott BK7, F2, etc., from `optical_presets.h`).
  - **IR/UV Response** — extends a base BSDF with an IR/UV reflectance band.
  - **NRC Cache Hint** — per-material flag telling the neural cache integrator whether to cache this surface.
  - **Astroray Output** — companion to `OUTPUT_MATERIAL`; lets the addon detect "this material is Astroray-aware".

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `blender_addon/nodes/__init__.py` | Node module registration. |
| `blender_addon/nodes/astroray_output.py` | `AstrorayOutputNode` (companion to OUTPUT_MATERIAL). |
| `blender_addon/nodes/spectral_profile.py` | `AstrorayShaderNodeSpectralProfile` — dropdown picker; output socket = profile name (string-typed shader socket). |
| `blender_addon/nodes/sellmeier_glass.py` | `AstrorayShaderNodeSellmeierGlass` — preset dropdown + raw B/C inputs; outputs a BSDF socket. |
| `blender_addon/nodes/ir_uv_response.py` | `AstrorayShaderNodeIrUvResponse` — base BSDF input + spectral profile input. |
| `blender_addon/nodes/nrc_hint.py` | `AstrorayShaderNodeNrcHint` — passthrough with a "cache this" toggle. |
| `tests/test_blender_native_nodes.py` | Stubbed Blender API tests for node registration and conversion. |

### Files to modify

| File | What changes |
|---|---|
| [blender_addon/__init__.py](blender_addon/__init__.py) | Import and register the new node modules. Keep `bl_use_shading_nodes_custom = False` so Cycles nodes still render. Extend `convert_node_material` to recognize `AstrorayOutputNode` and the Astroray-specific BSDF nodes; when present, they take precedence over the Cycles output for Astroray's material spec. |
| `scripts/build/build_blender_addon.py` | Package the `nodes/` directory into the addon zip. |

### Key design decisions

1. **Cycles compat is non-negotiable.** Existing `BsdfPrincipled` materials must still render correctly after this lands. The new converter checks for an `AstrorayOutputNode` first, then falls back to the existing `OUTPUT_MATERIAL` path.
2. **No replacement of Cycles nodes.** We add nodes; we do not subclass or shadow Cycles ones.
3. **Custom properties for invisible knobs.** Per-material settings without a node home (e.g. NRC priority float) live on `material["astroray_*"]` custom properties.
4. **Don't enable `bl_use_shading_nodes_custom` yet.** That flag tells Blender to hide all Cycles nodes from the editor — exactly what we want to avoid. Stay in compat mode; add nodes via standard registration.
5. **String-typed sockets are fine.** Blender's NodeSocketString works for profile names. Don't invent a custom socket type.

---

## Acceptance criteria

- [ ] All 5 Astroray nodes appear in the Add menu of the Shader Editor when the active engine is Astroray.
- [ ] An existing Cycles scene with `BsdfPrincipled` materials renders identically (within Monte Carlo noise) before and after this package lands.
- [ ] A material with an `AstrorayOutputNode` + `Sellmeier Glass` produces dispersive refraction in a prism scene that the existing flat-IOR Cycles converter cannot.
- [ ] `tests/test_blender_native_nodes.py` covers node registration, the Cycles-fallback path, and the Astroray-takes-precedence path.
- [ ] Switching the engine back to Cycles silently keeps the Astroray nodes (they render as inert / passthrough) and leaves the original BsdfPrincipled wired so Cycles still works.

---

## Non-goals

- Do not write a full OSL-equivalent shader compiler.
- Do not migrate procedural texture nodes — Cycles' procedurals continue to be converted by the existing pipeline.
- Do not remove the existing Cycles converter.
- Do not add a "Convert to Astroray" destructive operator. Annotation, not replacement.

---

## Progress

- [ ] Decide final node list (lock down with project owner).
- [ ] Scaffold `blender_addon/nodes/` and registration plumbing.
- [ ] Implement Spectral Profile node + converter wiring.
- [ ] Implement Sellmeier Glass node + converter wiring.
- [ ] Implement IR/UV Response node + converter wiring.
- [ ] Implement NRC Hint node + converter wiring.
- [ ] Implement Astroray Output node + precedence logic.
- [ ] Tests.
- [ ] Update build script packaging.

---

## Lessons

*(Fill in after the package is done.)*
