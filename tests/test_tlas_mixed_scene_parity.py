"""pkg114 increment 3b — MIXED instanced + non-instanced GPU pixel-parity gate.

The previous two-level upload was all-or-nothing: the moment a scene contained
ANY instance, every NON-instanced ("flat") object was dropped from the GPU
upload. Real Blender scenes always mix a static floor / unique props with
instanced duplis, so this is the blocker for using the addon instancing path.

inc 3b folds the flat scene into the TLAS as ONE identity-transform instance
(its BVH wrapped as a BLAS), so the existing gpu_tlas_hit traverses flat +
instanced geometry uniformly. This test renders:

  flat floor (add_triangle → single-level scene)  +  3 instanced tetrahedra
                              vs
  the SAME floor + tetrahedra ALL baked into world-space add_triangle calls.

If the flat floor were still dropped (old behaviour) the two images would differ
massively in the lower half of the frame. Same camera/seed/spp + flat
background ⇒ they agree to float transform-order noise.

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

_TET = np.array([
    [1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1],
], dtype=np.float64) * 0.55
_FACES = [(0, 1, 2), (0, 2, 3), (0, 3, 1), (1, 3, 2)]


def _tet_local_triangles():
    return [list(np.concatenate([_TET[a], _TET[b], _TET[c]]).astype(np.float32))
            for (a, b, c) in _FACES]


def _translate(x, y, z):
    M = np.eye(4); M[0, 3], M[1, 3], M[2, 3] = x, y, z; return M


def _scale(sx, sy, sz):
    M = np.eye(4); M[0, 0], M[1, 1], M[2, 2] = sx, sy, sz; return M


def _rot_y(deg):
    a = np.radians(deg); c, s = np.cos(a), np.sin(a)
    M = np.eye(4); M[0, 0], M[0, 2], M[2, 0], M[2, 2] = c, s, -s, c; return M


_TRANSFORMS = [
    _translate(-2.4, 0.4, 0) @ _rot_y(35),
    _translate(0.0, 0.4, 0) @ _scale(1.5, 0.7, 1.0),
    _translate(2.4, 0.4, 0) @ _scale(-1.0, 1.0, 1.0),   # mirror
]

# A large flat floor at y = -1.2 (two triangles), in the NON-instanced scene.
_FLOOR = [
    ([-6, -1.2, -6], [6, -1.2, -6], [6, -1.2, 6]),
    ([-6, -1.2, -6], [6, -1.2, 6], [-6, -1.2, 6]),
]


def _common(r):
    r.set_background_color([0.55, 0.65, 0.85])
    r.set_integrator("path_tracer")
    r.set_use_gpu(True)
    r.setup_camera([0, 2.2, 9.0], [0, -0.2, 0], [0, 1, 0], 42.0, 1.0, 0.0, 9.0, _W, _H)
    r.set_seed(7)


def _render(r):
    return np.asarray(r.render(_SPP, _DEPTH, None, False),
                      dtype=np.float32).reshape(_H, _W, 3)


def _add_floor(r, mat):
    for (a, b, c) in _FLOOR:
        r.add_triangle(list(map(float, a)), list(map(float, b)), list(map(float, c)), mat)


def _mixed_image():
    r = astroray.Renderer()
    floor_mat = r.create_material("lambertian", [0.30, 0.55, 0.30], {})
    tet_mat = r.create_material("lambertian", [0.82, 0.30, 0.30], {})
    _add_floor(r, floor_mat)                       # → non-instanced flat scene
    mesh = r.register_mesh_triangles(_tet_local_triangles(), tet_mat)  # → BLAS
    for M in _TRANSFORMS:
        r.add_instance(mesh, list(M.flatten().astype(np.float32)))
    _common(r)
    return _render(r)


def _baked_image():
    r = astroray.Renderer()
    floor_mat = r.create_material("lambertian", [0.30, 0.55, 0.30], {})
    tet_mat = r.create_material("lambertian", [0.82, 0.30, 0.30], {})
    _add_floor(r, floor_mat)
    for M in _TRANSFORMS:
        R = M[:3, :3]; t = M[:3, 3]
        for (a, b, c) in _FACES:
            w = [(R @ _TET[i] + t).astype(np.float32).tolist() for i in (a, b, c)]
            r.add_triangle(w[0], w[1], w[2], tet_mat)
    _common(r)
    return _render(r)


@pytest.mark.skipif(
    AVAILABLE and not astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build")
def test_mixed_instanced_and_flat_matches_fully_baked():
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")

    mixed = _mixed_image()
    baked = _baked_image()

    assert mixed.mean() > 0.05, f"mixed render looks empty (mean={mixed.mean():.4f})"

    # The floor fills the lower rows of the frame. If the flat scene had been
    # dropped (the bug this gate guards), the lower band would show only the
    # blue background (high B, low R/G) instead of the green floor. Assert the
    # floor band carries the floor's green energy in BOTH images.
    band = slice(int(_H * 0.72), _H)
    for img, tag in ((mixed, "mixed"), (baked, "baked")):
        g = img[band, :, 1].mean(); b = img[band, :, 2].mean()
        assert g > 0.10 and g > 0.6 * b, (
            f"{tag} floor band missing green floor (G={g:.3f} B={b:.3f})")

    # Whole-frame parity: same geometry, same seed ⇒ float transform-order noise.
    for ch, name in enumerate("RGB"):
        rm, rb = mixed[..., ch].mean(), baked[..., ch].mean()
        ratio = rm / max(rb, 1e-6)
        assert 0.97 <= ratio <= 1.03, (
            f"{name} channel energy off: mixed={rm:.4f} baked={rb:.4f} ratio={ratio:.4f}")

    mad = float(np.abs(mixed - baked).mean())
    assert mad < 0.02, f"mean abs per-pixel diff {mad:.4f} too large (flat scene dropped?)"
