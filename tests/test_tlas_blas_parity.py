"""pkg114 increment 1 — two-level BVH (TLAS-over-BLAS) identity-passthrough gate.

Validates that the new device two-level traversal `gpu_tlas_hit`, fed a single
IDENTITY instance (one BLAS = the whole uploaded scene, M = Minv = I, a 1-leaf
TLAS), reduces EXACTLY to the single-level `gpu_bvh_hit` over every primary
camera ray of the Cornell scene.

The comparison runs device-side (see src/gpu/tlas_parity.cu): for each ray the
probe generates ONE camera ray and dual-traces it through both entry points,
then returns aggregate stats. For an identity instance:

  * t / primId / materialId / frontFace / point must match bit-for-bit, and
  * the surface normal may differ by at most a sub-ulp (the no-op
    inverse-transpose + renormalize on the way back to world space).

This is the regression guard for the two-level plumbing — struct upload, the
leaf/instance indirection, the BLAS root-pointer offset, the primId remap, the
GRay field-assign (un-normalized local direction), and the back-transform —
BEFORE any production kernel is routed through it (increment 2).

Skipped when the astroray module lacks CUDA or no GPU is present.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

import runtime_setup  # noqa: E402

runtime_setup.configure_test_imports()

import astroray  # noqa: E402

_RES = 64  # 64x64 = 4096 primary rays


def _build_cornell(res: int):
    from importlib import import_module

    mod = import_module("benchmarks.showcase.scenes.convergence_grid")
    r = astroray.Renderer()
    mod.build_cornell(r, res, res)
    return r


@pytest.mark.skipif(
    not getattr(astroray, "__features__", {}).get("cuda", False),
    reason="astroray built without CUDA",
)
def test_tlas_identity_passthrough_matches_single_level():
    r = _build_cornell(_RES)
    if not getattr(r, "gpu_available", False):
        pytest.skip("CUDA GPU not available")

    stats = astroray._gpu_tlas_identity_parity(r, _RES, _RES)

    assert stats["total_rays"] == _RES * _RES, stats
    # Hit/miss agreement and the exact integer/float fields must be bit-identical.
    assert stats["hit_disagree"] == 0, (
        f"{stats['hit_disagree']} rays where TLAS and single-level disagreed on "
        f"hit/miss: {stats}")
    assert stats["field_mismatch"] == 0, (
        f"{stats['field_mismatch']} rays where t/primId/materialId/frontFace "
        f"differed under the identity instance: {stats}")
    assert stats["max_t_delta"] == 0.0, stats
    assert stats["max_point_delta"] == 0.0, stats
    # The only permitted drift: a sub-ulp normal change from the (no-op) inverse-
    # transpose renormalize on an already-unit normal.
    assert stats["max_normal_delta"] < 1e-5, (
        f"identity instance perturbed the surface normal by "
        f"{stats['max_normal_delta']:.3e} (> 1e-5): {stats}")
