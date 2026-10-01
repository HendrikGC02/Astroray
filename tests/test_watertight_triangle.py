"""#1000 - watertight ray/triangle on the CPU oracle and the GPU software BVH.

The old Moller-Trumbore |det| < 1e-6 rejection missed tiny/grazing triangles.
CPU: standalone C++ test (tests/cpp/test_watertight_triangle.cpp). GPU: fixed-ray
A/B of the software BVH against OptiX on a mesh of tiny triangles (every ray is
aimed at a triangle centroid; OptiX is the correct reference).
"""
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_pkg299_optix_traversal import _renderer  # noqa: E402
import astroray  # noqa: E402


def test_cpu_watertight_cpp(tmp_path):
    cxx = shutil.which("g++") or shutil.which("clang++")
    if cxx is None:
        pytest.skip("no C++ compiler")
    exe = tmp_path / "wt_test.exe"
    src = ROOT / "tests" / "cpp" / "test_watertight_triangle.cpp"
    subprocess.run([cxx, "-std=c++17", "-O2", "-I", str(ROOT / "include"), str(src), "-o", str(exe)],
                   check=True)
    res = subprocess.run([str(exe)], capture_output=True, text=True)
    assert res.returncode == 0, res.stdout


@pytest.mark.skipif(not hasattr(astroray, "_gpu_optix_ray_ab"), reason="no OptiX A/B hook")
def test_gpu_software_hits_tiny_triangles():
    r = _renderer()
    m = r.create_material("lambertian", [0.7, 0.7, 0.7], {})
    # Grid of right triangles with legs 4e-4 (|det| = 1.6e-7 < 1e-6) in a tilted plane.
    n = 40
    h = 4e-4
    tris = []
    for i in range(n):
        for j in range(n):
            o = np.array([i * 2 * h - 0.5, j * 2 * h - 0.5, 0.0])
            tris.append([o, o + [h, 0, 0], o + [0, h, 0.05 * h]])
    pos = np.asarray(tris, np.float32)
    k = len(pos)
    r.add_triangles_bulk(pos, np.full(k, m, np.int32), np.zeros(k, np.int32), 0,
                         np.zeros((0, k, 3, 2), np.float32), [],
                         np.zeros((0, 3, 3), np.float32))
    cen = pos.mean(axis=1)
    o = (cen + np.array([0.0, 0.0, 1.0])).astype(np.float32)
    d = np.tile(np.array([0.0, 0.0, -1.0], np.float32), (k, 1))
    ab = astroray._gpu_optix_ray_ab(r, o, d, np.full(k, 1e30, np.float32), False)
    assert ab["hw_hit"].all(), "OptiX reference must hit every tiny triangle"
    miss = (~ab["sw_hit"].astype(bool)).sum()
    assert miss == 0, f"software BVH missed {miss}/{k} tiny triangles"
    assert (ab["sw_prim"] == ab["hw_prim"]).all()
