"""Batch A item 4 (#802) — Render Region.

CPU: a bordered render reproduces the SAME pixels of an unbordered render inside
the rect (bit-identical, same seed -> same per-tile RNG) and leaves the outside
at 0/alpha 0; wall time scales roughly with the region area.
GPU: a wavefront parity check (marked gpu) — inside pixels match the full render,
outside pixels are 0.
Addon: `_apply_render_region` maps Blender's bottom-up normalized border to the
engine's top-down pixel rect.
"""
import time
import types

import numpy as np
import pytest
from _batch_a_stub import RecordingRenderer, load_addon


def _scene(width, height, seed=777, gpu=False):
    import base_helpers as bh
    r = bh.create_renderer()
    if gpu:
        r.set_use_gpu(True)
    r.set_seed(seed)
    bh.create_cornell_box(r)
    bh.setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=40,
                    width=width, height=height)
    return r


# --------------------------------------------------------------------------- #
# CPU correctness: inside identical, outside zero.
# --------------------------------------------------------------------------- #
@pytest.mark.serial
def test_cpu_region_inside_identical_outside_zero():
    import base_helpers as bh
    # Tile-aligned bounds (16 px tiles): fully-inside tiles run the same
    # per-tile RNG stream as the full render, so inside pixels are bit-identical.
    # (A partial edge tile skips its outside pixels' RNG draws, which perturbs
    # the stream for the tile's inside pixels -- still correct, but only "within
    # noise" identical, per the issue's "same seed -> ideally identical".)
    W = H = 128
    x0, y0, x1, y1 = 32, 48, 80, 96

    r_full = _scene(W, H, seed=777)
    img_full = bh.render_image(r_full, samples=16, max_depth=4, apply_gamma=False)

    r_reg = _scene(W, H, seed=777)
    r_reg.set_render_region(x0, y0, x1, y1)
    img_reg = bh.render_image(r_reg, samples=16, max_depth=4, apply_gamma=False)

    inside_full = img_full[y0:y1, x0:x1]
    inside_reg = img_reg[y0:y1, x0:x1]
    # Same seed => same tile RNG => the inside pixels are bit-identical.
    assert np.array_equal(inside_reg, inside_full), (
        "inside-region pixels diverged: max abs diff %g"
        % float(np.max(np.abs(inside_reg - inside_full))))

    # Outside the rect: exactly 0.
    mask = np.ones((H, W), dtype=bool)
    mask[y0:y1, x0:x1] = False
    assert np.all(img_reg[mask] == 0.0), (
        "outside-region pixels are not zero: max %g"
        % float(np.max(img_reg[mask])))


@pytest.mark.serial
def test_cpu_region_wall_time_scales_with_area():
    import base_helpers as bh
    W = H = 128
    # A quarter-area region should be materially cheaper than the full frame.
    x0, y0, x1, y1 = 32, 32, 96, 96  # 1/4 of the film

    r_full = _scene(W, H, seed=5)
    t0 = time.perf_counter()
    bh.render_image(r_full, samples=64, max_depth=5, apply_gamma=False)
    full_t = time.perf_counter() - t0

    r_reg = _scene(W, H, seed=5)
    r_reg.set_render_region(x0, y0, x1, y1)
    t0 = time.perf_counter()
    bh.render_image(r_reg, samples=64, max_depth=5, apply_gamma=False)
    reg_t = time.perf_counter() - t0

    # Loose bound: the quarter-region render must be clearly faster than full.
    assert reg_t < full_t * 0.85, (reg_t, full_t)


@pytest.mark.serial
def test_cpu_clear_region_restores_full_frame():
    import base_helpers as bh
    W = H = 64
    r = _scene(W, H, seed=9)
    r.set_render_region(10, 10, 30, 30)
    r.clear_render_region()
    img = bh.render_image(r, samples=8, max_depth=3, apply_gamma=False)
    # With the region cleared, the corners are rendered (Cornell walls), not 0.
    assert float(np.mean(img)) > 0.0
    assert float(np.max(img[:5, :5])) > 0.0


# --------------------------------------------------------------------------- #
# GPU parity.
# --------------------------------------------------------------------------- #
@pytest.mark.gpu
@pytest.mark.serial
def test_gpu_region_matches_full_inside_zero_outside():
    import base_helpers as bh
    W = H = 96
    x0, y0, x1, y1 = 24, 24, 72, 72
    try:
        r_full = _scene(W, H, seed=321, gpu=True)
    except Exception as e:  # noqa: BLE001 - no GPU / not compiled
        pytest.skip("GPU unavailable: %s" % e)
    if not getattr(r_full, "gpu_available", False):
        pytest.skip("gpu_available is False")

    img_full = bh.render_image(r_full, samples=32, max_depth=4, apply_gamma=False)

    r_reg = _scene(W, H, seed=321, gpu=True)
    r_reg.set_render_region(x0, y0, x1, y1)
    img_reg = bh.render_image(r_reg, samples=32, max_depth=4, apply_gamma=False)

    inside_full = img_full[y0:y1, x0:x1]
    inside_reg = img_reg[y0:y1, x0:x1]
    # Same seed on the same device: inside pixels should match closely.
    denom = float(np.mean(inside_full)) + 1e-6
    rel = float(np.mean(np.abs(inside_reg - inside_full))) / denom
    assert rel < 0.02, ("inside-region GPU divergence rel=%g" % rel)

    mask = np.ones((H, W), dtype=bool)
    mask[y0:y1, x0:x1] = False
    assert float(np.max(img_reg[mask])) == 0.0, (
        "outside-region GPU pixels not zero: max %g" % float(np.max(img_reg[mask])))


# --------------------------------------------------------------------------- #
# Addon border -> engine rect mapping.
# --------------------------------------------------------------------------- #
def _render_stub(**border):
    render = types.SimpleNamespace(
        use_border=border.get('use_border', False),
        use_crop_to_border=border.get('use_crop_to_border', False),
        border_min_x=border.get('border_min_x', 0.0),
        border_max_x=border.get('border_max_x', 1.0),
        border_min_y=border.get('border_min_y', 0.0),
        border_max_y=border.get('border_max_y', 1.0),
    )
    return types.SimpleNamespace(render=render)


def test_addon_border_maps_to_topdown_rect(monkeypatch):
    addon = load_addon(monkeypatch, "region_map")
    engine = addon.CustomRaytracerRenderEngine()
    r = RecordingRenderer()
    # Border covers the TOP-LEFT quadrant in Blender's bottom-up coords:
    # x in [0,0.5], y in [0.5,1.0]  -> top-down y in [0,0.5].
    scene = _render_stub(use_border=True, border_min_x=0.0, border_max_x=0.5,
                         border_min_y=0.5, border_max_y=1.0)
    engine._apply_render_region(scene, r, 100, 80)
    assert r.render_region_calls == [(0, 0, 50, 40)], r.render_region_calls


def test_addon_no_border_clears_region(monkeypatch):
    addon = load_addon(monkeypatch, "region_clear")
    engine = addon.CustomRaytracerRenderEngine()
    r = RecordingRenderer()
    scene = _render_stub(use_border=False)
    engine._apply_render_region(scene, r, 100, 80)
    assert r.clear_region_calls == 1
    assert r.render_region_calls == []


def test_addon_crop_to_border_warns(monkeypatch):
    addon = load_addon(monkeypatch, "region_crop")
    engine = addon.CustomRaytracerRenderEngine()
    r = RecordingRenderer()
    scene = _render_stub(use_border=True, use_crop_to_border=True,
                         border_min_x=0.25, border_max_x=0.75,
                         border_min_y=0.25, border_max_y=0.75)
    engine._apply_render_region(scene, r, 100, 100)
    assert r.render_region_calls == [(25, 25, 75, 75)]
    details = " || ".join(d for (_f, d) in engine._degradation_report().approximated)
    assert 'Crop to Render Region' in details
