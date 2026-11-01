"""pkg307 Phase 2 -- builds the three spectral arbitration scenes (runs INSIDE Blender 5.2).

    blender -b --factory-startup --python build_arbitration.py -- [--out-dir <dir>]

Scenes (geometry, materials, lamps, cameras: ``mitsuba_scenes.PARAMS``, shared with the Mitsuba scenes so the three
engines render one definition):

* ``arb_prism_sun``         SF11 prism under a 4 degree sun on a diffuse floor (dispersive floor caustic).
* ``arb_chromatic_medium``  chromatic homogeneous medium cube (sigma_s = density x colour) under a rectangle lamp.
* ``arb_narrowband_wall``   sodium-vapour (narrow-band) rectangle lamp on a coloured diffuse wall.

Settings: box pixel filter 1 px, clamps off, filter glossy off, adaptive and denoise off, Standard view. Writes
``scenes/<id>.blend`` and ``manifest.json`` in the corpus manifest schema, so ``render_leg.py --corpus-manifest`` and
``mc_tolerance.py --suite arbitration`` consume them unchanged. Needs the Astroray addon (ASTRORAY_PYD_DIR) for the
Sellmeier node and the spectral-lamp properties. Cycles has no dispersion and no narrow-band lamps: on those scenes
its RGB render is a labelled "RGB reference limit", not a target.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path[:0] = [str(HERE), str(REPO / "benchmarks" / "reference_corpus"), str(REPO / "benchmarks" / "blender_parity")]

import mitsuba_scenes as ms  # pure python: no mitsuba import at module level

# (name, world point, half-width as a fraction of image width): projected through the scene camera.
ROIS = {
    # prism_sun_glint (was floor_caustic, #1025): the camera sees the prism there, and 97 % of the ROI is the sun after a
    # TIR off the prism base. The floor_* beams are the floor caustics (oracle path signatures): rainbow = refraction
    # T T, tir_beam = T r T (TIR), reflection_beam = T r T + external reflection R.
    "arb_prism_sun": [("prism_sun_glint", (-1.2, 1.4, 0.0), 0.04), ("floor_prism_shadow", (1.9, -0.35, 0.0), 0.04),
                      ("prism_body", (-0.4, 0.3, 0.65), 0.03), ("floor_far", (0.5, 2.6, 0.0), 0.05),
                      ("floor_rainbow", (0.35, 1.8, 0.0), 0.02), ("floor_tir_beam", (-2.0, -0.05, 0.0), 0.02),
                      ("floor_reflection_beam", (0.55, -1.1, 0.0), 0.02)],
    "arb_chromatic_medium": [("floor_direct", (2.0, -0.5, 0.0), 0.05), ("medium_core", (0.0, 0.0, 0.8), 0.04),
                             ("medium_edge", (-0.55, -0.7, 1.2), 0.03), ("floor_under_medium", (0.0, 0.0, 0.0), 0.04),
                             ("floor_beside_medium", (-1.4, 0.2, 0.0), 0.04)],
    "arb_narrowband_wall": [("wall_near_lamp", (0.2, 2.0, 1.4), 0.04),
                            ("wall_centre", (-0.3, 2.0, 0.8), 0.05), ("wall_far", (-2.2, 2.0, 0.8), 0.05),
                            ("floor_lit", (0.4, 1.2, 0.0), 0.05)],
    # pkg327 chroma proxies. Bowl points are on the sphere (centre (0, 0, 0.85), r 0.9) at latitude +10 / -10 / -30 deg on the far inside
    # (the cap ends at latitude asin(0.35 / 0.9) = 22.9 deg).
    "arb_chroma_bowl": [("inner_far_upper", (0.0, 0.886, 1.006), 0.03), ("inner_far_mid", (0.0, 0.886, 0.694), 0.03),
                        ("inner_far_low", (0.0, 0.779, 0.400), 0.03)],
    "arb_chroma_warm": [("floor_open", (0.0, -1.2, 0.0), 0.05), ("floor_at_box", (0.0, -0.3, 0.0), 0.03),
                        ("box_front", (0.0, -0.1, 0.5), 0.05)],
    "arb_chroma_warm_sky": [("floor_open", (0.0, -1.2, 0.0), 0.05), ("floor_at_box", (0.0, -0.3, 0.0), 0.03),
                            ("box_front", (0.0, -0.1, 0.5), 0.05)],
    "arb_chroma_warm_hdri": [("floor_open", (0.0, -1.2, 0.0), 0.05), ("floor_at_box", (0.0, -0.3, 0.0), 0.03),
                             ("box_front", (0.0, -0.1, 0.5), 0.05)],
    "arb_chroma_patches": [(name, (cx, 0.0, 0.0), 0.025) for name, cx, _ in ms.PARAMS["arb_chroma_patches"]["patches"]],
    **{sid: [(name, ms.hero_point(ms.PARAMS[sid]["hero"], dx, dz), 0.03) for name, (dx, dz) in ms.PARAMS[sid]["hero"]["rois"].items()]
       for sid in ms.PARAMS if "hero" in ms.PARAMS[sid]},
    # the production curves ROIs (build_corpus._prod_curves_geometry): the same world points, on the smooth bowl
    "arb_chroma_bowl_stage": [("inner_backface", (0.0, 0.75, 0.9), 0.04), ("outer_front", (0.0, -0.9, 0.55), 0.035)],
}


def _diffuse(sl, bpy, name, rgb):
    mat, nt, out = sl._bare_material(bpy, name)
    d = nt.nodes.new("ShaderNodeBsdfDiffuse")
    sl._sock(d.inputs, "Color").default_value = (*rgb, 1.0)
    sl._sock(d.inputs, "Roughness").default_value = 0.0
    nt.links.new(d.outputs[0], sl._sock(out.inputs, "Surface"))
    return mat


def build_scene(sid: str, bc, sc, sl, bpy, draft: bool = False):
    """One arbitration scene in the current Blender session -> (scene, crops)."""
    p = ms.PARAMS[sid]
    scene = sc._reset()
    sc._render_defaults(scene, samples=64, max_bounces=p["max_depth"])
    bc._v2_finish(scene, ms.RES)
    scene.cycles.pixel_filter_type = "BOX"
    scene.cycles.filter_width = 1.0
    world = sc._world(p.get("world", (0.03, 0.03, 0.03) if "hdri" in p else (0.0, 0.0, 0.0)), 1.0 if "world" in p else 0.0)
    if "hdri" in p:  # as build_corpus._prod_stage: Environment Texture -> Background, strength from PARAMS
        env = world.node_tree.nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(str(REPO / p["hdri"]["path"]))
        bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
        bg.inputs["Strength"].default_value = p["hdri"]["strength"]
        world.node_tree.links.new(env.outputs["Color"], bg.inputs["Color"])
    floor = (sc._box("Floor", (0.0, 0.0, -0.05), (20.0, 20.0, 0.1), _diffuse(sl, bpy, "FloorMat", p["floor_albedo"]))
             if p["floor_albedo"] is not None else None)
    cam = p["camera"]
    if sid == "arb_prism_sun":
        pr, s = p["prism"], p["sun"]
        sc._caustic_flags(floor, receiver=True)
        sun = sc._light("Sun", "SUN", (0.0, 0.0, 0.0), ms.sun_direction(s), s["strength"], color=s["color"],
                        angle=math.radians(s["angle_deg"]))
        sun.data.cycles.is_caustics_light = True
        prism = sc._prism("Prism", pr["loc"], pr["side"], pr["length"], math.radians(pr["rot_z_deg"]))
        sc._assign(prism, sc._dispersive_glass("SF11Prism", pr["ior_d"], "flint_sf11"))
        sc._caustic_flags(prism, caster=True)
    elif sid == "arb_chromatic_medium":
        c, lp = p["cube"], p["lamp"]
        scene.cycles.volume_bounces = 4
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=c["center"])
        cube = bpy.context.active_object
        cube.name = "Medium"
        cube.scale = (c["size"],) * 3
        mat = sl._principled_volume_material(bpy, "ChromaticMedium", density=c["density"], color=c["color"],
                                             anisotropy=c["anisotropy"])
        pv = next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeVolumePrincipled")
        sl._sock(pv.inputs, "Absorption Color").default_value = (0.0, 0.0, 0.0, 1.0)  # explicit: Color is then the scattering albedo
        cube.data.materials.append(mat)
        sc._light("Lamp", "AREA", lp["loc"], lp["target"], lp["power_w"], color=lp["color"], shape="SQUARE", size=lp["size"])
    elif sid in ms.CHROMA_SCENES:
        if "bowl" in p:  # the facets Mitsuba loads from the OBJ (ms.write_bowl_obj), built here from the same triangle list
            tris = ms.bowl_triangles(p["bowl"])
            me = bpy.data.meshes.new("Bowl")
            me.from_pydata([v for t in tris for v in t], [], [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(tris))])
            me.update()
            obj = bpy.data.objects.new("Bowl", me)
            scene.collection.objects.link(obj)
            sc._assign(obj, _diffuse(sl, bpy, "BowlMat", p["bowl"]["albedo"]))
        for name, cx, albedo in p.get("patches", ()):
            sc._box(f"Patch_{name}", (cx, 0.0, -0.05), (1.0, 1.0, 0.1), _diffuse(sl, bpy, f"Patch_{name}", albedo))
        if "stage" in p:  # build_corpus._prod_stage lamps
            st = p["stage"]
            sc._light("Sun", "SUN", (0.0, 0.0, 0.0), ms.sun_direction(st["sun"]), st["sun"]["strength"], color=st["sun"]["color"],
                      angle=math.radians(st["sun"]["angle_deg"]))
            lp = st["lamp"]
            sc._light("Area", "AREA", lp["loc"], lp["target"], lp["power_w"], color=lp["color"], shape="SQUARE", size=lp["size"])
        if "hero" in p:
            h = p["hero"]
            sc._assign(sc._uv_sphere("Hero", h["center"], h["radius"], seg=96, rings=48), _diffuse(sl, bpy, "HeroMat", h["albedo"]))
        if "box" in p:
            b = p["box"]
            sc._box("Occluder", b["center"], b["dims"], _diffuse(sl, bpy, "OccluderMat", b["albedo"]))
    else:
        lp = p["lamp"]
        wy = p["wall_y"]
        sc._box("Wall", (0.0, wy + 0.05, 2.0), (20.0, 0.1, 6.0), _diffuse(sl, bpy, "WallMat", p["wall_albedo"]))
        lamp = sc._light("Lamp", "AREA", lp["loc"], lp["target"], lp["power_w"], color=lp["color"], shape="SQUARE", size=lp["size"])
        lamp.data.custom_raytracer.spectrum_mode = "preset"
        lamp.data.custom_raytracer.preset_profile = lp["profile"]
    sc._camera(cam["loc"], cam["target"], lens=cam["lens"])
    r = bc._Rois(scene)
    crops = {}
    for name, pt, hw in ROIS[sid]:
        r.items = {name: (tuple(pt), hw)}
        try:
            crops.update(r.project())
        except SystemExit as exc:  # off-frame ROI: fatal unless drafting the camera/ROI layout
            if not draft:
                raise
            print(f"[pkg307-draft] {exc}", flush=True)
    return scene, crops


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(HERE))
    ap.add_argument("--scenes", nargs="+", default=None, choices=ms.SCENES,
                    help="build only these scenes and merge them into the existing manifest (default: all, rewriting it)")
    ap.add_argument("--draft", action="store_true", help="tolerate off-frame ROIs while laying out cameras (never commit a draft)")
    a = ap.parse_args(argv)
    import bpy
    import build_corpus as bc
    import render_leg
    render_leg._bootstrap_astroray_addon(REPO)
    print(f"[pkg307] sodium_vapor SPD: {len(ms.sodium_spd())} samples cached for the Mitsuba lamp", flush=True)
    sc = bc._load_showcase(None)
    import scene_library as sl
    out = Path(a.out_dir)
    (out / "scenes").mkdir(parents=True, exist_ok=True)
    mpath = out / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if a.scenes and mpath.is_file() else {"scenes": {}}
    for sid in (a.scenes or ms.SCENES):
        _, crops = build_scene(sid, bc, sc, sl, bpy, a.draft)
        blend = out / "scenes" / f"{sid}.blend"
        for img in bpy.data.images:  # a saved scene must not bake this checkout's absolute HDRI path
            if img.source == "FILE" and not img.filepath.startswith("//"):
                img.filepath = bpy.path.relpath(img.filepath, start=str(blend.parent))
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))
        manifest["scenes"][sid] = {
            "family": sid, "builder_fn": "build_scene",
            "blend_path": (blend.resolve().relative_to(REPO).as_posix() if blend.resolve().is_relative_to(REPO)
                           else blend.resolve().as_posix()),
            "sha256": hashlib.sha256(blend.read_bytes()).hexdigest(),
            "settings": {"res_x": ms.RES[0], "res_y": ms.RES[1], "samples": 64, "saved_default_engine": "CYCLES"},
            "v2": {"seed": 278, "spp_gate": 64, "spp_reference": 16384, "render_gate": sid not in ms.CHROMA_SCENES, "cameras": ["Cam"],
                   "blender_version": bpy.app.version_string, "doc": ms.PARAMS[sid]["doc"],
                   "anchor": ms.PARAMS[sid]["anchor"], "divergence": {}},
            "assets": ([{"path": ms.PARAMS[sid]["hdri"]["path"], "license": "CC0 1.0", "source_url": "https://polyhaven.com/a/syferfontein_18d_clear",
                         "sha256": hashlib.sha256((REPO / ms.PARAMS[sid]["hdri"]["path"]).read_bytes()).hexdigest()}]
                       if "hdri" in ms.PARAMS[sid] else []), "crops": crops}
        print(f"[pkg307] {sid}: {blend.name}, ROIs {list(crops)}", flush=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="\n")
    print("PKG307_BUILD PASS")


if __name__ == "__main__":
    main()
