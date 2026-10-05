"""pkg315 (#1067) - material-domain device update.

A viewport material edit used to invalidate the whole device scene, so the next GPU
render re-flattened the geometry (host buildSceneArrays ~32 ms at 100k triangles).
It now invalidates only the material domain: the render rebuilds and uploads the
material arrays (buildMaterialDomain, the same producer the full build runs) and keeps
geometry, lights, environment and the OptiX accel. Anything the geometry arrays
depend on (slot order, per-slot UV gate / name hash / SMS class / hair routing /
emissive status, Object-coordinate bakes, a scene version bump) falls back to the
full re-flatten.

Gates (GPU): the material path renders BYTE-IDENTICAL to a forced full re-flatten
(same seed) for colour / texture swap / program-bearing / normal-map / texture-mapping
edits; each reachable guard takes the full path (asserted through
last_render_info()["gpu_material_domain_update"], not timing); the 100k edit costs
< 10 ms (rebind + next render, min of 5). CPU legs cover the rebind holder index.
"""
import time

import numpy as np
import pytest
import runtime_setup  # configures sys.path + DLL dirs

runtime_setup.configure_test_imports()
import astroray

W = H = 24
SPP, DEPTH, SEED = 4, 4, 11
MOVE = [1, 0, 0, 0.3, 0, 1, 0, 0.2, 0, 0, 1, 0, 0, 0, 0, 1]

# op-VM opcodes (mirror include/astroray/shader_vm.h; see test_issue825_826_opvm_gpu_inputs)
OP_LOAD_TEX, OP_LOAD_CONST, OP_MIX = 1, 2, 4
_IDENTITY_PROG = ([OP_LOAD_TEX, 0, 0, 0, 0, 0, 0, 0], [])
_MIX2_PROG = ([OP_LOAD_TEX, 0, 0, 0, 0, 0, 0, 0,
               OP_LOAD_TEX, 1, 0, 0, 0, 0, 0, 1,
               OP_LOAD_CONST, 2, 0, 0, 0, 0, 0, 0,
               OP_MIX, 3, 2, 0, 1, 0, 0, 0],
              [0.3, 0.3, 0.3])


@pytest.fixture(params=["optix", "software"])
def traversal(request, monkeypatch):
    monkeypatch.setenv("ASTRORAY_GPU_TRAVERSAL", request.param)
    return request.param


def _new_gpu():
    r = astroray.Renderer()
    if not r.gpu_available:
        pytest.skip("CUDA device not available")
    return r


def _rgby(flip=False):
    img = np.zeros((2, 2, 3), dtype=np.float32)
    img[0, 0] = (0.9, 0.05, 0.05)
    img[0, 1] = (0.05, 0.9, 0.05)
    img[1, 0] = (0.05, 0.05, 0.9)
    img[1, 1] = (0.9, 0.9, 0.05)
    return img[::-1].copy() if flip else img


def _normal_image(nx, ny, nz):
    v = np.asarray([nx, ny, nz], np.float32)
    v = v / np.linalg.norm(v)
    img = np.empty((2, 2, 3), np.float32)
    img[:] = v * 0.5 + 0.5
    return img


def _quad(r, mat, x0, x1, y0, y1, z):
    A, B, C, D, n = [x0, y0, z], [x1, y0, z], [x1, y1, z], [x0, y1, z], [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)


def _program(r, name, inputs, prog, num_tex):
    code, consts = prog
    r.create_program_texture(name, "UV")
    for child in inputs:
        r.program_texture_add_input(name, child)
    r.set_program_texture_program(name, num_tex, 3 if num_tex == 2 else 0, code, consts, [])


def _flat(img):
    return np.asarray(img, dtype=np.float32).reshape(-1).tolist()


def _scene(r=None):
    """Triangle-only (OptiX-eligible) scene with one material of every edit kind: plain
    colour (blue), emitter (light, must stay untouched), textured, program-bearing,
    normal-mapped. Returns (renderer, material ids)."""
    r = r or _new_gpu()
    r.setup_camera([0.0, 0.0, 4.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0], 40.0, 1.0, 0.0, 4.0, W, H)
    r.set_background_color([0.1, 0.1, 0.12])
    r.set_adaptive_sampling(False)
    r.load_texture("t315", _rgby(), 2, 2, "UV")
    r.load_texture("t315b", _rgby(flip=True), 2, 2, "UV")
    r.load_texture("n315", _normal_image(0.7071, 0.0, 0.7071), 2, 2, "UV")
    _program(r, "p315", ["t315"], _IDENTITY_PROG, 1)
    m = {
        "grey": r.create_material("lambertian", [0.7, 0.7, 0.7], {}),
        "blue": r.create_material("lambertian", [0.1, 0.2, 0.9], {}),
        "light": r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 6.0}),
        "tex": r.create_material("lambertian", [0.5, 0.5, 0.5], {"texture": "t315"}),
        "prog": r.create_material("lambertian", [0.5, 0.5, 0.5], {"texture": "p315"}),
        "nrm": r.create_material("lambertian", [0.8, 0.8, 0.8],
                                 {"normal_map_texture": "n315", "normal_strength": 1.0}),
    }
    r.set_material_name(m["blue"], "Blue")
    r.add_triangle([-2, -1, -2], [2, -1, -2], [2, -1, 2], m["grey"])               # obj 0
    r.add_triangle([-2, -1, -2], [2, -1, 2], [-2, -1, 2], m["grey"])               # obj 1
    r.add_triangle([0.2, -0.8, 0.5], [1.4, -0.8, 0.5], [0.8, 0.6, 0.5], m["blue"])  # obj 2
    r.add_triangle([-0.5, 1.9, -0.5], [0.5, 1.9, -0.5], [0.5, 1.9, 0.5], m["light"])
    r.add_triangle([-0.5, 1.9, -0.5], [0.5, 1.9, 0.5], [-0.5, 1.9, 0.5], m["light"])
    _quad(r, m["tex"], -1.6, -0.6, -0.2, 0.8, 0.2)
    _quad(r, m["prog"], 0.3, 1.3, 0.7, 1.5, 0.1)
    _quad(r, m["nrm"], -0.5, 0.5, -0.9, -0.1, 0.3)
    r.add_point_light([0.0, 1.0, 1.5], {"mode": "rgb", "color": [1.0, 0.9, 0.8]}, 20.0)
    r.set_use_gpu(True)
    return r, m


def _render(r):
    r.set_seed(SEED)
    return np.asarray(r.render(SPP, DEPTH, None, False), dtype=np.float32).copy()


def _info(r):
    i = r.last_render_info()
    return bool(i["gpu_scene_reused"]), bool(i["gpu_scene_patched"]), bool(i["gpu_material_domain_update"])


def _differs(a, b):
    assert float(np.max(np.abs(a - b))) > 1e-4, "edit not visible in the image"


# ---- edits that must take the material-domain path -----------------------------------
def _colour(r, m):
    new = r.create_material("lambertian", [0.1, 0.8, 0.1], {})
    r.set_material_name(new, "Blue")           # the viewport names a fresh material first
    assert r.rebind_material(m["blue"], new)
    r.upload_materials()


def _texture_swap(r, m):
    new = r.create_material("lambertian", [0.5, 0.5, 0.5], {"texture": "t315b"})
    assert r.rebind_material(m["tex"], new)
    r.upload_materials()


def _program_edit(r, m):
    _program(r, "p315b", ["t315", "t315b"], _MIX2_PROG, 2)
    new = r.create_material("lambertian", [0.5, 0.5, 0.5], {"texture": "p315b"})
    assert r.rebind_material(m["prog"], new)
    r.upload_materials()


def _normal_map_edit(r, m):
    r.load_texture("n315b", _normal_image(-0.7071, 0.0, 0.7071), 2, 2, "UV")
    new = r.create_material("lambertian", [0.8, 0.8, 0.8],
                            {"normal_map_texture": "n315b", "normal_strength": 0.6})
    assert r.rebind_material(m["nrm"], new)
    r.upload_materials()


def _texture_mapping_edit(r, m):
    r.set_texture_mapping_matrix("t315", [2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 1, 0])
    r.upload_materials()


MATERIAL_EDITS = [_colour, _texture_swap, _program_edit, _normal_map_edit, _texture_mapping_edit]


@pytest.mark.gpu
@pytest.mark.parametrize("mutate", MATERIAL_EDITS, ids=[e.__name__ for e in MATERIAL_EDITS])
def test_material_edit_is_byte_identical_to_full_reflatten(traversal, mutate):
    r, m = _scene()
    before = _render(r)
    _render(r)
    assert _info(r)[0], "unchanged scene was not served from the cache"
    mutate(r, m)
    after = _render(r)
    reused, patched, mat_update = _info(r)
    assert mat_update, f"{mutate.__name__}: took the full re-flatten, not the material domain"
    assert not reused and not patched
    _differs(after, before)
    again = _render(r)                      # the cache re-arms after the material rebuild
    assert _info(r)[0] and not _info(r)[2]
    assert np.array_equal(after, again, equal_nan=True)
    r.upload_lights()                       # scene-domain invalidation: forced full re-flatten
    full = _render(r)
    reused, patched, mat_update = _info(r)
    assert not reused and not patched and not mat_update, "reference did not re-flatten"
    assert np.array_equal(after, full, equal_nan=True), (
        f"{mutate.__name__}: material path differs from the full re-flatten, "
        f"max |diff| {float(np.nanmax(np.abs(after - full))):.3g}")


@pytest.mark.gpu
def test_repeated_material_edits_stay_on_material_path(traversal):
    """A burst of edits to the same material id (the viewport pattern) keeps hitting
    the material domain and keeps matching a full re-flatten."""
    r, m = _scene()
    _render(r)
    for k in range(4):
        new = r.create_material("lambertian", [0.1 + 0.2 * k, 0.5, 0.2], {})
        r.set_material_name(new, "Blue")
        assert r.rebind_material(m["blue"], new)
        r.upload_materials()
        img = _render(r)
        assert _info(r)[2], f"edit {k} left the material domain"
    r.upload_lights()
    assert np.array_equal(img, _render(r), equal_nan=True)


# ---- guards: the full path ---------------------------------------------------------------
def _uv_gate_flip(r, m):                    # plain -> textured: per-triangle hasUV / uv upload
    new = r.create_material("lambertian", [0.5, 0.5, 0.5], {"texture": "t315"})
    r.set_material_name(new, "Blue")           # same name: isolate the UV gate
    assert r.rebind_material(m["blue"], new)
    r.upload_materials()


def _slot_collapse(r, m):                   # two slots become one: slot order / count changes
    assert r.rebind_material(m["blue"], m["grey"])
    r.upload_materials()


def _name_change(r, m):                     # stamped per-triangle materialHash changes
    new = r.create_material("lambertian", [0.1, 0.8, 0.1], {})
    r.set_material_name(new, "SomethingElse")
    assert r.rebind_material(m["blue"], new)
    r.upload_materials()


def _rename_in_use(r, m):                   # materialHash of every holder
    r.set_material_name(m["blue"], "RenamedInUse")


def _glass_class(r, m):                     # SMS caster class (transmissive, ior > 1)
    new = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})
    r.set_material_name(new, "Blue")
    assert r.rebind_material(m["blue"], new)
    r.upload_materials()


def _hair_routing(r, m):                    # hair routing flag (c_hasHair)
    new = r.create_material("principled_hair", [0.5, 0.3, 0.1], {})
    r.set_material_name(new, "Blue")
    assert r.rebind_material(m["blue"], new)
    r.upload_materials()


def _geometry_plus_material(r, m):          # scene version bump alongside the material edit
    r.update_object_transform(2, MOVE)
    _colour(r, m)


def _scene_invalidation_wins(r, m):
    _colour(r, m)
    r.upload_lights()


GUARDS = [_uv_gate_flip, _slot_collapse, _name_change, _rename_in_use, _glass_class,
          _hair_routing, _geometry_plus_material, _scene_invalidation_wins]


@pytest.mark.gpu
@pytest.mark.parametrize("mutate", GUARDS, ids=[g.__name__ for g in GUARDS])
def test_guard_takes_the_full_path_and_matches_fresh(traversal, mutate):
    r, m = _scene()
    _render(r)
    _render(r)
    mutate(r, m)
    after = _render(r)
    reused, _, mat_update = _info(r)
    assert not mat_update, f"{mutate.__name__}: guard did not fall back to the full re-flatten"
    assert not reused
    fresh, fm = _scene()
    mutate(fresh, fm)
    assert np.array_equal(after, _render(fresh), equal_nan=True), (
        f"{mutate.__name__}: cached full path differs from a cold render of the final scene")


@pytest.mark.gpu
def test_naming_a_fresh_material_does_not_invalidate_the_scene():
    """The viewport names a freshly converted material BEFORE rebinding it; that must
    not force the full path (nothing references the new material yet)."""
    r, m = _scene()
    _render(r)
    _render(r)
    assert _info(r)[0]
    new = r.create_material("lambertian", [0.1, 0.8, 0.1], {})
    r.set_material_name(new, "Blue")
    _render(r)
    assert _info(r) == (True, False, False), "naming an unreferenced material dropped the cache"
    assert r.rebind_material(m["blue"], new)
    r.upload_materials()
    _render(r)
    assert _info(r)[2]


# ---- 100k timing probe -------------------------------------------------------------------
def _grid_scene(n):
    r = _new_gpu()
    r.set_background_color([0.5, 0.6, 0.8])
    mat = r.create_material("disney", [0.8, 0.2, 0.2], {"roughness": 0.4})
    xs = np.linspace(-2, 2, n + 1, dtype=np.float32)
    x0, y0 = np.meshgrid(xs[:-1], xs[:-1], indexing="ij")
    x1, y1 = np.meshgrid(xs[1:], xs[1:], indexing="ij")
    z = np.zeros_like(x0)
    a, b, c, d = (np.stack(p, -1).reshape(-1, 3) for p in
                  ((x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)))
    pos = np.concatenate([np.stack([a, b, c], 1), np.stack([a, c, d], 1)]).astype(np.float32)
    cnt = len(pos)
    r.add_triangles_bulk(pos, np.full(cnt, mat, np.int32), np.zeros(cnt, np.int32), 0,
                         np.zeros((0, cnt, 3, 2), np.float32), [], np.zeros((0, 3, 3), np.float32))
    wd, ht = 2100 // 4, 1221 // 4
    r.setup_camera([0, -3, 3], [0, 0, 0], [0, 0, 1], 45.0, wd / ht, 0.0, 4.0, wd, ht)
    return r, mat


@pytest.mark.gpu
def test_100k_material_edit_under_10ms():
    r, mat = _grid_scene(224)                       # 2*224^2 = 100,352 triangles
    r.set_seed(SEED)

    def render():
        r.render(1, 4, None, False)

    render()
    render()
    mat_ms, full_ms = [], []
    for k in range(5):
        new = r.create_material("disney", [0.2 + 0.05 * k, 0.5, 0.2], {"roughness": 0.4})
        t0 = time.perf_counter()
        assert r.rebind_material(mat, new)
        r.upload_materials()
        render()
        mat_ms.append((time.perf_counter() - t0) * 1e3)
        assert _info(r)[2], "100k edit left the material domain"
    for k in range(5):
        new = r.create_material("disney", [0.7 - 0.05 * k, 0.5, 0.2], {"roughness": 0.4})
        t0 = time.perf_counter()
        assert r.rebind_material(mat, new)
        r.upload_lights()                           # forces the full re-flatten reference
        render()
        full_ms.append((time.perf_counter() - t0) * 1e3)
        assert not _info(r)[2]
    print(f"[pkg315] 100k tris, rebind+render: material domain min {min(mat_ms):.1f} ms "
          f"(all {np.round(mat_ms, 1).tolist()}), full re-flatten min {min(full_ms):.1f} ms")
    assert min(mat_ms) < 10.0, mat_ms


# ---- CPU legs: the rebind holder index ----------------------------------------------------
def _cpu_scene():
    r = astroray.Renderer()
    r.set_use_gpu(False)
    r.setup_camera([0.0, 0.0, 4.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0], 40.0, 1.0, 0.0, 4.0, 16, 16)
    r.set_background_color([0.8, 0.8, 0.8])
    r.set_adaptive_sampling(False)
    r.set_seed(SEED)
    red = r.create_material("lambertian", [0.9, 0.1, 0.1], {})
    other = r.create_material("lambertian", [0.1, 0.1, 0.9], {})
    r.add_sphere([0.0, 0.0, 0.0], 0.8, red)
    r.add_sphere([2.5, 0.0, 0.0], 0.8, other)
    return r, red, other


def _cpu_render(r):
    r.set_seed(SEED)
    return np.asarray(r.render(8, 3, None, False), dtype=np.float32).copy()


def test_rebind_chain_follows_the_holder_index_cpu():
    """Successive rebinds of one id (index entry moved each time), then a scene
    mutation (index rebuilt), then another rebind: always the latest colour."""
    r, red, _ = _cpu_scene()
    base = _cpu_render(r)
    imgs = []
    for col in ([0.1, 0.9, 0.1], [0.9, 0.9, 0.1], [0.1, 0.9, 0.9]):
        new = r.create_material("lambertian", col, {})
        assert r.rebind_material(red, new)
        imgs.append(_cpu_render(r))
    assert float(np.abs(imgs[0] - base).max()) > 1e-3
    assert float(np.abs(imgs[1] - imgs[0]).max()) > 1e-3
    assert float(np.abs(imgs[2] - imgs[1]).max()) > 1e-3
    # scene mutation bumps the version: the index is rebuilt and still finds every holder
    extra = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
    r.add_sphere([0.0, 1.5, 0.0], 0.4, extra)
    new = r.create_material("lambertian", [0.9, 0.5, 0.1], {})
    assert r.rebind_material(red, new)
    r2, fred, _ = _cpu_scene()
    r2.add_sphere([0.0, 1.5, 0.0], 0.4, r2.create_material("lambertian", [0.5, 0.5, 0.5], {}))
    n2 = r2.create_material("lambertian", [0.9, 0.5, 0.1], {})
    assert r2.rebind_material(fred, n2)
    np.testing.assert_array_equal(_cpu_render(r), _cpu_render(r2))


def test_rebind_to_an_in_use_material_collapses_holders_cpu():
    r, red, other = _cpu_scene()
    assert r.rebind_material(red, other)       # both spheres now share one material
    img = _cpu_render(r)
    fresh, fred, fother = _cpu_scene()
    fresh.rebind_material(fred, fother)
    np.testing.assert_array_equal(img, _cpu_render(fresh))
