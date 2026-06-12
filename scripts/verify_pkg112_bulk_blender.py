"""pkg112 — real-Blender end-to-end pixel-parity for batched geometry upload.

Run headless:
    "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background \
        --factory-startup --python scripts/verify_pkg112_bulk_blender.py

Builds a REAL Blender mesh (rotation + non-uniform scale, two materials on
alternating faces, a UV layer, smooth shading → custom corner normals), extracts it
TWO ways on the actual bpy mesh data —
  (A) the legacy per-triangle path: matrix @ co / uv_data[loop].uv /
      normalize(normal_matrix @ corner_normal) → renderer.add_triangle(...)
  (B) the bulk path: blender_addon/_bulk_geometry.mesh_to_bulk_arrays(...) (real
      foreach_get) → renderer.add_triangles_bulk(...)
— renders both through the real astroray engine (build_cuda) at a fixed seed, and
asserts the images are pixel-identical. This exercises the addon's bulk extraction +
the C++ binding on genuine Blender geometry (the spec's RTX/Blender acceptance).
"""
import os
import sys

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
import _bulk_geometry
import astroray

W = H = 64
SAMPLES = 8
MAX_DEPTH = 3
SEED = 11


def _build_mesh():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # Subdivided plane → quads → loop_triangles, UVs, smooth normals.
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=6, y_subdivisions=6, size=2.0)
    obj = bpy.context.active_object
    # Non-uniform scale + rotation (exercises world transform + inverse-transpose).
    obj.scale = (1.6, 0.7, 1.2)
    obj.rotation_euler = (0.3, 0.2, 0.6)
    bpy.context.view_layer.update()
    me = obj.data
    # Two materials on alternating faces.
    for nm in ("MatA", "MatB"):
        m = bpy.data.materials.new(nm)
        me.materials.append(m)
    for i, poly in enumerate(me.polygons):
        poly.material_index = i % 2
    # Smooth shading → custom corner normals.
    for poly in me.polygons:
        poly.use_smooth = True
    # UV layer (grid_add adds one; ensure present).
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")
    me.calc_loop_triangles()
    return obj, me


def _uv_layer_items(me):
    items = []
    active = me.uv_layers.active if me.uv_layers.active else None
    if active is not None:
        items.append((active.name or "UVMap", active.data))
    for layer in me.uv_layers:
        if layer is active:
            continue
        items.append((layer.name or "UVMap", layer.data))
    return items


def _corner_normals(me):
    try:
        n = len(me.loops)
        buf = np.empty(n * 3, dtype=np.float32)
        me.corner_normals.foreach_get("vector", buf)
        return buf.reshape(n, 3)
    except Exception:
        return None


def _make_renderer():
    r = astroray.Renderer()
    r.set_background_color([0.04, 0.04, 0.06])
    ids = [r.create_material("lambertian", [0.85, 0.25, 0.25], {}),
           r.create_material("lambertian", [0.25, 0.35, 0.9], {})]
    r.add_sun_light_dedicated([0.3, -0.6, -1.0], 0.02,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 4.0)
    r.setup_camera([0.0, 0.0, 3.2], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   45.0, W / H, 0.0, 3.0, W, H)
    return r, ids


def _render(r):
    r.set_seed(SEED)
    img = np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float32)
    return img.reshape(H, W, 3) if img.ndim == 1 else img


def main():
    obj, me = _build_mesh()
    matrix = obj.matrix_world.copy()
    try:
        normal_matrix = matrix.to_3x3().inverted_safe().transposed()
    except Exception:
        normal_matrix = matrix.to_3x3()
    uv_items = _uv_layer_items(me)
    cn = _corner_normals(me)

    # --- (A) per-triangle path ---
    rA, idsA = _make_renderer()
    slot_to_id = {0: idsA[0], 1: idsA[1]}
    uv_data = uv_items[0][1] if uv_items else None
    NM = mathutils.Matrix(normal_matrix)
    for tri in me.loop_triangles:
        vs = [matrix @ me.vertices[tri.vertices[k]].co for k in range(3)]
        uv = [[0.0, 0.0]] * 3
        if uv_data is not None:
            uv = [list(uv_data[tri.loops[k]].uv) for k in range(3)]
        nn = [[], [], []]
        if cn is not None:
            nn = [list((NM @ mathutils.Vector(cn[tri.loops[k]])).normalized()) for k in range(3)]
        rA.add_triangle(list(vs[0]), list(vs[1]), list(vs[2]),
                        slot_to_id.get(tri.material_index, idsA[0]),
                        uv[0], uv[1], uv[2], nn[0], nn[1], nn[2],
                        0, int(tri.material_index))

    # --- (B) bulk path via the addon helper ---
    rB, idsB = _make_renderer()
    slot_to_id_b = {0: idsB[0], 1: idsB[1]}
    pos, mids, mpass, uvs, uvn, nrm = _bulk_geometry.mesh_to_bulk_arrays(
        me, matrix, normal_matrix, slot_to_id_b, idsB[0], uv_items)
    rB.add_triangles_bulk(pos, mids, mpass, 0, uvs, uvn, nrm)

    n_tri = len(me.loop_triangles)
    assert rA.scene_object_count() == rB.scene_object_count() == n_tri, (
        f"count mismatch: per-tri {rA.scene_object_count()} bulk {rB.scene_object_count()} "
        f"(n_tri {n_tri})")

    imgA, imgB = _render(rA), _render(rB)
    max_abs = float(np.max(np.abs(imgA - imgB)))
    identical = bool(np.array_equal(imgA, imgB))
    print(f"PKG112_BLENDER n_tri={n_tri} count_ok=True identical={identical} "
          f"max_abs_diff={max_abs:.6g} meanA={float(imgA.mean()):.4f}")
    if not identical and max_abs > 1e-5:
        print("PKG112_BLENDER_RESULT FAIL")
        raise SystemExit(1)
    print("PKG112_BLENDER_RESULT PASS")


main()
