"""Tests for the pkg05 Integrator interface and plugin registry."""
import sys, os
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'build'))

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
        width=16, height=16,
    )
    r.set_background_color([1.0, 1.0, 1.0])
    return r


def test_integrator_registry_names_contains_builtins():
    names = astroray.integrator_registry_names()
    assert "path_tracer" in names, f"'path_tracer' not in registry: {names}"
    assert "ambient_occlusion" in names, f"'ambient_occlusion' not in registry: {names}"


def test_path_integrator_renders_nonzero():
    r = _renderer()
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.set_integrator("path_tracer")
    pixels = np.array(r.render(samples_per_pixel=1, max_depth=4), dtype=np.float32)
    assert pixels is not None
    assert pixels.size > 0
    assert pixels.max() > 0.0, "path_tracer integrator produced all-black output"


def test_ambient_occlusion_integrator_renders_nonzero():
    r = _renderer()
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.set_integrator("ambient_occlusion")
    pixels = np.array(r.render(samples_per_pixel=1, max_depth=4), dtype=np.float32)
    assert pixels is not None
    assert pixels.size > 0
    assert pixels.max() > 0.0, "ambient_occlusion integrator produced all-black output"


def test_no_integrator_returns_black():
    """Since pkg14, a Renderer with no set_integrator() produces all-black output.
    The render must not crash and must return a valid array."""
    r = _renderer()
    mat = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    pixels = np.array(r.render(samples_per_pixel=1, max_depth=4), dtype=np.float32)
    assert pixels is not None
    assert pixels.size > 0
    assert not np.any(np.isnan(pixels)), "null integrator render produced NaN"
