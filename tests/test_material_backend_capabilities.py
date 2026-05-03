"""Tests for pkg34 material backend capability metadata."""

from __future__ import annotations

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


def _renderer(width: int = 16, height: int = 16):
    r = astroray.Renderer()
    r.setup_camera(
        look_from=[0, 0, 4], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=40, aspect_ratio=width / height, aperture=0.0, focus_dist=4.0,
        width=width, height=height,
    )
    r.set_background_color([0.05, 0.05, 0.06])
    return r


def test_backend_capabilities_report_gpu_supported_material():
    r = _renderer()
    mat = r.create_material("lambertian", [0.8, 0.2, 0.2], {})
    caps = r.get_material_backend_capabilities(mat)
    assert caps["cpu"] is True
    assert caps["spectral"] is True
    assert caps["gpu"] is True
    assert caps["gpu_spectral"] is True
    assert caps["gpu_approximate"] is False
    assert caps["closure_graph"] is True
    assert caps["gpu_type"] == "closure_graph"


def test_backend_capabilities_report_cpu_only_material():
    r = _renderer()
    mat = r.create_material("mirror", [1.0, 1.0, 1.0], {})
    caps = r.get_material_backend_capabilities(mat)
    assert caps["gpu"] is False
    assert caps["gpu_spectral"] is False
    assert "mirror" in caps["notes"]


def test_backend_capabilities_report_explicit_preview_approximation():
    r = _renderer()
    mat = r.create_material("disney", [1.0, 1.0, 1.0], {"transmission": 1.0, "roughness": 0.35})
    caps = r.get_material_backend_capabilities(mat)
    assert caps["gpu"] is True
    assert caps["gpu_spectral"] is True
    assert caps["gpu_approximate"] is True
    assert caps["closure_graph"] is True
    assert caps["gpu_type"] == "closure_graph"
    assert "closure-graph" in caps["notes"]


def test_dispersive_dielectric_is_cpu_only_until_spectral_gpu_support():
    r = _renderer()
    mat = r.create_material("dielectric", [1.0, 1.0, 1.0], {"glass_preset": "bk7"})
    caps = r.get_material_backend_capabilities(mat)
    assert caps["gpu"] is False
    assert caps["gpu_spectral"] is False
    assert "Sellmeier" in caps["notes"]


def test_gpu_rejects_cpu_only_material_without_silent_lambertian_fallback():
    r = _renderer()
    if not bool(astroray.__features__.get("cuda", False)) or not bool(getattr(r, "gpu_available", False)):
        pytest.skip("CUDA GPU not available")

    mat = r.create_material("mirror", [1.0, 1.0, 1.0], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.set_use_gpu(True)
    with pytest.raises(RuntimeError, match="Material cannot be uploaded to GPU"):
        np.asarray(r.render(samples_per_pixel=1, max_depth=2), dtype=np.float32)
