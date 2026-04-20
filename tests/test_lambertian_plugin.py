"""Tests for the Lambertian material plugin registered via ASTRORAY_REGISTER_MATERIAL."""
import math
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'build'))

import pytest

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")


def _make_renderer():
    return astroray.Renderer()


def test_lambertian_in_registry():
    """material_registry_names() lists 'lambertian'."""
    assert "lambertian" in astroray.material_registry_names()


def test_construction_default_albedo():
    """create_material('lambertian', ...) succeeds with default params."""
    r = _make_renderer()
    mat_id = r.create_material("lambertian", [0.8, 0.3, 0.1], {})
    assert mat_id >= 0


def test_construction_with_roughness():
    """create_material accepts roughness param without error."""
    r = _make_renderer()
    mat_id = r.create_material("lambertian", [0.5, 0.5, 0.5], {"roughness": 0.9})
    assert mat_id >= 0


def test_eval_non_negative():
    """Rendered pixels with a lambertian material are non-negative."""
    import numpy as np
    r = _make_renderer()
    r.setup_camera(
        look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
        width=16, height=16,
    )
    r.set_background_color([1.0, 1.0, 1.0])
    mat = r.create_material("lambertian", [0.8, 0.2, 0.2], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    pixels = np.array(r.render(samples_per_pixel=4, max_depth=3), dtype=np.float32)
    assert pixels.min() >= 0.0, "Lambertian eval returned negative values"


def test_sample_upper_hemisphere():
    """Rendered pixels with backlit lambertian stay non-negative (sample in upper hemisphere)."""
    import numpy as np
    r = _make_renderer()
    r.setup_camera(
        look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
        width=8, height=8,
    )
    r.set_background_color([0.0, 0.0, 0.0])
    mat = r.create_material("lambertian", [1.0, 1.0, 1.0], {})
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 5.0})
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.add_sphere([0, 3, 0], 0.5, light)
    pixels = np.array(r.render(samples_per_pixel=8, max_depth=4), dtype=np.float32)
    assert pixels.min() >= 0.0, "sample() returned direction outside upper hemisphere"
