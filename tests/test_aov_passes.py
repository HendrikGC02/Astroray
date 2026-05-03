"""Tests for pkg32: AlbedoAOV pass."""
import numpy as np
import pytest
import os

from runtime_setup import configure_test_imports

configure_test_imports()

from base_helpers import save_image  # noqa: E402

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


def test_depth_aov_nonzero(test_results_dir):
    """DepthAOV pass must write normalized depth as grayscale (non-black, varying) to color."""
    r = _renderer()
    mat = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
    r.add_sphere([0, 0, 0], 1.5, mat)
    r.add_pass("depth_aov")
    pixels = np.array(r.render(samples_per_pixel=4, max_depth=2), dtype=np.float32)
    save_image(pixels, os.path.join(test_results_dir, "aov_depth.png"))
    assert pixels is not None
    assert pixels.size > 0
    assert np.any(pixels > 0.0), "DepthAOV output is all black; depth normalization failed"
    assert np.max(pixels) > np.min(pixels[pixels > 0.0]), "DepthAOV values do not vary; normalization may be broken"


def test_normal_aov_nonzero(test_results_dir):
    """NormalAOV pass must remap normals to [0,1] and write non-black output."""
    r = _renderer()
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    r.add_sphere([0, 0, 0], 1.5, mat)
    r.add_pass("normal_aov")
    pixels = np.array(r.render(samples_per_pixel=4, max_depth=2), dtype=np.float32)
    save_image(pixels, os.path.join(test_results_dir, "aov_normal.png"))
    assert pixels is not None
    assert pixels.size > 0
    assert np.any(pixels > 0.0), "NormalAOV output is all black; normal remap failed"
    assert np.all(pixels >= 0.0) and np.all(pixels <= 1.0), "NormalAOV output has values outside [0,1]"


def test_bounce_heatmap_registered():
    """bounce_heatmap must appear in pass_registry_names()."""
    assert "bounce_heatmap" in astroray.pass_registry_names()


def test_bounce_heatmap_nontrivial(test_results_dir):
    """BounceHeatmap must write finite, non-trivial false-color output."""
    r = _renderer()
    diffuse = r.create_material("lambertian", [0.7, 0.7, 0.7], {})
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})
    r.add_sphere([0, 0, 0], 1.3, glass)
    r.add_sphere([0, -1002, 0], 1000, diffuse)
    r.add_pass("bounce_heatmap")
    pixels = np.array(r.render(samples_per_pixel=8, max_depth=6), dtype=np.float32)
    save_image(pixels, os.path.join(test_results_dir, "aov_bounce_heatmap.png"))
    assert pixels.shape == (32, 32, 3)
    assert np.all(np.isfinite(pixels))
    assert np.any(pixels > 0.0), "BounceHeatmap output is all black"
    assert float(np.max(pixels) - np.min(pixels)) > 0.05, "BounceHeatmap output has no useful variation"


def test_albedo_aov_nonzero(test_results_dir):
    """AlbedoAOV pass must copy the albedo buffer (non-black) into the color output."""
    r = _renderer()
    mat = r.create_material("lambertian", [0.8, 0.2, 0.2], {})
    r.add_sphere([0, 0, 0], 1.5, mat)
    r.add_pass("albedo_aov")
    pixels = np.array(r.render(samples_per_pixel=4, max_depth=2), dtype=np.float32)
    save_image(pixels, os.path.join(test_results_dir, "aov_albedo.png"))
    assert pixels is not None
    assert pixels.size > 0
    # The albedo of the red Lambertian sphere should produce non-black pixels.
    assert np.any(pixels > 0.0), "AlbedoAOV output is all black; albedo copy failed"


def test_sample_heatmap_registered():
    """sample_heatmap must appear in the pass registry."""
    names = astroray.pass_registry_names()
    assert "sample_heatmap" in names, f"'sample_heatmap' not in registry: {names}"


def test_sample_heatmap_nontrivial(test_results_dir):
    """SampleHeatmap must visualize finite sample weights."""
    r = _renderer()
    diffuse = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    light = r.create_material("light", [1.0, 0.95, 0.85], {"intensity": 4.0})
    r.add_sphere([0, 0, 0], 1.1, diffuse)
    r.add_sphere([0, 2.8, 0.5], 0.4, light)
    r.add_pass("sample_heatmap")
    pixels = np.array(r.render(samples_per_pixel=8, max_depth=6), dtype=np.float32)
    save_image(pixels, os.path.join(test_results_dir, "aov_sample_heatmap.png"))
    assert pixels.shape == (32, 32, 3)
    assert np.all(np.isfinite(pixels))
    assert np.any(pixels > 0.0), "SampleHeatmap output is all black"
    assert float(np.max(pixels) - np.min(pixels)) > 0.05, "SampleHeatmap output has no useful variation"
