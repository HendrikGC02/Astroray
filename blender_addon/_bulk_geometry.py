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


def extract_curves_bulk(curves, matrix, default_radius=0.005):
    """pkg225 Stage 6 — a Blender ``Curves`` (hair / geometry-nodes) data-block →
    the arrays ``Renderer.add_curves_bulk`` consumes.

    Returns (positions, radii, strand_point_counts):
      positions            (P,3) float32 — WORLD-space control points (the engine
                           adds them directly; add_curves_bulk applies no transform)
      radii                (P,)  float32 — per-point world-space radius
      strand_point_counts  list[int]     — points per strand (each >= 2)

    Uses C-speed ``foreach_get`` for positions/radius. `matrix` is the 4x4 world
    matrix; control points are transformed by its linear+translation part and the
    per-point radius by the mean axis scale (exact for uniform scale, Cycles'
    approximation otherwise). Kept dependency-free (numpy + the passed data-block)
    so it is headlessly unit-testable with a fake ``foreach_get`` object.
    """
    points = curves.points
    n_pts = len(points)
    if n_pts == 0:
        return (np.zeros((0, 3), dtype=np.float32),
                np.zeros((0,), dtype=np.float32), [])

    co = np.empty(n_pts * 3, dtype=np.float32)
    points.foreach_get("position", co)
    co = co.reshape(n_pts, 3)
    M = np.asarray(matrix, dtype=np.float32)
    positions = np.ascontiguousarray(co @ M[:3, :3].T + M[:3, 3], dtype=np.float32)

    # Mean axis scale for the scalar radius (exact under uniform scale).
    scale = float(np.mean(np.linalg.norm(M[:3, :3], axis=0))) or 1.0
    radii = np.empty(n_pts, dtype=np.float32)
    try:
        points.foreach_get("radius", radii)
    except (RuntimeError, TypeError, AttributeError, KeyError):
        # Some Curves have radius only as a generic attribute (or none at all).
        attrs = getattr(curves, "attributes", None)
        rad_attr = attrs.get("radius") if attrs is not None else None
        if rad_attr is not None and hasattr(rad_attr, "data"):
            rad_attr.data.foreach_get("value", radii)
        else:
            radii.fill(default_radius)
    radii = np.ascontiguousarray(np.abs(radii) * scale, dtype=np.float32)
    # A zero/degenerate radius makes a strand invisible; floor it.
    radii[radii < 1e-6] = default_radius * scale

    # Per-strand point counts. Prefer the C-speed offsets; fall back to a slice
    # loop. `Curves.curve_offsets` (Blender 3.5+) is the cumulative point index of
    # each strand start plus a final total, so counts = diff(offsets).
    counts = None
    offsets_owner = getattr(curves, "curve_offsets", None)
    if offsets_owner is not None and len(offsets_owner) >= 2:
        try:
            off = np.empty(len(offsets_owner), dtype=np.int32)
            offsets_owner.foreach_get("value", off)
            counts = np.diff(off).astype(np.int64).tolist()
        except (RuntimeError, TypeError, AttributeError, KeyError):
            counts = None
    if counts is None:
        counts = [int(s.points_length) for s in curves.curves]

    # add_curves_bulk requires each strand >= 2 points; drop degenerate strands
    # (and the points they own) so a single 1-point strand can't abort the batch.
    if any(c < 2 for c in counts):
        keep_pos, keep_rad, keep_counts, off = [], [], [], 0
        for c in counts:
            if c >= 2:
                keep_pos.append(positions[off:off + c])
                keep_rad.append(radii[off:off + c])
                keep_counts.append(c)
            off += c
        positions = (np.concatenate(keep_pos, axis=0) if keep_pos
                     else np.zeros((0, 3), dtype=np.float32))
        radii = (np.concatenate(keep_rad, axis=0) if keep_rad
                 else np.zeros((0,), dtype=np.float32))
        counts = keep_counts

    return positions, radii, counts


def mesh_world_positions(mesh, matrix):
    """Return (Nt,3,3) world-space triangle-corner positions for `mesh` under
    `matrix`, using the SAME vertex->loop-triangle indexing as
    ``mesh_to_bulk_arrays``. pkg88-B: lets the addon compute a second
    ("shutter close") position array from a different, already-evaluated
    world matrix, for ``Renderer.add_triangles_bulk_motion``'s
    ``positions_end`` argument -- material/UV/normal data are identical
    between the two shutter samples (pkg88-B bakes a RIGID transform, not a
    deforming mesh, so only positions differ).
    """
    n_tri = len(mesh.loop_triangles)
    n_vert = len(mesh.vertices)

    co = np.empty(n_vert * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(n_vert, 3)
    M = np.asarray(matrix, dtype=np.float32)
    world = co @ M[:3, :3].T + M[:3, 3]

    vidx = np.empty(n_tri * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", vidx)
    vidx = vidx.reshape(n_tri, 3)
    return np.ascontiguousarray(world[vidx], dtype=np.float32)
