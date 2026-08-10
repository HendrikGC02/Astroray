# -*- coding: utf-8 -*-
"""pkg178 Stage-4 acceptance — thin-film iridescence A/B sweep + Blender scene builder.

Two layers, deliberately split so the sweep definition is import-safe without
``bpy`` (mirrors ``benchmarks/cycles-parity/metal_ab/scenes.py``):

  * ``thinfilm_sweep()`` — a PURE function returning the (kind, thickness, film_ior)
    matrix. Unit-testable without Blender.
  * ``build_thinfilm_scene(bpy, cfg)`` — runs INSIDE Blender (imported lazily by
    the render leg); mutates the current file into a single Principled sphere with
    the Thin Film sockets set, under a uniform constant-colour world, so Cycles
    and the Astroray addon render the *same translated scene* and differ only in
    the renderer/device. This is the pkg178 "feature-matrix parity vs Cycles" gate
    done through the real addon Principled->native translation (incl. the #581
    thin-film socket mapping), NOT the standalone ``conductor_hue_sweep.py`` path
    (which never touches the addon and cannot render a Cycles oracle leg).

Scene rationale (why a uniform-world "furnace" and two material kinds):

  * ``conductor`` — a metallic=1 neutral sphere. Thin-film modulates the whole
    metal reflection; this is the metal-iridescence (anodised/oil-on-metal) case.
    Astroray ships this as an RGB-upsample approximation (STATUS 2026-08-11), so a
    residual hue gap vs Cycles' per-wavelength film is EXPECTED and is the number
    this sweep quantifies (feeds the per-lambda-conductor follow-up).

  * ``dielectric`` — a near-black (base_color ~0) metallic=0, transmission=0,
    IOR 1.5 sphere: only the iridescent specular Fresnel shows (the literal
    oil-slick / soap-bubble reflection). This ISOLATES the thin-film Fresnel term,
    which is the quantity the "analytically exact vs Cycles" claim is about. A
    fully transmissive bubble adds refractive multi-bounce transport that would
    diverge for RNG/thin-wall reasons unrelated to the Fresnel utility, so it is
    deliberately out of scope for this Fresnel-parity gate.

A metallic/dielectric sphere in a uniform environment reflects the constant world
at a magnitude/hue set by its (thin-film-modulated) Fresnel; the image-plane ROI
mean + circular-mean hue is the most direct, noise-cheap read of the iridescence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Sweep grid (pure)
# --------------------------------------------------------------------------- #

# Thickness sweep across the task's 100-1000 nm band. Below ~ half a visible
# wavelength the first-order interference dominates (strong hue swing); by 1000 nm
# several orders overlap and the hue begins to wash toward neutral.
THICKNESSES_NM = (100.0, 200.0, 400.0, 600.0, 800.0, 1000.0)
FILM_IORS = (1.2, 1.5, 1.8)

# Uniform world = the sole illuminant (furnace-style), matching metal_ab so the
# two Cycles-parity gates read the same illumination. Moderate strength keeps the
# linear radiance clear of 0/1 so per-channel ratios are not floor/clamp limited.
WORLD_COLOR = (0.60, 0.60, 0.60)
WORLD_STRENGTH = 1.0

# Conductor: neutral metal so the iridescence hue is the dominant chroma signal.
CONDUCTOR_BASE = (0.90, 0.90, 0.90)
# Dielectric: near-black body so ONLY the iridescent specular Fresnel shows.
DIELECTRIC_BASE = (0.02, 0.02, 0.02)
DIELECTRIC_IOR = 1.5
ROUGHNESS = 0.06  # sharp enough that the interference tint is not blurred away


@dataclass(frozen=True)
class ThinFilmConfig:
    name: str
    kind: str  # "dielectric" | "conductor"
    thickness_nm: float
    film_ior: float

    @property
    def metallic(self) -> float:
        return 1.0 if self.kind == "conductor" else 0.0

    @property
    def base_color(self) -> tuple[float, float, float]:
        return CONDUCTOR_BASE if self.kind == "conductor" else DIELECTRIC_BASE


def thinfilm_sweep() -> list[ThinFilmConfig]:
    """The thin-film A/B matrix: kind x thickness x film_ior."""
    out: list[ThinFilmConfig] = []
    for kind in ("dielectric", "conductor"):
        for d in THICKNESSES_NM:
            for fior in FILM_IORS:
                out.append(ThinFilmConfig(
                    name=f"tf_{kind}_d{int(d):04d}_ior{int(round(fior * 100)):03d}",
                    kind=kind, thickness_nm=d, film_ior=fior))
    return out


def config_by_name(name: str) -> ThinFilmConfig:
    for cfg in thinfilm_sweep():
        if cfg.name == name:
            return cfg
    raise ValueError(f"unknown thin-film config {name!r}")


# --------------------------------------------------------------------------- #
# Blender scene builder (runs inside Blender; bpy passed in, never imported here)
# --------------------------------------------------------------------------- #

def _set_socket(principled, names, value) -> bool:
    """Set the first Principled input whose label matches any of ``names``.

    Socket labels drift across Blender versions; try each candidate and report
    whether one landed so the leg can FAIL loudly rather than silently skip the
    thin-film sockets (which would make the whole parity gate a no-op).
    """
    for nm in names:
        sock = principled.inputs.get(nm)
        if sock is not None:
            sock.default_value = value
            return True
    return False


def build_thinfilm_scene(bpy, cfg: ThinFilmConfig):
    """Single Principled sphere with Thin Film sockets under a uniform world."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

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

    mat = bpy.data.materials.new("ThinFilm")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    principled = nt.nodes.new("ShaderNodeBsdfPrincipled")
    principled.inputs["Base Color"].default_value = (
        cfg.base_color[0], cfg.base_color[1], cfg.base_color[2], 1.0)
    principled.inputs["Metallic"].default_value = cfg.metallic
    principled.inputs["Roughness"].default_value = ROUGHNESS
    _set_socket(principled, ("IOR",), DIELECTRIC_IOR)
    _set_socket(principled, ("Transmission Weight", "Transmission"), 0.0)

    # Thin Film sockets (Blender 4.1+; the addon maps these to the native
    # 'thin_film_thickness'/'thin_film_ior' params, PR #581). FAIL if absent so a
    # socket rename in a future Blender does not silently disable the whole gate.
    if not _set_socket(principled, ("Thin Film Thickness",), cfg.thickness_nm):
        raise RuntimeError("Principled node has no 'Thin Film Thickness' socket")
    if not _set_socket(principled, ("Thin Film IOR",), cfg.film_ior):
        raise RuntimeError("Principled node has no 'Thin Film IOR' socket")

    nt.links.new(principled.outputs["BSDF"], out.inputs["Surface"])
    sphere.data.materials.append(mat)

    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "PERSP"
    cam_data.angle = math.radians(60.0)
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, -1.35, 0.0)
    cam.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.camera = cam
    return scene
