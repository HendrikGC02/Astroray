"""pkg268 review-fix — pin the Cycles Principled Volume socket->coefficient
mapping (svm_node_principled_volume) numerically, and confirm the Volume
Absorption node matches Cycles (white Color => transparent; grey 0.5 =>
Tr=exp(-0.5*density*L)).

Cycles:
  sigma_s = color * density
  sigma_a = max(1-color,0) * max(1-sqrt(absorption_color),0) * density
  sigma_t = sigma_s + sigma_a
Default white absorption_color => sigma_a = 0 (lossless, albedo 1).

Scalar-sigma_t scope: extinction_scale = density*max_c(sigma_s+sigma_a),
albedo_rgb = sigma_s/max_c(sigma_s+sigma_a) (<=1 per channel, no energy gain).
"""

from __future__ import annotations

import math
import sys

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

import astroray

SEED = 268333


# --------------------------------------------------------------------------- #
# Numeric pin of the coefficient mapping.
# --------------------------------------------------------------------------- #

def test_principled_white_absorption_is_lossless():
    # color red, default WHITE absorption -> sigma_a = 0, per-channel albedo 1 at
    # the max channel; extinction = density*max(color).
    ext, alb = astroray.principled_volume_coefficients(
        1.5, [0.9, 0.15, 0.12], [1.0, 1.0, 1.0])
    assert ext == pytest.approx(1.5 * 0.9, rel=1e-5), f"extinction {ext}"
    assert alb[0] == pytest.approx(1.0, abs=1e-5)          # max channel lossless
    assert alb[1] == pytest.approx(0.15 / 0.9, abs=1e-5)
    assert alb[2] == pytest.approx(0.12 / 0.9, abs=1e-5)


def test_principled_grey_white_is_albedo_one():
    ext, alb = astroray.principled_volume_coefficients(
        2.0, [1.0, 1.0, 1.0], [1.0, 1.0, 1.0])
    assert ext == pytest.approx(2.0, rel=1e-5)             # sigma_t = density
    assert alb == pytest.approx((1.0, 1.0, 1.0), abs=1e-5)  # fully lossless


def test_principled_dark_absorption_adds_absorption():
    # black absorption_color -> max(1-sqrt(0),0)=1 -> sigma_a=(1-color)*density.
    # color 0.5 grey: sigma_s=0.5, sigma_a=0.5, sigma_t=1.0; albedo 0.5.
    ext, alb = astroray.principled_volume_coefficients(
        1.0, [0.5, 0.5, 0.5], [0.0, 0.0, 0.0])
    assert ext == pytest.approx(1.0, rel=1e-5)
    assert alb == pytest.approx((0.5, 0.5, 0.5), abs=1e-5)


def test_absorption_node_mapping_via_color_squared():
    # Volume Absorption Color=C is exported as color=0, absorption_color=C^2 so the
    # Principled formula yields sigma_a=(1-C)*density, sigma_s=0, albedo 0.
    # white C=1 -> absorption_color=1 -> sigma_a=0 -> extinction 0.
    ext, alb = astroray.principled_volume_coefficients(3.0, [0.0, 0.0, 0.0], [1.0, 1.0, 1.0])
    assert ext == pytest.approx(0.0, abs=1e-6), f"white absorption not transparent: {ext}"
    # grey C=0.5 -> absorption_color=0.25 -> sigma_a=(1-0.5)=0.5 -> extinction=D*0.5.
    ext2, alb2 = astroray.principled_volume_coefficients(2.0, [0.0, 0.0, 0.0], [0.25, 0.25, 0.25])
    assert ext2 == pytest.approx(2.0 * 0.5, rel=1e-5), f"grey absorption extinction {ext2}"
    assert alb2 == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)


# --------------------------------------------------------------------------- #
# Render-level: absorption-node transmittance matches Beer-Lambert (linear,
# floor + ceiling).
# --------------------------------------------------------------------------- #

def _render_cpu(r, spp, max_depth, w, h):
    img = np.asarray(r.render(spp, max_depth, None, False), dtype=np.float64)
    if img.ndim == 1:
        img = img.reshape(h, w, 3)
    return img


def _abs_scene(density, color, absorption, dist=6.0, near=-4.0, far=-2.0, w=24, h=24):
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_use_gpu(False)  # pkg268 volume transport is CPU-only (GPU = pkg269)
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


def _center(img):
    h, w = img.shape[:2]
    return float(img[h // 2 - 3:h // 2 + 3, w // 2 - 3:w // 2 + 3, :].mean())


def test_white_absorption_cube_is_transparent():
    """Volume Absorption white Color (exported absorption_color=1) => sigma_a=0 =>
    the cube is invisible (Tr ~ 1), matching Cycles (was opaque before the fix)."""
    clear = _center(_render_cpu(_abs_scene(None, None, None), 256, 2, 24, 24))
    foggy = _center(_render_cpu(_abs_scene(5.0, [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]), 256, 2, 24, 24))
    tr = foggy / max(clear, 1e-9)
    print(f"[pkg268 map] white-absorption Tr={tr:.4f} (expect ~1)")
    assert tr >= 0.95, f"white-Color absorption cube not transparent (Tr={tr:.4f})"


def test_grey_absorption_cube_beer_lambert():
    thickness = 2.0  # slab z=-4..-2
    clear = _center(_render_cpu(_abs_scene(None, None, None), 256, 2, 24, 24))
    for dens in (0.4, 0.8):
        # grey Color 0.5 -> absorption_color=0.25 -> sigma_a=0.5*dens.
        foggy = _center(_render_cpu(
            _abs_scene(dens, [0.0, 0.0, 0.0], [0.25, 0.25, 0.25]), 512, 2, 24, 24))
        tr = foggy / max(clear, 1e-9)
        analytic = math.exp(-0.5 * dens * thickness)
        print(f"[pkg268 map] grey-absorption dens={dens}: Tr={tr:.4f} analytic={analytic:.4f}")
        assert tr >= analytic * 0.85, f"Tr {tr:.4f} below floor {analytic*0.85:.4f}"
        assert tr <= analytic * 1.12, f"Tr {tr:.4f} above ceiling {analytic*1.12:.4f}"
