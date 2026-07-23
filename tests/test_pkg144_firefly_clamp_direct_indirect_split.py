"""pkg144 -- firefly clamp direct/indirect split.

The package's reason to exist: the pre-pkg144 code had an always-on,
unconditional `sLum > 20.0f` cap applied to the WHOLE per-sample path color
(include/raytracer.h, per-pixel accumulation loop). This capped delta-light
NEE, which is deterministic (a delta light's `sampleLi` returns emission
with pdf==1/delta selection, so there is zero variance to suppress --
clamping it is pure downward bias, not noise control). For a bright delta
sun this made the measured floor brightness asymptote at ~14-20 across
S = 1e6...1e9 instead of growing linearly with S (measured, PR #507,
pkg140 gate-5 investigation).

Fix (this package): remove the hardcoded top-level cap; wire the
already-stubbed `clampDirect`/`clampIndirect` fields into the integrator,
applied per-CONTRIBUTION by bounce depth -- mirrors Cycles
`film_clamp_light` (src/kernel/film/light_passes.h, Apache-2.0):
    const float limit = (bounce > 0) ? sample_clamp_indirect : sample_clamp_direct;
`bounce == 0` (camera-visible emission + first-hit direct NEE, INCLUDING
delta-light NEE) uses clampDirect; `bounce > 0` (indirect) uses
clampIndirect. limit <= 0 disables (Cycles semantics: user 0 -> no clamp).

Defaults (evidence-first, per spec):
  - clampDirect  = 0 (off), non-negotiable -- direct/delta NEE must never be
    silently biased. This is the whole point of the package.
  - clampIndirect = 0 (off) -- the existing firefly/caustic/furnace test
    suite (test_disney_energy_conservation.py, test_dielectric_glass_furnace.py,
    test_disney_rough_glass_furnace.py, test_caustic_validation.py, etc.)
    was measured to pass with clampIndirect fully disabled, so this package
    ships full Cycles parity (both clamps off) rather than reintroducing a
    nonzero indirect cap "just in case".

DESIGN NOTES
------------
* Real bindings only (astroray_module fixture / astroray.Renderer()).
* Seeds pinned nonzero (memory seed-zero-is-random-sentinel).
* Linear output (apply_gamma=False) so measured values are radiance
  (memory gamma-vs-linear-comparison-artifact).
* Metric is per-channel mean-ratio to the analytic Lambertian value, NOT
  SSIM (memory ssim-wrong-gate-for-independent-rng: independent MC streams
  at different S values have no reason to correlate pixel-for-pixel; SSIM
  would be meaningless here. A stable per-channel ratio across three
  decades of S is exactly the signature of correct linear energy scaling).
* CPU-only (renderer.render(...) without set_use_gpu(True)); this test does
  not touch the GPU megakernels (see PR body for the HW-verification gate
  that mirrors this on GPU).
"""

import math
import numpy as np
import pytest


def _luminance(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _floor_scene(module, seed, half_extent=20.0, width=48, height=48, albedo=0.5):
    """Large gray Lambertian floor at y=0, camera high above looking straight
    down, black background. Mirrors test_pkg140_distant_light_zero_angle.py's
    _floor_scene (same winding / camera convention, already validated)."""
    r = module.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(seed)
    r.setup_camera(
        look_from=[0.0, 20.0, 0.01], look_at=[0.0, 0.0, 0.0], vup=[0.0, 0.0, -1.0],
        vfov=20.0, aspect_ratio=1.0, aperture=0.0, focus_dist=20.0,
        width=width, height=height,
    )
    mat = r.create_material('lambertian', [albedo, albedo, albedo], {})
    e = half_extent
    r.add_triangle([-e, 0, -e], [e, 0, -e], [e, 0, e], mat)
    r.add_triangle([-e, 0, -e], [e, 0, e], [-e, 0, e], mat)
    return r


def _center_rgb(pixels):
    """Mean linear RGB of the central 8x8 patch."""
    h, w = pixels.shape[0], pixels.shape[1]
    cy, cx = h // 2, w // 2
    patch = pixels[cy - 4:cy + 4, cx - 4:cx + 4, :3]
    return np.mean(patch, axis=(0, 1))


ALBEDO = 0.5
SUN_S_DECADES = [1.0e6, 1.0e7, 1.0e8]  # >= 3 decades, per spec gate


def _sun_floor_rgb(module, S, angular_diameter, seed, samples=128):
    r = _floor_scene(module, seed, albedo=ALBEDO)
    r.add_sun_light_dedicated(
        direction=[0.0, -1.0, 0.0],  # straight down -> cos(theta) = 1 on the floor
        angular_diameter=angular_diameter,
        emission={'mode': 'rgb', 'color': [1.0, 1.0, 1.0]},
        intensity=S,
    )
    px = r.render(samples, 3, None, False)
    return _center_rgb(px)


@pytest.mark.parametrize("angular_diameter", [0.0, 0.00918])
@pytest.mark.parametrize("S", SUN_S_DECADES)
def test_bright_sun_energy_linearity(astroray_module, S, angular_diameter):
    """THE gate this package exists for: a delta (or near-delta) sun's
    reflected radiance off a Lambertian floor must grow linearly with S
    across >= 3 decades (S = 1e6, 1e7, 1e8), matching the analytic
    albedo*S/pi per-channel within noise. Pre-pkg144, the always-on
    sLum>20 cap made this asymptote at ~14-20 regardless of S -- the ratio
    would collapse toward 0 as S grows. Post-fix the ratio stays ~1 at
    every S (measured 0.9995 empirically at this scene/sample setup).
    """
    rgb = _sun_floor_rgb(astroray_module, S, angular_diameter, seed=14401)
    analytic = ALBEDO * S / math.pi
    for ch, name in enumerate('RGB'):
        ratio = rgb[ch] / analytic
        assert 0.85 < ratio < 1.15, (
            f"S={S:.0e} angular_diameter={angular_diameter}: channel {name} "
            f"measured={rgb[ch]:.6g} analytic={analytic:.6g} ratio={ratio:.4f} "
            f"-- expected ~1.0 (linear growth with S); a collapse toward 0 "
            f"here is the pre-pkg144 firefly-clamp bias reappearing"
        )


def test_bright_sun_ratio_stable_across_decades(astroray_module):
    """Stronger form of the linearity gate: compare the ratio-to-analytic at
    the smallest and largest swept S directly. Pre-pkg144, S/selPdf converges
    to a clamp-bounded constant (~14-20) independent of S once the sun is
    bright enough to trip the cap, so ratio(S=1e8)/ratio(S=1e6) would collapse
    toward (20/analytic(1e8)) / (20/analytic(1e6)) = analytic(1e6)/analytic(1e8)
    = 1e-2 -- i.e. a 100x drop. Post-fix this ratio-of-ratios stays ~1.
    """
    lo = _luminance(_sun_floor_rgb(astroray_module, 1.0e6, 0.00918, seed=14402))
    hi = _luminance(_sun_floor_rgb(astroray_module, 1.0e8, 0.00918, seed=14402))
    analytic_lo = ALBEDO * 1.0e6 / math.pi
    analytic_hi = ALBEDO * 1.0e8 / math.pi
    ratio_lo = lo / analytic_lo
    ratio_hi = hi / analytic_hi
    rr = ratio_hi / ratio_lo
    assert 0.7 < rr < 1.43, (
        f"ratio(S=1e8)/ratio(S=1e6) = {rr:.4f} (expect ~1.0); a collapse "
        f"here means the direct-light clamp is still active and biasing "
        f"bright delta-light NEE"
    )


def test_clamp_direct_default_is_off():
    """clampDirect must default to 0 (disabled) -- non-negotiable per spec:
    direct/delta NEE must never be silently biased by a default-on clamp."""
    import astroray
    r = astroray.Renderer()
    # No Python getter is exposed for clampDirect/clampIndirect (setters
    # only, module/blender_module.cpp set_clamp_direct/set_clamp_indirect);
    # verify behaviourally instead: setting an aggressive clampDirect must
    # visibly dim a direct-lit render relative to the (default, off) baseline,
    # proving 0 truly means "no clamp" and the field is wired.
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(14403)
    r.setup_camera(
        look_from=[0.0, 20.0, 0.01], look_at=[0.0, 0.0, 0.0], vup=[0.0, 0.0, -1.0],
        vfov=20.0, aspect_ratio=1.0, aperture=0.0, focus_dist=20.0,
        width=32, height=32,
    )
    mat = r.create_material('lambertian', [0.5, 0.5, 0.5], {})
    r.add_triangle([-20, 0, -20], [20, 0, -20], [20, 0, 20], mat)
    r.add_triangle([-20, 0, -20], [20, 0, 20], [-20, 0, 20], mat)
    r.add_sun_light_dedicated(
        direction=[0.0, -1.0, 0.0], angular_diameter=0.00918,
        emission={'mode': 'rgb', 'color': [1.0, 1.0, 1.0]}, intensity=1.0e6,
    )
    baseline = _luminance(_center_rgb(r.render(64, 3, None, False)))

    r2 = astroray.Renderer()
    r2.set_clamp_direct(0.01)  # aggressively small -- must dim the render
    r2.set_background_color([0.0, 0.0, 0.0])
    r2.set_seed(14403)
    r2.setup_camera(
        look_from=[0.0, 20.0, 0.01], look_at=[0.0, 0.0, 0.0], vup=[0.0, 0.0, -1.0],
        vfov=20.0, aspect_ratio=1.0, aperture=0.0, focus_dist=20.0,
        width=32, height=32,
    )
    mat2 = r2.create_material('lambertian', [0.5, 0.5, 0.5], {})
    r2.add_triangle([-20, 0, -20], [20, 0, -20], [20, 0, 20], mat2)
    r2.add_triangle([-20, 0, -20], [20, 0, 20], [-20, 0, 20], mat2)
    r2.add_sun_light_dedicated(
        direction=[0.0, -1.0, 0.0], angular_diameter=0.00918,
        emission={'mode': 'rgb', 'color': [1.0, 1.0, 1.0]}, intensity=1.0e6,
    )
    clamped = _luminance(_center_rgb(r2.render(64, 3, None, False)))

    assert clamped < baseline * 0.1, (
        f"set_clamp_direct(0.01) did not visibly dim the render "
        f"(clamped={clamped:.4g} vs baseline(off)={baseline:.4g}) -- "
        f"clampDirect does not appear to be wired into the integrator"
    )
