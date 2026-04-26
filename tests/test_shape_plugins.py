"""Smoke tests for the five shape plugins introduced in pkg04."""
import sys
import os

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'build'))

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

SHAPE_TYPES = ["sphere", "triangle", "mesh", "constant_medium", "black_hole"]


def test_all_shapes_in_registry():
    names = astroray.shape_registry_names()
    for s in SHAPE_TYPES:
        assert s in names, f"'{s}' not in ShapeRegistry"


def _renderer(width=16, height=16):
    r = astroray.Renderer()
    r.setup_camera(
        look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
        width=width, height=height,
    )
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_integrator("path_tracer")
    return r


def _render(renderer, samples=8):
    return np.array(renderer.render(samples_per_pixel=samples, max_depth=4), dtype=np.float32)


def test_sphere_hit():
    r = _renderer()
    mat = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 5.0})
    r.add_sphere([0, 0, 0], 1.0, mat)
    pixels = _render(r)
    assert pixels.max() > 0.0, "sphere: render is all black — no hit"


def test_triangle_hit():
    r = _renderer()
    mat = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 5.0})
    r.add_triangle([0, 1, 0], [-1, -1, 0], [1, -1, 0], mat)
    pixels = _render(r)
    assert pixels.max() > 0.0, "triangle: render is all black — no hit"


def test_mesh_hit(tmp_path):
    obj_file = tmp_path / "box.obj"
    obj_file.write_text(
        "v -1 -1 0\nv  1 -1 0\nv  0  1 0\n"
        "f 1 2 3\n"
    )
    r = _renderer()
    mat = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 5.0})
    r.add_mesh(str(obj_file), mat)
    pixels = _render(r)
    assert pixels.max() > 0.0, "mesh: render is all black — no hit"


def test_constant_medium_no_crash():
    r = _renderer()
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    r.set_background_color([1.0, 1.0, 1.0])
    r.add_volume([0, 0, 0], 2.0, 0.5, [0.8, 0.8, 0.8])
    light_mat = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 10.0})
    r.add_sphere([0, 3, 0], 0.5, light_mat)
    pixels = _render(r)
    assert np.isfinite(pixels).all(), "constant_medium: non-finite pixels"


def test_black_hole_no_regression():
    r = _renderer(width=32, height=32)
    r.set_background_color([0.1, 0.1, 0.5])
    r.add_black_hole([0, 0, 0], 1.0, 2.0, {})
    pixels = _render(r, samples=16)
    assert np.isfinite(pixels).all(), "black_hole: non-finite pixels"
    mean = float(pixels.mean())
    assert mean >= 0.0, "black_hole: negative mean pixel"
