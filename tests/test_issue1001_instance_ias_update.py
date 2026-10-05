"""Issue #1001 item 2 - transform-only pkg114 instance edits keep every GAS.

A viewport transform edit of instanced objects (refit_instance_transforms ->
upload_instance_transforms -> render(skip_upload=True)) used to invalidate the whole
wavefront scene cache, so every OptiX GAS and the IAS were rebuilt along with the host
flatten (62 ms per render on the 2M-triangle Cornell). It now logs the edit against the
scene version (Renderer::getInstanceLog); the next render re-pushes only d_instances and
d_tlas and rebuilds only the OptiX IAS. Anything that is not provably transform-only
(instance added, mesh registered, geometry or material edit in between, an instance
dropped by a singular transform) takes the full re-flatten.

Gates (GPU): the instance-update render equals a forced full re-flatten of the same
scene (to the GPU accumulation float-atomic floor, see _ATOL) and a cold render of the
final scene; each guard reports gpu_instance_update == False; and on a large instanced
scene the edit + render is faster than the full re-flatten (timing probe; the numbers
are printed). The ASTRORAY_PROFILE breakdown (host:instancePatch, host:optixIasRebuild vs
host:optixAccelBuild) is collected by test_profile_breakdown.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

import numpy as np
import pytest
import runtime_setup  # configures sys.path + DLL dirs

runtime_setup.configure_test_imports()
import astroray

pytestmark = pytest.mark.gpu

W = H = 24
SPP, DEPTH, SEED = 4, 4, 11
# GPU accumulation uses float atomics: two renders of the SAME scene and seed differ by
# ~3e-7 (see tests/test_pkg315_material_domain_update.py). _ATOL is ~7x that floor and far
# below _differs (1e-4), so a wrong instance upload (a stale transform) still fails.
_ATOL = 2e-6


def _mv(x, y, z):
    return [1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1]


@pytest.fixture(params=["optix", "software"], autouse=True)
def traversal(request, monkeypatch):
    monkeypatch.setenv("ASTRORAY_GPU_TRAVERSAL", request.param)
    return request.param


def _bumpy_sphere(radius, n):
    """UV sphere with a bumpy radius (the pkg299 heavy-Cornell mesh generator), (T,3,3)."""
    th = np.linspace(0.0, np.pi, n + 1)
    ph = np.linspace(0.0, 2.0 * np.pi, 2 * n + 1)
    T, P = np.meshgrid(th, ph, indexing="ij")
    r = radius * (1.0 + 0.06 * np.sin(9 * T) * np.sin(11 * P)
                  + 0.03 * np.sin(23 * T) * np.cos(17 * P))
    xyz = np.stack([r * np.sin(T) * np.cos(P), r * np.cos(T), r * np.sin(T) * np.sin(P)],
                   axis=-1)
    a, b = xyz[:-1, :-1], xyz[1:, :-1]
    c, d = xyz[1:, 1:], xyz[:-1, 1:]
    t0 = np.stack([a, b, c], axis=2).reshape(-1, 3, 3)
    t1 = np.stack([a, c, d], axis=2).reshape(-1, 3, 3)
    return np.concatenate([t0, t1], axis=0).astype(np.float32)


def _register(r, tris, mat):
    n = len(tris)
    return r.register_mesh_bulk(tris, np.full(n, mat, np.int32), np.zeros(n, np.int32), 0,
                                np.zeros((0, n, 3, 2), np.float32), [],
                                np.zeros((0, 3, 3), np.float32))


def _scene(sphere_n=12, instances=3):
    """Triangle-only: a flat floor + light, and a registered bumpy-sphere mesh instanced
    `instances` times. Returns (renderer, materials, instance ids, mesh id)."""
    r = astroray.Renderer()
    if not r.gpu_available:
        pytest.skip("CUDA device not available")
    r.setup_camera([0.0, 0.5, 5.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0], 40.0, 1.0, 0.0, 5.0, W, H)
    r.set_background_color([0.1, 0.1, 0.12])
    r.set_adaptive_sampling(False)
    m = {
        "grey": r.create_material("lambertian", [0.7, 0.7, 0.7], {}),
        "red": r.create_material("lambertian", [0.8, 0.2, 0.2], {}),
        "light": r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 6.0}),
    }
    r.add_triangle([-4, -1, -4], [4, -1, -4], [4, -1, 4], m["grey"])
    r.add_triangle([-4, -1, -4], [4, -1, 4], [-4, -1, 4], m["grey"])
    r.add_triangle([-0.5, 2.5, -0.5], [0.5, 2.5, -0.5], [0.5, 2.5, 0.5], m["light"])
    r.add_triangle([-0.5, 2.5, -0.5], [0.5, 2.5, 0.5], [-0.5, 2.5, 0.5], m["light"])
    mesh = _register(r, _bumpy_sphere(0.5, sphere_n), m["red"])
    ids = [r.add_instance(mesh, _mv(-1.5 + 1.5 * k, -0.4, 0.2 * k)) for k in range(instances)]
    r.set_use_gpu(True)
    return r, m, ids, mesh


def _render(r, spp=SPP):
    r.set_seed(SEED)
    return np.asarray(r.render(spp, DEPTH, None, False), dtype=np.float32).copy()


def _info(r):
    i = r.last_render_info()
    return bool(i["gpu_scene_reused"]), bool(i["gpu_instance_update"]), i["gpu_traversal"]


def _same(a, b):
    return bool(np.allclose(a, b, rtol=0.0, atol=_ATOL, equal_nan=True))


def _differs(a, b):
    assert float(np.max(np.abs(a - b))) > 1e-4, "edit not visible in the image"


def _edit(r, ids, dx):
    for k, iid in enumerate(ids):
        r.update_instance_transform(iid, _mv(-1.5 + 1.5 * k + dx, -0.4 + 0.1 * dx, 0.2 * k))
    r.upload_instance_transforms()


def test_instance_edit_matches_full_reflatten():
    r, _, ids, _ = _scene()
    before = _render(r)
    assert not _info(r)[1]
    for step, dx in enumerate((0.3, 0.6, -0.2)):   # repeated edits stay on the patched path
        _edit(r, ids, dx)
        after = _render(r)
        reused, updated, _ = _info(r)
        assert updated and not reused, f"step {step}: instance edit did not take the update path"
        _differs(after, before)
        # forced full re-flatten of the SAME scene state (a lights upload invalidates the cache)
        r.upload_lights()
        flat = _render(r)
        reused, updated, _ = _info(r)
        assert not updated and not reused
        assert _same(after, flat), (
            f"step {step}: |instance-update - re-flatten| max "
            f"{float(np.max(np.abs(after - flat))):.3e}")
        before = after
    # an unedited repeat serves the cache; the update path re-armed it. Checked
    # before the cold render: the wavefront cache is process-global and keyed on
    # the owning renderer, so `fresh` below takes it over.
    _render(r)
    assert _info(r)[0]
    # cold render of the final scene
    fresh, _, fids, _ = _scene()
    _edit(fresh, fids, -0.2)
    assert _same(after, _render(fresh))


def test_partial_edit_moves_only_one_instance():
    r, _, ids, _ = _scene()
    _render(r)
    r.update_instance_transform(ids[1], _mv(0.4, -0.4, 0.6))
    r.upload_instance_transforms()
    after = _render(r)
    assert _info(r)[1]
    fresh, _, fids, _ = _scene()
    fresh.update_instance_transform(fids[1], _mv(0.4, -0.4, 0.6))
    assert _same(after, _render(fresh))


# ---- guards: anything not provably transform-only takes the full path -------------------
def _add_instance(r, _m, _ids, mesh):
    r.add_instance(mesh, _mv(1.0, 0.3, -0.5))


def _register_mesh(r, m, _ids, _mesh):
    r.register_mesh_triangles([[0, 0, 0, 0.4, 0, 0, 0, 0.4, 0]], m["grey"])


def _add_flat_triangle(r, m, _ids, _mesh):
    r.add_triangle([0.2, -0.9, 1.0], [1.0, -0.9, 1.0], [0.6, 0.0, 1.0], m["red"])


def _singular_transform(r, _m, ids, _mesh):      # the instance is skipped: count changes
    r.update_instance_transform(ids[0], [0.0] * 12 + [0, 0, 0, 1])
    r.upload_instance_transforms()


def _upload_lights_between(r, _m, _ids, _mesh):
    r.upload_lights()


def _object_move_between(r, _m, _ids, _mesh):
    r.update_object_transform(0, _mv(0.0, 0.0, 0.1))


def _material_edit_between(r, m, _ids, _mesh):
    new = r.create_material("lambertian", [0.1, 0.8, 0.1], {})
    assert r.rebind_material(m["grey"], new)
    r.upload_materials()


GUARDS = [_add_instance, _register_mesh, _add_flat_triangle, _singular_transform,
          _upload_lights_between, _object_move_between, _material_edit_between]


@pytest.mark.parametrize("mutate", GUARDS, ids=[g.__name__ for g in GUARDS])
def test_guard_takes_the_full_path_and_matches_fresh(mutate):
    r, m, ids, mesh = _scene()
    _render(r)
    _render(r)
    _edit(r, ids, 0.3)          # a transform-only edit pending ...
    mutate(r, m, ids, mesh)     # ... plus something that is not
    after = _render(r)
    reused, updated, _ = _info(r)
    assert not updated, f"{mutate.__name__}: guard did not fall back to the full re-flatten"
    assert not reused
    fresh, fm, fids, fmesh = _scene()
    _edit(fresh, fids, 0.3)
    mutate(fresh, fm, fids, fmesh)
    assert _same(after, _render(fresh)), f"{mutate.__name__}: differs from a cold render"


def test_edit_before_any_upload_is_full():
    r, _, ids, _ = _scene()
    _edit(r, ids, 0.3)          # no render yet: nothing cached
    _render(r)
    assert not _info(r)[1]


# ---- engine-side timing probe (large instanced scene) -----------------------------------
def _heavy(n):
    r, _, ids, _ = _scene(sphere_n=n, instances=4)
    return r, ids


def _ms(fn, n):
    out = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1e3)
    return min(out)


def test_heavy_instanced_edit_is_cheaper_than_reflatten():
    n = int(os.environ.get("ASTRORAY_1001_HEAVY_N", "250"))   # 2*(2n)*n triangles per mesh
    r, ids = _heavy(n)
    tris = 4 * n * n
    flip = [0.0]

    def edit_render():
        flip[0] += 0.05
        _edit(r, ids, flip[0])
        r.set_seed(SEED)
        r.render(1, 2, None, False)

    def full_render():
        flip[0] += 0.05
        _edit(r, ids, flip[0])
        r.upload_lights()            # forces the full re-flatten of the same scene
        r.set_seed(SEED)
        r.render(1, 2, None, False)

    r.set_seed(SEED)
    r.render(1, 2, None, False)       # warm: first upload + OptiX init
    edit_render()
    assert _info(r)[1]
    t_edit = _ms(edit_render, 5)
    assert _info(r)[1]
    full_render()
    assert not _info(r)[1]
    t_full = _ms(full_render, 5)
    print(f"\n#1001 heavy instanced ({tris} tris/mesh x4): instance update "
          f"{t_edit:.1f} ms vs full re-flatten {t_full:.1f} ms ({t_full / t_edit:.1f}x)")
    assert t_edit < 0.5 * t_full, f"instance update {t_edit:.1f} ms is not < 50% of {t_full:.1f} ms"


def test_profile_breakdown():
    """ASTRORAY_PROFILE=1 in a child process: the update path records host:instancePatch +
    host:optixIasRebuild; host:optixAccelBuild is recorded for the first render only."""
    if os.environ.get("ASTRORAY_GPU_TRAVERSAL") != "optix":
        pytest.skip("IAS rebuild is an OptiX-path stage")
    here = os.path.dirname(os.path.abspath(__file__))
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "prof.json")
        env = dict(os.environ, ASTRORAY_PROFILE="1", ASTRORAY_PROFILE_OUT=out,
                   ASTRORAY_GPU_TRAVERSAL="optix")
        code = (
            f"import sys; sys.path.insert(0, {here!r})\n"
            "import test_issue1001_instance_ias_update as t\n"
            "r, m, ids, _ = t._scene(sphere_n=60)\n"
            "t._render(r)\n"
            "for dx in (0.2, 0.4):\n"
            "    t._edit(r, ids, dx); t._render(r)\n"
            "assert t._info(r)[1]\n")
        p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                           cwd=here, timeout=300, check=False)
        assert p.returncode == 0, p.stderr[-2000:]
        with open(out) as fh:
            prof = json.load(fh)
        print("\n#1001 profile:", json.dumps(
            {k: v for k, v in _host_entries(prof).items()}, indent=1))
        host = _host_entries(prof)
        assert "host:optixIasRebuild" in host and "host:instancePatch" in host
        assert host["host:optixIasRebuild"]["count"] == 2
        assert host["host:optixAccelBuild"]["count"] == 1     # the first render only
        assert host["host:buildSceneArrays"]["count"] == 3     # recorded on every render


def _host_entries(prof):
    """The profile JSON's host:* aggregator rows, keyed by name (shape-tolerant)."""
    found = {}

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(k, str) and k.startswith("host:") and isinstance(v, dict):
                    found[k] = {"count": v.get("count", v.get("launches", 0)),
                                "sum_ms": v.get("sum_ms", 0.0)}
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                if isinstance(v, dict) and isinstance(v.get("name"), str) \
                        and v["name"].startswith("host:"):
                    found[v["name"]] = {"count": v.get("count", v.get("launches", 0)),
                                        "sum_ms": v.get("sum_ms", 0.0)}
                else:
                    walk(v)

    walk(prof)
    return found
