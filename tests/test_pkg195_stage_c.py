"""pkg195 Stage C — spectrum sources + honest material nodes (engine gates).

Stage C makes spectral authoring real end-to-end:
  1. astroray.register_spectral_profile(name, lmin, step, values) — runtime SPDs.
  2. In-band Replace mode — an authored SPD drives ALL wavelengths, bypassing the
     Jakob-Hanika RGB round-trip (set_material_spectral_profile(..., replace=True)).
  3. IR/UV Response is non-destructive — attaching a band profile in ExtendOnly
     mode leaves the visible render pixel-identical.
  4. Sellmeier manual B/C coefficients now drive dispersion (were silently dropped).

These gates run at the engine level on the CPU (set_use_gpu(False)); the addon-UI
wiring (Drawn Spectrum CurveMapping, Spectrum Preset / IR/UV nodes) is exercised by
the headless-Blender check recorded in the PR body. The Drawn Spectrum's engine
path is covered here by registering the same narrow-band SPD the curve produces.
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

# Schott BK7 Sellmeier terms (optical_presets.h / addon socket defaults).
BK7_B = [1.03961212, 0.231792344, 1.01046945]
BK7_C = [0.00600069867, 0.0200179144, 103.560653]

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")


# --------------------------------------------------------------------------- #
# C1 — register_spectral_profile roundtrip
# --------------------------------------------------------------------------- #

def test_c1_register_profile_roundtrip():
    """register → names() lists it → reflectance interpolates vs a numpy oracle."""
    name = "__test__/pkg195c/ramp"
    lmin, step = 400.0, 5.0
    # A linear ramp 0..1 over 400..600 nm (41 samples).
    values = [i / 40.0 for i in range(41)]
    assert astroray.register_spectral_profile(name, lmin, step, values)

    assert name in astroray.spectral_profile_names()

    grid = np.array([lmin + i * step for i in range(len(values))])
    oracle = np.array(values)
    # Sample on the grid and between grid points; compare to numpy linear interp.
    for wl in [400.0, 402.5, 455.0, 512.5, 597.5, 600.0]:
        got = astroray.spectral_profile_reflectance(name, wl)
        want = float(np.interp(wl, grid, oracle))
        assert abs(got - want) < 1e-5, f"λ={wl}: got {got}, want {want}"

    # Clamps outside the grid to the boundary samples.
    assert abs(astroray.spectral_profile_reflectance(name, 300.0) - values[0]) < 1e-6
    assert abs(astroray.spectral_profile_reflectance(name, 900.0) - values[-1]) < 1e-6
    print("[C1 PASS] register_spectral_profile roundtrip + interpolation exact")


def test_c1b_register_profile_overwrite_in_place():
    """Re-registering the same runtime name overwrites its samples (no duplicate)."""
    name = "__test__/pkg195c/overwrite"
    assert astroray.register_spectral_profile(name, 500.0, 10.0, [0.1, 0.1, 0.1])
    n_before = astroray.spectral_profile_names().count(name)
    assert astroray.register_spectral_profile(name, 500.0, 10.0, [0.9, 0.9, 0.9])
    assert astroray.spectral_profile_names().count(name) == n_before == 1
    assert abs(astroray.spectral_profile_reflectance(name, 505.0) - 0.9) < 1e-6
    print("[C1b PASS] overwrite in place, no duplicate name")


def test_c1c_register_clamps_reflectance_to_unit_range():
    """PR #610 review hardening: values passed to register_spectral_profile are
    clamped to the documented [0,1] reflectance range at registration, so a >1
    curve cannot inject energy in ProfileMode::Replace. Stored samples clamp; a
    negative clamps to 0."""
    name = "__test__/pkg195c/hot"
    # 2.0 everywhere over 300..1000 nm — a physically-impossible reflectance.
    n = int((1000.0 - 300.0) / 5.0) + 1
    assert astroray.register_spectral_profile(name, 300.0, 5.0, [2.0] * n)
    for wl in (300.0, 550.0, 999.0):
        r = astroray.spectral_profile_reflectance(name, wl)
        assert r <= 1.0 + 1e-6, f"λ={wl}: stored reflectance {r} not clamped to <= 1"
        assert abs(r - 1.0) < 1e-6, f"λ={wl}: expected clamp to 1.0, got {r}"
    neg = "__test__/pkg195c/neg"
    assert astroray.register_spectral_profile(neg, 300.0, 5.0, [-0.5] * n)
    assert astroray.spectral_profile_reflectance(neg, 550.0) >= 0.0
    print("[C1c PASS] register clamps reflectance samples to [0,1]")


def test_c1d_replace_energy_bounded_by_clamp():
    """The clamp keeps a Replace-mode render's energy bounded: a would-be >1
    reflectance profile renders no brighter than a =1 profile (both clamp to 1),
    and stays finite."""
    if not HAS_PROFILES:
        import pytest as _pytest
        _pytest.skip("profiles.bin not found")
    n = int((1000.0 - 300.0) / 5.0) + 1
    astroray.register_spectral_profile("__test__/pkg195c/unit", 300.0, 5.0, [1.0] * n)
    astroray.register_spectral_profile("__test__/pkg195c/over", 300.0, 5.0, [5.0] * n)
    unit = _replace_mode_channels("__test__/pkg195c/unit")
    over = _replace_mode_channels("__test__/pkg195c/over")
    assert np.all(np.isfinite(over)), f"over-unit render non-finite: {over}"
    # Clamped to identical stored data -> per-channel means match (same RNG seed).
    assert np.allclose(unit, over, atol=1e-5), (
        f"C1d FAIL: >1 profile ({over}) not bounded to =1 profile ({unit}) — clamp "
        f"did not hold"
    )
    print(f"[C1d PASS] Replace energy bounded by clamp (unit={unit}, over={over})")


# --------------------------------------------------------------------------- #
# Shared render helper for the Replace-mode gates.
# --------------------------------------------------------------------------- #

def _replace_mode_channels(profile_name, spp=96, width=48, height=48):
    """White sphere whose per-λ reflectance is `profile_name` in Replace mode,
    lit by a white point lamp, visible band, CPU MW integrator. Returns per-channel
    linear means."""
    if HAS_PROFILES:
        astroray.load_spectral_profiles(PROFILES_BIN)
    r = astroray.Renderer()
    r.set_use_gpu(False)
    r.setup_camera(
        look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=35, aspect_ratio=1.0, aperture=0.0, focus_dist=3.0,
        width=width, height=height,
    )
    r.set_seed(195)
    r.set_background_color([0.0, 0.0, 0.0])
    mat = r.create_material("lambertian", [1.0, 1.0, 1.0], {})  # neutral white base
    r.set_material_spectral_profile(mat, profile_name, True)     # Replace mode
    r.add_sphere([0, 0, 0], 1.0, mat)
    emission = {"mode": "rgb", "color": [1.0, 1.0, 1.0]}
    r.add_point_light(position=[2.0, 2.0, 2.0], emission=emission,
                      intensity=60.0, radius=0.0)
    r.set_wavelength_range(380.0, 780.0)
    r.set_integrator("multiwavelength_path_tracer")
    pixels = np.array(r.render(spp, 6, None, False), dtype=np.float32)  # linear
    return pixels.reshape(-1, 3).mean(axis=0)


@pytest.mark.skipif(not HAS_PROFILES, reason="profiles.bin not found")
def test_c2_preset_replace_mode_red_vs_green():
    """C2: paint_red vs grass_green in Replace mode -> R-dominant vs G-dominant.
    Anti-regression for the |Δmean|=0.00028 in-band no-op the old white-Disney
    path produced (design doc §1.2)."""
    red = _replace_mode_channels("paint_red")
    green = _replace_mode_channels("grass_green")
    print(f"[C2] paint_red   linear RGB = {red}")
    print(f"[C2] grass_green linear RGB = {green}")
    assert red[0] > red[1] and red[0] > red[2], f"paint_red not R-dominant: {red}"
    assert green[1] > green[0] and green[1] > green[2], f"grass_green not G-dominant: {green}"
    # The two renders must be clearly distinguishable — NOT the |Δmean|=0.00028
    # no-op the old white-Disney path produced. Use relative signatures (the scene
    # is intentionally dim): paint_red's R channel is far stronger than
    # grass_green's, and grass_green's G/R ratio far exceeds paint_red's.
    assert float(red[0]) > float(green[0]) * 1.5, (
        f"C2 FAIL: paint_red R ({red[0]:.5f}) not >> grass_green R ({green[0]:.5f})")
    red_gr = float(red[1]) / max(float(red[0]), 1e-6)
    green_gr = float(green[1]) / max(float(green[0]), 1e-6)
    assert green_gr > red_gr * 3.0, (
        f"C2 FAIL: G/R signatures too similar (paint_red G/R={red_gr:.3f}, "
        f"grass_green G/R={green_gr:.3f})")
    # And the absolute R-channel delta is >15x the historical 0.00028 no-op.
    assert abs(float(red[0] - green[0])) > 0.005, (
        f"C2 FAIL: R-channel delta {abs(float(red[0]-green[0])):.5f} <= 0.005 "
        f"(historical no-op was 0.00028)")
    print(f"[C2 PASS] Replace-mode preset drives visible hue "
          f"(paint_red G/R={red_gr:.3f} vs grass_green G/R={green_gr:.3f}, "
          f"R-delta={abs(float(red[0]-green[0])):.5f})")


def test_c5_drawn_spectrum_engine_equiv_green_bump():
    """C5 (engine equivalent of the Drawn Spectrum curve): a narrow 550 nm bump SPD
    registered at runtime and attached in Replace mode renders green-dominant vs a
    flat SPD rendering neutral. This is the exact engine path the addon's Drawn
    Spectrum node produces after sample_drawn_spectrum() + register_spectral_profile."""
    lmin, step = 300.0, 5.0
    n = int((1000.0 - lmin) / step) + 1
    bump = []
    flat = []
    for i in range(n):
        wl = lmin + i * step
        # Gaussian-ish bump centered at 550 nm, width ~20 nm.
        bump.append(float(np.exp(-((wl - 550.0) ** 2) / (2 * 20.0 ** 2))))
        flat.append(0.6)
    assert astroray.register_spectral_profile("__test__/pkg195c/bump550", lmin, step, bump)
    assert astroray.register_spectral_profile("__test__/pkg195c/flat", lmin, step, flat)

    green = _replace_mode_channels("__test__/pkg195c/bump550")
    neutral = _replace_mode_channels("__test__/pkg195c/flat")
    print(f"[C5] 550nm-bump  linear RGB = {green}")
    print(f"[C5] flat SPD    linear RGB = {neutral}")
    assert green[1] > green[0] and green[1] > green[2], f"550 bump not green-dominant: {green}"
    # The flat SPD must be near-neutral (channels within 15% of each other).
    mx, mn = float(neutral.max()), float(neutral.min())
    assert (mx - mn) / max(mx, 1e-6) < 0.15, f"flat SPD not neutral: {neutral}"
    print("[C5 PASS] drawn-equivalent 550 nm bump is green; flat SPD is neutral")


# --------------------------------------------------------------------------- #
# C3 — IR/UV Response non-destructiveness (ExtendOnly leaves visible identical)
# --------------------------------------------------------------------------- #

def _red_material_visible(with_band_profile, spp=64, width=48, height=48):
    """Red lambertian sphere, visible band, CPU MW integrator. Optionally attach a
    constant IR-band (700-1000 nm) profile in ExtendOnly mode (what the redesigned
    IR/UV Response node does). Returns the raw pixel array."""
    r = astroray.Renderer()
    r.set_use_gpu(False)
    r.setup_camera(
        look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=35, aspect_ratio=1.0, aperture=0.0, focus_dist=3.0,
        width=width, height=height,
    )
    r.set_seed(4242)
    r.set_background_color([0.0, 0.0, 0.0])
    mat = r.create_material("lambertian", [0.9, 0.1, 0.1], {})  # red base
    if with_band_profile:
        lmin, step = 300.0, 5.0
        n = int((1000.0 - lmin) / step) + 1
        band = [0.5 if 700.0 <= (lmin + i * step) <= 1000.0 else 0.0 for i in range(n)]
        astroray.register_spectral_profile("__test__/pkg195c/iruv_band", lmin, step, band)
        r.set_material_spectral_profile(mat, "__test__/pkg195c/iruv_band", False)  # ExtendOnly
    r.add_sphere([0, 0, 0], 1.0, mat)
    emission = {"mode": "rgb", "color": [1.0, 1.0, 1.0]}
    r.add_point_light(position=[2.0, 2.0, 2.0], emission=emission,
                      intensity=60.0, radius=0.0)
    r.set_wavelength_range(380.0, 780.0)
    r.set_integrator("multiwavelength_path_tracer")
    return np.array(r.render(spp, 6, None, False), dtype=np.float32)


def test_c3_iruv_extend_only_visible_identical():
    """C3: an ExtendOnly IR-band profile (the redesigned IR/UV node) must NOT change
    the visible render — byte-identical to the same red material without it."""
    without = _red_material_visible(False)
    with_band = _red_material_visible(True)
    assert np.array_equal(without, with_band), (
        "C3 FAIL: IR/UV ExtendOnly band profile changed the visible render "
        f"(max abs diff {float(np.abs(without - with_band).max()):.3e})"
    )
    print("[C3 PASS] IR/UV ExtendOnly band profile is visible-band byte-identical")


# --------------------------------------------------------------------------- #
# C4 — Sellmeier manual B/C coefficients now drive dispersion
# --------------------------------------------------------------------------- #

def _prism_scene(glass_params, seed=17):
    from scenes.prism_reference import (
        WIDTH, HEIGHT, SAMPLES, MAX_DEPTH, _add_panel, add_triangular_prism,
        red_blue_centroid_separation,
    )
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([0.8, 0.9, 1.0])
    red = r.create_material("lambertian", [1.0, 0.05, 0.03], {})
    white = r.create_material("lambertian", [0.92, 0.92, 0.90], {})
    blue = r.create_material("lambertian", [0.03, 0.08, 1.0], {})
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 5.0})
    _add_panel(r, red, -2.0, -0.4, -1.79)
    _add_panel(r, white, -0.45, 0.45, -1.80)
    _add_panel(r, blue, 0.4, 2.0, -1.78)
    r.add_triangle([-1.5, 1.6, 1.5], [1.5, 1.6, 1.5], [1.5, 1.6, -1.2], light)
    r.add_triangle([-1.5, 1.6, 1.5], [1.5, 1.6, -1.2], [-1.5, 1.6, -1.2], light)
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], glass_params)
    add_triangular_prism(r, glass)
    r.setup_camera([0.0, 0.0, 4.2], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   38.0, 1.0, 0.0, 4.2, WIDTH, HEIGHT)
    r.set_seed(seed)
    pixels = np.asarray(r.render(SAMPLES, MAX_DEPTH, None, True), dtype=np.float32)
    return pixels, red_blue_centroid_separation(pixels)


def test_c4_sellmeier_manual_bc_matches_preset(test_results_dir):
    """C4: manual BK7 B/C (no preset) reproduces the bk7 preset's prism dispersion.
    Before Stage C, sellmeier_b/sellmeier_c were exported but no engine code read
    them (silent no-op); the manual-coefficient UI did nothing."""
    from base_helpers import save_image
    preset_px, preset_sep = _prism_scene({"sellmeier_preset": "bk7"})
    manual_px, manual_sep = _prism_scene({"sellmeier_b": BK7_B, "sellmeier_c": BK7_C})
    save_image(preset_px, os.path.join(test_results_dir, "pkg195c_prism_bk7_preset.png"))
    save_image(manual_px, os.path.join(test_results_dir, "pkg195c_prism_bk7_manual.png"))
    print(f"[C4] bk7 preset red/blue separation = {preset_sep:.3f}px")
    print(f"[C4] manual B/C  red/blue separation = {manual_sep:.3f}px")
    # Manual coefficients must produce real dispersion (a flat-IOR glass gives a
    # much smaller separation), and match the preset within 2%.
    assert manual_sep > 1.0, f"C4 FAIL: manual B/C produced no dispersion ({manual_sep:.3f}px)"
    rel = abs(manual_sep - preset_sep) / max(preset_sep, 1e-6)
    assert rel < 0.02, (
        f"C4 FAIL: manual B/C separation {manual_sep:.3f} vs preset {preset_sep:.3f} "
        f"differ {rel*100:.2f}% (> 2%)"
    )
    print(f"[C4 PASS] manual Sellmeier B/C matches bk7 preset within {rel*100:.2f}%")
