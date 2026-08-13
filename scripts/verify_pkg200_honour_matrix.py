# -*- coding: utf-8 -*-
"""pkg200 — in-Blender A/B honour leg (runs INSIDE headless Blender).

Invoked once per (Blender-version, matrix-row) by ``verify_pkg200_honour_matrix_run.py``.
Builds the row's scene, applies the row's variant-A then variant-B native
overrides, and renders BOTH through the TRUE F12 path
(``bpy.ops.render.render(write_still=True)`` with the CUSTOM_RAYTRACER engine)
to two 32-bit LINEAR EXRs. The outer orchestrator then reads those EXRs with cv2
and evaluates the row predicate.

Why F12 and not the pkg175 standin: ``bpy.ops.render.render`` drives the real
``CustomRaytracerRenderEngine.render()``, so it exercises the full native-settings
resolution + every ``renderer.*`` setter — that IS the honour surface. The addon
bootstrap is reused verbatim from ``verify_pkg175_smoke_blender._bootstrap`` (one
implementation, memory: no-duplicate-scripts) via ASTRORAY_SMOKE_ADDON_DIR.

Sentinel discipline (memory: dev_loop_guards / pkg175): prints
``PKG200_LEG PASS`` + the two EXR paths on success, ``PKG200_LEG FAIL <reason>``
on any error, and exits 0 either way — the outer keys on the sentinel, never the
exit code (Blender swallows tracebacks).

Run:
    ASTRORAY_SMOKE_ADDON_DIR=<installed addon dir> \
    blender --background --factory-startup --python verify_pkg200_honour_matrix.py -- \
        --row max_bounces --out-a a.exr --out-b b.exr
"""

import os
import sys
import traceback
from pathlib import Path

import bpy  # type: ignore

SENTINEL = "PKG200_LEG"
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import pkg200_honour_matrix as M  # noqa: E402


def _fail(reason: str):
    print(f"{SENTINEL} FAIL {reason}", flush=True)
    sys.exit(0)  # sentinel, not exit code, is the source of truth


# --------------------------------------------------------------------------- #
# Scene builders (bpy-side; keyed by Row.scene). Kept minimal and closed so the
# light-path depth rows have a real indirect-energy signal.
# --------------------------------------------------------------------------- #
def _reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return bpy.context.scene


def _camera(scene, location=(0.0, -6.0, 0.0), look_along_y=True):
    cam_data = bpy.data.cameras.new("C")
    cam = bpy.data.objects.new("C", cam_data)
    cam.location = location
    cam.rotation_euler = (1.5708, 0.0, 0.0) if look_along_y else (0.0, 0.0, 0.0)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


def _black_world(scene, strength=0.0):
    w = bpy.data.worlds.new("W")
    w.use_nodes = False
    w.color = (0.0, 0.0, 0.0)
    scene.world = w
    return w


def _diffuse_mat(name, color):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Roughness"].default_value = 0.85
    return m


def _glossy_mat(name, color):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Metallic"].default_value = 1.0
    b.inputs["Roughness"].default_value = 0.15
    return m


def _plane(scene, mat, location, rotation, size=4.0, smooth=False):
    bpy.ops.mesh.primitive_plane_add(size=size, location=location, rotation=rotation)
    obj = bpy.context.object
    obj.data.materials.append(mat)
    if smooth:
        bpy.ops.object.shade_smooth()
    return obj


def _emitter(scene, energy=60.0, location=(0.0, 1.0, 1.9), size=1.2):
    ld = bpy.data.lights.new("E", type='AREA')
    ld.energy = energy
    ld.size = size
    o = bpy.data.objects.new("E", ld)
    o.location = location
    o.rotation_euler = (3.14159, 0.0, 0.0)  # point down
    scene.collection.objects.link(o)
    return o


def _walls(scene, mat_factory):
    import math
    white = mat_factory("white", (0.75, 0.75, 0.75))
    red = mat_factory("red", (0.65, 0.06, 0.06))
    green = mat_factory("green", (0.06, 0.55, 0.06))
    _plane(scene, white, (0.0, 0.0, -2.0), (0.0, 0.0, 0.0))              # floor
    _plane(scene, white, (0.0, 0.0, 2.0), (math.pi, 0.0, 0.0))          # ceiling
    _plane(scene, white, (0.0, 2.0, 0.0), (math.pi / 2, 0.0, 0.0))      # back
    _plane(scene, red, (-2.0, 0.0, 0.0), (0.0, math.pi / 2, 0.0))       # left
    _plane(scene, green, (2.0, 0.0, 0.0), (0.0, -math.pi / 2, 0.0))     # right


def build_closed_box(scene):
    _walls(scene, _diffuse_mat)
    _emitter(scene)
    _camera(scene, location=(0.0, -5.5, 0.0))


def build_closed_box_glossy(scene):
    import math
    # Glossy side/back walls, diffuse floor/ceiling; emitter creates a highlight
    # that only reaches the camera via glossy interreflection.
    white = _diffuse_mat("white", (0.75, 0.75, 0.75))
    gloss = _glossy_mat("gloss", (0.9, 0.9, 0.9))
    _plane(scene, white, (0.0, 0.0, -2.0), (0.0, 0.0, 0.0))
    _plane(scene, white, (0.0, 0.0, 2.0), (math.pi, 0.0, 0.0))
    _plane(scene, gloss, (0.0, 2.0, 0.0), (math.pi / 2, 0.0, 0.0))
    _plane(scene, gloss, (-2.0, 0.0, 0.0), (0.0, math.pi / 2, 0.0))
    _plane(scene, gloss, (2.0, 0.0, 0.0), (0.0, -math.pi / 2, 0.0))
    _emitter(scene, energy=120.0)
    _camera(scene, location=(0.0, -5.5, 0.0))


def _glass_mat(name="glass"):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    b.inputs["Roughness"].default_value = 0.0
    b.inputs["Transmission Weight"].default_value = 1.0
    b.inputs["IOR"].default_value = 1.5
    return m


def build_glass_sphere(scene):
    _walls(scene, _diffuse_mat)
    _emitter(scene, energy=90.0)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.1, location=(0.0, 0.3, -0.9))
    obj = bpy.context.object
    obj.data.materials.append(_glass_mat())
    bpy.ops.object.shade_smooth()   # memory: caustics/dispersion need smooth normals
    _camera(scene, location=(0.0, -5.5, 0.2))


def build_transparent_tower(scene):
    import math
    _walls(scene, _diffuse_mat)
    _emitter(scene, energy=90.0)
    # A stack of alpha-transparent quads between camera and back wall; each ray to
    # the wall must pass N alpha surfaces -> transparent_max_bounces gates how many.
    for i in range(6):
        m = bpy.data.materials.new(f"alpha{i}")
        m.use_nodes = True
        b = m.node_tree.nodes.get("Principled BSDF")
        b.inputs["Base Color"].default_value = (0.9, 0.9, 0.9, 1.0)
        b.inputs["Alpha"].default_value = 0.5
        _plane(scene, m, (0.0, -0.5 + i * 0.35, 0.0), (math.pi / 2, 0.0, 0.0), size=3.0)
    _camera(scene, location=(0.0, -5.5, 0.0))


def build_hdri_box(scene):
    # World-lit (bright constant world) open box; world_max_bounces gates how many
    # world-light bounces contribute indirect fill.
    import math
    w = bpy.data.worlds.new("W")
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs[0].default_value = (0.9, 0.9, 0.95, 1.0)
        bg.inputs[1].default_value = 2.0
    scene.world = w
    white = _diffuse_mat("white", (0.8, 0.8, 0.8))
    _plane(scene, white, (0.0, 0.0, -2.0), (0.0, 0.0, 0.0))
    _plane(scene, white, (0.0, 2.0, 0.0), (math.pi / 2, 0.0, 0.0))
    _plane(scene, white, (-2.0, 0.0, 0.0), (0.0, math.pi / 2, 0.0))
    _plane(scene, white, (2.0, 0.0, 0.0), (0.0, -math.pi / 2, 0.0))
    _camera(scene, location=(0.0, -5.5, 0.0))


def build_firefly(scene):
    # Small very bright emitter over a sharp glossy floor: the classic firefly
    # generator so a clamp has something bright to clip.
    _black_world(scene)
    gloss = _glossy_mat("floor", (0.9, 0.9, 0.9))
    gloss.node_tree.nodes.get("Principled BSDF").inputs["Roughness"].default_value = 0.08
    _plane(scene, gloss, (0.0, 0.0, -1.0), (0.0, 0.0, 0.0), size=8.0)
    _emitter(scene, energy=1500.0, location=(0.0, 0.0, 3.0), size=0.15)
    _camera(scene, location=(0.0, -6.0, 1.2))


def build_caustic(scene):
    # Smooth-shaded glass sphere over a diffuse floor lit by a small bright light:
    # focuses a caustic on the floor. Smooth normals per memory.
    _black_world(scene)
    floor = _diffuse_mat("floor", (0.8, 0.8, 0.8))
    _plane(scene, floor, (0.0, 0.0, -1.5), (0.0, 0.0, 0.0), size=8.0)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, location=(0.0, 0.0, 0.2))
    obj = bpy.context.object
    obj.data.materials.append(_glass_mat())
    bpy.ops.object.shade_smooth()
    _emitter(scene, energy=800.0, location=(0.0, 0.0, 4.0), size=0.3)
    _camera(scene, location=(0.0, -5.5, 2.2))


def build_volume_box(scene):
    # A cube filled with a Principled Volume, lit by an emitter: volume_bounces
    # gates multi-scatter inside it. KNOWN-PARTIAL — may be non-responsive.
    _black_world(scene)
    bpy.ops.mesh.primitive_cube_add(size=3.0, location=(0.0, 0.5, 0.0))
    cube = bpy.context.object
    m = bpy.data.materials.new("vol")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type == "BSDF_PRINCIPLED":
            nt.nodes.remove(n)
    out = nt.nodes.get("Material Output")
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    vol.inputs["Density"].default_value = 0.6
    vol.inputs["Anisotropy"].default_value = 0.0
    nt.links.new(vol.outputs[0], out.inputs["Volume"])
    cube.data.materials.append(m)
    _emitter(scene, energy=600.0, location=(2.5, 0.0, 2.5), size=0.5)
    _camera(scene, location=(0.0, -6.0, 0.0))


def build_denoiser_scene(scene):
    # A noisy indirect-lit box at very low spp — denoise has plenty of variance
    # to collapse.
    _walls(scene, _diffuse_mat)
    _emitter(scene, energy=70.0)
    _camera(scene, location=(0.0, -5.5, 0.0))


SCENE_BUILDERS = {
    "closed_box": build_closed_box,
    "closed_box_glossy": build_closed_box_glossy,
    "glass_sphere": build_glass_sphere,
    "transparent_tower": build_transparent_tower,
    "hdri_box": build_hdri_box,
    "firefly": build_firefly,
    "caustic": build_caustic,
    "volume_box": build_volume_box,
    "denoiser_scene": build_denoiser_scene,
}


# --------------------------------------------------------------------------- #
# Render config + override application
# --------------------------------------------------------------------------- #
def _base_render_config(scene, row: M.Row):
    r = scene.render
    r.resolution_x = row.res
    r.resolution_y = row.res
    r.resolution_percentage = 100
    r.film_transparent = False
    r.image_settings.file_format = "OPEN_EXR"
    r.image_settings.color_depth = "32"
    r.image_settings.exr_codec = "NONE"
    r.engine = "CUSTOM_RAYTRACER"
    vs = scene.view_settings
    vs.view_transform = "Standard"
    vs.exposure = 0.0
    vs.gamma = 1.0
    c = scene.cycles
    c.samples = row.samples
    c.use_adaptive_sampling = False
    c.use_denoising = False
    c.film_exposure = 1.0
    # A fixed nonzero seed baseline (memory: seed 0 = std::random_device sentinel).
    c.seed = 20200


def _apply_overrides(scene, overrides):
    for path, value in overrides:
        obj = scene
        parts = path.split(".")
        for p in parts[:-1]:
            obj = getattr(obj, p)
        setattr(obj, parts[-1], value)


def _render_leg(scene, row: M.Row, variant: str, out_path: Path):
    _base_render_config(scene, row)
    _apply_overrides(scene, row.common)
    if variant == "A":
        _apply_overrides(scene, row.variant_a)
        scene.cycles.seed = row.seed_a
    else:
        _apply_overrides(scene, row.variant_b)
        scene.cycles.seed = row.seed_b
    out_path.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(out_path.with_suffix(""))
    bpy.ops.render.render(write_still=True)
    # Blender appends the extension per file_format; normalise to out_path.
    produced = out_path.with_suffix("").with_suffix(".exr")
    if not produced.exists():
        # Some Blender builds honour the literal filepath; check both.
        alt = Path(str(out_path.with_suffix("")) + ".exr")
        produced = alt if alt.exists() else produced
    if produced != out_path and produced.exists():
        produced.replace(out_path)
    if not out_path.exists():
        raise RuntimeError(f"no EXR produced for variant {variant} at {out_path}")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--row", required=True)
    p.add_argument("--out-a", required=True)
    p.add_argument("--out-b", required=True)
    args = p.parse_args(argv)

    try:
        row = M.get_row(args.row)
        # Reuse the pkg175 bootstrap (loads the staged/installed addon from
        # ASTRORAY_SMOKE_ADDON_DIR, registers the CUSTOM_RAYTRACER engine).
        import verify_pkg175_smoke_blender as smoke
        astroray, addon = smoke._bootstrap()
        print(f"[pkg200-leg] engine: {astroray.__file__}", flush=True)

        builder = SCENE_BUILDERS[row.scene]

        out_a = Path(args.out_a).resolve()
        out_b = Path(args.out_b).resolve()

        scene = _reset()
        builder(scene)
        _render_leg(scene, row, "A", out_a)

        scene = _reset()
        builder(scene)
        _render_leg(scene, row, "B", out_b)

        print(f"PKG200_EXR_A {out_a}", flush=True)
        print(f"PKG200_EXR_B {out_b}", flush=True)
        print(f"{SENTINEL} PASS", flush=True)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _fail(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
