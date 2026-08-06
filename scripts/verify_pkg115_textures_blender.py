# -*- coding: utf-8 -*-
"""pkg115 final acceptance — Blender-vs-Cycles procedural-texture stills.

Run INSIDE Blender (headless), once per engine:

    blender --background --factory-startup --python \
        scripts/verify_pkg115_textures_blender.py -- \
        --engine CUSTOM_RAYTRACER --out test_results/pkg115_visual

Builds a 4x2 grid of spheres, one per ported procedural texture node
(Checker, Gradient, Magic, Noise, Voronoi, Wave, Brick + a plain diffuse
reference), under a sun-ish area light, and saves one F12 still. The lead
inspects the CUSTOM_RAYTRACER still against the CYCLES still (same node
trees) for semantic parity: pattern type, scale, orientation, color
mapping. Exact pixel equality is NOT expected (different integrators);
the audit's acceptance is node-semantics parity.

Addon bootstrap mirrors benchmarks/viewport_parity/blender_driver.py
(fresh-pyd guard per memory stale_pyd_locations).
"""
import argparse
import os
import sys
from pathlib import Path

import bpy  # type: ignore


def _bootstrap_astroray_addon():
    repo_root = Path(__file__).resolve().parents[1]
    # Ninja (single-config, 2026-08) emits the pyd at build_cuda/ root;
    # legacy multi-config builds used build_cuda/Release.
    default_build = repo_root / "build_cuda"
    if not list(default_build.glob("astroray*.pyd")):
        default_build = repo_root / "build_cuda" / "Release"
    build_dir = Path(os.environ.get("ASTRORAY_PYD_DIR", default_build))
    for entry in (str(build_dir), str(repo_root)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    cuda_root = Path(os.environ.get(
        "CUDA_PATH",
        r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.8"))
    if not cuda_root.is_dir():
        # CUDA_PATH unset and default absent: probe installed toolkits.
        toolkit_root = Path(r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA")
        versions = sorted(toolkit_root.glob("v*"), reverse=True) if toolkit_root.is_dir() else []
        cuda_root = versions[0] if versions else cuda_root
    # CUDA 13+ moved the Windows runtime DLLs into bin\x64 — probe both.
    for dll_dir in (build_dir, cuda_root / "bin", cuda_root / "bin" / "x64"):
        if dll_dir.is_dir():
            os.add_dll_directory(str(dll_dir))
    import astroray  # noqa: F401
    print(f"[pkg115-visual] astroray module: {astroray.__file__}")
    import blender_addon
    try:
        blender_addon.register()
    except Exception as exc:
        if "already registered" not in str(exc):
            raise


def _tex_nodes():
    """(label, node_type, configure(node)) per ported texture."""
    def noise(n):
        n.inputs["Scale"].default_value = 6.0
        n.inputs["Detail"].default_value = 3.0
        n.inputs["Roughness"].default_value = 0.5

    def voronoi(n):
        n.inputs["Scale"].default_value = 6.0
        n.inputs["Randomness"].default_value = 1.0

    def wave(n):
        n.wave_type = 'BANDS'
        n.wave_profile = 'SIN'
        n.inputs["Scale"].default_value = 2.0
        n.inputs["Distortion"].default_value = 2.0
        n.inputs["Detail"].default_value = 2.0

    def brick(n):
        n.inputs["Scale"].default_value = 4.0
        n.inputs["Color1"].default_value = (0.7, 0.25, 0.15, 1.0)
        n.inputs["Color2"].default_value = (0.55, 0.18, 0.10, 1.0)
        mortar = n.inputs.get("Mortar") or n.inputs.get("Color3")
        if mortar is not None:
            mortar.default_value = (0.85, 0.85, 0.85, 1.0)

    def magic(n):
        n.turbulence_depth = 2
        n.inputs["Scale"].default_value = 3.0
        n.inputs["Distortion"].default_value = 1.5

    def gradient(n):
        n.gradient_type = 'SPHERICAL'

    def checker(n):
        n.inputs["Scale"].default_value = 6.0
        n.inputs["Color1"].default_value = (0.9, 0.9, 0.9, 1.0)
        n.inputs["Color2"].default_value = (0.12, 0.12, 0.12, 1.0)

    return [
        ("checker", "ShaderNodeTexChecker", checker),
        ("gradient", "ShaderNodeTexGradient", gradient),
        ("magic", "ShaderNodeTexMagic", magic),
        ("noise", "ShaderNodeTexNoise", noise),
        ("voronoi", "ShaderNodeTexVoronoi", voronoi),
        ("wave", "ShaderNodeTexWave", wave),
        ("brick", "ShaderNodeTexBrick", brick),
        ("plain", None, None),
    ]


_LIGHT_ENERGY = [300.0]


def build_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    specs = _tex_nodes()
    for k, (label, node_type, configure) in enumerate(specs):
        col, row = k % 4, k // 4
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=0.42,
            location=(col * 1.0 - 1.5, 0.55 - row * 0.95, 0.0),
            segments=48, ring_count=24)
        obj = bpy.context.active_object
        bpy.ops.object.shade_smooth()
        mat = bpy.data.materials.new(f"pkg115_{label}")
        mat.use_nodes = True
        tree = mat.node_tree
        bsdf = tree.nodes.get("Principled BSDF")
        bsdf.inputs["Roughness"].default_value = 0.9
        if node_type is not None:
            tex = tree.nodes.new(node_type)
            if configure:
                configure(tex)
            out_socket = "Color" if "Color" in tex.outputs else "Fac"
            tree.links.new(tex.outputs[out_socket],
                           bsdf.inputs["Base Color"])
        else:
            bsdf.inputs["Base Color"].default_value = (0.6, 0.6, 0.6, 1.0)
        obj.data.materials.append(mat)

    # Area light overhead + camera head-on.
    bpy.ops.object.light_add(type='AREA', location=(0.0, 0.2, 3.0))
    light = bpy.context.active_object
    light.data.energy = _LIGHT_ENERGY[0]
    light.data.size = 3.0
    light.rotation_euler = (0.0, 0.0, 0.0)

    bpy.ops.object.camera_add(location=(0.0, 0.05, 4.2),
                              rotation=(0.0, 0.0, 0.0))
    cam = bpy.context.active_object
    bpy.context.scene.camera = cam

    world = bpy.context.scene.world or bpy.data.worlds.new("pkg115_world")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs[0].default_value = (0.08, 0.09, 0.11, 1.0)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--engine", default="CUSTOM_RAYTRACER")
    p.add_argument("--out", type=Path, default=Path("test_results/pkg115_visual"))
    p.add_argument("--spp", type=int, default=64)
    p.add_argument("--light-energy", dest="light_energy", type=float,
                   default=300.0)
    p.add_argument("--resx", type=int, default=512)
    p.add_argument("--device", default="gpu",
                   help="astroray device_mode (gpu|cpu|auto)")
    args = p.parse_args(argv)

    _LIGHT_ENERGY[0] = args.light_energy
    build_scene()
    scene = bpy.context.scene
    if args.engine == "CUSTOM_RAYTRACER":
        _bootstrap_astroray_addon()
    scene.render.engine = args.engine
    scene.render.resolution_x = args.resx
    scene.render.resolution_y = args.resx // 2
    scene.render.resolution_percentage = 100
    if args.engine == "CYCLES":
        scene.cycles.samples = args.spp
        scene.cycles.use_denoising = False
    elif hasattr(scene, "custom_raytracer"):
        scene.custom_raytracer.samples = args.spp  # the F12 property
        scene.custom_raytracer.preview_samples = args.spp
        if hasattr(scene.custom_raytracer, "device_mode"):
            scene.custom_raytracer.device_mode = args.device

    args.out = args.out.resolve()  # Blender resolves relative paths
    args.out.mkdir(parents=True, exist_ok=True)  # against the blend dir
    out_png = args.out / f"{args.engine.lower()}.png"
    scene.render.filepath = str(out_png)
    bpy.ops.render.render(write_still=True)
    print(f"[pkg115-visual] wrote {out_png}")


main()
