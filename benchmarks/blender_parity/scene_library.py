# -*- coding: utf-8 -*-
"""pkg119 Phase B - minimal per-feature scene builders (runs INSIDE Blender).

Every builder takes the live ``bpy`` module and mutates the current file into a
single-object, single-light scene that exercises exactly one matrix feature, so
the CYCLES (oracle) and CUSTOM_RAYTRACER legs render the SAME geometry/lighting
and differ only in the engine. Follows the headless pattern of
``scripts/verify_pkg122_cycles_oracle.py`` and ``verify_pkg115_textures_blender.py``.

The generic shader-node builder is intentionally mechanical (it does not hand-
author a scene per node): it instantiates the node, inspects its *live* output
sockets, and wires a SHADER output straight to the Material Output or a
colour/scalar output through a Principled Base Color. That keeps the harness
self-updating as Blender adds nodes (same philosophy as the Phase-A enumerator).

Anything that raises here is caught by ``render_leg.py`` and reported as a
crashed leg (spec Phase-B "no crash on any feature"), which back-propagates to
close the Phase-A UNKNOWN cell.
"""

from __future__ import annotations

import math

# Dedicated-light energy configs mirror verify_pkg122_cycles_oracle.SCENES so the
# light legs reproduce the pkg122 radiometric setup exactly.
LIGHT_CONFIGS = {
    "POINT": dict(energy=800.0, height=3.0, extra={}),
    "AREA": dict(energy=300.0, height=3.0, extra={"size_x": 3.0, "size_y": 3.0}),
    "SPOT": dict(energy=800.0, height=3.0,
                 extra={"spot_size": math.radians(46.0), "spot_blend": 0.5}),
    "SUN": dict(energy=5.0, height=10.0, extra={"angle": math.radians(0.526)}),
}

COMPOSITE_SCENES = ("mix_shader_stack", "texture_driven_roughness", "bump_plus_normal")


# --------------------------------------------------------------------------- #
# Shared scaffolding
# --------------------------------------------------------------------------- #

def _reset(bpy):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return bpy.context.scene


def _add_world(bpy, scene, strength=0.15, color=(0.05, 0.05, 0.05)):
    world = bpy.data.worlds.new("W")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (color[0], color[1], color[2], 1.0)
    bg.inputs[1].default_value = strength
    return world


def _add_camera(bpy, scene, location=(0.0, -6.0, 1.5), look_down=False):
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "PERSP"
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = location
    if look_down:
        cam.location = (0.0, 0.0, 20.0)
        cam.rotation_euler = (0.0, 0.0, 0.0)
    else:
        # aim roughly at origin
        cam.rotation_euler = (math.radians(78.0), 0.0, 0.0)
    scene.camera = cam
    return cam


def _add_area_light(bpy, scene, energy=200.0, location=(2.0, -2.0, 4.0)):
    ld = bpy.data.lights.new("Key", type="AREA")
    ld.energy = energy
    ld.size = 2.0
    obj = bpy.data.objects.new("Key", ld)
    scene.collection.objects.link(obj)
    obj.location = location
    # point down-ish toward origin
    obj.rotation_euler = (math.radians(35.0), 0.0, math.radians(25.0))
    return obj


def _add_sphere(bpy, scene):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, location=(0.0, 0.0, 1.0))
    obj = bpy.context.active_object
    # smooth shading (memory: some effects need smooth normals; harmless here)
    for poly in obj.data.polygons:
        poly.use_smooth = True
    return obj


# Solid diffuse colours for the parity-safe backdrop bands (world X centre, RGB).
# Bands abut (2.0-wide planes at 2.0 spacing) to form a red/yellow/green/blue
# flag - spatial structure a transparent/refractive BSDF shows, built ONLY from
# plain diffuse BSDFs that the harness's passing cells prove Astroray renders
# identically to Cycles.
_BACKDROP_BANDS = (
    (-3.0, (0.85, 0.22, 0.18)),   # red
    (-1.0, (0.90, 0.80, 0.20)),   # yellow
    (1.0, (0.20, 0.70, 0.35)),    # green
    (3.0, (0.22, 0.35, 0.85)),    # blue
)


def _apply_solid_diffuse(bpy, obj, color):
    """Give ``obj`` a single solid-colour Diffuse BSDF (no procedural texture
    node). This is the exact material pattern the light-scene floor and the
    diffuse combiner inputs use, i.e. the parity-safe subset."""
    mat = bpy.data.materials.new("Solid")
    mat.use_nodes = True
    nt = mat.node_tree
    _clear_nodes(nt)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.inputs["Color"].default_value = (color[0], color[1], color[2], 1.0)
    nt.links.new(diff.outputs["BSDF"], out.inputs["Surface"])
    obj.data.materials.append(mat)
    return mat


def _add_backdrop(bpy, scene):
    """Parity-SAFE structured backdrop BEHIND the subject (camera at y=-6 looking
    +Y). A TRANSPARENT / refractive BSDF shows the background, so without a
    structured, lit backdrop the transparent-material scene renders a near-black
    frame where SSIM is meaningless (this false-convicted BSDF_TRANSPARENT in the
    2026-08-08 baseline).

    Structure is built from SOLID-COLOUR diffuse quads (vertical colour bands)
    plus a neutral fill plane - NOT a procedural texture. ShaderNodeTexChecker is
    NOT parity-safe in Astroray (lead HW re-triage 2026-08-08: the checker
    backdrop rendered flat grey in the Astroray leg -> SSIM 0.30, which measured
    checker-node parity, not the transparent BSDF). Do not reintroduce it. The
    backdrop-only parity is guarded by build_backdrop_probe_scene + its test."""
    objs = []
    # Neutral fill plane first so band gaps never show the world colour.
    bpy.ops.mesh.primitive_plane_add(size=20.0, location=(0.0, 5.2, 1.0))
    fill = bpy.context.active_object
    fill.rotation_euler = (math.radians(90.0), 0.0, 0.0)  # stand it up, face -Y
    _apply_solid_diffuse(bpy, fill, (0.55, 0.52, 0.50))
    objs.append(fill)
    for x, col in _BACKDROP_BANDS:
        bpy.ops.mesh.primitive_plane_add(size=2.0, location=(x, 4.5, 1.5))
        band = bpy.context.active_object
        band.scale = (1.0, 2.0, 1.0)                       # 2.0 wide x 4.0 tall
        band.rotation_euler = (math.radians(90.0), 0.0, 0.0)
        _apply_solid_diffuse(bpy, band, col)
        objs.append(band)
    return objs


# --------------------------------------------------------------------------- #
# Generic shader-node scene
# --------------------------------------------------------------------------- #

def _clear_nodes(nt):
    for n in list(nt.nodes):
        nt.nodes.remove(n)


def _first_output(node):
    for out in node.outputs:
        return out
    return None


def _shader_output(node):
    for out in node.outputs:
        if out.type == "SHADER":
            return out
    return None


def build_shader_node_scene(bpy, bl_idname: str):
    """Single sphere lit by one area light, its material driven by ``bl_idname``.

    SHADER-output nodes are wired straight to the Material Output Surface.
    Colour/scalar/vector nodes are wired through a Principled Base Color so they
    still produce a visible, oracle-comparable surface.

    A lit, coloured world + a checker backdrop behind the sphere guarantee a
    transparent/refractive BSDF has structured background to show instead of a
    near-black frame (see ``_add_backdrop``).
    """
    scene = _reset(bpy)
    _add_world(bpy, scene, strength=0.6, color=(0.35, 0.40, 0.50))
    sphere = _add_sphere(bpy, scene)
    _add_backdrop(bpy, scene)
    _add_area_light(bpy, scene)
    _add_camera(bpy, scene)

    mat = bpy.data.materials.new("Feat")
    mat.use_nodes = True
    nt = mat.node_tree
    _clear_nodes(nt)
    out = nt.nodes.new("ShaderNodeOutputMaterial")

    feat = nt.nodes.new(bl_idname)

    shader_out = _shader_output(feat)
    if shader_out is not None:
        # Multi-shader combiners need their shader inputs fed or they render black.
        _feed_shader_inputs(bpy, nt, feat)
        nt.links.new(shader_out, out.inputs["Surface"])
    else:
        principled = nt.nodes.new("ShaderNodeBsdfPrincipled")
        nt.links.new(principled.outputs["BSDF"], out.inputs["Surface"])
        fout = _first_output(feat)
        if fout is not None and "Base Color" in principled.inputs:
            nt.links.new(fout, principled.inputs["Base Color"])

    sphere.data.materials.append(mat)
    return scene


def _feed_shader_inputs(bpy, nt, feat):
    """For MIX_SHADER / ADD_SHADER (and any node with SHADER inputs), attach two
    contrasting Diffuse BSDFs so the combiner has something to combine."""
    shader_inputs = [s for s in feat.inputs if s.type == "SHADER"]
    if not shader_inputs:
        return
    colors = [(0.8, 0.1, 0.1, 1.0), (0.1, 0.2, 0.8, 1.0)]
    for i, sock in enumerate(shader_inputs[:2]):
        d = nt.nodes.new("ShaderNodeBsdfDiffuse")
        d.inputs["Color"].default_value = colors[i % len(colors)]
        nt.links.new(d.outputs["BSDF"], sock)


# --------------------------------------------------------------------------- #
# Light / camera / world scenes
# --------------------------------------------------------------------------- #

def build_light_scene(bpy, light_type: str, engine: str | None = None):
    """Gray Lambertian floor lit by one dedicated light, camera top-down.
    Mirrors verify_pkg122_cycles_oracle.build_scene (same energies)."""
    cfg = LIGHT_CONFIGS[light_type]
    scene = _reset(bpy)
    _add_world(bpy, scene, strength=0.0, color=(0.0, 0.0, 0.0))

    bpy.ops.mesh.primitive_plane_add(size=40.0, location=(0.0, 0.0, 0.0))
    floor = bpy.context.active_object
    mat = bpy.data.materials.new("Floor")
    mat.use_nodes = True
    nt = mat.node_tree
    _clear_nodes(nt)
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1.0)
    diff.inputs["Roughness"].default_value = 0.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(diff.outputs["BSDF"], out.inputs["Surface"])
    floor.data.materials.append(mat)

    _add_camera(bpy, scene, look_down=True)

    ld = bpy.data.lights.new("L", type=light_type)
    obj = bpy.data.objects.new("L", ld)
    scene.collection.objects.link(obj)
    obj.rotation_euler = (0.0, 0.0, 0.0)
    extra = cfg["extra"]
    ld.energy = cfg["energy"]
    if light_type == "SUN":
        ld.angle = extra.get("angle", math.radians(0.526))
        obj.location = (0.0, 0.0, 10.0)
    else:
        obj.location = (0.0, 0.0, cfg["height"])
        if light_type == "POINT":
            ld.shadow_soft_size = 0.0
        elif light_type == "AREA":
            ld.shape = "RECTANGLE"
            ld.size = extra["size_x"]
            ld.size_y = extra["size_y"]
            # pkg122 orientation finding: Astroray area normal is +Z; flip 180
            # about X for the Astroray leg so both legs light the floor below.
            if engine == "CUSTOM_RAYTRACER":
                obj.rotation_euler = (math.pi, 0.0, 0.0)
        elif light_type == "SPOT":
            ld.shadow_soft_size = 0.0
            ld.spot_size = extra["spot_size"]
            ld.spot_blend = extra["spot_blend"]
    return scene


def build_camera_scene(bpy):
    """Sphere + floor with a shallow depth-of-field camera (exercises the DoF /
    lens datablock properties the matrix marks SUPPORTED)."""
    scene = _reset(bpy)
    _add_world(bpy, scene, strength=0.3)
    sphere = _add_sphere(bpy, scene)
    mat = bpy.data.materials.new("Gray")
    mat.use_nodes = True
    sphere.data.materials.append(mat)
    _add_area_light(bpy, scene)
    cam = _add_camera(bpy, scene, location=(0.0, -6.0, 1.5))
    cam.data.lens = 50.0
    cam.data.dof.use_dof = True
    cam.data.dof.focus_distance = 6.0
    cam.data.dof.aperture_fstop = 1.4
    return scene


def build_world_scene(bpy):
    """Sphere under a coloured node-based world (exercises World.use_nodes)."""
    scene = _reset(bpy)
    _add_world(bpy, scene, strength=1.0, color=(0.15, 0.35, 0.6))
    sphere = _add_sphere(bpy, scene)
    mat = bpy.data.materials.new("Gray")
    mat.use_nodes = True
    sphere.data.materials.append(mat)
    _add_camera(bpy, scene)
    return scene


def build_backdrop_probe_scene(bpy):
    """Parity CANARY: the shader_node backdrop + world + light + camera with NO
    feature sphere, so both engine legs render ONLY the backdrop. The guard test
    (test_backdrop_is_parity_safe) asserts high SSIM here; if the backdrop ever
    stops rendering with parity in Astroray it fails HERE instead of silently
    contaminating the BSDF_TRANSPARENT differential (lead HW finding 2026-08-08).
    Must stay byte-for-byte the same backdrop as build_shader_node_scene."""
    scene = _reset(bpy)
    _add_world(bpy, scene, strength=0.6, color=(0.35, 0.40, 0.50))
    _add_backdrop(bpy, scene)
    _add_area_light(bpy, scene)
    _add_camera(bpy, scene)
    return scene


# --------------------------------------------------------------------------- #
# Composite scenes (owner-approved replacement for the cut .blend corpus)
# --------------------------------------------------------------------------- #

def build_mix_shader_stack(bpy):
    """Two-level Mix Shader: (Glossy mix Diffuse) mixed with Glass."""
    scene = _reset(bpy)
    _add_world(bpy, scene, strength=0.2)
    sphere = _add_sphere(bpy, scene)
    _add_area_light(bpy, scene)
    _add_camera(bpy, scene)

    mat = bpy.data.materials.new("MixStack")
    mat.use_nodes = True
    nt = mat.node_tree
    _clear_nodes(nt)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.inputs["Color"].default_value = (0.8, 0.2, 0.2, 1.0)
    gloss = nt.nodes.new("ShaderNodeBsdfGlossy")
    gloss.inputs["Roughness"].default_value = 0.1
    glass = nt.nodes.new("ShaderNodeBsdfGlass")
    mix1 = nt.nodes.new("ShaderNodeMixShader")
    mix1.inputs[0].default_value = 0.4
    mix2 = nt.nodes.new("ShaderNodeMixShader")
    mix2.inputs[0].default_value = 0.3
    nt.links.new(diff.outputs["BSDF"], mix1.inputs[1])
    nt.links.new(gloss.outputs["BSDF"], mix1.inputs[2])
    nt.links.new(mix1.outputs["Shader"], mix2.inputs[1])
    nt.links.new(glass.outputs["BSDF"], mix2.inputs[2])
    nt.links.new(mix2.outputs["Shader"], out.inputs["Surface"])
    sphere.data.materials.append(mat)
    return scene


def build_texture_driven_roughness(bpy):
    """Noise texture -> Principled Roughness (texture-driven scalar input)."""
    scene = _reset(bpy)
    _add_world(bpy, scene, strength=0.2)
    sphere = _add_sphere(bpy, scene)
    _add_area_light(bpy, scene)
    _add_camera(bpy, scene)

    mat = bpy.data.materials.new("TexRough")
    mat.use_nodes = True
    nt = mat.node_tree
    _clear_nodes(nt)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    principled = nt.nodes.new("ShaderNodeBsdfPrincipled")
    principled.inputs["Base Color"].default_value = (0.6, 0.6, 0.65, 1.0)
    principled.inputs["Metallic"].default_value = 1.0
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 6.0
    nt.links.new(noise.outputs["Fac"], principled.inputs["Roughness"])
    nt.links.new(principled.outputs["BSDF"], out.inputs["Surface"])
    sphere.data.materials.append(mat)
    return scene


def build_bump_plus_normal(bpy):
    """Bump node feeding a Principled Normal, driven by a wave texture."""
    scene = _reset(bpy)
    _add_world(bpy, scene, strength=0.25)
    sphere = _add_sphere(bpy, scene)
    _add_area_light(bpy, scene)
    _add_camera(bpy, scene)

    mat = bpy.data.materials.new("BumpNormal")
    mat.use_nodes = True
    nt = mat.node_tree
    _clear_nodes(nt)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    principled = nt.nodes.new("ShaderNodeBsdfPrincipled")
    principled.inputs["Base Color"].default_value = (0.7, 0.5, 0.3, 1.0)
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.inputs["Scale"].default_value = 8.0
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.6
    nt.links.new(wave.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], principled.inputs["Normal"])
    nt.links.new(principled.outputs["BSDF"], out.inputs["Surface"])
    sphere.data.materials.append(mat)
    return scene


COMPOSITE_BUILDERS = {
    "mix_shader_stack": build_mix_shader_stack,
    "texture_driven_roughness": build_texture_driven_roughness,
    "bump_plus_normal": build_bump_plus_normal,
}


def build_scene(bpy, category: str, feature: str, bl_idname: str = "",
                engine: str | None = None):
    """Dispatch on the matrix category to the right builder. Returns the scene."""
    if category == "shader_node":
        if not bl_idname:
            raise ValueError(f"shader_node feature {feature} needs a bl_idname")
        return build_shader_node_scene(bpy, bl_idname)
    if category == "light":
        return build_light_scene(bpy, feature, engine=engine)
    if category == "camera":
        return build_camera_scene(bpy)
    if category == "world":
        return build_world_scene(bpy)
    if category == "backdrop_probe":
        return build_backdrop_probe_scene(bpy)
    if category == "composite":
        builder = COMPOSITE_BUILDERS.get(feature)
        if builder is None:
            raise ValueError(f"unknown composite scene: {feature}")
        return builder(bpy)
    raise ValueError(f"no scene generator for category {category!r} "
                     f"(feature {feature!r})")
