"""pkg267 — Blender `bpy.types.Volume` / OpenVDB import for the Astroray engine.

Owner decision (Batch F, 2026-09-13): the import path is **Blender's native
OpenVDB**. Blender 5.2's bundled Python ships `openvdb` (the pyopenvdb bindings);
`bpy.types.VolumeGrid` exposes no voxel data, so the addon reads the Volume
datablock's resolved `.vdb` filepath (frame/sequence aware) with
`openvdb.readAll(...)` and hands the engine dense numpy arrays + transforms. No
engine-side `.vdb`/`.nvdb` reader exists in this track (see the research note and
pkg267 spec).

Grid transfer contract (matches `astroray::volume::DenseGrid` /
`GridMedium.set_density`):

* ``density`` — a dense float32 array shaped ``(nz, ny, nx)`` (C-order, x fastest)
  over the grid's ACTIVE-voxel bounding box,
* ``bbox_min`` — the ``(i, j, k)`` index of that block's minimum corner,
* ``index_to_object`` — the row-major 4x4 affine from voxel-index space to the
  volume's object space (from ``grid.transform``),
* ``object_to_world`` — the object's ``matrix_world`` (row-major 4x4).

``temperature`` / ``color`` / ``velocity`` are carried as passthrough handles
(consumed by pkg270); anything else is reported as a degradation.

This module is import-safe without Blender/openvdb so the unit layer can exercise
the array/transform math; the Blender-dependent helpers import lazily.
"""

from __future__ import annotations

import numpy as np

# Grid attribute names follow Cycles (`blender/volume.cpp`).
DENSITY_GRID = "density"
PASSTHROUGH_GRIDS = ("temperature", "color", "velocity", "flame", "heat")


def _import_openvdb():
    try:
        import openvdb  # Blender-bundled pyopenvdb
        return openvdb
    except ImportError as exc:  # pragma: no cover - only in non-Blender python
        raise RuntimeError(
            "volume_export requires Blender's bundled `openvdb` module; it is "
            "only importable inside Blender's Python."
        ) from exc


def index_to_object_matrix(grid):
    """Row-major 4x4 affine mapping voxel-index (i,j,k) -> volume object space.

    Built from the grid's (linear) transform: the translation is
    ``indexToWorld((0,0,0))`` and the columns are the images of the unit index
    basis vectors. openvdb "world" here is the volume datablock's object space;
    Blender then applies ``object.matrix_world`` on top.
    """
    t = grid.transform
    o = t.indexToWorld((0.0, 0.0, 0.0))
    ex = t.indexToWorld((1.0, 0.0, 0.0))
    ey = t.indexToWorld((0.0, 1.0, 0.0))
    ez = t.indexToWorld((0.0, 0.0, 1.0))
    cx = (ex[0] - o[0], ex[1] - o[1], ex[2] - o[2])
    cy = (ey[0] - o[0], ey[1] - o[1], ey[2] - o[2])
    cz = (ez[0] - o[0], ez[1] - o[1], ez[2] - o[2])
    return [
        cx[0], cy[0], cz[0], o[0],
        cx[1], cy[1], cz[1], o[1],
        cx[2], cy[2], cz[2], o[2],
        0.0,   0.0,   0.0,   1.0,
    ]


def dense_from_grid(grid):
    """Return ``(density_nzyx_float32, bbox_min_ijk)`` over the active bbox.

    openvdb ``evalActiveVoxelBoundingBox`` is inclusive; ``copyToArray(out, ijk)``
    fills ``out[x, y, z]`` with the voxel value at ``(ijk + (x, y, z))``. We then
    transpose to ``(nz, ny, nx)`` C-order to match the engine contract.
    """
    mn, mx = grid.evalActiveVoxelBoundingBox()
    dim = (mx[0] - mn[0] + 1, mx[1] - mn[1] + 1, mx[2] - mn[2] + 1)
    if dim[0] <= 0 or dim[1] <= 0 or dim[2] <= 0:
        # Empty grid -> a single background voxel so the engine has valid bounds.
        return np.zeros((1, 1, 1), dtype=np.float32), (int(mn[0]), int(mn[1]), int(mn[2]))
    out = np.zeros((dim[0], dim[1], dim[2]), dtype=np.float32)  # [x, y, z]
    grid.copyToArray(out, ijk=(int(mn[0]), int(mn[1]), int(mn[2])))
    nzyx = np.ascontiguousarray(out.transpose(2, 1, 0))  # -> [z, y, x]
    return nzyx, (int(mn[0]), int(mn[1]), int(mn[2]))


def resolve_vdb_filepath(volume_data, bpy_module=None):
    """Resolve the current frame's `.vdb` path for a Volume datablock.

    Prefers ``volume.grids.frame_filepath`` (already frame/sequence resolved);
    falls back to ``bpy.path.abspath(volume.filepath)``.
    """
    grids = getattr(volume_data, "grids", None)
    fp = getattr(grids, "frame_filepath", "") if grids is not None else ""
    if not fp:
        fp = getattr(volume_data, "filepath", "")
        if bpy_module is not None and fp:
            fp = bpy_module.path.abspath(fp)
    return fp


def payload_from_vdb(filepath, object_to_world, report=None):
    """Read a `.vdb` file and build the engine grid-transfer payload.

    ``object_to_world`` is a flat row-major length-16 list. Returns a dict with
    ``density`` (np.float32 (nz,ny,nx)), ``bbox_min``, ``index_to_object``,
    ``object_to_world`` and optional passthrough arrays, plus a ``degradations``
    list naming any grid we did not honour (pkg200 rule: never claim honour
    silently).
    """
    openvdb = _import_openvdb()
    grids = openvdb.readAll(filepath)[0]  # (grids, file_metadata)
    by_name = {g.name: g for g in grids}
    degradations = []

    if DENSITY_GRID not in by_name:
        # Some fog caches name the scalar grid differently; take the first
        # scalar FloatGrid as density and report the substitution.
        float_grids = [g for g in grids if g.valueTypeName == "float"]
        if not float_grids:
            raise RuntimeError(
                "no 'density' grid and no scalar grid in %s" % filepath)
        by_name[DENSITY_GRID] = float_grids[0]
        degradations.append(
            "no 'density' grid; used scalar grid '%s'" % float_grids[0].name)

    density, bbox_min = dense_from_grid(by_name[DENSITY_GRID])
    payload = {
        "density": density,
        "bbox_min": bbox_min,
        "index_to_object": index_to_object_matrix(by_name[DENSITY_GRID]),
        "object_to_world": list(object_to_world),
        "degradations": degradations,
    }

    # temperature passthrough (pkg270) — carried, not evaluated here.
    if "temperature" in by_name:
        temp, temp_bbox = dense_from_grid(by_name["temperature"])
        payload["temperature"] = temp
        payload["temperature_bbox_min"] = temp_bbox

    for name, g in by_name.items():
        if name == DENSITY_GRID or name == "temperature":
            continue
        degradations.append("grid '%s' not yet consumed (pkg270/pkg272)" % name)

    if report is not None and degradations:
        for d in degradations:
            report(d)
    return payload


def flatten_matrix_world(matrix_world):
    """Flatten a mathutils.Matrix (or any row-iterable 4x4) to a row-major list."""
    return [float(c) for row in matrix_world for c in row]


def _socket_rgb(node, name, default=(0.8, 0.8, 0.8)):
    s = node.inputs.get(name) if hasattr(node.inputs, "get") else None
    if s is None:
        return list(default)
    v = s.default_value
    try:
        return [float(v[0]), float(v[1]), float(v[2])]
    except (TypeError, IndexError):
        return [float(v)] * 3


def _socket_float(node, name, default=0.0):
    s = node.inputs.get(name) if hasattr(node.inputs, "get") else None
    if s is None:
        return float(default)
    try:
        return float(s.default_value)
    except (TypeError, ValueError):
        return float(default)


def principled_volume_from_material(material):
    """Extract Principled-Volume-basics params from a material's node tree.

    Returns a dict ``{density, color, absorption_color, anisotropy, has_surface,
    degradations}`` when the Material Output has a Volume input connected, else
    ``None``. Supports ``ShaderNodeVolumePrincipled`` / ``ShaderNodeVolumeScatter``
    / ``ShaderNodeVolumeAbsorption`` (Cycles socket semantics). Honours only the
    basics (density/color/absorption/anisotropy); every other socket or node is
    reported as a degradation (pkg200 rule).
    """
    nt = getattr(material, "node_tree", None)
    if nt is None:
        return None
    out = None
    for n in nt.nodes:
        if n.type == "OUTPUT_MATERIAL" and getattr(n, "is_active_output", True):
            out = n
            break
    if out is None:
        return None
    vol_in = out.inputs.get("Volume")
    if vol_in is None or not vol_in.is_linked:
        return None
    node = vol_in.links[0].from_node
    has_surface = bool(out.inputs.get("Surface") and out.inputs["Surface"].is_linked)
    degr = []
    info = {"has_surface": has_surface, "anisotropy": 0.0,
            "absorption_color": [1.0, 1.0, 1.0], "degradations": degr}
    ntype = node.type
    if ntype == "VOLUME_PRINCIPLED" or "Principled" in node.bl_idname:
        info["density"] = _socket_float(node, "Density", 1.0)
        info["color"] = _socket_rgb(node, "Color", (0.8, 0.8, 0.8))
        info["absorption_color"] = _socket_rgb(node, "Absorption Color", (1.0, 1.0, 1.0))
        info["anisotropy"] = _socket_float(node, "Anisotropy", 0.0)
        if _socket_float(node, "Emission Strength", 0.0) > 0.0:
            degr.append("Principled Volume emission not honoured (pkg270)")
    elif ntype == "VOLUME_SCATTER" or "Scatter" in node.bl_idname:
        info["density"] = _socket_float(node, "Density", 1.0)
        info["color"] = _socket_rgb(node, "Color", (0.8, 0.8, 0.8))  # scattering albedo
        info["anisotropy"] = _socket_float(node, "Anisotropy", 0.0)
    elif ntype == "VOLUME_ABSORPTION" or "Absorption" in node.bl_idname:
        info["density"] = _socket_float(node, "Density", 1.0)
        info["color"] = [0.0, 0.0, 0.0]  # pure absorption: albedo 0
        info["absorption_color"] = _socket_rgb(node, "Color", (1.0, 1.0, 1.0))
    else:
        degr.append("unsupported volume node '%s' (pkg270/pkg272)" % node.bl_idname)
        return None
    # colored absorption is a chromatic-extinction effect -> pkg270 (grey here).
    ac = info.get("absorption_color", [1, 1, 1])
    if abs(ac[0] - ac[1]) > 1e-3 or abs(ac[0] - ac[2]) > 1e-3:
        degr.append("chromatic absorption colour approximated grey (pkg270)")
    return info


def mesh_world_aabb(obj, matrix_world):
    """World-space AABB of a mesh object's local bound box under matrix_world."""
    import numpy as _np
    corners = [_np.array(matrix_world @ _cornerv(c)) for c in obj.bound_box]
    arr = _np.array(corners)
    return arr.min(axis=0).tolist(), arr.max(axis=0).tolist()


def _cornerv(c):
    # obj.bound_box yields length-3 sequences; build a mathutils-compatible vec4.
    import mathutils  # Blender only
    return mathutils.Vector((c[0], c[1], c[2]))


def export_volume_objects(depsgraph, renderer, bpy_module=None, report=None):
    """Walk the depsgraph, export every `VOLUME` object to ``renderer``.

    For each Volume object, resolves its `.vdb`, builds the payload and calls
    ``renderer.set_volume_grid(name, density, bbox_min, index_to_object,
    object_to_world, temperature=...)`` when the renderer exposes it (pkg268
    wires transport; pkg267 ships the import path + handle). Returns the list of
    exported object names.
    """
    exported = []
    for inst in depsgraph.object_instances:
        obj = inst.object
        if obj is None or obj.type != "VOLUME":
            continue
        filepath = resolve_vdb_filepath(obj.data, bpy_module)
        if not filepath:
            if report is not None:
                report("volume object '%s' has no resolved .vdb filepath" % obj.name)
            continue
        obj_to_world = flatten_matrix_world(inst.matrix_world)
        payload = payload_from_vdb(filepath, obj_to_world, report=report)
        set_grid = getattr(renderer, "set_volume_grid", None)
        if set_grid is not None:
            kwargs = dict(
                density=payload["density"],
                bbox_min=payload["bbox_min"],
                index_to_object=payload["index_to_object"],
                object_to_world=payload["object_to_world"],
            )
            if "temperature" in payload:
                kwargs["temperature"] = payload["temperature"]
            set_grid(obj.name, **kwargs)
        exported.append(obj.name)
    return exported
