"""#1033 - transparent pass-throughs are not bounces (CPU + GPU).

Cycles (kernel/integrator/path_state.h path_state_next, Apache-2.0): a
LABEL_TRANSPARENT sample keeps the ray's flags, counts in transparent_bounce
only (no max_bounces / clamp-class / per-type spend), and once
transparent_bounce >= transparent_max_bounces the NEXT surface hit takes its
emission and terminates (PATH_RAY_TERMINATE_ON_NEXT_SURFACE). Verified against
Blender 5.2 Cycles (CPU): 3 stacked Transparent-BSDF sheets in front of a lit
diffuse wall -> wall black for transparent_max_bounces = 0..3, lit for 4 and 8.

Before the fix the engine counted the pass in `bounce` (CPU + GPU): the wall seen
through alpha was clamped with clamp_indirect, alpha ate the max_bounces budget,
and transparent_bounces was accepted and ignored.
"""
import pytest
from test_issue991_light_path import BACKENDS, _quad, _renderer, _roi

SUN_W = 3.0
WALL_Y = 6.0


def _scene(use_gpu, sheets, clamp_indirect=0.0, wall_y=WALL_Y):
    """Camera at the origin looking +y; `sheets` Alpha-0 quads in front of a lit
    diffuse wall at y=6 (sun travelling +y)."""
    r = _renderer(use_gpu)
    r.set_background_color([0.0, 0.0, 0.0])
    r.add_sun_light_dedicated([0.0, 1.0, 0.0], 0.01, {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]},
                              SUN_W, 0, 0)
    wall = r.create_material("principled", [0.8, 0.8, 0.8],
                             {"roughness": 1.0, "specular_ior_level": 0.0})
    _quad(r, wall, [0, wall_y, 0], [4.0, 0, 0], [0, 0, 4.0])
    sheet = r.create_material("principled", [1.0, 1.0, 1.0], {"alpha": 0.0})
    for i in range(sheets):
        _quad(r, sheet, [0, 2.0 + 0.5 * i, 0], [4.0, 0, 0], [0, 0, 4.0])
    r.set_clamp_indirect(clamp_indirect)
    return r


def _wall_value(use_gpu, sheets, depth=4, transparent=-1, clamp_indirect=0.0,
                wall_y=WALL_Y, clip_near=0.001):
    from base_helpers import setup_camera
    r = _scene(use_gpu, sheets, clamp_indirect, wall_y)
    setup_camera(r, look_from=[0, 0, 0], look_at=[0, 1, 0], vup=[0, 0, 1], vfov=10,
                 width=32, height=32)
    if clip_near > 0.001:   # setup_camera() has no clip args: re-issue the camera
        r.setup_camera(look_from=[0, 0, 0], look_at=[0, 1, 0], vup=[0, 0, 1], vfov=10.0,
                       aspect_ratio=1.0, aperture=0.0, focus_dist=5.0, width=32, height=32,
                       clip_near=clip_near)
    img = r.render(48, depth, None, False, -1, -1, -1, -1, transparent)
    return float(_roi(img, 16, 16, 4).mean())


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_alpha_pass_keeps_the_direct_clamp_class(use_gpu):
    """The wall seen through an alpha sheet is a camera-visible (direct) surface: its
    NEE is clamped with clamp_direct, never clamp_indirect (Cycles), so clamp_indirect
    must not change it. The sun-lit wall (~0.7) exceeds the 0.2 clamp."""
    ref = _wall_value(use_gpu, 0)
    assert ref > 0.3, ref
    free = _wall_value(use_gpu, 1, clamp_indirect=0.0)
    clamped = _wall_value(use_gpu, 1, clamp_indirect=0.2)
    assert free == pytest.approx(ref, rel=0.05), (free, ref)
    assert clamped == pytest.approx(free, rel=0.03), (clamped, free)


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_alpha_pass_spends_no_max_bounces(use_gpu):
    """max_depth = 1 is first-hit direct lighting only: the wall behind an alpha sheet
    must still be lit (the pass is not a bounce), like the sheet-free render."""
    ref = _wall_value(use_gpu, 0, depth=1)
    through = _wall_value(use_gpu, 1, depth=1)
    assert ref > 0.3, ref
    assert through == pytest.approx(ref, rel=0.05), (through, ref)


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_transparent_max_bounces_is_honoured(use_gpu):
    """Three Alpha-0 sheets: after the T-th pass the next surface terminates, so the
    wall is black for T <= 3 (Blender 5.2 Cycles, see module docstring). For T = 4, 5
    the camera reaches the wall but its sun shadow ray (which crosses the same three
    sheets) has only T - 3 transparent hits left, so it stays black until T >= 6
    (#1073, Blender 5.2: black T = 3..5, lit T = 6, 8); -1 (unlimited) lights it. The
    original expectation (lit from T = 4) was calibrated on small sheets that the
    shadow ray bypassed, and on the engine's own 8-hop shadow cap."""
    ref = _wall_value(use_gpu, 0)
    for t in (1, 3):
        v = _wall_value(use_gpu, 3, transparent=t)
        assert v < 0.02, (t, v)
    for t in (6, 8, -1):
        v = _wall_value(use_gpu, 3, transparent=t)
        assert v == pytest.approx(ref, rel=0.05), (t, v, ref)


@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_camera_clip_applies_to_the_camera_segment_only(use_gpu):
    """The near clip bounds the camera ray, not its continuation through an alpha
    sheet: a wall 0.1 behind the sheet stays visible with clip_start 0.5 (the
    continuation is a bounce-0 ray now, so the clip must not be re-applied)."""
    ref = _wall_value(use_gpu, 0, wall_y=2.1)
    clipped = _wall_value(use_gpu, 1, wall_y=2.1, clip_near=0.5)
    assert ref > 0.3, ref
    assert clipped == pytest.approx(ref, rel=0.05), (clipped, ref)
