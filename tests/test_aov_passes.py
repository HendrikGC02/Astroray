"""Tests for pkg32: AlbedoAOV pass."""
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


def _renderer():
    r = astroray.Renderer()
    r.setup_camera(
        look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
        width=32, height=32,
    )
    r.set_background_color([0.0, 0.0, 0.0])
    return r


def test_albedo_aov_nonzero():
    """AlbedoAOV pass must copy the albedo buffer (non-black) into the color output."""
    r = _renderer()
    mat = r.create_material("lambertian", [0.8, 0.2, 0.2], {})
    r.add_sphere([0, 0, 0], 1.5, mat)
    r.add_pass("albedo_aov")
    pixels = np.array(r.render(samples_per_pixel=4, max_depth=2), dtype=np.float32)
    assert pixels is not None
    assert pixels.size > 0
    # The albedo of the red Lambertian sphere should produce non-black pixels.
    assert np.any(pixels > 0.0), "AlbedoAOV output is all black; albedo copy failed"
