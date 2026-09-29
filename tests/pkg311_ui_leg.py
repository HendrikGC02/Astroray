"""pkg311 in-Blender leg: run by tests/test_pkg311_ui_conformance.py.

    blender --background --factory-startup --python tests/pkg311_ui_leg.py -- out.json

Registers the addon from the source tree (no engine .pyd needed: UI only),
exercises menus / panels / presets / node status lines through mock layouts,
and writes a JSON dict of results. Never imports outside Blender.
"""
import inspect
import json
import os
import re
import sys
import traceback
import types

import bpy

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[sys.argv.index("--") + 1]
sys.path.insert(0, REPO)

results = {}


def step(name):
    def deco(fn):
        try:
            results[name] = {"ok": True, "data": fn()}
        except Exception:
            results[name] = {"ok": False, "error": traceback.format_exc()}
        return fn
    return deco


class Rec:
    """Mock UILayout: records label/menu/operator/prop calls, nests for column()/row()."""
    def __init__(self, log=None):
        self.log = log if log is not None else []
        self.active = True
        self.enabled = True
        self.use_property_split = False
        self.use_property_decorate = False

    def _sub(self, *a, **k):
        return Rec(self.log)
    column = row = box = split = column_flow = grid_flow = _sub

    def label(self, text="", icon='NONE', **k):
        self.log.append(("label", text, icon))

    def menu(self, idname, text="", **k):
        self.log.append(("menu", idname, text))

    def prop(self, data, prop, **k):
        assert prop in data.bl_rna.properties, f"bad prop {prop}"
        self.log.append(("prop", prop))

    def operator(self, idname, text="", **k):
        op = types.SimpleNamespace()
        self.log.append(("operator", idname, text, op))
        return op

    def separator(self, *a, **k):
        pass

    def popover(self, *a, **k):
        self.log.append(("popover", k.get("panel")))

    def __getattr__(self, name):
        raise AttributeError(name)


sys.modules.pop("blender_addon", None)
import blender_addon as addon  # noqa: E402
from blender_addon import nodes as anodes  # noqa: E402

addon.register()
scene = bpy.context.scene
scene.render.engine = 'CUSTOM_RAYTRACER'


@step("engine_selected")
def _():
    return scene.render.engine


@step("property_descriptions")
def _():
    """Every property on every Astroray-registered RNA struct has a description."""
    structs = [c for c in addon.classes
               if isinstance(c, type) and issubclass(c, bpy.types.PropertyGroup)]
    structs.append(anodes.AstrorayMaterialSettings)
    missing, checked = [], 0
    for cls in structs:
        for p in cls.bl_rna.properties:
            if p.identifier == "rna_type":
                continue
            checked += 1
            if not p.description.strip():
                missing.append(f"{cls.__name__}.{p.identifier}")
    # Node classes: only properties the addon adds on top of bpy.types.ShaderNode.
    base = {p.identifier for p in bpy.types.ShaderNode.bl_rna.properties}
    for cls in anodes.NODE_CLASSES:
        for p in cls.bl_rna.properties:
            if p.identifier in base:
                continue
            checked += 1
            if not p.description.strip():
                missing.append(f"{cls.__name__}.{p.identifier}")
    prefs = addon.CustomRaytracerPreferences
    for p in prefs.bl_rna.properties:
        if p.identifier in ("rna_type", "bl_idname"):
            continue
        checked += 1
        if not p.description.strip():
            missing.append(f"{prefs.__name__}.{p.identifier}")
    return {"checked": checked, "missing": missing, "structs": len(structs)}


@step("add_menu_categories")
def _():
    log = []
    anodes.NODE_MT_astroray_add.draw(types.SimpleNamespace(layout=Rec(log)), None)
    top_ops = [e[3].type for e in log if e[0] == "operator"]
    menus = [(e[1], e[2]) for e in log if e[0] == "menu"]
    per_menu = {}
    for idname, _label in menus:
        mlog = []
        getattr(bpy.types, idname).draw(types.SimpleNamespace(layout=Rec(mlog)), None)
        per_menu[idname] = [e[3].type for e in mlog if e[0] == "operator"]
    all_types = top_ops + [t for v in per_menu.values() for t in v]
    tree = bpy.data.node_groups.new("pkg311_menu_check", 'ShaderNodeTree')
    unresolved = []
    for t in all_types:
        try:
            tree.nodes.new(t)
        except Exception:
            unresolved.append(t)
    return {"top_ops": top_ops, "menus": menus, "per_menu": per_menu,
            "unresolved": unresolved, "n_types": len(all_types),
            "n_registered_node_types": len(anodes.NODE_CLASSES)}


@step("black_hole_subpanels")
def _():
    bpy.ops.object.empty_add(type='SPHERE')
    obj = bpy.context.active_object
    ctx = types.SimpleNamespace(active_object=obj, scene=scene, object=obj)
    names = ["OBJECT_PT_astroray_black_hole"] + [
        f"OBJECT_PT_astroray_black_hole_{s}"
        for s in ("mass_spin", "disk", "adaf", "jet", "observer")]
    out = {}
    for model in ('NOVIKOV_THORNE', 'SLIM_DISK', 'ADAF'):
        obj.astroray_black_hole.accretion_model = model
        for n in names:
            cls = getattr(bpy.types, n)
            assert cls.poll(ctx), n
            log = []
            inst = types.SimpleNamespace(layout=Rec(log))
            if hasattr(cls, "draw_header"):
                cls.draw_header(inst, ctx)
            if hasattr(cls, "draw_header_preset"):
                cls.draw_header_preset(inst, ctx)
            cls.draw(inst, ctx)
            out.setdefault(n, {})[model] = [e[1] for e in log if e[0] == "prop"]
    parents = {n: getattr(bpy.types, n).bl_parent_id for n in names[1:]}
    # every BH property is drawn somewhere in the sub-panels (none silently lost)
    drawn = set()
    for per_model in out.values():
        for props in per_model.values():
            drawn.update(props)
    all_props = {p.identifier for p in addon.AstrorayBlackHoleProperties.bl_rna.properties
                 if p.identifier not in ("rna_type", "name")}
    return {"parents": parents, "not_drawn": sorted(all_props - drawn),
            "mass_spin_props": out[names[1]]['ADAF']}


@step("presets_round_trip")
def _():
    paths = bpy.utils.preset_paths("astroray_black_hole")
    files = sorted(f for d in paths for f in os.listdir(d) if f.endswith(".py"))
    expected = {
        "Sgr_A_star.py": dict(mass=4.297e6, accretion_model='ADAF', enable_jet=False),
        "M87_star.py": dict(mass=6.5e9, accretion_model='ADAF', enable_jet=True),
        "Stellar_mass_HMXB_Cyg_X-1.py": dict(mass=21.2, accretion_model='NOVIKOV_THORNE',
                                              enable_jet=False),
    }
    bpy.ops.object.empty_add(type='SPHERE')
    obj = bpy.context.active_object
    bpy.context.view_layer.objects.active = obj
    bh = obj.astroray_black_hole
    applied = {}
    for fname, want in expected.items():
        d = next(p for p in paths if os.path.exists(os.path.join(p, fname)))
        bh.mass, bh.enable_jet, bh.accretion_model = 1.0, not want["enable_jet"], 'SLIM_DISK'
        r = bpy.ops.script.execute_preset(
            filepath=os.path.join(d, fname),
            menu_idname="OBJECT_PT_astroray_black_hole_presets")
        applied[fname] = {"ret": sorted(r),
                          "got": {k: getattr(bh, k) for k in want},
                          "match": all(abs(getattr(bh, k) - v) < 1e-3 * abs(v)
                                       if isinstance(v, float) else getattr(bh, k) == v
                                       for k, v in want.items())}
    # Add-operator preset_values must all resolve on the live property group.
    op = bpy.types.ASTRORAY_OT_black_hole_preset_add
    unresolved = []
    for expr in op.preset_values:
        try:
            eval(expr, {"bh": bh})
        except Exception:
            unresolved.append(expr)
    # Render presets
    rpaths = bpy.utils.preset_paths("astroray_render")
    rfiles = sorted(f for d in rpaths for f in os.listdir(d) if f.endswith(".py"))
    rd = rpaths[0]
    bpy.ops.script.execute_preset(
        filepath=os.path.join(rd, "Draft.py"),
        menu_idname="RENDER_PT_custom_raytracer_sampling_presets")
    draft = (scene.cycles.samples, scene.cycles.preview_samples)
    bpy.ops.script.execute_preset(
        filepath=os.path.join(rd, "Final.py"),
        menu_idname="RENDER_PT_custom_raytracer_sampling_presets")
    final = (scene.cycles.samples, scene.cycles.preview_samples)
    rop = bpy.types.ASTRORAY_OT_sampling_preset_add
    runresolved = []
    for expr in rop.preset_values:
        try:
            eval(expr, {"cycles": scene.cycles, "settings": scene.custom_raytracer})
        except Exception:
            runresolved.append(expr)
    return {"bh_files": files, "applied": applied, "unresolved": unresolved,
            "render_files": rfiles, "draft": draft, "final": final,
            "render_unresolved": runresolved}


@step("node_status_line")
def _():
    mat = bpy.data.materials.new("pkg311")
    mat.use_nodes = True
    nt = mat.node_tree
    out = next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL')
    node = nt.nodes.new("AstrorayShaderNodeSellmeierGlass")

    def lines():
        log = []
        anodes._draw_native_status(node, Rec(log))
        return [(e[1], e[2]) for e in log if e[0] == "label"]

    res = {"unwired": lines()}
    nt.links.new(node.outputs[0], out.inputs['Surface'])
    res["wired"] = lines()
    # Behind a Mix Shader: converter would ignore it -> ERROR line.
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(node.outputs[0], mix.inputs[1])
    nt.links.new(mix.outputs[0], out.inputs['Surface'])
    res["behind_mix"] = lines()
    # Same answer as the converter's own dispatch set.
    src = inspect.getsource(
        addon.CustomRaytracerRenderEngine._convert_astroray_native_surface)
    res["converter_idnames"] = sorted(set(re.findall(r"AstrorayShaderNode\w+", src)))
    res["status_idnames"] = sorted(anodes.NATIVE_SURFACE_IDNAMES)
    # Behavioural: every native idname wired directly to Surface is "used",
    # under both a Material Output and an AstrorayOutputNode.
    direct = {}
    for idname in anodes.NATIVE_SURFACE_IDNAMES:
        for out_id in ("ShaderNodeOutputMaterial", "AstrorayOutputNode"):
            t2 = bpy.data.node_groups.new("pkg311_direct", 'ShaderNodeTree')
            o2 = t2.nodes.new(out_id)
            n2 = t2.nodes.new(idname)
            src = n2.outputs[0]
            t2.links.new(src, o2.inputs['Surface'])
            direct[f"{idname}/{out_id}"] = anodes.native_surface_status(n2)
    res["direct"] = direct
    # Every native surface node resolves a status without error. (draw_buttons
    # itself is C-typed to a real UILayout, so the mock drives the shared helper.)
    for idname in anodes.NATIVE_SURFACE_IDNAMES:
        anodes.native_surface_status(nt.nodes.new(idname))
    return res


@step("unregister_clean")
def _():
    addon.unregister()
    left = [n for n in dir(bpy.types)
            if n.startswith(("OBJECT_PT_astroray", "NODE_MT_astroray",
                             "RENDER_PT_custom_raytracer_sampling_presets"))]
    addon.register()  # re-register must also be clean
    addon.unregister()
    return {"left": left}


with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(results, fh, indent=1, default=str)
print("PKG311_LEG_DONE")
