# -*- coding: utf-8 -*-
"""pkg324 - spectral showcase corpus v1: scene builder (runs INSIDE Blender 5.2).

Builds the procedural scenes from code (deterministic: fixed seeds, no
randomness beyond a seeded ``random.Random``) and merges one manifest entry per
scene into ``benchmarks/showcase/spectral/manifest.json``. Materials use stock
Cycles nodes (Principled thin film, Glass, Volume Absorption, ...). Blender 5.2
has NO Cycles dispersion sockets (they arrive in 5.3), so the dispersive glass
carries the Astroray Sellmeier node on the Astroray Output exactly like
``benchmarks/blender_showcase/showcase.py``; the Cycles leg sees the plain,
non-dispersive Glass BSDF and the sheets say so.

Scene recipes are inferred from published renders (``.astroray_plan/docs/research/
spectra-website-2026-10-25.md`` section 4, ``spectra-blenderartists-thread-
2026-10-25.md`` section 6); no competitor asset is used.

    blender -b --factory-startup --python build_scenes.py -- \
        --scene sp01_thinfilm_ladder --addon-dir <staged addon dir>
    python build_scenes.py --all --addon-dir <staged addon dir>   # one Blender per scene

Reuses (CLAUDE.md 5b): ``benchmarks/blender_showcase/showcase.py`` scene helpers
and ``benchmarks/blender_parity/scene_library.py``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

try:
    import bpy  # type: ignore
except ImportError:  # driver mode (plain python): spawns Blender per scene
    bpy = None

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SCENES_DIR = HERE / "scenes"
MANIFEST = HERE / "manifest.json"
ASSETS = HERE / "assets"  # gitignored: downloaded CC0 demo files (Classroom)
BLENDER_EXE = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
HDRI = REPO / "benchmarks" / "reference_corpus" / "assets" / "syferfontein_18d_clear_1k.hdr"
SEED = 324
SCHEMA = "pkg324.spectral_showcase.v1"

CLASSROOM = {
    "id": "sp09_classroom",
    "source_url": "https://www.blender.org/download/demo-files/ (classroom.zip, CC0, Christophe Seux)",
    "local_path": "benchmarks/showcase/spectral/assets/classroom/classroom.blend",
}

# (scene id) -> builder name; order = sheet order.
SCENE_IDS = [
    "sp01_thinfilm_ladder", "sp02_prism_fan", "sp02b_prism_check", "sp03_brilliant_diamond",
    "sp04_bubble_glass_block", "sp04b_film_furnace", "sp05_absorbing_cube_caustic",
    "sp06_iridescent_head", "sp07_tumbler_bounce_cap", "sp08_shader_ball_bench",
]


# --------------------------------------------------------------------------- #
# Small shared helpers (Blender side)
# --------------------------------------------------------------------------- #

def _load_helpers(addon_dir):
    """Import showcase (which imports scene_library) and register the addon so the
    Astroray Sellmeier node exists. Returns (sc, sl)."""
    sys.path.insert(0, str(REPO / "benchmarks" / "blender_showcase"))
    import showcase as sc  # noqa: E402  (imports bpy)
    if addon_dir:
        sc._bootstrap_addon(addon_dir)
    sys.path.insert(0, str(REPO / "benchmarks" / "blender_parity"))
    import scene_library as sl  # noqa: E402
    return sc, sl


def _begin(sc, res, spp, bounces=12):
    scene = sc._reset()
    sc._render_defaults(scene, samples=spp, max_bounces=bounces)
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.view_settings.view_transform = "Standard"
    scene.cycles.seed = SEED
    scene.cycles.use_animated_seed = False
    scene.cycles.use_denoising = False
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.sample_clamp_indirect = 0.0
    return scene


def _rois(scene, items):
    """{name: (world point, half-width as a fraction of image width)} -> {name: [x0,y0,x1,y1]}
    fractional rects, row 0 = top of the frame (matches the npy top-down convention)."""
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    bpy.context.view_layer.update()
    aspect = scene.render.resolution_x / scene.render.resolution_y
    out = {}
    for name, (pt, hw) in items.items():
        u, v, _ = world_to_camera_view(scene, scene.camera, Vector(pt))
        cx, cy, hh = u, 1.0 - v, hw * aspect
        out[name] = [round(min(max(c, 0.0), 1.0), 4) for c in (cx - hw, cy - hh, cx + hw, cy + hh)]
    return out


def _plane(sc, name, loc, size, mat, rot=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_plane_add(size=size, location=loc, rotation=rot)
    obj = bpy.context.active_object
    obj.name = name
    return sc._assign(obj, mat)


def _emitter_mat(sl, name, strength, color=(1.0, 1.0, 1.0)):
    mat, nt, emit, out = sl._emission_card_material(bpy, name, strength)
    sl._sock(emit.inputs, "Color").default_value = (*color, 1.0)
    return mat


def _hdri_world(sl, strength=1.0, rot_z=0.0):
    scene = bpy.context.scene
    world = bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    sl._clear_nodes(nt)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(str(HDRI), check_existing=True)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value = (0.0, 0.0, rot_z)
    nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], env.inputs["Vector"])
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = strength
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    return world


def _glass(sl, name, ior=1.5, rough=0.0, color=(1.0, 1.0, 1.0)):
    mat, nt, out = sl._bare_material(bpy, name)
    g = nt.nodes.new("ShaderNodeBsdfGlass")
    sl._sock(g.inputs, "Color").default_value = (*color, 1.0)
    sl._sock(g.inputs, "Roughness").default_value = rough
    sl._sock(g.inputs, "IOR").default_value = ior
    nt.links.new(g.outputs[0], sl._sock(out.inputs, "Surface"))
    return mat


def _revolve(name, profile, segs=64):
    """Closed (r, z) profile polyline revolved around Z. Points with r == 0 are poles."""
    import bmesh
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    rings = []
    for r, z in profile:
        if r == 0.0:
            rings.append([bm.verts.new((0.0, 0.0, z))] * segs)
        else:
            rings.append([bm.verts.new((r * math.cos(2 * math.pi * k / segs),
                                        r * math.sin(2 * math.pi * k / segs), z))
                          for k in range(segs)])
    n = len(profile)
    for i in range(n):
        a, b = rings[i], rings[(i + 1) % n]
        for k in range(segs):
            k2 = (k + 1) % segs
            quad = [a[k], a[k2], b[k2], b[k]]
            uniq = list(dict.fromkeys(quad))
            if len(uniq) >= 3:
                bm.faces.new(uniq)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    for p in obj.data.polygons:
        p.use_smooth = True
    return obj


def _brilliant(name, radius=0.5):
    """Round-brilliant stand-in: convex hull of a girdle, table and pavilion point set.
    Flat-shaded triangles (a faceted gem), culet at -z."""
    import bmesh
    R = radius
    pts = []
    for k in range(8):  # table octagon
        a = math.radians(45.0 * k + 22.5)
        pts.append((0.56 * R * math.cos(a), 0.56 * R * math.sin(a), 0.34 * R))
    for j in range(16):  # girdle band
        a = math.radians(22.5 * j)
        pts.append((R * math.cos(a), R * math.sin(a), 0.02 * R))
        pts.append((R * math.cos(a), R * math.sin(a), -0.02 * R))
    for k in range(8):  # pavilion mains (slightly outside the culet cone)
        a = math.radians(45.0 * k)
        pts.append((0.58 * R * math.cos(a), 0.58 * R * math.sin(a), -0.44 * R))
    pts.append((0.0, 0.0, -0.86 * R))  # culet
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    for p in pts:
        bm.verts.new(p)
    res = bmesh.ops.convex_hull(bm, input=bm.verts[:])
    interior = res.get("geom_interior", [])
    if interior:
        bmesh.ops.delete(bm, geom=[g for g in interior if isinstance(g, bmesh.types.BMVert)], context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


# --------------------------------------------------------------------------- #
# Scene builders: each returns a manifest-entry dict (minus path/sha/blender)
# --------------------------------------------------------------------------- #

FILM_IOR = 1.33
FILM_SUBSTRATE_IOR = 2.0


def _film_mat(sc, name, thickness_nm):
    """Dielectric (IOR 2.0, black base, mirror) with a Principled thin film. The reflected
    spectrum at normal incidence is the Airy reflectance of film(1.33, d) on n=2.0."""
    return sc._principled(name, (0.0, 0.0, 0.0), rough=0.0, metallic=0.0, IOR=FILM_SUBSTRATE_IOR,
                          Thin_Film_Thickness=float(thickness_nm), Thin_Film_IOR=FILM_IOR)


def build_sp01(sc, sl):
    res, spp = (640, 360), 128
    scene = _begin(sc, res, spp)
    sc._world((1.0, 1.0, 1.0), 1.0)
    floor = sc._cyclorama("Sweep", (0.3, 0.3, 0.3), rough=0.9, y_back=6.0, height=8.0, width=60.0)
    r = 0.9
    row = [("White", sc._principled("White", (0.8, 0.8, 0.8), rough=1.0)),
           ("Chrome", sc._principled("Chrome", (0.95, 0.95, 0.95), rough=0.03, metallic=1.0)),
           ("Film300", _film_mat(sc, "Film300", 300.0)),
           ("Film600", _film_mat(sc, "Film600", 600.0)),
           ("Film900", _film_mat(sc, "Film900", 900.0))]
    pts = {}
    for i, (label, mat) in enumerate(row):
        x = (i - 2) * 2.2
        sc._assign(sc._uv_sphere(label, (x, 0.0, r), r), mat)
        pts[label] = ((x, 0.0, r), 0.008)
    sc._light("Softbox", "AREA", (0.0, -5.0, 7.5), (0.0, 0.0, 0.6), 300.0, shape="RECTANGLE",
              size=6.0, size_y=2.0)
    sc._camera((0.0, -10.5, r), (0.0, 0.0, r), lens=28.0)
    return {
        "res": res, "spp": spp, "max_bounces": 12, "cycles": "full",
        "rois": _rois(scene, pts),
        "check": {"kind": "airy_thin_film", "film_ior": FILM_IOR, "substrate_ior": FILM_SUBSTRATE_IOR,
                  "film_nm": {"Film300": 300.0, "Film600": 600.0, "Film900": 900.0},
                  "illuminant": "D65 (RGB-white world)", "tolerance_deg": 10.0,
                  "pass_rule": "hue angle of the ROI mean vs Airy prediction, per thickness"},
        "notes": "White diffuse + chrome + three Principled thin-film dielectrics (black base, mirror, film 1.33 over n=2.0) "
                 "under a uniform white world (flat spectrum, D65) and one softbox. ROIs sit on the projected sphere centres (normal incidence).",
    }


def _prism_scene(sc, sl, check):
    """BK7 prism at minimum deviation, collimated sun through a window baffle, matte screen.
    ``check`` = measurement variant: square-on 2 mm/px camera and NO fill light (a fill would lift the
    screen plateau); otherwise the hero variant with a faint fill so the prism, baffle and screen read."""
    res, spp = (640, 480), (128 if check else 256)
    scene = _begin(sc, res, spp, bounces=16)
    sc._world((0.0, 0.0, 0.0), 0.0)
    n_nominal = 1.5168  # BK7: the check evaluates the engine's own Sellmeier table
    floor = sc._cyclorama("Floor", (0.35, 0.35, 0.35), rough=0.8, y_back=30.0, height=3.0, width=60.0)
    sc._caustic_flags(floor, receiver=True)
    # Equilateral prism (vertical axis, apex +Y before rotation) rotated to minimum deviation
    # for the beam travelling +X: incidence on face 1 = asin(n sin 30) ~ 49.3 deg.
    inc = math.asin(n_nominal * math.sin(math.radians(30.0)))
    rot = math.radians(30.0) - inc  # face-1 normal (150 deg + rot) = 180 deg - inc
    prism = sc._prism("Prism", (0.0, 0.0, 0.0), 1.2, 1.0, rot)
    sc._assign(prism, sc._dispersive_glass("BK7Prism", n_nominal, "bk7"))
    sc._caustic_flags(prism, caster=True)
    # Sun travelling +X, tiny disc, through a window baffle just wider than the beam.
    sun = sc._light("Sun", "SUN", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 6.0, color=(1.0, 1.0, 1.0),
                    angle=math.radians(0.05))
    sun.data.cycles.is_caustics_light = True
    bmat = sc._principled("Baffle", (0.02, 0.02, 0.02), rough=1.0)
    ww = 0.9  # window width along Y; the baffle is big enough that no direct sun reaches the screen
    for i, sgn in enumerate((-1.0, 1.0)):
        sc._box(f"BaffleSide{i}", (-1.4, sgn * (ww / 2 + 6.0), 4.0), (0.05, 12.0, 8.0), bmat)
    sc._box("BaffleTop", (-1.4, 0.0, 4.5), (0.05, ww, 7.0), bmat)
    # Receiver wall, perpendicular to the mid-spectrum exit ray, 6 m from the prism centre.
    dev = 2.0 * inc - math.radians(60.0)
    e = (math.cos(-dev), math.sin(-dev))
    L = 6.0
    wall_c = (L * e[0], L * e[1], 1.0)
    wall = sc._box("Screen", wall_c, (0.05, 3.0, 2.0), sc._principled("Screen", (0.9, 0.9, 0.9), rough=1.0))
    wall.rotation_euler.z = -dev
    sc._caustic_flags(wall, receiver=True)
    t = (-e[1], e[0])
    # Square-on camera, optical axis along -e, centred on the band: ~2 mm/px.
    chk = sc._camera((wall_c[0] - 3.0 * e[0], wall_c[1] - 3.0 * e[1], 0.5), (wall_c[0], wall_c[1], 0.5), lens=67.0)
    chk.name = "CamCheck"
    if not check:
        sc._camera((6.4, 3.4, 2.0), (2.2, -1.9, 0.5), lens=32.0)
        sc._light("Fill", "AREA", (2.0, 1.0, 7.0), (2.0, -1.5, 0.0), 120.0, shape="RECTANGLE", size=8.0, size_y=8.0)
    scene.camera = bpy.data.objects["CamCheck" if check else "Cam"]
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    bpy.context.view_layer.update()
    px = []
    for sv in (-0.4, 0.0, 0.4):  # screen coordinate s (along t from the wall centre) <-> pixel column
        u, _, _ = world_to_camera_view(scene, chk, Vector((wall_c[0] + sv * t[0], wall_c[1] + sv * t[1], 0.5)))
        px.append(u * res[0])
    entry = {
        "res": res, "spp": spp, "max_bounces": 16, "cycles": "no_dispersion",
        "rois": _rois(scene, {"screen": (wall_c, 0.2)}),
        "notes": "BK7 (Abbe 64; the recipe's Abbe ~58 crown) 60 deg prism at minimum deviation, collimated sun through a window, "
                 "matte screen. Cycles 5.2 has no dispersion: its column shows a black screen by design.",
    }
    if check:
        entry["gallery"] = False
        entry["check"] = {
            "kind": "prism_fan_sellmeier", "preset": "bk7", "apex_deg": 60.0,
            "wall_distance_m": L, "exit_dir_deg": -math.degrees(dev), "incidence_deg": math.degrees(inc),
            "prism_rot_deg": math.degrees(rot), "prism_side_m": 1.2, "window_half_m": ww / 2, "baffle_x_m": -1.4,
            "wall_centre": [wall_c[0], wall_c[1]], "t_dir": [t[0], t[1]],
            "px_at_s_m": {"-0.4": round(px[0], 3), "0.0": round(px[1], 3), "0.4": round(px[2], 3)},
            "rows_px": [int(res[1] * 0.40), int(res[1] * 0.60)], "tolerance": 0.05,
            "pass_rule": "R-to-B 50 % edge separation on the screen vs a 2-D Sellmeier ray-trace prediction (same clip, same CMF)"}
        entry["notes"] += " Check scene (not a gallery tile): square-on camera, no fill light."
    else:
        entry["check"] = {"kind": "see_check_scene", "check_scene": "sp02b_prism_check"}
    return entry


def build_sp02(sc, sl):
    return _prism_scene(sc, sl, check=False)


def build_sp02b(sc, sl):
    return _prism_scene(sc, sl, check=True)


def build_sp03(sc, sl):
    res, spp = (640, 480), 256
    scene = _begin(sc, res, spp, bounces=24)
    sc._world((0.002, 0.002, 0.003), 1.0)
    floor = sc._cyclorama("Floor", (0.05, 0.05, 0.055), rough=0.12, y_back=6.0, height=5.0, width=40.0)
    gem = _brilliant("Diamond", 0.5)
    gem.rotation_euler = (math.radians(180.0), 0.0, math.radians(11.0))  # table down, culet up
    gem.location = (0.0, 0.0, 0.34 * 0.5)
    sc._assign(gem, sc._dispersive_glass("Diamond", 2.417, "diamond"))
    sc._caustic_flags(gem, caster=True)
    sc._caustic_flags(floor, receiver=True)
    sc._light("KeyL", "AREA", (-3.2, -2.2, 2.6), (0.0, 0.0, 0.3), 220.0, shape="RECTANGLE", size=1.6, size_y=1.0)
    sc._light("KeyR", "AREA", (3.0, -2.6, 2.4), (0.0, 0.0, 0.3), 160.0, shape="RECTANGLE", size=1.0, size_y=1.6)
    panel = _plane(sc, "Panel", (0.0, 3.2, 1.6), 2.5, _emitter_mat(sl, "PanelMat", 2.0),
                   rot=(math.radians(90.0), 0.0, 0.0))
    panel.scale = (0.9, 0.4, 1.0)
    sc._camera((0.4, -3.1, 0.6), (0.0, 0.0, 0.3), lens=50.0)
    return {
        "res": res, "spp": spp, "max_bounces": 24, "cycles": "no_dispersion",
        "rois": _rois(scene, {"gem": ((0.0, 0.0, 0.3), 0.12)}),
        "check": {"kind": "none", "metric": "firefly count, hue spread of the gem ROI (qualitative sheet)"},
        "notes": "Procedural round-brilliant stand-in (convex hull of a girdle/table/pavilion point set, flat facets), Sellmeier "
                 "'diamond' preset (n 2.417), table down on a dark glossy floor, two soft rectangles plus an emissive panel.",
    }


def _bubble_mat(sl, name, thickness_nm, ior_spec=1.8):
    """Soap-bubble look from stock nodes: Add Shader(Principled specular-only film, Transparent).
    Both Cycles and Astroray CPU render the coloured film; the Principled thin-wall + Transmission route shows
    NO film in either engine (the film modifies the specular lobe only). Additive by construction (adds the film
    reflection to a clear pass-through), so it is not energy conserving - see sp04b for the lossless layer check."""
    mat, nt, out = sl._bare_material(bpy, name)
    p = nt.nodes.new("ShaderNodeBsdfPrincipled")
    sl._sock(p.inputs, "Base Color").default_value = (0.0, 0.0, 0.0, 1.0)
    sl._sock(p.inputs, "Roughness").default_value = 0.0
    sl._sock(p.inputs, "IOR").default_value = ior_spec
    sl._sock(p.inputs, "Thin Film Thickness").default_value = float(thickness_nm)
    sl._sock(p.inputs, "Thin Film IOR").default_value = FILM_IOR
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    ad = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(p.outputs[0], ad.inputs[0])
    nt.links.new(tr.outputs[0], ad.inputs[1])
    nt.links.new(ad.outputs[0], sl._sock(out.inputs, "Surface"))
    return mat


def build_sp04(sc, sl):
    res, spp = (640, 480), 256
    scene = _begin(sc, res, spp, bounces=16)
    sc._world((0.0, 0.0, 0.0), 0.0)
    sc._cyclorama("Floor", (0.04, 0.04, 0.045), rough=0.4, y_back=6.0, height=5.0, width=40.0)
    sc._assign(sc._uv_sphere("Bubble", (-0.9, 0.0, 0.95), 0.9), _bubble_mat(sl, "Bubble", 450.0))
    block = sc._box("GlassBlock", (1.25, 0.2, 0.55), (1.2, 0.6, 1.1), _glass(sl, "BlockGlass", 1.5))
    block.rotation_euler.z = math.radians(18.0)
    sc._light("SoftboxL", "AREA", (-3.8, -2.5, 3.0), (0.0, 0.0, 0.8), 400.0, shape="RECTANGLE", size=2.5, size_y=1.6)
    sc._light("SoftboxR", "AREA", (4.0, -2.0, 2.2), (0.0, 0.0, 0.8), 250.0, shape="RECTANGLE", size=1.0, size_y=2.4)
    sc._light("Back", "AREA", (0.0, 4.5, 3.0), (0.0, 0.0, 0.8), 300.0, shape="RECTANGLE", size=4.0, size_y=1.0)
    sc._camera((0.0, -6.2, 1.2), (0.2, 0.0, 0.85), lens=45.0)
    return {
        "res": res, "spp": spp, "max_bounces": 16, "cycles": "full",
        "rois": _rois(scene, {"bubble_centre": ((-0.9, -0.9, 0.95), 0.05), "block": ((1.25, -0.1, 0.55), 0.05)}),
        "check": {"kind": "see_check_scene", "check_scene": "sp04b_film_furnace"},
        "notes": "Bubble = Add(Principled specular film 450 nm over IOR 1.8, Transparent) next to a 1.5 glass block under three softboxes. "
                 "GPU backend renders only the first Add Shader child (degradation report): expect a black film mirror in the GPU column.",
    }


def build_sp04b(sc, sl):
    """White furnace for a lossless layered film: white diffuse base + specular film (and a no-film control)."""
    res, spp = (256, 128), 128
    scene = _begin(sc, res, spp, bounces=16)
    sc._world((1.0, 1.0, 1.0), 1.0)
    film = sc._principled("FilmLayer", (1.0, 1.0, 1.0), rough=0.0, IOR=FILM_IOR,
                          Thin_Film_Thickness=450.0, Thin_Film_IOR=FILM_IOR)
    ctrl = sc._principled("PlainLayer", (1.0, 1.0, 1.0), rough=0.0, IOR=FILM_IOR)
    sc._assign(sc._uv_sphere("FilmLayer", (-1.1, 0.0, 0.0), 1.0), film)
    sc._assign(sc._uv_sphere("PlainLayer", (1.1, 0.0, 0.0), 1.0), ctrl)
    sc._camera((0.0, -7.0, 0.0), (0.0, 0.0, 0.0), lens=50.0)
    return {
        "res": res, "spp": spp, "max_bounces": 16, "cycles": "full",
        "rois": _rois(scene, {"film_layer": ((-1.1, -1.0, 0.0), 0.12), "plain_layer": ((1.1, -1.0, 0.0), 0.12)}),
        "check": {"kind": "white_furnace_energy", "expected": 1.0, "tolerance": 0.03,
                  "pass_rule": "mean of each ROI == 1.0 within 3 % (white base + specular film layer is lossless)"},
        "notes": "Check scene (not a gallery tile): Principled white base + thin-film specular layer and a no-film control in a "
                 "uniform white world.",
        "gallery": False,
    }


def build_sp05(sc, sl):
    res, spp = (480, 480), 512
    scene = _begin(sc, res, spp, bounces=24)
    sc._world((0.04, 0.045, 0.05), 1.0)
    floor = _plane(sc, "Plane", (0.0, 0.0, 0.0), 40.0, sc._principled("White", (0.9, 0.9, 0.9), rough=1.0))
    sc._caustic_flags(floor, receiver=True)
    cube_mat = sc._dispersive_glass("OrangeGlass", 1.517, "bk7")
    nt = cube_mat.node_tree
    absorb = nt.nodes.new("ShaderNodeVolumeAbsorption")
    sl._sock(absorb.inputs, "Color").default_value = (1.0, 0.45, 0.08, 1.0)
    sl._sock(absorb.inputs, "Density").default_value = 1.2
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    nt.links.new(absorb.outputs[0], sl._sock(out.inputs, "Volume"))
    cube = sc._box("Cube", (0.0, 0.0, 0.5), (1.0, 1.0, 1.0), cube_mat)
    cube.rotation_euler.z = math.radians(22.0)
    sc._caustic_flags(cube, caster=True)
    sph = sc._uv_sphere("GlassSphere", (1.3, -0.5, 0.35), 0.35)
    sc._assign(sph, sc._dispersive_glass("ClearGlass", 1.517, "bk7"))
    sc._caustic_flags(sph, caster=True)
    spot = sc._light("Lamp", "SPOT", (-1.4, -0.8, 3.6), (0.5, 0.0, 0.3), 700.0, color=(1.0, 0.98, 0.95),
                     shadow_soft_size=0.03, spot_size=math.radians(42.0), spot_blend=0.25)
    spot.data.cycles.is_caustics_light = True
    sc._camera((2.7, -3.5, 1.0), (0.4, 0.1, 0.35), lens=38.0)
    return {
        "res": res, "spp": spp, "max_bounces": 24, "cycles": "no_dispersion",
        "rois": _rois(scene, {"caustic_floor": ((1.3, 0.9, 0.0), 0.08), "cube": ((0.0, 0.0, 0.5), 0.06)}),
        "check": {"kind": "none", "metric": "caustic ROI mean vs long path-traced reference (sheet)"},
        "notes": "Orange-absorbing glass cube (mesh volume) + clear sphere, one small bright spot, white plane; photon caustics.",
    }


def build_sp06(sc, sl):
    """Iridescent 'bunny': Blender's Suzanne (subdivided) stands in for the Stanford bunny, which is not in the repo."""
    res, spp = (640, 480), 256
    scene = _begin(sc, res, spp, bounces=16)
    _hdri_world(sl, strength=1.0, rot_z=math.radians(60.0))
    sc._cyclorama("Floor", (0.04, 0.04, 0.045), rough=0.08, y_back=7.0, height=6.0, width=40.0)
    bpy.ops.mesh.primitive_monkey_add(size=1.6, location=(0.0, 0.0, 0.62),
                                      rotation=(0.0, 0.0, math.radians(-28.0)))
    head = bpy.context.active_object
    head.name = "Head"
    mod = head.modifiers.new("Subsurf", "SUBSURF")
    mod.levels = 3
    mod.render_levels = 3
    bpy.context.view_layer.objects.active = head
    bpy.ops.object.modifier_apply(modifier="Subsurf")
    sc._smooth(head)
    iri = sc._principled("Iridescent", (0.0, 0.0, 0.0), rough=0.06, metallic=0.0, IOR=2.0,
                         Thin_Film_Thickness=520.0, Thin_Film_IOR=1.33)
    sc._assign(head, iri)
    sun = sc._light("Sun", "SUN", (0.0, 0.0, 0.0), (0.45, 0.8, -0.35), 6.0, color=(1.0, 0.97, 0.92),
                    angle=math.radians(0.6))
    sc._light("Rim", "AREA", (3.0, 2.0, 3.0), (0.0, 0.0, 0.6), 500.0, shape="RECTANGLE", size=1.0, size_y=3.0)
    sc._camera((0.0, -4.6, 1.2), (0.0, 0.0, 0.7), lens=50.0)
    return {
        "res": res, "spp": spp, "max_bounces": 16, "cycles": "full",
        "rois": _rois(scene, {"head": ((0.0, -0.6, 0.7), 0.1)}),
        "check": {"kind": "none", "metric": "hue varies with viewing angle; Airy hue per angle (sheet)"},
        "notes": "STAND-IN: Suzanne (subdivided) replaces the Stanford bunny (no bunny mesh in the repo; mesh licence unverified). "
                 "Principled thin film 520 nm (1.33) over a black n=2.0 dielectric, small sun plus a dim CC0 sky HDRI (the film needs something to reflect), glossy dark floor.",
    }


def build_sp07(sc, sl):
    res, spp = (640, 480), 256
    scene = _begin(sc, res, spp, bounces=12)
    _hdri_world(sl, strength=1.0, rot_z=math.radians(-74.0))  # sun (elev 18 deg) behind the tumbler, toward the camera
    sc._cyclorama("Table", (0.3, 0.3, 0.3), rough=0.6, y_back=8.0, height=4.0, width=40.0)
    plinth = sc._box("Plinth", (0.0, 0.0, 0.25), (1.8, 1.8, 0.5), sc._principled("Plinth", (0.45, 0.45, 0.45), rough=0.5))
    h, ro, wall, base = 1.3, 0.5, 0.1, 0.3
    z0 = 0.5
    profile = [(0.0, z0), (0.36, z0), (ro - 0.02, z0 + h), (ro, z0 + h), (ro, z0 + h + 0.0),
               (ro - wall, z0 + h), (ro - wall - 0.02, z0 + h), (0.28, z0 + base), (0.0, z0 + base)]
    glass = _revolve("Tumbler", profile, segs=64)
    sc._assign(glass, _glass(sl, "TumblerGlass", 1.5))
    sc._camera((0.0, -5.2, 1.7), (0.0, 0.0, 1.15), lens=50.0)
    return {
        "res": res, "spp": spp, "max_bounces": 12, "cycles": "full",
        "rois": _rois(scene, {"tumbler": ((0.0, -0.4, 1.15), 0.14)}),
        "variants": [{"id": f"b{b:02d}", "max_bounces": b} for b in (4, 8, 12, 64)],
        "reference_variant": "b64",
        "check": {"kind": "bounce_cap_dead_spots", "metric": "dark pixel fraction in the tumbler ROI and ROI mean vs b64",
                  "dark_threshold_frac_of_ref_mean": 0.25},
        "notes": "Thick-walled 1.5 glass tumbler on a plinth under the repo's CC0 sky HDRI (no city HDRI in the repo). Rendered at "
                 "bounce caps 4/8/12 and 64 (reference): the acceptance scene for pkg325.",
    }


def _tile_mats(sc, sl):
    """21 Cycles-node tiles (the four Spectra node-parity sheets, thread section 3)."""
    def P(name, color, **kw):
        return sc._principled(name, color, **kw)

    def with_tree(name, build):
        mat, nt, out = sl._bare_material(bpy, name)
        build(nt, out)
        return mat

    def N(nt, t, **props):
        n = nt.nodes.new(t)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def L(nt, a, ao, b, bi):
        nt.links.new(a.outputs[ao], b.inputs[bi])

    def principled_from(nt, out, color_src=None, rough=0.4, **extra):
        p = N(nt, "ShaderNodeBsdfPrincipled")
        sl._sock(p.inputs, "Roughness").default_value = rough
        for k, v in extra.items():
            sl._sock(p.inputs, k.replace("_", " ")).default_value = v
        nt.links.new(p.outputs[0], sl._sock(out.inputs, "Surface"))
        return p

    tiles = []
    tiles.append(("principled_blue_metal", P("t1", (0.1, 0.25, 0.9), rough=0.2, metallic=0.8)))
    tiles.append(("metallic_gold", sc._metallic("t2", (1.0, 0.78, 0.34), (1.0, 0.9, 0.6), rough=0.2)))
    tiles.append(("glass_rough_0p02", _glass(sl, "t3", 1.45, rough=0.02)))
    tiles.append(("diffuse_pink", P("t4", (0.9, 0.35, 0.55), rough=1.0)))
    tiles.append(("sheen_magenta", P("t5", (0.5, 0.05, 0.4), rough=0.8, Sheen_Weight=1.0, Sheen_Roughness=0.3)))

    def emit(nt, out):
        e = N(nt, "ShaderNodeEmission")
        sl._sock(e.inputs, "Color").default_value = (1.0, 0.6, 0.2, 1.0)
        sl._sock(e.inputs, "Strength").default_value = 2.0
        L(nt, e, 0, out, "Surface")
    tiles.append(("emission", with_tree("t6", emit)))

    def mixsh(nt, out):
        d = N(nt, "ShaderNodeBsdfDiffuse")
        sl._sock(d.inputs, "Color").default_value = (0.2, 0.6, 0.3, 1.0)
        g = N(nt, "ShaderNodeBsdfGlossy")
        sl._sock(g.inputs, "Roughness").default_value = 0.15
        m = N(nt, "ShaderNodeMixShader")
        m.inputs[0].default_value = 0.5
        L(nt, d, 0, m, 1)
        L(nt, g, 0, m, 2)
        L(nt, m, 0, out, "Surface")
    tiles.append(("mix_shader", with_tree("t7", mixsh)))

    def checker(scale, rot=0.0, off=(0.0, 0.0, 0.0), bump=False):
        def build(nt, out):
            tc = N(nt, "ShaderNodeTexCoord")
            mp = N(nt, "ShaderNodeMapping")
            mp.inputs["Scale"].default_value = (scale,) * 3
            mp.inputs["Rotation"].default_value = (0.0, 0.0, rot)
            mp.inputs["Location"].default_value = off
            ck = N(nt, "ShaderNodeTexChecker")
            ck.inputs["Color1"].default_value = (0.9, 0.9, 0.9, 1.0)
            ck.inputs["Color2"].default_value = (0.1, 0.2, 0.7, 1.0)
            L(nt, tc, "Object", mp, "Vector")
            L(nt, mp, "Vector", ck, "Vector")
            p = principled_from(nt, out, rough=0.5)
            L(nt, ck, "Color", p, "Base Color")
            if bump:
                b = N(nt, "ShaderNodeBump")
                b.inputs["Strength"].default_value = 1.0
                L(nt, ck, "Fac", b, "Height")
                L(nt, b, "Normal", p, "Normal")
        return build
    tiles.append(("mapping_scale", with_tree("t8", checker(3.0))))
    tiles.append(("mapping_offset_rot", with_tree("t9", checker(3.0, rot=math.radians(35.0), off=(0.2, 0.1, 0.0)))))
    tiles.append(("bump_checker", with_tree("t10", checker(3.0, bump=True))))

    def normalmap(nt, out):
        tc = N(nt, "ShaderNodeTexCoord")
        no = N(nt, "ShaderNodeTexNoise")
        no.inputs["Scale"].default_value = 6.0
        L(nt, tc, "Object", no, "Vector")
        b = N(nt, "ShaderNodeBump")
        b.inputs["Strength"].default_value = 1.6
        L(nt, no, "Fac", b, "Height")
        p = principled_from(nt, out, rough=0.25)
        sl._sock(p.inputs, "Base Color").default_value = (0.7, 0.7, 0.75, 1.0)
        L(nt, b, "Normal", p, "Normal")
    tiles.append(("bump_noise_strength_1p6", with_tree("t11", normalmap)))

    def voronoi_bump(nt, out):
        tc = N(nt, "ShaderNodeTexCoord")
        vo = N(nt, "ShaderNodeTexVoronoi")
        vo.inputs["Scale"].default_value = 5.0
        L(nt, tc, "Object", vo, "Vector")
        b = N(nt, "ShaderNodeBump")
        L(nt, vo, "Distance", b, "Height")
        p = principled_from(nt, out, rough=0.4)
        sl._sock(p.inputs, "Base Color").default_value = (0.2, 0.4, 0.9, 1.0)
        L(nt, b, "Normal", p, "Normal")
    tiles.append(("voronoi_bump", with_tree("t12", voronoi_bump)))

    def tex_color(kind, scale, **inp):
        def build(nt, out):
            tc = N(nt, "ShaderNodeTexCoord")
            t = N(nt, kind)
            for k, v in inp.items():
                t.inputs[k].default_value = v
            t.inputs["Scale"].default_value = scale
            L(nt, tc, "Object", t, "Vector")
            ramp = N(nt, "ShaderNodeValToRGB")
            ramp.color_ramp.elements[0].color = (0.05, 0.1, 0.4, 1.0)
            ramp.color_ramp.elements[1].color = (1.0, 0.8, 0.3, 1.0)
            L(nt, t, "Fac", ramp, "Fac")
            p = principled_from(nt, out, rough=0.5)
            L(nt, ramp, "Color", p, "Base Color")
        return build
    tiles.append(("noise_fbm_ramp", with_tree("t13", tex_color("ShaderNodeTexNoise", 4.0, Detail=6.0))))
    tiles.append(("wave_ramp", with_tree("t14", tex_color("ShaderNodeTexWave", 3.0))))

    def grad(nt, out):
        tc = N(nt, "ShaderNodeTexCoord")
        g = N(nt, "ShaderNodeTexGradient")
        L(nt, tc, "Object", g, "Vector")
        ramp = N(nt, "ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = (0.9, 0.1, 0.1, 1.0)
        ramp.color_ramp.elements[1].color = (0.1, 0.2, 0.9, 1.0)
        L(nt, g, "Fac", ramp, "Fac")
        p = principled_from(nt, out, rough=0.5)
        L(nt, ramp, "Color", p, "Base Color")
    tiles.append(("gradient_ramp", with_tree("t15", grad)))

    def vor_col(nt, out):
        tc = N(nt, "ShaderNodeTexCoord")
        vo = N(nt, "ShaderNodeTexVoronoi")
        vo.inputs["Scale"].default_value = 5.0
        L(nt, tc, "Object", vo, "Vector")
        p = principled_from(nt, out, rough=0.5)
        L(nt, vo, "Color", p, "Base Color")
    tiles.append(("voronoi_color", with_tree("t16", vor_col)))

    def sepcomb_col(nt, out):
        sp = N(nt, "ShaderNodeSeparateColor")
        sp.inputs[0].default_value = (0.9, 0.3, 0.1, 1.0)
        cb = N(nt, "ShaderNodeCombineColor")
        L(nt, sp, "Red", cb, "Blue")
        L(nt, sp, "Green", cb, "Green")
        L(nt, sp, "Blue", cb, "Red")
        p = principled_from(nt, out, rough=0.5)
        L(nt, cb, "Color", p, "Base Color")
    tiles.append(("separate_combine_color", with_tree("t17", sepcomb_col)))

    def sepcomb_xyz(nt, out):
        tc = N(nt, "ShaderNodeTexCoord")
        sp = N(nt, "ShaderNodeSeparateXYZ")
        cb = N(nt, "ShaderNodeCombineXYZ")
        L(nt, tc, "Object", sp, "Vector")
        L(nt, sp, "Z", cb, "X")
        L(nt, sp, "X", cb, "Y")
        L(nt, sp, "Y", cb, "Z")
        p = principled_from(nt, out, rough=0.5)
        sl._sock(p.inputs, "Base Color").default_value = (0.5, 0.5, 0.5, 1.0)
        # route the shuffled vector as colour via a Map Range-free path: vector -> colour input
        L(nt, cb, "Vector", p, "Base Color")
    tiles.append(("separate_combine_xyz", with_tree("t18", sepcomb_xyz)))

    def vmath(nt, out):
        tc = N(nt, "ShaderNodeTexCoord")
        vm = N(nt, "ShaderNodeVectorMath", operation="DOT_PRODUCT")
        vn = N(nt, "ShaderNodeVectorMath", operation="NORMALIZE")
        L(nt, tc, "Object", vn, 0)
        vm.inputs[1].default_value = (0.0, 0.0, 1.0)
        L(nt, vn, "Vector", vm, 0)
        p = principled_from(nt, out, rough=0.5)
        L(nt, vm, "Value", p, "Base Color")
    tiles.append(("vector_math_dot_normalize", with_tree("t19", vmath)))

    def bc(nt, out):
        bcn = N(nt, "ShaderNodeBrightContrast")
        bcn.inputs["Color"].default_value = (0.5, 0.4, 0.3, 1.0)
        bcn.inputs["Bright"].default_value = 0.2
        bcn.inputs["Contrast"].default_value = 0.6
        gm = N(nt, "ShaderNodeGamma")
        gm.inputs["Gamma"].default_value = 1.6
        L(nt, bcn, "Color", gm, "Color")
        p = principled_from(nt, out, rough=0.5)
        L(nt, gm, "Color", p, "Base Color")
    tiles.append(("bright_contrast_gamma", with_tree("t20", bc)))

    def curves(nt, out):
        c = N(nt, "ShaderNodeRGBCurve")
        c.inputs["Color"].default_value = (0.4, 0.6, 0.8, 1.0)
        pts = c.mapping.curves[0].points  # red curve: invert
        pts[0].location = (0.0, 1.0)
        pts[1].location = (1.0, 0.0)
        c.mapping.update()
        p = principled_from(nt, out, rough=0.5)
        L(nt, c, "Color", p, "Base Color")
    tiles.append(("rgb_curves", with_tree("t21", curves)))
    return tiles


def build_sp08(sc, sl):
    res, spp = (640, 480), 128
    scene = _begin(sc, res, spp, bounces=12)
    scene.view_settings.view_transform = "Standard"
    _hdri_world(sl, strength=0.5, rot_z=math.radians(120.0))
    floor_mat, nt, out = sl._bare_material(bpy, "CheckerFloor")
    p = nt.nodes.new("ShaderNodeBsdfPrincipled")
    sl._sock(p.inputs, "Roughness").default_value = 0.4
    ck = nt.nodes.new("ShaderNodeTexChecker")
    ck.inputs["Scale"].default_value = 28.0
    ck.inputs["Color1"].default_value = (0.75, 0.75, 0.75, 1.0)
    ck.inputs["Color2"].default_value = (0.25, 0.25, 0.25, 1.0)
    nt.links.new(ck.outputs["Color"], p.inputs["Base Color"])
    nt.links.new(p.outputs[0], sl._sock(out.inputs, "Surface"))
    _plane(sc, "Floor", (0.0, 0.0, 0.0), 40.0, floor_mat)
    tiles = _tile_mats(sc, sl)
    cols, pitch, rad = 7, 2.3, 1.0
    pts = {}
    for i, (label, mat) in enumerate(tiles):
        row, col = divmod(i, cols)
        x = (col - (cols - 1) / 2) * pitch
        y = (1 - row) * 2.7
        o = sc._uv_sphere(f"Tile_{label}", (x, y, rad), rad, seg=64, rings=32)
        sc._assign(o, mat)
        pts[label] = ((x, y - rad, rad), 0.018)
    sc._camera((0.0, -15.5, 12.5), (0.0, 0.2, 0.8), lens=32.0)
    return {
        "res": res, "spp": spp, "max_bounces": 12, "cycles": "full",
        "rois": _rois(scene, pts),
        "tiles": [t[0] for t in tiles],
        "check": {"kind": "none", "metric": "per-tile luminance/chroma ratio vs Cycles (sheet, report only)"},
        "notes": "21 spheres on a checker floor under the CC0 sky HDRI: Principled/Metallic/Glass/Sheen/Emission/Mix, mapping, bump, "
                 "noise/wave/gradient/voronoi, colour/XYZ separate-combine, vector math, bright-contrast/gamma, RGB curves.",
    }


BUILDERS = {
    "sp01_thinfilm_ladder": build_sp01, "sp02_prism_fan": build_sp02, "sp02b_prism_check": build_sp02b,
    "sp03_brilliant_diamond": build_sp03, "sp04_bubble_glass_block": build_sp04,
    "sp04b_film_furnace": build_sp04b, "sp05_absorbing_cube_caustic": build_sp05,
    "sp06_iridescent_head": build_sp06, "sp07_tumbler_bounce_cap": build_sp07,
    "sp08_shader_ball_bench": build_sp08,
}


# --------------------------------------------------------------------------- #
# Manifest + driver
# --------------------------------------------------------------------------- #

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_manifest(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"schema": SCHEMA, "seed": SEED, "scenes": {}}


def _classroom_entry() -> dict:
    """Manifest entry for the CC0 Classroom (linked, never committed: assets/ is gitignored)."""
    path = REPO / CLASSROOM["local_path"]
    return {
        "blend_path": CLASSROOM["local_path"], "linked_not_copied": True, "gallery": True,
        "source_url": CLASSROOM["source_url"], "licence": "CC0 1.0",
        "sha256": _sha256(path) if path.is_file() else None,
        "status": "present" if path.is_file() else "needs_download",
        "res": [480, 270], "spp": 48, "seed": SEED, "max_bounces": 12, "cycles": "full",
        # fractional [x0, y0, x1, y1] on the file's own camera (rows from the top)
        "rois": {"blackboard": [0.43, 0.38, 0.64, 0.56], "window": [0.85, 0.17, 0.92, 0.50],
                 "floor": [0.42, 0.60, 0.52, 0.72]},
        "check": {"kind": "roi_parity_vs_cycles", "metric": "ROI luminance ratio Astroray / Cycles (report only)"},
        "notes": "Blender CC0 demo scene (Christophe Seux). Not committed: copy the unzipped classroom folder to "
                 "benchmarks/showcase/spectral/assets/classroom/ (gitignored); `build_scenes.py --register-classroom` "
                 "records its sha256. Heavy (1.25 M triangles, ~1 min per 48 spp CPU frame at 480x270).",
    }


def register_classroom(manifest_path: Path):
    manifest = _load_manifest(manifest_path)
    manifest["scenes"]["sp09_classroom"] = _classroom_entry()
    order = SCENE_IDS + ["sp09_classroom"]
    manifest["scenes"] = {k: manifest["scenes"][k] for k in order if k in manifest["scenes"]}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    e = manifest["scenes"]["sp09_classroom"]
    print(f"[pkg324] sp09_classroom: status={e['status']} sha256={str(e['sha256'])[:12]}", flush=True)


def _r(v, nd=5):
    """JSON-friendly, rounded copy of a bpy value (float, vector, colour, bool, str)."""
    if isinstance(v, (bool, int, str)) or v is None:
        return v
    if isinstance(v, float):
        return round(v, nd)
    try:
        return [_r(x, nd) for x in v]
    except TypeError:
        return str(v)


def scene_digest() -> str:
    """sha256 of a canonical dump of the open scene (objects, mesh coordinates, lights, camera, materials, world,
    render settings). The .blend bytes are NOT reproducible across Blender sessions (verified), the content is."""
    scene = bpy.context.scene
    rec = {"render": [scene.render.resolution_x, scene.render.resolution_y, scene.cycles.samples, scene.cycles.seed,
                      scene.cycles.max_bounces, scene.cycles.transmission_bounces, scene.view_settings.view_transform],
           "objects": [], "materials": [], "world": []}
    for o in sorted(scene.objects, key=lambda x: x.name):
        r = [o.name, o.type, _r(o.location), _r(o.rotation_euler), _r(o.scale), o.parent.name if o.parent else None,
             [sl.material.name if sl.material else None for sl in o.material_slots]]
        if o.type == "MESH":
            me = o.data
            r += [len(me.vertices), len(me.polygons),
                  _r([c for v in me.vertices for c in v.co], 4)]
        elif o.type == "LIGHT":
            ld = o.data
            r += [ld.type, _r(ld.energy), _r(ld.color)] + [_r(getattr(ld, k, None)) for k in
                                                          ("size", "size_y", "spot_size", "spot_blend", "angle")]
        elif o.type == "CAMERA":
            r += [_r(o.data.lens), _r(o.data.sensor_width), _r(o.data.clip_start), _r(o.data.clip_end)]
        rec["objects"].append(r)

    def tree(nt):
        nodes = []
        for n in sorted(nt.nodes, key=lambda x: x.name):
            ins = [[i.identifier, _r(i.default_value) if hasattr(i, "default_value") and not i.is_linked else "L"]
                   for i in n.inputs if i.enabled]
            props = [[k, _r(getattr(n, k))] for k in ("operation", "distribution", "subsurface_method", "interpolation",
                                                      "projection", "preset", "use_preset") if hasattr(n, k)]
            nodes.append([n.name, n.bl_idname, ins, props])
        links = sorted([l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier]
                       for l in nt.links)
        return [nodes, links]
    for m in sorted(bpy.data.materials, key=lambda x: x.name):
        if m.node_tree:
            rec["materials"].append([m.name, tree(m.node_tree)])
    if scene.world and scene.world.node_tree:
        rec["world"] = tree(scene.world.node_tree)
    return hashlib.sha256(json.dumps(rec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_one(scene_id: str, out_dir: Path, addon_dir: str, manifest_path: Path):
    sc, sl = _load_helpers(addon_dir)
    entry = BUILDERS[scene_id](sc, sl)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    out_dir.mkdir(parents=True, exist_ok=True)
    blend = out_dir / f"{scene_id}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), relative_remap=True, compress=True)
    bpy.ops.wm.open_mainfile(filepath=str(blend))  # digest what is in the FILE
    scene = bpy.context.scene
    tri = sum(max(0, len(p.vertices) - 2) for o in scene.objects if o.type == "MESH" for p in o.data.polygons)
    entry.update({
        "blend_path": str(blend.relative_to(REPO)).replace("\\", "/") if str(blend).startswith(str(REPO)) else str(blend),
        "sha256": _sha256(blend), "scene_digest": scene_digest(), "triangles": tri, "gallery": entry.get("gallery", True),
        "blender": bpy.app.version_string, "seed": SEED,
        "res": list(entry["res"]),
    })
    manifest = _load_manifest(manifest_path)
    manifest["schema"], manifest["seed"] = SCHEMA, SEED
    manifest["scenes"][scene_id] = entry
    manifest["scenes"].setdefault("sp09_classroom", _classroom_entry())
    order = SCENE_IDS + ["sp09_classroom"]
    manifest["scenes"] = {k: manifest["scenes"][k] for k in order if k in manifest["scenes"]}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"[pkg324] {scene_id}: {tri} tris, sha256={entry['sha256'][:12]}, {len(entry['rois'])} ROIs", flush=True)


def main():
    if bpy is not None:
        argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    else:
        argv = sys.argv[1:]
    p = argparse.ArgumentParser()
    p.add_argument("--scene", choices=SCENE_IDS)
    p.add_argument("--all", action="store_true", help="driver mode: one Blender process per scene")
    p.add_argument("--addon-dir", default="", help="staged addon dir (__init__.py + astroray*.pyd); needed for the Sellmeier node")
    p.add_argument("--out-dir", default=str(SCENES_DIR))
    p.add_argument("--manifest", default=str(MANIFEST))
    p.add_argument("--digest", default="", metavar="BLEND",
                   help="open BLEND (after registering --addon-dir, so Astroray nodes resolve) and print its SCENE_DIGEST")
    p.add_argument("--register-classroom", action="store_true",
                   help="(re)write the sp09_classroom manifest entry from the local assets/classroom copy, then exit")
    args = p.parse_args(argv)
    if args.register_classroom:
        register_classroom(Path(args.manifest))
        return
    if args.digest:
        _load_helpers(args.addon_dir)
        bpy.ops.wm.open_mainfile(filepath=str(Path(args.digest).resolve()))
        print("SCENE_DIGEST " + scene_digest(), flush=True)
        return
    if args.all or bpy is None:
        ids = SCENE_IDS if args.all else [args.scene]
        for sid in ids:
            subprocess.run([BLENDER_EXE, "-b", "--factory-startup", "--python", str(Path(__file__).resolve()), "--",
                            "--scene", sid, "--addon-dir", args.addon_dir, "--out-dir", args.out_dir,
                            "--manifest", args.manifest], check=True)
        return
    if not args.scene:
        p.error("--scene is required inside Blender")
    build_one(args.scene, Path(args.out_dir), args.addon_dir, Path(args.manifest))


if __name__ == "__main__":
    main()
