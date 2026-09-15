"""pkg270 — per-wavelength (chromatic) extinction through bounded media.

pkg268 collapsed the Cycles per-channel coefficients to a GREY extinction
(max channel). pkg270 tracks σ_t(λ) with hero-wavelength spectral MIS (pbrt-v4
VolPath, research note pkg270-spectral-tracking-volume-emission-research.md §1).

Gates:
1. Unit — ``principled_volume_spectral_coefficients`` applies the Cycles socket
   formula per wavelength on the JH-upsampled colours (grey colours reproduce
   the RGB formula; a red absorber absorbs blue >> red) and s(λ)+a(λ) <= 1 at
   every wavelength (the exact λ-independent majorant D·maxDensity).
2. Render — the #807 cabinet's Volume Absorption cube (Color (0.85,0.25,0.20),
   density 5) as a slab: the measured per-channel transmittance must be
   MEASURABLY CHROMATIC (red channel far above the grey-collapsed value) and lie
   inside the Cycles cross-check band around Cycles' per-channel Beer–Lambert
   ``exp(-(1-C_c)·D·L)``. Linear render with FLOOR + CEILING (``apply_gamma=False``).
3. Regression — registering then clearing media leaves a grid-free render
   bit-identical (the medium block is gated on registered media).
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

import astroray

SEED = 270222


# --------------------------------------------------------------------------- #
# 1. Unit: per-wavelength coefficients
# --------------------------------------------------------------------------- #

def test_grey_colours_reproduce_rgb_formula():
    lambdas = [420.0, 520.0, 620.0, 720.0]
    s, a = astroray.principled_volume_spectral_coefficients(2.0, [0.5, 0.5, 0.5], [0.25, 0.25, 0.25], lambdas)
    # sigma_s = color*D = 1.0 ; sigma_a = (1-0.5)*(1-sqrt(0.25))*D = 0.5
    for i in range(4):
        assert s[i] == pytest.approx(1.0, abs=0.03), s
        assert a[i] == pytest.approx(0.5, abs=0.03), a


def test_red_absorber_is_chromatic_per_wavelength():
    # Volume Absorption Color C=(0.85,0.25,0.20) exported as color=0, absorption=C^2
    # => sigma_a(lambda) = (1 - C(lambda)) * D: blue absorbed strongly, red weakly.
    C = [0.85, 0.25, 0.20]
    lambdas = [450.0, 550.0, 650.0, 700.0]
    s, a = astroray.principled_volume_spectral_coefficients(
        5.0, [0.0, 0.0, 0.0], [c * c for c in C], lambdas)
    print(f"[pkg270 sigma] sigma_a(lambda) = {np.round(a, 4)} at {lambdas}")
    assert max(s) == 0.0
    assert a[0] > 3.0 * a[2], a           # 450 nm absorbed >= 3x more than 650 nm
    assert a[3] <= a[2] * 1.1 + 1e-6, a   # long wavelengths stay weakly absorbed
    assert a[0] == pytest.approx((1.0 - 0.2) * 5.0, rel=0.25)   # near the blue channel value
    assert a[2] == pytest.approx((1.0 - 0.85) * 5.0, rel=0.5)  # near the red channel value


@pytest.mark.parametrize("color,absorption", [
    ([0.9, 0.15, 0.12], [1.0, 1.0, 1.0]), ([0.55, 0.70, 0.95], [0.2, 0.9, 0.3]),
    ([0.0, 0.0, 0.0], [0.7225, 0.0625, 0.04]), ([1.0, 1.0, 1.0], [0.0, 0.0, 0.0]),
    ([0.2, 0.9, 0.2], [0.9, 0.1, 0.9]),
])
def test_coefficients_never_exceed_the_scalar_majorant(color, absorption):
    D = 3.0
    for lam0 in np.arange(360.0, 830.0, 20.0):
        lambdas = [float(lam0 + k * 5.0) for k in range(4)]
        s, a = astroray.principled_volume_spectral_coefficients(D, color, absorption, lambdas)
        for i in range(4):
            assert s[i] + a[i] <= D * (1.0 + 1e-5), (lambdas[i], s[i], a[i])
            assert s[i] >= 0.0 and a[i] >= 0.0


# --------------------------------------------------------------------------- #
# 2. Render: chromatic absorption slab vs Cycles per-channel Beer-Lambert
# --------------------------------------------------------------------------- #

def _render_cpu(r, spp, max_depth, w, h):
    img = np.asarray(r.render(spp, max_depth, None, False), dtype=np.float64)
    if img.ndim == 1:
        img = img.reshape(h, w, 3)
    return img


def _abs_scene(density, color, absorption, dist=6.0, near=-4.0, far=-3.5, w=24, h=24):
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_use_gpu(False)
    r.set_background_color([0.0, 0.0, 0.0])
    wall = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 1.0})
    r.add_triangle([-20, -20, -dist], [20, -20, -dist], [20, 20, -dist], wall)
    r.add_triangle([-20, -20, -dist], [20, 20, -dist], [-20, 20, -dist], wall)
    if density is not None:
        r.add_homogeneous_medium([-10.0, -10.0, near], [10.0, 10.0, far],
                                 density, color, absorption, 0.0)
    r.setup_camera([0.0, 0.0, 0.001], [0.0, 0.0, -dist], [0.0, 1.0, 0.0],
                   20.0, w / h, 0.0, dist, w, h)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 2)
    return r


def _center_rgb(img):
    h, w = img.shape[:2]
    return img[h // 2 - 3:h // 2 + 3, w // 2 - 3:w // 2 + 3, :].reshape(-1, 3).mean(axis=0)


def test_chromatic_absorption_slab_vs_cycles_band():
    C = np.array([0.85, 0.25, 0.20])   # the #807 cabinet Volume Absorption colour
    D, thickness = 5.0, 0.5            # slab z in [-4, -3.5]
    clear = _center_rgb(_render_cpu(_abs_scene(None, None, None), 256, 2, 24, 24))
    foggy = _center_rgb(_render_cpu(
        _abs_scene(D, [0.0, 0.0, 0.0], [float(c * c) for c in C]), 1024, 2, 24, 24))
    tr = foggy / np.maximum(clear, 1e-9)
    cycles = np.exp(-(1.0 - C) * D * thickness)            # per-channel Beer-Lambert
    grey = math.exp(-(1.0 - C.min()) * D * thickness)      # pkg268 max-channel collapse
    print(f"[pkg270 chroma] Tr measured={tr.round(4)} cycles={cycles.round(4)} grey-collapsed={grey:.4f}")
    # Measurably chromatic: the red channel must sit far above the grey collapse.
    assert tr[0] > 2.5 * grey, f"red Tr {tr[0]:.4f} not chromatic vs grey {grey:.4f}"
    assert tr[0] > 2.5 * tr[2] and tr[0] > 2.5 * tr[1], tr
    # Cycles cross-check band (RGB Beer-Lambert vs our spectral integral): the
    # weakly-absorbed red channel within +-20 %, the strongly-absorbed channels
    # within a wider band (the spectral curve differs most where 1-C(lambda) is
    # steep). FLOOR and CEILING on every channel.
    assert cycles[0] * 0.80 <= tr[0] <= cycles[0] * 1.20, (tr, cycles)
    for c in (1, 2):
        assert cycles[c] * 0.5 <= tr[c] <= cycles[c] * 1.6, (c, tr, cycles)


def test_grey_absorption_still_beer_lambert():
    # pkg268's grey gate must survive the spectral tracker (grey colour => flat
    # spectrum => Tr = exp(-0.5*D*L) on every channel).
    thickness = 2.0
    clear = _center_rgb(_render_cpu(_abs_scene(None, None, None, near=-4.0, far=-2.0), 256, 2, 24, 24))
    foggy = _center_rgb(_render_cpu(
        _abs_scene(0.8, [0.0, 0.0, 0.0], [0.25, 0.25, 0.25], near=-4.0, far=-2.0), 512, 2, 24, 24))
    tr = foggy / np.maximum(clear, 1e-9)
    analytic = math.exp(-0.5 * 0.8 * thickness)
    print(f"[pkg270 grey] Tr={tr.round(4)} analytic={analytic:.4f}")
    for c in range(3):
        assert analytic * 0.85 <= tr[c] <= analytic * 1.12, (c, tr, analytic)


# --------------------------------------------------------------------------- #
# 3. Regression: grid-free scenes untouched
# --------------------------------------------------------------------------- #

def _lit_scene(w=16, h=16):
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_use_gpu(False)
    r.set_background_color([0.2, 0.25, 0.3])
    r.add_point_light([2.0, 3.0, 2.0], {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 80.0)
    m = r.create_material("lambertian", [0.7, 0.4, 0.3], {})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, m)
    r.setup_camera([0.0, 0.0, 5.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0], 30.0, w / h, 0.0, 5.0, w, h)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 4)
    return r


def test_registering_then_clearing_media_is_bit_identical():
    a = _render_cpu(_lit_scene(), 32, 4, 16, 16)
    r = _lit_scene()
    r.add_homogeneous_medium([-1, -1, -1], [1, 1, 1], 2.0, [0.5, 0.5, 0.5], [1, 1, 1], 0.0,
                             emission_strength=1.0, blackbody_intensity=0.5)
    r.clear_grid_media()
    b = _render_cpu(r, 32, 4, 16, 16)
    assert np.array_equal(a, b)
    assert a.max() > 0.0
