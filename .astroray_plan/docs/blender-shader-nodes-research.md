# Blender Shader Nodes Research — Astroray pkg57

**Date:** 2026-05-10  
**Scope:** Third-party engine custom shader nodes targeting Blender 5.1 (manifest `blender_version_min = "5.1.0"`).  
**References fetched this session:**
- Blender source `source/blender/nodes/shader/node_shader_tree.cc` (GPL-2.0-or-later)
- Blender source `source/blender/render/RE_engine.h` (GPL-2.0-or-later)
- Cycles source `intern/cycles/blender/shader.cpp` (Apache-2.0)
- Cycles source `intern/cycles/blender/session.cpp` (Apache-2.0)
- Cycles Python addon `intern/cycles/blender/addon/properties.py` (Apache-2.0)
- Blender startup `scripts/startup/bl_ui/node_add_menu_shader.py` (GPL-2.0-or-later)
- BlendLuxCore `nodes/__init__.py`, `nodes/textures/__init__.py`, `operators/material.py`
  — **License: GPL-3.0**. Astroray is MIT. **Code mirroring disallowed.** Design
  patterns referenced at architecture level only; no code snippets reproduced.
- bpbrt4 (NicNel/bpbrt4) `pbrt.py`, `__init__.py` — **License: GPL-3.0-or-later**.
  Same restriction. Fetched for architecture-level reference only.
- Octane for Blender — proprietary. Only public docs reviewed; no source available.

---

## 1. Custom Node Base Class — ShaderNodeCustomGroup vs bpy.types.ShaderNode Subclass

### The two options

**`bpy.types.ShaderNodeCustomGroup`**  
Wraps an internal `node_tree` (a `ShaderNodeTree` group). The node acts as a
group node whose sub-tree is managed by the addon. Blender exposes the group's
sockets on the outer node automatically. Use cases: runtime-generated node trees
that represent complex procedural networks; nodes that must expose sockets from an
underlying group. Limitation: the group sub-tree must exist in `bpy.data.node_groups`
and can be accidentally modified by the user. There is no built-in UI panel —
`draw_buttons()` can be defined but operates alongside the group-tree interface
pins. Blender version compatibility: available since 2.8x; unchanged in 4.x/5.x.

**`bpy.types.ShaderNode` (direct subclass)**  
The standard approach for every Cycles built-in node (`ShaderNodeBsdfPrincipled`,
`ShaderNodeEmission`, etc.). Define `bl_idname`, `bl_label`, `bl_icon`; override
`init()` to create sockets, `draw_buttons()` for a UI panel on the node, and
`poll(cls, node_tree)` to restrict to the correct tree type and engine. The
node appears as a leaf node (no sub-tree), its properties are serialised as RNA
properties on the class, and its sockets are fully typed. No dependency on a
separate group node-tree in `bpy.data`.

### Recommendation for Astroray

**Use `bpy.types.ShaderNode` subclasses for all five Astroray nodes.** Reasons:

1. All Astroray nodes are conceptually leaf nodes that send data to the Astroray
   C++ core — they don't need or benefit from an internal group sub-tree.
2. `ShaderNodeCustomGroup` requires maintaining a companion node-tree in
   `bpy.data.node_groups`. This node-tree would appear in Blender's node editor
   "browse" dropdown and can confuse users. It also creates orphaned data blocks
   when materials are deleted.
3. The `ShaderNode` subclass pattern is the same used by Cycles for every
   production node since Blender 2.8. For Blender 5.1 targets this is fully
   stable and documented.

### Blender 5.1 compatibility notes

- `bpy.types.ShaderNode` subclass registration via `bpy.utils.register_class()`
  is unchanged through Blender 5.1.
- `nodeitems_utils` was deprecated in Blender 3.4 and is absent in 5.1. The
  replacement is `bpy.types.NODE_MT_add.append(draw_func)` — a menu append that
  inserts addon nodes into the Add menu. The draw function checks the engine and
  tree type and emits `layout.operator("node.add_node", text=...).type = bl_idname`.
- The node's `poll(cls, node_tree)` classmethod controls when the node can be
  created (display in the operator search list). Return `True` only when
  `bpy.context.scene.render.engine == 'ASTRORAY'`.

---

## 2. Engine-Switching Survival

When the user switches from Astroray to Cycles (or vice versa), three architectural
strategies exist for preserving Astroray-specific data.

### Option (a) — PointerProperty on the Material ID

Attach a `bpy.types.PropertyGroup` to `bpy.types.Material` using a
`PointerProperty`. This is exactly the pattern Cycles uses for all per-material
settings (`CyclesMaterialSettings` registered as `bpy.types.Material.cycles`,
Apache-2.0, `intern/cycles/blender/addon/properties.py`). The property group
is serialised with the `.blend` file regardless of which engine is active.
Astroray-specific node data (Sellmeier preset, spectral profile override at the
node level, NRC hint flag) can live here as typed properties with validators.

```python
# Pattern sourced from Cycles intern/cycles/blender/addon/properties.py (Apache-2.0)
class AstrorayMaterialSettings(bpy.types.PropertyGroup):
    sellmeier_preset: EnumProperty(items=SELLMEIER_PRESETS, ...)
    nrc_cache_hint:   BoolProperty(default=True, ...)

    @classmethod
    def register(cls):
        bpy.types.Material.astroray = PointerProperty(type=cls)

    @classmethod
    def unregister(cls):
        del bpy.types.Material.astroray
```

**Used by:** Cycles (Apache-2.0) in full; BlendLuxCore (GPL-3.0) in spirit —
BlendLuxCore stores `mat.luxcore` as a property group and maintains parallel node
trees (`mat.node_tree` for Cycles, `mat.luxcore.node_tree` for LuxCore). We
observe the design but cannot reproduce the code.

**Verdict:** Cleanest. Typed, validated, serialised, engine-agnostic. This is
already partially in place: `mat.custom_raytracer` exists in the addon for
scene-level settings; the per-material version follows the same structure.

### Option (b) — ID-property mirror on the Node

Store Astroray data directly on the node object as a Python dict-like
assignment (`node["astroray_B1"] = 0.696`). Blender serialises node ID-properties
with the `.blend` file. Advantage: no extra registration step. Disadvantage: no
type validation; properties appear as raw dicts in the node's "Custom Properties"
panel which confuses users; migration when property names change is manual.

**Used by:** None of the four reference projects. Observed in some older Blender
addons as a workaround; generally considered a hack.

**Verdict:** Rejected. Typing and discoverability are important for a physics-centric
renderer where coefficient values are meaningful numbers.

### Option (c) — Graceful degrade to a fallback Cycles node

Astroray nodes remain in the Blender node tree when the user switches to Cycles.
Cycles' `add_node()` in `shader.cpp` returns `nullptr` for unknown node types and
silently skips them (confirmed from source). The original `BsdfPrincipled` node,
which the user never removed, remains wired and Cycles renders it normally. The
Astroray nodes are inert objects in the tree — visible as grey boxes in Cycles but
producing no errors.

**Used by:** This is the implicit behaviour every third-party-node addon exhibits
when `RE_USE_SHADING_NODES_CUSTOM` is NOT set. Cycles confirms it in `shader.cpp`
(Apache-2.0). BlendLuxCore's architecture avoids it by using separate node trees,
but since Astroray layers on top non-destructively, it applies naturally.

**Verdict:** Works automatically; no explicit code needed. But alone it doesn't
solve the forward direction (Astroray reading back the correct parameters on
engine switch-back).

### Recommendation: (a) + (c) combined

Use option (a) as the primary per-material data store. Astroray-specific node
sockets write their values into `mat.astroray.*` properties when the user confirms
them (or via a `depsgraph_update_post` handler). When the engine switches back to
Astroray, the addon reads `mat.astroray.*` and the node sockets simultaneously,
preferring the socket value when the node is present, falling back to the material
property when it is absent (pkg37-era material with no Astroray nodes). Option (c)
ensures Cycles compatibility at zero cost.

This combined strategy is what `pkg57`'s existing "Non-destructive design point"
section already describes. The research confirms it is the correct choice and
the Cycles properties.py provides a directly mirrorable (Apache-2.0) template.

---

## 3. Per-Socket Typing for Astroray-Specific Data

### The two approaches

**`NodeSocketString` (built-in)**  
Use a string socket to pass a spectral profile name or a serialised triple like
`"0.696163,0.407943,0.897480"`. Simple, no registration, degrades gracefully.
Disadvantage: zero validation; the user can type arbitrary strings; no UI widget
beyond a text field; downstream code must parse and can silently mishandle malformed
input.

**`bpy.types.NodeSocket` subclass**  
Define a custom socket type with `bl_idname`, `bl_label`, a typed `default_value`
property, a `draw()` method for in-node UI, and a `draw_color()` method returning
an RGBA tuple for the socket wire colour. Survives serialisation. The socket's
`default_value` property is typed (e.g., `FloatVectorProperty(size=3)`) so
Blender validates it automatically.

Cycles itself uses **only built-in socket types** (`NodeSocketFloat`,
`NodeSocketColor`, `NodeSocketShader`, etc.) — there are no `NodeSocket` subclasses
in Cycles' Python addon. However, Cycles offloads the type complexity to C++
node definitions. For a Python-only addon defining new physics types, a custom
socket subclass is the appropriate level of abstraction.

### Concrete example: Sellmeier coefficient triple (B1, B2, B3)

The Sellmeier B-coefficient triple `(B1, B2, B3)` is a unit of physics data that
must travel together from the `AstrorayShaderNodeSellmeierGlass` output socket to
the `AstrorayOutputNode` surface socket. Encoding it as three separate float sockets
would require three wires in the node graph, which is visually noisy. Encoding it
as a string socket loses type safety.

Recommended: one `AstroraySellmeierSocket` custom socket carrying a
`FloatVectorProperty(size=3)` as its default value.

```python
# Astroray-owned code (MIT), pattern derived from Blender Python API docs.
class AstroraySellmeierSocket(bpy.types.NodeSocket):
    bl_idname = 'AstroraySellmeierSocketType'
    bl_label  = 'Sellmeier B Coefficients'

    default_value: bpy.props.FloatVectorProperty(
        name="B1 B2 B3",
        description="Sellmeier B coefficients (dimensionless)",
        size=3,
        default=(0.6962, 0.4080, 0.8975),   # Schott BK7 B-terms
        min=0.0, max=5.0,
        precision=4,
    )

    def draw(self, context, layout, node, text):
        if self.is_linked:
            layout.label(text=text)
        else:
            col = layout.column()
            col.prop(self, "default_value", text=text)

    def draw_color(self, context, node):
        return (0.9, 0.6, 0.1, 1.0)   # amber — distinct from standard shader sockets
```

The corresponding C-coefficient triple (C1, C2, C3, units µm²) follows the same
pattern: `AstroraySellmeierCSocket` with `FloatVectorProperty(size=3,
default=(0.0467914826, 0.013512063, 97.9340025))` (BK7 C-terms, see
Schott AG "Optical Glass Data Sheets", public domain glass data).

For **spectral profile names** (`AstrorayShaderNodeSpectralProfile`): use a
standard `NodeSocketString` for the output and a bespoke `EnumProperty` on the
node itself (populated from `astroray.spectral_profile_names()`) for the picker.
The string output socket is forwarded to `AstrorayOutputNode` and read by the
converter. This matches the pkg58 design.

For **IR/UV response curves**: a `NodeSocketString` carrying the profile name is
sufficient (same reasoning as spectral profiles).

---

## 4. Conversion Path — Reading the Node Tree via Depsgraph

### Cycles reference (Apache-2.0, `intern/cycles/blender/shader.cpp`)

Cycles' conversion is a C++ `add_node()` dispatch function. The entry point is
`add_nodes(scene, b_engine, b_data, b_scene, graph, b_ntree)` which iterates
`b_ntree.nodes` and calls `add_node()` per node. `add_node()` is a large
`switch`/`if-else` over `b_node.type` and `b_node.bl_idname`, constructing a
`ShaderNode *` for each known type and returning `nullptr` for unknowns (which
are then silently skipped). Socket defaults are read via
`b_sock.default_value_typed<bNodeSocketValueFloat>()`.

For material sync: `sync_materials()` in `session.cpp` iterates
`DEG_iterator_ids_begin` over all evaluated `ID_MA` objects in the depsgraph,
calling `shader_map.add_or_update()` per material to avoid redundant conversion.

### Astroray's existing path

`convert_node_material` at `blender_addon/__init__.py:1169` already follows
this dispatch pattern in Python:

1. Calls `mat.inline_shader_nodes()` (Blender 5.0+) to get a flattened tree with
   groups inlined and muted nodes stripped.
2. Finds the active `OUTPUT_MATERIAL` node.
3. Walks `output.inputs['Surface'].links[0].from_node` → `convert_shader_node()`.
4. `convert_shader_node()` dispatches on `node.type` / `node.bl_idname`.

### pkg57 extension

Add a pre-check at step 2: before looking for `OUTPUT_MATERIAL`, scan the flattened
node tree for any node whose `bl_idname` is `AstrorayOutputNode`. If found, treat
it as the output; its `Surface` input provides the Astroray BSDF chain. This is a
single loop over `node_tree.nodes` before the existing output-finding loop — no
architectural change to the existing path.

In `convert_shader_node()`, add `elif node.bl_idname == 'AstrorayShaderNodeXxx':`
branches, each delegating to a corresponding `_astroray_xxx_spec()` helper (same
pattern as `_principled_shader_spec()`). The helper reads node properties and
socket defaults directly from the node, maps them to Astroray renderer API calls,
and returns the material ID.

This mirrors the Cycles dispatch pattern faithfully and requires no changes to
the depsgraph iteration or the existing Cycles/Principled path.

### Depsgraph access in Python

The `render()` and `view_update()` methods already receive a `depsgraph` parameter.
`bpy.data.materials` (already used in `convert_materials()`) iterates all materials
in the file. No change to iteration strategy is needed.

---

## 5. Cycles Compatibility — BsdfPrincipled Scenes and pkg37's Path

### What pkg37 established

pkg37 (`blender_addon/__init__.py:1160–1167`) iterates `bpy.data.materials` and
calls `convert_node_material()` per material. The function:

1. Uses `mat.inline_shader_nodes()` to flatten node groups.
2. Finds `OUTPUT_MATERIAL`.
3. Dispatches `convert_shader_node()` → `_principled_shader_spec()` for
   `BSDF_PRINCIPLED` nodes.

This path is fully operational and tested.

### pkg57's non-destructive layering

When a material has only a `BsdfPrincipled` node (no Astroray nodes), the
`AstrorayOutputNode` pre-check returns no match, the existing path runs, and
rendering is identical to pre-pkg57 behaviour. No regression risk.

When a material has both a `BsdfPrincipled` and an `AstrorayOutputNode`, the
pre-check triggers the Astroray path. The BsdfPrincipled is ignored by Astroray
but remains wired in the node tree so Cycles can still use it.

### Known gaps to resolve in code

1. **`inline_shader_nodes()` + Astroray nodes**: If the user wires Astroray nodes
   into a group node, `inline_shader_nodes()` may or may not preserve unknown
   `bl_idname` nodes in the flattened tree (this depends on Blender's inliner
   implementation, which is new in 5.0). The safe rule is: **do not nest Astroray
   nodes inside group nodes** in v1.0. Document this limitation.

2. **`mat.astroray` property group initialisation**: The PointerProperty must be
   registered in `register()` before any `.blend` file is loaded. Otherwise, scenes
   opened without Astroray installed and then re-opened with it lose the custom
   properties. This is handled by the `register(cls)` / `unregister(cls)` pattern.

3. **Spectral profile fallback**: When `AstrorayShaderNodeSpectralProfile` is
   wired but no profile is selected (empty string), the converter must fall back
   to the `mat.custom_raytracer.spectral_profile` value (existing property from
   pkg58), not raise an error.

---

## 6. Open Questions

The following items could not be resolved from paper-level research and require
empirical testing or a Blender developer confirmation to pin down:

1. **`inline_shader_nodes()` unknown-node preservation**: Does Blender 5.1's
   `inline_shader_nodes()` preserve nodes with unknown `bl_idname` values (i.e.,
   our Astroray nodes) in the flattened tree, or does it strip them? If it strips
   them, pkg57 must operate on `mat.node_tree` directly instead, foregoing
   group-inlining for Astroray materials.

2. **Custom socket inter-node communication**: Can a custom `NodeSocket` subclass
   (`AstroraySellmeierSocket`) be used as a linked output→input pair between two
   addon nodes? The Blender Python API docs show `draw_color()` returning a wire
   colour, implying links are allowed. Needs a minimal live test to confirm wire
   type checking does not reject the link.

3. **`bl_use_shading_nodes_custom` interaction with `shader_tree_poll`**: The
   C++ source confirms `shader_tree_poll()` permits shader trees when
   `!BKE_scene_use_shading_nodes_custom(scene)`. If we never set
   `RE_USE_SHADING_NODES_CUSTOM`, this path is always open. Needs confirmation
   that Blender 5.1 did not change this gate.

4. **Node poll and the Shader Editor "Add" menu**: The `NODE_MT_add.append()`
   pattern is the documented approach since nodeitems_utils deprecation in 3.4.
   However, Blender 5.x may have additional menu layering from
   `node_add_menu_shader.py`'s `generate_menus()` call. Need to verify that
   `.append()` still works or whether the new `add_menus` dict must be extended
   instead. A minimal test addon that adds one node to the Add menu under Blender
   5.1 will resolve this in under an hour.

5. **AstrorayOutputNode vs OUTPUT_MATERIAL target field**: Blender's
   `OUTPUT_MATERIAL` node has a `target` enum (`ALL`, `CYCLES`, `EEVEE`) that
   controls which engine uses it. For `AstrorayOutputNode`, setting target to
   `ASTRORAY` would be ideal for visual clarity, but this requires either Blender
   core changes (not available) or is silently ignored. The practical approach is
   to use a plain `ShaderNode` subclass that does not derive from
   `ShaderNodeOutputMaterial`, and identify it purely by `bl_idname` in the
   converter — which is what Octane appears to do (doc-only observation;
   no source available).

6. **Parallel property group vs per-node data**: When a user manually types values
   into the `AstroraySellmeierSocket` default (no incoming wire), those values live
   on the node instance. When the engine switches to Cycles and back, the node
   remains in the tree with its socket values intact. The `mat.astroray` property
   group is therefore redundant for socket-hosted data. It is still needed for
   scene-level and material-level toggles (NRC hint, spectral profile name) that
   have no natural node home, and for the pkg37-era fallback path. Confirm during
   implementation that the two paths do not desync.

---

## Reference Commit SHAs and License Summary

| Source | License | SHA / note | Mirrorable? |
|---|---|---|---|
| `blender/blender` (node_shader_tree.cc, RE_engine.h, node_add_menu_shader.py) | GPL-2.0-or-later | `main` branch, fetched 2026-05-10 | API usage only; no code copy |
| `intern/cycles` (shader.cpp, session.cpp, properties.py) | Apache-2.0 | `main` branch, fetched 2026-05-10 | **Yes** — pattern + snippet mirroring allowed |
| `LuxCoreRender/BlendLuxCore` | **GPL-3.0** | `master` branch, fetched 2026-05-10 | **No** — Astroray is MIT; incompatible. Architecture reference only. |
| `NicNel/bpbrt4` | **GPL-3.0-or-later** | `main` branch, fetched 2026-05-10 | **No** — same restriction. Architecture reference only. |
| Octane for Blender | Proprietary | Public docs only | No source reviewed |
| Schott BK7 glass data | Public domain | Schott AG "Optical Glass Data Sheets" | Yes |
