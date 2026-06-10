"""pkg114 increment 2 — multi-instance two-level BVH GPU pixel-parity gate.

Renders N instances of one registered mesh through the two-level (TLAS-over-BLAS)
device path and compares against the SAME instances baked into world-space
triangles and rendered through the single-level path. Both use the same camera,
seed, spp and a flat background (NO area lights — instanced emitters are a
deferred follow-up), so with identical geometry the two images must match to
within float (transform-order) noise, NOT Monte-Carlo noise.

The instance set deliberately exercises the hard transform cases:
  * a rigid rotate+translate,
  * a NON-UNIFORM scale (validates the inverse-transpose normal transform), and
  * a MIRROR / negative-determinant scale (validates that frontFace is recomputed
    in world space — a diffuse surface's oriented shading normal must still match
    the baked reference even though the geometric winding flips).

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

# Regular tetrahedron (object-local). Flat-shaded; winding is irrelevant for a
# double-sided diffuse surface (the oriented normal is recomputed per ray).
_TET = np.array([
    [1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1],
], dtype=np.float64) * 0.6
_FACES = [(0, 1, 2), (0, 2, 3), (0, 3, 1), (1, 3, 2)]


def _tet_local_triangles():
    return [list(np.concatenate([_TET[a], _TET[b], _TET[c]]).astype(np.float32))
            for (a, b, c) in _FACES]


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


# Three instance transforms (object->world), row-major 4x4.
_TRANSFORMS = [
    _translate(-2.6, 0, 0) @ _rot_y(35),          # rigid rotate + translate
    _translate(0.0, 0, 0) @ _scale(1.6, 0.6, 1.0),  # non-uniform scale
    _translate(2.6, 0, 0) @ _scale(-1.0, 1.0, 1.0),  # mirror (det < 0)
]


def _common(r):
    r.set_background_color([0.55, 0.65, 0.85])
    r.set_integrator("path_tracer")
    r.set_use_gpu(True)
    r.setup_camera([0, 1.6, 8.5], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 8.5, _W, _H)
    r.set_seed(7)


def _render(r):
    return np.asarray(r.render(_SPP, _DEPTH, None, False),
                      dtype=np.float32).reshape(_H, _W, 3)


def _instanced_image():
    r = astroray.Renderer()
    mat = r.create_material("lambertian", [0.82, 0.30, 0.30], {})
    mesh = r.register_mesh_triangles(_tet_local_triangles(), mat)
    for M in _TRANSFORMS:
        r.add_instance(mesh, list(M.flatten().astype(np.float32)))
    _common(r)
    return _render(r)


def _baked_image():
    r = astroray.Renderer()
    mat = r.create_material("lambertian", [0.82, 0.30, 0.30], {})
    for M in _TRANSFORMS:
        R = M[:3, :3]
        t = M[:3, 3]
        for (a, b, c) in _FACES:
            w = [(R @ _TET[i] + t).astype(np.float32).tolist() for i in (a, b, c)]
            r.add_triangle(w[0], w[1], w[2], mat)
    _common(r)
    return _render(r)


@pytest.mark.skipif(
    AVAILABLE and not astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build")
def test_instanced_render_matches_baked_world_space():
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")

    inst = _instanced_image()
    baked = _baked_image()

    assert inst.mean() > 0.05, f"instanced render looks empty (mean={inst.mean():.4f})"
    assert baked.mean() > 0.05, f"baked render looks empty (mean={baked.mean():.4f})"

    # Per-channel mean ratio: instanced geometry must carry the same energy as
    # the baked world-space geometry (right poses, right shading).
    for ch, name in enumerate("RGB"):
        ri, rb = inst[..., ch].mean(), baked[..., ch].mean()
        ratio = ri / max(rb, 1e-6)
        assert 0.97 <= ratio <= 1.03, (
            f"{name} channel energy off: instanced={ri:.4f} baked={rb:.4f} "
            f"ratio={ratio:.4f}")

    # Same seed + same geometry + non-adaptive ⇒ the two images differ only by
    # float transform-order noise, far below the MC noise floor.
    mad = float(np.abs(inst - baked).mean())
    assert mad < 0.02, f"mean abs per-pixel diff {mad:.4f} too large (TLAS≠baked)"
