"""Tests for pkg06: Pass interface and plugin registry."""
import sys
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

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")


def _renderer():
    r = astroray.Renderer()
    r.setup_camera(
        look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
        width=16, height=16,
    )
    r.set_background_color([0.5, 0.5, 0.5])
    return r


def test_pass_registry_names_contains_builtins():
    names = astroray.pass_registry_names()
    assert "oidn_denoiser" in names, f"'oidn_denoiser' not in registry: {names}"
    assert "depth_aov"     in names, f"'depth_aov' not in registry: {names}"
    assert "normal_aov"    in names, f"'normal_aov' not in registry: {names}"
    assert "albedo_aov"    in names, f"'albedo_aov' not in registry: {names}"


def test_add_pass_aov_no_crash():
    """AOV passes must execute without crashing on a rendered framebuffer."""
    r = _renderer()
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.add_pass("depth_aov")
    r.add_pass("normal_aov")
    r.add_pass("albedo_aov")
    pixels = np.array(r.render(samples_per_pixel=1, max_depth=4), dtype=np.float32)
    assert pixels is not None
    assert pixels.size > 0


def test_clear_passes_removes_all_passes():
    """After clear_passes, render output matches a baseline with no passes."""
    r_base = _renderer()
    mat = r_base.create_material("lambertian", [0.8, 0.8, 0.8], {})
    r_base.add_sphere([0, 0, 0], 1.0, mat)
    r_base.set_seed(1)
    base = np.array(r_base.render(samples_per_pixel=2, max_depth=4), dtype=np.float32)

    r_cleared = _renderer()
    mat2 = r_cleared.create_material("lambertian", [0.8, 0.8, 0.8], {})
    r_cleared.add_sphere([0, 0, 0], 1.0, mat2)
    r_cleared.set_seed(1)
    r_cleared.add_pass("depth_aov")
    r_cleared.clear_passes()
    after = np.array(r_cleared.render(samples_per_pixel=2, max_depth=4), dtype=np.float32)

    assert np.array_equal(base, after), "clear_passes() must leave output unchanged"


def test_oidn_pass_executes_or_gracefully_skips():
    """oidn_denoiser pass must run without throwing even if OIDN is unavailable."""
    r = _renderer()
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.add_pass("oidn_denoiser")
    pixels = np.array(r.render(samples_per_pixel=4, max_depth=4), dtype=np.float32)
    assert pixels is not None
    assert pixels.size > 0
    assert np.all(np.isfinite(pixels)), "oidn_denoiser output contains non-finite values"
