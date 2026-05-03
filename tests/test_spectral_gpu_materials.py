"""pkg35 — GPU spectral material capability and parity coverage."""

import numpy as np
import pytest

import astroray
from base_helpers import create_cornell_box, create_renderer, render_image, setup_camera


def _has_cuda_gpu(renderer):
    return bool(astroray.__features__.get("cuda", False)) and bool(getattr(renderer, "gpu_available", False))


def _scene(renderer, material_type, base_color, params):
    create_cornell_box(renderer)
    mat = renderer.create_material(material_type, base_color, params)
    renderer.add_sphere([0.0, -0.85, 0.0], 0.85, mat)
    setup_camera(
        renderer,
        look_from=[0, 0, 5.5],
        look_at=[0, -0.15, 0],
        vfov=38,
        width=80,
        height=60,
    )


@pytest.mark.parametrize(
    "material_type,base_color,params,tolerance",
    [
        ("lambertian", [0.75, 0.25, 0.15], {}, 0.45),
        ("metal", [0.8, 0.65, 0.35], {"roughness": 0.45}, 0.55),
        ("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5}, 0.60),
        ("disney", [0.8, 0.4, 0.2], {"roughness": 0.35, "metallic": 0.2}, 0.60),
    ],
)
def test_core_non_dispersive_materials_have_cpu_gpu_brightness_parity(
        material_type, base_color, params, tolerance):
    probe = create_renderer()
    if not _has_cuda_gpu(probe):
        pytest.skip("CUDA GPU not available")

    cpu = create_renderer()
    _scene(cpu, material_type, base_color, params)
    cpu.set_seed(1234)
    cpu_pixels = render_image(cpu, samples=32, max_depth=6)

    gpu = create_renderer()
    _scene(gpu, material_type, base_color, params)
    gpu.set_use_gpu(True)
    gpu_pixels = render_image(gpu, samples=64, max_depth=6)

    assert np.isfinite(cpu_pixels).all()
    assert np.isfinite(gpu_pixels).all()
    cpu_mean = float(np.mean(cpu_pixels))
    gpu_mean = float(np.mean(gpu_pixels))
    rel = abs(cpu_mean - gpu_mean) / max(cpu_mean, 1e-6)
    assert rel < tolerance, (
        f"{material_type} CPU/GPU mean brightness diverged: "
        f"cpu={cpu_mean:.4f}, gpu={gpu_mean:.4f}, rel={rel:.3f}"
    )


def test_pkg35_capabilities_mark_spectral_gpu_and_cpu_only_emitters():
    renderer = create_renderer()
    lambertian = renderer.create_material("lambertian", [0.5, 0.6, 0.7], {})
    lam_caps = renderer.get_material_backend_capabilities(lambertian)
    assert lam_caps["gpu"] is True
    assert lam_caps["gpu_spectral"] is True

    flat = renderer.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.52})
    flat_caps = renderer.get_material_backend_capabilities(flat)
    assert flat_caps["gpu"] is True
    assert flat_caps["gpu_spectral"] is True
    assert "flat-IOR" in flat_caps["notes"]

    dispersive = renderer.create_material("dielectric", [1.0, 1.0, 1.0], {"sellmeier_preset": "bk7"})
    dispersive_caps = renderer.get_material_backend_capabilities(dispersive)
    assert dispersive_caps["gpu"] is False
    assert dispersive_caps["gpu_spectral"] is False
    assert "Sellmeier" in dispersive_caps["notes"]

    for name in ("line_emitter", "blackbody"):
        mat = renderer.create_material(name, [1.0, 1.0, 1.0], {})
        caps = renderer.get_material_backend_capabilities(mat)
        assert caps["gpu"] is False
        assert caps["gpu_spectral"] is False
        assert "CPU-only" in caps["notes"]
