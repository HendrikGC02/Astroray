"""pkg122 — Dedicated-light energy calibration regression gates.

Re-derivation of the pkg89 dedicated-light wattage->radiance against the Cycles
kernel (see .astroray_plan/docs/pkg122-light-energy-calibration-research.md).
The pkg89 GAP-2 audit measured, at equal wattage vs the Cycles-calibrated
reference: AREA 0.13x (size-dependent), POINT 3.59x (== 4x), BLACKBODY 14.4x
(and blue-ish). These gates lock in the fixes.

DESIGN NOTES
------------
* Per-channel MEAN-RATIO gates, NOT SSIM (memory ssim-wrong-gate-for-independent-
  rng): stable ratios that do not shrink with sqrt(SPP) = a units/normalization
  bug, which is exactly what these gates assert has been fixed.
* Seeds are pinned NONZERO (memory seed-zero-is-random-sentinel: render seed 0 ==
  std::random_device).
* Linear output (apply_gamma=False) so measured floor values are radiance, not a
  display transform.
* The gates are deliberately chosen to be INVARIANT to the unresolved Defect-4
  emission-spectrum convention (RGBIlluminant vs RGBUnbounded), which this package
  leaves for owner adjudication + a live-Cycles build: they gate relative /
  structural quantities (inverse-square, size-independence, temperature-stability)
  plus loose absolute bands that catch a 4x error but tolerate the ~10% Defect-4
  residual. The tight [0.97,1.03] absolute band from the spec is left for the
  team-lead's post-build live-Cycles A/B run.

BUILD NOTE: these were authored without a local build (no MSVC vcvars for the
implementer). They are the team-lead's acceptance gates; run with:
    pytest tests/test_pkg122_light_energy_calibration.py -v
"""

import math
import numpy as np
import pytest

# 1/(4*pi) — isotropic power->intensity factor (the pkg122 point/spot fix).
INV_FOUR_PI = 1.0 / (4.0 * math.pi)


def _luminance(rgb):
    """Rec.709 relative luminance of a linear RGB triple."""
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _floor_scene(module, seed):
    """Renderer with a large gray Lambertian floor at y=0 and a black
    background, camera high above looking straight down. Dedicated lights do not
    occlude the camera (no geometry), so the light can sit between camera and
    floor. Returns (renderer, albedo)."""
    r = module.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(seed)
    r.setup_camera(
        look_from=[0.0, 20.0, 0.01], look_at=[0.0, 0.0, 0.0], vup=[0.0, 0.0, -1.0],
        vfov=20.0, aspect_ratio=1.0, aperture=0.0, focus_dist=20.0,
        width=48, height=48,
    )
    albedo = 0.5
    mat = r.create_material('lambertian', [albedo, albedo, albedo], {})
    r.add_triangle([-20, 0, -20], [20, 0, -20], [20, 0, 20], mat)
    r.add_triangle([-20, 0, -20], [20, 0, 20], [-20, 0, 20], mat)
    return r, albedo


def _center_rgb(pixels):
    """Mean linear RGB of the central 8x8 patch (floor directly under the light)."""
    h, w = pixels.shape[0], pixels.shape[1]
    cy, cx = h // 2, w // 2
    patch = pixels[cy - 4:cy + 4, cx - 4:cx + 4, :3]
    return np.mean(patch, axis=(0, 1))


# ---------------------------------------------------------------------------
# POINT light
# ---------------------------------------------------------------------------

def test_point_inverse_square(astroray_module):
    """POINT illumination falls as 1/d^2 (relative — no calibration constant).

    A measure bug in the falloff/pdf would break this regardless of the absolute
    scale. Two heights h and 2h => floor radiance ratio == 4.
    """
    def floor_at(h, seed):
        r, _ = _floor_scene(astroray_module, seed)
        r.add_point_light(position=[0, h, 0],
                          emission={'mode': 'rgb', 'color': [1, 1, 1]},
                          intensity=200.0, radius=0.0)
        px = r.render(128, 3, None, False)
        return _luminance(_center_rgb(px))

    near = floor_at(5.0, 101)
    far = floor_at(10.0, 101)
    ratio = near / max(far, 1e-9)
    assert 3.4 < ratio < 4.6, f"point 1/d^2 broken: L(5)/L(10)={ratio:.3f} (expect ~4)"


def test_point_absolute_calibration(astroray_module):
    """POINT matches analytic rho*P/(4*pi^2*d^2) within a Defect-4-tolerant band.

    Before pkg122 the point light used intensity P/pi instead of P/(4*pi) and
    measured 3.59x (== 4x) the analytic value. The band catches that 4x while
    tolerating the ~10% RGB-convention (Defect 4) residual and the pre-existing
    delta-light MIS weight (< 1), both out of scope here.
    """
    P, d, albedo = 200.0, 10.0, 0.5
    r, _ = _floor_scene(astroray_module, 202)
    r.add_point_light(position=[0, d, 0],
                      emission={'mode': 'rgb', 'color': [1, 1, 1]},
                      intensity=P, radius=0.0)
    px = r.render(256, 3, None, False)
    measured = _luminance(_center_rgb(px))
    analytic = albedo * P / (4.0 * math.pi * math.pi * d * d)  # rho*P/(4pi^2 d^2), cos=1
    ratio = measured / analytic
    assert 0.65 < ratio < 1.35, \
        f"point absolute calibration off: measured/analytic={ratio:.3f} " \
        f"(pre-pkg122 bug measured ~3.59)"


# ---------------------------------------------------------------------------
# AREA light — the headline "dimmer than Cycles" defect (Defect 1)
# ---------------------------------------------------------------------------

def test_area_light_size_independence(astroray_module):
    """AREA light energy is size-INDEPENDENT in the far field (Defect 1).

    At equal wattage a Lambertian area light emits L = P/(pi*A); a small and a
    large light HIGH above the floor (both far-field, A << h^2) deliver the same
    irradiance directly below. The old code returned an AREA-measure pdf while the
    integrator's MIS combines it with a SOLID-ANGLE bsdf pdf, so the MIS weight —
    and thus the brightness — depended on 1/A: the audit's 7.68x (size 3) vs 1.40x
    (small) spread (~5.5x). The fix returns a solid-angle pdf, restoring size
    independence.
    """
    def floor_for_size(size, seed):
        r, _ = _floor_scene(astroray_module, seed)
        # Normal = u x v = (1,0,0) x (0,0,1) = (0,-1,0): faces the floor.
        r.add_area_light_dedicated(
            center=[0, 10, 0], axis_u=[1, 0, 0], axis_v=[0, 0, 1],
            size_x=size, size_y=size, shape='RECTANGLE',
            emission={'mode': 'rgb', 'color': [1, 1, 1]},
            intensity=300.0, spread=1.5708,  # pi/2: full hemisphere
        )
        px = r.render(256, 3, None, False)
        return _luminance(_center_rgb(px))

    small = floor_for_size(0.1, 303)   # far-field point-like
    large = floor_for_size(3.0, 303)   # A=9, h^2=100 -> still far-field
    ratio = small / max(large, 1e-9)
    # Physically ~1.0 (both far-field). Pre-fix this was ~8x (MIS-measure bias).
    assert 0.80 < ratio < 1.25, \
        f"area light size-dependent: L(0.1)/L(3)={ratio:.3f} (expect ~1.0; " \
        f"pre-pkg122 the MIS-measure bug made this ~8x)"


def test_area_light_nonzero(astroray_module):
    """AREA light produces meaningful illumination (not the 0.13x near-black)."""
    r, albedo = _floor_scene(astroray_module, 304)
    P, d = 300.0, 10.0
    r.add_area_light_dedicated(
        center=[0, d, 0], axis_u=[1, 0, 0], axis_v=[0, 0, 1],
        size_x=0.1, size_y=0.1, shape='RECTANGLE',
        emission={'mode': 'rgb', 'color': [1, 1, 1]},
        intensity=P, spread=1.5708,
    )
    px = r.render(256, 3, None, False)
    measured = _luminance(_center_rgb(px))
    # A small far area light of power P delivers ~ E = P/(pi*d^2) directly below;
    # reflected L ~ albedo * E / pi. Catches a gross (0.13x) under-scale.
    approx = albedo * (P / (math.pi * d * d)) / math.pi
    ratio = measured / approx
    assert 0.4 < ratio < 2.0, \
        f"area light energy off: measured/approx={ratio:.3f} (pre-pkg122 ~0.13x)"


# ---------------------------------------------------------------------------
# BLACKBODY (Defect 3) — photopic normalization
# ---------------------------------------------------------------------------

def _blackbody_point_center(module, temperature, seed):
    r = module.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(seed)
    r.setup_camera(
        look_from=[0.0, 20.0, 0.01], look_at=[0.0, 0.0, 0.0], vup=[0.0, 0.0, -1.0],
        vfov=20.0, aspect_ratio=1.0, aperture=0.0, focus_dist=20.0,
        width=48, height=48,
    )
    mat = r.create_material('lambertian', [1.0, 1.0, 1.0], {})  # white for chroma
    r.add_triangle([-20, 0, -20], [20, 0, -20], [20, 0, 20], mat)
    r.add_triangle([-20, 0, -20], [20, 0, 20], [-20, 0, 20], mat)
    r.add_point_light(position=[0, 10, 0],
                      emission={'mode': 'blackbody', 'temperature_K': temperature,
                                'tint_rgb': [1, 1, 1]},
                      intensity=200.0, radius=0.0)
    px = r.render(256, 3, None, False)
    return _center_rgb(px)


def test_blackbody_temperature_stability(astroray_module):
    """Q11: a blackbody's PERCEIVED intensity is stable across temperature.

    With photopic-luminance normalization (divide by integrated luminance, per
    Cycles light_normalize_factor) a 4000 K and a 6500 K light at equal intensity
    have ~equal luminance. Without it (pre-pkg122, raw Planck) the luminance
    scaled with the Planck integral and differed by several-fold. Defect-4-
    invariant (both are blackbody through the same point machinery).
    """
    rgb_4000 = _blackbody_point_center(astroray_module, 4000.0, 405)
    rgb_6500 = _blackbody_point_center(astroray_module, 6500.0, 405)
    ratio = _luminance(rgb_4000) / max(_luminance(rgb_6500), 1e-9)
    assert 0.80 < ratio < 1.25, \
        f"blackbody NOT photopic-stable across T: Y(4000)/Y(6500)={ratio:.3f} " \
        f"(expect ~1.0; pre-pkg122 raw Planck was several-fold off)"


def test_blackbody_vs_rgb_brightness(astroray_module):
    """A 6500 K blackbody and an RGB-white light at equal intensity are ~equally
    bright — closing the ~4x blackbody-over-RGB excess (the other half of the 14x).
    """
    rgb_bb = _blackbody_point_center(astroray_module, 6500.0, 406)

    r, _ = _floor_scene(astroray_module, 406)
    # white floor for a fair chroma-neutral comparison
    matw = r.create_material('lambertian', [1.0, 1.0, 1.0], {})
    r.add_triangle([-20, 0.001, -20], [20, 0.001, -20], [20, 0.001, 20], matw)
    r.add_triangle([-20, 0.001, -20], [20, 0.001, 20], [-20, 0.001, 20], matw)
    r.add_point_light(position=[0, 10, 0],
                      emission={'mode': 'rgb', 'color': [1, 1, 1]},
                      intensity=200.0, radius=0.0)
    px = r.render(256, 3, None, False)
    rgb_white = _center_rgb(px)

    ratio = _luminance(rgb_bb) / max(_luminance(rgb_white), 1e-9)
    assert 0.5 < ratio < 1.7, \
        f"blackbody/RGB brightness off: {ratio:.3f} (expect ~1; pre-pkg122 ~4x)"


def test_blackbody_6500k_neutral(astroray_module):
    """6500 K blackbody on a white surface is near-neutral (G2-style chroma gate).

    Photopic normalization is a scalar, so chromaticity is unchanged; this guards
    against a regression that tints the SPD.
    """
    rgb = _blackbody_point_center(astroray_module, 6500.0, 407)
    mx, mn = float(np.max(rgb)), float(np.min(rgb))
    rel_var = (mx - mn) / mx if mx > 0 else 1.0
    assert rel_var < 0.12, \
        f"6500K blackbody not neutral: RGB={rgb}, variation={rel_var * 100:.1f}%"
