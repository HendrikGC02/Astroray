"""Issue #828 item 2 — GPU wavefront device-side grid cache.

Before #828 every ``render()`` re-uploaded every NanoVDB density buffer, even on
``render(skip_upload=True)`` (the #801 scene cache did not cover grids). Now the
density + temperature buffers ride the #801 reuse decision and every media
mutation (``set_volume_grid`` / ``add_homogeneous_medium`` / ``clear_grid_media``)
invalidates the cache.

The gate is the driver's own upload count, ``last_render_info()["grid_uploads"]``
(host->device grid buffer copies of the last GPU render; the key does not exist
before #828, so every test here fails on main):
  1. an upload render copies density + temperature (2); a following reuse
     render copies nothing (0) and renders the same image;
  2. ``set_volume_grid`` / ``add_homogeneous_medium`` after an upload force the
     next reuse render to re-upload (and match an upload render);
  3. ``clear_grid_media`` leaves nothing to upload and the medium is gone;
  4. on a grid-dominated scene the reuse path is measurably cheaper.
Images are compared with a float tolerance, not bit-exactly: with volumes the
wavefront's per-pixel accumulation order varies run to run (ulp-level).
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


def _uploads(r):
    return r.last_render_info()["grid_uploads"]


def _close(a, b):
    np.testing.assert_allclose(a, b, rtol=1e-4, atol=1e-6)


def test_reuse_render_uploads_no_grid_buffers():
    _gpu_or_skip()
    r = _scene()
    a = _render(r, skip_upload=False)
    assert _uploads(r) == 2, "upload render must copy density + temperature"
    b = _render(r, skip_upload=True)
    assert _uploads(r) == 0, "reuse render re-uploaded the grids (no device grid cache)"
    assert a.mean() > 0.01, "grid scene renders black -- fixture broken"
    _close(a, b)


def test_set_volume_grid_invalidates_the_cache():
    _gpu_or_skip()
    r = _scene()
    base = _render(r, skip_upload=False)
    _add_fire(r, T=3500.0, name="fire2", offset=(1.6, 0.0, -1.0))  # a second, hotter grid
    after_reuse = _render(r, skip_upload=True)
    assert _uploads(r) == 4, "set_volume_grid did not invalidate the grid cache"
    after_upload = _render(r, skip_upload=False)
    assert after_reuse.mean() > 1.05 * base.mean(), "second grid not rendered"
    _close(after_reuse, after_upload)


def test_add_homogeneous_medium_invalidates_the_cache():
    _gpu_or_skip()
    r = _scene()
    base = _render(r, skip_upload=False)
    r.add_homogeneous_medium([-3, -3, -3], [3, 3, -1.5], 0.0, [0, 0, 0], [1, 1, 1], 0.0,
                             emission_strength=2.0, emission_color=[0.2, 0.4, 1.0])
    after_reuse = _render(r, skip_upload=True)
    assert _uploads(r) == 2, "add_homogeneous_medium did not invalidate the grid cache"
    after_upload = _render(r, skip_upload=False)
    assert not np.allclose(base, after_reuse, rtol=1e-3), "new medium not rendered"
    _close(after_reuse, after_upload)


def test_clear_grid_media_invalidates_the_cache():
    _gpu_or_skip()
    r = _scene()
    base = _render(r, skip_upload=False)
    r.clear_grid_media()
    after_reuse = _render(r, skip_upload=True)
    assert _uploads(r) == 0
    after_upload = _render(r, skip_upload=False)
    assert after_reuse.mean() < 0.9 * base.mean(), "cleared medium still rendered"
    _close(after_reuse, after_upload)


def test_grid_reuse_is_cheaper_than_upload():
    """A dense 192^3 density + temperature pair is ~56 MB of host->device copy per
    upload render; the reuse path copies nothing. Measured 4.4 ms vs 0.7 ms
    (2026-09-20, RTX 5070 Ti); gate at 1.5x, min-of-7 against clock drift."""
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
        for _ in range(7):
            t = time.perf_counter()
            run(skip)
            ts.append(time.perf_counter() - t)
        return min(ts)

    t_upload = best(False)
    t_reuse = best(True)
    print(f"[#828] 192^3 grid 1 spp 16x16: upload {t_upload*1e3:.1f} ms, reuse {t_reuse*1e3:.1f} ms")
    assert t_reuse * 1.5 < t_upload, (t_upload, t_reuse)
