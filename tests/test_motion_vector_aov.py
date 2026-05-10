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


def _add_centre_sphere(r, radius=1.5):
    """Modest sphere at the world origin — covers the centre of the viewport
    when the camera is at z=5, leaves the corners as sky pixels. Avoids
    enclosing the camera (which would put the hit at the sphere's far inner
    surface and crush all parallax)."""
    mat = r.create_material("lambertian", [0.7, 0.7, 0.7], {})
    r.add_sphere([0.0, 0.0, 0.0], radius, mat)


def test_motion_buffer_shape_and_dtype():
    r = _make_renderer()
    _add_centre_sphere(r)
    r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH)
    mv = r.get_motion_buffer()
    assert mv.shape == (H, W, 2)
    assert mv.dtype == np.float32
    # pkg72 acceptance: shares memory with the C++ buffer.
    assert mv.base is not None


def test_first_frame_is_zero():
    """First render after setup_camera has no previous camera -> all zeros."""
    r = _make_renderer()
    _add_centre_sphere(r)
    r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH)
    mv = np.asarray(r.get_motion_buffer())
    assert np.max(np.abs(mv)) == 0.0


def test_static_camera_zero_motion():
    """Two renders with identical camera -> |motion| < 1e-4 everywhere."""
    r = _make_renderer()
    _add_centre_sphere(r)
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

    OptiX flow convention: motion = prev_pixel - curr_pixel. When the camera
    pans in +x, a static surface point's previous-frame pixel sits to the
    right of its current-frame pixel, so motion.x is positive. Magnitude is
    parallax-dependent: for a sphere at distance ~3.5 with focal ~37 px and
    Δ = 0.6477 world, expect roughly +1 to +6 px on hit pixels. The test
    asserts only sign + sanity range, not an exact value (sphere curvature
    spreads the flow across the surface).
    """
    delta = 0.6477
    r = _make_renderer(look_from=(0.0, 0.0, 5.0))
    _add_centre_sphere(r)
    r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH)

    r.setup_camera(
        look_from=[delta, 0.0, 5.0], look_at=[delta, 0.0, 0.0], vup=[0.0, 1.0, 0.0],
        vfov=45.0, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
        width=W, height=H,
    )
    r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH)
    mv = np.asarray(r.get_motion_buffer())
    assert np.all(np.isfinite(mv)), "motion buffer contains non-finite values"

    # Find pixels that actually hit the sphere by checking |motion| > 0;
    # sky pixels are exactly (0, 0) per the OptiX-convention zero-fill.
    mag = np.abs(mv).sum(axis=-1)
    hit_mask = mag > 1e-6
    assert hit_mask.sum() > 0, "no surface-hit pixels recorded any motion"

    hit_x = mv[..., 0][hit_mask]
    hit_y = mv[..., 1][hit_mask]
    mean_x = float(hit_x.mean())
    mean_y = float(hit_y.mean())
    # +x camera pan -> +x flow. Hit-pixel magnitudes vary across the sphere
    # surface; assert direction + reasonable magnitude.
    assert mean_x > 0.5, f"camera pan in +x should produce +motion.x, got {mean_x}"
    assert mean_x < 10.0, f"motion.x mean unexpectedly large: {mean_x}"
    assert abs(mean_y) < 1.5, f"motion.y should be ~0 for horizontal pan: {mean_y}"


def test_motion_vector_aov_pass_runs():
    """The motion_vector_aov pass renders without crashing and is finite."""
    assert "motion_vector_aov" in astroray.pass_registry_names()
    r = _make_renderer()
    _add_centre_sphere(r)
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
