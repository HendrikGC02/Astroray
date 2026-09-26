"""#908 — Principled Volume "Blackbody Intensity" > 1 must NOT be clamped.

Cycles ``svm_node_principled_volume`` (intern/cycles/kernel/svm/closure.h,
Apache-2.0) uses the socket raw: emission = tint · σ_SB·1e-6/π · mix(1, T⁴, I)
· rec709_to_rgb(blackbody_color_rec709(T)) per unit length, and Blender stores
I > 1 (the showcase fire uses 3.0). Astroray clamped I to [0, 1] on CPU and GPU,
so that fire rendered 3× dim (AgX: dimmer AND redder).

Gates pin SCENE-LINEAR emission of an emission-only slab (density 0, thickness
L) against Cycles' formula computed here independently (the vendored Rec.709
polynomial of test_pkg270_blackbody_furnace, which matches Planck·CIE-1931 to
4 digits). Channels < 20 % of the max are excluded: Astroray integrates the true
Planck SPD (documented pkg270 divergence), which differs in the tiny channels.
"""

from __future__ import annotations

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

import astroray
from test_pkg270_blackbody_furnace import cycles_blackbody_rec709, cycles_intensity

SEED = 908
THICK = 2.0


def _gpu_available() -> bool:
    return astroray.__features__.get("cuda", False) and astroray.Renderer().gpu_available


def _render(r, w, h, spp=1024):
    img = np.asarray(r.render(spp, 2, None, False), dtype=np.float64)
    return img.reshape(h, w, 3) if img.ndim == 1 else img


def _slab(use_gpu, T, I, w=16, h=16, dist=6.0):
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 2)
    r.set_use_gpu(use_gpu)
    if use_gpu:
        r.set_wavelength_range(380.0, 780.0)
        r.set_output_mode("srgb")
    r.add_homogeneous_medium([-10.0, -10.0, -4.0], [10.0, 10.0, -4.0 + THICK],
                             0.0, [0.0, 0.0, 0.0], [1.0, 1.0, 1.0], 0.0,
                             blackbody_intensity=I, blackbody_temperature=T)
    r.setup_camera([0.0, 0.0, 0.001], [0.0, 0.0, -dist], [0.0, 1.0, 0.0],
                   20.0, w / h, 0.0, dist, w, h)
    return _render(r, w, h)


def _center(img, half=3):
    h, w = img.shape[:2]
    return img[h // 2 - half:h // 2 + half, w // 2 - half:w // 2 + half].reshape(-1, 3).mean(axis=0)


def _cycles_linear(T, I):
    return cycles_intensity(T, I) * THICK * np.array(cycles_blackbody_rec709(T))


def _check_vs_cycles(rgb, T, I, tag):
    ref = _cycles_linear(T, I)
    ratio = rgb / np.where(np.abs(ref) > 1e-12, ref, 1e-12)
    print(f"\n[#908 {tag} T={T} I={I}] ours={rgb.round(4)} cycles={ref.round(4)} ratio={ratio.round(4)}")
    for c in range(3):
        if ref[c] >= 0.2 * ref.max():
            assert 0.9 <= ratio[c] <= 1.1, (c, ratio, rgb, ref)


@pytest.mark.cpu
def test_emission_unit_is_linear_in_intensity_above_one():
    lams = [450.0, 550.0, 600.0, 650.0]
    one = np.array(astroray.volume_blackbody_emission(3000.0, 1.0, [1, 1, 1], lams))
    three = np.array(astroray.volume_blackbody_emission(3000.0, 3.0, [1, 1, 1], lams))
    expected = cycles_intensity(3000.0, 3.0) / cycles_intensity(3000.0, 1.0)  # ~3.0
    print(f"\n[#908 unit] I=3/I=1 = {(three / one).round(4)} expected {expected:.4f}")
    np.testing.assert_allclose(three / one, expected, rtol=1e-4)


@pytest.mark.cpu
@pytest.mark.parametrize("T", [1500.0, 3000.0, 6500.0])
def test_cpu_slab_blackbody_intensity_3_matches_cycles(T):
    _check_vs_cycles(_center(_slab(False, T, 3.0)), T, 3.0, "cpu")


@pytest.mark.gpu
@pytest.mark.parametrize("T", [1500.0, 3000.0, 6500.0])
def test_gpu_slab_blackbody_intensity_3_matches_cycles(T):
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    _check_vs_cycles(_center(_slab(True, T, 3.0)), T, 3.0, "gpu")


def _grid(use_gpu, I, w=24, h=24, n=16):
    """Temperature-grid path (T = socket × grid), the showcase fire's route."""
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 2)
    r.set_use_gpu(use_gpu)
    if use_gpu:
        r.set_wavelength_range(380.0, 780.0)
        r.set_output_mode("srgb")
    dens = np.full((n, n, n), 1e-6, dtype=np.float32)   # emission only
    temp = np.full((n, n, n), 0.8, dtype=np.float32)    # T = 3000 K × 0.8
    vox = 2.0 / n
    i2o = [vox, 0, 0, -1.0, 0, vox, 0, -1.0, 0, 0, vox, -1.0, 0, 0, 0, 1]
    o2w = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    r.set_volume_grid("fire", dens, [0, 0, 0], i2o, o2w, density_scale=1.0,
                      color=[0.5, 0.5, 0.5], absorption_color=[1.0, 1.0, 1.0],
                      anisotropy=0.0, temperature=temp,
                      blackbody_intensity=I, blackbody_temperature=3000.0)
    r.setup_camera([0.0, 0.0, 6.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   12.0, w / h, 0.0, 6.0, w, h)
    return _center(_render(r, w, h))


def _check_grid(use_gpu):
    T = 3000.0 * 0.8
    rgb = _grid(use_gpu, 3.0)
    _check_vs_cycles(rgb, T, 3.0, "gpu-grid" if use_gpu else "cpu-grid")


@pytest.mark.cpu
def test_cpu_temperature_grid_blackbody_intensity_3_matches_cycles():
    _check_grid(False)


@pytest.mark.gpu
def test_gpu_temperature_grid_blackbody_intensity_3_matches_cycles():
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    _check_grid(True)
