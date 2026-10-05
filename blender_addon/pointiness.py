"""pkg322 -- Geometry > Pointiness as a per-vertex value, host side.

Port of Cycles `attr_create_pointiness` (intern/cycles/blender/mesh.cpp, Apache-2.0,
Blender 5.x): weld colocated vertices, accumulate the welded vertex normals, take the
angle between that normal and the mean unit edge direction of the one-ring, then one
blur pass over the edge neighbours. The result rides the #990 per-corner attribute
layer ('geom:Pointiness', see _bulk_geometry.mesh_attribute_layers); no device code.

Pure numpy (no bpy) so it is unit-testable with plain arrays.
"""
import numpy as np

_FLT_EPS = np.float32(np.finfo(np.float32).eps)  # FLT_EPSILON


def _weld_index(positions):
    """vert_orig_index of Cycles STEP 1: every vertex -> the first colocated vertex in
    (coordinate-sum, descending-index) order. Colocated = squared distance < FLT_EPSILON
    within a 3 * FLT_EPSILON window of the coordinate sum, scanning in sorted order."""
    n = len(positions)
    pos = positions.astype(np.float32)
    s = (pos[:, 0] + pos[:, 1]) + pos[:, 2]  # float32, as VertexAverageComparator
    order = np.lexsort((-np.arange(n), s))   # sum ascending, equal sums: higher index first
    ss, sp = s[order], pos[order]
    orig = np.arange(n)
    active = np.arange(n)                    # sorted positions still scanning
    k = 1
    while len(active):
        active = active[active + k < n]
        if not len(active):
            break
        q = active + k
        # sorted ascending: once the sum gap exceeds the window it stays exceeded
        active = active[(ss[q] - ss[active]) <= np.float32(3.0) * _FLT_EPS]
        q = active + k
        d = sp[q] - sp[active]
        hit = ((d * d).sum(axis=1, dtype=np.float32)) < _FLT_EPS
        orig[order[active[hit]]] = order[q[hit]]
        active = active[~hit]
        k += 1
    # point every vertex at the very first original vertex (chain following)
    while True:
        nxt = orig[orig]
        if np.array_equal(nxt, orig):
            return orig
        orig = nxt


def compute_pointiness(positions, vertex_normals, edges):
    """Per-vertex Pointiness, (n,) float32, as Cycles' ATTR_STD_POINTINESS.
    positions (n,3), vertex_normals (n,3) (Blender Mesh.vertex_normals), edges (m,2)."""
    positions = np.asarray(positions, np.float32).reshape(-1, 3)
    n = len(positions)
    if n == 0:
        return np.zeros((0,), np.float32)
    normals = np.asarray(vertex_normals, np.float64).reshape(-1, 3)
    edges = np.asarray(edges, np.int64).reshape(-1, 2)
    orig = _weld_index(positions)

    # STEP 2: welded vertex normals
    acc = np.zeros((n, 3))
    np.add.at(acc, orig, normals)
    ln = np.linalg.norm(acc, axis=1, keepdims=True)
    vnorm = np.where(ln > 0.0, acc / np.where(ln > 0.0, ln, 1.0), 0.0)

    # STEP 3: unique (welded) edges; each end accumulates the unit direction to the other
    v0, v1 = orig[edges[:, 0]], orig[edges[:, 1]]
    lo, hi = np.minimum(v0, v1), np.maximum(v0, v1)
    _, first = np.unique(lo * n + hi, return_index=True)
    v0, v1 = v0[first], v1[first]
    co = positions.astype(np.float64)
    e = co[v1] - co[v0]
    el = np.linalg.norm(e, axis=1, keepdims=True)
    e = np.where(el > 0.0, e / np.where(el > 0.0, el, 1.0), 0.0)  # safe_normalize
    edge_accum = np.zeros((n, 3))
    np.add.at(edge_accum, v0, e)
    np.add.at(edge_accum, v1, -e)
    counter = np.zeros(n, np.int64)
    np.add.at(counter, v0, 1)
    np.add.at(counter, v1, 1)

    raw = np.zeros(n)
    use = (orig == np.arange(n)) & (counter > 0)
    d = (vnorm[use] * edge_accum[use] / counter[use, None]).sum(axis=1)
    raw[use] = np.arccos(np.clip(d, -1.0, 1.0)) / np.pi  # safe_acosf * M_1_PI_F

    # blur: approximate the two-ring neighbourhood (same edge set, same counter)
    data = raw.copy()
    np.add.at(data, v0, raw[v1])
    np.add.at(data, v1, raw[v0])
    data /= counter + 1
    return data[orig].astype(np.float32)


def mesh_pointiness(mesh):
    """compute_pointiness over a Blender Mesh (object space, as Cycles syncs it)."""
    nv, ne = len(mesh.vertices), len(mesh.edges)
    co = np.empty(nv * 3, np.float32)
    mesh.vertices.foreach_get("co", co)
    vn = np.empty(nv * 3, np.float32)
    mesh.vertex_normals.foreach_get("vector", vn)
    ed = np.empty(ne * 2, np.int32)
    mesh.edges.foreach_get("vertices", ed)
    return compute_pointiness(co.reshape(nv, 3), vn.reshape(nv, 3), ed.reshape(ne, 2))
