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


# ---- 4/5. pkg259 Phase 1 -- materials_hall + textures_mapping ------------- #
#
# Corpus scenes for pkg259 (Cycles feature-coverage reference corpus, Phase 1).
# Design: .astroray_plan/docs/reference-corpus-design-2026-09.md Sec 1.1/1.2/6.
# Each builder returns (scene, tags, crop_rects, gap_tags):
#   tags       -- list[(bl_idname, socket_or_prop)] this scene ACTIVELY wires
#                 (connected/non-default AND visible in a crop region) --
#                 build_corpus.py cross-checks this list against every
#                 SUPPORTED/APPROXIMATED coverage_matrix.json row assigned to
#                 the family and fails loudly if one is missing (Sec 4.1's
#                 coverage-claim rule: a row may only be claimed if actively
#                 demonstrated, not merely "the node exists somewhere").
#   crop_rects -- dict[str, [x0, y0, x1, y1]] normalised image-space crop per
#                 alcove/proof group, for the Phase-4 coverage report.
#   gap_tags   -- list[(bl_idname, socket_or_prop)] DROPPED-SILENT rows this
#                 scene deliberately makes visible (gap cards); every other
#                 DROPPED-SILENT row for the family is listed in the README's
#                 gap registry instead (design doc Sec 4.4).

def _layout_slots(slots, gap=0.6):
    """Lay ``slots`` (list of (name, width)) left-to-right along X with a
    fixed gap, centred on x=0. Returns {name: (center_x, half_width)} and the
    total corridor/workshop width."""
    x = 0.0
    centers = {}
    for name, width in slots:
        centers[name] = (x + width / 2.0, width / 2.0)
        x += width + gap
    total = x - gap
    shift = total / 2.0
    return {k: (cx - shift, hw) for k, (cx, hw) in centers.items()}, total


def _crop_rect(cam_distance, fov_x_rad, x0, x1, y0=0.06, y1=0.94):
    """Normalised-image-coordinate crop for an X range at the object plane,
    given a camera looking straight down +Y from ``cam_distance`` away with
    horizontal field of view ``fov_x_rad``. A linear pinhole approximation --
    adequate for the Phase-4 coverage report; not a claim of sub-pixel
    accuracy (open item: refine if a future crop render disagrees)."""
    half_at_dist = cam_distance * math.tan(fov_x_rad / 2.0)
    u0 = 0.5 + x0 / (2.0 * half_at_dist)
    u1 = 0.5 + x1 / (2.0 * half_at_dist)
    lo, hi = (u0, u1) if u0 <= u1 else (u1, u0)
    return [round(max(0.0, lo), 4), y0, round(min(1.0, hi), 4), y1]


def _pedestal(bpy, cx, width, depth=1.1, height=0.4, color=(0.5, 0.42, 0.32), name="Pedestal"):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(cx, 0.0, height / 2.0))
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (max(width, 0.4), depth, height)
    _apply_principled(bpy, obj, color, roughness=0.65, name=f"{name}Mat")
    return obj


def _small_sphere(bpy, x, y, z, radius=0.32, name="S", segments=24, ring_count=12):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=(x, y, z),
                                          segments=segments, ring_count=ring_count)
    obj = bpy.context.active_object
    obj.name = name
    for poly in obj.data.polygons:
        poly.use_smooth = True
    return obj


def _sock(collection, name):
    """Look up a node input/output socket by name via identifier match
    instead of ``collection["Name"]``. A large corpus scene creates many
    hundreds of distinct node-trees in one Blender session, and past some
    node count the bpy_prop_collection string-keyed getitem/``in`` for
    NodeSocket collections starts spuriously raising KeyError for sockets
    that are plainly present under iteration (reproduced in isolation:
    identical code path, only the prior node count differs) -- apparently
    an RNA string-interning ceiling in this Blender build, not a logic bug
    in this file. Iterating and matching by ``identifier`` (falling back to
    ``name``) sidesteps it and is the pattern used throughout this Phase-1
    corpus code."""
    for s in collection:
        if getattr(s, "identifier", None) == name or s.name == name:
            return s
    raise KeyError(f"no socket named {name!r} in {collection!r}")


def _bare_material(bpy, name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    _clear_nodes(nt)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    return mat, nt, out


def _emission_card_material(bpy, name, strength=1.6):
    mat, nt, out = _bare_material(bpy, name)
    emit = nt.nodes.new("ShaderNodeEmission")
    _sock(emit.inputs, "Strength").default_value = strength
    nt.links.new(_sock(emit.outputs, "Emission"), _sock(out.inputs, "Surface"))
    return mat, nt, emit, out


def _proof_plane(bpy, x, y, z, size=0.85, name="Proof"):
    bpy.ops.mesh.primitive_plane_add(size=size, location=(x, y, z))
    obj = bpy.context.active_object
    obj.name = name
    obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    for poly in obj.data.polygons:
        poly.use_smooth = True
    return obj


# --------------------------------------------------------------------------- #
# materials_hall
# --------------------------------------------------------------------------- #

def build_materials_hall_scene(bpy):
    """Every BSDF/closure Cycles ships, staged as one gallery corridor: one
    alcove per closure family, a fixed 3-point + warm practical light rig
    shared by every alcove (so BSDF differences read against one lighting
    reference), glass lifted off its pedestal, everything shade-smooth.
    Covers all 56 SUPPORTED/APPROXIMATED materials_hall matrix rows
    (10 SUPPORTED + 46 APPROXIMATED as of the post-pkg253 matrix); the 110
    DROPPED-SILENT rows are listed in the corpus README's gap registry
    (one -- SCRIPT -- gets an in-scene placard, Alcove I)."""
    scene = _reset(bpy)
    _add_world(bpy, scene, strength=0.30, color=(0.05, 0.05, 0.07))
    tags = []
    gap_tags = []
    crop_rects = {}

    def tag(bl, sock):
        tags.append((bl, sock))

    PEDESTAL_TOP = 0.4

    # Hall shell (warm stone tones, not grey -- composition rule).
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.0, 0.0, 0.0))
    floor = bpy.context.active_object
    floor.name = "HallFloor"
    floor.scale = (17.0, 3.2, 1.0)
    _apply_principled(bpy, floor, (0.28, 0.24, 0.20), roughness=0.85, name="FloorMat")

    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.0, 2.6, 2.4))
    wall = bpy.context.active_object
    wall.name = "HallBackWall"
    wall.scale = (17.0, 2.4, 1.0)
    wall.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    _apply_principled(bpy, wall, (0.40, 0.36, 0.32), roughness=0.9, name="WallMat")

    # Shared 3-point + practical light rig.
    key = _add_area_light(bpy, scene, energy=1000.0, location=(-5.0, -6.5, 6.5))
    key.data.size = 4.5
    fill = bpy.data.lights.new("Fill", type="AREA")
    fill.energy = 280.0
    fill.size = 5.0
    fill_obj = bpy.data.objects.new("Fill", fill)
    scene.collection.objects.link(fill_obj)
    fill_obj.location = (7.0, -5.5, 4.5)
    fill_obj.rotation_euler = (math.radians(55.0), 0.0, math.radians(-35.0))
    rim = bpy.data.lights.new("Rim", type="AREA")
    rim.energy = 200.0
    rim.size = 3.0
    rim_obj = bpy.data.objects.new("Rim", rim)
    scene.collection.objects.link(rim_obj)
    rim_obj.location = (0.0, 3.3, 3.2)
    rim_obj.rotation_euler = (math.radians(140.0), 0.0, 0.0)
    practical = bpy.data.lights.new("Practical", type="POINT")
    practical.energy = 25.0
    practical.color = (1.0, 0.78, 0.55)
    practical_obj = bpy.data.objects.new("Practical", practical)
    scene.collection.objects.link(practical_obj)
    practical_obj.location = (-2.0, 1.0, 2.4)

    slots = [
        ("A", 2.6), ("B", 3.2), ("C", 3.8), ("D", 6.6), ("E", 2.6),
        ("H", 3.4), ("I", 1.6),
    ]
    layout, total_width = _layout_slots(slots)

    CAM_DIST = 17.0
    cam = _add_pinned_camera(bpy, scene, (0.0, -CAM_DIST, 5.0), (0.0, 0.0, 1.3), lens=18.0)
    cam.data.sensor_width = 36.0
    fov_x = 2.0 * math.atan(cam.data.sensor_width / (2.0 * cam.data.lens))

    def crop(name):
        cx, hw = layout[name]
        crop_rects[name] = _crop_rect(CAM_DIST, fov_x, cx - hw, cx + hw)

    # --- Alcove A: Diffuse ---------------------------------------------- #
    cx, hw = layout["A"]
    _pedestal(bpy, cx, hw * 1.85, name="PedestalA")
    for x, rough in zip((cx - hw * 0.55, cx, cx + hw * 0.55), (0.0, 0.3, 0.8)):
        s = _small_sphere(bpy, x, 0.0, PEDESTAL_TOP + 0.32, radius=0.30, name=f"Diffuse_{rough}")
        mat, nt, out = _bare_material(bpy, f"DiffuseMat{rough}")
        diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
        _sock(diff.inputs, "Color").default_value = (0.78, 0.28, 0.22, 1.0)
        _sock(diff.inputs, "Roughness").default_value = rough
        nt.links.new(_sock(diff.outputs, "BSDF"), _sock(out.inputs, "Surface"))
        s.data.materials.append(mat)
    tag("ShaderNodeBsdfDiffuse", "input:Color")
    tag("ShaderNodeBsdfDiffuse", "input:Roughness")
    crop("A")

    # --- Alcove B: Glossy / Metallic ------------------------------------- #
    cx, hw = layout["B"]
    _pedestal(bpy, cx, hw * 1.85, name="PedestalB")
    for x, rough in zip((cx - hw * 0.65, cx - hw * 0.1, cx + hw * 0.45), (0.05, 0.3, 0.6)):
        s = _small_sphere(bpy, x, 0.0, PEDESTAL_TOP + 0.28, radius=0.26, name=f"Glossy_{rough}")
        mat, nt, out = _bare_material(bpy, f"GlossyMat{rough}")
        gloss = nt.nodes.new("ShaderNodeBsdfAnisotropic")
        _sock(gloss.inputs, "Color").default_value = (0.75, 0.75, 0.78, 1.0)
        _sock(gloss.inputs, "Roughness").default_value = rough
        nt.links.new(_sock(gloss.outputs, "BSDF"), _sock(out.inputs, "Surface"))
        s.data.materials.append(mat)
    tag("ShaderNodeBsdfAnisotropic", "input:Color")
    tag("ShaderNodeBsdfAnisotropic", "input:Roughness")

    s = _small_sphere(bpy, cx + hw * 0.85, 0.0, PEDESTAL_TOP + 0.34, radius=0.32, name="ThinFilmMetal")
    mat, nt, out = _bare_material(bpy, "ThinFilmMetalMat")
    met = nt.nodes.new("ShaderNodeBsdfMetallic")
    _sock(met.inputs, "Base Color").default_value = (0.85, 0.70, 0.35, 1.0)
    _sock(met.inputs, "Edge Tint").default_value = (0.95, 0.85, 0.60, 1.0)
    _sock(met.inputs, "Roughness").default_value = 0.18
    _sock(met.inputs, "Anisotropy").default_value = 0.7
    _sock(met.inputs, "Rotation").default_value = 0.3
    _sock(met.inputs, "Thin Film Thickness").default_value = 420.0
    _sock(met.inputs, "Thin Film IOR").default_value = 1.55
    met.distribution = "MULTI_GGX"
    met.fresnel_type = "F82"
    nt.links.new(_sock(met.outputs, "BSDF"), _sock(out.inputs, "Surface"))
    s.data.materials.append(mat)
    for sock in ("Base Color", "Edge Tint", "Roughness", "Anisotropy", "Rotation",
                 "Thin Film Thickness", "Thin Film IOR"):
        tag("ShaderNodeBsdfMetallic", f"input:{sock}")
    tag("ShaderNodeBsdfMetallic", "prop:distribution")
    tag("ShaderNodeBsdfMetallic", "prop:fresnel_type")
    crop("B")

    # --- Alcove C: Dielectric --------------------------------------------- #
    cx, hw = layout["C"]
    _pedestal(bpy, cx, hw * 1.85, height=0.35, name="PedestalC")
    LIFT = 0.16  # glass never sits flush on the pedestal
    for x, (ior, rough) in zip((cx - hw * 0.7, cx - hw * 0.15, cx + hw * 0.4),
                                ((1.3, 0.0), (1.5, 0.05), (1.8, 0.15))):
        s = _small_sphere(bpy, x, 0.0, PEDESTAL_TOP - 0.05 + LIFT + 0.30, radius=0.28,
                           name=f"Glass_{ior}")
        mat, nt, out = _bare_material(bpy, f"GlassMat{ior}")
        glass = nt.nodes.new("ShaderNodeBsdfGlass")
        _sock(glass.inputs, "Color").default_value = (0.92, 0.96, 1.0, 1.0)
        _sock(glass.inputs, "Roughness").default_value = rough
        _sock(glass.inputs, "IOR").default_value = ior
        nt.links.new(_sock(glass.outputs, "BSDF"), _sock(out.inputs, "Surface"))
        s.data.materials.append(mat)
    tag("ShaderNodeBsdfGlass", "input:Color")
    tag("ShaderNodeBsdfGlass", "input:Roughness")
    tag("ShaderNodeBsdfGlass", "input:IOR")

    s = _small_sphere(bpy, cx + hw * 0.78, 0.0, PEDESTAL_TOP - 0.05 + LIFT + 0.28, radius=0.26,
                       name="RefractionOnly")
    mat, nt, out = _bare_material(bpy, "RefractionMat")
    refr = nt.nodes.new("ShaderNodeBsdfRefraction")
    _sock(refr.inputs, "Color").default_value = (0.85, 0.95, 0.90, 1.0)
    _sock(refr.inputs, "Roughness").default_value = 0.05
    _sock(refr.inputs, "IOR").default_value = 1.33
    nt.links.new(_sock(refr.outputs, "BSDF"), _sock(out.inputs, "Surface"))
    s.data.materials.append(mat)
    tag("ShaderNodeBsdfRefraction", "input:Color")
    tag("ShaderNodeBsdfRefraction", "input:Roughness")
    tag("ShaderNodeBsdfRefraction", "input:IOR")

    plane = _proof_plane(bpy, cx + hw * 1.05, 0.05, PEDESTAL_TOP + 0.55, size=0.6, name="AlphaPane")
    mat, nt, out = _bare_material(bpy, "AlphaPaneMat")
    trans = nt.nodes.new("ShaderNodeBsdfTransparent")
    _sock(trans.inputs, "Color").default_value = (0.6, 0.85, 0.95, 1.0)
    nt.links.new(_sock(trans.outputs, "BSDF"), _sock(out.inputs, "Surface"))
    mat.blend_method = "BLEND"
    plane.data.materials.append(mat)
    tag("ShaderNodeBsdfTransparent", "input:Color")
    crop("C")

    # --- Alcove D: Principled wall (largest alcove) ----------------------- #
    cx, hw = layout["D"]
    _pedestal(bpy, cx, hw * 1.9, height=0.45, name="PedestalD")
    bust_x = cx - hw * 0.72
    bpy.ops.mesh.primitive_monkey_add(size=1.0, location=(bust_x, 0.05, PEDESTAL_TOP + 0.65))
    bust = bpy.context.active_object
    bust.name = "PrincipledBust"
    bust.modifiers.new("Subsurf", "SUBSURF").levels = 1
    bust.modifiers["Subsurf"].render_levels = 2
    for poly in bust.data.polygons:
        poly.use_smooth = True
    mat, nt, out = _bare_material(bpy, "BustMat")
    principled = nt.nodes.new("ShaderNodeBsdfPrincipled")
    _sock(principled.inputs, "Base Color").default_value = (0.62, 0.18, 0.14, 1.0)
    _sock(principled.inputs, "Metallic").default_value = 0.0
    _sock(principled.inputs, "Roughness").default_value = 0.35
    _sock(principled.inputs, "IOR").default_value = 1.5
    noise = nt.nodes.new("ShaderNodeTexNoise")
    _sock(noise.inputs, "Scale").default_value = 12.0
    bump = nt.nodes.new("ShaderNodeBump")
    _sock(bump.inputs, "Strength").default_value = 0.15
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    nt.links.new(_sock(geo.outputs, "Normal"), _sock(bump.inputs, "Normal"))
    nt.links.new(_sock(noise.outputs, "Fac"), _sock(bump.inputs, "Height"))
    nt.links.new(_sock(bump.outputs, "Normal"), _sock(principled.inputs, "Normal"))
    nt.links.new(_sock(principled.outputs, "BSDF"), _sock(out.inputs, "Surface"))
    bust.data.materials.append(mat)
    for sock in ("Base Color", "Metallic", "Roughness", "IOR", "Normal"):
        tag("ShaderNodeBsdfPrincipled", f"input:{sock}")

    def _principled_sphere(x, name, base_color, **overrides):
        s = _small_sphere(bpy, x, 0.35, PEDESTAL_TOP + 0.30, radius=0.24, name=name)
        mat, nt, out = _bare_material(bpy, f"{name}Mat")
        p = nt.nodes.new("ShaderNodeBsdfPrincipled")
        _sock(p.inputs, "Base Color").default_value = (*base_color, 1.0)
        for sock, val in overrides.items():
            if sock in ("Thin Wall",):
                _sock(p.inputs, sock).default_value = val
            elif isinstance(val, tuple) and len(val) == 3 and sock in ("Subsurface Radius",):
                _sock(p.inputs, sock).default_value = val
            elif isinstance(val, tuple):
                _sock(p.inputs, sock).default_value = (*val, 1.0)
            else:
                _sock(p.inputs, sock).default_value = val
        nt.links.new(_sock(p.outputs, "BSDF"), _sock(out.inputs, "Surface"))
        s.data.materials.append(mat)
        return s

    adv_x0 = cx - hw * 0.30
    dx = hw * 1.55 / 7.0
    _principled_sphere(adv_x0 + 0 * dx, "AlphaThinWall", (0.8, 0.85, 0.9),
                        Alpha=0.45, **{"Thin Wall": True}, Roughness=0.10)
    for sock in ("Alpha", "Thin Wall"):
        tag("ShaderNodeBsdfPrincipled", f"input:{sock}")

    _principled_sphere(adv_x0 + 1 * dx, "SSSDemo", (0.9, 0.75, 0.6),
                        **{"Subsurface Weight": 1.0, "Subsurface Radius": (0.3, 0.12, 0.06),
                           "Subsurface Scale": 0.4, "Subsurface Anisotropy": 0.6, "Roughness": 0.35})
    for sock in ("Subsurface Weight", "Subsurface Radius", "Subsurface Scale", "Subsurface Anisotropy"):
        tag("ShaderNodeBsdfPrincipled", f"input:{sock}")

    _principled_sphere(adv_x0 + 2 * dx, "SpecularAniso", (0.2, 0.25, 0.3),
                        **{"Specular IOR Level": 0.85, "Specular Tint": (0.6, 0.8, 1.0),
                           "Anisotropic": 0.85, "Anisotropic Rotation": 0.3,
                           "Roughness": 0.22, "Metallic": 0.9})
    for sock in ("Specular IOR Level", "Specular Tint", "Anisotropic", "Anisotropic Rotation"):
        tag("ShaderNodeBsdfPrincipled", f"input:{sock}")

    _principled_sphere(adv_x0 + 3 * dx, "CoatDemo", (0.15, 0.15, 0.18),
                        **{"Coat Weight": 1.0, "Coat Roughness": 0.04, "Coat IOR": 1.6,
                           "Coat Tint": (0.85, 0.55, 0.2), "Roughness": 0.5})
    for sock in ("Coat Weight", "Coat Roughness", "Coat IOR", "Coat Tint"):
        tag("ShaderNodeBsdfPrincipled", f"input:{sock}")

    _principled_sphere(adv_x0 + 4 * dx, "SheenDemo", (0.25, 0.2, 0.22),
                        **{"Sheen Weight": 1.0, "Sheen Roughness": 0.35,
                           "Sheen Tint": (0.9, 0.5, 0.7), "Roughness": 0.8})
    for sock in ("Sheen Weight", "Sheen Roughness", "Sheen Tint"):
        tag("ShaderNodeBsdfPrincipled", f"input:{sock}")

    _principled_sphere(adv_x0 + 5 * dx, "EmissionThinFilm", (0.9, 0.9, 0.92),
                        **{"Emission Color": (1.0, 0.65, 0.3), "Emission Strength": 3.0,
                           "Thin Film Thickness": 380.0, "Thin Film IOR": 1.5,
                           "Metallic": 1.0, "Roughness": 0.15})
    for sock in ("Emission Color", "Emission Strength", "Thin Film Thickness", "Thin Film IOR"):
        tag("ShaderNodeBsdfPrincipled", f"input:{sock}")

    _principled_sphere(adv_x0 + 6 * dx, "DiffuseRough", (0.55, 0.4, 0.3),
                        **{"Diffuse Roughness": 0.9, "Roughness": 1.0})
    tag("ShaderNodeBsdfPrincipled", "input:Diffuse Roughness")

    _principled_sphere(adv_x0 + 7 * dx, "TransmissionDemo", (0.95, 0.95, 0.98),
                        **{"Transmission Weight": 0.85, "Roughness": 0.05, "IOR": 1.45})
    tag("ShaderNodeBsdfPrincipled", "input:Transmission Weight")
    crop("D")

    # --- Alcove E: Sheen / Translucent (dedicated closure nodes) ---------- #
    cx, hw = layout["E"]
    _pedestal(bpy, cx, hw * 1.85, name="PedestalE")
    backlight = bpy.data.lights.new("BacklightE", type="POINT")
    backlight.energy = 60.0
    backlight_obj = bpy.data.objects.new("BacklightE", backlight)
    scene.collection.objects.link(backlight_obj)
    backlight_obj.location = (cx, 1.6, PEDESTAL_TOP + 0.6)

    s = _small_sphere(bpy, cx - hw * 0.5, 0.0, PEDESTAL_TOP + 0.32, radius=0.30, name="SheenFabric")
    mat, nt, out = _bare_material(bpy, "SheenMat")
    sheen = nt.nodes.new("ShaderNodeBsdfSheen")
    _sock(sheen.inputs, "Color").default_value = (0.85, 0.3, 0.35, 1.0)
    _sock(sheen.inputs, "Roughness").default_value = 0.35
    _sock(sheen.inputs, "Weight").default_value = 1.0
    nt.links.new(_sock(sheen.outputs, "BSDF"), _sock(out.inputs, "Surface"))
    s.data.materials.append(mat)
    tag("ShaderNodeBsdfSheen", "input:Color")
    tag("ShaderNodeBsdfSheen", "input:Roughness")
    tag("ShaderNodeBsdfSheen", "input:Weight")

    plane = _proof_plane(bpy, cx + hw * 0.55, 0.1, PEDESTAL_TOP + 0.5, size=0.7, name="TranslucentPane")
    mat, nt, out = _bare_material(bpy, "TranslucentMat")
    trl = nt.nodes.new("ShaderNodeBsdfTranslucent")
    _sock(trl.inputs, "Color").default_value = (0.9, 0.75, 0.35, 1.0)
    nt.links.new(_sock(trl.outputs, "BSDF"), _sock(out.inputs, "Surface"))
    plane.data.materials.append(mat)
    tag("ShaderNodeBsdfTranslucent", "input:Color")
    crop("E")

    # --- Alcove H: Emission & spectral ------------------------------------ #
    cx, hw = layout["H"]
    _pedestal(bpy, cx, hw * 1.85, name="PedestalH")
    s = _small_sphere(bpy, cx - hw * 0.75, 0.0, PEDESTAL_TOP + 0.28, radius=0.26, name="WarmBulb")
    mat, nt, emit, out = _emission_card_material(bpy, "BulbMat", strength=6.0)
    _sock(emit.inputs, "Color").default_value = (1.0, 0.75, 0.45, 1.0)
    s.data.materials.append(mat)
    tag("ShaderNodeEmission", "input:Color")
    tag("ShaderNodeEmission", "input:Strength")

    for i, (x, temp) in enumerate(zip(
            (cx - hw * 0.2, cx + hw * 0.25, cx + hw * 0.7), (1500.0, 4500.0, 9000.0))):
        s = _small_sphere(bpy, x, 0.0, PEDESTAL_TOP + 0.20, radius=0.18, name=f"Filament_{int(temp)}")
        mat, nt, emit, out = _emission_card_material(bpy, f"FilamentMat{int(temp)}", strength=4.0)
        bb = nt.nodes.new("ShaderNodeBlackbody")
        _sock(bb.inputs, "Temperature").default_value = temp
        nt.links.new(_sock(bb.outputs, "Color"), _sock(emit.inputs, "Color"))
        s.data.materials.append(mat)
    tag("ShaderNodeBlackbody", "input:Temperature")

    plane = _proof_plane(bpy, cx + hw * 1.05, 0.1, PEDESTAL_TOP + 0.5, size=0.5, name="WavelengthSwatch")
    mat, nt, emit, out = _emission_card_material(bpy, "WavelengthMat", strength=2.0)
    wl = nt.nodes.new("ShaderNodeWavelength")
    _sock(wl.inputs, "Wavelength").default_value = 580.0
    nt.links.new(_sock(wl.outputs, "Color"), _sock(emit.inputs, "Color"))
    plane.data.materials.append(mat)
    tag("ShaderNodeWavelength", "input:Wavelength")
    crop("H")

    # --- Alcove I: gap card (OSL is not supported at all) ----------------- #
    cx, hw = layout["I"]
    _pedestal(bpy, cx, hw * 1.7, height=0.3, name="PedestalI")
    bpy.ops.object.text_add(location=(cx - 0.55, 0.05, PEDESTAL_TOP + 0.5))
    placard = bpy.context.active_object
    placard.name = "OSLPlacard"
    placard.data.body = "OSL Script\n(not supported)"
    placard.data.size = 0.22
    placard.data.extrude = 0.01
    mat, nt, out = _bare_material(bpy, "PlacardMat")
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    _sock(diff.inputs, "Color").default_value = (0.05, 0.05, 0.05, 1.0)
    nt.links.new(_sock(diff.outputs, "BSDF"), _sock(out.inputs, "Surface"))
    placard.data.materials.append(mat)
    gap_tags.append(("ShaderNodeScript", "prop:mode"))
    crop("I")

    return scene, tags, crop_rects, gap_tags


REFERENCE_MATERIALS_HALL_RES = (960, 540)
REFERENCE_MATERIALS_HALL_SAMPLES = 256


# --------------------------------------------------------------------------- #
# textures_mapping
# --------------------------------------------------------------------------- #

def build_textures_mapping_scene(bpy):
    """A printmaker's workshop: a hero print table plus 19 small independent
    proof cards (one per required node), each ``<node> -> Emission -> Output``
    (bump/normal/displacement instead go on a small sphere, since they need
    curvature to read) so texture legibility is never confounded by BSDF
    fidelity, under one raking area light. Covers all 72 SUPPORTED/
    APPROXIMATED textures_mapping matrix rows (69 SUPPORTED + 3 APPROXIMATED
    as of the post-pkg253 matrix); the 149 DROPPED-SILENT rows are listed in
    the corpus README's gap registry (Mapping is wired for visual flavour on
    the TexImage proof but tags nothing new -- every Mapping row is
    DROPPED-SILENT in the current matrix)."""
    scene = _reset(bpy)
    _add_world(bpy, scene, strength=0.35, color=(0.06, 0.06, 0.08))
    tags = []
    gap_tags = []
    crop_rects = {}

    def tag(bl, sock):
        tags.append((bl, sock))

    TABLE_TOP = 0.75

    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.0, 0.6, 0.0))
    floor = bpy.context.active_object
    floor.name = "WorkshopFloor"
    floor.scale = (9.0, 5.0, 1.0)
    _apply_principled(bpy, floor, (0.22, 0.19, 0.16), roughness=0.9, name="WorkshopFloorMat")

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.7, TABLE_TOP / 2.0))
    table = bpy.context.active_object
    table.name = "PrintingTable"
    table.scale = (8.8, 2.8, TABLE_TOP)
    _apply_principled(bpy, table, (0.42, 0.20, 0.14), roughness=0.55, name="TableMat")

    raking = _add_area_light(bpy, scene, energy=650.0, location=(-6.5, -3.0, 2.6))
    raking.data.size = 5.0
    raking.rotation_euler = (math.radians(58.0), 0.0, math.radians(58.0))
    fill = bpy.data.lights.new("WorkshopFill", type="AREA")
    fill.energy = 180.0
    fill.size = 4.0
    fill_obj = bpy.data.objects.new("WorkshopFill", fill)
    scene.collection.objects.link(fill_obj)
    fill_obj.location = (5.5, -3.5, 3.0)
    fill_obj.rotation_euler = (math.radians(55.0), 0.0, math.radians(-40.0))

    # 4 rows x 5 cols = 20 slots (19 used, 1 spare).
    COLS = (-2.2, -1.1, 0.0, 1.1, 2.2)
    ROWS = (1.5, 0.7, -0.1, -0.9)
    Z = TABLE_TOP + 0.55
    grid = {}
    for r, y in enumerate(ROWS):
        for c, x in enumerate(COLS):
            grid[(r, c)] = (x, y)

    # Cards lie flat on the table (see _flat_card below) and the camera looks
    # down at a steep angle, so a standing-card occlusion problem (front-row
    # proofs blocking the rows behind them) can't happen -- the whole grid is
    # legible in one shot, like looking down at swatches on a print table.
    CAM_DIST = 6.5
    cam = _add_pinned_camera(bpy, scene, (0.0, -CAM_DIST, 8.0), (0.0, 0.3, 0.75), lens=24.0)
    cam.data.sensor_width = 36.0
    fov_x = 2.0 * math.atan(cam.data.sensor_width / (2.0 * cam.data.lens))

    def _flat_card(x, y, z, size, name):
        bpy.ops.mesh.primitive_plane_add(size=size, location=(x, y, z))
        obj = bpy.context.active_object
        obj.name = name
        for poly in obj.data.polygons:
            poly.use_smooth = True
        return obj

    # Row bands in normalised image Y (row 0 = farthest from camera = top of
    # frame, row 3 = nearest = bottom) -- a deliberately simple, documented
    # approximation (not a perspective-accurate projection of each row's Z);
    # good enough so every (row, col) proof gets a distinct crop rectangle
    # for the Phase-4 coverage report, refine there if a crop render disagrees.
    ROW_BANDS = ((0.10, 0.30), (0.30, 0.50), (0.50, 0.68), (0.68, 0.85))

    def crop_for(key, row, x, half=0.55):
        y0, y1 = ROW_BANDS[row]
        crop_rects[key] = _crop_rect(CAM_DIST, fov_x, x - half, x + half, y0, y1)

    def texture_card(row, col, key, bl_idname, configure, output="Color", use_vector=True):
        x, y = grid[(row, col)]
        plane = _flat_card(x, y, Z, 0.85, key)
        mat, nt, emit, out = _emission_card_material(bpy, f"{key}Mat")
        node = nt.nodes.new(bl_idname)
        if use_vector and "Vector" in node.inputs:
            coord = nt.nodes.new("ShaderNodeTexCoord")
            nt.links.new(_sock(coord.outputs, "Generated"), _sock(node.inputs, "Vector"))
        configure(node)
        nt.links.new(_sock(node.outputs, output), _sock(emit.inputs, "Color"))
        plane.data.materials.append(mat)
        crop_for(key, row, x)
        return node

    # --- Row 0: procedural noise family + Brick -------------------------- #
    def cfg_noise(n):
        _sock(n.inputs, "Scale").default_value = 8.0
        _sock(n.inputs, "Detail").default_value = 4.0
        _sock(n.inputs, "Roughness").default_value = 0.7
        _sock(n.inputs, "Lacunarity").default_value = 2.5
        _sock(n.inputs, "Offset").default_value = 0.3
        _sock(n.inputs, "Gain").default_value = 1.4
        _sock(n.inputs, "Distortion").default_value = 0.6
        n.noise_type = "HETERO_TERRAIN"
        n.normalize = False
    texture_card(0, 0, "TexNoise", "ShaderNodeTexNoise", cfg_noise)
    for sock in ("Scale", "Detail", "Roughness", "Lacunarity", "Offset", "Gain", "Distortion"):
        tag("ShaderNodeTexNoise", f"input:{sock}")
    tag("ShaderNodeTexNoise", "prop:noise_type")
    tag("ShaderNodeTexNoise", "prop:normalize")

    def cfg_voronoi(n):
        _sock(n.inputs, "Scale").default_value = 6.0
        _sock(n.inputs, "Detail").default_value = 2.0
        _sock(n.inputs, "Roughness").default_value = 0.6
        _sock(n.inputs, "Lacunarity").default_value = 2.2
        _sock(n.inputs, "Smoothness").default_value = 0.3
        _sock(n.inputs, "Exponent").default_value = 2.0
        _sock(n.inputs, "Randomness").default_value = 0.8
        n.distance = "MANHATTAN"
        n.feature = "SMOOTH_F1"
        n.normalize = True
    texture_card(0, 1, "TexVoronoi", "ShaderNodeTexVoronoi", cfg_voronoi, output="Color")
    for sock in ("Scale", "Detail", "Roughness", "Lacunarity", "Smoothness", "Exponent", "Randomness"):
        tag("ShaderNodeTexVoronoi", f"input:{sock}")
    tag("ShaderNodeTexVoronoi", "prop:distance")
    tag("ShaderNodeTexVoronoi", "prop:feature")
    tag("ShaderNodeTexVoronoi", "prop:normalize")

    def cfg_wave_bands(n):
        _sock(n.inputs, "Scale").default_value = 4.0
        _sock(n.inputs, "Distortion").default_value = 1.2
        _sock(n.inputs, "Detail").default_value = 3.0
        _sock(n.inputs, "Detail Scale").default_value = 1.5
        _sock(n.inputs, "Detail Roughness").default_value = 0.6
        _sock(n.inputs, "Phase Offset").default_value = 0.8
        n.wave_type = "BANDS"
        n.bands_direction = "Z"
        n.wave_profile = "SAW"
    texture_card(0, 2, "TexWaveBands", "ShaderNodeTexWave", cfg_wave_bands)
    for sock in ("Scale", "Distortion", "Detail", "Detail Scale", "Detail Roughness", "Phase Offset"):
        tag("ShaderNodeTexWave", f"input:{sock}")
    tag("ShaderNodeTexWave", "prop:wave_type")
    tag("ShaderNodeTexWave", "prop:bands_direction")
    tag("ShaderNodeTexWave", "prop:wave_profile")

    def cfg_wave_rings(n):
        _sock(n.inputs, "Scale").default_value = 3.0
        n.wave_type = "RINGS"
        n.rings_direction = "SPHERICAL"
        n.wave_profile = "TRI"
    texture_card(0, 3, "TexWaveRings", "ShaderNodeTexWave", cfg_wave_rings)
    tag("ShaderNodeTexWave", "prop:rings_direction")

    def cfg_brick(n):
        _sock(n.inputs, "Color1").default_value = (0.65, 0.25, 0.18, 1.0)
        _sock(n.inputs, "Color2").default_value = (0.15, 0.10, 0.08, 1.0)
        _sock(n.inputs, "Scale").default_value = 6.0
        _sock(n.inputs, "Mortar Size").default_value = 0.08
        _sock(n.inputs, "Mortar Smooth").default_value = 0.3
        _sock(n.inputs, "Bias").default_value = 0.4
        _sock(n.inputs, "Brick Width").default_value = 0.4
        _sock(n.inputs, "Row Height").default_value = 0.2
        n.offset_frequency = 3
        n.squash = 1.3
        n.squash_frequency = 3
    texture_card(0, 4, "TexBrick", "ShaderNodeTexBrick", cfg_brick)
    for sock in ("Color1", "Color2", "Scale", "Mortar Size", "Mortar Smooth", "Bias",
                 "Brick Width", "Row Height"):
        tag("ShaderNodeTexBrick", f"input:{sock}")
    for prop in ("offset_frequency", "squash", "squash_frequency"):
        tag("ShaderNodeTexBrick", f"prop:{prop}")

    # --- Row 1: pattern/gradient/image + bump ----------------------------- #
    def cfg_checker(n):
        _sock(n.inputs, "Color1").default_value = (0.9, 0.9, 0.85, 1.0)
        _sock(n.inputs, "Color2").default_value = (0.08, 0.08, 0.1, 1.0)
        _sock(n.inputs, "Scale").default_value = 8.0
    texture_card(1, 0, "TexChecker", "ShaderNodeTexChecker", cfg_checker)
    for sock in ("Color1", "Color2", "Scale"):
        tag("ShaderNodeTexChecker", f"input:{sock}")

    def cfg_magic(n):
        _sock(n.inputs, "Scale").default_value = 6.0
        _sock(n.inputs, "Distortion").default_value = 2.5
        n.turbulence_depth = 4
    texture_card(1, 1, "TexMagic", "ShaderNodeTexMagic", cfg_magic)
    for sock in ("Scale", "Distortion"):
        tag("ShaderNodeTexMagic", f"input:{sock}")
    tag("ShaderNodeTexMagic", "prop:turbulence_depth")

    def cfg_gradient(n):
        n.gradient_type = "SPHERICAL"
    texture_card(1, 2, "TexGradient", "ShaderNodeTexGradient", cfg_gradient)
    tag("ShaderNodeTexGradient", "prop:gradient_type")

    stripe_img = bpy.data.images.new("WorkshopStripe", width=16, height=16, float_buffer=True)
    stripe_img.pixels[:] = _make_stripe_image_pixels(16, 16)
    stripe_img.pack()

    x, y = grid[(1, 3)]
    plane = _flat_card(x, y, Z, 0.85, "TexImage")
    mat, nt, emit, out = _emission_card_material(bpy, "TexImageMat")
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    _sock(mapping.inputs, "Scale").default_value = (2.0, 2.0, 2.0)
    img = nt.nodes.new("ShaderNodeTexImage")
    img.image = stripe_img
    nt.links.new(_sock(coord.outputs, "Generated"), _sock(mapping.inputs, "Vector"))
    nt.links.new(_sock(mapping.outputs, "Vector"), _sock(img.inputs, "Vector"))
    nt.links.new(_sock(img.outputs, "Color"), _sock(emit.inputs, "Color"))
    plane.data.materials.append(mat)
    crop_for("TexImage", 1, x)
    tag("ShaderNodeTexImage", "input:Vector")

    normal_img = bpy.data.images.new("WorkshopNormal", width=16, height=16, float_buffer=True)
    normal_img.colorspace_settings.name = "Non-Color"
    normal_img.pixels[:] = _make_checker_image_pixels(16, 16)
    normal_img.pack()

    def _bump_normal_displacement_sphere(row, col, key, kind):
        x, y = grid[(row, col)]
        s = _small_sphere(bpy, x, y, Z, radius=0.4, name=key, segments=32, ring_count=16)
        mat = bpy.data.materials.new(f"{key}Mat")
        mat.use_nodes = True
        nt = mat.node_tree
        _clear_nodes(nt)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        principled = nt.nodes.new("ShaderNodeBsdfPrincipled")
        _sock(principled.inputs, "Base Color").default_value = (0.55, 0.5, 0.42, 1.0)
        _sock(principled.inputs, "Roughness").default_value = 0.5
        nt.links.new(_sock(principled.outputs, "BSDF"), _sock(out.inputs, "Surface"))
        if kind == "bump":
            voronoi = nt.nodes.new("ShaderNodeTexVoronoi")
            _sock(voronoi.inputs, "Scale").default_value = 10.0
            geo = nt.nodes.new("ShaderNodeNewGeometry")
            bump = nt.nodes.new("ShaderNodeBump")
            _sock(bump.inputs, "Strength").default_value = 0.9
            _sock(bump.inputs, "Distance").default_value = 0.02
            _sock(bump.inputs, "Filter Width").default_value = 0.05
            nt.links.new(_sock(geo.outputs, "Normal"), _sock(bump.inputs, "Normal"))
            nt.links.new(_sock(voronoi.outputs, "Distance"), _sock(bump.inputs, "Height"))
            nt.links.new(_sock(bump.outputs, "Normal"), _sock(principled.inputs, "Normal"))
            for sock in ("Strength", "Distance", "Filter Width", "Height", "Normal"):
                tag("ShaderNodeBump", f"input:{sock}")
        elif kind == "normal_map":
            img2 = nt.nodes.new("ShaderNodeTexImage")
            img2.image = normal_img
            nmap = nt.nodes.new("ShaderNodeNormalMap")
            _sock(nmap.inputs, "Strength").default_value = 1.3
            nt.links.new(_sock(img2.outputs, "Color"), _sock(nmap.inputs, "Color"))
            nt.links.new(_sock(nmap.outputs, "Normal"), _sock(principled.inputs, "Normal"))
            tag("ShaderNodeNormalMap", "input:Strength")
            tag("ShaderNodeNormalMap", "input:Color")
        elif kind == "displacement":
            s.modifiers.new("Subsurf", "SUBSURF").levels = 2
            s.modifiers["Subsurf"].render_levels = 3
            noise = nt.nodes.new("ShaderNodeTexNoise")
            _sock(noise.inputs, "Scale").default_value = 5.0
            disp = nt.nodes.new("ShaderNodeDisplacement")
            _sock(disp.inputs, "Midlevel").default_value = 0.4
            _sock(disp.inputs, "Scale").default_value = 0.15
            nt.links.new(_sock(noise.outputs, "Fac"), _sock(disp.inputs, "Height"))
            nt.links.new(_sock(disp.outputs, "Displacement"), _sock(out.inputs, "Displacement"))
            try:
                mat.cycles.displacement_method = "BOTH"
            except AttributeError:
                pass
            for sock in ("Height", "Midlevel", "Scale"):
                tag("ShaderNodeDisplacement", f"input:{sock}")
        s.data.materials.append(mat)
        crop_for(key, row, x, half=0.45)

    _bump_normal_displacement_sphere(1, 4, "BumpDemo", "bump")
    _bump_normal_displacement_sphere(2, 0, "NormalMapDemo", "normal_map")
    _bump_normal_displacement_sphere(2, 1, "DisplacementDemo", "displacement")

    # --- Row 2 (remaining) + Row 3: colour-grade / mix converter nodes ---- #
    def cfg_brightcontrast(n):
        _sock(n.inputs, "Color").default_value = (0.4, 0.4, 0.4, 1.0)
        _sock(n.inputs, "Brightness").default_value = 0.3
        _sock(n.inputs, "Contrast").default_value = 0.6
    texture_card(2, 2, "BrightContrast", "ShaderNodeBrightContrast", cfg_brightcontrast,
                 use_vector=False)
    for sock in ("Color", "Brightness", "Contrast"):
        tag("ShaderNodeBrightContrast", f"input:{sock}")

    def cfg_gamma(n):
        _sock(n.inputs, "Color").default_value = (0.4, 0.4, 0.4, 1.0)
        _sock(n.inputs, "Gamma").default_value = 2.4
    texture_card(2, 3, "Gamma", "ShaderNodeGamma", cfg_gamma, use_vector=False)
    for sock in ("Color", "Gamma"):
        tag("ShaderNodeGamma", f"input:{sock}")

    def cfg_huesat(n):
        _sock(n.inputs, "Color").default_value = (0.6, 0.2, 0.2, 1.0)
        _sock(n.inputs, "Hue").default_value = 0.65
        _sock(n.inputs, "Saturation").default_value = 1.8
        _sock(n.inputs, "Value").default_value = 1.2
        _sock(n.inputs, "Factor").default_value = 1.0
    texture_card(2, 4, "HueSat", "ShaderNodeHueSaturation", cfg_huesat, use_vector=False)
    for sock in ("Hue", "Saturation", "Value", "Factor", "Color"):
        tag("ShaderNodeHueSaturation", f"input:{sock}")

    def cfg_invert(n):
        _sock(n.inputs, "Color").default_value = (0.15, 0.65, 0.85, 1.0)
    texture_card(3, 0, "Invert", "ShaderNodeInvert", cfg_invert, use_vector=False)
    tag("ShaderNodeInvert", "input:Color")

    def cfg_rgbtobw(n):
        _sock(n.inputs, "Color").default_value = (0.8, 0.2, 0.2, 1.0)
    texture_card(3, 1, "RgbToBw", "ShaderNodeRGBToBW", cfg_rgbtobw, output="Val", use_vector=False)
    tag("ShaderNodeRGBToBW", "input:Color")

    def cfg_mix(n):
        n.data_type = "RGBA"
        n.blend_type = "BURN"
        enabled = {s.name: s for s in n.inputs if s.enabled}
        enabled["Factor"].default_value = 0.6
        enabled["A"].default_value = (0.7, 0.3, 0.2, 1.0)
        enabled["B"].default_value = (0.2, 0.5, 0.8, 1.0)
    x, y = grid[(3, 2)]
    plane = _flat_card(x, y, Z, 0.85, "MixCard")
    mat, nt, emit, out = _emission_card_material(bpy, "MixCardMat")
    mixnode = nt.nodes.new("ShaderNodeMix")
    cfg_mix(mixnode)
    result = next(s for s in mixnode.outputs if s.enabled)
    nt.links.new(result, _sock(emit.inputs, "Color"))
    plane.data.materials.append(mat)
    crop_for("MixCard", 3, x)
    tag("ShaderNodeMix", "prop:blend_type")

    def cfg_mixrgb(n):
        n.blend_type = "SCREEN"
        _sock(n.inputs, "Factor").default_value = 0.5
        _sock(n.inputs, "Color1").default_value = (0.6, 0.2, 0.6, 1.0)
        _sock(n.inputs, "Color2").default_value = (0.2, 0.6, 0.3, 1.0)
    texture_card(3, 3, "MixRgbCard", "ShaderNodeMixRGB", cfg_mixrgb, output="Color",
                 use_vector=False)
    tag("ShaderNodeMixRGB", "prop:blend_type")

    return scene, tags, crop_rects, gap_tags


REFERENCE_TEXTURES_MAPPING_RES = (960, 540)
REFERENCE_TEXTURES_MAPPING_SAMPLES = 192



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
