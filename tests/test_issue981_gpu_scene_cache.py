"""Issue #981 - GPU device-scene cache across render() calls.

The wavefront driver used to re-flatten (buildSceneArrays) and re-upload the whole
scene on every render() that was not asserted unchanged by the caller
(skip_upload). It now keys the device scene, and the OptiX accel built from it,
on Renderer::getSceneVersion() (process-unique, bumped by every scene mutation)
plus the owning renderer, the GPU-traversal request, and the #801 invalidation
flag. last_render_info()["gpu_scene_reused"] reports whether the last render was
served from the cache.

A missed invalidation renders a stale scene, so every edit kind is exercised:
render, edit, render (must MISS, must differ where visible), render again (must
HIT and equal), then compare against a renderer built from scratch with the final
scene. Run on OptiX (default) and the software-BVH fallback
(ASTRORAY_GPU_TRAVERSAL=software). Same-seed images must agree within 1e-6.
"""
import os
import shutil
import subprocess

import numpy as np
import pytest

import runtime_setup  # configures sys.path + DLL dirs
runtime_setup.configure_test_imports()
import astroray

pytestmark = pytest.mark.gpu

W = H = 24
SPP, DEPTH, SEED = 4, 4, 11
HERE = os.path.dirname(os.path.abspath(__file__))
ENV_HDR = os.path.join(HERE, "..", "samples", "test_env.hdr")
MOVE = [1, 0, 0, 0.3, 0, 1, 0, 0.2, 0, 0, 1, 0, 0, 0, 0, 1]
UNMOVE = [1, 0, 0, -0.3, 0, 1, 0, -0.2, 0, 0, 1, 0, 0, 0, 0, 1]


@pytest.fixture(params=["optix", "software"], autouse=True)
def traversal(request, monkeypatch):
    monkeypatch.setenv("ASTRORAY_GPU_TRAVERSAL", request.param)
    return request.param


def _new():
    r = astroray.Renderer()
    if not r.gpu_available:
        pytest.skip("CUDA device not available")
    return r


def _tex_image(flip=False):
    img = np.zeros((2, 2, 3), dtype=np.float32)
    img[0, 0] = (0.9, 0.05, 0.05)
    img[0, 1] = (0.05, 0.9, 0.05)
    img[1, 0] = (0.05, 0.05, 0.9)
    img[1, 1] = (0.9, 0.9, 0.05)
    return img[::-1].copy() if flip else img


def _base(r=None, tex_quad=True):
    """Triangle-only scene (OptiX-eligible): floor, a blue triangle, a quad light, and
    (optionally) a textured quad. Returns (renderer, material ids)."""
    r = r or _new()
    r.setup_camera([0.0, 0.0, 4.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   40.0, 1.0, 0.0, 4.0, W, H)
    r.set_background_color([0.1, 0.1, 0.12])
    r.set_adaptive_sampling(False)
    r.load_texture("t981", _tex_image(), 2, 2, "UV")
    mats = {
        "grey": r.create_material("lambertian", [0.7, 0.7, 0.7], {}),
        "blue": r.create_material("lambertian", [0.1, 0.2, 0.9], {}),
        "light": r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 6.0}),
        "tex": r.create_material("lambertian", [0.5, 0.5, 0.5], {"texture": "t981"}),
    }
    r.add_triangle([-2, -1, -2], [2, -1, -2], [2, -1, 2], mats["grey"])       # obj 0
    r.add_triangle([-2, -1, -2], [2, -1, 2], [-2, -1, 2], mats["grey"])       # obj 1
    r.add_triangle([0.2, -0.8, 0.5], [1.4, -0.8, 0.5], [0.8, 0.6, 0.5], mats["blue"])  # obj 2
    r.add_triangle([-0.5, 1.9, -0.5], [0.5, 1.9, -0.5], [0.5, 1.9, 0.5], mats["light"])  # 3
    r.add_triangle([-0.5, 1.9, -0.5], [0.5, 1.9, 0.5], [-0.5, 1.9, 0.5], mats["light"])  # 4
    if tex_quad:
        A, B, C, D, n = [-1.6, -0.2, 0.2], [-0.6, -0.2, 0.2], [-0.6, 0.8, 0.2], [-1.6, 0.8, 0.2], [0, 0, 1]
        r.add_triangle_layers(A, B, C, mats["tex"], {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)  # 5
        r.add_triangle_layers(A, C, D, mats["tex"], {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)  # 6
    r.set_use_gpu(True)
    return r, mats


def _render(r):
    r.set_seed(SEED)
    return np.asarray(r.render(SPP, DEPTH, None, False), dtype=np.float32).copy()


def _reused(r):
    return bool(r.last_render_info()["gpu_scene_reused"])


def _same(a, b):
    assert a.shape == b.shape
    assert float(np.max(np.abs(a - b))) <= 1e-6


def _differs(a, b):
    assert float(np.max(np.abs(a - b))) > 1e-4, "edit not visible in the image"


def test_repeat_render_hits_cache_and_is_identical():
    r, _ = _base()
    a = _render(r)
    assert not _reused(r), "first render of a fresh scene cannot be a cache hit"
    b = _render(r)
    assert _reused(r), "unchanged scene was re-flattened and re-uploaded"
    c = _render(r)
    assert _reused(r)
    _same(a, b)
    _same(a, c)
    assert a.mean() > 0.01, "fixture renders black"


# ---- edit kinds: (mutate(renderer, mats), visible?) -------------------------
def _add_sphere(r, m):                      # also flips an OptiX-eligible scene to software
    r.add_sphere([0.9, 0.6, -0.5], 0.35, m["grey"])


def _add_triangle(r, m):
    r.add_triangle([-1.5, 0.0, -1.0], [-0.5, 0.0, -1.0], [-1.0, 1.0, -1.0], m["blue"])


def _add_bulk(r, m):
    pos = np.array([[[0.5, 0.2, -1.2], [1.5, 0.2, -1.2], [1.0, 1.2, -1.2]]], np.float32)
    r.add_triangles_bulk(pos, np.array([m["grey"]], np.int32), np.zeros(1, np.int32), 0,
                         np.zeros((0, 1, 3, 2), np.float32), [],
                         np.zeros((0, 3, 3), np.float32))


def _add_emissive_geometry(r, m):
    r.add_triangle([0.6, 1.2, 0.6], [1.2, 1.2, 0.6], [0.9, 1.7, 0.6], m["light"])


def _move_object(r, m):
    r.update_object_transform(2, MOVE)


def _material_rebind(r, m):
    new = r.create_material("lambertian", [0.1, 0.8, 0.1], {})
    assert r.rebind_material(m["blue"], new)
    r.upload_materials()


def _add_point_light(r, m):
    r.add_point_light([0.0, 1.0, 1.5], {"mode": "rgb", "color": [1.0, 0.9, 0.8]}, 20.0)


def _tree_sampler(r, m):
    r.set_light_sampler("tree")


def _texture_mapping(r, m):
    r.set_texture_mapping_matrix("t981", [2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 1, 0])


def _texture_extension(r, m):
    r.set_texture_extension("t981", "MIRROR")


def _texture_swap(r, m):
    r.load_texture("t981b", _tex_image(flip=True), 2, 2, "UV")
    new = r.create_material("lambertian", [0.5, 0.5, 0.5], {"texture": "t981b"})
    assert r.rebind_material(m["tex"], new)
    r.upload_materials()


def _environment(r, m):
    if not os.path.exists(ENV_HDR):
        pytest.skip("samples/test_env.hdr missing")
    assert r.load_environment_map(ENV_HDR, 1.0)


def _object_name(r, m):
    r.set_object_name(2, "renamed_for_981")


# (mutate, expect a visible change). Names/sampler edits change data but not (or only
# stochastically) the image; the cold-vs-fresh equality is still asserted.
EDITS = [
    (_add_sphere, True), (_add_triangle, True), (_add_bulk, True),
    (_add_emissive_geometry, True), (_move_object, True), (_material_rebind, True),
    (_add_point_light, True), (_tree_sampler, False), (_texture_mapping, True),
    (_texture_extension, False), (_texture_swap, True), (_environment, True),
    (_object_name, False),
]


@pytest.mark.parametrize("mutate,visible", EDITS, ids=[e[0].__name__ for e in EDITS])
def test_edit_misses_then_hits_and_matches_fresh(mutate, visible):
    r, m = _base()
    before = _render(r)
    _render(r)
    assert _reused(r)
    mutate(r, m)
    after = _render(r)
    assert not _reused(r), f"{mutate.__name__}: stale device scene served after an edit"
    if visible:
        _differs(after, before)
    again = _render(r)
    assert _reused(r), f"{mutate.__name__}: cache did not re-arm after the rebuild"
    _same(after, again)
    fresh, fm = _base()
    mutate(fresh, fm)
    _same(after, _render(fresh))   # cold render of the final scene == cached render


def test_light_removal_matches_fresh():
    r, m = _base()
    _add_point_light(r, m)
    with_light = _render(r)
    n = r.dedicated_light_count()
    r.remove_dedicated_lights(n - 1, 1)
    after = _render(r)
    assert not _reused(r)
    _differs(after, with_light)
    fresh, _ = _base()
    _same(after, _render(fresh))


def test_clear_and_smaller_scene_matches_fresh():
    """Object removal: clear() then rebuild a scene without the textured quad."""
    r, _ = _base()
    big = _render(r)
    r.clear()
    _base(r, tex_quad=False)
    after = _render(r)
    assert not _reused(r)
    _differs(after, big)
    fresh, _ = _base(tex_quad=False)
    _same(after, _render(fresh))


def _with_instance(r, m):
    mesh = r.register_mesh_triangles([[0, 0, 0, 0.5, 0, 0, 0, 0.5, 0]], m["grey"])
    return r.add_instance(mesh, [1, 0, 0, -0.2, 0, 1, 0, -0.9, 0, 0, 1, 0, 0, 0, 0, 1])


def test_add_instance_misses_and_matches_fresh():
    r, m = _base()
    before = _render(r)
    _with_instance(r, m)
    after = _render(r)
    assert not _reused(r)
    _differs(after, before)
    _same(after, _render(r))
    assert _reused(r)
    fresh, fm = _base()
    _with_instance(fresh, fm)
    _same(after, _render(fresh))


def test_instance_transform_misses_and_matches_fresh():
    r, m = _base()
    inst = _with_instance(r, m)
    before = _render(r)
    r.update_instance_transform(inst, MOVE)
    r.upload_instance_transforms()
    after = _render(r)
    assert not _reused(r)
    _differs(after, before)
    _same(after, _render(r))
    assert _reused(r)
    fresh, fm = _base()
    inst2 = _with_instance(fresh, fm)
    fresh.update_instance_transform(inst2, MOVE)
    _same(after, _render(fresh))


def test_other_renderer_evicts_cache():
    """One process-global device context: B's render must not serve A's scene and
    A's next render must rebuild (and still match)."""
    a, _ = _base()
    ia = _render(a)
    b, bm = _base()
    _add_sphere(b, bm)
    ib = _render(b)
    assert not _reused(b)
    ia2 = _render(a)
    assert not _reused(a), "A rendered from B's device scene"
    _same(ia, ia2)
    assert float(np.max(np.abs(ia - ib))) > 1e-4


def test_traversal_switch_rebuilds(monkeypatch):
    """The OptiX accel only exists for an OptiX-requested upload; flipping the
    request must not reuse a cache built under the other one."""
    r, _ = _base()
    monkeypatch.setenv("ASTRORAY_GPU_TRAVERSAL", "optix")
    _render(r)
    _render(r)
    assert _reused(r)
    monkeypatch.setenv("ASTRORAY_GPU_TRAVERSAL", "software")
    _render(r)
    assert not _reused(r)
    assert r.last_render_info()["gpu_traversal"] == "software"
    _render(r)
    assert _reused(r)


def _used_mb():
    smi = shutil.which("nvidia-smi")
    if not smi:
        pytest.skip("nvidia-smi not available")
    out = subprocess.run([smi, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, check=True).stdout.split()[0]
    return float(out)


def test_no_vram_growth_over_100_alternating_edits():
    r, m = _base()
    flip = [False]

    def edit_and_render():
        flip[0] = not flip[0]
        r.update_object_transform(2, MOVE if flip[0] else UNMOVE)   # geometry: full rebuild
        _render(r)
        assert not _reused(r)
        new = r.create_material("lambertian", [0.2, 0.7, 0.2] if flip[0] else [0.7, 0.2, 0.2], {})
        assert r.rebind_material(m["blue"], new)                   # material: full rebuild
        r.upload_materials()
        _render(r)
        assert not _reused(r)

    for _ in range(10):
        edit_and_render()
    base = _used_mb()
    for _ in range(50):          # 100 renders, every one a rebuild
        edit_and_render()
    growth = _used_mb() - base
    assert growth < 64.0, f"VRAM grew {growth:.0f} MB across 100 rebuilds"
