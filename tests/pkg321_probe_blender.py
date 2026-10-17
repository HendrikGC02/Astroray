"""pkg321 -- counterfactual probes for the DROPPED-SILENT rows of #1089 (runs INSIDE Blender).

    blender -b --factory-startup --python tests/pkg321_probe_blender.py -- <out_dir> [probe_id ...]

For every probe the same tiny scene is rendered on CPU three times: variant A, variant A under a second seed (the noise
floor `d_aa`; renders are deterministic per seed, so an inert input gives d_ab == 0 exactly) and variant B, where B mutates ONE node
input / property (or links one socket). `<out_dir>/results.json` carries, per probe, the pixel differences
and the DegradationReport text each variant produced; `<out_dir>/<id>_{A,B}.npy` the linear renders.
tests/test_pkg321_dropped_row_probes.py is the pytest driver and owns the probe table (PROBES below is
only the scene description); .astroray_plan/docs/pkg321-dropped-row-audit.md is the verdict table.

Environment: ASTRORAY_PYD_DIR (a copy of the engine .pyd), CUDA_VISIBLE_DEVICES=-1, OMP_NUM_THREADS=8.
"""
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path

import bpy
import numpy as np

REPO = Path(__file__).resolve().parents[1]
RES, SPP = 80, 64
FLOOR = (0.8, 0.8, 0.8, 1.0)


# --------------------------------------------------------------------------- #
# Probe table: one counterfactual per #1089 row group
# --------------------------------------------------------------------------- #
# id -> dict(scene, node, out (output socket of the material), pre, A, B, link, link_socket)
#   pre/A/B : {socket name | "prop:<name>": value}; ("enum", i) picks the i-th enum item (-1 = last)
#   link    : helper linking a source node into `link_socket` of the probed node in variant B only
def _normal_probe(node, pre=None, sock="Normal"):
    return dict(scene="sphere", node=node, pre=pre or {}, A={}, B={}, link="normal_map", link_socket=sock)


PROBES = {
    # ---- Hair Principled (family 1) ---------------------------------------------------------------------
    "hair_color": dict(scene="hair", node="ShaderNodeBsdfHairPrincipled",
                       A={"Color": (0.8, 0.1, 0.05, 1)}, B={"Color": (0.05, 0.1, 0.8, 1)}),
    "hair_roughness": dict(scene="hair", node="ShaderNodeBsdfHairPrincipled", A={"Roughness": 0.1}, B={"Roughness": 0.8}),
    "hair_radial_roughness": dict(scene="hair", node="ShaderNodeBsdfHairPrincipled",
                                  A={"Radial Roughness": 0.1}, B={"Radial Roughness": 0.9}),
    "hair_coat": dict(scene="hair", node="ShaderNodeBsdfHairPrincipled", A={"Coat": 0.0}, B={"Coat": 1.0}),
    "hair_ior": dict(scene="hair", node="ShaderNodeBsdfHairPrincipled", A={"IOR": 1.2}, B={"IOR": 2.4}),
    "hair_offset": dict(scene="hair", node="ShaderNodeBsdfHairPrincipled", A={"Offset": 0.0}, B={"Offset": 0.35}),
    "hair_random_roughness": dict(scene="hair", node="ShaderNodeBsdfHairPrincipled",
                                  pre={"Random": 1.0}, A={"Random Roughness": 0.0}, B={"Random Roughness": 1.0}),
    "hair_random": dict(scene="hair", node="ShaderNodeBsdfHairPrincipled",
                        pre={"prop:parametrization": "MELANIN", "Random Roughness": 1.0, "Random Color": 1.0},
                        A={"Random": 0.0}, B={"Random": 1.0}),
    "hair_random_color": dict(scene="hair", node="ShaderNodeBsdfHairPrincipled",
                              pre={"prop:parametrization": "MELANIN", "Random": 1.0},
                              A={"Random Color": 0.0}, B={"Random Color": 1.0}),
    "hair_model": dict(scene="hair", node="ShaderNodeBsdfHairPrincipled",
                       A={"prop:model": "CHIANG"}, B={"prop:model": "HUANG"}),
    "hair_melanin": dict(scene="hair", node="ShaderNodeBsdfHairPrincipled", pre={"prop:parametrization": "MELANIN"},
                         A={"Melanin": 0.05}, B={"Melanin": 0.95}),
    "hair_parametrization": dict(scene="hair", node="ShaderNodeBsdfHairPrincipled",
                                 A={"prop:parametrization": "COLOR"}, B={"prop:parametrization": "MELANIN"}),
    "hair_melanin_redness": dict(scene="hair", node="ShaderNodeBsdfHairPrincipled",
                                 pre={"prop:parametrization": "MELANIN", "Melanin": 0.6},
                                 A={"Melanin Redness": 0.0}, B={"Melanin Redness": 1.0}),
    "hair_tint": dict(scene="hair", node="ShaderNodeBsdfHairPrincipled",
                      pre={"prop:parametrization": "MELANIN", "Melanin": 0.0, "Melanin Redness": 0.5},
                      A={"Tint": (1, 1, 1, 1)}, B={"Tint": (0.05, 0.2, 1.0, 1)}),
    "hair_absorption": dict(scene="hair", node="ShaderNodeBsdfHairPrincipled",
                            pre={"prop:parametrization": "ABSORPTION"},
                            A={"Absorption Coefficient": (0.1, 0.1, 0.1)}, B={"Absorption Coefficient": (0.1, 1.5, 3.0)}),
    # ---- BSDF Normal / Tangent / Coat Normal (family 2) -----------------------------------------------------
    "n_principled_control": _normal_probe("ShaderNodeBsdfPrincipled", {"Roughness": 0.4}),
    "n_diffuse": _normal_probe("ShaderNodeBsdfDiffuse", {"Color": (0.6, 0.6, 0.6, 1)}),
    "n_glass": _normal_probe("ShaderNodeBsdfGlass", {"Roughness": 0.1}),
    "n_metallic": _normal_probe("ShaderNodeBsdfMetallic", {"Roughness": 0.3}),
    "n_refraction": _normal_probe("ShaderNodeBsdfRefraction", {"Roughness": 0.1}),
    "n_sheen": _normal_probe("ShaderNodeBsdfSheen", {"Color": (1, 1, 1, 1), "Roughness": 0.3}),
    "n_translucent": _normal_probe("ShaderNodeBsdfTranslucent", {"Color": (0.6, 0.6, 0.6, 1)}),
    "n_anisotropic": _normal_probe("ShaderNodeBsdfAnisotropic", {"Roughness": 0.3, "Anisotropy": 0.5}),
    "n_diffuse_bump": dict(scene="sphere", node="ShaderNodeBsdfDiffuse", pre={"Color": (0.6, 0.6, 0.6, 1)}, A={}, B={},
                           link="bump_image", link_socket="Normal"),
    "n_principled_coat": dict(scene="sphere", node="ShaderNodeBsdfPrincipled",
                              pre={"Roughness": 0.5, "Coat Weight": 1.0, "Coat Roughness": 0.05}, A={}, B={},
                              link="normal_map", link_socket="Coat Normal"),
    "t_principled": dict(scene="sphere", node="ShaderNodeBsdfPrincipled",
                         pre={"Metallic": 1.0, "Roughness": 0.35, "Anisotropic": 0.85}, A={}, B={},
                         link="tangent_radial", link_socket="Tangent"),
    "t_metallic": dict(scene="sphere", node="ShaderNodeBsdfMetallic", pre={"Roughness": 0.35, "Anisotropy": 0.85},
                       A={}, B={}, link="tangent_radial", link_socket="Tangent"),
    "t_anisotropic": dict(scene="sphere", node="ShaderNodeBsdfAnisotropic", pre={"Roughness": 0.35, "Anisotropy": 0.85},
                          A={}, B={}, link="tangent_radial", link_socket="Tangent"),
    "disp_normal": dict(scene="sphere", node="ShaderNodeDisplacement", custom="displacement"),
    # ---- enum props + Anisotropic inputs (family 3) -------------------------------------------------------
    "e_principled_distribution": dict(scene="sphere", node="ShaderNodeBsdfPrincipled",
                                      pre={"Metallic": 1.0, "Roughness": 0.7},
                                      A={"prop:distribution": "MULTI_GGX"}, B={"prop:distribution": "GGX"}),
    "e_principled_subsurface_method": dict(scene="sphere", node="ShaderNodeBsdfPrincipled",
                                           pre={"Subsurface Weight": 1.0, "Subsurface Scale": 0.4,
                                                "Subsurface Radius": (1.0, 0.2, 0.1)},
                                           A={"prop:subsurface_method": "RANDOM_WALK"},
                                           B={"prop:subsurface_method": "BURLEY"}),
    "e_principled_subsurface_ior": dict(scene="sphere", node="ShaderNodeBsdfPrincipled",
                                        pre={"Subsurface Weight": 1.0, "Subsurface Scale": 0.4,
                                             "prop:subsurface_method": "RANDOM_WALK_SKIN"},
                                        A={"Subsurface IOR": 1.2}, B={"Subsurface IOR": 2.0}),
    "e_glass_distribution": dict(scene="sphere", node="ShaderNodeBsdfGlass", pre={"Roughness": 0.45},
                                 A={"prop:distribution": ("enum", 0)}, B={"prop:distribution": ("enum", 1)}),
    "e_refraction_distribution": dict(scene="sphere", node="ShaderNodeBsdfRefraction", pre={"Roughness": 0.45},
                                      A={"prop:distribution": ("enum", 0)}, B={"prop:distribution": ("enum", -1)}),
    "e_sheen_distribution": dict(scene="sphere", node="ShaderNodeBsdfSheen", pre={"Color": (1, 1, 1, 1), "Roughness": 0.4},
                                 A={"prop:distribution": ("enum", 0)}, B={"prop:distribution": ("enum", -1)}),
    "e_glossy_distribution": dict(scene="sphere", node="ShaderNodeBsdfGlossy", pre={"Roughness": 0.45},
                                  A={"prop:distribution": ("enum", 0)}, B={"prop:distribution": ("enum", 1)}),
    "e_anisotropic_distribution": dict(scene="sphere", node="ShaderNodeBsdfAnisotropic",
                                       pre={"Roughness": 0.45, "Anisotropy": 0.5},
                                       A={"prop:distribution": ("enum", 0)}, B={"prop:distribution": ("enum", 1)}),
    "a_anisotropy": dict(scene="sphere", node="ShaderNodeBsdfAnisotropic", pre={"Roughness": 0.35},
                         A={"Anisotropy": 0.0}, B={"Anisotropy": 0.9}),
    "a_rotation": dict(scene="sphere", node="ShaderNodeBsdfAnisotropic", pre={"Roughness": 0.35, "Anisotropy": 0.9},
                       A={"Rotation": 0.0}, B={"Rotation": 0.25}),
    # ---- Principled Volume (family 4) ---------------------------------------------------------------------
    "v_absorption_color": dict(scene="volsphere", node="ShaderNodeVolumePrincipled", out="Volume",
                               pre={"Density": 3.0, "Color": (0.3, 0.3, 0.3, 1)},
                               A={"Absorption Color": (1, 1, 1, 1)}, B={"Absorption Color": (1.0, 0.1, 0.02, 1)}),
    "v_blackbody_tint": dict(scene="volsphere", node="ShaderNodeVolumePrincipled", out="Volume",
                             pre={"Density": 2.0, "Blackbody Intensity": 1.0, "Temperature": 3500.0},
                             A={"Blackbody Tint": (1, 1, 1, 1)}, B={"Blackbody Tint": (0.1, 0.3, 1.0, 1)}),
    "v_density_attribute": dict(scene="vdb", node="ShaderNodeVolumePrincipled", out="Volume", pre={"Density": 4.0},
                                A={"Density Attribute": "density"}, B={"Density Attribute": "dens2"}),
    "v_temperature_attribute": dict(scene="vdb", node="ShaderNodeVolumePrincipled", out="Volume",
                                    pre={"Density": 3.0, "Blackbody Intensity": 4.0, "Temperature": 3500.0},
                                    A={"Temperature Attribute": "temperature"}, B={"Temperature Attribute": "temp2"}),
    "v_color_attribute": dict(scene="vdb", node="ShaderNodeVolumePrincipled", out="Volume", pre={"Density": 4.0},
                              A={"Color Attribute": ""}, B={"Color Attribute": "color"}),
    # ---- Sky texture props (family 5) --------------------------------------------------------------------
    "s_ground_albedo": dict(scene="sky", node="ShaderNodeTexSky", A={"prop:ground_albedo": 0.0}, B={"prop:ground_albedo": 1.0}),
    "s_sun_direction": dict(scene="sky", node="ShaderNodeTexSky",
                            A={"prop:sun_direction": (0.0, 0.88, 0.48)}, B={"prop:sun_direction": (0.6, 0.6, 0.3)}),
    "s_sun_direction_preetham": dict(scene="sky", node="ShaderNodeTexSky", pre={"prop:sky_type": "PREETHAM"},
                                     A={"prop:sun_direction": (0.0, 0.88, 0.48)}, B={"prop:sun_direction": (0.6, 0.6, 0.3)}),
    "s_sun_elevation_control": dict(scene="sky", node="ShaderNodeTexSky",
                                    A={"prop:sun_elevation": 0.5}, B={"prop:sun_elevation": 0.2}),
    "s_sun_intensity": dict(scene="sky", node="ShaderNodeTexSky", A={"prop:sun_intensity": 1.0}, B={"prop:sun_intensity": 4.0}),
    "s_sun_size": dict(scene="sky", node="ShaderNodeTexSky", A={"prop:sun_size": 0.0095}, B={"prop:sun_size": 0.12}),
    "s_altitude": dict(scene="sky", node="ShaderNodeTexSky", A={"prop:altitude": 0.0}, B={"prop:altitude": 20000.0}),
    # ---- Glass thin film + misc (family 6) ------------------------------------------------------------------
    "g_thin_film_thickness": dict(scene="sphere", node="ShaderNodeBsdfGlass", pre={"Roughness": 0.0},
                                  A={"Thin Film Thickness": 0.0}, B={"Thin Film Thickness": 600.0}),
    "g_thin_film_ior": dict(scene="sphere", node="ShaderNodeBsdfGlass", pre={"Roughness": 0.0, "Thin Film Thickness": 600.0},
                            A={"Thin Film IOR": 1.33}, B={"Thin Film IOR": 2.0}),
    "m_geometry_normal": dict(scene="sphere", node="ShaderNodeBsdfDiffuse", pre={},
                              A={"Color": (0.5, 0.5, 0.5, 1)}, B={"Color": (0.5, 0.5, 0.5, 1)},
                              link="geometry_normal", link_socket="Color"),
}


# --------------------------------------------------------------------------- #
# Bootstrap
# --------------------------------------------------------------------------- #
def bootstrap():
    build_dir = Path(os.environ.get("ASTRORAY_PYD_DIR", REPO / "build_cuda"))
    for entry in (str(build_dir), str(REPO)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    dirs = [build_dir, Path(r"C:/oidn/bin"), Path(r"C:/Program Files/mingw64/bin")]
    dirs += sorted(Path(r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA").glob("v*/bin"))
    for d in dirs:
        if d.is_dir():
            try:
                os.add_dll_directory(str(d))
            except (OSError, AttributeError):
                pass
    import astroray
    print(f"[pkg321] astroray module: {astroray.__file__}", flush=True)
    import blender_addon
    try:
        blender_addon.register()
    except Exception as exc:  # noqa: BLE001
        if "already registered" not in str(exc):
            raise
    return blender_addon


CAPTURED = []


def install_degradation_capture(addon):
    cls = addon.DegradationReport
    orig = cls.emit

    def emit(self, report=None):
        text = orig(self, report)
        CAPTURED.append(text)
        return text
    cls.emit = emit


# --------------------------------------------------------------------------- #
# Scene builders
# --------------------------------------------------------------------------- #
def _world(color, strength=1.0, sky=False):
    world = bpy.data.worlds.new("W")
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    if sky:
        src = nt.nodes.new("ShaderNodeTexSky")
        bg = nt.nodes.new("ShaderNodeBackground")
        nt.links.new(src.outputs["Color"], bg.inputs["Color"])
    else:
        src = None
        bg = nt.nodes.new("ShaderNodeBackground")
        bg.inputs["Color"].default_value = (color, color, color, 1.0)
    bg.inputs["Strength"].default_value = strength
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    bpy.context.scene.world = world
    return src


def _sun(energy=4.0, rot=(0.9, 0.0, 0.6), angle=0.14):
    d = bpy.data.lights.new("Sun", "SUN")
    d.energy = energy
    d.angle = angle
    o = bpy.data.objects.new("Sun", d)
    o.rotation_euler = rot
    bpy.context.scene.collection.objects.link(o)


def _camera(loc, rot, lens=50.0):
    d = bpy.data.cameras.new("Cam")
    d.lens = lens
    o = bpy.data.objects.new("Cam", d)
    o.location = loc
    o.rotation_euler = rot
    bpy.context.scene.collection.objects.link(o)
    bpy.context.scene.camera = o


def _configure(scene):
    scene.render.engine = "CUSTOM_RAYTRACER"
    scene.render.resolution_x = scene.render.resolution_y = RES
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.render.image_settings.exr_codec = "NONE"
    scene.cycles.samples = SPP
    scene.cycles.use_denoising = False
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.seed = 321
    scene.cycles.use_animated_seed = False
    cr = scene.custom_raytracer
    cr.samples = SPP
    if hasattr(cr, "preview_samples"):
        cr.preview_samples = SPP
    cr.device_mode = "cpu"
    cr.use_adaptive_sampling = False


def build_scene(kind, out_dir):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    _configure(scene)
    info = {"obj": None}
    if kind in ("sphere", "hair", "volsphere"):
        _world(0.25 if kind != "volsphere" else 0.6)
        _sun(4.0 if kind != "volsphere" else 0.0)
    if kind == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, location=(0, 0, 0), segments=48, ring_count=24)
        o = bpy.context.active_object
        for p in o.data.polygons:
            p.use_smooth = True
        info["obj"] = o
        _camera((0, -3.4, 0), (math.pi / 2, 0, 0))
    elif kind == "volsphere":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.9, location=(0, 0, 0), segments=32, ring_count=16)
        info["obj"] = bpy.context.active_object
        _camera((0, -3.4, 0), (math.pi / 2, 0, 0))
    elif kind == "hair":
        sys.path.insert(0, str(REPO))
        from benchmarks.blender_parity import scene_library as sl
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.3, location=(0, 0, 0))
        scalp = bpy.context.active_object
        scalp.hide_render = True
        curves = sl._build_hair_curves(bpy, scalp, 0.3, 1500, 6, seed=321)
        n = len(curves.attributes["radius"].data)
        radii = [0.014 * (1.0 - 0.5 * ((i % 6) / 5.0)) for i in range(n)]
        curves.attributes["radius"].data.foreach_set("value", radii)
        o = bpy.data.objects.new("Hair", curves)
        scene.collection.objects.link(o)
        info["obj"] = o
        _camera((0, -2.2, 0.05), (math.pi / 2, 0, 0))
    elif kind == "sky":
        info["sky"] = _world(0.0, sky=True)
        # camera at the sun azimuth, pitched up to the sun elevation (sun_elevation 0.5, rotation 0 -> +Y)
        _camera((0, 0, 1.0), (math.pi / 2 + 0.5, 0, 0), lens=24.0)
        bpy.context.scene.view_settings.view_transform = "Standard"
    elif kind == "vdb":
        info["obj"] = _vdb_object(out_dir)
        _world(0.6)
        _camera((0, -5.0, 0), (math.pi / 2, 0, 0))
    return info


def _vdb_object(out_dir):
    import openvdb
    N = 32
    z, y, x = np.mgrid[0:N, 0:N, 0:N].astype(np.float32)
    c = (N - 1) / 2.0
    r2 = ((x - c) ** 2 + (y - c) ** 2 + (z - c) ** 2) / (c * c)
    lumps = 0.6 + 0.4 * np.sin(x * 0.7) * np.cos(y * 0.5) * np.sin(z * 0.6)
    dens = (np.clip(1.0 - r2, 0.0, 1.0) * lumps).astype(np.float32)
    r2b = ((x - c * 1.5) ** 2 + (y - c) ** 2 + (z - c * 0.6) ** 2) / (0.6 * c * 0.6 * c)
    dens2 = np.clip(1.0 - r2b, 0.0, 1.0).astype(np.float32)
    temp = (np.clip(1.0 - 2.5 * r2, 0.0, 1.0) ** 2).astype(np.float32)
    temp2 = (np.clip(1.0 - 2.5 * r2b, 0.0, 1.0) ** 2).astype(np.float32)
    grids = []
    for name, arr in (("density", dens), ("dens2", dens2), ("temperature", temp), ("temp2", temp2)):
        g = openvdb.FloatGrid()
        g.copyFromArray(np.ascontiguousarray(arr.transpose(2, 1, 0)))
        g.name = name
        g.transform = openvdb.createLinearTransform(voxelSize=2.0 / N)
        grids.append(g)
    try:
        col = np.stack([dens, dens * 0.2, 1.0 - dens], axis=-1).astype(np.float32)
        g = openvdb.Vec3SGrid()
        g.copyFromArray(np.ascontiguousarray(col.transpose(2, 1, 0, 3)))
        g.name = "color"
        g.transform = openvdb.createLinearTransform(voxelSize=2.0 / N)
        grids.append(g)
    except Exception as exc:  # noqa: BLE001
        print(f"[pkg321] vec3 color grid not written: {exc}", flush=True)
    path = os.path.join(out_dir, "probe.vdb")
    openvdb.write(path, grids=grids)
    vol = bpy.data.volumes.new("ProbeVol")
    vol.filepath = path
    obj = bpy.data.objects.new("ProbeVol", vol)
    obj.location = (-1.0, -1.0, -1.0)
    bpy.context.scene.collection.objects.link(obj)
    return obj


# --------------------------------------------------------------------------- #
# Material builder
# --------------------------------------------------------------------------- #
def _png_image(out_dir, name, arr):
    img = bpy.data.images.new(name, arr.shape[1], arr.shape[0], alpha=False, float_buffer=False)
    rgba = np.concatenate([arr, np.ones(arr.shape[:2] + (1,), np.float32)], axis=-1)
    img.pixels.foreach_set(rgba.ravel())
    img.filepath_raw = os.path.join(out_dir, name + ".png")
    img.file_format = "PNG"
    img.colorspace_settings.name = "Non-Color"
    img.save()
    bpy.data.images.remove(img)
    img = bpy.data.images.load(os.path.join(out_dir, name + ".png"))
    img.colorspace_settings.name = "Non-Color"
    return img


def _link_normal_map(nt, sock, out_dir):
    a = np.zeros((8, 8, 3), np.float32)
    a[..., 0], a[..., 1], a[..., 2] = 0.85, 0.5, 0.85          # tangent-space normal tilted (+0.7, 0, +0.7)
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = _png_image(out_dir, "pkg321_nmap", a)
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nm.space = "TANGENT"
    nm.inputs["Strength"].default_value = 1.0
    nt.links.new(tex.outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], sock)


def _link_bump_image(nt, sock, out_dir):
    a = np.zeros((32, 32, 3), np.float32)
    a[...] = (np.sin(np.linspace(0, 6 * math.pi, 32, dtype=np.float32)) * 0.5 + 0.5)[None, :, None]
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = _png_image(out_dir, "pkg321_bump", a)
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 1.0
    bump.inputs["Distance"].default_value = 0.4
    nt.links.new(tex.outputs["Color"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], sock)


def _link_tangent_radial(nt, sock, out_dir):
    t = nt.nodes.new("ShaderNodeTangent")
    t.direction_type = "RADIAL"
    t.axis = "Z"
    nt.links.new(t.outputs["Tangent"], sock)


def _link_geometry_normal(nt, sock, out_dir):
    g = nt.nodes.new("ShaderNodeNewGeometry")
    nt.links.new(g.outputs["Normal"], sock)


LINKS = {"normal_map": _link_normal_map, "bump_image": _link_bump_image,
         "tangent_radial": _link_tangent_radial, "geometry_normal": _link_geometry_normal}


def _setv(node, key, val, notes):
    if key.startswith("prop:"):
        name = key[5:]
        if isinstance(val, tuple) and val and val[0] == "enum":
            items = [i.identifier for i in node.bl_rna.properties[name].enum_items]
            val = items[val[1]]
            notes.append(f"{name}={val}")
        setattr(node, name, val)
        return
    sock = node.inputs.get(key)
    if sock is None:
        raise KeyError(f"socket {key!r} missing on {node.bl_idname}; has {[s.name for s in node.inputs]}")
    sock.default_value = val


def build_material(p, variant, out_dir, scene_info):
    mat = bpy.data.materials.new(f"probe_{variant}")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    notes = []
    if p.get("custom") == "displacement":
        pr = nt.nodes.new("ShaderNodeBsdfPrincipled")
        pr.inputs["Base Color"].default_value = (0.6, 0.6, 0.6, 1)
        nt.links.new(pr.outputs["BSDF"], out.inputs["Surface"])
        d = nt.nodes.new("ShaderNodeDisplacement")
        d.inputs["Scale"].default_value = 0.3
        tex = nt.nodes.new("ShaderNodeTexImage")
        a = np.zeros((32, 32, 3), np.float32)
        a[...] = (np.sin(np.linspace(0, 6 * math.pi, 32, dtype=np.float32)) * 0.5 + 0.5)[None, :, None]
        tex.image = _png_image(out_dir, "pkg321_dispheight", a)
        nt.links.new(tex.outputs["Color"], d.inputs["Height"])
        if variant == "B":
            _link_normal_map(nt, d.inputs["Normal"], out_dir)
        nt.links.new(d.outputs["Displacement"], out.inputs["Displacement"])
        return mat, notes
    node = nt.nodes.new(p["node"])
    for k, v in p.get("pre", {}).items():
        _setv(node, k, v, notes)
    for k, v in p["A" if variant != "B" else "B"].items():
        _setv(node, k, v, notes)
    if variant == "B" and p.get("link"):
        LINKS[p["link"]](nt, node.inputs[p["link_socket"]], out_dir)
    if p["node"] == "ShaderNodeTexSky":
        return mat, notes
    out_name = p.get("out", "Surface")
    src = node.outputs.get("BSDF") or node.outputs.get("Volume") or node.outputs[0]
    nt.links.new(src, out.inputs[out_name])
    return mat, notes


def apply_sky(p, variant, scene_info, notes):
    sky = scene_info["sky"]
    for k, v in {**p.get("pre", {}), **p["A" if variant != "B" else "B"]}.items():
        _setv(sky, k, v, notes)


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
def render(scene, out_dir, stem):
    import glob
    for f in glob.glob(os.path.join(out_dir, stem + "*")):
        os.remove(f)
    scene.render.filepath = os.path.join(out_dir, stem)
    del CAPTURED[:]
    bpy.ops.render.render(write_still=True)
    warn = CAPTURED[-1] if CAPTURED else ""
    files = sorted(glob.glob(os.path.join(out_dir, stem + "*.exr")))
    if not files:
        raise RuntimeError("no render output")
    img = bpy.data.images.load(files[0])
    w, h = img.size
    px = np.asarray(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[:, :, :3]
    bpy.data.images.remove(img)
    os.remove(files[0])
    return np.ascontiguousarray(px[::-1]), warn


def run_probe(pid, p, out_dir, scene_info):
    scene = bpy.context.scene
    res = {"id": pid, "node": p["node"]}
    pix, warns, notes = {}, {}, []
    for variant in ("A", "A2", "B"):
        scene.cycles.seed = 322 if variant == "A2" else 321      # A2 = A under another seed: the noise floor
        if p["node"] == "ShaderNodeTexSky":
            # the Sky node lives in the world tree; rebuild the mutation each time
            apply_sky(p, variant, scene_info, notes if variant == "B" else [])
        else:
            mat, n = build_material(p, variant, out_dir, scene_info)
            if variant == "B":
                notes += n
            obj = scene_info["obj"]
            obj.data.materials.clear()
            obj.data.materials.append(mat)
            for old in [m for m in bpy.data.materials if m is not mat]:   # convert_materials walks every datablock
                bpy.data.materials.remove(old)
        t0 = time.time()
        pix[variant], warns[variant] = render(scene, out_dir, f"{pid}_{variant}")
        res.setdefault("seconds", {})[variant] = round(time.time() - t0, 2)
    a, a2, b = pix["A"], pix["A2"], pix["B"]
    res["mean_A"] = a.reshape(-1, 3).mean(0).tolist()
    res["mean_B"] = b.reshape(-1, 3).mean(0).tolist()
    res["d_ab"] = float(np.abs(a - b).mean())
    res["d_aa"] = float(np.abs(a - a2).mean())
    res["max_ab"] = float(np.abs(a - b).max())

    def blur(x):                      # 8x8 block means: averages the MC noise, keeps a systematic change
        h, w, c = x.shape
        return x.reshape(h // 8, 8, w // 8, 8, c).mean(axis=(1, 3))
    res["db_ab"] = float(np.abs(blur(a) - blur(b)).mean())
    res["db_aa"] = float(np.abs(blur(a) - blur(a2)).mean())
    res["finite"] = bool(np.isfinite(a).all() and np.isfinite(b).all())
    res["warn_A"], res["warn_B"] = warns["A"], warns["B"]
    res["notes"] = notes
    np.save(os.path.join(out_dir, f"{pid}_A.npy"), a)
    np.save(os.path.join(out_dir, f"{pid}_B.npy"), b)
    return res


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out_dir = argv[0]
    os.makedirs(out_dir, exist_ok=True)
    ids = argv[1:] or list(PROBES)
    addon = bootstrap()
    install_degradation_capture(addon)
    results, info, kind = {}, None, None
    for pid in sorted(ids, key=lambda i: (PROBES[i]["scene"], i)):
        p = PROBES[pid]
        try:
            if kind != p["scene"]:
                info = build_scene(p["scene"], out_dir)
                kind = p["scene"]
            if p["scene"] == "sky":      # reset the sky node to node defaults between probes
                info = build_scene("sky", out_dir)
            results[pid] = run_probe(pid, p, out_dir, info)
            r = results[pid]
            print(f"[pkg321] {pid}: d_ab={r['d_ab']:.3e} d_aa={r['d_aa']:.3e} warnB={r['warn_B'][:120]!r}", flush=True)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            results[pid] = {"id": pid, "error": f"{type(exc).__name__}: {exc}"}
            kind = None
        with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=1)
    print("PKG321_PROBES_DONE", flush=True)


main()
