"""pkg140 -- DistantLight angular_diameter ~= 0 zero-angle delta fix.

Regression gates for the pkg122 hardware-verifier finding (2026-07-20
overnight): a DistantLight with angular_diameter == 0.0 (a true delta sun)
or angular_diameter == 1.7e-4 rad (inside the float32 1-cos(h) cancellation
zone) rendered PURE BLACK on both CPU and GPU, while >= 1.75e-3 rad rendered
correctly (~0.99x analytic). Root cause (src/lights/distant_light.cpp):

  1. sampleLi / pdfLi used solidAngle = 2*pi*(1 - cos(halfAngle)), which
     cancels to exactly 0.0f in float32 for halfAngle <~ 3.4e-4 rad, even
     though the true value is tiny-but-nonzero -> pdf = 1/0 = +inf -> the
     L/pdf NEE estimator contributes 0.
  2. power() returned 0 for a true delta sun (solidAngle == 0 exactly),
     starving PowerLightSampler's power-weighted CDF (LightList::addLight)
     -- the sun was never selected at all, sufficient for black on its own.
  3. Even once sampleLi/power were nonzero, the NEE/BSDF MIS combine
     (raytracer.h pathTraceSpectral) power-heuristics ls.pdf against
     bsdfPdf; a true delta light's ls.pdf collapses from
     ~1/solidAngle (huge, MIS weight -> 1 in the finite-angle limit) to
     O(1) selPdf right at angle == 0, discontinuously UNDER-weighting the
     delta branch relative to its finite-angle neighbors.

Fix (src/lights/distant_light.cpp, include/raytracer.h, src/light_sampler.cpp,
src/gpu/gpu_nee.cuh, include/astroray/{light,gpu_types}.h):
  A. distantSolidAngle() uses the 2*sin^2(h/2) identity (exact, no
     cancellation) instead of 1 - cos(h).
  B. power() floors solidAngle at the 1.75e-3 rad value (the smallest angle
     the pkg122 verifier measured as correct) so a delta sun always has
     nonzero power-CDF weight, continuous with the finite-angle branch.
  C. Light::LiSample / LightSample gain an `isDelta` flag (mirrors pbrt-v4's
     delta-light MIS handling, src/pbrt/lights.h, Apache-2.0): the NEE/BSDF
     MIS weight is forced to 1 for delta samples instead of a power
     heuristic against bsdfPdf, matching the finite-angle wt->1 limit as
     solidAngle -> 0+.

DESIGN NOTES
------------
* Real bindings only (astroray_module fixture), no invented APIs.
* Seeds are pinned NONZERO (memory seed-zero-is-random-sentinel: render seed
  0 == std::random_device).
* Linear output (apply_gamma=False) so measured values are radiance.
* Tolerance bands follow the repo's existing pkg122 precedent
  (test_pkg122_light_energy_calibration.py uses ~[0.65, 1.35] "Defect-4-
  tolerant" bands, not the spec's aspirational 1-2% -- that figure describes
  the hardware verifier's own high-SPP measurement, not a bound achievable at
  CPU-test-suite SPP with the RGBIlluminant convention (Defect 4) still
  unresolved repo-wide). The FLOOR value for the black-regression assertion
  (ratio > 0.05) is what actually catches the pkg140 bug -- the previously
  pure-black rows fail that check by roughly two orders of magnitude.

BUILD NOTE: authored without a local build (no MSVC vcvars for the
implementer). Run with:
    pytest tests/test_pkg140_distant_light_zero_angle.py -v
GPU parity (spec gate 2, "GPU leg matches CPU at the 1e-5 MC convention") is
NOT covered here -- it requires set_use_gpu(True) hardware verification the
implementer cannot run; see the PR body for the exact recipe.
"""

import math
import numpy as np
import pytest


def _luminance(rgb):
    """Rec.709 relative luminance of a linear RGB triple."""
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _floor_scene(module, seed, half_extent=20.0, width=48, height=48):
    """Large gray Lambertian floor at y=0, camera high above looking straight
    down, black background. Mirrors test_pkg122_light_energy_calibration.py's
    _floor_scene (same winding / camera convention, already validated)."""
    r = module.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(seed)
    r.setup_camera(
        look_from=[0.0, 20.0, 0.01], look_at=[0.0, 0.0, 0.0], vup=[0.0, 0.0, -1.0],
        vfov=20.0, aspect_ratio=1.0, aperture=0.0, focus_dist=20.0,
        width=width, height=height,
    )
    albedo = 0.5
    mat = r.create_material('lambertian', [albedo, albedo, albedo], {})
    e = half_extent
    r.add_triangle([-e, 0, -e], [e, 0, -e], [e, 0, e], mat)
    r.add_triangle([-e, 0, -e], [e, 0, e], [-e, 0, e], mat)
    return r, albedo


def _center_rgb(pixels):
    """Mean linear RGB of the central 8x8 patch."""
    h, w = pixels.shape[0], pixels.shape[1]
    cy, cx = h // 2, w // 2
    patch = pixels[cy - 4:cy + 4, cx - 4:cx + 4, :3]
    return np.mean(patch, axis=(0, 1))


# pkg140 spec sweep: angular_diameter 0.0 and 1.7e-4 are the regression rows
# (both pure black pre-fix); 1.75e-3 and 0.00918 (Blender default) already
# rendered correctly and must stay that way (no-regression anchor).
SWEEP_ANGLES = [0.0, 1.7e-4, 1.75e-3, 0.00918]
SUN_INTENSITY = 4.0  # irradiance S (W/m^2), post-pkg122 units


def _sun_floor_luminance(module, angular_diameter, seed, samples=512):
    r, albedo = _floor_scene(module, seed)
    r.add_sun_light_dedicated(
        direction=[0.0, -1.0, 0.0],  # straight down -> cos(theta) = 1 on the floor
        angular_diameter=angular_diameter,
        emission={'mode': 'rgb', 'color': [1, 1, 1]},
        intensity=SUN_INTENSITY,
    )
    px = r.render(samples, 3, None, False)
    return _luminance(_center_rgb(px)), albedo


@pytest.mark.parametrize("angle", SWEEP_ANGLES)
def test_sweep_no_black_regression(astroray_module, angle):
    """pkg140 gate 1: none of the swept angles render black. A straight-down
    sun's analytic reflected radiance is albedo*S/pi (Lambertian, cos=1,
    distance-independent). 0.0 and 1.7e-4 measured ~0 pre-fix (ratio << 0.05);
    this is the primary regression check.
    """
    measured, albedo = _sun_floor_luminance(astroray_module, angle, seed=1401)
    analytic = albedo * SUN_INTENSITY / math.pi
    ratio = measured / analytic
    assert ratio > 0.05, (
        f"angular_diameter={angle}: measured={measured:.6f} (analytic={analytic:.6f}, "
        f"ratio={ratio:.4f}) -- looks BLACK; pkg140 regression (0.0 and 1.7e-4 were "
        f"pure black pre-fix: power()==0 CDF starvation / 1-cos(h) cancellation)"
    )
    assert 0.6 < ratio < 1.4, (
        f"angular_diameter={angle}: measured/analytic={ratio:.3f} (expect ~1.0 within "
        f"the pkg122-precedent Defect-4-tolerant band)"
    )


def test_continuity_delta_vs_smallest_finite(astroray_module):
    """pkg140 gate 3: no brightness jump between the true-delta branch (0.0)
    and the smallest finite sweep angle (1.7e-4) beyond MC noise. Both were
    pure black pre-fix; post-fix both converge to the same analytic value
    because the MIS weight is forced to 1 for the delta case (LightSample::
    isDelta, raytracer.h), matching the finite branch's wt -> 1 limit as
    solidAngle -> 0+. Without the isDelta MIS fix this would still show a
    jump: the delta branch's ls.pdf collapses from ~1/solidAngle to O(1)
    selPdf, discontinuously lowering the power-heuristic weight.
    """
    delta_L, _ = _sun_floor_luminance(astroray_module, 0.0, seed=1402)
    finite_L, _ = _sun_floor_luminance(astroray_module, 1.7e-4, seed=1402)
    ratio = delta_L / max(finite_L, 1e-9)
    assert 0.7 < ratio < 1.43, (
        f"delta/finite continuity broken: L(0.0)={delta_L:.6f} L(1.7e-4)={finite_L:.6f} "
        f"ratio={ratio:.3f} (expect ~1.0; a jump here means the MIS weight is not "
        f"consistent across the delta/finite boundary)"
    )


def test_power_cdf_delta_sun_plus_area_light_both_contribute(astroray_module):
    """pkg140 gate 5: a scene with a TRUE DELTA sun (angular_diameter=0.0)
    AND an area light must have BOTH lights selectable in the power-weighted
    CDF. Pre-fix, DistantLight::power() returned exactly 0.0 for a delta sun,
    giving it zero probability in LightList's unified power CDF (sufficient
    for total black on its own -- pkg140 root-cause item 2/3).

    Isolate the sun's contribution with a floor point 50 m from the area
    light: inverse-square falloff makes the area light's contribution there
    negligible, but a distant light has NO distance falloff, so the sun (if
    selectable at all) still fully illuminates it. Compare a render with the
    sun included vs excluded (area light present in both) -- a measurable
    brightening at the far point proves the delta sun was actually sampled.
    """
    def render(include_sun, seed):
        r = astroray_module.Renderer()
        r.set_background_color([0.0, 0.0, 0.0])
        r.set_seed(seed)
        r.setup_camera(
            look_from=[50.0, 20.0, 0.01], look_at=[50.0, 0.0, 0.0],
            vup=[0.0, 0.0, -1.0], vfov=20.0, aspect_ratio=1.0,
            aperture=0.0, focus_dist=20.0, width=32, height=32,
        )
        albedo = 0.5
        mat = r.create_material('lambertian', [albedo, albedo, albedo], {})
        r.add_triangle([-100, 0, -100], [200, 0, -100], [200, 0, 100], mat)
        r.add_triangle([-100, 0, -100], [200, 0, 100], [-100, 0, 100], mat)
        # AREA light near the origin: at x=50 its inverse-square contribution
        # is negligible (>= ~2500x falloff vs directly underneath).
        r.add_area_light_dedicated(
            center=[0, 5, 0], axis_u=[1, 0, 0], axis_v=[0, 0, 1],
            size_x=1.0, size_y=1.0, shape='RECTANGLE',
            emission={'mode': 'rgb', 'color': [1, 1, 1]},
            intensity=300.0, spread=1.5708,  # pi/2: full hemisphere
        )
        if include_sun:
            r.add_sun_light_dedicated(
                direction=[0.0, -1.0, 0.0], angular_diameter=0.0,
                emission={'mode': 'rgb', 'color': [1, 1, 1]}, intensity=SUN_INTENSITY,
            )
        px = r.render(256, 3, None, False)
        return _luminance(_center_rgb(px))

    with_sun = render(True, seed=1403)
    without_sun = render(False, seed=1403)
    assert with_sun > without_sun * 1.5, (
        f"delta sun not selectable in the power CDF: with_sun={with_sun:.6f} "
        f"without_sun={without_sun:.6f} (expect with_sun measurably brighter -- "
        f"pre-pkg140 power()==0 for a delta sun starved it out of the CDF entirely, "
        f"so with_sun ~= without_sun)"
    )
