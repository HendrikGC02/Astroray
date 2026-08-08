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
