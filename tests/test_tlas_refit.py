"""pkg114 increment 3d — TLAS-only refit (transform-only re-upload) gate.

A transform-only edit of an instanced object must NOT rebuild/re-upload geometry:
update_instance_transform() changes the CPU transform, upload_instance_transforms()
re-pushes ONLY d_instances + d_tlas, and render(skip_upload=True) renders from the
existing device state.

Two gates:
  * CORRECTNESS (refit-isolated): upload geometry once with the instance at A,
    refit it to B, then render(skip_upload=True) — which does NOT re-upload — and
    require it to match an oracle built from scratch with the instance at B. Since
    the skip-upload render uses only the device TLAS the refit wrote, a match
    proves the refit produced correct device state (a no-op refit would show A).
  * BUDGET (pkg56 ≤50% baseline): on a heavy instanced scene, the refit upload
    (upload_instance_transforms) must cost < 50% of a full geometry upload
    (upload_geometry) — in practice it is a tiny fraction.

Skipped when the astroray module lacks CUDA or no GPU is present.
"""
from __future__ import annotations

import time
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

_W = _H = 80
_SPP = 24
_DEPTH = 4

_TET = np.array([[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]], dtype=np.float64) * 0.6
_FACES = [(0, 1, 2), (0, 2, 3), (0, 3, 1), (1, 3, 2)]
_FLOOR = [([-6, -1.2, -6], [6, -1.2, -6], [6, -1.2, 6]),
          ([-6, -1.2, -6], [6, -1.2, 6], [-6, -1.2, 6])]


def _tet_local():
    return [list(np.concatenate([_TET[a], _TET[b], _TET[c]]).astype(np.float32))
            for (a, b, c) in _FACES]


def _translate(x, y, z):
    M = np.eye(4); M[0, 3], M[1, 3], M[2, 3] = x, y, z; return M


def _common(r):
    r.set_background_color([0.55, 0.65, 0.85])
    r.set_integrator("path_tracer")
    r.set_use_gpu(True)
    r.setup_camera([0, 1.6, 8.5], [0, 0, 0], [0, 1, 0], 42.0, 1.0, 0.0, 8.5, _W, _H)
    r.set_seed(7)


def _render(r, skip_upload=False):
    return np.asarray(r.render(_SPP, _DEPTH, None, False, -1, -1, -1, -1, -1, skip_upload),
                      dtype=np.float32).reshape(_H, _W, 3)


def _scene(instance_xform):
    r = astroray.Renderer()
    floor_mat = r.create_material("lambertian", [0.30, 0.55, 0.30], {})
    tet_mat = r.create_material("lambertian", [0.82, 0.30, 0.30], {})
    for (a, b, c) in _FLOOR:
        r.add_triangle(list(map(float, a)), list(map(float, b)), list(map(float, c)), floor_mat)
    mesh = r.register_mesh_triangles(_tet_local(), tet_mat)
    inst = r.add_instance(mesh, list(instance_xform.flatten().astype(np.float32)))
    _common(r)
    return r, inst


@pytest.mark.skipif(AVAILABLE and not astroray.__features__.get("cuda", False),
                    reason="CUDA feature not in this build")
def test_tlas_refit_matches_full_rebuild():
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")

    A = _translate(-2.4, 0.6, 0.0)
    B = _translate(2.4, 0.6, 0.0)

    # Upload geometry with the instance at A, then refit it to B and render WITHOUT
    # re-uploading (skip_upload=True renders from the device TLAS the refit wrote).
    r, inst = _scene(A)
    _render(r)                                   # full upload @ A (also primes device)
    r.update_instance_transform(inst, list(B.flatten().astype(np.float32)))
    r.upload_instance_transforms()               # TLAS-only re-push
    refit = _render(r, skip_upload=True)         # render from device state @ B

    # Oracle: a from-scratch scene with the instance already at B.
    r_oracle, _ = _scene(B)
    oracle = _render(r_oracle)

    assert refit.mean() > 0.05, f"refit render empty (mean={refit.mean():.4f})"
    mad = float(np.abs(refit - oracle).mean())
    assert mad < 0.02, (
        f"TLAS refit != full rebuild at B (mean abs diff {mad:.4f}); a no-op refit "
        f"would leave the instance at A")

    # Negative control: WITHOUT a refit, a skip_upload render keeps the device at A,
    # so it must DIFFER from the oracle at B (proves skip_upload uses device state).
    r2, _ = _scene(A)
    _render(r2)
    stale = _render(r2, skip_upload=True)
    assert float(np.abs(stale - oracle).mean()) > 0.03, (
        "skip_upload render did not reflect device state (A vs B indistinguishable)")


@pytest.mark.skipif(AVAILABLE and not astroray.__features__.get("cuda", False),
                    reason="CUDA feature not in this build")
def test_tlas_refit_cost_under_half_full_upload():
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA GPU not available")

    # Heavy registered mesh (a subdivided grid) instanced many times, so a full
    # geometry upload re-walks + re-pushes thousands of triangles while the refit
    # touches only the instance/TLAS arrays.
    N = 40
    verts = []
    for i in range(N):
        for j in range(N):
            x0, x1 = -1 + 2.0 * i / N, -1 + 2.0 * (i + 1) / N
            z0, z1 = -1 + 2.0 * j / N, -1 + 2.0 * (j + 1) / N
            verts.append([x0, 0, z0, x1, 0, z0, x1, 0, z1])
            verts.append([x0, 0, z0, x1, 0, z1, x0, 0, z1])
    tris = [list(np.asarray(v, dtype=np.float32)) for v in verts]

    r = astroray.Renderer()
    mat = r.create_material("lambertian", [0.7, 0.7, 0.7], {})
    mesh = r.register_mesh_triangles(tris, mat)
    insts = [r.add_instance(mesh, list((_translate(k * 2.5, 0, 0)).flatten().astype(np.float32)))
             for k in range(16)]
    _common(r)
    r.upload_geometry()   # prime device

    def _median(fn, n=7):
        ts = []
        for _ in range(n):
            t0 = time.perf_counter(); fn(); ts.append(time.perf_counter() - t0)
        return sorted(ts)[len(ts) // 2]

    def _full():
        r.upload_geometry()

    def _refit():
        for k, iid in enumerate(insts):
            r.update_instance_transform(iid, list(_translate(k * 2.5 + 0.01, 0, 0).flatten().astype(np.float32)))
        r.upload_instance_transforms()

    _full(); _refit()                    # warm up
    full_ms = _median(_full) * 1e3
    refit_ms = _median(_refit) * 1e3
    n_tris = len(tris)
    print(f"\npkg114 inc3d refit: {n_tris} tris x16 inst — full_upload={full_ms:.2f}ms "
          f"refit={refit_ms:.2f}ms ({100*refit_ms/full_ms:.1f}% of full)")
    assert refit_ms < 0.5 * full_ms, (
        f"TLAS refit {refit_ms:.2f}ms is not < 50% of full upload {full_ms:.2f}ms")
