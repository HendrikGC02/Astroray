"""pkg195 Stage A — MultiwavelengthPathTracer dedicated-light NEE.

Before this package the MW integrator had no light sampling of any kind, so every
Blender lamp (a dedicated astroray::Light) was invisible and lamp-lit scenes
rendered black outside the visible band (measured mean 0.0003). Stage A ports the
in-header pathTraceSpectral dedicated-light NEE + two-sided MIS into the MW
integrator (CPU only; wavefront GPU kernels untouched).

Gates (from the spec):
  A1: snow sphere + dedicated blackbody sun, band 700-1000 nm -> mean > 0.05.
  A2: snow vs water_clear NIR mean-ratio > 2.
  A3: visible-band regression -- MW vs default path_tracer on a lamp-lit scene,
      per-channel mean-ratio in [0.95, 1.05], LINEAR (apply_gamma=False).

All renders force CPU (set_use_gpu(False)): the NEE fix lives in the CPU
integrator, and the pkg54 GPU MW megakernel keeps its current behaviour.
"""
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

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_BIN = os.path.join(REPO_ROOT, "data", "spectral_profiles", "profiles.bin")
HAS_PROFILES = os.path.exists(PROFILES_BIN)

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")


def _nir_sphere_render(profile, spp=24, width=48, height=48):
    """Sphere with `profile` lit by a dedicated blackbody sun, rendered in the
    700-1000 nm band on the CPU MW integrator. Returns linear luminance pixels.

    The sun is a 3000 K blackbody: its Wien peak (~966 nm) lands inside the
    700-1000 nm band, so after the pkg122 photopic normalization it still carries
    real NIR energy (a hot 5778 K sun normalizes almost all of its weight into the
    visible band, leaving the NIR tail too dim to exercise the gate meaningfully)."""
    astroray.load_spectral_profiles(PROFILES_BIN)
    r = astroray.Renderer()
    r.set_use_gpu(False)
    r.setup_camera(
        look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=35, aspect_ratio=1.0, aperture=0.0, focus_dist=3.0,
        width=width, height=height,
    )
    r.set_seed(7)
    r.set_background_color([0.0, 0.0, 0.0])  # black bg: only the lit sphere shows

    mat = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
    r.set_material_spectral_profile(mat, profile)
    r.add_sphere([0, 0, 0], 1.0, mat)

    # Dedicated blackbody sun coming from the camera-facing upper hemisphere so
    # the visible face of the sphere is lit. A distant light's `direction` is the
    # direction the light travels (points FROM the light).
    emission = {"mode": "blackbody", "temperature_K": 3000.0, "tint_rgb": [1, 1, 1]}
    r.add_sun_light_dedicated(
        direction=[-0.25, -0.35, -1.0], angular_diameter=0.0093,
        emission=emission, intensity=25.0,
    )

    r.set_wavelength_range(700.0, 1000.0)
    r.set_output_mode("luminance")
    r.set_integrator("multiwavelength_path_tracer")
    # apply_gamma=False -> linear energy gate (memory gamma-furnace-cannot-detect-energy-gain).
    return np.array(r.render(spp, 4, None, False), dtype=np.float32)


@pytest.mark.skipif(not HAS_PROFILES, reason="profiles.bin not found")
def test_a1_nir_snow_sphere_lit_by_dedicated_sun():
    """A1: snow sphere + dedicated blackbody sun in NIR must be lit (mean > 0.05,
    was ~0.0003 before the MW-integrator NEE fix)."""
    pixels = _nir_sphere_render("snow")
    assert np.all(np.isfinite(pixels)), "NIR render has non-finite pixels"
    mean = float(pixels.mean())
    assert mean > 0.05, (
        f"A1 FAIL: NIR snow sphere mean {mean:.4f} <= 0.05 -- dedicated sun not seen "
        f"by the MW integrator"
    )
    print(f"[A1 PASS] NIR snow-sphere mean luminance = {mean:.4f}")


@pytest.mark.skipif(not HAS_PROFILES, reason="profiles.bin not found")
def test_a2_nir_snow_brighter_than_water():
    """A2: snow (NIR R~0.76) must be > 2x brighter than water_clear (NIR R~0.03)
    under the same dedicated sun."""
    snow = float(_nir_sphere_render("snow").mean())
    water = float(_nir_sphere_render("water_clear").mean())
    ratio = snow / max(water, 1e-6)
    assert ratio > 2.0, (
        f"A2 FAIL: snow/water NIR mean-ratio {ratio:.2f} <= 2 "
        f"(snow={snow:.4f}, water={water:.4f})"
    )
    print(f"[A2 PASS] snow/water NIR mean-ratio = {ratio:.2f} "
          f"(snow={snow:.4f}, water={water:.4f})")


def _visible_lamp_scene(integrator, spp=96, width=48, height=48):
    """Lambertian sphere lit by a dedicated point light, visible band, CPU.
    Returns per-channel linear means for `integrator`."""
    r = astroray.Renderer()
    r.set_use_gpu(False)
    r.setup_camera(
        look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=40, aspect_ratio=1.0, aperture=0.0, focus_dist=3.0,
        width=width, height=height,
    )
    r.set_seed(20260813)  # fixed, non-zero (seed 0 = random sentinel)
    r.set_background_color([0.0, 0.0, 0.0])

    mat = r.create_material("lambertian", [0.6, 0.5, 0.4], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    emission = {"mode": "rgb", "color": [1.0, 1.0, 1.0]}
    r.add_point_light(position=[2.0, 2.0, 2.0], emission=emission,
                      intensity=40.0, radius=0.0)

    r.set_wavelength_range(380.0, 780.0)
    r.set_integrator(integrator)
    pixels = np.array(r.render(spp, 6, None, False), dtype=np.float32)  # linear
    return pixels.reshape(-1, pixels.shape[-1]).mean(axis=0)


def test_a3_visible_band_regression_vs_default_tracer():
    """A3: on a lamp-lit visible-band scene, the MW integrator must match the
    default path_tracer per-channel within [0.95, 1.05] (linear)."""
    ref = _visible_lamp_scene("path_tracer")
    mw = _visible_lamp_scene("multiwavelength_path_tracer")
    assert np.all(np.isfinite(ref)) and np.all(np.isfinite(mw))
    assert np.all(ref > 1e-4), f"reference scene channel(s) too dark: {ref}"
    ratio = mw / ref
    print(f"[A3] path_tracer per-channel mean = {ref}")
    print(f"[A3] MW          per-channel mean = {mw}")
    print(f"[A3] per-channel ratio = {ratio}")
    assert np.all((ratio > 0.95) & (ratio < 1.05)), (
        f"A3 FAIL: MW vs path_tracer per-channel ratio {ratio} outside [0.95, 1.05]"
    )
    print("[A3 PASS] MW matches default path_tracer within 5% per channel")
