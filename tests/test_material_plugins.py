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


def _render_mat(mat_id, renderer, samples=32, apply_gamma=True):
    renderer.add_sphere([0, 0, 0], 1.0, mat_id)
    pixels = np.array(
        renderer.render(samples, 6, None, apply_gamma), dtype=np.float32)
    return pixels


def _reflectance(mat_type, color, params=None, samples=32):
    """Estimate reflectance as mean pixel value relative to pure white lambertian.

    pkg166: rendered LINEAR (apply_gamma=False). Both the material and its white
    lambertian reference share the same scene and the same linear transfer, so
    the RATIO is unchanged in the conserving case — but a material that CREATES
    energy now reads its true value > 1 instead of being clamped to 1 by gamma,
    so the `mat_mean <= ref_mean * ceiling` gates below can finally catch a gain
    (memory gamma-furnace-cannot-detect-energy-gain).
    """
    params = params or {}
    # Reference: pure white lambertian in same scene
    r_ref = _renderer()
    ref_id = r_ref.create_material("lambertian", [1.0, 1.0, 1.0], {})
    ref_pixels = _render_mat(ref_id, r_ref, samples, apply_gamma=False)
    ref_mean = float(np.mean(ref_pixels))

    r = _renderer()
    mat_id = r.create_material(mat_type, color, params)
    pixels = _render_mat(mat_id, r, samples, apply_gamma=False)
    mat_mean = float(np.mean(pixels))

    # Non-emissive materials must not exceed white lambertian significantly
    return mat_mean, ref_mean


# ---------------------------------------------------------------------------
# Energy conservation tests (reflectance ≤ 1.0 relative to white lambertian)
# ---------------------------------------------------------------------------

def _assert_conserving(label, mat_mean, ref_mean, floor_frac=0.85):
    """pkg166 floor+ceiling pair on a linear white-furnace reflectance ratio.
    The CEILING catches energy GAIN (a material reflecting MORE than the white
    lambertian reference in the same field); the FLOOR catches gross energy LOSS
    or a black/broken BRDF. Both halves are needed — gamma used to clamp the
    ceiling to a passing 1.0. Ratios measured on cf67a92 (linear, RTX 5070 Ti)
     range 0.83 (subsurface) to 1.00 (dielectric/mirror); floors are set below
    the measured ratio with noise margin."""
    assert mat_mean <= ref_mean * 1.1, \
        f"{label} mean={mat_mean:.3f} exceeds white lambertian {ref_mean:.3f} (energy GAIN)"
    assert mat_mean >= ref_mean * floor_frac, \
        f"{label} mean={mat_mean:.3f} < {floor_frac:.2f}x white lambertian " \
        f"{ref_mean:.3f} (energy LOSS / broken-dark BRDF)"


def test_metal_energy_conservation():
    mat_mean, ref_mean = _reflectance("metal", [0.9, 0.9, 0.9], {"roughness": 0.3})
    _assert_conserving("Metal", mat_mean, ref_mean)  # measured ratio 0.948


def test_metal_smooth_energy_conservation():
    mat_mean, ref_mean = _reflectance("metal", [0.9, 0.9, 0.9], {"roughness": 0.02})
    _assert_conserving("Metal (smooth)", mat_mean, ref_mean)  # measured ratio 0.978


def test_dielectric_energy_conservation():
    mat_mean, ref_mean = _reflectance("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})
    _assert_conserving("Dielectric", mat_mean, ref_mean)  # measured ratio 1.002


def test_glass_alias_energy_conservation():
    mat_mean, ref_mean = _reflectance("glass", [1.0, 1.0, 1.0], {"ior": 1.5})
    _assert_conserving("Glass", mat_mean, ref_mean)  # measured ratio 1.000


def test_phong_energy_conservation():
    for shininess in [8.0, 32.0, 100.0]:
        mat_mean, ref_mean = _reflectance("phong", [0.8, 0.8, 0.8], {"shininess": shininess})
        _assert_conserving(f"Phong(shininess={shininess})", mat_mean, ref_mean)  # ratio 0.969-0.974


def test_subsurface_energy_conservation():
    mat_mean, ref_mean = _reflectance("subsurface", [0.9, 0.6, 0.5])
    # Subsurface is a colored ([0.9,0.6,0.5]) material, so it reflects less of
    # the white field than an achromatic one — measured ratio 0.834; lower floor.
    _assert_conserving("Subsurface", mat_mean, ref_mean, floor_frac=0.70)


def test_disney_energy_conservation():
    for params in [
        {"metallic": 0.0, "roughness": 0.5},
        {"metallic": 1.0, "roughness": 0.2},
        {"clearcoat": 1.0, "clearcoat_gloss": 0.8},
    ]:
        mat_mean, ref_mean = _reflectance("disney", [0.8, 0.8, 0.8], params)
        _assert_conserving(f"Disney({params})", mat_mean, ref_mean)  # ratio 0.960-0.969


def test_mirror_energy_conservation():
    mat_mean, ref_mean = _reflectance("mirror", [1.0, 1.0, 1.0])
    _assert_conserving("Mirror", mat_mean, ref_mean)  # measured ratio 1.001


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
