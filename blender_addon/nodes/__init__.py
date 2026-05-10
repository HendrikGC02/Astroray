"""Astroray native shader nodes for the Blender Shader Editor (pkg57).

These five nodes expose Astroray-only physics (Sellmeier dispersion, spectral
profiles, IR/UV reflectance, NRC cache hints) inside the Shader Editor without
disturbing the existing Cycles → Astroray BsdfPrincipled auto-conversion path.
The non-destructive design is the same architectural approach used by
BlendLuxCore (GPL-3.0; pattern referenced only, no code mirrored) and Octane:
Astroray nodes layer on top of an existing Cycles tree; switching engines does
not delete or rewrite anything.

Pattern references
------------------
- `bpy.types.ShaderNode` subclassing — same as every Cycles built-in node
  (intern/cycles/blender/addon/properties.py et al., Apache-2.0).
- `PointerProperty` on `bpy.types.Material` for per-material settings —
  mirrors `CyclesMaterialSettings` registered as `bpy.types.Material.cycles`
  (intern/cycles/blender/addon/properties.py, Apache-2.0).
- `NODE_MT_add.append()` — current Blender (3.4+) replacement for the
  deprecated `nodeitems_utils` API.

Engine bl_idname is "CUSTOM_RAYTRACER" (the Astroray engine class registers
under that name; pkg57 spec wrote "ASTRORAY" but the live code uses
CUSTOM_RAYTRACER and we don't rename it as part of this package — see
CLAUDE.md §3 "surgical changes").
"""
from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    PointerProperty,
    StringProperty,
)


ENGINE_ID = "CUSTOM_RAYTRACER"


# --------------------------------------------------------------------------- #
# Spectral profile enum populated from the C++ side at draw time.
# --------------------------------------------------------------------------- #

def _spectral_profile_items(self, context):
    """Lazy enum populator. Mirrors blender_addon/__init__.py:_spectral_profile_items
    so the node-level dropdown matches the material-panel dropdown."""
    items = [("__none__", "<None>", "No spectral profile")]
    try:
        import astroray  # type: ignore
        if hasattr(astroray, "spectral_profile_names"):
            for n in astroray.spectral_profile_names():
                items.append((n, n, ""))
    except Exception:
        pass
    return items


# --------------------------------------------------------------------------- #
# Sellmeier preset enum — built from the C++ optical_presets table when
# available; static fallback list lets the dropdown render even before
# astroray.pyd has loaded (e.g. in unit tests).
# --------------------------------------------------------------------------- #

_SELLMEIER_FALLBACK_PRESETS = [
    ("bk7",          "Schott BK7",           "Borosilicate crown glass"),
    ("fused_silica", "Fused Silica",         "Pure SiO2"),
    ("flint_sf11",   "Schott SF11",          "Dense flint glass"),
    ("diamond",      "Diamond",              "Cubic carbon"),
]

def _sellmeier_preset_items(self, context):
    items = []
    try:
        import astroray  # type: ignore
        if hasattr(astroray, "optical_glass_preset_names"):
            for n in astroray.optical_glass_preset_names():
                items.append((n, n.replace("_", " ").title(), ""))
    except Exception:
        pass
    if not items:
        items = list(_SELLMEIER_FALLBACK_PRESETS)
    return items


# --------------------------------------------------------------------------- #
# Custom socket: Sellmeier coefficient triple (B1 B2 B3) and (C1 C2 C3).
# --------------------------------------------------------------------------- #

class AstroraySellmeierSocket(bpy.types.NodeSocket):
    """B-coefficient triple (dimensionless) for the Sellmeier IOR equation."""
    bl_idname = "AstroraySellmeierSocketType"
    bl_label = "Sellmeier B"

    # Schott BK7 B-terms — matches the C++ optical_presets.h default.
    default_value: FloatVectorProperty(
        name="B1 B2 B3",
        description="Sellmeier B coefficients (dimensionless)",
        size=3,
        default=(1.03961212, 0.231792344, 1.01046945),
        min=0.0, max=5.0,
        precision=6,
    )

    def draw(self, context, layout, node, text):
        if self.is_linked:
            layout.label(text=text)
        else:
            col = layout.column()
            col.prop(self, "default_value", text=text)

    def draw_color(self, context, node):
        return (0.9, 0.6, 0.1, 1.0)  # amber


class AstroraySellmeierCSocket(bpy.types.NodeSocket):
    """C-coefficient triple (units µm²) for the Sellmeier IOR equation."""
    bl_idname = "AstroraySellmeierCSocketType"
    bl_label = "Sellmeier C"

    # Schott BK7 C-terms (units µm²)
    default_value: FloatVectorProperty(
        name="C1 C2 C3",
        description="Sellmeier C coefficients (µm²)",
        size=3,
        default=(0.00600069867, 0.0200179144, 103.560653),
        min=0.0, max=200.0,
        precision=6,
    )

    def draw(self, context, layout, node, text):
        if self.is_linked:
            layout.label(text=text)
        else:
            col = layout.column()
            col.prop(self, "default_value", text=text)

    def draw_color(self, context, node):
        return (0.7, 0.45, 0.1, 1.0)  # darker amber


# --------------------------------------------------------------------------- #
# Mixin: poll() → engine gate. All Astroray nodes share this gate.
# --------------------------------------------------------------------------- #

class _AstrorayNodeBase:
    @classmethod
    def poll(cls, ntree):
        # Blender's shader-tree poll already restricts ntree.bl_idname.
        # We additionally require the active engine to be Astroray.
        try:
            return (bpy.context.scene.render.engine == ENGINE_ID
                    and ntree.bl_idname == "ShaderNodeTree")
        except (AttributeError, TypeError):
            return False


# --------------------------------------------------------------------------- #
# 1. AstrorayOutputNode — companion to OUTPUT_MATERIAL.
# --------------------------------------------------------------------------- #

class AstrorayOutputNode(_AstrorayNodeBase, bpy.types.ShaderNode):
    """Marks the entry point for the Astroray converter.

    Presence of an `AstrorayOutputNode` in the active material's node tree
    causes `convert_node_material` to take the Astroray path; the existing
    `OUTPUT_MATERIAL` node is left untouched so Cycles continues to render
    the same material correctly (option (a)+(c) from the research note).
    """
    bl_idname = "AstrorayOutputNode"
    bl_label = "Astroray Output"
    bl_icon = "NODE_MATERIAL"

    def init(self, context):
        self.inputs.new("NodeSocketShader", "Surface")
        self.inputs.new("NodeSocketShader", "Volume")


# --------------------------------------------------------------------------- #
# 2. AstrorayShaderNodeSpectralProfile — picks from spectral_profile_names().
# --------------------------------------------------------------------------- #

class AstrorayShaderNodeSpectralProfile(_AstrorayNodeBase, bpy.types.ShaderNode):
    bl_idname = "AstrorayShaderNodeSpectralProfile"
    bl_label = "Astroray Spectral Profile"
    bl_icon = "COLOR"

    profile: EnumProperty(
        name="Profile",
        description="Spectral reflectance profile from the Astroray DB",
        items=_spectral_profile_items,
    )

    def init(self, context):
        out = self.outputs.new("NodeSocketString", "Profile")
        out.default_value = ""

    def draw_buttons(self, context, layout):
        layout.prop(self, "profile", text="")


# --------------------------------------------------------------------------- #
# 3. AstrorayShaderNodeSellmeierGlass — dispersive IOR.
# --------------------------------------------------------------------------- #

class AstrorayShaderNodeSellmeierGlass(_AstrorayNodeBase, bpy.types.ShaderNode):
    bl_idname = "AstrorayShaderNodeSellmeierGlass"
    bl_label = "Astroray Sellmeier Glass"
    bl_icon = "MATSPHERE"

    preset: EnumProperty(
        name="Preset",
        description="Glass preset (Schott catalogue + common dispersive media)",
        items=_sellmeier_preset_items,
    )
    use_preset: BoolProperty(
        name="Use Preset",
        description="When on, the preset overrides the manual B/C inputs below",
        default=True,
    )
    ior_design: FloatProperty(
        name="IOR (design λ)",
        description="Refractive index at the design wavelength (587.6 nm, d-line)",
        min=1.0, max=3.5, default=1.5168,
    )

    def init(self, context):
        self.inputs.new("AstroraySellmeierSocketType", "Sellmeier B")
        self.inputs.new("AstroraySellmeierCSocketType", "Sellmeier C")
        self.inputs.new("NodeSocketColor", "Tint").default_value = (1.0, 1.0, 1.0, 1.0)
        self.outputs.new("NodeSocketShader", "BSDF")

    def draw_buttons(self, context, layout):
        col = layout.column(align=True)
        col.prop(self, "use_preset")
        if self.use_preset:
            col.prop(self, "preset", text="")
        else:
            col.prop(self, "ior_design")


# --------------------------------------------------------------------------- #
# 4. AstrorayShaderNodeIrUvResponse — extends a base BSDF with IR/UV band.
# --------------------------------------------------------------------------- #

class AstrorayShaderNodeIrUvResponse(_AstrorayNodeBase, bpy.types.ShaderNode):
    bl_idname = "AstrorayShaderNodeIrUvResponse"
    bl_label = "Astroray IR/UV Response"
    bl_icon = "OUTLINER_OB_LIGHTPROBE"

    band: EnumProperty(
        name="Band",
        items=[
            ("ir", "Near IR (700–1000 nm)", ""),
            ("uv", "Near UV (300–400 nm)", ""),
            ("both", "IR + UV", ""),
        ],
        default="ir",
    )
    reflectance: FloatProperty(
        name="Reflectance",
        description="Out-of-band reflectance (constant across the band)",
        min=0.0, max=1.0, default=0.5,
    )

    def init(self, context):
        self.inputs.new("NodeSocketShader", "Surface")
        self.inputs.new("NodeSocketString", "Profile")
        self.outputs.new("NodeSocketShader", "BSDF")

    def draw_buttons(self, context, layout):
        layout.prop(self, "band", text="")
        layout.prop(self, "reflectance")


# --------------------------------------------------------------------------- #
# 5. AstrorayShaderNodeNrcHint — per-material flag for the neural cache.
# --------------------------------------------------------------------------- #

class AstrorayShaderNodeNrcHint(_AstrorayNodeBase, bpy.types.ShaderNode):
    bl_idname = "AstrorayShaderNodeNrcHint"
    bl_label = "Astroray NRC Cache Hint"
    bl_icon = "MOD_HUE_SATURATION"

    cache_this: BoolProperty(
        name="Cache this surface",
        description="Suggest the Neural Radiance Cache integrator should query/store "
                    "outgoing radiance at this surface",
        default=True,
    )

    def init(self, context):
        self.inputs.new("NodeSocketShader", "Surface")
        self.outputs.new("NodeSocketShader", "BSDF")

    def draw_buttons(self, context, layout):
        layout.prop(self, "cache_this")


# --------------------------------------------------------------------------- #
# Per-material PropertyGroup. Pattern from
# intern/cycles/blender/addon/properties.py:CyclesMaterialSettings (Apache-2.0).
# --------------------------------------------------------------------------- #

class AstrorayMaterialSettings(bpy.types.PropertyGroup):
    """Engine-agnostic per-material settings.

    Survives engine switches because it lives on the `Material` ID, not on a
    node. Nodes can still hold authoritative values when present; the material
    settings act as the pkg37-era fallback for materials without Astroray nodes.
    """
    sellmeier_preset: EnumProperty(
        name="Sellmeier Preset",
        items=_sellmeier_preset_items,
    )
    nrc_cache_hint: BoolProperty(
        name="NRC Cache Hint",
        description="Default NRC cache hint when no AstrorayNrcHint node is wired",
        default=True,
    )
    # spectral_profile already lives on mat.custom_raytracer (pkg58); read from
    # there rather than duplicating it here.


# --------------------------------------------------------------------------- #
# Add-menu integration. NODE_MT_add.append() is the post-3.4 replacement for
# the deprecated nodeitems_utils API.
# --------------------------------------------------------------------------- #

_ASTRORAY_NODE_TYPES = [
    ("Astroray Output",          "AstrorayOutputNode"),
    ("Astroray Spectral Profile","AstrorayShaderNodeSpectralProfile"),
    ("Astroray Sellmeier Glass", "AstrorayShaderNodeSellmeierGlass"),
    ("Astroray IR/UV Response",  "AstrorayShaderNodeIrUvResponse"),
    ("Astroray NRC Cache Hint",  "AstrorayShaderNodeNrcHint"),
]


def draw_astroray_nodes(self, context):
    """Append an 'Astroray' submenu to the Shader-editor Add menu when the
    active engine is Astroray and we are inside a shader tree."""
    if context.scene.render.engine != ENGINE_ID:
        return
    space = getattr(context, "space_data", None)
    if space is None or getattr(space, "tree_type", None) != "ShaderNodeTree":
        return
    layout = self.layout
    layout.separator()
    sub = layout.menu("NODE_MT_astroray_add", text="Astroray")  # noqa: F841
    # Fallback inline draw for environments where the submenu class isn't
    # registered (extremely defensive — kept for testability):
    del sub


class NODE_MT_astroray_add(bpy.types.Menu):
    bl_idname = "NODE_MT_astroray_add"
    bl_label = "Astroray"

    def draw(self, context):
        layout = self.layout
        for label, bl_idname in _ASTRORAY_NODE_TYPES:
            op = layout.operator("node.add_node", text=label)
            op.type = bl_idname
            op.use_transform = True


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

SOCKET_CLASSES = (
    AstroraySellmeierSocket,
    AstroraySellmeierCSocket,
)

NODE_CLASSES = (
    AstrorayOutputNode,
    AstrorayShaderNodeSpectralProfile,
    AstrorayShaderNodeSellmeierGlass,
    AstrorayShaderNodeIrUvResponse,
    AstrorayShaderNodeNrcHint,
)

_ALL_CLASSES = (
    *SOCKET_CLASSES,
    *NODE_CLASSES,
    NODE_MT_astroray_add,
    AstrorayMaterialSettings,
)


def register():
    for cls in _ALL_CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Material.astroray = PointerProperty(type=AstrorayMaterialSettings)
    # Hook the Add menu. Wrapped in try/except because Blender 5.x menu
    # internals may change; failure here must not break the rest of the addon.
    try:
        bpy.types.NODE_MT_add.append(draw_astroray_nodes)
    except (AttributeError, RuntimeError) as exc:
        print(f"Astroray nodes: could not append to NODE_MT_add ({exc})")


def unregister():
    try:
        bpy.types.NODE_MT_add.remove(draw_astroray_nodes)
    except (AttributeError, RuntimeError, ValueError):
        pass
    if hasattr(bpy.types.Material, "astroray"):
        try:
            del bpy.types.Material.astroray
        except (AttributeError, RuntimeError):
            pass
    for cls in reversed(_ALL_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
