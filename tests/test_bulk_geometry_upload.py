"""pkg112 — `add_triangles_bulk` parity with the per-triangle `add_triangle` path.

The bulk binding (`module/blender_module.cpp::addTrianglesBulk`) ingests an entire
mesh's triangles from contiguous NumPy arrays in one pybind call, looping in C++ to
cut the per-triangle Python/pybind round-trip. It MUST be pixel-identical to the
per-triangle path. This CPU test builds the same small multi-material, smooth-shaded
mesh both ways and asserts the renders are bit-identical (same geometry → same BVH →
same deterministic render at a fixed seed).
"""
import numpy as np
import pytest

import runtime_setup  # noqa: F401 — configures sys.path + DLL dirs
runtime_setup.configure_test_imports()
import astroray


W, H, SAMPLES, MAX_DEPTH, SEED = 48, 48, 16, 4, 7


def _quad_tris(z, mat_id):
    """Two triangles forming a quad at depth z, with UVs + per-vertex normals.
    Returns list of (v0,v1,v2, mat_id, uv0,uv1,uv2, n0,n1,n2, mat_pass)."""
    p = [(-0.6, -0.6, z), (0.6, -0.6, z), (0.6, 0.6, z), (-0.6, 0.6, z)]
    uv = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    # Slightly tilted per-vertex normals so smooth shading actually depends on them.
    nrm = [(-0.2, -0.2, 1.0), (0.2, -0.2, 1.0), (0.2, 0.2, 1.0), (-0.2, 0.2, 1.0)]
    nrm = [tuple(np.array(n) / np.linalg.norm(n)) for n in nrm]
    tris = []
    for a, b, c in [(0, 1, 2), (0, 2, 3)]:
        tris.append((p[a], p[b], p[c], mat_id,
                     uv[a], uv[b], uv[c], nrm[a], nrm[b], nrm[c], mat_id))
    return tris


def _scene_skeleton():
    r = astroray.Renderer()
    r.set_background_color([0.05, 0.05, 0.08])
    m0 = r.create_material("lambertian", [0.85, 0.3, 0.3], {})
    m1 = r.create_material("lambertian", [0.3, 0.4, 0.9], {})
    r.add_sun_light_dedicated([0.3, -0.5, -1.0], 0.02,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 4.0)
    r.setup_camera([0.0, 0.0, 3.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   45.0, W / H, 0.0, 3.0, W, H)
    return r, [m0, m1]


def _all_tris():
    r0, mats = _scene_skeleton()
    tris = _quad_tris(-0.3, mats[0]) + _quad_tris(0.3, mats[1])
    return tris


def _render(r):
    r.set_seed(SEED)
    img = np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float32)
    if img.ndim == 1:
        img = img.reshape(H, W, 3)
    return img


def _build_per_tri():
    r, _ = _scene_skeleton()
    for (v0, v1, v2, mid, uv0, uv1, uv2, n0, n1, n2, mpass) in _all_tris():
        r.add_triangle(list(v0), list(v1), list(v2), mid,
                       list(uv0), list(uv1), list(uv2),
                       list(n0), list(n1), list(n2), 0, mpass)
    return r


def _build_bulk():
    r, _ = _scene_skeleton()
    tris = _all_tris()
    nt = len(tris)
    positions = np.array([[t[0], t[1], t[2]] for t in tris], dtype=np.float32)      # (Nt,3,3)
    material_ids = np.array([t[3] for t in tris], dtype=np.int32)                    # (Nt,)
    mat_pass = np.array([t[10] for t in tris], dtype=np.int32)                       # (Nt,)
    uvs = np.array([[[t[4], t[5], t[6]] for t in tris]], dtype=np.float32)           # (1,Nt,3,2)
    normals = np.array([[t[7], t[8], t[9]] for t in tris], dtype=np.float32)         # (Nt,3,3)
    assert positions.shape == (nt, 3, 3) and uvs.shape == (1, nt, 3, 2)
    r.add_triangles_bulk(positions, material_ids, mat_pass, 0, uvs, ["UVMap"], normals)
    return r


def test_bulk_matches_per_triangle_scene_count():
    rp, rb = _build_per_tri(), _build_bulk()
    assert rp.scene_object_count() == rb.scene_object_count()


def test_bulk_render_pixel_identical_to_per_triangle():
    img_p = _render(_build_per_tri())
    img_b = _render(_build_bulk())
    assert img_p.shape == img_b.shape
    # Identical geometry built in identical order → bit-identical deterministic render.
    assert np.array_equal(img_p, img_b), (
        f"bulk vs per-tri render differs: max abs diff "
        f"{float(np.max(np.abs(img_p - img_b))):.6g}, "
        f"mean {float(np.mean(np.abs(img_p - img_b))):.6g}"
    )


def test_bulk_no_uv_no_normals_ok():
    """nLayers==0 + empty normals path (face-normal fallback) must not crash."""
    r, mats = _scene_skeleton()
    tris = _quad_tris(0.0, mats[0])
    nt = len(tris)
    positions = np.array([[t[0], t[1], t[2]] for t in tris], dtype=np.float32)
    material_ids = np.array([t[3] for t in tris], dtype=np.int32)
    mat_pass = np.array([t[10] for t in tris], dtype=np.int32)
    empty_uv = np.zeros((0,), dtype=np.float32)
    empty_n = np.zeros((0,), dtype=np.float32)
    r.add_triangles_bulk(positions, material_ids, mat_pass, 0, empty_uv, [], empty_n)
    assert r.scene_object_count() == nt
    img = _render(r)
    assert np.isfinite(img).all()
