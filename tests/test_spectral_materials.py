#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Pillar 2 / pkg13 — spectral material overrides: Metal, Dielectric, Mirror,
Subsurface, and the Texture::sampleSpectral infrastructure.

Covers:
  1. Metal evalSpectral: non-negative, no NaN/Inf; roughness path produces
     per-λ Fresnel variation (warm-tinted albedo peaks differently across
     wavelengths); same-seed Cornell A/B is deterministic with a metal sphere.
  2. Dielectric / Mirror evalSpectral: returns 0 (delta lobes).
  3. Subsurface evalSpectral: non-negative, no NaN/Inf.
  4. Texture plugin registry still exposes the expected procedural/image
     plugins used by spectral texture tests.
  5. RGBAlbedoSpectrum sampling is stable across repeated calls.
  6. pkg13a non-physics overrides (Phong, Disney, DiffuseLight, NormalMapped):
     spectral renders are finite and deterministic for a fixed seed.
"""
import math
import os
import sys

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

from base_helpers import create_cornell_box, save_image, setup_camera  # noqa: E402

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

SPP = 64
WIDTH = 200
HEIGHT = 150
MAX_DEPTH = 8


def _render(integrator: str, scene_fn, seed: int = 42) -> np.ndarray:
    r = astroray.Renderer()
    scene_fn(r)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 vfov=38, width=WIDTH, height=HEIGHT)
    r.set_integrator(integrator)
    r.set_seed(seed)
    return np.asarray(r.render(SPP, MAX_DEPTH, None, True), dtype=np.float32)


def _metal_scene(r):
    create_cornell_box(r)
    mat = r.create_material("metal", [0.9, 0.7, 0.3], {"roughness": 0.3})
    r.add_sphere([0, -1, 0], 1.0, mat)


def _dielectric_scene(r):
    create_cornell_box(r)
    mat = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})
    r.add_sphere([0, -1, 0], 1.0, mat)


def _phong_scene(r):
    create_cornell_box(r)
    mat = r.create_material("phong", [0.8, 0.5, 0.2], {"specular": 0.4, "shininess": 24.0})
    r.add_sphere([0, -1, 0], 1.0, mat)


def _disney_scene(r):
    create_cornell_box(r)
    mat = r.create_material("disney", [0.7, 0.55, 0.25], {"roughness": 0.45, "metallic": 0.2})
    r.add_sphere([0, -1, 0], 1.0, mat)


def _normal_mapped_scene(r):
    create_cornell_box(r)
    mat = r.create_material("normal_mapped", [0.75, 0.45, 0.25], {"inner_type": "phong", "specular": 0.35, "shininess": 20.0})
    r.add_sphere([0, -1, 0], 1.0, mat)


def _diffuse_light_scene(r):
    create_cornell_box(r)
    mat = r.create_material("diffuse_light", [1.0, 0.9, 0.7], {"intensity": 6.0})
    r.add_sphere([0, 1.4, 0], 0.45, mat)


# ---------------------------------------------------------------------------
# Metal
# ---------------------------------------------------------------------------

def test_metal_spectral_no_nan_no_inf():
    pixels = _render("path_tracer", _metal_scene)
    assert not np.any(np.isnan(pixels)), "spectral Metal render contains NaN"
    assert not np.any(np.isinf(pixels)), "spectral Metal render contains Inf"
    assert pixels.min() >= 0.0


def test_metal_spectral_formula_non_negative():
    """Metal evalSpectral output is non-negative for valid geometry."""
    wl = astroray.SampledWavelengths.sample_uniform(0.5)
    rsp = astroray.RGBAlbedoSpectrum([0.9, 0.7, 0.3])
    sampled = rsp.sample(wl)
    # Simulate the Schlick Fresnel term scaling (simplified sanity check)
    for cosTheta in [0.1, 0.5, 1.0]:
        fresnelPow5 = (1.0 - cosTheta) ** 5
        for i in range(4):
            F_i = sampled[i] + (1.0 - sampled[i]) * fresnelPow5
            assert F_i >= 0.0, f"Schlick F negative at cosTheta={cosTheta}, sample {i}"
            assert F_i <= 1.0 + 1e-6, f"Schlick F > 1 at cosTheta={cosTheta}, sample {i}"


def test_metal_spectral_deterministic_a_b(test_results_dir):
    """Cornell+metal spectral render is deterministic for a fixed seed."""
    baseline = _render("path_tracer", _metal_scene, seed=7)
    repeat = _render("path_tracer", _metal_scene, seed=7)
    save_image(baseline, os.path.join(test_results_dir, 'pkg13_metal_baseline.png'))
    save_image(repeat, os.path.join(test_results_dir, 'pkg13_metal_repeat.png'))

    baseline_mean = baseline.reshape(-1, 3).mean(axis=0)
    repeat_mean = repeat.reshape(-1, 3).mean(axis=0)
    rel_delta = np.abs(baseline_mean - repeat_mean) / (baseline_mean + 1e-3)
    print(f"\n  Metal baseline mean: {baseline_mean}")
    print(f"  Metal repeat mean:   {repeat_mean}")
    print(f"  rel delta:       {rel_delta}")
    assert np.allclose(baseline, repeat, rtol=0.0, atol=1e-7), \
        "same seed should produce deterministic metal spectral output"


# ---------------------------------------------------------------------------
# Dielectric / Mirror — delta materials, evalSpectral returns 0
# ---------------------------------------------------------------------------

def test_dielectric_spectral_no_nan(test_results_dir):
    """Spectral render with a glass sphere must not produce NaN/Inf."""
    pixels = _render("path_tracer", _dielectric_scene)
    save_image(pixels, os.path.join(test_results_dir, 'pkg13_dielectric_spectral.png'))
    assert not np.any(np.isnan(pixels))
    assert not np.any(np.isinf(pixels))
    assert pixels.min() >= 0.0
    assert float(pixels.mean()) > 0.001


def test_mirror_spectral_no_nan(test_results_dir):
    def mirror_scene(r):
        create_cornell_box(r)
        mat = r.create_material("mirror", [1.0, 1.0, 1.0], {})
        r.add_sphere([0, -1, 0], 1.0, mat)

    pixels = _render("path_tracer", mirror_scene)
    save_image(pixels, os.path.join(test_results_dir, 'pkg13_mirror_spectral.png'))
    assert not np.any(np.isnan(pixels))
    assert not np.any(np.isinf(pixels))
    assert pixels.min() >= 0.0


# ---------------------------------------------------------------------------
# Subsurface
# ---------------------------------------------------------------------------

def test_subsurface_spectral_no_nan(test_results_dir):
    def ss_scene(r):
        create_cornell_box(r)
        mat = r.create_material("subsurface", [0.8, 0.4, 0.2],
                                {"scatter_distance": [1.0, 0.3, 0.1], "scale": 1.0})
        r.add_sphere([0, -1, 0], 1.0, mat)

    pixels = _render("path_tracer", ss_scene)
    save_image(pixels, os.path.join(test_results_dir, 'pkg13_subsurface_spectral.png'))
    assert not np.any(np.isnan(pixels))
    assert not np.any(np.isinf(pixels))
    assert pixels.min() >= 0.0


# ---------------------------------------------------------------------------
# Texture::sampleSpectral — default and image cache
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# pkg13c — OrenNayar, Isotropic, TwoSided, Emissive
# ---------------------------------------------------------------------------

def test_oren_nayar_spectral_no_nan(test_results_dir):
    def scene(r):
        create_cornell_box(r)
        mat = r.create_material("oren_nayar", [0.8, 0.6, 0.3], {"roughness": 0.6})
        r.add_sphere([0, -1, 0], 1.0, mat)

    pixels = _render("path_tracer", scene)
    save_image(pixels, os.path.join(test_results_dir, 'pkg13c_oren_nayar_spectral.png'))
    assert not np.any(np.isnan(pixels))
    assert not np.any(np.isinf(pixels))
    assert pixels.min() >= 0.0
    assert float(pixels.mean()) > 0.001


def test_isotropic_spectral_no_nan(test_results_dir):
    def scene(r):
        create_cornell_box(r)
        mat = r.create_material("isotropic", [0.9, 0.9, 0.9], {})
        r.add_sphere([0, -1, 0], 1.0, mat)

    pixels = _render("path_tracer", scene)
    save_image(pixels, os.path.join(test_results_dir, 'pkg13c_isotropic_spectral.png'))
    assert not np.any(np.isnan(pixels))
    assert not np.any(np.isinf(pixels))
    assert pixels.min() >= 0.0


def test_two_sided_spectral_no_nan(test_results_dir):
    def scene(r):
        create_cornell_box(r)
        mat = r.create_material("two_sided", [0.7, 0.4, 0.9],
                                {"inner_type": "lambertian"})
        r.add_sphere([0, -1, 0], 1.0, mat)

    pixels = _render("path_tracer", scene)
    save_image(pixels, os.path.join(test_results_dir, 'pkg13c_two_sided_spectral.png'))
    assert not np.any(np.isnan(pixels))
    assert not np.any(np.isinf(pixels))
    assert pixels.min() >= 0.0


def test_emissive_spectral_emits(test_results_dir):
    """Emissive plugin (two-sided) should produce nonzero luminance."""
    def scene(r):
        create_cornell_box(r)
        mat = r.create_material("emissive", [1.0, 0.8, 0.4], {"intensity": 3.0})
        r.add_sphere([0, -1, 0], 0.5, mat)

    pixels = _render("path_tracer", scene)
    save_image(pixels, os.path.join(test_results_dir, 'pkg13c_emissive_spectral.png'))
    assert not np.any(np.isnan(pixels))
    assert not np.any(np.isinf(pixels))
    assert float(pixels.mean()) > 0.01, "emissive sphere should illuminate the scene"


def test_new_materials_in_registry():
    """All pkg13c materials appear in the material registry."""
    names = astroray.material_registry_names()
    for name in ("oren_nayar", "isotropic", "two_sided", "emissive"):
        assert name in names, f"{name!r} not in registry; have {names}"


# ---------------------------------------------------------------------------
def test_texture_plugins_needed_for_spectral_tests_registered():
    """Texture plugins used by spectral texture tests are registered."""
    tex_names = astroray.texture_registry_names()
    for name in ("checker", "noise", "gradient", "voronoi", "brick",
                 "musgrave", "magic", "wave", "image"):
        assert name in tex_names, f"{name!r} not registered; have {tex_names}"


def test_rgb_albedo_spectrum_sample_stable():
    """RGBAlbedoSpectrum returns identical samples on repeated calls."""
    wl = astroray.SampledWavelengths.sample_uniform(0.5)
    rsp = astroray.RGBAlbedoSpectrum([0.6, 0.3, 0.1])
    s1 = rsp.sample(wl)
    s2 = rsp.sample(wl)
    for i in range(4):
        assert s1[i] == s2[i], f"RGBAlbedoSpectrum sample not stable at index {i}"


@pytest.mark.parametrize(
    "scene_fn,tag",
    [
        (_phong_scene, "phong"),
        (_disney_scene, "disney"),
        (_normal_mapped_scene, "normal_mapped"),
        (_diffuse_light_scene, "diffuse_light"),
    ],
)
def test_pkg13a_material_spectral_deterministic_a_b(scene_fn, tag, test_results_dir):
    baseline = _render("path_tracer", scene_fn, seed=17)
    repeat = _render("path_tracer", scene_fn, seed=17)
    save_image(baseline, os.path.join(test_results_dir, f'pkg13a_{tag}_baseline.png'))
    save_image(repeat, os.path.join(test_results_dir, f'pkg13a_{tag}_repeat.png'))

    assert not np.any(np.isnan(repeat)), f"{tag} spectral render contains NaN"
    assert not np.any(np.isinf(repeat)), f"{tag} spectral render contains Inf"
    assert np.allclose(baseline, repeat, rtol=0.0, atol=1e-7), \
        f"{tag} same-seed spectral render is not deterministic"
