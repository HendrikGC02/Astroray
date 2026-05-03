"""pkg36 — shared material closure graph coverage."""

from __future__ import annotations

import numpy as np
import pytest

import astroray
from base_helpers import create_renderer, render_image, setup_camera


def _renderer(width=32, height=24):
    r = create_renderer()
    r.setup_camera(
        look_from=[0, 0, 4],
        look_at=[0, 0, 0],
        vup=[0, 1, 0],
        vfov=40,
        aspect_ratio=width / height,
        aperture=0.0,
        focus_dist=4.0,
        width=width,
        height=height,
    )
    r.set_background_color([0.05, 0.06, 0.08])
    return r


@pytest.mark.parametrize(
    "material_type,color,params,expected_types",
    [
        ("lambertian", [0.7, 0.2, 0.1], {}, {"diffuse"}),
        ("metal", [0.9, 0.7, 0.4], {"roughness": 0.35}, {"ggx_conductor"}),
        ("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5}, {"dielectric_transmission"}),
        ("disney", [0.8, 0.45, 0.25], {"roughness": 0.45}, {"diffuse", "ggx_conductor"}),
        ("disney", [0.9, 0.95, 1.0], {"transmission": 1.0, "roughness": 0.25}, {"dielectric_transmission"}),
    ],
)
def test_core_materials_export_closure_graphs(material_type, color, params, expected_types):
    r = _renderer()
    mat = r.create_material(material_type, color, params)

    graph = r.get_material_closure_graph(mat)
    caps = r.get_material_backend_capabilities(mat)
    types = {closure["type"] for closure in graph}

    assert expected_types.issubset(types)
    assert caps["closure_graph"] is True
    assert caps["closure_count"] == len(graph)
    assert caps["gpu"] is True
    assert caps["gpu_type"] == "closure_graph"


def test_dispersive_dielectric_does_not_export_flat_closure_graph():
    r = _renderer()
    mat = r.create_material("dielectric", [1.0, 1.0, 1.0], {"sellmeier_preset": "bk7"})
    caps = r.get_material_backend_capabilities(mat)

    assert r.get_material_closure_graph(mat) == []
    assert caps["closure_graph"] is False
    assert caps["gpu"] is False


def test_closure_only_plugin_gets_gpu_capability_without_gpu_type_name():
    assert "closure_matte" in astroray.material_registry_names()

    r = _renderer()
    mat = r.create_material("closure_matte", [0.2, 0.65, 0.9], {})
    graph = r.get_material_closure_graph(mat)
    caps = r.get_material_backend_capabilities(mat)

    assert [closure["type"] for closure in graph] == ["diffuse"]
    assert caps["closure_graph"] is True
    assert caps["gpu"] is True
    assert caps["gpu_type"] == "closure_graph"


def test_materials_without_graph_remain_cpu_only_escape_hatches():
    r = _renderer()
    mat = r.create_material("mirror", [1.0, 1.0, 1.0], {})
    caps = r.get_material_backend_capabilities(mat)

    assert r.get_material_closure_graph(mat) == []
    assert caps["closure_graph"] is False
    assert caps["gpu"] is False


def test_closure_only_plugin_renders_on_gpu_when_available():
    r = _renderer(48, 36)
    if not bool(astroray.__features__.get("cuda", False)) or not bool(getattr(r, "gpu_available", False)):
        pytest.skip("CUDA GPU not available")

    mat = r.create_material("closure_matte", [0.2, 0.65, 0.9], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.set_use_gpu(True)
    setup_camera(r, look_from=[0, 0, 4], look_at=[0, 0, 0], vfov=40, width=48, height=36)

    pixels = render_image(r, samples=16, max_depth=3)
    assert np.isfinite(pixels).all()
    assert float(np.mean(pixels)) > 0.0
