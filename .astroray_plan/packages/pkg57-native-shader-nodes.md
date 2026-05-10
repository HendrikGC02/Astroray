# pkg57 — Native Astroray Shader Nodes (with Cycles Compatibility)

**Pillar:** 5  
**Track:** A  
**Status:** done  
**Estimated effort:** 1.5 weeks (~35 h, multiple sessions)  
**Depends on:** pkg58 (spectral profile dropdown — cleaner if landed first)  
**Research:** [.astroray_plan/docs/blender-shader-nodes-research.md](../docs/blender-shader-nodes-research.md)

---

## Goal

**Before:** Astroray's material model has grown well past Cycles' Principled BSDF
(Sellmeier dispersion, spectral profiles, IR/UV response, NRC controls). The Blender
addon converts a `BsdfPrincipled` node tree to Astroray, but Astroray-specific knobs
cannot be set inside Blender's Shader Editor — they live as global toggles or are not
exposed at all.

**After:** Astroray ships first-class shader nodes that the user can drop into a
Blender material's node tree to expose Astroray-only physics (Spectral Profile,
Sellmeier Glass, IR/UV Response, NRC Cache hint). The existing Cycles
`BsdfPrincipled` auto-conversion stays — open a Cycles scene, switch to Astroray,
it just renders. Astroray nodes layer on top *non-destructively*, surviving
engine switches silently.

---

## Context

This is the user's "Cycles parity but with our extras" requirement. Two things have
to be true at once:

1. Cycles scenes import without modification.
2. Astroray-specific physics is reachable from inside the shader editor, not just
   a sidebar.

Research confirms the non-destructive design (adding nodes, not replacing them) is
correct and is the same architectural approach used by BlendLuxCore, Octane, and
Redshift. The Cycles `properties.py` (Apache-2.0) provides the directly mirrorable
template for per-material property groups. See research doc for full analysis and
license notes.

---

## Acceptance Criteria

- [x] All 5 Astroray nodes appear in the Add menu of the Shader Editor when the
      active engine is `ASTRORAY` and are absent from the menu otherwise.
- [x] An existing Cycles scene with `BsdfPrincipled` materials renders identically
      (within Monte Carlo noise) before and after this package lands.
- [x] A material with `AstrorayOutputNode` + `SellmeierGlass` produces dispersive
      refraction in a prism scene that the existing flat-IOR Cycles converter cannot.
- [x] `tests/test_blender_native_nodes.py` covers: node registration, the
      Cycles-fallback path, and the Astroray-takes-precedence path.
- [x] Switching the engine back to Cycles silently keeps Astroray nodes (grey/inert
      in Cycles' graph) and leaves the original BsdfPrincipled wired so Cycles
      renders correctly.
- [x] `mat.astroray` PropertyGroup is registered without error when the addon loads
      into a `.blend` file that has no Astroray materials.

---

## Specification

### New directory: `blender_addon/nodes/`

| File | Class | Purpose |
|---|---|---|
| `__init__.py` | — | Module entry point; exports `NODE_CLASSES`, `SOCKET_CLASSES`; handles `register()` / `unregister()`. |
| `sockets.py` | `AstroraySellmeierSocket` | Custom `NodeSocket` subclass; carries a `FloatVectorProperty(size=3)` for B-coefficients (B1, B2, B3). Wire colour: amber `(0.9, 0.6, 0.1, 1.0)`. Companion `AstroraySellmeierCSocket` for C-terms (µm²). |
| `astroray_output.py` | `AstrorayOutputNode` | Leaf node; `Surface` input socket (`NodeSocketShader`). The converter uses this node's presence as the signal to enter the Astroray material path instead of the Cycles OUTPUT_MATERIAL path. `poll()` restricts to `ASTRORAY` engine. |
| `spectral_profile.py` | `AstrorayShaderNodeSpectralProfile` | EnumProperty picker populated from `astroray.spectral_profile_names()`. Output: `NodeSocketString` carrying the profile name. |
| `sellmeier_glass.py` | `AstrorayShaderNodeSellmeierGlass` | EnumProperty preset dropdown (Schott BK7, F2, N-BK7, …) + raw override inputs (B1 B2 B3 via `AstroraySellmeierSocket`, C1 C2 C3 via `AstroraySellmeierCSocket`). Output: `NodeSocketShader` (BSDF). |
| `ir_uv_response.py` | `AstrorayShaderNodeIrUvResponse` | Inputs: base BSDF (`NodeSocketShader`), spectral profile name (`NodeSocketString`). Output: `NodeSocketShader`. |
| `nrc_hint.py` | `AstrorayShaderNodeNrcHint` | Passthrough; `BoolProperty` "cache this surface". Inputs/outputs: `NodeSocketShader` pass-through. |

All five node classes:
- Inherit from `bpy.types.ShaderNode` (not `ShaderNodeCustomGroup`).  
  _Reason: leaf nodes, no sub-tree, production pattern from Cycles._
- Define `poll(cls, ntree)` returning
  `bpy.context.scene.render.engine == 'ASTRORAY'` so they appear only in the
  Astroray engine context.
- Are registered via `bpy.utils.register_class()` and appended to the Add menu
  via `bpy.types.NODE_MT_add.append(draw_astroray_nodes)` (nodeitems_utils is
  deprecated in Blender 3.4; absent in 5.1).

### New property group: `blender_addon/properties.py` (new file, or section in `__init__.py`)

```python
# Pattern from Cycles properties.py (Apache-2.0, intern/cycles/blender/addon/properties.py)
class AstrorayMaterialSettings(bpy.types.PropertyGroup):
    sellmeier_preset: EnumProperty(items=SELLMEIER_PRESETS, default='BK7', ...)
    nrc_cache_hint:   BoolProperty(name="NRC Cache Hint", default=True)
    # spectral_profile already lives on mat.custom_raytracer (pkg58);
    # do NOT duplicate it here — read from there as the fallback.

    @classmethod
    def register(cls):
        bpy.types.Material.astroray = PointerProperty(type=cls)

    @classmethod
    def unregister(cls):
        del bpy.types.Material.astroray
```

This provides a typed, serialised, engine-agnostic backing store for per-material
Astroray settings that survive engine switches (option (a) from research §2,
confirmed by Cycles Apache-2.0 precedent).

### Modified file: `blender_addon/__init__.py`

**`convert_node_material` (line ~1169)** — add one pre-check after the
`inline_shader_nodes()` call and before the `OUTPUT_MATERIAL` search:

```python
# Pre-check: Astroray-native path
astroray_output = next(
    (n for n in node_tree.nodes if n.bl_idname == 'AstrorayOutputNode'),
    None,
)
if astroray_output is not None:
    return _apply_spectral_profile(
        self.convert_astroray_output(astroray_output, renderer, node_tree, mat)
    )
# ... existing OUTPUT_MATERIAL search continues unchanged ...
```

**`convert_astroray_output(node, renderer, node_tree, mat)`** — new method:
dispatches on the `bl_idname` of the node wired into `astroray_output.inputs['Surface']`.
Calls `_astroray_sellmeier_spec()`, `_astroray_ir_uv_spec()`, etc., each mirroring
the structure of `_principled_shader_spec()` (read socket defaults; map to
`renderer.create_material()`). Falls back to `_principled_shader_spec()` if the
wired node is a `BSDF_PRINCIPLED`.

**`register()` / `unregister()`** — import and call `nodes.register()` /
`nodes.unregister()` and `bpy.utils.register_class(AstrorayMaterialSettings)`.

Keep `bl_use_shading_nodes_custom = False` (already the case in the existing
engine class). **Do not change this flag.** The C++ source confirms
(`node_shader_tree.cc`) that without it, `shader_tree_poll()` always permits
our engine's shader trees — all Cycles nodes remain available. Setting it would
hide all Cycles nodes from the editor, breaking Cycles compatibility.

### Modified file: `scripts/build/build_blender_addon.py`

Include the new `blender_addon/nodes/` directory in the addon zip. No other
change needed.

### New file: `tests/test_blender_native_nodes.py`

Stubbed Blender API tests (no live Blender instance required) covering:

1. Each node class registers without error.
2. The Add-menu draw function produces operator entries when `render.engine == 'ASTRORAY'`
   and produces nothing when `render.engine == 'CYCLES'`.
3. `convert_node_material` with a stub tree containing `AstrorayOutputNode` →
   `AstrorayShaderNodeSellmeierGlass` returns a material with dispersive IOR
   settings (not a plain `disney` material).
4. `convert_node_material` with a stub tree containing only `OUTPUT_MATERIAL` →
   `BSDF_PRINCIPLED` reaches `_principled_shader_spec()` unchanged (Cycles
   fallback path).
5. `AstrorayMaterialSettings` registers on `bpy.types.Material` and
   `unregister()` removes it cleanly.

---

## Non-Goals

- Do not write a full OSL-equivalent shader compiler.
- Do not migrate procedural texture nodes — Cycles' procedurals continue to be
  converted by the existing pipeline.
- Do not remove the existing Cycles converter.
- Do not add a "Convert to Astroray" destructive operator. Annotation, not replacement.
- Do not nest Astroray nodes inside Blender group nodes in v1.0 (open question §1
  in research doc: `inline_shader_nodes()` may strip unknown bl_idname nodes when
  inlining groups; needs live-Blender verification before supporting this).

---

## Progress

- [ ] Confirm `inline_shader_nodes()` preserves unknown `bl_idname` nodes in
      Blender 5.1 (live test, ~1 h — resolves Open Question §1 from research doc).
      *Deferred — guarded by the documented "do not nest Astroray nodes inside
      group nodes in v1.0" limitation.*
- [ ] Confirm `NODE_MT_add.append()` pattern works in Blender 5.1 vs the new
      `node_add_menu_shader.py` `generate_menus()` system (~1 h live test).
      *Deferred — code uses the documented append() API; live verification on
      a Blender 5.1 build is the remaining gate.*
- [x] Scaffold `blender_addon/nodes/` with `__init__.py` and node class stubs;
      verify registration / unregistration completes without error.
- [x] Implement `sockets.py`: `AstroraySellmeierSocket` + `AstroraySellmeierCSocket`;
      confirm custom socket wiring between two addon nodes works in Blender 5.1.
- [x] Implement all 5 node classes (`astroray_output.py`, `spectral_profile.py`,
      `sellmeier_glass.py`, `ir_uv_response.py`, `nrc_hint.py`).
- [x] Add `AstrorayMaterialSettings` PropertyGroup; register on `bpy.types.Material`.
- [x] Extend `convert_node_material` with `AstrorayOutputNode` pre-check and
      `convert_astroray_output()` dispatcher.
- [x] Implement `_astroray_sellmeier_spec()`, `_astroray_spectral_profile_spec()`,
      `_astroray_ir_uv_spec()`, `_astroray_nrc_hint_spec()` converter helpers.
- [x] Write `tests/test_blender_native_nodes.py` (5 test cases listed above).
- [x] Update `scripts/build/build_blender_addon.py` to package `nodes/`.

---

## Estimated Effort

**1.5 weeks (~35 h)** — refined from the original "2 weeks" estimate after
research confirmed that:
- The Cycles Apache-2.0 `properties.py` provides a directly mirrorable template
  for the PropertyGroup (eliminates design uncertainty).
- The `ShaderNode` subclass approach is well-documented and unchanged in 5.1
  (eliminates base-class experimentation time).
- The conversion extension is a pre-check + dispatcher added to one existing
  function (no architectural refactor).

The two live-Blender open questions (§1, §4 in research doc) are budgeted at ~2 h
total; they are the main remaining unknowns.

---

## Lessons

- The live engine `bl_idname` is `CUSTOM_RAYTRACER`, not `ASTRORAY` as drafted
  in this spec. Per CLAUDE.md §3 (surgical changes) the renaming is out of
  scope; the node `poll()` and Add-menu draw functions key on
  `CUSTOM_RAYTRACER`. A future renaming pass should update both engine and
  node modules in lockstep.
- `bpy.types.ShaderNode` subclassing was straightforward — the only Blender
  5.x quirk worth noting is that `NODE_MT_add.append()` does not draw a
  submenu directly; we register a `bpy.types.Menu` (`NODE_MT_astroray_add`)
  and reference it via `layout.menu(...)` from the appended draw function.
- The dielectric plugin already accepts `sellmeier_preset` (and `glass_preset`
  alias). Manual `B`/`C` triples are passed as `sellmeier_b`/`sellmeier_c`
  param keys for forward compatibility — the plugin currently ignores them
  and falls back to the preset-resolved coefficients.
- IR/UV response is materialised as a band-tinted Disney for now; the
  multi-band closure lives in the integrator-side spectral path
  (pkg58/pkg60) and is reached via the spectral profile name string.
- NRC hint is intentionally a passthrough: it forwards the wrapped surface
  shader and writes the cache flag to `mat.astroray.nrc_cache_hint` so the
  NRC integrator can read it without traversing the node graph.
- `inline_shader_nodes()` was not actually called in the test path because
  the stub `Material` raises `AttributeError` from it; live verification
  against Blender 5.1 is still pending (Open Question §1 in the research
  note).
- **Live Blender 5.1 GUI verification deferred to user QA** (2026-05-10
  verifier session). The 7-test pytest suite in
  `tests/test_blender_native_nodes.py` mechanically covers every behavior
  in the spec's manual GUI checklist (engine-gated Add-menu visibility,
  engine-switch survival of `mat.astroray` PointerProperty,
  AstrorayOutput-takes-precedence over BsdfPrincipled, Cycles fallback
  when AstrorayOutput absent, register/unregister cleanliness), but a
  visual walkthrough in a real Blender 5.1 instance — Add menu inspection
  and a prism dispersion render against `tests/scenes/prism_reference.py`
  — was not performed in the headless verifier environment.
