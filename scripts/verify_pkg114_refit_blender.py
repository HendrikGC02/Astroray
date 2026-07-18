"""pkg114 inc 3d — real-Blender end-to-end verification of the TLAS-only REFIT.

Run headless:
    "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background \
        --factory-startup --python scripts/verify_pkg114_refit_blender.py

Builds the same collection-instanced scene as verify_pkg114_instancing_blender.py
(one "Prop" datablock instanced by several empties + a static floor), full-syncs it
through the addon's `convert_objects` on a REAL GPU renderer at transform state A,
then MOVES an instancer empty and exercises the exporter's transform-only fast path
directly:

    engine.refit_instance_transforms(depsgraph_B, r)   # re-derive each dupli xform
    r.upload_instance_transforms()                      # TLAS-only re-push
    img_refit = r.render(..., skip_upload=True)         # render from device state

and compares that to a from-scratch full re-sync at B (fresh renderer,
`convert_objects` at the new transforms, normal render). Mirrors test_tlas_refit.py:

  * CORRECTNESS: mean-abs-diff(refit, full-resync @ B) < 0.02.
  * NON-VACUOUS: A and B renders differ (the empty really moved the image).
  * NEGATIVE CONTROL: render(skip_upload=True) WITHOUT the refit keeps device @ A,
    so it differs from the oracle @ B (proves skip_upload reads device state).

Prints PKG114_REFIT_RESULT PASS / FAIL.
"""
import os
import sys
import importlib.util

import bpy
import numpy as np

ROOT = os.environ.get(
    "ASTRORAY_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import runtime_setup
runtime_setup.configure_test_imports()
sys.path.insert(0, os.path.join(ROOT, "blender_addon"))
import astroray

_spec = importlib.util.spec_from_file_location(
    "astroray_addon", os.path.join(ROOT, "blender_addon", "__init__.py"))
addon = importlib.util.module_from_spec(_spec)
sys.modules["astroray_addon"] = addon
_spec.loader.exec_module(addon)
try:
    addon.register()
except Exception as exc:
    print(f"addon.register() warning: {exc}")
Engine = addon.CustomRaytracerRenderEngine


def _make_engine_standin():
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

    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.5)
    prop = bpy.context.active_object
    prop.name = "Prop"
    prop.scale = (1.0, 0.6, 1.3)
    me = prop.data
    for nm, col in (("PropA", (0.85, 0.25, 0.2)), ("PropB", (0.2, 0.4, 0.85))):
        m = bpy.data.materials.new(nm)
        m.use_nodes = True
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (*col, 1.0)
            es = bsdf.inputs.get("Emission Strength")
            if es is not None:
                es.default_value = 0.0
        me.materials.append(m)
    for i, poly in enumerate(me.polygons):
        poly.material_index = i % 2
        poly.use_smooth = True
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")

    col = bpy.data.collections.new("PropCol")
    scene.collection.children.link(col)
    col.objects.link(prop)
    scene.collection.objects.unlink(prop)

    placements = [
        ((-1.6, 0.0, 0.0), 0.0),
        ((0.0, 0.0, 0.0), 35.0),
        ((1.6, 0.0, 0.0), -20.0),
    ]
    empties = []
    for k, (loc, rot_deg) in enumerate(placements):
        e = bpy.data.objects.new(f"Inst{k}", None)
        e.instance_type = 'COLLECTION'
        e.instance_collection = col
        e.location = loc
        e.rotation_euler = (0.0, np.radians(rot_deg), 0.0)
        scene.collection.objects.link(e)
        empties.append(e)

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
    return scene, empties


def _setup_common(r):
    r.set_background_color([0.5, 0.6, 0.8])
    r.set_integrator("path_tracer")
    r.set_use_gpu(True)
    r.setup_camera([0.0, 2.0, 8.0], [0.0, -0.1, 0.0], [0.0, 1.0, 0.0],
                   42.0, W / H, 0.0, 8.0, W, H)
    r.add_sun_light_dedicated([0.3, -0.7, -0.5], 0.02,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 3.0)
    r.set_seed(SEED)


def _render(r, skip_upload=False):
    img = np.asarray(
        r.render(SAMPLES, MAX_DEPTH, None, False, -1, -1, -1, -1, -1, skip_upload),
        dtype=np.float32)
    return img.reshape(H, W, 3) if img.ndim == 1 else img


def _full_sync(eng, depsgraph):
    """Fresh renderer, full convert at the depsgraph's current transforms."""
    r = astroray.Renderer()
    if not r.gpu_available:
        raise SystemExit("PKG114_REFIT_RESULT SKIP (no CUDA GPU)")
    material_map = eng.convert_materials(depsgraph, r)
    _setup_common(r)
    eng.convert_objects(depsgraph, r, material_map)
    return r


def main():
    scene, empties = _build_scene()
    eng = _make_engine_standin()

    # NB: bpy.context.evaluated_depsgraph_get() returns the scene's single depsgraph,
    # re-evaluated IN PLACE by view_layer.update(). So we capture the state-A images
    # (and the negative control) BEFORE moving, then reuse the same depsgraph handle
    # for the refit/oracle after the move.
    depsgraph = bpy.context.evaluated_depsgraph_get()

    # --- State A: full sync + prime device. ---
    r = _full_sync(eng, depsgraph)
    id_map = dict(getattr(eng, "_renderer_instance_id_map", {}))
    elig = dict(getattr(eng, "_renderer_instancer_eligible", {}))
    img_a = _render(r)                          # normal (full upload) render @ A

    # --- Negative control: skip_upload WITHOUT a refit reads the device state,
    #     which is still A. Captured before the move; must differ from the B oracle.
    img_stale = _render(r, skip_upload=True)

    # --- Move (and scale) an instancer empty dramatically → state B. Big enough that
    #     its dupli clearly relocates on the 80x80 frame (non-vacuous move); scaling
    #     the empty also exercises composed (empty ∘ prop_local) matrices in refit.
    empties[1].location = (0.0, 1.3, 3.4)
    empties[1].scale = (2.4, 2.4, 2.4)
    empties[1].rotation_euler = (0.0, np.radians(70.0), 0.0)
    bpy.context.view_layer.update()

    # --- REFIT path (the exporter fast path, driven directly): re-derive every mapped
    #     instance's fresh matrix_world, TLAS-only re-push, render from device state.
    eng.refit_instance_transforms(depsgraph, r)
    r.upload_instance_transforms()
    img_refit = _render(r, skip_upload=True)

    # --- Oracle: from-scratch full re-sync at B. ---
    r_oracle = _full_sync(eng, depsgraph)
    img_oracle = _render(r_oracle)

    mad_refit = float(np.abs(img_refit - img_oracle).mean())
    mad_moved = float(np.abs(img_a - img_oracle).mean())
    mad_stale = float(np.abs(img_stale - img_oracle).mean())

    print(f"PKG114_REFIT instancer_eligible={elig} "
          f"instanced_names={list(id_map.keys())} "
          f"n_instances={sum(len(v) for v in id_map.values())}")
    print(f"PKG114_REFIT mad_refit_vs_oracle={mad_refit:.5f} "
          f"mad_A_vs_oracle(moved)={mad_moved:.5f} "
          f"mad_stale_vs_oracle(neg_ctrl)={mad_stale:.5f} "
          f"mean_refit={float(img_refit.mean()):.4f}")

    ok = True
    if not any(elig.values()):
        print("FAIL: no instancer was refit-eligible (empty-move path never armed)")
        ok = False
    if not (img_refit.mean() > 0.05):
        print("FAIL: refit render looks empty"); ok = False
    if mad_refit > 0.02:
        print(f"FAIL: refit != full re-sync @ B (mad={mad_refit:.4g} > 0.02)"); ok = False
    if not (mad_moved > 0.02):
        print(f"FAIL: moving the empty did not change the image (mad={mad_moved:.4g}) "
              f"— test is vacuous"); ok = False
    if not (mad_stale > 0.02):
        print(f"FAIL: skip_upload without refit matched the oracle (mad={mad_stale:.4g}) "
              f"— skip_upload not reading device state"); ok = False

    print("PKG114_REFIT_RESULT " + ("PASS" if ok else "FAIL"))
    if not ok:
        raise SystemExit(1)


main()
