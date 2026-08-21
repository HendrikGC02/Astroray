"""pkg195 Stage B — spectral lamp presets (engine-level gate).

The addon's _build_emission_dict emits, for a light in spectrum_mode='preset'
(or 'custom_profile'), the dict this test feeds directly to the engine:
    {'mode': 'measured_spd', 'profile_name': <name>}          # white light colour
    {'mode': 'composite', 'base': {...measured...},            # tinted (gel) light
     'filter_rgb': [r, g, b]}
Both are already parsed by module/blender_module.cpp::parseEmissionSpectrum.

Gate B (from the spec): a point lamp in preset/sodium_vapor over a white sphere,
visible band CPU -> amber hue (R > G > 3*B in linear mean); switching to cie_f2
changes per-channel ratios by > 10%.

This test validates the engine + emission-dict physics on the CPU (set_use_gpu
False). The full addon-UI wiring is exercised by the headless-Blender check in the
PR body (blender_addon/__init__.py DATA_PT_custom_raytracer_light path).

A companion note: sodium's SPD is a narrow ~589 nm spike whose single-stratum
power() estimate is zero; pkg195 adds a uniform-selection fallback in
PowerLightSampler for that degenerate CDF so the lamp is not silently dropped.
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


def _lamp_scene_channels(emission, spp=64, width=48, height=48):
    """White sphere lit by a point lamp with the given emission dict, rendered in
    the visible band on the CPU. Returns per-channel linear means."""
    astroray.load_spectral_profiles(PROFILES_BIN)
    r = astroray.Renderer()
    r.set_use_gpu(False)
    r.setup_camera(
        look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=35, aspect_ratio=1.0, aperture=0.0, focus_dist=3.0,
        width=width, height=height,
    )
    r.set_seed(101)
    r.set_background_color([0.0, 0.0, 0.0])
    mat = r.create_material("lambertian", [1.0, 1.0, 1.0], {})  # white sphere
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.add_point_light(position=[2.0, 2.0, 2.0], emission=emission,
                      intensity=60.0, radius=0.0)
    r.set_wavelength_range(380.0, 780.0)
    r.set_integrator("multiwavelength_path_tracer")
    pixels = np.array(r.render(spp, 6, None, False), dtype=np.float32)  # linear
    return pixels.reshape(-1, 3).mean(axis=0)


@pytest.mark.skipif(not HAS_PROFILES, reason="profiles.bin not found")
def test_b1_sodium_lamp_is_amber():
    """B1: sodium_vapor preset lamp -> amber (R > G > 3*B) linear, and emits.

    pkg214 adds the explicit >0 floor: the pre-fix defect was a black render
    (the aliased D-line was missed by every hero wavelength), and the ratio
    check alone infers non-zero only indirectly.
    """
    ch = _lamp_scene_channels({"mode": "measured_spd", "profile_name": "sodium_vapor"})
    R, G, B = float(ch[0]), float(ch[1]), float(ch[2])
    print(f"[B1] sodium linear RGB = ({R:.4f}, {G:.4f}, {B:.4f})")
    assert R > 1e-3, (
        f"B1 FAIL: sodium lamp emits no light -- R={R:.4f} <= 1e-3"
    )
    assert R > G > 3.0 * B, (
        f"B1 FAIL: sodium lamp not amber -- R={R:.4f} G={G:.4f} B={B:.4f} "
        f"(need R > G > 3*B)"
    )
    print("[B1 PASS] sodium lamp is amber")


@pytest.mark.skipif(not HAS_PROFILES, reason="profiles.bin not found")
def test_b2_cie_f2_differs_from_sodium():
    """B2: switching sodium_vapor -> cie_f2 changes per-channel ratios by > 10%."""
    sod = _lamp_scene_channels({"mode": "measured_spd", "profile_name": "sodium_vapor"})
    f2 = _lamp_scene_channels({"mode": "measured_spd", "profile_name": "cie_f2"})
    # Compare per-channel where the reference (f2, broadband) is non-negligible.
    rel = np.abs(sod / np.maximum(f2, 1e-6) - 1.0)
    print(f"[B2] sodium = {sod}")
    print(f"[B2] cie_f2 = {f2}")
    print(f"[B2] per-channel relative change = {rel}")
    assert rel.max() > 0.10, (
        f"B2 FAIL: sodium vs cie_f2 per-channel change {rel.max():.3f} <= 0.10"
    )
    print(f"[B2 PASS] sodium vs cie_f2 max per-channel change = {rel.max():.2f}")


@pytest.mark.skipif(not HAS_PROFILES, reason="profiles.bin not found")
def test_b3_composite_gel_tint_path():
    """B3: the composite (non-white gel tint) emission dict -- what
    _build_emission_dict emits when the lamp colour is not white -- renders and a
    blue gel measurably suppresses the amber sodium output vs no gel."""
    plain = _lamp_scene_channels({"mode": "measured_spd", "profile_name": "sodium_vapor"})
    # Blue gel: filters out the amber; the composite base is the sodium SPD.
    gelled = _lamp_scene_channels({
        "mode": "composite",
        "base": {"mode": "measured_spd", "profile_name": "sodium_vapor"},
        "filter_rgb": [0.2, 0.2, 1.0],
    })
    print(f"[B3] plain sodium = {plain}")
    print(f"[B3] blue-gel     = {gelled}")
    assert np.all(np.isfinite(gelled))
    # The blue gel must attenuate the (amber-dominant) red channel.
    assert gelled[0] < plain[0] * 0.9, (
        f"B3 FAIL: blue gel did not suppress sodium's red channel "
        f"({gelled[0]:.4f} vs {plain[0]:.4f})"
    )
    print("[B3 PASS] composite gel tint attenuates as expected")
