# -*- coding: utf-8 -*-
"""Blender showcase scenes for the Astroray addon (runs INSIDE Blender 5.2).

Pretty, Blender-native scenes (Principled, Glass, Volume, Sky Texture, thin
film) that render in both Cycles and Astroray from the same .blend.

    build:  blender -b --factory-startup --python showcase.py -- build \
                --scene glass|volumes|sky|metals|all --out-dir <dir> [--addon-dir <dist/astroray>]
    render: blender -b --factory-startup <scene.blend> --python showcase.py -- render \
                --engine cycles|astroray --device cpu|gpu --samples N --out <png> \
                [--res-pct 100] [--addon-dir <dist/astroray>]

--addon-dir (staged addon: __init__.py + astroray*.pyd) is required to build
`glass` (Astroray Sellmeier node + caustic-caster flag) and to render with
Astroray. Composition rules: memory readme-showcase-render-feedback.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import bpy  # type: ignore

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "benchmarks" / "blender_parity"))
import scene_library as sl  # noqa: E402

RES = (1920, 1080)


# --------------------------------------------------------------------------- #
# Shared scaffolding
# --------------------------------------------------------------------------- #

def _bootstrap_addon(addon_dir):
    os.environ["ASTRORAY_SMOKE_ADDON_DIR"] = str(addon_dir)
    sys.path.insert(0, str(REPO / "scripts"))
    import verify_pkg175_smoke_blender as smoke
    return smoke._bootstrap()


def _reset():
    """Empty the file WITHOUT read_factory_settings (that unregisters a
    script-registered addon, dropping the Astroray node types)."""
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                 bpy.data.cameras, bpy.data.worlds, bpy.data.volumes, bpy.data.images):
        for item in list(coll):
            coll.remove(item)
    return bpy.context.scene


def _render_defaults(scene, samples=256, max_bounces=12):
    scene.render.resolution_x, scene.render.resolution_y = RES
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "AgX"
    scene.cycles.samples = samples
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.use_denoising = False
    scene.cycles.max_bounces = max_bounces
    for k in ("diffuse_bounces", "glossy_bounces", "transmission_bounces",
              "transparent_max_bounces"):
        setattr(scene.cycles, k, max_bounces)
    scene.cycles.caustics_reflective = True
    scene.cycles.caustics_refractive = True
    scene.cycles.blur_glossy = 0.0
    scene.cycles.sample_clamp_indirect = 0.0


def _smooth(obj):
    for p in obj.data.polygons:
        p.use_smooth = True
    return obj


def _principled(name, color, rough=0.5, metallic=0.0, **inputs):
    mat, nt, out = sl._bare_material(bpy, name)
    p = nt.nodes.new("ShaderNodeBsdfPrincipled")
    sl._sock(p.inputs, "Base Color").default_value = (*color, 1.0)
    sl._sock(p.inputs, "Roughness").default_value = rough
    sl._sock(p.inputs, "Metallic").default_value = metallic
    for k, v in inputs.items():
        sl._sock(p.inputs, k.replace("_", " ")).default_value = v
    nt.links.new(p.outputs[0], sl._sock(out.inputs, "Surface"))
    return mat


def _assign(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return obj


def _cyclorama(name, color, width=40.0, depth=8.0, height=6.0, radius=2.5, y_back=4.0, rough=0.7):
    """Floor that curves up into a back wall (studio sweep), smooth-shaded."""
    import bmesh
    prof = [(-depth, 0.0), (y_back - radius, 0.0)]
    for i in range(1, 12):
        a = (math.pi / 2) * i / 12
        prof.append((y_back - radius + radius * math.sin(a), radius - radius * math.cos(a)))
    prof += [(y_back, radius), (y_back, height)]
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    left = [bm.verts.new((-width / 2, y, z)) for y, z in prof]
    right = [bm.verts.new((width / 2, y, z)) for y, z in prof]
    for i in range(len(prof) - 1):
        bm.faces.new((left[i], right[i], right[i + 1], left[i + 1]))
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    _smooth(obj)
    return _assign(obj, _principled(name + "Mat", color, rough=rough))


def _uv_sphere(name, loc, r, seg=96, rings=48):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=loc, segments=seg, ring_count=rings)
    obj = bpy.context.active_object
    obj.name = name
    return _smooth(obj)


def _light(name, kind, loc, target, energy, color=(1, 1, 1), **props):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color
    for k, v in props.items():
        setattr(ld, k, v)
    obj = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = loc
    sl._look_at(obj, target)
    return obj


def _world(color=(0.0, 0.0, 0.0), strength=1.0):
    scene = bpy.context.scene
    world = bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (*color, 1.0)
    bg.inputs[1].default_value = strength
    return world


def _camera(loc, target, lens=50.0, dof=None):
    cam = sl._add_pinned_camera(bpy, bpy.context.scene, loc, target, lens=lens)
    cam.data.sensor_width = 36.0
    if dof:
        cam.data.dof.use_dof = True
        cam.data.dof.focus_distance = dof[0]
        cam.data.dof.aperture_fstop = dof[1]
    return cam


# --------------------------------------------------------------------------- #
# 1. Glass dispersion + caustics
# --------------------------------------------------------------------------- #

def _dispersive_glass(name, ior, preset):
    """Cycles: Glass BSDF (no dispersion in 5.2). Astroray: Sellmeier glass on
    the Astroray Output (memory astroray-native-nodes-need-astroray-output)."""
    mat, nt, out = sl._bare_material(bpy, name)
    glass = nt.nodes.new("ShaderNodeBsdfGlass")
    sl._sock(glass.inputs, "Roughness").default_value = 0.0
    sl._sock(glass.inputs, "IOR").default_value = ior
    nt.links.new(glass.outputs[0], sl._sock(out.inputs, "Surface"))
    out.target = "CYCLES"
    scene = bpy.context.scene
    engine = scene.render.engine
    try:
        scene.render.engine = "CUSTOM_RAYTRACER"  # Astroray node poll needs it
        sell = nt.nodes.new("AstrorayShaderNodeSellmeierGlass")
        aout = nt.nodes.new("AstrorayOutputNode")
    except (RuntimeError, TypeError):
        print("[showcase] Astroray nodes unavailable: glass is non-dispersive", flush=True)
        return mat
    finally:
        scene.render.engine = engine
    sell.use_preset = True
    try:
        sell.preset = preset
    except TypeError as exc:  # dispersion is the scene's point: fail loudly
        raise SystemExit(f"[showcase] Sellmeier preset {preset!r} rejected: {exc}")
    nt.links.new(sell.outputs[0], aout.inputs["Surface"])
    return mat


def _prism(name, loc, side, length, rot_z):
    """Closed equilateral triangular prism (flat faces: a real prism)."""
    import bmesh
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    rr = side / math.sqrt(3.0)
    tri = [(rr * math.cos(a), rr * math.sin(a)) for a in
           (math.radians(90), math.radians(210), math.radians(330))]
    bot = [bm.verts.new((x, y, 0.0)) for x, y in tri]
    top = [bm.verts.new((x, y, length)) for x, y in tri]
    bm.faces.new(bot[::-1])
    bm.faces.new(top)
    for i in range(3):
        j = (i + 1) % 3
        bm.faces.new((bot[i], bot[j], top[j], top[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = loc
    obj.rotation_euler = (0.0, 0.0, rot_z)
    return obj


def _caustic_flags(obj, caster=False, receiver=False):
    obj.cycles.is_caustics_caster = caster
    obj.cycles.is_caustics_receiver = receiver
    if caster and hasattr(obj, "astroray_object"):
        obj.astroray_object.is_caustic_caster = True


def _box(name, loc, dims, mat):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = dims
    return _assign(obj, mat)


def build_glass():
    """Sun through a window onto an SF11 prism + lifted ball lens.

    A SUN lamp matches Astroray's GPU photon-caustic model (one collimated
    beam aimed at the caster union), and the window wall keeps direct sun off
    the floor so the dispersed band reads (memory readme-showcase-render-feedback).
    """
    scene = _reset()
    _render_defaults(scene, samples=512, max_bounces=16)
    _world((0.05, 0.06, 0.08), 1.0)
    floor = _cyclorama("Sweep", (0.4, 0.4, 0.4), rough=0.6, y_back=5.0)
    _caustic_flags(floor, receiver=True)

    # Sun travelling +X/-Y, 22 deg elevation.
    elev, az = math.radians(22.0), math.radians(-12.0)
    d = (math.cos(elev) * math.cos(az), math.cos(elev) * math.sin(az), -math.sin(elev))
    sun = _light("Sun", "SUN", (0.0, 0.0, 0.0), d, 4.0, color=(1.0, 0.97, 0.92),
                 angle=math.radians(0.5))
    sun.data.cycles.is_caustics_light = True

    # 60-degree SF11 prism near minimum deviation: the band falls forward.
    prism = _prism("Prism", (-0.4, 0.3, 0.0), 0.8, 1.3, math.radians(-33.0))
    _assign(prism, _dispersive_glass("SF11Prism", 1.785, "flint_sf11"))
    _caustic_flags(prism, caster=True)
    # Ball lens lifted ~0.1 above the floor so its focus is visible.
    sphere = _uv_sphere("GlassSphere", (1.4, -0.4, 0.5), 0.4)
    _assign(sphere, _dispersive_glass("SF11Sphere", 1.785, "flint_sf11"))
    _caustic_flags(sphere, caster=True)

    # Wall with a window between sun and casters (beyond the photon aperture).
    c = (0.5, 0.0, 0.6)
    dh = math.hypot(d[0], d[1])
    wall_c = [c[i] - 8.0 * d[i] / (dh if i < 2 else 1.0) * (1 if i < 2 else 0) for i in range(3)]
    wall_z = c[2] + 8.0 * math.tan(elev)
    wmat = _principled("WallMat", (0.05, 0.05, 0.05), rough=0.9)
    rot = math.atan2(d[1], d[0])
    ww, wh = 1.8, 1.6  # opening
    parts = [((0, -(ww / 2 + 2.0)), (4.0, 6.0)), ((0, ww / 2 + 2.0), (4.0, 6.0))]
    for i, ((_, off), (w, h)) in enumerate(parts):
        ox, oy = -math.sin(rot) * off, math.cos(rot) * off
        _box(f"Wall{i}", (wall_c[0] + ox, wall_c[1] + oy, 3.0), (0.1, w, h), wmat).rotation_euler.z = rot
    _box("Lintel", (wall_c[0], wall_c[1], wall_z + wh / 2 + 1.5), (0.1, ww, 3.0), wmat).rotation_euler.z = rot
    _box("Sill", (wall_c[0], wall_c[1], (wall_z - wh / 2) / 2), (0.1, ww, max(wall_z - wh / 2, 0.01)), wmat).rotation_euler.z = rot

    _camera((2.3, -4.4, 2.8), (0.55, 0.55, 0.25), lens=40.0)
    return scene


# --------------------------------------------------------------------------- #
# 2. Volumes: fire + smoke + volumetric light shafts
# --------------------------------------------------------------------------- #

def build_volumes():
    scene = _reset()
    _render_defaults(scene, samples=512, max_bounces=8)
    scene.cycles.volume_bounces = 4
    _world((0.01, 0.012, 0.02), 1.0)
    _cyclorama("Ground", (0.12, 0.11, 0.1), rough=0.9, y_back=6.0, height=8.0)

    vdb_dir = HERE / "assets"
    size = 3.2
    paths = sl.write_volumes_vdbs(str(vdb_dir), n=128, seed=4242, size=size)
    smoke = sl._principled_volume_material(bpy, "Smoke", density=10.0,
                                           color=(0.6, 0.62, 0.66), anisotropy=0.4)
    fire = sl._principled_volume_material(bpy, "Fire", density=3.0,
                                          color=(0.2, 0.19, 0.18), anisotropy=0.2,
                                          blackbody=3.0, temperature=3000.0)
    sl._volume_object(bpy, scene, "Smoke", paths["smoke"], (0.2, -size / 2, 0.0), smoke)
    sl._volume_object(bpy, scene, "Fire", paths["fire"], (-size - 0.2, -size / 2, 0.0), fire)

    # Fog slab behind the plumes (disjoint AABB) catches the light shafts.
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 4.0, 2.55))
    fog = bpy.context.active_object
    fog.name = "Fog"
    fog.scale = (12.0, 3.0, 4.9)  # bottom 0.1 above ground: no coplanar faces
    fmat, nt, out = sl._bare_material(bpy, "FogMat")
    pv = nt.nodes.new("ShaderNodeVolumePrincipled")
    sl._sock(pv.inputs, "Density").default_value = 0.08
    sl._sock(pv.inputs, "Anisotropy").default_value = 0.5
    nt.links.new(pv.outputs[0], sl._sock(out.inputs, "Volume"))
    _assign(fog, fmat)

    # Moonlight-blue shafts through the fog, warm fire, cool rim on smoke.
    _light("Shaft", "SPOT", (2.5, 5.5, 7.5), (-0.5, 2.5, 0.0), 12000.0,
           color=(0.6, 0.75, 1.0), shadow_soft_size=0.05,
           spot_size=math.radians(22.0), spot_blend=0.3)
    _light("Rim", "AREA", (4.5, 1.0, 4.0), (0.8, 0.0, 1.2), 400.0,
           color=(0.8, 0.9, 1.0), size=1.5)
    _camera((0.0, -8.0, 1.5), (0.0, 0.0, 1.6), lens=30.0)
    return scene


# --------------------------------------------------------------------------- #
# 3. Nishita sky + sun (outdoor)
# --------------------------------------------------------------------------- #

def build_sky():
    scene = _reset()
    _render_defaults(scene, samples=256, max_bounces=8)
    world = _world()
    wnt = world.node_tree
    bg = wnt.nodes.get("Background")
    sky = wnt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_disc = True
    sky.sun_size = math.radians(1.2)
    sky.sun_elevation = math.radians(4.0)
    sky.sun_rotation = math.radians(0.0)
    sky.altitude = 200.0
    sky.air_density = 1.0
    sky.aerosol_density = 1.2
    sky.ozone_density = 1.0
    wnt.links.new(sky.outputs[0], bg.inputs[0])
    bg.inputs[1].default_value = 0.25

    bpy.ops.mesh.primitive_plane_add(size=400.0, location=(0.0, 0.0, 0.0))
    ground = _assign(bpy.context.active_object, _principled("Ground", (0.22, 0.19, 0.14), rough=0.95))
    ground.name = "Ground"

    # A ring of standing stones catching the low sun, with long shadows.
    import random
    rnd = random.Random(7)
    stone = _principled("Stone", (0.3, 0.28, 0.26), rough=0.8)
    for i in range(9):
        a = 2 * math.pi * i / 9 + 0.2
        h = rnd.uniform(1.6, 2.6)
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(4.0 * math.cos(a), 6.0 + 4.0 * math.sin(a), h / 2))
        s = bpy.context.active_object
        s.name = f"Stone{i}"
        s.scale = (rnd.uniform(0.5, 0.8), rnd.uniform(0.35, 0.5), h)
        s.rotation_euler = (rnd.uniform(-0.05, 0.05), rnd.uniform(-0.05, 0.05), a + math.pi / 2)
        bevel = s.modifiers.new("Bevel", "BEVEL")
        bevel.width = 0.06
        bevel.segments = 3
        _assign(s, stone)
    # Chrome + white spheres show sky reflection and the sky/sun colour split.
    _assign(_uv_sphere("Chrome", (-1.0, 3.0, 0.6), 0.6), _principled("Chrome", (0.95, 0.95, 0.95), rough=0.05, metallic=1.0))
    _assign(_uv_sphere("White", (1.2, 3.4, 0.5), 0.5), _principled("White", (0.8, 0.8, 0.8), rough=0.6))
    _camera((0.4, -6.0, 1.3), (0.0, 6.0, 2.4), lens=28.0)
    return scene


# --------------------------------------------------------------------------- #
# 4. Thin film + metals
# --------------------------------------------------------------------------- #

def _metallic(name, color, edge, rough=0.15, film_nm=0.0, film_ior=2.4):
    """Metallic BSDF (F82-tint): the Blender-native conductor node."""
    mat, nt, out = sl._bare_material(bpy, name)
    m = nt.nodes.new("ShaderNodeBsdfMetallic")
    sl._sock(m.inputs, "Base Color").default_value = (*color, 1.0)
    sl._sock(m.inputs, "Edge Tint").default_value = (*edge, 1.0)
    sl._sock(m.inputs, "Roughness").default_value = rough
    sl._sock(m.inputs, "Thin Film Thickness").default_value = film_nm
    sl._sock(m.inputs, "Thin Film IOR").default_value = film_ior
    nt.links.new(m.outputs[0], sl._sock(out.inputs, "Surface"))
    return mat


def build_metals():
    scene = _reset()
    _render_defaults(scene, samples=512, max_bounces=16)
    _world((0.03, 0.03, 0.035), 1.0)
    _cyclorama("Sweep", (0.035, 0.035, 0.04), rough=0.3, y_back=3.0)

    # Front row: gold, copper, then anodised titanium at rising oxide thickness.
    row = [
        ("Gold", _metallic("Gold", (1.0, 0.78, 0.34), (1.0, 0.9, 0.6))),
        ("Copper", _metallic("Copper", (0.96, 0.55, 0.42), (1.0, 0.75, 0.6))),
    ]
    ti, ti_edge = (0.55, 0.52, 0.5), (0.7, 0.68, 0.66)
    for nm in (160.0, 230.0, 300.0, 380.0):
        row.append((f"Ti{int(nm)}", _metallic(f"Ti{int(nm)}", ti, ti_edge, rough=0.12,
                                               film_nm=nm, film_ior=2.4)))
    n = len(row)
    for i, (label, mat) in enumerate(row):
        x = (i - (n - 1) / 2) * 1.05
        _assign(_uv_sphere(label, (x, 0.0, 0.45), 0.45), mat)

    # Soap bubbles floating behind: thin-walled water film.
    for j, (x, y, z, r, nm) in enumerate(((-1.6, 1.3, 1.55, 0.55, 480.0),
                                          (0.4, 1.7, 1.85, 0.7, 380.0),
                                          (2.1, 1.2, 1.35, 0.45, 560.0))):
        bub = _principled(f"Bubble{j}", (1, 1, 1), rough=0.0, IOR=1.33,
                          Transmission_Weight=1.0, Thin_Wall=True,
                          Thin_Film_Thickness=nm, Thin_Film_IOR=1.33)
        _assign(_uv_sphere(f"Bubble{j}", (x, y, z), r), bub)

    # Softboxes: big key above-left, strip rim right, low fill.
    _light("Key", "AREA", (-3.0, -3.0, 4.5), (0.0, 0.5, 0.6), 900.0,
           color=(1.0, 0.97, 0.92), shape="RECTANGLE", size=3.0, size_y=1.5)
    _light("Strip", "AREA", (4.0, 1.5, 2.5), (0.0, 0.5, 0.8), 500.0,
           color=(0.85, 0.92, 1.0), shape="RECTANGLE", size=0.4, size_y=3.0)
    _light("Fill", "AREA", (1.0, -5.0, 1.0), (0.0, 0.5, 0.6), 120.0, size=3.0)
    _camera((0.0, -7.5, 1.7), (0.0, 0.6, 0.85), lens=40.0)
    return scene


BUILDERS = {"glass": build_glass, "volumes": build_volumes, "sky": build_sky,
            "metals": build_metals}


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #

def _enable_cycles_gpu():
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type == "OPTIX"
    if not any(d.use for d in prefs.devices):
        raise SystemExit("[showcase] no OptiX device; use --device cpu")
    bpy.context.scene.cycles.device = "GPU"


def render(a):
    scene = bpy.context.scene
    scene.render.resolution_percentage = a.res_pct
    scene.cycles.samples = a.samples
    if a.engine == "cycles":
        scene.render.engine = "CYCLES"
        if a.device == "gpu":
            _enable_cycles_gpu()
        else:
            scene.cycles.device = "CPU"
    else:
        astroray, _addon = _bootstrap_addon(a.addon_dir)
        print(f"[showcase] astroray module: {astroray.__file__}", flush=True)
        scene.render.engine = "CUSTOM_RAYTRACER"
        cr = scene.custom_raytracer
        cr.samples = a.samples
        cr.device_mode = a.device
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.filepath = str(Path(a.out).resolve())
    import time
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    print(f"[showcase] rendered {a.out} engine={a.engine}/{a.device} spp={a.samples} "
          f"{time.time() - t0:.1f}s", flush=True)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--scene", choices=[*BUILDERS, "all"], required=True)
    b.add_argument("--out-dir", default=str(HERE / "scenes"))
    b.add_argument("--addon-dir", default="")
    r = sub.add_parser("render")
    r.add_argument("--engine", choices=("cycles", "astroray"), required=True)
    r.add_argument("--device", choices=("cpu", "gpu"), default="gpu")
    r.add_argument("--samples", type=int, default=256)
    r.add_argument("--res-pct", type=int, default=100)
    r.add_argument("--out", required=True)
    r.add_argument("--addon-dir", default="")
    a = p.parse_args(argv)
    if a.cmd == "render":
        render(a)
        return
    if a.addon_dir:
        _bootstrap_addon(a.addon_dir)
    names = list(BUILDERS) if a.scene == "all" else [a.scene]
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        BUILDERS[name]()
        path = out_dir / f"showcase_{name}.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(path), relative_remap=True)
        print(f"[showcase] saved {path}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.exit(1)
