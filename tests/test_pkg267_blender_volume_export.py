"""pkg267 — Blender headless `bpy.types.Volume` / OpenVDB export.

Runs a real ``blender --background`` process that:
  1. builds a small heterogeneous `.vdb` with Blender's bundled ``openvdb``,
  2. creates a ``bpy.types.Volume`` object referencing it,
  3. runs ``blender_addon.volume_export.export_volume_objects`` against a mock
     renderer, asserting the captured dense array / bbox / transform match the
     known grid,
  4. writes the captured payload to an ``.npz``.

Back in pytest, the payload is fed to the real engine ``astroray.GridMedium`` and
its world AABB is checked against the object->world * index->object transform —
the full addon->engine round trip ("exports to an engine grid handle with
matching bounds", pkg267 acceptance).

Skips cleanly when no Blender is installed (CI runners have none).
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

import astroray

_BLENDER = r"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe"

_REPO = Path(__file__).resolve().parents[1]
_ADDON_DIR = _REPO / "blender_addon"

_SCRIPT = r'''
import sys, json
import numpy as np

addon_dir = sys.argv[sys.argv.index("--") + 1]
out_npz = sys.argv[sys.argv.index("--") + 2]
vdb_path = sys.argv[sys.argv.index("--") + 3]
sys.path.insert(0, addon_dir)

import bpy, openvdb
import volume_export

bpy.ops.wm.read_factory_settings(use_empty=True)

# --- build a small heterogeneous density grid (12^3, linear voxel size 0.1) ---
D = 12
arr = np.zeros((D, D, D), dtype=np.float32)  # [x, y, z]
for x in range(D):
    for y in range(D):
        for z in range(D):
            arr[x, y, z] = 0.2 + 0.1 * (x + y + z)   # strictly positive -> full bbox
grid = openvdb.FloatGrid()
grid.copyFromArray(arr)                     # active bbox (0,0,0)..(D-1,D-1,D-1)
grid.name = "density"
grid.transform = openvdb.createLinearTransform(voxelSize=0.1)
openvdb.write(vdb_path, grids=[grid])

# --- Volume object referencing the .vdb ---
vol = bpy.data.volumes.new("fog")
vol.filepath = vdb_path
obj = bpy.data.objects.new("FogObj", vol)
# object at a translation so object->world is non-identity.
obj.location = (5.0, -2.0, 1.0)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.update()
depsgraph = bpy.context.evaluated_depsgraph_get()

class Rec:
    def __init__(self):
        self.calls = []
    def set_volume_grid(self, name, density, bbox_min, index_to_object,
                        object_to_world, temperature=None):
        self.calls.append(dict(name=name, density=density, bbox_min=bbox_min,
                               index_to_object=index_to_object,
                               object_to_world=object_to_world))

rec = Rec()
names = volume_export.export_volume_objects(depsgraph, rec, bpy_module=bpy)
failures = []
if names != ["FogObj"]:
    failures.append("exported names %r != ['FogObj']" % names)
if len(rec.calls) != 1:
    failures.append("set_volume_grid calls %d != 1" % len(rec.calls))
else:
    c = rec.calls[0]
    dens = c["density"]
    print("[pkg267-HB] density shape (nz,ny,nx) =", dens.shape)
    print("[pkg267-HB] bbox_min =", c["bbox_min"])
    if dens.shape != (D, D, D):
        failures.append("density shape %r != (%d,%d,%d)" % (dens.shape, D, D, D))
    if tuple(c["bbox_min"]) != (0, 0, 0):
        failures.append("bbox_min %r != (0,0,0)" % (c["bbox_min"],))
    # density[z,y,x] must equal arr[x,y,z]
    if not np.allclose(dens[3, 2, 1], arr[1, 2, 3], atol=1e-5):
        failures.append("density transpose mismatch: %r vs %r"
                        % (dens[3, 2, 1], arr[1, 2, 3]))
    np.savez(out_npz, density=dens, bbox_min=np.array(c["bbox_min"]),
             index_to_object=np.array(c["index_to_object"], dtype=np.float64),
             object_to_world=np.array(c["object_to_world"], dtype=np.float64))

if failures:
    print("PKG267_HB_FAILURES:" + json.dumps(failures))
    sys.exit(3)
print("PKG267_HB_OK")
'''


sys.path.insert(0, str(_ADDON_DIR))
import volume_export  # noqa: E402  (addon module, Blender-free import)


class _FakeTransform:
    """Minimal openvdb.Transform stand-in: linear, voxel size v, origin o."""
    def __init__(self, v, o):
        self.v = v
        self.o = o
    def indexToWorld(self, ijk):
        return (self.o[0] + self.v[0] * ijk[0],
                self.o[1] + self.v[1] * ijk[1],
                self.o[2] + self.v[2] * ijk[2])


class _FakeGrid:
    def __init__(self, arr_xyz, mn, transform):
        self._arr = arr_xyz  # [x,y,z]
        self._mn = mn
        self.transform = transform
    def evalActiveVoxelBoundingBox(self):
        mn = self._mn
        s = self._arr.shape
        return (mn, (mn[0] + s[0] - 1, mn[1] + s[1] - 1, mn[2] + s[2] - 1))
    def copyToArray(self, out, ijk=(0, 0, 0)):
        out[:] = self._arr  # dense block aligned to bbox min


def test_index_to_object_matrix_linear():
    t = _FakeTransform((0.5, 0.25, 2.0), (1.0, -3.0, 4.0))
    m = volume_export.index_to_object_matrix(_FakeGrid(np.zeros((1, 1, 1), np.float32), (0, 0, 0), t))
    # columns are the scaled basis, last column is the origin (row-major 4x4).
    assert m[0] == pytest.approx(0.5) and m[5] == pytest.approx(0.25) and m[10] == pytest.approx(2.0)
    assert m[3] == pytest.approx(1.0) and m[7] == pytest.approx(-3.0) and m[11] == pytest.approx(4.0)
    assert m[12:16] == [0.0, 0.0, 0.0, 1.0]


def test_dense_from_grid_transposes_to_nzyx():
    arr_xyz = np.zeros((4, 3, 2), dtype=np.float32)  # [x,y,z]
    arr_xyz[3, 2, 1] = 9.0
    g = _FakeGrid(arr_xyz, (-1, 5, 2), _FakeTransform((1, 1, 1), (0, 0, 0)))
    nzyx, bbox_min = volume_export.dense_from_grid(g)
    assert nzyx.shape == (2, 3, 4)  # (nz, ny, nx)
    assert bbox_min == (-1, 5, 2)
    assert nzyx[1, 2, 3] == pytest.approx(9.0)  # [z,y,x] == arr[x,y,z]


@pytest.mark.skipif(not os.path.exists(_BLENDER), reason="Blender 5.2 not installed")
def test_blender_volume_exports_to_grid_medium(tmp_path):
    script = tmp_path / "pkg267_hb.py"
    script.write_text(_SCRIPT)
    out_npz = tmp_path / "payload.npz"
    vdb_path = tmp_path / "fog.vdb"
    proc = subprocess.run(
        [_BLENDER, "-b", "--factory-startup", "--python-exit-code", "1",
         "--python", str(script), "--",
         str(_ADDON_DIR), str(out_npz), str(vdb_path)],
        capture_output=True, text=True, timeout=300)
    out = proc.stdout + "\n" + proc.stderr
    assert "PKG267_HB_OK" in out, "headless export failed:\n" + out
    assert out_npz.exists(), "payload npz not written:\n" + out

    # --- engine side: build a real GridMedium from the exported payload ---
    data = np.load(out_npz)
    density = np.ascontiguousarray(data["density"].astype(np.float32))
    bbox_min = tuple(int(v) for v in data["bbox_min"])
    i2o = [float(v) for v in data["index_to_object"]]
    o2w = [float(v) for v in data["object_to_world"]]

    gm = astroray.GridMedium()
    gm.set_density(density, bbox_min=bbox_min,
                   index_to_object=i2o, object_to_world=o2w)
    assert gm.valid()
    nz, ny, nx = density.shape
    assert gm.dims() == (nx, ny, nz)

    # world AABB: object at (5,-2,1), voxel size 0.1, 12 voxels -> 1.2 extent.
    aabb = gm.world_aabb()
    assert aabb[0] == pytest.approx(5.0, abs=1e-3)
    assert aabb[1] == pytest.approx(-2.0, abs=1e-3)
    assert aabb[2] == pytest.approx(1.0, abs=1e-3)
    assert aabb[3] == pytest.approx(5.0 + 1.2, abs=1e-3)
    assert aabb[4] == pytest.approx(-2.0 + 1.2, abs=1e-3)
    assert aabb[5] == pytest.approx(1.0 + 1.2, abs=1e-3)
