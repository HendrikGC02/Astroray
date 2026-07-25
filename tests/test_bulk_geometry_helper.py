"""pkg112 — `mesh_to_bulk_arrays` reproduces the per-triangle extraction exactly.

This is the headless (no-Blender, no-engine) validation of the addon's bulk geometry
EXTRACTION: a fake Blender mesh implementing the documented `foreach_get` contract is
fed through the helper, and every output array is checked against the legacy per-triangle
extraction (matrix @ co, uv_data[loop].uv, normalize(normal_matrix @ split_normal),
slot→id remap). Combined with the binding's bit-identical render
(test_bulk_geometry_upload), this closes pixel-parity for the bulk path.
"""
import os
import sys

import numpy as np
import pytest

# Import the helper as a standalone module (mirrors how the addon imports it with
# addon_dir on sys.path) so we DON'T trigger blender_addon/__init__.py (bpy/engine).
_ADDON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "blender_addon")
if _ADDON_DIR not in sys.path:
    sys.path.insert(0, _ADDON_DIR)
import _bulk_geometry  # noqa: E402


class _Coll:
    """Minimal Blender-collection stub: __len__ + foreach_get(attr, buf) filling
    buf in place from a stored flat list (the documented foreach_get contract)."""
    def __init__(self, n, attrs):
        self._n = n
        self._attrs = {k: np.asarray(v, dtype=np.float64) for k, v in attrs.items()}

    def __len__(self):
        return self._n

    def foreach_get(self, name, buf):
        data = self._attrs[name]
        assert buf.shape[0] == data.shape[0], f"{name}: buf {buf.shape} vs data {data.shape}"
        buf[:] = data


class _Mesh:
    def __init__(self, vertices, loop_triangles, loops, corner_normals):
        self.vertices = vertices
        self.loop_triangles = loop_triangles
        self.loops = loops
        self.corner_normals = corner_normals


def _make_mesh():
    # Two triangles from a quad (4 verts, 4 loops). loop i -> vertex i.
    verts = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0.5], [0, 1, 0.5]], dtype=np.float64)
    tri_verts = [0, 1, 2, 0, 2, 3]
    tri_loops = [0, 1, 2, 0, 2, 3]
    tri_mat = [0, 1]
    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float64)
    cn = np.array([[-0.2, -0.1, 1.0], [0.2, -0.1, 1.0],
                   [0.2, 0.2, 1.0], [-0.2, 0.2, 1.0]], dtype=np.float64)
    mesh = _Mesh(
        vertices=_Coll(4, {"co": verts.reshape(-1)}),
        loop_triangles=_Coll(2, {"vertices": tri_verts, "loops": tri_loops,
                                 "material_index": tri_mat}),
        loops=_Coll(4, {}),
        corner_normals=_Coll(4, {"vector": cn.reshape(-1)}),
    )
    uv_layer = _Coll(4, {"uv": uv.reshape(-1)})
    return mesh, verts, tri_verts, tri_loops, tri_mat, uv, cn, uv_layer


def _transform():
    # Non-uniform scale + rotation + translation — exercises the world transform
    # AND the inverse-transpose normal handling (a wrong normal_matrix shows here).
    th = 0.6
    R = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]])
    S = np.diag([2.0, 0.5, 1.3])
    A = R @ S
    M = np.eye(4)
    M[:3, :3] = A
    M[:3, 3] = [1.0, -2.0, 0.5]
    normal_matrix = np.linalg.inv(A).T  # inverse-transpose 3x3
    return M.astype(np.float32), normal_matrix.astype(np.float32)


def test_helper_matches_per_triangle_extraction():
    mesh, verts, tri_verts, tri_loops, tri_mat, uv, cn, uv_layer = _make_mesh()
    M, NM = _transform()
    slot_to_id = {0: 10, 1: 20}
    default_mat_id = 10
    uv_layer_items = [("UVMap", uv_layer)]

    positions, material_ids, mat_pass, uvs, uv_names, normals = \
        _bulk_geometry.mesh_to_bulk_arrays(mesh, M, NM, slot_to_id, default_mat_id,
                                           uv_layer_items)

    # --- per-triangle reference (the legacy loop) ---
    world = verts @ M[:3, :3].T.astype(np.float64) + M[:3, 3].astype(np.float64)
    tv = np.array(tri_verts).reshape(2, 3)
    tl = np.array(tri_loops).reshape(2, 3)
    exp_pos = world[tv]                                              # (2,3,3)
    exp_uv = uv[tl][None]                                           # (1,2,3,2)
    raw_n = cn[tl] @ NM.T.astype(np.float64)                        # (2,3,3)
    exp_n = raw_n / np.linalg.norm(raw_n, axis=2, keepdims=True)
    exp_mid = np.array([slot_to_id[m] for m in tri_mat], dtype=np.int32)

    assert positions.shape == (2, 3, 3)
    np.testing.assert_allclose(positions, exp_pos, rtol=0, atol=1e-5)
    np.testing.assert_array_equal(material_ids, exp_mid)
    np.testing.assert_array_equal(mat_pass, np.array(tri_mat, dtype=np.int32))
    assert uv_names == ["UVMap"]
    assert uvs.shape == (1, 2, 3, 2)
    np.testing.assert_allclose(uvs, exp_uv, rtol=0, atol=1e-6)
    assert normals.shape == (2, 3, 3)
    np.testing.assert_allclose(normals, exp_n, rtol=0, atol=1e-5)


def test_helper_multi_uv_layer_order_preserved():
    mesh, verts, tri_verts, tri_loops, tri_mat, uv, cn, uv_layer = _make_mesh()
    M, NM = _transform()
    uv2 = _Coll(4, {"uv": (uv * 0.5).reshape(-1)})
    uv_layer_items = [("UVMap", uv_layer), ("Lightmap", uv2)]  # active first
    positions, material_ids, mat_pass, uvs, uv_names, normals = \
        _bulk_geometry.mesh_to_bulk_arrays(mesh, M, NM, {0: 0, 1: 1}, 0, uv_layer_items)
    assert uv_names == ["UVMap", "Lightmap"]
    assert uvs.shape == (2, 2, 3, 2)            # (nLayers, Nt, 3, 2)
    tl = np.array(tri_loops).reshape(2, 3)
    np.testing.assert_allclose(uvs[0], uv[tl], atol=1e-6)
    np.testing.assert_allclose(uvs[1], (uv * 0.5)[tl], atol=1e-6)


def test_helper_no_uv_empty_arrays():
    mesh, *_ = _make_mesh()
    M, NM = _transform()
    positions, material_ids, mat_pass, uvs, uv_names, normals = \
        _bulk_geometry.mesh_to_bulk_arrays(mesh, M, NM, {}, 0, [])
    assert uvs.size == 0 and uv_names == []
    assert material_ids.tolist() == [0, 0]   # empty slot_to_id -> default_mat_id


# --- pkg88-B: mesh_world_positions (object motion blur shutter-close bake) ---

def test_mesh_world_positions_matches_mesh_to_bulk_arrays_positions():
    """Same matrix -> mesh_world_positions must reproduce EXACTLY the
    `positions` array mesh_to_bulk_arrays computes (both derive world-space
    triangle corners the same way; pkg88-B reuses this for the shutter-close
    sample instead of re-deriving material/UV/normal data)."""
    mesh, *_ = _make_mesh()
    M, NM = _transform()
    positions, *_rest = _bulk_geometry.mesh_to_bulk_arrays(
        mesh, M, NM, {0: 10, 1: 20}, 10, [])
    world_positions = _bulk_geometry.mesh_world_positions(mesh, M)
    np.testing.assert_allclose(world_positions, positions, rtol=0, atol=1e-6)


def test_mesh_world_positions_reflects_different_matrix():
    """A translated matrix must shift every corner by exactly the
    translation delta -- the shutter-close sample pkg88-B feeds as
    add_triangles_bulk_motion's positions_end."""
    mesh, *_ = _make_mesh()
    M, _NM = _transform()
    M_end = M.copy()
    M_end[:3, 3] += np.array([1.2, 0.0, 0.0], dtype=np.float32)

    start = _bulk_geometry.mesh_world_positions(mesh, M)
    end = _bulk_geometry.mesh_world_positions(mesh, M_end)

    assert start.shape == end.shape == (2, 3, 3)
    np.testing.assert_allclose(end - start,
                               np.full((2, 3, 3), [1.2, 0.0, 0.0], dtype=np.float32),
                               rtol=0, atol=1e-5)
