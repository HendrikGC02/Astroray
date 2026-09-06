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

COMPOSITE_SCENES = (
    "mix_shader_stack", "texture_driven_roughness", "bump_plus_normal",
    "opvm_plain", "opvm_vector_math", "opvm_vector_rotate",
    "opvm_mix_clamped", "opvm_mix_unclamped",
    "coords_plain", "coords_arithmetic", "coords_euler", "coords_axis",
    "coords_mirror", "coords_program", "coords_shared_programs",
)


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
            # pkg181 (removes pkg122/pkg139 stale flip): pkg139 fixed the addon
            # area-light axis convention, so the identity-rotation Astroray leg now
            # lights the floor correctly. The old 180-deg flip now points the lamp
            # AWAY and renders the Astroray leg BLACK (pkg180 side-finding 1). Both
            # legs use identity rotation (obj.rotation_euler set to 0 above).
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


def build_vector_opvm_scene(bpy, variant):
    """pkg230: image-driven vector/color chains on a Principled UV chart.

    The plain image and clamped Mix are controls. Fixed linear image values,
    white world illumination and a front-facing plane isolate node semantics
    from geometry, glossy lobes and color-management differences.
    """
    scene = _reset(bpy)
    _add_world(bpy, scene, strength=1.0, color=(0.5, 0.5, 0.5))
    bpy.ops.mesh.primitive_plane_add(size=2.0)
    plane = bpy.context.active_object
    mat = bpy.data.materials.new('VectorChartMaterial')
    mat.use_nodes = True
    plane.data.materials.append(mat)
    nt = mat.node_tree
    diffuse = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    diffuse.inputs['Specular IOR Level'].default_value = 0.0
    diffuse.inputs['Roughness'].default_value = 0.0
    img = bpy.data.images.new("VectorChart", width=8, height=8, float_buffer=True)
    img.colorspace_settings.name = 'Non-Color'
    pixels = []
    for y in range(8):
        for x in range(8):
            pixels.extend((0.15 + 0.6 * x / 7, 0.15 + 0.6 * y / 7,
                           0.25 + 0.3 * ((x // 2 + y // 2) % 2), 1.0))
    img.pixels[:] = pixels
    img.pack()
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = img
    # pkg186 image sampling currently supports nearest on both backends.
    # Match that explicitly; Linear/Cubic filtering belongs to pkg234.
    tex.interpolation = 'Closest'
    source = tex.outputs['Color']
    if variant == 'vector_math':
        node = nt.nodes.new('ShaderNodeVectorMath')
        node.operation = 'MULTIPLY_ADD'
        nt.links.new(source, node.inputs[0])
        node.inputs[1].default_value = (0.6, 0.85, 0.45)
        node.inputs[2].default_value = (0.12, 0.04, 0.18)
        source = node.outputs['Vector']
    elif variant == 'vector_rotate':
        node = nt.nodes.new('ShaderNodeVectorRotate')
        node.rotation_type = 'EULER_XYZ'
        node.invert = True
        node.inputs['Center'].default_value = (0.5, 0.5, 0.5)
        node.inputs['Rotation'].default_value = (0.2, -0.3, 0.5)
        nt.links.new(source, node.inputs['Vector'])
        source = node.outputs['Vector']
    elif variant in ('mix_clamped', 'mix_unclamped'):
        node = nt.nodes.new('ShaderNodeMix')
        node.data_type = 'RGBA'
        node.blend_type = 'MIX'
        node.clamp_factor = variant == 'mix_clamped'
        node.clamp_result = False
        # Real Blender has duplicate Factor/A/B names for each data type.
        enabled = {s.name: s for s in node.inputs if s.enabled}
        enabled['Factor'].default_value = 1.4
        enabled['A'].default_value = (0.3, 0.3, 0.3, 1.0)
        nt.links.new(source, enabled['B'])
        source = next(s for s in node.outputs if s.enabled)
    elif variant != 'plain':
        raise ValueError(f'unknown vector op-VM variant: {variant}')
    nt.links.new(source, diffuse.inputs['Base Color'])
    camera_data = bpy.data.cameras.new('VectorChartCamera')
    camera_data.type = 'PERSP'
    camera_data.lens = 47.0
    camera = bpy.data.objects.new('VectorChartCamera', camera_data)
    scene.collection.objects.link(camera)
    camera.location = (0, 0, 3)
    scene.camera = camera
    scene.cycles.max_bounces = 2
    return scene


def build_affine_coordinate_scene(bpy, variant):
    """pkg230b: spatial operations before image lookup, including shared samplers."""
    scene = build_vector_opvm_scene(bpy, 'plain')
    plane = next(obj for obj in scene.objects if obj.type == 'MESH')

    def wire(material, mode):
        nt = material.node_tree
        image = next(node for node in nt.nodes if node.type == 'TEX_IMAGE')
        # Native image samplers clamp outside [0,1]. Match Extend here; Repeat
        # and the wider image-extension contract remain under pkg234.
        image.extension = 'EXTEND'
        principled = next(node for node in nt.nodes if node.type == 'BSDF_PRINCIPLED')
        source = nt.nodes.new('ShaderNodeTexCoord').outputs['UV']

        def vector_math(operation, constant, varying_slot=0):
            nonlocal source
            node = nt.nodes.new('ShaderNodeVectorMath')
            node.operation = operation
            nt.links.new(source, node.inputs[varying_slot])
            node.inputs[1 - varying_slot].default_value = constant
            source = node.outputs['Vector']

        # Keep the arithmetic/mirror chart inside the image domain so the
        # visible pattern tests placement rather than a clamped edge texel.
        if mode == 'arithmetic':
            vector_math('ADD', (0.13, -0.08, 0.0))
            vector_math('MULTIPLY', (0.8, 0.7, 1.0))
            vector_math('SUBTRACT', (1.05, 0.85, 0.0), varying_slot=1)
            mapping = nt.nodes.new('ShaderNodeMapping')
            mapping.inputs['Rotation'].default_value = (0.0, 0.0, 0.17)
            mapping.inputs['Location'].default_value = (0.04, 0.02, 0.0)
            nt.links.new(source, mapping.inputs['Vector'])
            source = mapping.outputs['Vector']
        elif mode in ('euler', 'axis', 'program'):
            rotate = nt.nodes.new('ShaderNodeVectorRotate')
            rotate.rotation_type = 'AXIS_ANGLE' if mode == 'axis' else 'EULER_XYZ'
            rotate.invert = True
            rotate.inputs['Center'].default_value = (0.42, 0.57, 0.1)
            if mode == 'axis':
                rotate.inputs['Axis'].default_value = (0.2, 0.3, 1.0)
                rotate.inputs['Angle'].default_value = 0.65
            else:
                rotate.inputs['Rotation'].default_value = (0.2, -0.3, 0.55)
            nt.links.new(source, rotate.inputs['Vector'])
            source = rotate.outputs['Vector']
        elif mode == 'mirror':
            vector_math('MULTIPLY', (-0.8, 0.8, 1.0))
            vector_math('ADD', (0.9, 0.08, 0.0))
        elif mode != 'plain':
            raise ValueError(f'unknown affine coordinate variant: {mode}')
        nt.links.new(source, image.inputs['Vector'])
        if variant in ('program', 'shared_programs'):
            post = nt.nodes.new('ShaderNodeVectorMath')
            post.operation = 'SCALE'
            post.inputs['Scale'].default_value = 0.8
            nt.links.new(image.outputs['Color'], post.inputs[0])
            nt.links.new(post.outputs['Vector'], principled.inputs['Base Color'])

    if variant == 'shared_programs':
        # Independent materials share the SAME bpy image. Each program must
        # carry its own mapping into the GPU descriptor, regardless of order.
        right = plane.copy()
        right.data = plane.data.copy()
        scene.collection.objects.link(right)
        right.data.materials.clear()
        right.data.materials.append(plane.data.materials[0].copy())
        plane.scale.x = right.scale.x = 0.5
        plane.location.x, right.location.x = -0.5, 0.5
        wire(plane.data.materials[0], 'euler')
        wire(right.data.materials[0], 'mirror')
    else:
        wire(plane.data.materials[0], variant)
    return scene


COMPOSITE_BUILDERS = {
    "mix_shader_stack": build_mix_shader_stack,
    "texture_driven_roughness": build_texture_driven_roughness,
    "bump_plus_normal": build_bump_plus_normal,
    "opvm_plain": lambda bpy: build_vector_opvm_scene(bpy, 'plain'),
    "opvm_vector_math": lambda bpy: build_vector_opvm_scene(bpy, 'vector_math'),
    "opvm_vector_rotate": lambda bpy: build_vector_opvm_scene(bpy, 'vector_rotate'),
    "opvm_mix_clamped": lambda bpy: build_vector_opvm_scene(bpy, 'mix_clamped'),
    "opvm_mix_unclamped": lambda bpy: build_vector_opvm_scene(bpy, 'mix_unclamped'),
    "coords_plain": lambda bpy: build_affine_coordinate_scene(bpy, 'plain'),
    "coords_arithmetic": lambda bpy: build_affine_coordinate_scene(bpy, 'arithmetic'),
    "coords_euler": lambda bpy: build_affine_coordinate_scene(bpy, 'euler'),
    "coords_axis": lambda bpy: build_affine_coordinate_scene(bpy, 'axis'),
    "coords_mirror": lambda bpy: build_affine_coordinate_scene(bpy, 'mirror'),
    "coords_program": lambda bpy: build_affine_coordinate_scene(bpy, 'program'),
    "coords_shared_programs": lambda bpy: build_affine_coordinate_scene(bpy, 'shared_programs'),
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
    if category == "reference_scene":
        spec = REFERENCE_SCENES.get(feature)
        if spec is None:
            raise ValueError(f"unknown reference scene: {feature}")
        return spec["builder"](bpy)
    raise ValueError(f"no scene generator for category {category!r} "
                     f"(feature {feature!r})")


# --------------------------------------------------------------------------- #
# Pillar-4 exit-gate (c) pinned reference-scene corpus
#
# Three standalone .blend assets (not per-feature diff scenes) exported by
# harness.py --export-blend for the north-star doc's gate (c): "three
# reference scenes render CPU+GPU, no exception, parity-clean". Each builder
# is deterministic (fixed seeds, no wall-clock/randomness left to chance): a
# re-run reproduces byte-identical GEOMETRY (vertex/curve-point positions,
# node graphs). The saved .blend FILE bytes are not guaranteed identical
# across runs - Blender embeds its own save-time metadata (thumbnail preview,
# session/undo state) independent of scene content - so manifest.json pins
# the SHA-256 of the actual committed .blend, not a reproducibility promise.
# --------------------------------------------------------------------------- #

def _look_at(obj, target):
    """Point ``obj`` (camera/light) at ``target`` (a 3-tuple), +Z up.

    Standard Blender "track to" pattern (object looks down local -Z, local Y
    is up) - avoids hand-picked Euler angles that are easy to get wrong.
    """
    import mathutils
    direction = mathutils.Vector(target) - mathutils.Vector(obj.location)
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _add_pinned_camera(bpy, scene, location, target, lens=35.0):
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "PERSP"
    cam_data.lens = lens
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = location
    _look_at(cam, target)
    scene.camera = cam
    return cam


def _apply_principled(bpy, obj, color, *, roughness=0.9, metallic=0.0,
                       transmission=0.0, alpha=1.0, ior=1.45, name="Mat"):
    """A Principled-BSDF material with the common sweep knobs pre-wired."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    principled = nt.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = (color[0], color[1], color[2], 1.0)
    principled.inputs["Roughness"].default_value = roughness
    principled.inputs["Metallic"].default_value = metallic
    principled.inputs["Transmission Weight"].default_value = transmission
    principled.inputs["IOR"].default_value = ior
    principled.inputs["Alpha"].default_value = alpha
    if alpha < 1.0:
        mat.blend_method = "BLEND"
    obj.data.materials.append(mat)
    return mat, principled


# ---- 1. cornell_interior --------------------------------------------------- #
#
# Ported from tests/scenes/disney_cornell.py (a native, non-Blender scene
# builder): the SAME box half-extent (S=1), the SAME wall colours
# (white/red/green), and the SAME ceiling-area-light footprint (0.6x0.6,
# flush under the ceiling). disney_cornell.py's four material spheres
# (lambertian/metal/dielectric/disney) are replaced by the classic Cornell
# "tall block" + "short block" pair the task calls for, since a literal port
# of four spheres is not a "Cornell-class interior" in the canonical sense;
# walls/floor/ceiling/blocks all use Principled BSDF (roughness~1, no
# specular tint) so they read as the Lambertian surfaces disney_cornell.py
# itself uses. disney_cornell.py's Y-up axis (their "y" = height) maps to
# Blender's Z-up; their depth axis "z" maps to Blender Y.
def build_cornell_interior_scene(bpy):
    scene = _reset(bpy)
    S = 1.0

    def wall(name, color, location, rot_x=0.0, rot_y=0.0):
        bpy.ops.mesh.primitive_plane_add(size=2.0 * S, location=location)
        obj = bpy.context.active_object
        obj.name = name
        obj.rotation_euler = (math.radians(rot_x), math.radians(rot_y), 0.0)
        _apply_principled(bpy, obj, color, roughness=1.0, name=f"{name}Mat")
        return obj

    white = (0.73, 0.73, 0.73)
    red = (0.65, 0.05, 0.05)
    green = (0.12, 0.45, 0.15)
    wall("Floor", white, (0.0, 0.0, -S), rot_x=0.0)
    wall("Ceiling", white, (0.0, 0.0, S), rot_x=180.0)
    wall("BackWall", white, (0.0, S, 0.0), rot_x=-90.0)
    wall("FrontWall", white, (0.0, -S, 0.0), rot_x=90.0)
    wall("LeftWall", red, (-S, 0.0, 0.0), rot_y=90.0)
    wall("RightWall", green, (S, 0.0, 0.0), rot_y=-90.0)

    def block(name, size, location, rot_z_deg):
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
        obj = bpy.context.active_object
        obj.name = name
        # cube_add(size=1.0) spans [-0.5, 0.5] per axis (edge length 1.0), so
        # scale == the desired edge length directly (NOT size/2).
        obj.scale = (size[0], size[1], size[2])
        obj.rotation_euler = (0.0, 0.0, math.radians(rot_z_deg))
        _apply_principled(bpy, obj, (0.72, 0.70, 0.68), roughness=0.9, name=f"{name}Mat")
        return obj

    # Short block: front-right, cube, sitting on the floor.
    short_h = 0.6
    block("ShortBlock", (0.6, 0.6, short_h), (0.32, -0.28, -S + short_h / 2.0), 18.0)
    # Tall block: back-left, twice the height, sitting on the floor.
    tall_h = 1.2
    block("TallBlock", (0.6, 0.6, tall_h), (-0.32, 0.28, -S + tall_h / 2.0), -18.0)

    # Ceiling area light — same 0.6x0.6 footprint as disney_cornell's LH=0.3
    # half-extent, flush under the ceiling.
    ld = bpy.data.lights.new("CeilingLight", type="AREA")
    ld.shape = "RECTANGLE"
    ld.size = 0.6
    ld.size_y = 0.6
    ld.energy = 34.0
    ld.color = (1.0, 1.0, 1.0)
    light_obj = bpy.data.objects.new("CeilingLight", ld)
    scene.collection.objects.link(light_obj)
    light_obj.location = (0.0, 0.0, S - 0.001)
    light_obj.rotation_euler = (math.radians(180.0), 0.0, 0.0)  # emit downward (-Z)

    _add_world(bpy, scene, strength=0.0, color=(0.0, 0.0, 0.0))
    # Camera just inside the (closed) front wall, aimed at the back wall —
    # disney_cornell.py's look_from=[0,0,0.95] look_at=[0,0,0] vfov=60.
    cam = _add_pinned_camera(bpy, scene, (0.0, -S + 0.05, 0.0), (0.0, S, 0.0), lens=18.0)
    cam.data.sensor_fit = "VERTICAL"
    cam.data.angle_y = math.radians(60.0)
    return scene


REFERENCE_CORNELL_RES = (512, 512)
REFERENCE_CORNELL_SAMPLES = 64


# ---- 2. material_zoo -------------------------------------------------------- #
#
# 4x4 Principled matrix on a plane, sun lamp, plain-colour world. Rows 0-2 are
# clean metallic/roughness/transmission sweeps; row 3 carries a light alpha
# demo plus the three texture-driven spheres the spec calls out (checker on
# GENERATED coordinates, an authored-UV image texture, a normal-mapped
# sphere) - see the manifest's "material_zoo_grid" table for the exact
# per-cell parameters (CLAUDE.md S1: stating the interpretation explicitly
# since "4x4 matrix" and "4 sweep axes x4 steps + 3 texture spheres" cannot
# both be literal without exceeding 16 cells).
def _make_checker_image_pixels(width, height):
    """A small deterministic tangent-space normal-map image (numpy-free, pure
    Python so this module has no extra runtime dependency): a low-frequency
    bump field encoded as an RGB normal map."""
    pixels = []
    for y in range(height):
        for x in range(width):
            u = x / (width - 1)
            v = y / (height - 1)
            # Two overlapping sine bumps -> analytic surface gradient -> normal.
            dzdx = 0.6 * math.cos(u * 6.0 * math.pi) * (6.0 * math.pi) * 0.05
            dzdy = 0.6 * math.cos(v * 4.0 * math.pi) * (4.0 * math.pi) * 0.05
            nx, ny, nz = -dzdx, -dzdy, 1.0
            n = math.sqrt(nx * nx + ny * ny + nz * nz)
            nx, ny, nz = nx / n, ny / n, nz / n
            # Tangent-space normal map encoding: [-1,1] -> [0,1].
            pixels.extend((nx * 0.5 + 0.5, ny * 0.5 + 0.5, nz * 0.5 + 0.5, 1.0))
    return pixels


def _make_stripe_image_pixels(width, height):
    """A small deterministic colour-stripe image for the authored-UV
    TexImage sphere, distinct in pattern from the procedural checker."""
    pixels = []
    for y in range(height):
        for x in range(width):
            band = (x * 5) // width
            colors = ((0.85, 0.2, 0.2), (0.9, 0.75, 0.15), (0.2, 0.7, 0.35),
                      (0.2, 0.4, 0.85), (0.55, 0.2, 0.75))
            r, g, b = colors[band % len(colors)]
            shade = 0.7 + 0.3 * (y / (height - 1))
            pixels.extend((r * shade, g * shade, b * shade, 1.0))
    return pixels


def build_material_zoo_scene(bpy):
    scene = _reset(bpy)
    _add_world(bpy, scene, strength=1.0, color=(0.045, 0.045, 0.05))

    bpy.ops.mesh.primitive_plane_add(size=8.0, location=(0.0, 0.0, 0.0))
    plane = bpy.context.active_object
    plane.name = "Ground"
    _apply_principled(bpy, plane, (0.4, 0.4, 0.42), roughness=0.8, name="GroundMat")

    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = 3.0
    sun_data.angle = math.radians(1.0)
    sun_obj = bpy.data.objects.new("Sun", sun_data)
    scene.collection.objects.link(sun_obj)
    sun_obj.rotation_euler = (math.radians(52.0), 0.0, math.radians(35.0))

    spacing = 1.4
    radius = 0.5
    n_cols, n_rows = 4, 4
    x0 = -spacing * (n_cols - 1) / 2.0
    y0 = -spacing * (n_rows - 1) / 2.0

    checker_img = bpy.data.images.new("ZooNormalMap", width=16, height=16, float_buffer=True)
    checker_img.colorspace_settings.name = "Non-Color"
    checker_img.pixels[:] = _make_checker_image_pixels(16, 16)
    checker_img.pack()

    stripe_img = bpy.data.images.new("ZooStripe", width=16, height=16, float_buffer=True)
    stripe_img.pixels[:] = _make_stripe_image_pixels(16, 16)
    stripe_img.pack()

    def sphere_at(col, row, name):
        x = x0 + col * spacing
        y = y0 + row * spacing
        bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=(x, y, radius),
                                              segments=24, ring_count=12)
        obj = bpy.context.active_object
        obj.name = name
        for poly in obj.data.polygons:
            poly.use_smooth = True
        return obj

    grid = []
    # Row 0: metallic sweep.
    for c, m in enumerate((0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0)):
        obj = sphere_at(c, 0, f"MetallicSweep_{c}")
        _apply_principled(bpy, obj, (0.75, 0.2, 0.15), roughness=0.3, metallic=m,
                           name=f"MetallicMat{c}")
        grid.append({"row": 0, "col": c, "kind": "metallic_sweep", "metallic": m})

    # Row 1: roughness sweep.
    for c, r in enumerate((0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0)):
        obj = sphere_at(c, 1, f"RoughnessSweep_{c}")
        _apply_principled(bpy, obj, (0.2, 0.55, 0.8), roughness=r, metallic=0.0,
                           name=f"RoughnessMat{c}")
        grid.append({"row": 1, "col": c, "kind": "roughness_sweep", "roughness": r})

    # Row 2: transmission sweep (glass-like).
    for c, t in enumerate((0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0)):
        obj = sphere_at(c, 2, f"TransmissionSweep_{c}")
        _apply_principled(bpy, obj, (0.95, 0.95, 0.95), roughness=0.05, metallic=0.0,
                           transmission=t, ior=1.45, name=f"TransmissionMat{c}")
        grid.append({"row": 2, "col": c, "kind": "transmission_sweep", "transmission": t})

    # Row 3: alpha demo + the three texture-driven spheres.
    obj = sphere_at(0, 3, "AlphaDemo")
    _apply_principled(bpy, obj, (0.8, 0.8, 0.2), roughness=0.4, alpha=0.4,
                       name="AlphaMat")
    grid.append({"row": 3, "col": 0, "kind": "alpha_demo", "alpha": 0.4})

    obj = sphere_at(1, 3, "CheckerGenerated")
    mat, principled = _apply_principled(bpy, obj, (1.0, 1.0, 1.0), roughness=0.4,
                                         name="CheckerMat")
    nt = mat.node_tree
    coord = nt.nodes.new("ShaderNodeTexCoord")
    checker = nt.nodes.new("ShaderNodeTexChecker")
    checker.inputs["Scale"].default_value = 6.0
    checker.inputs["Color1"].default_value = (0.05, 0.05, 0.05, 1.0)
    checker.inputs["Color2"].default_value = (0.9, 0.9, 0.9, 1.0)
    nt.links.new(coord.outputs["Generated"], checker.inputs["Vector"])
    nt.links.new(checker.outputs["Color"], principled.inputs["Base Color"])
    grid.append({"row": 3, "col": 1, "kind": "checker_generated_uv"})

    obj = sphere_at(2, 3, "ImageAuthoredUV")
    mat, principled = _apply_principled(bpy, obj, (1.0, 1.0, 1.0), roughness=0.4,
                                         name="ImageUVMat")
    nt = mat.node_tree
    coord = nt.nodes.new("ShaderNodeTexCoord")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = stripe_img
    nt.links.new(coord.outputs["UV"], tex.inputs["Vector"])
    nt.links.new(tex.outputs["Color"], principled.inputs["Base Color"])
    grid.append({"row": 3, "col": 2, "kind": "image_authored_uv"})

    obj = sphere_at(3, 3, "NormalMapped")
    mat, principled = _apply_principled(bpy, obj, (0.6, 0.6, 0.65), roughness=0.35,
                                         name="NormalMapMat")
    nt = mat.node_tree
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = checker_img
    normal_map = nt.nodes.new("ShaderNodeNormalMap")
    normal_map.space = "TANGENT"
    normal_map.inputs["Strength"].default_value = 1.0
    nt.links.new(tex.outputs["Color"], normal_map.inputs["Color"])
    nt.links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])
    grid.append({"row": 3, "col": 3, "kind": "normal_mapped"})

    scene["material_zoo_grid"] = grid  # id-property, cheap manifest source

    center = (0.0, 0.0, radius)
    cam_pos = (0.0, -6.4, 4.6)
    _add_pinned_camera(bpy, scene, cam_pos, center, lens=32.0)
    return scene


REFERENCE_MATERIAL_ZOO_RES = (640, 360)
REFERENCE_MATERIAL_ZOO_SAMPLES = 64


# ---- 3. hdri_exterior_hair --------------------------------------------------- #
#
# Ground plane + a Curves (hair) object grown from a UV-sphere scalp (roots
# placed on the scalp's sphere surface, radial + gravity-drooped strands) +
# one glass sphere, world lit ONLY by an HDRI (ShaderNodeTexEnvironment, no
# sun). ``bpy.ops.curves.primitive_random_sphere`` does not exist in Blender
# 5.2 (probed live; only ``object.curves_random_add`` /
# ``object.curves_empty_hair_add`` exist and neither takes a strand count) so
# strands are built directly via the Curves.add_curves() + position_data
# 5.x API for a deterministic, exact strand count - the "equivalent 5.2 API"
# the task anticipates.
_HAIR_STRANDS = 2400
_HAIR_POINTS_PER_STRAND = 6
_HDRI_RELPATH = "//../../../samples/test_env.hdr"  # scenes/ -> repo root is 3 ups


def _build_hair_curves(bpy, scalp_obj, scalp_radius, n_strands, points_per_strand, seed=1234):
    import random
    rng = random.Random(seed)
    sizes = [points_per_strand] * n_strands
    curves_data = bpy.data.hair_curves.new("HairCurves")
    curves_data.add_curves(sizes)

    positions = []
    radii = []
    scalp_center = tuple(scalp_obj.location)
    for _ in range(n_strands):
        u, v = rng.random(), rng.random()
        theta = 2.0 * math.pi * u
        phi = math.acos(1.0 - v * 0.9)  # bias roots toward the upper hemisphere
        nx = math.sin(phi) * math.cos(theta)
        ny = math.sin(phi) * math.sin(theta)
        nz = math.cos(phi)
        root = (scalp_center[0] + nx * scalp_radius,
                scalp_center[1] + ny * scalp_radius,
                scalp_center[2] + nz * scalp_radius)
        strand_len = 0.18 + rng.random() * 0.10
        droop = rng.random() * 0.35
        for p in range(points_per_strand):
            t = p / (points_per_strand - 1)
            positions.append((
                root[0] + nx * strand_len * t,
                root[1] + ny * strand_len * t,
                root[2] + nz * strand_len * t - droop * t * t,
            ))
            radii.append(0.0015 * (1.0 - 0.5 * t))

    flat_positions = [c for p in positions for c in p]
    curves_data.position_data.foreach_set("vector", flat_positions)
    curves_data.attributes.new("radius", "FLOAT", "POINT")
    curves_data.attributes["radius"].data.foreach_set("value", radii)
    curves_data.surface = scalp_obj
    curves_data.update_tag()
    return curves_data


def build_hdri_exterior_hair_scene(bpy):
    import os
    scene = _reset(bpy)

    bpy.ops.mesh.primitive_plane_add(size=20.0, location=(0.0, 0.0, 0.0))
    ground = bpy.context.active_object
    ground.name = "Ground"
    _apply_principled(bpy, ground, (0.25, 0.27, 0.24), roughness=0.85, name="GroundMat")

    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, location=(0.0, 0.0, 0.9),
                                          segments=32, ring_count=16)
    scalp = bpy.context.active_object
    scalp.name = "Scalp"
    for poly in scalp.data.polygons:
        poly.use_smooth = True
    _apply_principled(bpy, scalp, (0.62, 0.5, 0.42), roughness=0.6, name="ScalpMat")

    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.42, location=(1.35, 0.4, 0.42),
                                          segments=32, ring_count=16)
    glass_obj = bpy.context.active_object
    glass_obj.name = "GlassSphere"
    for poly in glass_obj.data.polygons:
        poly.use_smooth = True
    gm = bpy.data.materials.new("GlassMat")
    gm.use_nodes = True
    gnt = gm.node_tree
    _clear_nodes(gnt)
    gout = gnt.nodes.new("ShaderNodeOutputMaterial")
    glass = gnt.nodes.new("ShaderNodeBsdfGlass")
    glass.inputs["IOR"].default_value = 1.45
    glass.inputs["Roughness"].default_value = 0.0
    gnt.links.new(glass.outputs["BSDF"], gout.inputs["Surface"])
    glass_obj.data.materials.append(gm)

    curves_data = _build_hair_curves(bpy, scalp, scalp_radius=0.5,
                                      n_strands=_HAIR_STRANDS,
                                      points_per_strand=_HAIR_POINTS_PER_STRAND)
    hair_obj = bpy.data.objects.new("Hair", curves_data)
    scene.collection.objects.link(hair_obj)
    hmat = bpy.data.materials.new("HairMat")
    hmat.use_nodes = True
    hnt = hmat.node_tree
    _clear_nodes(hnt)
    hout = hnt.nodes.new("ShaderNodeOutputMaterial")
    hair_bsdf = hnt.nodes.new("ShaderNodeBsdfHairPrincipled")
    hair_bsdf.inputs["Color"].default_value = (0.22, 0.11, 0.06, 1.0)
    hair_bsdf.inputs["Roughness"].default_value = 0.3
    hnt.links.new(hair_bsdf.outputs["BSDF"], hout.inputs["Surface"])
    hair_obj.data.materials.append(hmat)

    # World: HDRI only, no sun - the environment map is the sole light source.
    world = bpy.data.worlds.new("W")
    scene.world = world
    world.use_nodes = True
    wnt = world.node_tree
    _clear_nodes(wnt)
    wout = wnt.nodes.new("ShaderNodeOutputWorld")
    env = wnt.nodes.new("ShaderNodeTexEnvironment")
    # repo root: this file lives at <repo>/benchmarks/blender_parity/scene_library.py
    repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    hdr_abs = os.path.join(repo_root, "samples", "test_env.hdr")
    img = bpy.data.images.load(hdr_abs)
    env.image = img
    wnt.links.new(env.outputs["Color"], wout.inputs["Surface"])
    # Store the intended repo-relative path; harness.py's export step rewrites
    # img.filepath_raw to this string AFTER the .blend has a real filepath
    # (relative resolution needs bpy.data.filepath to be set first).
    scene["hdri_relpath"] = _HDRI_RELPATH

    cam_pos = (0.0, -3.2, 1.15)
    cam_target = (0.1, 0.3, 0.85)
    _add_pinned_camera(bpy, scene, cam_pos, cam_target, lens=30.0)
    return scene


REFERENCE_HDRI_HAIR_RES = (640, 360)
REFERENCE_HDRI_HAIR_SAMPLES = 64


REFERENCE_SCENES = {
    "cornell_interior": dict(
        builder=build_cornell_interior_scene,
        res_x=REFERENCE_CORNELL_RES[0], res_y=REFERENCE_CORNELL_RES[1],
        samples=REFERENCE_CORNELL_SAMPLES),
    "material_zoo": dict(
        builder=build_material_zoo_scene,
        res_x=REFERENCE_MATERIAL_ZOO_RES[0], res_y=REFERENCE_MATERIAL_ZOO_RES[1],
        samples=REFERENCE_MATERIAL_ZOO_SAMPLES),
    "hdri_exterior_hair": dict(
        builder=build_hdri_exterior_hair_scene,
        res_x=REFERENCE_HDRI_HAIR_RES[0], res_y=REFERENCE_HDRI_HAIR_RES[1],
        samples=REFERENCE_HDRI_HAIR_SAMPLES),
}
