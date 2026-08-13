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

import math

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

# pkg195 Stage C: default authoring range for drawn/baked spectra. The DB grid
# is 5 nm; drawn curves resample onto the same step so drawn and preset spectra
# behave identically downstream (design doc §3.4).
DRAWN_SPECTRUM_STEP_NM = 5.0

# Emission-category (category 7) lamp SPDs shipped in profiles.bin. The DB does
# not expose category in-memory, so the Spectrum Preset node filters names
# against this known set (mirrors blender_addon/__init__.py:_EMISSION_PROFILE_NAMES).
_EMISSION_PROFILE_NAMES = frozenset((
    'sodium_vapor', 'mercury_vapor',
    'cie_f2', 'cie_f3',
    'led_3000k', 'led_5000k', 'led_6500k',
))


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


def _spectrum_preset_items(self, context):
    """Two-tier Spectrum Preset dropdown: profiles filtered by the node's
    `category` (reflectance = DB categories 0-6, emission = category 7). Category
    is not exposed in-memory, so emission is filtered by the known name set."""
    want_emission = getattr(self, "category", "reflectance") == "emission"
    items = []
    try:
        import astroray  # type: ignore
        if hasattr(astroray, "spectral_profile_names"):
            for n in astroray.spectral_profile_names():
                is_emission = n in _EMISSION_PROFILE_NAMES
                if is_emission == want_emission:
                    items.append((n, n.replace("_", " ").title(), ""))
    except Exception:
        pass
    if not items:
        items = [("__none__", "<None>", "No matching preset in the profile DB")]
    return items


# --------------------------------------------------------------------------- #
# pkg195 Stage C: drawn-curve + blackbody spectrum sampling helpers. Both
# produce a regular-grid float array that astroray.register_spectral_profile
# consumes; drawn and preset spectra share the 5 nm DB grid so they behave
# identically downstream.
# --------------------------------------------------------------------------- #

def spectrum_grid(lmin: float, lmax: float, step: float = DRAWN_SPECTRUM_STEP_NM):
    """(count, clamped_lmin, clamped_lmax) for a regular grid; count >= 2."""
    lmin = float(lmin)
    lmax = float(lmax)
    if lmax < lmin:
        lmin, lmax = lmax, lmin
    if lmax - lmin < step:
        lmax = lmin + step
    count = round((lmax - lmin) / step) + 1
    return max(count, 2), lmin, lmax


def _drawn_curve_node(node):
    """Resolve the hidden ShaderNodeFloatCurve that stores this Drawn Spectrum
    node's CurveMapping, or None when unavailable (e.g. CI bpy stub)."""
    grp_name = getattr(node, "curve_group", "") or ""
    if not grp_name:
        return None
    groups = getattr(getattr(bpy, "data", None), "node_groups", None)
    if groups is None:
        return None
    grp = groups.get(grp_name)
    if grp is None:
        return None
    return grp.nodes.get("curve")


def sample_drawn_spectrum(node, step: float = DRAWN_SPECTRUM_STEP_NM):
    """Evaluate a Drawn Spectrum node's CurveMapping on its [λmin, λmax] grid.
    Returns (lambda_min_nm, step_nm, values) or None if the curve is missing.
    The curve's X input 0..1 maps linearly to [λmin, λmax]; Y is the value."""
    fc = _drawn_curve_node(node)
    if fc is None:
        return None
    mapping = getattr(fc, "mapping", None)
    if mapping is None:
        return None
    try:
        mapping.update()
    except Exception:
        pass
    try:
        curve = mapping.curves[0]
    except (IndexError, AttributeError):
        return None
    count, lmin, lmax = spectrum_grid(
        getattr(node, "lambda_min", 300.0), getattr(node, "lambda_max", 1000.0), step)
    span = lmax - lmin
    values = []
    for i in range(count):
        wl = lmin + i * step
        x = (wl - lmin) / span if span > 0.0 else 0.0
        try:
            y = float(mapping.evaluate(curve, x))
        except (AttributeError, TypeError):
            y = 0.0
        values.append(max(0.0, y))
    return lmin, step, values


# Planck's law (textbook; CLAUDE.md §6 trivial): spectral radiance shape only.
# Absolute scale is irrelevant — a MeasuredSPD is a *relative* SPD and the light
# energy slider carries magnitude. `normalize` peak-normalizes to max 1.0 for a
# stable relative curve (the engine's native blackbody light mode does the exact
# pkg122 photopic-luminance normalization; this node authors a relative SPD).
def _planck_radiance(lambda_nm: float, temperature_K: float) -> float:
    h = 6.62607015e-34
    c = 2.99792458e8
    kB = 1.380649e-23
    lam = lambda_nm * 1e-9
    if lam <= 0.0 or temperature_K <= 0.0:
        return 0.0
    x = (h * c) / (lam * kB * temperature_K)
    if x > 700.0:  # avoid overflow in exp; radiance ~ 0 here
        return 0.0
    return (2.0 * h * c * c) / (lam ** 5 * (math.expm1(x)))


def bake_blackbody_spectrum(temperature_K: float, normalize: bool,
                            lmin: float = 300.0, lmax: float = 1000.0,
                            step: float = DRAWN_SPECTRUM_STEP_NM):
    """Bake a Planck SPD onto a regular grid. Returns (lambda_min_nm, step, values)."""
    count, lmin, lmax = spectrum_grid(lmin, lmax, step)
    values = [_planck_radiance(lmin + i * step, temperature_K) for i in range(count)]
    if normalize:
        peak = max(values) if values else 0.0
        if peak > 0.0:
            values = [v / peak for v in values]
    return lmin, step, values


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
# 6. AstrorayShaderNodeSpectrumPreset — two-tier preset dropdown source.
#    Replaces the bare Spectral Profile node as the source in new trees; the
#    old node stays registered for .blend compat (pkg195 Stage C item 3).
# --------------------------------------------------------------------------- #

class AstrorayShaderNodeSpectrumPreset(_AstrorayNodeBase, bpy.types.ShaderNode):
    bl_idname = "AstrorayShaderNodeSpectrumPreset"
    bl_label = "Astroray Spectrum Preset"
    bl_icon = "COLOR"

    category: EnumProperty(
        name="Category",
        description="Reflectance presets (materials) or emission presets (lamps)",
        items=[
            ("reflectance", "Reflectance", "Material reflectance spectra"),
            ("emission", "Emission", "Lamp / illuminant emission spectra"),
        ],
        default="reflectance",
    )
    profile: EnumProperty(
        name="Preset",
        description="Spectral profile from the Astroray DB, filtered by category",
        items=_spectrum_preset_items,
    )

    def init(self, context):
        self.outputs.new("NodeSocketShader", "BSDF")

    def draw_buttons(self, context, layout):
        layout.prop(self, "category", text="")
        layout.prop(self, "profile", text="")


# --------------------------------------------------------------------------- #
# 7. AstrorayShaderNodeDrawnSpectrum — the owner's headline ask: draw exactly
#    which wavelengths to emit/absorb via Blender's native CurveMapping widget
#    (hidden ShaderNodeFloatCurve in a private node group; design doc §3.4).
# --------------------------------------------------------------------------- #

class AstrorayShaderNodeDrawnSpectrum(_AstrorayNodeBase, bpy.types.ShaderNode):
    bl_idname = "AstrorayShaderNodeDrawnSpectrum"
    bl_label = "Astroray Drawn Spectrum"
    bl_icon = "FCURVE"

    lambda_min: FloatProperty(
        name="lambda min (nm)", description="Left edge of the drawn range",
        default=300.0, min=100.0, max=3000.0,
    )
    lambda_max: FloatProperty(
        name="lambda max (nm)", description="Right edge of the drawn range",
        default=1000.0, min=100.0, max=3000.0,
    )
    semantic: EnumProperty(
        name="Semantic",
        description="How the drawn curve is interpreted where it is wired",
        items=[
            ("reflectance", "Reflectance", "λ → reflectance [0,1] for a surface"),
            ("emission", "Emission", "λ → relative emission for a light"),
        ],
        default="reflectance",
    )
    # Name of the hidden node group holding the drawable CurveMapping. The .blend
    # stores the curve; the node stores only this reference.
    curve_group: StringProperty(default="")

    def _ensure_curve_group(self):
        groups = getattr(getattr(bpy, "data", None), "node_groups", None)
        if groups is None:
            return None
        grp = groups.get(self.curve_group) if self.curve_group else None
        if grp is None:
            grp = groups.new(name="_AstrorayDrawnSpectrum", type="ShaderNodeTree")
            try:
                grp.use_fake_user = True
            except AttributeError:
                pass
            fc = grp.nodes.new("ShaderNodeFloatCurve")
            fc.name = "curve"
            self.curve_group = grp.name
        return grp

    def init(self, context):
        self.outputs.new("NodeSocketShader", "BSDF")
        try:
            self._ensure_curve_group()
        except Exception:
            pass

    def copy(self, src_node):
        # A duplicated node must own an independent curve so edits don't alias
        # the original (memory id-node-cache-aliasing lesson: never share curve
        # state across nodes). Force a fresh group on copy.
        self.curve_group = ""
        try:
            self._ensure_curve_group()
        except Exception:
            pass

    def draw_buttons(self, context, layout):
        col = layout.column(align=True)
        col.prop(self, "semantic", text="")
        row = col.row(align=True)
        row.prop(self, "lambda_min")
        row.prop(self, "lambda_max")
        fc = _drawn_curve_node(self)
        if fc is not None and hasattr(layout, "template_curve_mapping"):
            layout.template_curve_mapping(fc, "mapping")
        else:
            layout.label(text="Draw λ → value curve (unavailable here)", icon="FCURVE")
        layout.operator("astroray.bake_spectrum_profile", icon="FILE_TICK")


# --------------------------------------------------------------------------- #
# 8. AstrorayShaderNodeBlackbodySpectrum — Planck emission source (Phase 1:
#    emission only; bakes a Planck SPD a light's Custom Profile mode can use).
# --------------------------------------------------------------------------- #

class AstrorayShaderNodeBlackbodySpectrum(_AstrorayNodeBase, bpy.types.ShaderNode):
    bl_idname = "AstrorayShaderNodeBlackbodySpectrum"
    bl_label = "Astroray Blackbody Spectrum"
    bl_icon = "LIGHT_SUN"

    temperature: FloatProperty(
        name="Temperature (K)", description="Blackbody temperature",
        default=6500.0, min=800.0, max=20000.0,
    )
    normalize: BoolProperty(
        name="Normalize (peak)",
        description="Peak-normalize the baked SPD to 1.0 (relative curve). The "
                    "engine's native blackbody light mode does exact photopic "
                    "normalization; this authors a relative emission SPD.",
        default=True,
    )

    def init(self, context):
        self.outputs.new("NodeSocketShader", "BSDF")

    def draw_buttons(self, context, layout):
        layout.prop(self, "temperature")
        layout.prop(self, "normalize")
        layout.operator("astroray.bake_spectrum_profile", icon="FILE_TICK")


# --------------------------------------------------------------------------- #
# Bake operator — registers the active Drawn/Blackbody node's spectrum as a
# runtime profile so a light's Custom Profile dropdown can reference it by name
# without a full render first (design doc §3.4 export-at-translation is the
# material path; this is the explicit bridge for the light-emission path).
# --------------------------------------------------------------------------- #

def drawn_spectrum_profile_name(node, owner_name: str = "node") -> str:
    """Stable __blend__/<owner>/<node> name for a source node's runtime profile."""
    return f"__blend__/{owner_name}/{getattr(node, 'name', 'spectrum')}"


class ASTRORAY_OT_bake_spectrum_profile(bpy.types.Operator):
    bl_idname = "astroray.bake_spectrum_profile"
    bl_label = "Bake to Profile"
    bl_description = ("Register this spectrum as a runtime Astroray profile so a "
                      "light's Custom Profile mode can use it by name")
    bl_options = {"REGISTER"}

    def execute(self, context):
        node = getattr(context, "active_node", None)
        if node is None:
            self.report({'ERROR'}, "No active node")
            return {'CANCELLED'}
        bl_idname = getattr(node, "bl_idname", "")
        if bl_idname == "AstrorayShaderNodeDrawnSpectrum":
            sampled = sample_drawn_spectrum(node)
        elif bl_idname == "AstrorayShaderNodeBlackbodySpectrum":
            sampled = bake_blackbody_spectrum(
                float(getattr(node, "temperature", 6500.0)),
                bool(getattr(node, "normalize", True)))
        else:
            self.report({'ERROR'}, "Active node is not a spectrum source")
            return {'CANCELLED'}
        if not sampled:
            self.report({'ERROR'}, "Could not evaluate the spectrum curve")
            return {'CANCELLED'}
        lmin, step, values = sampled
        try:
            import astroray  # type: ignore
        except ImportError:
            self.report({'ERROR'}, "astroray engine module not available")
            return {'CANCELLED'}
        owner = getattr(getattr(context, "material", None), "name", None) or "scene"
        name = drawn_spectrum_profile_name(node, owner)
        ok = bool(astroray.register_spectral_profile(name, lmin, step, list(values)))
        if not ok:
            self.report({'ERROR'}, "register_spectral_profile failed")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Registered spectral profile '{name}'")
        return {'FINISHED'}


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
    ("Astroray Spectrum Preset", "AstrorayShaderNodeSpectrumPreset"),
    ("Astroray Drawn Spectrum",  "AstrorayShaderNodeDrawnSpectrum"),
    ("Astroray Blackbody Spectrum", "AstrorayShaderNodeBlackbodySpectrum"),
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
    AstrorayShaderNodeSpectrumPreset,
    AstrorayShaderNodeDrawnSpectrum,
    AstrorayShaderNodeBlackbodySpectrum,
    AstrorayShaderNodeSellmeierGlass,
    AstrorayShaderNodeIrUvResponse,
    AstrorayShaderNodeNrcHint,
)

_ALL_CLASSES = (
    *SOCKET_CLASSES,
    *NODE_CLASSES,
    ASTRORAY_OT_bake_spectrum_profile,
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
