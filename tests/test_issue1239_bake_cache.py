"""Issue #1239 - GPU procedural bakes survive across renders (cross-render bake cache).

#1229 raised a UV procedural bake from 64^2 to 1024^2 (about 50-100 ms of CPU
evaluation per Noise / Wave / warped card). Any material edit re-ran the producer,
so an unrelated edit re-baked every card (614 ms for six). The bake cache keys a
bake on the texture's content identity (process-unique uid + mutation counter of the
texture and of every child it reads), its Mapping / UV transform, coordinate mode and
resolution; a material-only update also keeps the device texel buffer when the blocks
are unchanged (pkg315 path, now taken for textured emitters too).

The dangerous failure is a STALE bake: an in-place texture edit served from the cache.
Every mutator is exercised and compared against a renderer built from scratch with the
final texture state (same seed, 1e-6), the pattern of tests/test_issue981_gpu_scene_cache.py.
last_render_info() reports the bake activity of the last render:
gpu_bake_hits / gpu_bake_misses / gpu_bake_ms / gpu_bake_cache_mb / gpu_texels_reused.
GPU-gated (CI has no CUDA device).
"""
import gc
import os

import numpy as np
import pytest
import runtime_setup  # configures sys.path + DLL dirs

runtime_setup.configure_test_imports()
import astroray

pytestmark = pytest.mark.gpu

W = 48
SPP, DEPTH, SEED = 4, 2, 7
LO, HI = (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
ROT20 = np.radians(20.0)
MAP_BEFORE = [5 * np.cos(ROT20), -3 * np.sin(ROT20), 0, 0, 5 * np.sin(ROT20), 3 * np.cos(ROT20), 0, 0, 0, 0, 1, 0]
CARDS = ("noise", "voronoi", "checker", "map_before")


@pytest.fixture(params=["optix", "software"], autouse=True)
def traversal(request, monkeypatch):
    monkeypatch.setenv("ASTRORAY_GPU_TRAVERSAL", request.param)
    return request.param


def _tex(r, kind):
    if kind == "noise":
        r.create_procedural_texture("n", "noise_perlin", [6.0, 2.0, 0.5, 2.0, 0.0, 1.0, 0.0, 0, 1], "UV")
        return "n"
    if kind == "voronoi":
        r.create_procedural_texture("v", "voronoi", [5.0, 1.0, 0, 0, 1.0, *LO, *HI, 0.0, 0.5, 2.0, 0.5, 0.0, 1.0], "UV")
        return "v"
    if kind == "checker":
        r.create_procedural_texture("c", "checker", [0.9, 0.85, 0.2, 0.1, 0.15, 0.6, 6.0], "UV")
        return "c"
    r.create_procedural_texture("cm", "checker", [0.9, 0.85, 0.2, 0.1, 0.15, 0.6, 1.0], "UV")
    r.set_texture_mapping_matrix("cm", [float(x) for x in MAP_BEFORE])
    return "cm"


def _scene(cards=CARDS, edit_rgb=(0.5, 0.5, 0.5), mutate=None):
    """UV-mapped emission cards (always baked on GPU, #962) + an unrelated lambertian
    triangle behind them + a point light. `mutate(renderer)` runs after the textures exist."""
    r = astroray.Renderer()
    if not r.gpu_available:
        pytest.skip("CUDA device not available")
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)
    r.set_use_gpu(True)
    r.set_background_color([0.0, 0.0, 0.0])
    n = len(cards)
    names = [_tex(r, k) for k in cards]
    if mutate:
        mutate(r)
    for k, tex in enumerate(names):
        m = r.create_material("light", [1, 1, 1], {"intensity": 1.0, "texture": tex})
        x0 = -1.0 + 2.0 * k / n
        x1 = x0 + 1.8 / n
        a, b, c, d = [x0, -0.4, 0], [x1, -0.4, 0], [x1, 0.4, 0], [x0, 0.4, 0]
        nn = [0, 0, 1]
        r.add_triangle_layers(a, b, c, m, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, nn, nn, nn)
        r.add_triangle_layers(a, c, d, m, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, nn, nn, nn)
    edit = r.create_material("lambertian", list(edit_rgb), {})
    r.add_triangle([-1, -1, -0.5], [1, -1, -0.5], [1, 1, -0.5], edit)
    r.add_point_light([0.0, 0.0, 2.0], {"mode": "rgb", "color": [1, 1, 1]}, 5.0)
    r.setup_camera([0.0, 0.0, 2.5], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0], 50.0, 1.0, 0.0, 2.5, W, W)
    return r, edit


def _render(r):
    r.set_seed(SEED)
    px = np.asarray(r.render(SPP, DEPTH, None, False), dtype=np.float32).copy()
    return px


def _info(r):
    i = r.last_render_info()
    return {k: i[k] for k in ("gpu_scene_reused", "gpu_material_domain_update", "gpu_bake_hits",
                              "gpu_bake_misses", "gpu_bake_ms", "gpu_bake_cache_mb", "gpu_texels_reused")}


def _same(a, b):
    assert a.shape == b.shape
    assert float(np.max(np.abs(a - b))) <= 1e-6


def _differs(a, b):
    assert float(np.max(np.abs(a - b))) > 1e-4, "edit not visible in the image"


def _edit_unrelated(r, edit, rgb=(0.6, 0.4, 0.4)):
    new = r.create_material("lambertian", list(rgb), {})
    assert r.rebind_material(edit, new)
    r.upload_materials()


def test_first_render_bakes_every_card_and_repeat_is_free():
    r, _ = _scene()
    px = _render(r)
    i = _info(r)
    assert i["gpu_bake_misses"] == len(CARDS) and i["gpu_bake_hits"] == 0, i
    assert i["gpu_bake_ms"] > 0.0 and px.mean() > 1e-3
    _render(r)
    i = _info(r)
    assert i["gpu_scene_reused"] and i["gpu_bake_misses"] == 0 and i["gpu_bake_hits"] == 0, i
    r.setup_camera([0.2, 0.1, 2.4], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0], 50.0, 1.0, 0.0, 2.5, W, W)
    _render(r)                                  # camera move: the device scene is reused, no bake
    i = _info(r)
    assert i["gpu_scene_reused"] and i["gpu_bake_misses"] == 0 and i["gpu_bake_ms"] == 0.0, i


def test_unrelated_material_edit_uploads_no_bakes_and_matches_fresh():
    r, edit = _scene()
    _render(r)
    _edit_unrelated(r, edit)
    after = _render(r)
    i = _info(r)
    assert i["gpu_material_domain_update"], f"emitter textures forced the full re-flatten: {i}"
    assert i["gpu_texels_reused"], f"the device texel buffer was re-uploaded: {i}"
    assert i["gpu_bake_misses"] == 0, i
    assert i["gpu_bake_ms"] <= 15.0, i
    fresh, _ = _scene(edit_rgb=(0.6, 0.4, 0.4))
    _same(after, _render(fresh))


def test_editing_a_textured_card_rebakes_only_its_own_texture():
    r, _ = _scene()
    before = _render(r)
    r.set_texture_mapping_matrix("n", [2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 1, 0])
    after = _render(r)
    i = _info(r)
    # One bake in total. The other cards are cache hits; a material-domain attempt that
    # the emitter-mean guard rejects and the full rebuild after it each look them up.
    assert i["gpu_bake_misses"] == 1 and i["gpu_bake_hits"] >= len(CARDS) - 1, i
    _differs(after, before)


def _mapping(r):
    r.set_texture_mapping_matrix("n", [2, 0, 0, 0.25, 0, 3, 0, 0, 0, 0, 1, 0])


def _uv_transform(r):
    r.set_texture_uv_transform("c", 2.0, 2.0, 0.1, 0.1, 0.3)


def _mapping_on_mapped(r):
    r.set_texture_mapping_matrix("cm", [float(x) * 1.5 for x in MAP_BEFORE])


# The legacy UV transform never moves the procedural point p (the evaluators read p), so
# on a procedural it changes nothing visible: its version bump is still checked below.
@pytest.mark.parametrize("mutate,visible", [(_mapping, True), (_uv_transform, False),
                                            (_mapping_on_mapped, True)],
                         ids=["_mapping", "_uv_transform", "_mapping_on_mapped"])
def test_in_place_texture_edit_is_not_served_stale(mutate, visible):
    """The dangerous failure: a cached bake outliving an in-place edit."""
    r, _ = _scene()
    before = _render(r)
    mutate(r)
    after = _render(r)
    i = _info(r)
    assert i["gpu_bake_misses"] >= 1, f"{mutate.__name__}: edited texture served from the bake cache: {i}"
    if visible:
        _differs(after, before)
    again = _render(r)
    _same(after, again)
    fresh, _ = _scene(mutate=mutate)
    _same(after, _render(fresh))


def test_revert_after_edit_returns_the_original_image():
    r, _ = _scene()
    before = _render(r)
    r.set_texture_mapping_matrix("c", [3, 0, 0, 0.1, 0, 2, 0, 0, 0, 0, 1, 0])
    _differs(_render(r), before)
    r.set_texture_mapping_matrix("c", [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0])
    back = _render(r)
    assert _info(r)["gpu_bake_misses"] >= 1       # the version moved on twice: no ABA hit
    _same(back, before)


def test_cache_is_bounded_and_forgets_gone_textures():
    r, _ = _scene()
    _render(r)
    assert _info(r)["gpu_bake_cache_mb"] >= len(CARDS) * 12.0 * 0.99
    del r
    gc.collect()
    for _ in range(6):                            # full builds that bake nothing: old entries age out
        s, _ = _scene(cards=())
        _render(s)
        del s
        gc.collect()
    assert _info_cache_mb() < 1.0


def _info_cache_mb():
    s, _ = _scene(cards=())
    _render(s)
    return s.last_render_info()["gpu_bake_cache_mb"]
