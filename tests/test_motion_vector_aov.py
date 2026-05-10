"""pkg72: per-pixel motion vector AOV tests (camera-only motion).

Acceptance criteria from .astroray_plan/packages/pkg72-motion-vectors.md.
The flow convention follows OptiX: motion(x,y) = prev_pixel - curr_pixel.
"""
import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")


W, H = 32, 32
SAMPLES = 2
DEPTH = 2


def _make_renderer(look_from=(0.0, 0.0, 5.0)):
    r = astroray.Renderer()
    r.setup_camera(
        look_from=list(look_from), look_at=[0.0, 0.0, 0.0], vup=[0.0, 1.0, 0.0],
        vfov=45.0, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
        width=W, height=H,
    )
    r.set_background_color([0.0, 0.0, 0.0])
    return r


def _add_filling_plane(r):
    """Big sphere centred at origin so it covers the entire viewport."""
    mat = r.create_material("lambertian", [0.7, 0.7, 0.7], {})
    r.add_sphere([0.0, 0.0, 0.0], 100.0, mat)


def test_motion_buffer_shape_and_dtype():
    r = _make_renderer()
    _add_filling_plane(r)
    r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH)
    mv = r.get_motion_buffer()
    assert mv.shape == (H, W, 2)
    assert mv.dtype == np.float32
    # pkg72 acceptance: shares memory with the C++ buffer.
    assert mv.base is not None


def test_first_frame_is_zero():
    """First render after setup_camera has no previous camera -> all zeros."""
    r = _make_renderer()
    _add_filling_plane(r)
    r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH)
    mv = np.asarray(r.get_motion_buffer())
    assert np.max(np.abs(mv)) == 0.0


def test_static_camera_zero_motion():
    """Two renders with identical camera -> |motion| < 1e-4 everywhere."""
    r = _make_renderer()
    _add_filling_plane(r)
    r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH)  # frame 1 (prev)
    r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH)  # frame 2 (curr)
    mv = np.asarray(r.get_motion_buffer())
    assert np.max(np.abs(mv)) < 1e-4, f"static camera produced motion {np.max(np.abs(mv))}"


def test_sky_pixels_zero_motion():
    """Env-miss pixels (no geometry) report exactly (0, 0)."""
    r = _make_renderer()
    # No geometry -> every pixel is sky.
    r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH)
    r.setup_camera(
        look_from=[0.5, 0.0, 5.0], look_at=[0.0, 0.0, 0.0], vup=[0.0, 1.0, 0.0],
        vfov=45.0, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
        width=W, height=H,
    )
    r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH)
    mv = np.asarray(r.get_motion_buffer())
    assert np.all(mv == 0.0), "sky pixels must store exactly (0, 0)"


def test_camera_pan_produces_expected_motion():
    """Pan the camera right between frames; static surface -> +x flow.

    With OptiX's flow convention (motion = prev_pixel - curr_pixel) and the
    camera moving in the +x direction by Δ world units, a static surface
    point's previous-frame pixel sits to the right of its current-frame
    pixel, so motion.x is positive. Picks Δ such that |motion.x| ≈ 5 px.
    """
    # Frame 1: camera at origin x.
    r = _make_renderer(look_from=(0.0, 0.0, 5.0))
    _add_filling_plane(r)
    r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH)

    # Frame 2: pan camera right. Geometry: image plane at focus_dist=5,
    # vw = 2 * tan(22.5°) * 5 ≈ 4.142, mapped to W=32 px -> ~7.72 px / world.
    # Δ = 5 / 7.72 ≈ 0.6477 world units gives ~5 px screen-space motion.
    delta = 0.6477
    r.setup_camera(
        look_from=[delta, 0.0, 5.0], look_at=[delta, 0.0, 0.0], vup=[0.0, 1.0, 0.0],
        vfov=45.0, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
        width=W, height=H,
    )
    r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH)
    mv = np.asarray(r.get_motion_buffer())

    # The huge sphere covers the centre of the viewport. Sample only the
    # centre 8x8 region where every pixel is a guaranteed surface hit.
    cx0, cx1 = W // 2 - 4, W // 2 + 4
    cy0, cy1 = H // 2 - 4, H // 2 + 4
    centre = mv[cy0:cy1, cx0:cx1]

    mean_x = float(centre[..., 0].mean())
    mean_y = float(centre[..., 1].mean())
    # Expected ~+5 px; tolerate ±1.5 px for sphere-curvature-induced spread.
    assert 3.5 < mean_x < 6.5, f"unexpected motion.x mean: {mean_x}"
    assert abs(mean_y) < 1.0, f"motion.y should be ~0: {mean_y}"
    assert np.all(np.isfinite(mv)), "motion buffer contains non-finite values"


def test_motion_vector_aov_pass_runs():
    """The motion_vector_aov pass renders without crashing and is finite."""
    assert "motion_vector_aov" in astroray.pass_registry_names()
    r = _make_renderer()
    _add_filling_plane(r)
    r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH)  # prev
    r.setup_camera(
        look_from=[0.3, 0.0, 5.0], look_at=[0.0, 0.0, 0.0], vup=[0.0, 1.0, 0.0],
        vfov=45.0, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
        width=W, height=H,
    )
    r.add_pass("motion_vector_aov")
    pixels = np.asarray(r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH), dtype=np.float32)
    assert pixels.shape == (H, W, 3)
    assert np.all(np.isfinite(pixels))
    assert np.all(pixels >= 0.0) and np.all(pixels <= 1.0)
