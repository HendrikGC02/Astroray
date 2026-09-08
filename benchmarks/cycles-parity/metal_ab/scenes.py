# -*- coding: utf-8 -*-
"""pkg129 A/B — rough-metal sweep definition + the shared Blender scene builder.

Two layers, deliberately split so the sweep definition is import-safe without
``bpy``:

  * ``metal_sweep()`` — a PURE function returning the (roughness, albedo) matrix.
    Unit-tested without Blender.
  * ``build_metal_scene(bpy, cfg)`` — runs INSIDE Blender (imported lazily by the
    render leg); mutates the current file into a single metal sphere under a
    uniform constant-colour world, so Cycles and the Astroray addon render the
    SAME translated scene and differ only in the renderer/device.

Scene rationale (why a uniform-world "furnace" and not an area-lit key):
a metallic=1 sphere in a uniform environment reflects the constant world back at
a magnitude set by its directional albedo INCLUDING the multiscatter energy
compensation. The image-plane mean over the sphere is therefore the most direct,
noise-cheap read of the compensation term — exactly the quantity the
application-form question turns on. An area key would add a specular-highlight
shape term that dilutes the energy signal we are trying to isolate.

The albedos mirror ``tests/test_pkg163_metal_spectral_colorspace_parity.py``
(CHROMATIC copper-ish, NEUTRAL grey) so this cross-engine gate and the internal
GPU/CPU gate measure the same material.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Mirror pkg163's albedos so the cross-engine A/B and the internal GPU/CPU parity
# gate exercise the identical metal response.
CHROMATIC = (0.92, 0.78, 0.35)
NEUTRAL = (0.35, 0.35, 0.35)
ROUGHNESSES = (0.3, 0.6, 0.9)

# Uniform world = the sole illuminant (furnace-style). Moderate strength keeps the
# linear radiance well away from 0 and 1 so the ratio is not floor/clamp limited.
WORLD_COLOR = (0.60, 0.60, 0.60)
WORLD_STRENGTH = 1.0


@dataclass(frozen=True)
class MetalConfig:
    name: str
    roughness: float
    albedo: tuple[float, float, float]  # linear RGB, metallic=1


def metal_sweep() -> list[MetalConfig]:
    """The rough-metal A/B matrix: r x {chromatic, neutral}, metallic=1."""
    out: list[MetalConfig] = []
    for tint, albedo in (("chromatic", CHROMATIC), ("neutral", NEUTRAL)):
        for r in ROUGHNESSES:
            out.append(MetalConfig(
                name=f"metal_{tint}_r{round(r * 100):03d}",
                roughness=r,
                albedo=albedo,
            ))
    return out


def config_by_name(name: str) -> MetalConfig:
    for cfg in metal_sweep():
        if cfg.name == name:
            return cfg
    raise ValueError(f"unknown metal config {name!r}")


# --------------------------------------------------------------------------- #
# Blender scene builder (runs inside Blender; bpy passed in, never imported here)
# --------------------------------------------------------------------------- #

def build_metal_scene(bpy, cfg: MetalConfig):
    """Single metallic=1 Principled sphere under a uniform world. Returns scene."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    # Uniform constant world as the sole light source.
    world = bpy.data.worlds.new("W")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (WORLD_COLOR[0], WORLD_COLOR[1], WORLD_COLOR[2], 1.0)
    bg.inputs[1].default_value = WORLD_STRENGTH

    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.9, location=(0.0, 0.0, 0.0),
                                         segments=64, ring_count=32)
    sphere = bpy.context.active_object
    for poly in sphere.data.polygons:
        poly.use_smooth = True

    mat = bpy.data.materials.new("Metal")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    principled = nt.nodes.new("ShaderNodeBsdfPrincipled")
    principled.inputs["Base Color"].default_value = (
        cfg.albedo[0], cfg.albedo[1], cfg.albedo[2], 1.0)
    principled.inputs["Metallic"].default_value = 1.0
    principled.inputs["Roughness"].default_value = cfg.roughness
    nt.links.new(principled.outputs["BSDF"], out.inputs["Surface"])
    sphere.data.materials.append(mat)

    # Close framing so the sphere fills the frame (whole-image mean ~= sphere
    # mean; the constant-world corners are identical across engines so they do
    # not bias the per-channel ratio). Mirrors the pkg163 60-degree framing.
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "PERSP"
    cam_data.angle = math.radians(60.0)
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, -1.35, 0.0)
    cam.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.camera = cam
    return scene


# --------------------------------------------------------------------------- #
# pkg263 — rough-glass sweep (owner "limb darkening" report). A second preset
# on the SAME driver (CLAUDE.md 5b: extend, don't fork); mirrors the split
# above (pure sweep / bpy-lazy scene builder).
#
# Unlike the metal furnace (uniform world, sole illuminant, whole-frame mean),
# the glass ROIs are POSITIONAL (centre disc / limb annulus / background
# patch), so the camera axis is made to pass exactly through the sphere
# centre and the projected silhouette radius is computed analytically
# (see ``sphere_projected_radius_px``) rather than measured empirically -
# the ROI masks must line up with the same formula the harness uses to draw
# them, in world-units, before any pixel exists.
# --------------------------------------------------------------------------- #

GLASS_IOR = 1.45
GLASS_ROUGHNESSES = (0.0, 0.2, 0.5, 0.85)
GLASS_SPHERE_RADIUS = 0.6
GLASS_PLANE_GAP = 0.05          # sphere lifted just off the plane
GLASS_CAM_DISTANCE = 2.4        # along -Y from the sphere centre
GLASS_CAM_FOV_DEG = 50.0        # full angle (cam_data.angle)
GLASS_WORLD_COLOR = (0.6, 0.6, 0.6)
GLASS_WORLD_STRENGTH = 0.3      # dim enough that the area light still reads
GLASS_PLANE_COLOR = (0.5, 0.5, 0.5)
GLASS_LIGHT_ENERGY = 150.0
GLASS_LIGHT_SIZE = 1.0
GLASS_LIGHT_LOCATION = (1.2, -1.2, 2.4)  # relative to world origin (Z absolute)


@dataclass(frozen=True)
class GlassConfig:
    name: str
    roughness: float
    ior: float = GLASS_IOR


def glass_sweep() -> list[GlassConfig]:
    """The rough-glass A/B matrix: roughness in {0, 0.2, 0.5, 0.85}, IOR 1.45."""
    return [GlassConfig(name=f"glass_r{round(r * 100):03d}", roughness=r)
            for r in GLASS_ROUGHNESSES]


def glass_config_by_name(name: str) -> GlassConfig:
    for cfg in glass_sweep():
        if cfg.name == name:
            return cfg
    raise ValueError(f"unknown glass config {name!r}")


def sphere_projected_radius_px(sphere_radius: float, cam_distance: float,
                               half_fov_rad: float, res: int) -> float:
    """Pixel radius of a sphere's silhouette for a pinhole camera whose optical
    axis passes through the sphere centre (so the silhouette is a circle
    centred in a square frame).

    The sphere subtends half-angle ``alpha = asin(r/d)`` as seen from the
    camera (the tangent line from the camera to the sphere makes this angle
    with the line to the centre). For a rectilinear camera with a symmetric
    field of view, a ray at angle ``beta`` from the optical axis lands at
    normalized screen coordinate ``tan(beta) / tan(half_fov)`` (range -1..1
    across the half-width). Since the sphere is dead-centre, beta == alpha at
    the silhouette edge. Standard pinhole-camera projection, not a rendering
    algorithm — no external citation applies (CLAUDE.md 6 is about physics/
    sampling algorithms in the engine, not ROI geometry in a test harness).
    """
    alpha = math.asin(sphere_radius / cam_distance)
    normalized_radius = math.tan(alpha) / math.tan(half_fov_rad)
    return normalized_radius * (res / 2.0)


def build_glass_scene(bpy, cfg: GlassConfig):
    """Glass sphere lifted off a grey plane, one area light + a uniform grey
    world, camera framing the sphere large with its axis through the sphere
    centre (required for the harness's circular ROI masks to line up)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    world = bpy.data.worlds.new("W")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (
        GLASS_WORLD_COLOR[0], GLASS_WORLD_COLOR[1], GLASS_WORLD_COLOR[2], 1.0)
    bg.inputs[1].default_value = GLASS_WORLD_STRENGTH

    bpy.ops.mesh.primitive_plane_add(size=20.0, location=(0.0, 0.0, 0.0))
    plane = bpy.context.active_object
    pmat = bpy.data.materials.new("Plane")
    pmat.use_nodes = True
    pbsdf = pmat.node_tree.nodes.get("Principled BSDF")
    if pbsdf is not None:
        pbsdf.inputs["Base Color"].default_value = (
            GLASS_PLANE_COLOR[0], GLASS_PLANE_COLOR[1], GLASS_PLANE_COLOR[2], 1.0)
        pbsdf.inputs["Roughness"].default_value = 0.6
    plane.data.materials.append(pmat)

    z = GLASS_SPHERE_RADIUS + GLASS_PLANE_GAP
    bpy.ops.mesh.primitive_uv_sphere_add(radius=GLASS_SPHERE_RADIUS,
                                         location=(0.0, 0.0, z),
                                         segments=64, ring_count=32)
    sphere = bpy.context.active_object
    for poly in sphere.data.polygons:
        poly.use_smooth = True

    mat = bpy.data.materials.new("Glass")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    glass = nt.nodes.new("ShaderNodeBsdfGlass")
    glass.inputs["Roughness"].default_value = cfg.roughness
    glass.inputs["IOR"].default_value = cfg.ior
    nt.links.new(glass.outputs["BSDF"], out.inputs["Surface"])
    sphere.data.materials.append(mat)

    light_data = bpy.data.lights.new("Key", type="AREA")
    light_data.energy = GLASS_LIGHT_ENERGY
    light_data.size = GLASS_LIGHT_SIZE
    light = bpy.data.objects.new("Key", light_data)
    scene.collection.objects.link(light)
    light.location = (GLASS_LIGHT_LOCATION[0], GLASS_LIGHT_LOCATION[1], z + 1.75)
    light.rotation_euler = (math.radians(35.0), 0.0, math.radians(25.0))

    # Camera level with the sphere centre, axis pointing straight at it (the
    # sphere lands dead-centre in the square frame; see
    # sphere_projected_radius_px for why that matters).
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "PERSP"
    cam_data.angle = math.radians(GLASS_CAM_FOV_DEG)
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, -GLASS_CAM_DISTANCE, z)
    cam.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.camera = cam
    return scene
