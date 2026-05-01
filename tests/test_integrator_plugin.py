"""Tests for the pkg05 Integrator interface and plugin registry."""
import sys, os
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
    r.set_background_color([1.0, 1.0, 1.0])
    return r


def test_integrator_registry_names_contains_builtins():
    names = astroray.integrator_registry_names()
    assert "path_tracer" in names, f"'path_tracer' not in registry: {names}"
    assert "ambient_occlusion" in names, f"'ambient_occlusion' not in registry: {names}"
    assert "neural-cache" in names, f"'neural-cache' not in registry: {names}"


def test_path_integrator_renders_nonzero():
    r = _renderer()
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.set_integrator("path_tracer")
    pixels = np.array(r.render(samples_per_pixel=1, max_depth=4), dtype=np.float32)
    assert pixels is not None
    assert pixels.size > 0
    assert pixels.max() > 0.0, "path_tracer integrator produced all-black output"
    assert r.get_integrator_stats() == {}


def test_ambient_occlusion_integrator_renders_nonzero():
    r = _renderer()
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.set_integrator("ambient_occlusion")
    pixels = np.array(r.render(samples_per_pixel=1, max_depth=4), dtype=np.float32)
    assert pixels is not None
    assert pixels.size > 0
    assert pixels.max() > 0.0, "ambient_occlusion integrator produced all-black output"


def test_neural_cache_integrator_is_selectable_and_renders_nonzero():
    r = _renderer()
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.set_integrator_param("force_fallback", 1)
    r.set_integrator("neural-cache")
    pixels = np.array(r.render(samples_per_pixel=1, max_depth=4), dtype=np.float32)
    assert pixels is not None
    assert pixels.size > 0
    assert pixels.max() > 0.0, "neural-cache integrator produced all-black output"


def test_neural_cache_reports_fallback_training_stats():
    r = _renderer()
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.set_integrator_param("force_fallback", 1)
    r.set_integrator("neural-cache")
    pixels = np.array(r.render(samples_per_pixel=1, max_depth=4), dtype=np.float32)
    stats = r.get_integrator_stats()
    assert pixels.max() > 0.0
    assert stats["buffered_training"] == 1.0
    assert stats["force_fallback"] == 1.0
    assert stats["last_fallback_samples"] > 0.0
    assert stats["last_queued_samples"] == 0.0
    assert stats["last_trained_samples"] == 0.0
    assert stats["total_train_steps"] == 0.0


def test_neural_cache_reports_buffered_training_when_backend_runs():
    r = _renderer()
    r.set_background_color([0.03, 0.035, 0.04])
    mat = r.create_material("lambertian", [0.75, 0.76, 0.78], {})
    r.add_sphere([0, 0, 0], 1.7, mat)
    r.set_integrator_param("warmup_frames", 2)
    r.set_integrator_param("training_pct", 100)
    r.set_integrator_param("min_train_batch", 1)
    r.set_integrator_param("max_train_samples", 64)
    r.set_integrator("neural-cache")
    pixels = np.array(r.render(samples_per_pixel=1, max_depth=3), dtype=np.float32)
    stats = r.get_integrator_stats()
    assert pixels.size > 0
    assert np.isfinite(pixels).all()
    if stats["backend_compiled"] == 0.0:
        pytest.skip("tiny-cuda-nn backend not compiled in this build")
    if stats["last_fallback_samples"] > 0.0:
        pytest.skip("tiny-cuda-nn backend compiled but unavailable at runtime")
    assert stats["last_queued_samples"] > 0.0
    assert stats["last_trained_samples"] == stats["last_queued_samples"]
    assert stats["last_padded_train_samples"] >= stats["last_trained_samples"]
    assert stats["last_padded_train_samples"] % 256.0 == 0.0
    assert stats["total_train_steps"] >= 1.0


def test_unset_integrator_uses_auto_default_and_renders_nonzero():
    """Unset integrator now chooses the best available path with fallback."""
    r = _renderer()
    mat = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    pixels = np.array(r.render(samples_per_pixel=1, max_depth=4), dtype=np.float32)
    stats = r.get_integrator_stats()
    assert pixels is not None
    assert pixels.size > 0
    assert not np.any(np.isnan(pixels)), "null integrator render produced NaN"
    assert pixels.max() > 0.0, "auto default integrator produced all-black output"
    assert stats.get("buffered_training") == 1.0


def test_auto_integrator_alias_resets_to_default_policy():
    r = _renderer()
    mat = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.set_integrator("ambient_occlusion")
    r.set_integrator("auto")
    pixels = np.array(r.render(samples_per_pixel=1, max_depth=4), dtype=np.float32)
    assert pixels.max() > 0.0
    assert r.get_integrator_stats().get("buffered_training") == 1.0
