"""pkg114 increment 3a — register_mesh_bulk GPU pixel-parity gate.

register_mesh_bulk() is the bulk twin of register_mesh_triangles: it ingests a
mesh's OBJECT-LOCAL geometry *with* UV layers, per-vertex (smooth) normals and
per-triangle multi-material into one shared BLAS. This test exercises exactly the
features the flat-shaded register_mesh_triangles path cannot:

  * SMOOTH per-vertex normals (the inverse-transpose normal transform must be
    applied per instance, so shading depends on the registered normals), and
  * MULTI-MATERIAL (per-triangle material ids), and
  * a UV layer present during ingest (must not corrupt the geometry).

The instanced-via-bulk render is compared against the SAME instances baked into
world-space triangles via add_triangle (carrying the inverse-transpose-transformed
corner normals and per-face material). Same camera/seed/spp + flat background
(no area lights) ⇒ the two images agree to float transform-order noise.

Skipped when the astroray module lacks CUDA or no GPU is present.
"""
from __future__ import annotations

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

_W = _H = 96
_SPP = 24
_DEPTH = 4

# Unit octahedron — vertices are already unit length, so each one doubles as its
# own smooth vertex normal. Object-local geometry is scaled by 0.7.
_V = np.array([
    [1, 0, 0], [-1, 0, 0],
    [0, 1, 0], [0, -1, 0],
    [0, 0, 1], [0, 0, -1],
], dtype=np.float64)
_SCALE = 0.7
_FACES = [
    (0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),   # top (+z) fan
    (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5),   # bottom (-z) fan
]
# Per-corner UVs (constant per face — UVs don't affect a plain lambertian, this
# just proves the layer survives ingest without corrupting positions/normals).
_UV3 = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32)


def _translate(x, y, z):
    M = np.eye(4)
    M[0, 3], M[1, 3], M[2, 3] = x, y, z
    return M


def _scale(sx, sy, sz):
    M = np.eye(4)
    M[0, 0], M[1, 1], M[2, 2] = sx, sy, sz
    return M


def _rot_y(deg):
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    M = np.eye(4)
    M[0, 0], M[0, 2], M[2, 0], M[2, 2] = c, s, -s, c
    return M


# Rigid rotate+translate, and a NON-UNIFORM scale (validates the inverse-
# transpose normal transform on the registered smooth normals).
_TRANSFORMS = [
    _translate(-1.7, 0, 0) @ _rot_y(35),
    _translate(1.7, 0, 0) @ _scale(1.5, 0.6, 1.0),
]


def _bulk_arrays():
    """OBJECT-local (positions, material_ids, mat_pass, uvs, normals) for the octahedron."""
    nt = len(_FACES)
    positions = np.empty((nt, 3, 3), dtype=np.float32)
    normals = np.empty((nt, 3, 3), dtype=np.float32)
    for t, (a, b, c) in enumerate(_FACES):
        for k, vi in enumerate((a, b, c)):
            positions[t, k] = (_V[vi] * _SCALE).astype(np.float32)
            normals[t, k] = _V[vi].astype(np.float32)   # already unit
    uvs = np.broadcast_to(_UV3, (1, nt, 3, 2)).astype(np.float32).copy()
    return positions, normals, uvs


def _common(r):
    r.set_background_color([0.55, 0.65, 0.85])
    r.set_integrator("path_tracer")
    r.set_use_gpu(True)
    r.setup_camera([0, 1.4, 6.5], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 6.5, _W, _H)
    r.set_seed(7)


def _render(r):
    return np.asarray(r.render(_SPP, _DEPTH, None, False),
                      dtype=np.float32).reshape(_H, _W, 3)


def _mats(r):
    a = r.create_material("lambertian", [0.85, 0.30, 0.25], {})
    b = r.create_material("lambertian", [0.25, 0.45, 0.85], {})
    return a, b


def _instanced_image():
    r = astroray.Renderer()
    matA, matB = _mats(r)
    positions, normals, uvs = _bulk_arrays()
    material_ids = np.array([matA if t % 2 == 0 else matB
                             for t in range(len(_FACES))], dtype=np.int32)
    mat_pass = np.array([t % 2 for t in range(len(_FACES))], dtype=np.int32)
    mesh = r.register_mesh_bulk(positions, material_ids, mat_pass, 0,
                                uvs, ["UVMap"], normals)
    for M in _TRANSFORMS:
        r.add_instance(mesh, list(M.flatten().astype(np.float32)))
    _common(r)
    return _render(r)


def _baked_image():
    r = astroray.Renderer()
    matA, matB = _mats(r)
    positions, normals, _uvs = _bulk_arrays()
    for M in _TRANSFORMS:
        R = M[:3, :3]
        t = M[:3, 3]
        Ninv = np.linalg.inv(R).T
        for tri, (a, b, c) in enumerate(_FACES):
            mat_id = matA if tri % 2 == 0 else matB
            w = [(R @ positions[tri, k] + t).astype(np.float32).tolist()
                 for k in range(3)]
            nw = []
            for k in range(3):
                n = Ninv @ normals[tri, k]
                n = n / max(np.linalg.norm(n), 1e-9)
                nw.append(n.astype(np.float32).tolist())
            r.add_triangle(w[0], w[1], w[2], mat_id, [], [], [],
                           nw[0], nw[1], nw[2], 0, int(tri % 2))
    _common(r)
    return _render(r)


@pytest.mark.skipif(
    AVAILABLE and not astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build")
def test_bulk_registered_instances_match_baked():
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")

    inst = _instanced_image()
    baked = _baked_image()

    assert inst.mean() > 0.05, f"instanced render looks empty (mean={inst.mean():.4f})"
    assert baked.mean() > 0.05, f"baked render looks empty (mean={baked.mean():.4f})"

    for ch, name in enumerate("RGB"):
        ri, rb = inst[..., ch].mean(), baked[..., ch].mean()
        ratio = ri / max(rb, 1e-6)
        assert 0.97 <= ratio <= 1.03, (
            f"{name} channel energy off: instanced={ri:.4f} baked={rb:.4f} "
            f"ratio={ratio:.4f}")

    mad = float(np.abs(inst - baked).mean())
    assert mad < 0.02, f"mean abs per-pixel diff {mad:.4f} too large (bulk-BLAS≠baked)"
