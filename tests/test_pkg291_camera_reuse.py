"""pkg291: setup_camera re-aims a same-size Camera instead of reallocating its
per-pixel buffers (~1 GB at 2100x1221; the dominant viewport commit cost).

A fresh Camera started with zeroed buffers; a re-aimed one keeps the previous
render's contents, so every render must overwrite or clear what it exposes. The
CPU render-region path clears outside the rect -- including the cryptomatte /
bounce / sample-weight / motion buffers it used to leave alone (Terra review of
pkg291). A re-aimed camera must also render exactly like a freshly built one.
"""
import numpy as np

import base_helpers as bh


def _scene(r=None):
    r = r or bh.create_renderer()
    r.set_seed(777)
    bh.create_cornell_box(r)
    return r


def _aim(r, look_from):
    bh.setup_camera(r, look_from=look_from, look_at=[0, 0, 0], vfov=40, width=64, height=64)


def test_reaimed_camera_renders_like_a_fresh_one():
    a = _scene()
    _aim(a, [0.4, 0.0, 5.5])
    bh.render_image(a, samples=4, max_depth=3, apply_gamma=False)
    _aim(a, [0.0, 0.0, 5.5])                     # same size -> re-aimed in place
    a.set_seed(777)
    img_a = bh.render_image(a, samples=4, max_depth=3, apply_gamma=False)
    b = _scene()
    _aim(b, [0.0, 0.0, 5.5])                     # fresh Camera
    b.set_seed(777)
    img_b = bh.render_image(b, samples=4, max_depth=3, apply_gamma=False)
    assert np.array_equal(img_a, img_b)


def test_region_render_on_reused_camera_clears_every_buffer_outside():
    r = _scene()
    r.set_cryptomatte_enabled(True)
    _aim(r, [0.0, 0.0, 5.5])
    bh.render_image(r, samples=2, max_depth=3, apply_gamma=False)  # populate everything
    x0, y0, x1, y1 = 16, 16, 48, 48
    full_crypto = np.asarray(r.get_cryptomatte_object_buffer()).copy()
    outside = np.ones((64, 64), dtype=bool)
    outside[y0:y1, x0:x1] = False
    assert np.any(full_crypto[outside] != 0.0), "fixture: crypto must be populated"
    _aim(r, [0.0, 0.0, 5.5])                     # same size -> buffers kept
    r.set_render_region(x0, y0, x1, y1)
    bh.render_image(r, samples=2, max_depth=3, apply_gamma=False)
    for name in ("get_cryptomatte_object_buffer", "get_cryptomatte_material_buffer",
                 "get_object_index_buffer", "get_material_index_buffer"):
        buf = np.asarray(getattr(r, name)())
        assert not np.any(buf[outside] != 0.0), f"{name} kept stale data outside the region"
