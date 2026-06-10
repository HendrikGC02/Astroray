"""pkg108 BUG-09 + BUG-14 — real-Blender 5.1 verification of addon material routing.

Run headless:
    "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background \
        --factory-startup --python scripts/verify_pkg108_bug09_bug14_blender.py

BUG-09 (Astroray Output node): the original report said an AstrorayOutputNode
in a material's node tree was detected but its output "isn't picked up" — the
material fell through to standard Principled translation. The stub-Blender
test (tests/test_blender_native_nodes.py) passes; what remained per the spec
was verification "on a live Blender scene with an actual AstrorayOutputNode
wired up". This script IS that verification: it registers the real addon in
real Blender, builds a material whose tree contains a REAL AstrorayOutputNode
→ AstrorayShaderNodeSellmeierGlass (plus a decoy Cycles OUTPUT_MATERIAL +
Principled), runs a full engine render (which exercises the real
inline_shader_nodes() flattening pass), and asserts the C++ material created
for it is a 'dielectric' with sellmeier_preset='bk7' — NOT a principled/disney
fallback.

BUG-14 (glass tint at low roughness): the addon-routed half. A second object
gets a real Principled BSDF with Transmission=1.0, Roughness=0.02 and a strong
red Base Color; we assert the conversion emits a 'disney' material carrying
both the transmission and the red tint (the core-renderer tint response at low
roughness is covered by tests/test_pkg108_glass_color_lowroughness.py).
"""
import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import runtime_setup
runtime_setup.configure_test_imports()
sys.path.insert(0, ROOT)

import astroray as _real_astroray
import blender_addon


class _SpyRenderer:
    """Wraps a real astroray.Renderer, recording create_material calls."""

    calls = []  # class-level: shared across every renderer the addon creates

    def __init__(self, *args, **kwargs):
        object.__setattr__(self, "_r", _real_astroray.Renderer(*args, **kwargs))

    def create_material(self, kind, color, params):
        mat_id = self._r.create_material(kind, color, params)
        _SpyRenderer.calls.append((kind, list(color), dict(params), mat_id))
        return mat_id

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_r"), name)


class _SpyModule:
    """Module proxy: astroray.* passthrough, but Renderer is the spy."""

    Renderer = _SpyRenderer

    def __getattr__(self, name):
        return getattr(_real_astroray, name)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    blender_addon.register()
    blender_addon.astroray = _SpyModule()

    scene = bpy.context.scene
    scene.render.engine = "CUSTOM_RAYTRACER"
    scene.render.resolution_x = 64
    scene.render.resolution_y = 64
    scene.render.resolution_percentage = 100
    scene.custom_raytracer.samples = 2

    # Camera + light so the engine has a complete scene.
    cam_data = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cam_data)
    cam.location = (0.0, -4.0, 1.0)
    cam.rotation_euler = (1.35, 0.0, 0.0)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam

    light_data = bpy.data.lights.new("Sun", type="SUN")
    light = bpy.data.objects.new("Sun", light_data)
    light.location = (1.0, -1.0, 3.0)
    bpy.context.collection.objects.link(light)

    # --- Object 1: BUG-09 — AstrorayOutputNode → Sellmeier glass -------------
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.7, location=(-1.0, 0.0, 0.7))
    sphere = bpy.context.active_object
    mat09 = bpy.data.materials.new("Bug09SellmeierGlass")
    mat09.use_nodes = True
    tree = mat09.node_tree
    # Keep the default Principled + OUTPUT_MATERIAL as the decoy Cycles path;
    # the AstrorayOutputNode must take precedence over it.
    sellmeier = tree.nodes.new("AstrorayShaderNodeSellmeierGlass")
    sellmeier.use_preset = True
    sellmeier.preset = "bk7"
    astro_out = tree.nodes.new("AstrorayOutputNode")
    tree.links.new(sellmeier.outputs["BSDF"], astro_out.inputs["Surface"])
    sphere.data.materials.append(mat09)

    # --- Object 2: BUG-14 — Principled glass, red tint, near-zero roughness --
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(1.0, 0.0, 0.5))
    cube = bpy.context.active_object
    mat14 = bpy.data.materials.new("Bug14TintedGlass")
    mat14.use_nodes = True
    principled = next(
        n for n in mat14.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    principled.inputs["Base Color"].default_value = (0.9, 0.05, 0.05, 1.0)
    principled.inputs["Roughness"].default_value = 0.02
    principled.inputs["Transmission Weight"].default_value = 1.0
    principled.inputs["IOR"].default_value = 1.5
    cube.data.materials.append(mat14)

    bpy.context.view_layer.update()
    bpy.ops.render.render(write_still=False)

    calls = _SpyRenderer.calls
    print(f"[pkg108-verify] {len(calls)} create_material calls recorded:")
    for kind, color, params, mat_id in calls:
        print(f"[pkg108-verify]   id={mat_id} kind={kind!r} color={color} params={params}")

    failures = []

    # BUG-09: the AstrorayOutputNode material must have routed to a Sellmeier
    # dielectric, not fallen through to disney/principled.
    bug09 = [c for c in calls
             if c[0] == "dielectric" and c[2].get("sellmeier_preset") == "bk7"]
    if not bug09:
        failures.append(
            "BUG-09 REPRODUCED: no dielectric material with "
            "sellmeier_preset='bk7' was created — AstrorayOutputNode output "
            "was not picked up by the live conversion path.")

    # BUG-14 (addon half): the Principled glass must reach C++ as a disney
    # material carrying transmission=1 and the red tint.
    def _is_red(color):
        return color[0] > 0.5 and color[1] < 0.2 and color[2] < 0.2

    bug14 = [c for c in calls
             if c[0] == "disney"
             and c[2].get("transmission", 0.0) >= 0.99
             and _is_red(c[1])]
    if not bug14:
        failures.append(
            "BUG-14 (addon route) REPRODUCED: no disney material with "
            "transmission=1.0 and red base color was created — the Principled "
            "glass tint/transmission did not survive conversion.")

    if failures:
        for f in failures:
            print(f"[pkg108-verify] {f}")
        print("PKG108_BLENDER_RESULT FAIL")
        raise SystemExit(1)

    print("[pkg108-verify] BUG-09: AstrorayOutputNode routed to "
          f"dielectric/bk7 (mat id {bug09[0][3]}) — does not reproduce.")
    print("[pkg108-verify] BUG-14: Principled glass routed to disney with "
          f"transmission=1.0, red tint (mat id {bug14[0][3]}) — addon tint "
          "plumbing intact.")
    print("PKG108_BLENDER_RESULT PASS")


main()
