"""Issue #828 item 2 — GPU wavefront device-side grid cache.

Before #828 every ``render()`` re-uploaded every NanoVDB density buffer, even on
``render(skip_upload=True)`` (the #801 scene cache did not cover grids). Now the
density + temperature buffers ride the #801 reuse decision and every media
mutation (``set_volume_grid`` / ``add_homogeneous_medium`` / ``clear_grid_media``)
invalidates the cache.

Contract (style of tests/test_issue801_wavefront_scene_cache.py):
  1. a reuse render of a grid scene is byte-identical to an upload render;
  2. ``set_volume_grid`` after an upload invalidates: the next reuse render shows
     the new medium and equals an upload render;
  3. ``clear_grid_media`` invalidates the same way;
  4. on a grid-dominated scene the reuse path is measurably cheaper.
"""
import time

import numpy as np
import pytest

import runtime_setup  # noqa: F401

astroray = pytest.importorskip("astroray")

pytestmark = pytest.mark.gpu

W, H = 48, 48
SEED = 828


def _gpu_or_skip():
    if not astroray.Renderer().gpu_available:
        pytest.skip("CUDA device not available")


def _xform(n, offset=(0.0, 0.0, 0.0)):
    vox = 2.0 / n
    ox, oy, oz = offset
    return ([vox, 0, 0, -1.0, 0, vox, 0, -1.0, 0, 0, vox, -1.0, 0, 0, 0, 1],
            [1, 0, 0, ox, 0, 1, 0, oy, 0, 0, 1, oz, 0, 0, 0, 1])


def _ball(n, scale=1.0):
    z, y, x = np.mgrid[0:n, 0:n, 0:n].astype(np.float32)
    c = (n - 1) / 2.0
    r2 = ((x - c) ** 2 + (y - c) ** 2 + (z - c) ** 2) / (c * c)
    return np.ascontiguousarray((np.clip(1.0 - r2, 0.0, 1.0) * scale).astype(np.float32))


def _add_fire(r, n=24, T=1600.0, name="fire", offset=(0.0, 0.0, 0.0)):
    i2o, o2w = _xform(n, offset)
    r.set_volume_grid(name, _ball(n), [0, 0, 0], i2o, o2w, density_scale=3.0,
                      color=[0.8, 0.7, 0.6], absorption_color=[0.5, 0.5, 0.5],
                      anisotropy=0.2, temperature=_ball(n),
                      blackbody_intensity=1.0, blackbody_temperature=T)


def _scene(n=24):
    r = astroray.Renderer()
    r.set_background_color([0.02, 0.02, 0.03])
    r.set_integrator("path_tracer")
    lamp = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 20.0})
    r.add_sphere([2.0, 3.0, 2.0], 0.5, lamp)
    _add_fire(r, n)
    r.setup_camera([0, 0, 4.0], [0, 0, 0], [0, 1, 0], 40.0, W / H, 0.0, 4.0, W, H)
    r.set_use_gpu(True)
    r.set_seed(SEED)
    return r


def _render(r, spp=4, skip_upload=False):
    img = np.asarray(r.render(spp, 6, None, False, -1, -1, -1, -1, -1, skip_upload),
                     dtype=np.float32)
    return img.reshape(H, W, 3) if img.ndim == 1 else img


def test_grid_reuse_is_byte_identical_to_upload():
    _gpu_or_skip()
    r = _scene()
    a = _render(r, skip_upload=False)
    b = _render(r, skip_upload=True)
    c = _render(r, skip_upload=False)
    assert a.mean() > 0.01, "grid scene renders black -- fixture broken"
    np.testing.assert_array_equal(a, b)
    np.testing.assert_array_equal(a, c)


def test_set_volume_grid_invalidates_the_cache():
    _gpu_or_skip()
    r = _scene()
    base = _render(r, skip_upload=False)
    _add_fire(r, T=3500.0, name="fire2", offset=(1.6, 0.0, -1.0))  # a second, hotter grid
    after_reuse = _render(r, skip_upload=True)
    after_upload = _render(r, skip_upload=False)
    assert not np.array_equal(base, after_reuse), "stale cached grid after set_volume_grid()"
    np.testing.assert_array_equal(after_reuse, after_upload)


def test_clear_grid_media_invalidates_the_cache():
    _gpu_or_skip()
    r = _scene()
    base = _render(r, skip_upload=False)
    r.clear_grid_media()
    after_reuse = _render(r, skip_upload=True)
    after_upload = _render(r, skip_upload=False)
    assert after_reuse.mean() < 0.5 * base.mean(), "cleared medium still rendered from the cache"
    np.testing.assert_array_equal(after_reuse, after_upload)


def test_add_homogeneous_medium_invalidates_the_cache():
    _gpu_or_skip()
    r = _scene()
    base = _render(r, skip_upload=False)
    r.add_homogeneous_medium([-3, -3, -3], [3, 3, -1.5], 0.0, [0, 0, 0], [1, 1, 1], 0.0,
                             emission_strength=2.0, emission_color=[0.2, 0.4, 1.0])
    after_reuse = _render(r, skip_upload=True)
    after_upload = _render(r, skip_upload=False)
    assert not np.array_equal(base, after_reuse), "stale cache after add_homogeneous_medium()"
    np.testing.assert_array_equal(after_reuse, after_upload)


def test_grid_reuse_is_cheaper_than_upload():
    """A dense 192^3 density + temperature pair is ~56 MB of host->device copy per
    upload render; the reuse path copies nothing (min-of-N, clock drift)."""
    _gpu_or_skip()
    n = 192
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_integrator("path_tracer")
    i2o, o2w = _xform(n)
    dense = np.full((n, n, n), 0.05, dtype=np.float32)   # every voxel active
    r.set_volume_grid("big", dense, [0, 0, 0], i2o, o2w, density_scale=0.5,
                      temperature=dense, blackbody_intensity=1.0,
                      blackbody_temperature=20000.0)
    r.setup_camera([0, 0, 4.0], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 16, 16)
    r.set_use_gpu(True)
    r.set_seed(SEED)

    def run(skip):
        r.render(1, 2, None, False, -1, -1, -1, -1, -1, skip)

    run(False)  # warm-up (first upload, LUT upload, kernel load)

    def best(skip):
        ts = []
        for _ in range(5):
            t = time.perf_counter()
            run(skip)
            ts.append(time.perf_counter() - t)
        return min(ts)

    t_upload = best(False)
    t_reuse = best(True)
    print(f"[#828] 192^3 grid 1 spp 16x16: upload {t_upload*1e3:.1f} ms, reuse {t_reuse*1e3:.1f} ms")
    assert t_reuse * 1.5 < t_upload, (t_upload, t_reuse)
