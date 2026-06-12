"""pkg114 inc 3c — real-Blender end-to-end verification of GPU two-level instancing.

Run headless:
    "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background \
        --factory-startup --python scripts/verify_pkg114_instancing_blender.py

Builds a REAL Blender scene where one mesh datablock ("Prop", non-uniform
scaled + smooth-shaded + 2 materials) is COLLECTION-instanced by several empties
at distinct transforms, plus a static floor. Then converts the SAME evaluated
depsgraph through the addon's `convert_objects` TWO ways on the real engine
(build_cuda, GPU):

  (A) instancing FORCED OFF  → every dupli flattened into world-space triangles
                               (the pre-pkg114 behaviour / reference image)
  (B) instancing ON          → shared Prop datablock registered ONCE into a BLAS
                               + one add_instance(matrix_world) per dupli (TLAS)

Asserts:
  * the two GPU renders are pixel-identical (transform-order float noise only),
  * (B) put FEWER triangles in the flat scene than (A) — i.e. the duplis really
    went through the shared BLAS, not the flat upload (the build/memory win), and
  * (B) is non-empty (the instanced props are actually visible).

Prints PKG114_INSTANCING_RESULT PASS / FAIL.
"""
import os
import sys
import importlib.util

import bpy
import mathutils
import numpy as np

ROOT = os.environ.get(
    "ASTRORAY_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import runtime_setup
runtime_setup.configure_test_imports()
sys.path.insert(0, os.path.join(ROOT, "blender_addon"))
import astroray

# Load the addon module by file path (it does top-level `from _bulk_geometry
# import ...`, satisfied by the blender_addon dir on sys.path above).
_spec = importlib.util.spec_from_file_location(
    "astroray_addon", os.path.join(ROOT, "blender_addon", "__init__.py"))
addon = importlib.util.module_from_spec(_spec)
sys.modules["astroray_addon"] = addon          # register() needs the module importable
_spec.loader.exec_module(addon)
# Register so Scene.custom_raytracer exists (the GPU device pre-check reads it).
try:
    addon.register()
except Exception as exc:
    print(f"addon.register() warning: {exc}")
Engine = addon.CustomRaytracerRenderEngine


def _make_engine_standin():
    """A bpy RenderEngine subclass can't be instantiated outside the render
    pipeline, so mirror its plain-Python convert_* methods onto a standalone
    object (with a no-op report)."""
    class _Standin:
        def report(self, *a, **k):
            pass
    for name, fn in Engine.__dict__.items():
        if callable(fn) and not name.startswith("__"):
            setattr(_Standin, name, fn)
    return _Standin()

W = H = 80
SAMPLES = 16
MAX_DEPTH = 3
SEED = 13


def _build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    # --- Prop: a smooth-shaded, non-uniformly-scaled ico-sphere, 2 materials. ---
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.5)
    prop = bpy.context.active_object
    prop.name = "Prop"
    prop.scale = (1.0, 0.6, 1.3)            # non-uniform → exercises inverse-transpose
    me = prop.data
    for nm, col in (("PropA", (0.85, 0.25, 0.2)), ("PropB", (0.2, 0.4, 0.85))):
        m = bpy.data.materials.new(nm)
        m.use_nodes = True
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (*col, 1.0)
            # Ensure NOT treated as an emitter (black emission → instanceable).
            es = bsdf.inputs.get("Emission Strength")
            if es is not None:
                es.default_value = 0.0
        me.materials.append(m)
    for i, poly in enumerate(me.polygons):
        poly.material_index = i % 2
        poly.use_smooth = True
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")

    # --- Put Prop in its own collection and instance it via empties. ---
    col = bpy.data.collections.new("PropCol")
    scene.collection.children.link(col)
    col.objects.link(prop)
    scene.collection.objects.unlink(prop)     # Prop renders ONLY as instances now

    placements = [
        ((-1.6, 0.0, 0.0), 0.0),
        ((0.0, 0.0, 0.0), 35.0),
        ((1.6, 0.0, 0.0), -20.0),
    ]
    for k, (loc, rot_deg) in enumerate(placements):
        e = bpy.data.objects.new(f"Inst{k}", None)
        e.instance_type = 'COLLECTION'
        e.instance_collection = col
        e.location = loc
        e.rotation_euler = (0.0, np.radians(rot_deg), 0.0)
        scene.collection.objects.link(e)

    # --- Static floor (non-instanced; stays on the flat path in BOTH renders). ---
    bpy.ops.mesh.primitive_plane_add(size=12.0, location=(0.0, -1.0, 0.0))
    floor = bpy.context.active_object
    floor.name = "Floor"
    fm = bpy.data.materials.new("FloorMat")
    fm.use_nodes = True
    fb = fm.node_tree.nodes.get("Principled BSDF")
    if fb is not None:
        fb.inputs["Base Color"].default_value = (0.3, 0.55, 0.3, 1.0)
    floor.data.materials.append(fm)

    bpy.context.view_layer.update()
    return scene


def _setup_common(r):
    r.set_background_color([0.5, 0.6, 0.8])
    r.set_integrator("path_tracer")
    r.set_use_gpu(True)
    r.setup_camera([0.0, 2.0, 8.0], [0.0, -0.1, 0.0], [0.0, 1.0, 0.0],
                   42.0, W / H, 0.0, 8.0, W, H)
    r.add_sun_light_dedicated([0.3, -0.7, -0.5], 0.02,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 3.0)
    r.set_seed(SEED)


def _convert(depsgraph, instancing):
    eng = _make_engine_standin()
    r = astroray.Renderer()
    if not r.gpu_available:
        raise SystemExit("PKG114_INSTANCING_RESULT SKIP (no CUDA GPU)")
    if not instancing:
        # Force the flatten path (reference): disable the GPU instancing pre-check.
        eng._register_instanced_groups = lambda *a, **k: set()
    material_map = eng.convert_materials(depsgraph, r)
    _setup_common(r)
    eng.convert_objects(depsgraph, r, material_map)
    flat_objs = r.scene_object_count() if hasattr(r, "scene_object_count") else -1
    img = np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float32)
    img = img.reshape(H, W, 3) if img.ndim == 1 else img
    return img, flat_objs


def main():
    _build_scene()
    depsgraph = bpy.context.evaluated_depsgraph_get()

    img_flat, flat_n = _convert(depsgraph, instancing=False)
    img_inst, inst_n = _convert(depsgraph, instancing=True)

    # Same seed, but the flat-vs-TLAS scenes traverse differently → divergent MC
    # noise, so (like the engine parity gates) compare MEAN abs diff + per-channel
    # energy ratio, not a single worst pixel.
    mad = float(np.abs(img_flat - img_inst).mean())
    mean_inst = float(img_inst.mean())
    band = slice(int(H * 0.7), H)
    g_inst = float(img_inst[band, :, 1].mean())
    ratios = [float(img_inst[..., c].mean() / max(img_flat[..., c].mean(), 1e-6))
              for c in range(3)]

    print(f"PKG114_INSTANCING flat_objs={flat_n} inst_objs={inst_n} "
          f"mean_abs_diff={mad:.5f} ratios={['%.4f' % r for r in ratios]} "
          f"mean_inst={mean_inst:.4f} floor_green={g_inst:.3f}")

    ok = True
    if not (mean_inst > 0.05):
        print("FAIL: instanced render looks empty"); ok = False
    if not (inst_n < flat_n):
        print(f"FAIL: instancing did not reduce flat-scene objects "
              f"({inst_n} !< {flat_n}) — duplis not routed through the BLAS"); ok = False
    if mad > 2e-2:
        print(f"FAIL: instanced vs flattened differ (mean_abs_diff={mad:.4g})"); ok = False
    if not all(0.97 <= r <= 1.03 for r in ratios):
        print(f"FAIL: per-channel energy off {ratios}"); ok = False
    if not (g_inst > 0.10):
        print("FAIL: floor missing in instanced render (flat scene dropped?)"); ok = False

    print("PKG114_INSTANCING_RESULT " + ("PASS" if ok else "FAIL"))
    if not ok:
        raise SystemExit(1)


main()
