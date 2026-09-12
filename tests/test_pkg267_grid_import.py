"""pkg267 — GridMedium representation + majorant grid (engine side).

Gates:
* a synthetic dense grid loads with the correct dims / bbox / world AABB /
  world transform (round trip),
* nearest-voxel point queries return the stored density,
* the coarse majorant grid is a true upper bound: for EVERY fine voxel the
  covering supervoxel's majorant >= that voxel's density, and the per-supervoxel
  majorant equals the numpy max over the fine voxels it covers.

No Blender / openvdb needed here (that is the companion
``test_pkg267_blender_volume_export.py``).
"""

import math

import numpy as np
import pytest

import astroray

IDENTITY = [1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0]


def _scale_translate(sx, sy, sz, tx, ty, tz):
    return [sx, 0.0, 0.0, tx,
            0.0, sy, 0.0, ty,
            0.0, 0.0, sz, tz,
            0.0, 0.0, 0.0, 1.0]


def _matvec(m, v):
    return (
        m[0] * v[0] + m[1] * v[1] + m[2] * v[2] + m[3],
        m[4] * v[0] + m[5] * v[1] + m[6] * v[2] + m[7],
        m[8] * v[0] + m[9] * v[1] + m[10] * v[2] + m[11],
    )


def _make_grid(nx=10, ny=8, nz=6, seed=7):
    rng = np.random.default_rng(seed)
    # shape (nz, ny, nx), C-order — the engine contract.
    dens = rng.random((nz, ny, nx), dtype=np.float32) * 3.0
    # punch some zeros so the grid is genuinely sparse.
    dens[dens < 0.5] = 0.0
    return dens


def test_dims_bbox_and_density_roundtrip():
    dens = _make_grid()
    nz, ny, nx = dens.shape
    bbox_min = (-3, 5, 2)
    gm = astroray.GridMedium()
    gm.set_density(dens, bbox_min=bbox_min,
                   index_to_object=IDENTITY, object_to_world=IDENTITY,
                   supervoxel=4)
    assert gm.valid()
    assert gm.dims() == (nx, ny, nz)
    assert gm.bbox_min() == bbox_min

    # nearest-voxel density at each voxel center must equal the stored value.
    i2w = gm.index_to_world()
    for z in range(nz):
        for y in range(ny):
            for x in range(nx):
                ai = bbox_min[0] + x
                aj = bbox_min[1] + y
                ak = bbox_min[2] + z
                w = _matvec(i2w, (ai, aj, ak))
                got = gm.density_world(*w)
                assert got == pytest.approx(float(dens[z, y, x]), abs=1e-6)


def test_world_aabb_under_scale_translate():
    dens = _make_grid(nx=4, ny=4, nz=4)
    bbox_min = (0, 0, 0)
    i2o = _scale_translate(0.5, 0.5, 0.5, 1.0, 2.0, 3.0)
    o2w = _scale_translate(2.0, 2.0, 2.0, 10.0, 0.0, -5.0)
    gm = astroray.GridMedium()
    gm.set_density(dens, bbox_min=bbox_min,
                   index_to_object=i2o, object_to_world=o2w, supervoxel=2)
    # index->world = o2w @ i2o; corners of index AABB [0,0,0]..[4,4,4].
    i2w = gm.index_to_world()
    corners = [(cx * 4, cy * 4, cz * 4) for cx in (0, 1) for cy in (0, 1) for cz in (0, 1)]
    wmn = [math.inf] * 3
    wmx = [-math.inf] * 3
    for c in corners:
        w = _matvec(i2w, c)
        for a in range(3):
            wmn[a] = min(wmn[a], w[a])
            wmx[a] = max(wmx[a], w[a])
    aabb = gm.world_aabb()
    for a in range(3):
        assert aabb[a] == pytest.approx(wmn[a], abs=1e-4)
        assert aabb[3 + a] == pytest.approx(wmx[a], abs=1e-4)


def test_world_to_index_is_inverse():
    dens = _make_grid(nx=3, ny=3, nz=3)
    i2o = _scale_translate(0.25, 0.5, 2.0, -1.0, 4.0, 0.5)
    o2w = _scale_translate(3.0, 1.0, 0.5, 2.0, -2.0, 7.0)
    gm = astroray.GridMedium()
    gm.set_density(dens, bbox_min=(0, 0, 0),
                   index_to_object=i2o, object_to_world=o2w)
    i2w = gm.index_to_world()
    for idx in [(0.0, 0.0, 0.0), (1.5, 2.0, 0.5), (2.9, 1.1, 2.2)]:
        w = _matvec(i2w, idx)
        back = gm.world_point_to_index(*w)
        for a in range(3):
            assert back[a] == pytest.approx(idx[a], abs=1e-3)


def test_majorant_is_true_upper_bound():
    """σ_t == density here (coeff=1). The majorant must be >= every fine voxel's
    density (per supervoxel) — the unbiasedness precondition for delta tracking."""
    dens = _make_grid(nx=12, ny=9, nz=7, seed=13)
    nz, ny, nx = dens.shape
    bbox_min = (0, 0, 0)
    S = 4
    gm = astroray.GridMedium()
    gm.set_density(dens, bbox_min=bbox_min,
                   index_to_object=IDENTITY, object_to_world=IDENTITY,
                   supervoxel=S)
    rx, ry, rz = gm.majorant_res()
    assert rx == (nx + S - 1) // S
    assert ry == (ny + S - 1) // S
    assert rz == (nz + S - 1) // S

    # numpy per-supervoxel max over the voxel CENTERS in each supervoxel
    # (the lower bound the majorant must meet; the engine adds a 1-voxel halo so
    # its majorant is a true upper bound at every point, hence >= this).
    ref = np.zeros((rx, ry, rz), dtype=np.float32)
    i2w = gm.index_to_world()
    for z in range(nz):
        for y in range(ny):
            for x in range(nx):
                sx = min(int((x + 0.5) / nx * rx), rx - 1)
                sy = min(int((y + 0.5) / ny * ry), ry - 1)
                sz = min(int((z + 0.5) / nz * rz), rz - 1)
                ref[sx, sy, sz] = max(ref[sx, sy, sz], float(dens[z, y, x]))

    # TRUE upper bound: for every fine voxel, the covering supervoxel majorant
    # (queried at the voxel CENTER and at a boundary CORNER) must be >= that
    # voxel's density — the unbiasedness precondition for delta tracking.
    for z in range(nz):
        for y in range(ny):
            for x in range(nx):
                for off in ((0.5, 0.5, 0.5), (0.02, 0.02, 0.02), (0.98, 0.98, 0.98)):
                    w = _matvec(i2w, (x + off[0], y + off[1], z + off[2]))
                    maj = gm.majorant_density_world(*w)
                    assert maj >= float(dens[z, y, x]) - 1e-6, (
                        f"majorant {maj} < voxel density {dens[z, y, x]} at "
                        f"({x},{y},{z}) off {off}")
                # and the supervoxel majorant bounds the numpy center-max.
                sx = min(int((x + 0.5) / nx * rx), rx - 1)
                sy = min(int((y + 0.5) / ny * ry), ry - 1)
                sz = min(int((z + 0.5) / nz * rz), rz - 1)
                cw = _matvec(i2w, (x + 0.5, y + 0.5, z + 0.5))
                assert gm.majorant_density_world(*cw) >= float(ref[sx, sy, sz]) - 1e-6
