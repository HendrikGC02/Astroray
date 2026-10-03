"""pkg291 / #875 - in-place transform update for a non-instanced mesh object.

A viewport object move used to promote to a full re-sync (~130 ms on 100k
triangles: re-export from Blender, BVH rebuild, re-flatten, re-upload). Now the
addon records each mesh object's contiguous triangle range at sync time and a
transform-only edit calls Renderer.transform_object_range(start, count, delta),
delta = M_new * M_old^-1: positions by delta, vertex normals by its
inverse-transpose, Generated coords untouched (object-local), BVH refit (no
rebuild), and the GPU wavefront patches only the moved triangles + node bounds
into its cached device scene (no re-flatten).

Equality vs a full re-export: the spec asks for byte-identical data, which a
delta applied to stored float32 world-space vertices cannot give by construction
(the spec's own design). The delta is evaluated in double and rounded once, so
positions agree to <= 2 float32 ULP; asserted at 4 ULP of the coordinate scale.
"""
import time

import numpy as np
import pytest
import runtime_setup  # configures sys.path + DLL dirs

runtime_setup.configure_test_imports()
import astroray

N_SIDE = 224             # 2 * 224^2 = 100,352 triangles
W, H = 64, 48
SEED = 7


def _grid(n=N_SIDE):
    """Object-space wavy grid: (n*n*2, 3, 3) positions and smooth normals."""
    xs = np.linspace(-1.0, 1.0, n + 1)
    X, Y = np.meshgrid(xs, xs, indexing="ij")
    Z = 0.15 * np.sin(3 * X) * np.cos(2 * Y)
    P = np.stack([X, Y, Z], -1)
    dzdx = 0.45 * np.cos(3 * X) * np.cos(2 * Y)
    dzdy = -0.3 * np.sin(3 * X) * np.sin(2 * Y)
    Nn = np.stack([-dzdx, -dzdy, np.ones_like(X)], -1)
    Nn /= np.linalg.norm(Nn, axis=-1, keepdims=True)
    a, b, c, d = (slice(0, -1), slice(0, -1)), (slice(1, None), slice(0, -1)), \
                 (slice(0, -1), slice(1, None)), (slice(1, None), slice(1, None))
    def q(s, A): return A[s].reshape(-1, 3)
    pos = np.concatenate([np.stack([q(a, P), q(b, P), q(c, P)], 1),
                          np.stack([q(b, P), q(d, P), q(c, P)], 1)])
    nrm = np.concatenate([np.stack([q(a, Nn), q(b, Nn), q(c, Nn)], 1),
                          np.stack([q(b, Nn), q(d, Nn), q(c, Nn)], 1)])
    return pos, nrm


def _rot_z(deg, t=(0.0, 0.0, 0.0), s=1.0):
    r = np.radians(deg)
    M = np.eye(4)
    M[:2, :2] = [[np.cos(r), -np.sin(r)], [np.sin(r), np.cos(r)]]
    M[:3, :3] *= s
    M[:3, 3] = t
    return M


M_OLD = _rot_z(10.0, (0.3, -0.2, 0.0))
M_NEW = _rot_z(35.0, (0.9, 0.4, 0.25))
GEN_OBJ = np.array([[0.5, 0, 0, 0.5], [0, 0.5, 0, 0.5], [0, 0, 0.5, 0.5]])  # obj -> Generated


def _scene(M, gpu=False, pos_nrm=None):
    """A renderer holding the grid object exported at pose M, exactly as the
    addon's bulk path does (world positions, inverse-transpose normals, #847
    world -> Generated affine), plus a static floor triangle pair."""
    pos, nrm = pos_nrm if pos_nrm is not None else _grid()
    r = astroray.Renderer()
    if gpu:
        if not r.gpu_available:
            pytest.skip("CUDA device not available")
        r.set_use_gpu(True)
    r.setup_camera([0.0, -3.0, 2.5], [0.3, 0.0, 0.0], [0.0, 0.0, 1.0],
                   45.0, W / H, 0.0, 4.0, W, H)
    r.set_background_color([0.6, 0.7, 0.9])
    r.set_adaptive_sampling(False)
    m = r.create_material("lambertian", [0.7, 0.5, 0.3], {})
    floor = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
    r.add_triangle([-3, -3, -0.5], [3, -3, -0.5], [3, 3, -0.5], floor)
    r.add_triangle([-3, -3, -0.5], [3, 3, -0.5], [-3, 3, -0.5], floor)
    start = r.scene_object_count()
    world = pos @ M[:3, :3].T + M[:3, 3]
    nmat = np.linalg.inv(M[:3, :3]).T
    wn = nrm @ nmat.T
    wn /= np.linalg.norm(wn, axis=-1, keepdims=True)
    n = len(pos)
    r.add_triangles_bulk(np.ascontiguousarray(world, np.float32), np.full(n, m, np.int32),
                         np.zeros(n, np.int32), 0, np.zeros((0, 1, 3, 2), np.float32), [],
                         np.ascontiguousarray(wn, np.float32))
    gen_world = GEN_OBJ @ np.linalg.inv(M)          # world -> Generated (3x4)
    r.set_objects_generated_transform(start, start + n, gen_world.reshape(-1).tolist())
    r.upload_geometry()                              # build the BVH
    return r, start, n


def _delta():
    return (M_NEW @ np.linalg.inv(M_OLD)).reshape(-1).tolist()


def test_transform_matches_full_reexport_and_bvh_refits():
    pn = _grid()
    a, start, n = _scene(M_OLD, pos_nrm=pn)
    b, _, _ = _scene(M_NEW, pos_nrm=pn)
    builds = a.get_scene_stats()["bvh_build_count"]
    assert a.transform_object_range(start, n, _delta())
    assert a.get_scene_stats()["bvh_build_count"] == builds  # refit, no rebuild
    Pa, Na, Ga = a._triangle_geometry(start, n)
    Pb, Nb, Gb = b._triangle_geometry(start, n)
    ulp = np.spacing(np.float32(np.abs(Pb).max()))
    assert float(np.abs(Pa - Pb).max()) <= 4 * ulp
    assert float(np.abs(Na - Nb).max()) <= 1e-6
    # Generated coords are object-local: untouched by the move, equal to the
    # re-export's (which bakes world -> Generated from the new pose).
    assert float(np.abs(Ga - Gb).max()) <= 1e-5
    assert a._bvh_encloses_prims()
    # The floor (outside the range) is untouched.
    Fa, _, _ = a._triangle_geometry(0, 2)
    Fb, _, _ = b._triangle_geometry(0, 2)
    assert np.array_equal(Fa, Fb)


def test_transform_100k_wall_time_under_10ms():
    a, start, n = _scene(M_OLD)
    assert n >= 100_000
    d = _delta()
    inv = (M_OLD @ np.linalg.inv(M_NEW)).reshape(-1).tolist()
    times = []
    for i in range(6):
        t0 = time.perf_counter()
        assert a.transform_object_range(start, n, d if i % 2 == 0 else inv)
        times.append((time.perf_counter() - t0) * 1e3)
    assert min(times) < 10.0, times


def test_cpu_render_after_move_matches_fresh_scene():
    pn = _grid(48)
    a, start, n = _scene(M_OLD, pos_nrm=pn)
    b, _, _ = _scene(M_NEW, pos_nrm=pn)
    a.render(1, 3, None, False)                      # warm (BVH in use)
    assert a.transform_object_range(start, n, _delta())
    for r in (a, b):
        r.set_seed(SEED)
    ia = np.asarray(a.render(4, 3, None, False), np.float32)
    ib = np.asarray(b.render(4, 3, None, False), np.float32)
    assert float(np.abs(ia - ib).max()) <= 1e-4


def test_refuses_emissive_and_bad_range():
    r = astroray.Renderer()
    light = r.create_material("light", [1, 1, 1], {"intensity": 3.0})
    r.add_triangle([0, 0, 0], [1, 0, 0], [0, 1, 0], light)
    r.upload_geometry()
    ident = np.eye(4).reshape(-1).tolist()
    assert r.transform_object_range(0, 1, ident) is False
    assert r.transform_object_range(0, 5, ident) is False


@pytest.mark.gpu
@pytest.mark.parametrize("traversal", ["optix", "software"])
def test_gpu_patches_cached_scene_and_matches_fresh_render(traversal, monkeypatch):
    monkeypatch.setenv("ASTRORAY_GPU_TRAVERSAL", traversal)
    pn = _grid(96)
    a, start, n = _scene(M_OLD, gpu=True, pos_nrm=pn)
    b, _, _ = _scene(M_NEW, gpu=True, pos_nrm=pn)

    def render(r):
        r.set_seed(SEED)
        return np.asarray(r.render(4, 3, None, False), np.float32).copy()

    before = render(a)
    render(a)
    assert a.last_render_info()["gpu_scene_reused"] is True
    assert a.transform_object_range(start, n, _delta())
    moved = render(a)
    info = a.last_render_info()
    assert info["gpu_scene_patched"] is True and info["gpu_scene_reused"] is False
    # Re-render BEFORE touching renderer b: the device-scene cache is process-
    # global and keyed on the owning renderer (#801), so b's render evicts a's.
    again = render(a)
    assert a.last_render_info()["gpu_scene_reused"] is True
    assert float(np.abs(again - moved).max()) <= 1e-6
    fresh = render(b)
    assert float(np.abs(moved - fresh).max()) <= 1e-4
    assert float(np.abs(moved - before).max()) > 1e-2   # the edit is visible
    # A non-refit edit after a refit breaks the chain: full re-flatten.
    a.add_sphere([0.0, 0.0, 1.2], 0.2, a.create_material("lambertian", [1, 1, 1], {}))
    render(a)
    info = a.last_render_info()
    assert info["gpu_scene_patched"] is False and info["gpu_scene_reused"] is False


@pytest.mark.gpu
def test_gpu_patched_move_100k_faster_than_reflatten():
    a, start, n = _scene(M_OLD, gpu=True)
    a.setup_camera([0.0, -3.0, 2.5], [0.3, 0.0, 0.0], [0.0, 0.0, 1.0],
                   45.0, 16 / 9, 0.0, 4.0, 640, 360)
    for _ in range(3):
        a.render(1, 3, None, False)
    d = _delta()
    inv = (M_OLD @ np.linalg.inv(M_NEW)).reshape(-1).tolist()
    patched, full = [], []
    for i in range(6):
        t0 = time.perf_counter()
        assert a.transform_object_range(start, n, d if i % 2 == 0 else inv)
        a.render(1, 3, None, False)
        patched.append((time.perf_counter() - t0) * 1e3)
        assert a.last_render_info()["gpu_scene_patched"] is True
    for _ in range(3):
        t0 = time.perf_counter()
        a.upload_materials()               # invalidates: full re-flatten path
        a.render(1, 3, None, False)
        full.append((time.perf_counter() - t0) * 1e3)
    print(f"[pkg291] 100k move+render ms patched={sorted(patched)} full={sorted(full)}")
    assert min(patched) < min(full)


# ------------------------------------------------- exporter dispatch (bpy-free)
def _exporter_module():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).parent.parent / "blender_addon" / "exporter.py"
    spec = importlib.util.spec_from_file_location("astroray_exporter_pkg291_xf", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Obj:
    def __init__(self, name, M):
        self.name = name
        self.type = "MESH"
        self.matrix_world = [list(row) for row in M]


class _Upd:
    def __init__(self, uid):
        self.id = uid
        self.is_updated_geometry = False
        self.is_updated_transform = True
        self.is_updated_shading = False


class _StubRenderer:
    def __init__(self, ok=True):
        self.calls = []
        self.ok = ok

    def transform_object_range(self, start, count, delta):
        self.calls.append((start, count, delta))
        return self.ok


def _exporter_with_range(mod, M_old):
    import types
    bpy = types.SimpleNamespace(types=types.SimpleNamespace(Object=_Obj))
    eng = types.SimpleNamespace(
        _renderer_instance_id_map={}, _renderer_instancer_eligible={},
        _renderer_object_ranges={"Grid": (2, 100, M_old.reshape(-1).tolist())},
        report=lambda *a, **k: None)
    e = mod.Exporter(eng, bpy, types.SimpleNamespace())
    e._viewport_full_synced = True
    return e, eng


def test_exporter_routes_mesh_move_in_place():
    mod = _exporter_module()
    e, eng = _exporter_with_range(mod, M_OLD)
    dg = type("DG", (), {})()
    dg.updates = [_Upd(_Obj("Grid", M_NEW))]
    dg.scene = None
    status, changes, flat, refit = e._classify_depsgraph_domains(dg, None)
    assert status == "dispatched" and not (changes & mod.Change.GEOMETRY)
    assert flat and flat[0][0] == "Grid" and refit is False
    r = _StubRenderer()
    assert e._dispatch_dirty_domains(r, dg, None, None, None, changes, flat, refit)
    (start, count, delta), = r.calls
    assert (start, count) == (2, 100)
    np.testing.assert_allclose(np.reshape(delta, (4, 4)), M_NEW @ np.linalg.inv(M_OLD),
                               atol=1e-12)
    np.testing.assert_allclose(np.reshape(eng._renderer_object_ranges["Grid"][2], (4, 4)),
                               M_NEW)


def test_exporter_full_syncs_unranged_or_rescaled_or_refused_move():
    mod = _exporter_module()
    # No recorded range -> geometry promote -> full sync (pre-pkg291 behaviour).
    e, _ = _exporter_with_range(mod, M_OLD)
    dg = type("DG", (), {})()
    dg.scene = None
    dg.updates = [_Upd(_Obj("Other", M_NEW))]
    assert e._classify_depsgraph_domains(dg, None)[0] == "fallback"
    # >10 % volume-scale change: refit quality -> full sync (spec).
    e, _ = _exporter_with_range(mod, M_OLD)
    assert e._move_object_in_place(_StubRenderer(), "Grid",
                                   (M_OLD @ _rot_z(0, s=1.2)).reshape(-1).tolist()) is False
    # Engine refuses (emissive / motion): dispatch reports False -> full sync.
    e, _ = _exporter_with_range(mod, M_OLD)
    dg.updates = [_Upd(_Obj("Grid", M_NEW))]
    _status, changes, flat, refit = e._classify_depsgraph_domains(dg, None)
    assert not e._dispatch_dirty_domains(_StubRenderer(ok=False), dg, None, None, None,
                                         changes, flat, refit)
