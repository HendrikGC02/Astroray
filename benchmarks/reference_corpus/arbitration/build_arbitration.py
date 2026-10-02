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
    "arb_prism_sun": [("floor_caustic", (-1.2, 1.4, 0.0), 0.04), ("floor_prism_shadow", (1.9, -0.35, 0.0), 0.04),
                      ("prism_body", (-0.4, 0.3, 0.65), 0.03), ("floor_far", (0.5, 2.6, 0.0), 0.05)],
    "arb_chromatic_medium": [("floor_direct", (2.0, -0.5, 0.0), 0.05), ("medium_core", (0.0, 0.0, 0.8), 0.04),
                             ("medium_edge", (-0.55, -0.7, 1.2), 0.03), ("floor_under_medium", (0.0, 0.0, 0.0), 0.04),
                             ("floor_beside_medium", (-1.4, 0.2, 0.0), 0.04)],
    "arb_narrowband_wall": [("wall_near_lamp", (0.2, 2.0, 1.4), 0.04),
                            ("wall_centre", (-0.3, 2.0, 0.8), 0.05), ("wall_far", (-2.2, 2.0, 0.8), 0.05),
                            ("floor_lit", (0.4, 1.2, 0.0), 0.05)],
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
    sc._world((0.0, 0.0, 0.0), 0.0)
    floor = sc._box("Floor", (0.0, 0.0, -0.05), (20.0, 20.0, 0.1), _diffuse(sl, bpy, "FloorMat", p["floor_albedo"]))
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
    manifest = {"scenes": {}}
    for sid in ms.SCENES:
        _, crops = build_scene(sid, bc, sc, sl, bpy, a.draft)
        blend = out / "scenes" / f"{sid}.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))
        manifest["scenes"][sid] = {
            "family": sid, "builder_fn": "build_scene",
            "blend_path": (blend.resolve().relative_to(REPO).as_posix() if blend.resolve().is_relative_to(REPO)
                           else blend.resolve().as_posix()),
            "sha256": hashlib.sha256(blend.read_bytes()).hexdigest(),
            "settings": {"res_x": ms.RES[0], "res_y": ms.RES[1], "samples": 64, "saved_default_engine": "CYCLES"},
            "v2": {"seed": 278, "spp_gate": 64, "spp_reference": 16384, "render_gate": True, "cameras": ["Cam"],
                   "blender_version": bpy.app.version_string, "doc": ms.PARAMS[sid]["doc"],
                   "anchor": ms.PARAMS[sid]["anchor"], "divergence": {}},
            "assets": [], "crops": crops}
        print(f"[pkg307] {sid}: {blend.name}, ROIs {list(crops)}", flush=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="\n")
    print("PKG307_BUILD PASS")


if __name__ == "__main__":
    main()
