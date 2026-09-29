"""pkg298 — CPU BVH cache between render() calls + deterministic parallel build.

`Renderer::buildAcceleration()` reuses the BVH until the scene geometry changes
(`bvhDirty_`: addObject, clear, getSceneMutable). A missed invalidation site would
render stale geometry, so every geometry-mutating binding is exercised below and
its render compared against a renderer built from scratch with the final scene.
Material and dedicated-light edits must NOT rebuild (the BVH holds neither), but
must still show up in the image.

The parallel build must produce the node-for-node identical tree at any thread
count (`_bvh_digest` hashes every flat node and the leaf primitive order).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import runtime_setup  # noqa: F401 — configures sys.path + DLL dirs
runtime_setup.configure_test_imports()
import astroray

W = H = 24
SPP, DEPTH, SEED = 4, 4, 11


def _builds(r):
    return r.get_scene_stats()["bvh_build_count"]


def _base(r=None):
    r = r or astroray.Renderer()
    r.setup_camera([0.0, 0.0, 4.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   40.0, 1.0, 0.0, 4.0, W, H)
    r.set_background_color([0.1, 0.1, 0.12])
    r.set_seed(SEED)
    r.set_adaptive_sampling(False)
    mats = {
        "grey": r.create_material("lambertian", [0.7, 0.7, 0.7], {}),
        "red": r.create_material("lambertian", [0.8, 0.1, 0.1], {}),
        "blue": r.create_material("lambertian", [0.1, 0.2, 0.9], {}),
        "light": r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 6.0}),
    }
    r.add_triangle([-2, -1, -2], [2, -1, -2], [2, -1, 2], mats["grey"])
    r.add_triangle([-2, -1, -2], [2, -1, 2], [-2, -1, 2], mats["grey"])
    r.add_sphere([-0.6, -0.4, 0.0], 0.6, mats["red"])
    r.add_triangle([0.2, -0.8, 0.5], [1.4, -0.8, 0.5], [0.8, 0.6, 0.5], mats["blue"])
    r.add_triangle([-0.5, 1.9, -0.5], [0.5, 1.9, -0.5], [0.5, 1.9, 0.5], mats["light"])
    r.add_triangle([-0.5, 1.9, -0.5], [0.5, 1.9, 0.5], [-0.5, 1.9, 0.5], mats["light"])
    return r, mats


def _render(r):
    r.set_seed(SEED)
    return np.asarray(r.render(SPP, DEPTH, None, False), dtype=np.float32).copy()


def _same(a, b):
    assert a.shape == b.shape
    assert float(np.max(np.abs(a - b))) <= 1e-6


def test_repeat_render_reuses_bvh_and_is_identical():
    r, _ = _base()
    a = _render(r)
    assert _builds(r) == 1
    b = _render(r)
    c = _render(r)
    assert _builds(r) == 1, "unchanged scene rebuilt the BVH"
    _same(a, b)
    _same(a, c)


# Every geometry-mutating binding: (name, mutate(renderer, mats), rebuilds?).
def _add_sphere(r, m):
    r.add_sphere([0.9, 0.6, -0.5], 0.35, m["grey"])


def _add_triangle(r, m):
    r.add_triangle([-1.5, 0.0, -1.0], [-0.5, 0.0, -1.0], [-1.0, 1.0, -1.0], m["blue"])


def _add_bulk(r, m):
    pos = np.array([[[0.5, 0.2, -1.2], [1.5, 0.2, -1.2], [1.0, 1.2, -1.2]]], np.float32)
    r.add_triangles_bulk(pos, np.array([m["red"]], np.int32), np.zeros(1, np.int32), 0,
                         np.zeros((0, 1, 3, 2), np.float32), [],
                         np.zeros((0, 3, 3), np.float32))


def _add_area_light(r, m):
    r.add_sphere([1.2, 1.2, 0.8], 0.15, m["light"])   # emissive geometry


MOVE = [1, 0, 0, 0.3, 0, 1, 0, 0.2, 0, 0, 1, 0, 0, 0, 0, 1]


def _move_sphere(r, m):
    r.update_object_transform(2, MOVE)


def _move_triangle(r, m):
    r.update_object_transform(3, MOVE)


ADDERS = [_add_sphere, _add_triangle, _add_bulk, _add_area_light]
MOVERS = [_move_sphere, _move_triangle]


@pytest.mark.parametrize("mutate", ADDERS, ids=lambda f: f.__name__)
def test_added_geometry_rebuilds_and_matches_fresh(mutate):
    r, m = _base()
    before = _render(r)
    mutate(r, m)
    after = _render(r)
    assert _builds(r) == 2, "added geometry did not rebuild the BVH"
    assert float(np.max(np.abs(after - before))) > 1e-4, "mutation not visible"
    fresh, fm = _base()
    mutate(fresh, fm)
    _same(after, _render(fresh))


@pytest.mark.parametrize("mutate", MOVERS, ids=lambda f: f.__name__)
def test_moved_object_rebuilds_and_matches_fresh(mutate):
    r, m = _base()
    before = _render(r)
    mutate(r, m)
    after = _render(r)
    # update_object_transform rebuilds inside upload_geometry; render reuses it.
    assert _builds(r) == 2
    assert float(np.max(np.abs(after - before))) > 1e-4, "move not visible"
    fresh, fm = _base()
    mutate(fresh, fm)          # same in-place edit on a never-rendered renderer
    _same(after, _render(fresh))


def test_clear_then_rebuild():
    r, _ = _base()
    a = _render(r)
    r.clear()
    _base(r)
    b = _render(r)
    assert _builds(r) == 1   # clear() resets the renderer; one fresh build
    _same(a, b)


def test_material_rebind_keeps_bvh():
    r, m = _base()
    before = _render(r)
    new = r.create_material("lambertian", [0.1, 0.8, 0.1], {})
    assert r.rebind_material(m["red"], new)
    r.upload_materials()
    after = _render(r)
    assert _builds(r) == 1, "material-only edit rebuilt the BVH"
    assert float(np.max(np.abs(after - before))) > 1e-4
    # Fresh scene with the sphere green from the start.
    fresh = astroray.Renderer()
    fresh.setup_camera([0.0, 0.0, 4.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                       40.0, 1.0, 0.0, 4.0, W, H)
    fresh.set_background_color([0.1, 0.1, 0.12])
    fresh.set_adaptive_sampling(False)
    g = fresh.create_material("lambertian", [0.7, 0.7, 0.7], {})
    fresh.create_material("lambertian", [0.8, 0.1, 0.1], {})
    b = fresh.create_material("lambertian", [0.1, 0.2, 0.9], {})
    li = fresh.create_material("light", [1.0, 1.0, 1.0], {"intensity": 6.0})
    gr = fresh.create_material("lambertian", [0.1, 0.8, 0.1], {})
    fresh.add_triangle([-2, -1, -2], [2, -1, -2], [2, -1, 2], g)
    fresh.add_triangle([-2, -1, -2], [2, -1, 2], [-2, -1, 2], g)
    fresh.add_sphere([-0.6, -0.4, 0.0], 0.6, gr)
    fresh.add_triangle([0.2, -0.8, 0.5], [1.4, -0.8, 0.5], [0.8, 0.6, 0.5], b)
    fresh.add_triangle([-0.5, 1.9, -0.5], [0.5, 1.9, -0.5], [0.5, 1.9, 0.5], li)
    fresh.add_triangle([-0.5, 1.9, -0.5], [0.5, 1.9, 0.5], [-0.5, 1.9, 0.5], li)
    _same(after, _render(fresh))


def test_dedicated_light_edit_keeps_bvh_but_updates_image():
    r, _ = _base()
    before = _render(r)
    r.add_point_light([0.0, 1.0, 1.5], {"mode": "rgb", "color": [1.0, 0.9, 0.8]}, 20.0)
    after = _render(r)
    assert _builds(r) == 1, "dedicated light is not BVH geometry"
    assert float(np.max(np.abs(after - before))) > 1e-4, "stale light sampler"
    fresh, _ = _base()
    fresh.add_point_light([0.0, 1.0, 1.5], {"mode": "rgb", "color": [1.0, 0.9, 0.8]}, 20.0)
    _same(after, _render(fresh))


def test_generated_transform_marks_dirty():
    r, _ = _base()
    _render(r)
    r.set_objects_generated_transform(0, 6, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0])
    _render(r)
    assert _builds(r) == 2   # conservative: mutable scene access dirties


def test_instance_transform_keeps_cpu_bvh():
    r, m = _base()
    mesh = r.register_mesh_triangles([[0, 0, 0, 0.3, 0, 0, 0, 0.3, 0]], m["grey"])
    inst = r.add_instance(mesh, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
    _render(r)
    r.update_instance_transform(inst, MOVE)
    _render(r)
    assert _builds(r) == 1   # instances live in the GPU TLAS, not the CPU BVH


_DIGEST_CHILD = r"""
import sys, json
sys.path.insert(0, {tests!r})
import runtime_setup
runtime_setup.configure_test_imports()
import numpy as np
import astroray
n = 160   # 160 x 320 x 2 = 102,400 triangles: exercises parallel reductions + jobs
th = np.linspace(0.0, np.pi, n + 1); ph = np.linspace(0.0, 2 * np.pi, 2 * n + 1)
T, P = np.meshgrid(th, ph, indexing="ij")
rad = 1.0 + 0.05 * np.sin(9 * T) * np.sin(11 * P)
xyz = np.stack([rad * np.sin(T) * np.cos(P), rad * np.cos(T), rad * np.sin(T) * np.sin(P)], -1)
a, b, c, d = xyz[:-1, :-1], xyz[1:, :-1], xyz[1:, 1:], xyz[:-1, 1:]
pos = np.concatenate([np.stack([a, b, c], 2).reshape(-1, 3, 3),
                      np.stack([a, c, d], 2).reshape(-1, 3, 3)]).astype(np.float32)
r = astroray.Renderer()
r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 8, 8)
m = r.create_material("lambertian", [0.5, 0.5, 0.5], {{}})
k = len(pos)
r.add_triangles_bulk(pos, np.full(k, m, np.int32), np.zeros(k, np.int32), 0,
                     np.zeros((0, k, 3, 2), np.float32), [], np.zeros((0, 3, 3), np.float32))
r.upload_geometry()
print("DIGEST " + r._bvh_digest())
"""


def _digest(threads):
    env = dict(os.environ, OMP_NUM_THREADS=str(threads))
    code = _DIGEST_CHILD.format(tests=str(Path(__file__).resolve().parent))
    out = subprocess.run([sys.executable, "-c", code], env=env,
                         capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    line = [ln for ln in out.stdout.splitlines() if ln.startswith("DIGEST ")]
    assert line, out.stdout[-2000:]
    return line[0].split(" ", 1)[1]


def test_parallel_build_node_for_node_identical_to_serial():
    serial = _digest(1)
    parallel = _digest(8)
    assert serial == parallel, (serial, parallel)
    assert int(serial.split(":")[1]) > 100000
