"""Physics-oriented spectral emitter material tests."""
import os

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

from base_helpers import save_image  # noqa: E402

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")


def _render_emitter(material_type, params, seed=11):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_seed(seed)
    r.setup_camera(
        look_from=[0.0, 0.0, 3.2],
        look_at=[0.0, 0.0, 0.0],
        vup=[0.0, 1.0, 0.0],
        vfov=34.0,
        aspect_ratio=1.0,
        aperture=0.0,
        focus_dist=3.2,
        width=96,
        height=96,
    )
    r.set_background_color([0.0, 0.0, 0.0])
    mat = r.create_material(material_type, [1.0, 1.0, 1.0], params)
    r.add_sphere([0.0, 0.0, 0.0], 0.9, mat)
    return np.asarray(r.render(16, 2, None, True), dtype=np.float32)


def test_physics_emitters_registered():
    names = astroray.material_registry_names()
    for name in ("blackbody", "blackbody_emitter", "line_emitter", "laser_emitter"):
        assert name in names


def test_blackbody_temperature_color_ordering(test_results_dir):
    warm = _render_emitter(
        "blackbody",
        {"temperature_kelvin": 2400.0, "intensity": 4.0},
    )
    cool = _render_emitter(
        "blackbody",
        {"temperature_kelvin": 10000.0, "intensity": 4.0},
    )
    save_image(warm, os.path.join(test_results_dir, "physics_blackbody_2400k.png"))
    save_image(cool, os.path.join(test_results_dir, "physics_blackbody_10000k.png"))

    warm_mean = warm.reshape(-1, 3).mean(axis=0)
    cool_mean = cool.reshape(-1, 3).mean(axis=0)
    assert np.isfinite(warm).all()
    assert np.isfinite(cool).all()
    assert warm_mean[0] > warm_mean[2], f"warm blackbody should lean red, got {warm_mean}"
    assert cool_mean[2] > cool_mean[0] * 0.7, f"cool blackbody should have strong blue, got {cool_mean}"


def test_line_emitter_wavelength_color_ordering(test_results_dir):
    red = _render_emitter("line_emitter", {"wavelength_nm": 635.0, "bandwidth_nm": 10.0, "intensity": 6.0})
    green = _render_emitter("line_emitter", {"wavelength_nm": 532.0, "bandwidth_nm": 10.0, "intensity": 6.0})
    blue = _render_emitter("line_emitter", {"wavelength_nm": 460.0, "bandwidth_nm": 10.0, "intensity": 6.0})
    save_image(red, os.path.join(test_results_dir, "physics_line_emitter_635nm.png"))
    save_image(green, os.path.join(test_results_dir, "physics_line_emitter_532nm.png"))
    save_image(blue, os.path.join(test_results_dir, "physics_line_emitter_460nm.png"))

    red_mean = red.reshape(-1, 3).mean(axis=0)
    green_mean = green.reshape(-1, 3).mean(axis=0)
    blue_mean = blue.reshape(-1, 3).mean(axis=0)
    assert red_mean[0] > red_mean[1] and red_mean[0] > red_mean[2]
    assert green_mean[1] > green_mean[0] and green_mean[1] > green_mean[2]
    assert blue_mean[2] > blue_mean[0] and blue_mean[2] > blue_mean[1]
