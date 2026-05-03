"""Energy conservation and basic output tests for the seven migrated material plugins."""
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

PLUGINS = [
    "metal", "dielectric", "glass", "light", "emission", "diffuse_light",
    "phong", "subsurface", "normal_mapped", "disney", "mirror",
    "thin_glass", "architectural_glass",
]


def test_all_plugins_in_registry():
    names = astroray.material_registry_names()
    for p in PLUGINS:
        assert p in names, f"'{p}' not in registry"


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------

def _renderer():
    r = astroray.Renderer()
    r.setup_camera(
        look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
        width=32, height=32,
    )
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_integrator("path_tracer")
    return r


def _render_mat(mat_id, renderer, samples=32):
    renderer.add_sphere([0, 0, 0], 1.0, mat_id)
    pixels = np.array(renderer.render(samples_per_pixel=samples, max_depth=6), dtype=np.float32)
    return pixels


def _reflectance(mat_type, color, params=None, samples=32):
    """Estimate reflectance as mean pixel value relative to pure white lambertian."""
    params = params or {}
    # Reference: pure white lambertian in same scene
    r_ref = _renderer()
    ref_id = r_ref.create_material("lambertian", [1.0, 1.0, 1.0], {})
    ref_pixels = _render_mat(ref_id, r_ref, samples)
    ref_mean = float(np.mean(ref_pixels))

    r = _renderer()
    mat_id = r.create_material(mat_type, color, params)
    pixels = _render_mat(mat_id, r, samples)
    mat_mean = float(np.mean(pixels))

    # Non-emissive materials must not exceed white lambertian significantly
    return mat_mean, ref_mean


# ---------------------------------------------------------------------------
# Energy conservation tests (reflectance ≤ 1.0 relative to white lambertian)
# ---------------------------------------------------------------------------

def test_metal_energy_conservation():
    mat_mean, ref_mean = _reflectance("metal", [0.9, 0.9, 0.9], {"roughness": 0.3})
    assert mat_mean <= ref_mean * 1.1, \
        f"Metal mean={mat_mean:.3f} exceeds white lambertian {ref_mean:.3f}"


def test_metal_smooth_energy_conservation():
    mat_mean, ref_mean = _reflectance("metal", [0.9, 0.9, 0.9], {"roughness": 0.02})
    assert mat_mean <= ref_mean * 1.1, \
        f"Metal (smooth) mean={mat_mean:.3f} exceeds white lambertian {ref_mean:.3f}"


def test_dielectric_energy_conservation():
    mat_mean, ref_mean = _reflectance("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})
    assert mat_mean <= ref_mean * 1.1, \
        f"Dielectric mean={mat_mean:.3f} exceeds white lambertian {ref_mean:.3f}"


def test_glass_alias_energy_conservation():
    mat_mean, ref_mean = _reflectance("glass", [1.0, 1.0, 1.0], {"ior": 1.5})
    assert mat_mean <= ref_mean * 1.1, \
        f"Glass mean={mat_mean:.3f} exceeds white lambertian {ref_mean:.3f}"


def test_phong_energy_conservation():
    for shininess in [8.0, 32.0, 100.0]:
        mat_mean, ref_mean = _reflectance("phong", [0.8, 0.8, 0.8], {"shininess": shininess})
        assert mat_mean <= ref_mean * 1.1, \
            f"Phong(shininess={shininess}) mean={mat_mean:.3f} exceeds white lambertian {ref_mean:.3f}"


def test_subsurface_energy_conservation():
    mat_mean, ref_mean = _reflectance("subsurface", [0.9, 0.6, 0.5])
    assert mat_mean <= ref_mean * 1.1, \
        f"Subsurface mean={mat_mean:.3f} exceeds white lambertian {ref_mean:.3f}"


def test_disney_energy_conservation():
    for params in [
        {"metallic": 0.0, "roughness": 0.5},
        {"metallic": 1.0, "roughness": 0.2},
        {"clearcoat": 1.0, "clearcoat_gloss": 0.8},
    ]:
        mat_mean, ref_mean = _reflectance("disney", [0.8, 0.8, 0.8], params)
        assert mat_mean <= ref_mean * 1.1, \
            f"Disney({params}) mean={mat_mean:.3f} exceeds white lambertian {ref_mean:.3f}"


def test_mirror_energy_conservation():
    mat_mean, ref_mean = _reflectance("mirror", [1.0, 1.0, 1.0])
    assert mat_mean <= ref_mean * 1.1, \
        f"Mirror mean={mat_mean:.3f} exceeds white lambertian {ref_mean:.3f}"


# ---------------------------------------------------------------------------
# Emissive materials: must actually emit
# ---------------------------------------------------------------------------

def test_diffuse_light_emits():
    r = _renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    mat_id = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 1.0})
    pixels = _render_mat(mat_id, r, samples=32)
    mean_val = float(np.mean(pixels))
    assert mean_val > 0.01, f"DiffuseLight mean={mean_val:.4f} — not emitting"
    assert mean_val <= 1.05, f"DiffuseLight mean={mean_val:.4f} exceeds intensity"


def test_emission_alias_emits():
    r = _renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    mat_id = r.create_material("emission", [1.0, 1.0, 1.0], {"intensity": 1.0})
    pixels = _render_mat(mat_id, r, samples=32)
    assert float(np.mean(pixels)) > 0.01, "emission alias not emitting"


# ---------------------------------------------------------------------------
# Basic output: non-negative, finite
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mat_type,color,params", [
    ("metal",       [0.8, 0.8, 0.8], {"roughness": 0.3}),
    ("glass",       [1.0, 1.0, 1.0], {"ior": 1.5}),
    ("phong",       [0.8, 0.5, 0.3], {"shininess": 50.0}),
    ("subsurface",  [0.9, 0.6, 0.5], {}),
    ("disney",      [0.8, 0.6, 0.4], {"metallic": 0.5, "roughness": 0.3}),
    ("mirror",      [1.0, 1.0, 1.0], {}),
])
def test_non_negative_output(mat_type, color, params):
    r = _renderer()
    mat_id = r.create_material(mat_type, color, params)
    pixels = _render_mat(mat_id, r, samples=16)
    assert pixels.min() >= 0.0, f"{mat_type} produced negative pixel value"
    assert np.isfinite(pixels).all(), f"{mat_type} produced non-finite pixel value"
