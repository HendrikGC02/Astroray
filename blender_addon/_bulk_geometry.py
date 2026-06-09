"""pkg112 — pure mesh → bulk-upload arrays.

Extracts an entire Blender mesh's loop-triangles into the contiguous NumPy arrays
that ``Renderer.add_triangles_bulk`` consumes, using Blender's C-speed
``foreach_get`` instead of a per-triangle Python loop. Kept dependency-free (only
``numpy`` + the passed-in Blender mesh) so it is unit-testable headlessly with a
fake ``foreach_get`` mesh — independent of the compiled engine ``.pyd`` and of the
addon's bpy class registration.

The output is byte-for-byte the same data the legacy per-triangle path fed to
``add_triangle`` / ``add_triangle_layers`` (same world transform, same slot→id
remap, same active-first UV-layer order, same inverse-transpose corner normals),
so the resulting render is pixel-identical.
"""
import numpy as np


def mesh_to_bulk_arrays(mesh, matrix, normal_matrix, slot_to_id, default_mat_id,
                        uv_layer_items):
    """Return (positions, material_ids, material_pass_indices, uvs, uv_names, normals).

    positions             (Nt,3,3) float32 — world-space triangle corners
    material_ids          (Nt,)    int32   — engine material ids (slot→id remapped)
    material_pass_indices (Nt,)    int32   — raw Blender material_index per triangle
    uvs                   (nLayers,Nt,3,2) float32, active layer first (empty if none)
    uv_names              list[str] — layer names, active first
    normals               (Nt,3,3) float32 world-space corner normals (empty → faces)

    `matrix` is the 4×4 model matrix, `normal_matrix` the 3×3 inverse-transpose;
    both may be mathutils.Matrix or anything np.asarray turns into the right shape.
    `uv_layer_items` is the active-first list of (name, layer.data).
    """
    n_tri = len(mesh.loop_triangles)
    n_vert = len(mesh.vertices)

    # Vertices (object space) → world via the 4×4 model matrix.
    co = np.empty(n_vert * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(n_vert, 3)
    M = np.asarray(matrix, dtype=np.float32)
    world = co @ M[:3, :3].T + M[:3, 3]                          # (n_vert, 3)

    # Loop-triangle vertex + loop indices.
    vidx = np.empty(n_tri * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", vidx)
    vidx = vidx.reshape(n_tri, 3)
    lidx = np.empty(n_tri * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("loops", lidx)
    lidx = lidx.reshape(n_tri, 3)
    positions = np.ascontiguousarray(world[vidx], dtype=np.float32)   # (Nt,3,3)

    # Per-face material slot → engine id (same map the per-tri path used).
    mface = np.empty(n_tri, dtype=np.int32)
    mesh.loop_triangles.foreach_get("material_index", mface)
    lut_size = int(mface.max()) + 1 if n_tri else 1
    if slot_to_id:
        lut_size = max(lut_size, max(slot_to_id.keys()) + 1)
    lut = np.full(lut_size, default_mat_id, dtype=np.int32)
    for _s, _mi in slot_to_id.items():
        if 0 <= _s < lut_size:
            lut[_s] = _mi
    material_ids = np.ascontiguousarray(lut[mface], dtype=np.int32)
    mat_pass = np.ascontiguousarray(mface, dtype=np.int32)

    # UV layers, ACTIVE FIRST → (nLayers, Nt, 3, 2).
    if uv_layer_items:
        n_loop = len(mesh.loops)
        layer_arrs = []
        for _name, layer_data in uv_layer_items:
            uvbuf = np.empty(n_loop * 2, dtype=np.float32)
            layer_data.foreach_get("uv", uvbuf)
            layer_arrs.append(uvbuf.reshape(n_loop, 2)[lidx])       # (Nt,3,2)
        uvs = np.ascontiguousarray(np.stack(layer_arrs, axis=0), dtype=np.float32)
        uv_names = [name for name, _ in uv_layer_items]
    else:
        uvs = np.zeros((0,), dtype=np.float32)
        uv_names = []

    # Per-corner split normals (Blender 4.1+ mesh.corner_normals), inverse-transpose
    # 3×3 transformed + normalized. Fall back to empty (face normals) if unavailable
    # — mirrors the per-tri try/except on tri.split_normals.
    try:
        n_loop = len(mesh.loops)
        cn = np.empty(n_loop * 3, dtype=np.float32)
        mesh.corner_normals.foreach_get("vector", cn)
        cn = cn.reshape(n_loop, 3)[lidx]                            # (Nt,3,3)
        N3 = np.asarray(normal_matrix, dtype=np.float32)
        cn = cn @ N3.T
        ln = np.linalg.norm(cn, axis=2, keepdims=True)
        ln[ln == 0.0] = 1.0
        normals = np.ascontiguousarray(cn / ln, dtype=np.float32)
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
        normals = np.zeros((0,), dtype=np.float32)

    return positions, material_ids, mat_pass, uvs, uv_names, normals
