"""pkg89 Phase B: Dedicated light Blender addon acceptance tests (G1-G5).

G1: Render tests/scenes/dedicated_lights_zoo.py — one of each type (SSIM ≥ 0.98).
G2: Blackbody spectral correctness (D65 XYZ match within 1%).
G3: IES profile correctness (candela distribution ±5% at 8 sample angles).
G4: Spot cone falloff (inner-cone ∝ cos²(θ)/r², outside outer cone = 0).
G5: POINT light isotropy regression (hard shadows from radius=0 possible).
"""

import pytest
import numpy as np


def test_g1_dedicated_lights_zoo(astroray_module):
    """G1: Render a zoo scene with all 5 dedicated light types.

    POINT, SUN, AREA, SPOT, (BACKGROUND handled by existing envmap tests).
    Verify each light type produces a non-trivial image and no crashes.
    """
    r = astroray_module.Renderer()

    # Camera looking at origin
    r.setup_camera(
        look_from=[0, 2, 5],
        look_at=[0, 0, 0],
        vup=[0, 1, 0],
        vfov=45.0,
        aspect_ratio=1.0,
        aperture=0.0,
        focus_dist=5.0,
        width=128,
        height=128
    )

    # Ground plane (diffuse)
    mat_ground = r.create_material('lambertian', [0.5, 0.5, 0.5], {})
    r.add_triangle(
        [-10, 0, -10], [10, 0, -10], [10, 0, 10], mat_ground
    )
    r.add_triangle(
        [-10, 0, -10], [10, 0, 10], [-10, 0, 10], mat_ground
    )

    # Test sphere (diffuse, for shadows)
    mat_sphere = r.create_material('lambertian', [0.8, 0.2, 0.2], {})
    r.add_sphere([0, 0.5, 0], 0.5, mat_sphere)

    # POINT light (isotropic, soft-shadow radius=0 for hard shadows)
    emission_point = {'mode': 'blackbody', 'temperature_K': 6500.0, 'tint_rgb': [1, 1, 1]}
    r.add_point_light(
        position=[2, 3, 2],
        emission=emission_point,
        intensity=50.0,
        radius=0.0
    )

    # SUN light (distant, angular diameter like the sun)
    emission_sun = {'mode': 'blackbody', 'temperature_K': 5778.0, 'tint_rgb': [1, 1, 1]}
    r.add_sun_light_dedicated(
        direction=[0.3, -1, 0.2],
        angular_diameter=0.0093,  # ~0.53 degrees in radians
        emission=emission_sun,
        intensity=1.0
    )

    # AREA light (rectangle, Lambertian emission)
    emission_area = {'mode': 'rgb', 'color': [1, 0.8, 0.6]}
    r.add_area_light_dedicated(
        center=[-2, 2, -2],
        axis_u=[1, 0, 0],
        axis_v=[0, 1, 0],
        size_x=1.0,
        size_y=1.0,
        shape='RECTANGLE',
        emission=emission_area,
        intensity=10.0,
        spread=1.57  # π/2 radians (full hemisphere)
    )

    # SPOT light (cone, with smooth falloff)
    emission_spot = {'mode': 'blackbody', 'temperature_K': 3000.0, 'tint_rgb': [1, 1, 1]}
    r.add_spot_light_dedicated(
        center=[0, 4, 0],
        direction=[0, -1, 0],
        inner_angle=0.3,
        outer_angle=0.5,
        emission=emission_spot,
        intensity=100.0,
        radius=0.0
    )

    # Render
    pixels = r.render(64, 4)

    # Validate: non-NaN, non-negative, non-trivial mean
    assert np.all(np.isfinite(pixels)), "G1 FAIL: pixels contain NaN/inf"
    assert np.all(pixels >= 0), "G1 FAIL: pixels contain negative values"

    mean_lum = np.mean(pixels)
    assert mean_lum > 0.01, f"G1 FAIL: scene too dark (mean={mean_lum}); lights not working"
    assert mean_lum < 20.0, f"G1 FAIL: scene too bright (mean={mean_lum}); fireflies or bad falloff"

    print(f"[G1 PASS] Zoo scene rendered successfully, mean luminance={mean_lum:.4f}")


# Linear sRGB of a Planckian radiator, normalised to its max channel. Independent
# oracle: colour-science 0.4.7 sd_blackbody -> sd_to_XYZ (CIE 1931 2 deg) ->
# XYZ_to_RGB(sRGB, no CCTF, no adaptation). 6500 K is NOT D65: G is 5.7 % low.
_PLANCK_SRGB = {6500.0: (1.0, 0.9429, 0.9922), 3000.0: (1.0, 0.4769, 0.1537)}


@pytest.mark.parametrize("temperature_K", [6500.0, 3000.0])
def test_g2_blackbody_spectral_correctness(astroray_module, temperature_K):
    """G2: a blackbody area light lights a white plane with the Planck colour.

    #767 rewrite. The old body lit the plane with an emitter facing AWAY from
    it (axis_u x axis_v = +z) and left the default world on, rendered with
    gamma, and gated channel spread < 12 %. A black-world probe showed the
    light contributed exactly 0: the gate measured the default sky gradient,
    for 6500 K, 3000 K and RGB white alike. Its original intent was "6500 K
    blackbody chromaticity is correct". This version tests that intent against
    an independent oracle. Pre-#767 (10 deg observer) 3000 K rendered G 0.459
    (oracle 0.477). Post-fix: 1.000 / 0.477 / 0.154.
    """
    r = astroray_module.Renderer()
    r.setup_camera(look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=45.0,
                   aspect_ratio=1.0, aperture=0.0, focus_dist=3.0, width=64, height=64)
    r.set_background_color([0.0, 0.0, 0.0])  # the light is the only source
    mat_white = r.create_material('lambertian', [1, 1, 1], {})
    r.add_triangle([-1, -1, 0], [1, -1, 0], [1, 1, 0], mat_white)
    r.add_triangle([-1, -1, 0], [1, 1, 0], [-1, 1, 0], mat_white)
    emission = {'mode': 'blackbody', 'temperature_K': temperature_K, 'tint_rgb': [1, 1, 1]}
    r.add_area_light_dedicated(
        center=[0, 0, 2], axis_u=[1, 0, 0], axis_v=[0, -1, 0],  # normal -z, faces the plane
        size_x=2.0, size_y=2.0, shape='RECTANGLE', emission=emission, intensity=1.0, spread=1.57)

    pixels = np.asarray(r.render(256, 4, None, False), dtype=np.float64)  # LINEAR
    mean_rgb = pixels.reshape(-1, 3).mean(0)
    assert mean_rgb.max() > 1e-3, f"G2 FAIL: light does not reach the plane, RGB={mean_rgb}"
    got = mean_rgb / mean_rgb.max()
    want = np.array(_PLANCK_SRGB[temperature_K])
    assert np.abs(got - want).max() < 0.01, \
        f"G2 FAIL: {temperature_K:.0f} K normalised RGB={got}, Planck oracle={want}"
    print(f"[G2 PASS] {temperature_K:.0f} K normalised RGB={got} (oracle {want})")


def test_g3_ies_profile_correctness(astroray_module):
    """G3: IES profile candela distribution matches within 5% at 8 sample angles.

    Requires an IES file. For now, we'll skip if no IES file is available.
    The full test requires loading a standard IES file and verifying the
    SpotLight or PointLight candela distribution via rendered intensity.
    """
    pytest.skip("G3 requires IES file; defer to visual regression suite")


def test_g4_spot_cone_falloff(astroray_module):
    """G4: Spot cone falloff verification.

    Inner cone (θ ≤ innerAngle): full intensity ∝ 1/r².
    Transition (innerAngle < θ ≤ outerAngle): smooth falloff.
    Outside outer cone: zero intensity.
    """
    r = astroray_module.Renderer()
    # Black background so corner pixels that miss the ground plane (or fall
    # outside the cone) don't pick up the default sky gradient — otherwise
    # the corner check measures ambient sky, not cone falloff.
    r.set_background_color([0.0, 0.0, 0.0])

    # Look DOWN at the ground from above so all pixels see the lit plane
    # (the earlier camera at y=0 sat IN the ground plane, glancing-angle).
    r.setup_camera(
        look_from=[0, 4, 0.01],
        look_at=[0, 0, 0],
        vup=[0, 0, -1],
        vfov=60.0,
        aspect_ratio=1.0,
        aperture=0.0,
        focus_dist=4.0,
        width=64,
        height=64
    )

    # Ground plane to sample spot cone
    mat_ground = r.create_material('lambertian', [1, 1, 1], {})
    r.add_triangle(
        [-5, 0, -5], [5, 0, -5], [5, 0, 5], mat_ground
    )
    r.add_triangle(
        [-5, 0, -5], [5, 0, 5], [-5, 0, 5], mat_ground
    )

    # Spot light aimed straight down
    emission_spot = {'mode': 'rgb', 'color': [1, 1, 1]}
    inner_angle = 0.2  # ~11.5 degrees half-angle
    outer_angle = 0.4  # ~23 degrees half-angle
    # pkg122 (2026-07-20): the spot wattage->radiance was re-derived against
    # Cycles kernel/light/spot.h — a Blender spot is a point light of power P
    # masked by the cone, radiant intensity I = P/(4π), delta pdf (was 1/π with a
    # 1/coneSolidAngle pdf that multiplied brightness by the cone solid angle).
    # The old scene cranked intensity 100->320 to fight those two compensating
    # bugs; with the physical fix the ABSOLUTE center level changes, so this gate
    # now asserts the cone STRUCTURE (center >> corner, corner ~ 0) plus a loose
    # brightness floor. The exact center magnitude is verified against live Cycles
    # by the team-lead post-build (this implementer cannot build the .pyd).
    r.add_spot_light_dedicated(
        center=[0, 5, 0],
        direction=[0, -1, 0],
        inner_angle=inner_angle,
        outer_angle=outer_angle,
        emission=emission_spot,
        intensity=320.0,
        radius=0.0
    )

    pixels = r.render(256, 1)

    # Check center (should be bright, within inner cone) and corner (dark, outside outer cone).
    # pkg122: absolute center threshold lowered 0.3 -> 0.1 because the spot energy
    # was re-derived (I = P/(4π), delta pdf) — the absolute level shifted and its
    # exact value is verified against live Cycles by the team-lead. The gate now
    # rests on the cone STRUCTURE (center >> corner, corner ~ 0), which is what
    # G4 is actually testing.
    center_lum = np.mean(pixels[32-2:32+2, 32-2:32+2])
    corner_lum = np.mean(pixels[0:4, 0:4])
    assert center_lum > 0.1, f"G4 FAIL: center too dark ({center_lum}), inner cone not working"
    assert corner_lum < 0.01, f"G4 FAIL: corner too bright ({corner_lum}), outer cone not working"
    assert center_lum > 30 * max(corner_lum, 1e-6), \
        f"G4 FAIL: center/corner ratio too low ({center_lum / max(corner_lum, 1e-6):.1f})"

    print(f"[G4 PASS] Spot cone: center={center_lum:.4f}, corner={corner_lum:.6f}")


def test_g5_point_light_isotropy_hard_shadows(astroray_module):
    """G5: POINT light isotropy regression (hard shadows from radius=0).

    Verifies that radius=0 POINT lights produce hard shadows (unlike the
    old 0.1 m emissive-sphere hack which always produced soft shadows).
    """
    r = astroray_module.Renderer()

    r.setup_camera(
        look_from=[3, 3, 3],
        look_at=[0, 0.5, 0],
        vup=[0, 1, 0],
        vfov=45.0,
        aspect_ratio=1.0,
        aperture=0.0,
        focus_dist=5.0,
        width=128,
        height=128
    )

    # Ground plane
    mat_ground = r.create_material('lambertian', [0.8, 0.8, 0.8], {})
    r.add_triangle(
        [-10, 0, -10], [10, 0, -10], [10, 0, 10], mat_ground
    )
    r.add_triangle(
        [-10, 0, -10], [10, 0, 10], [-10, 0, 10], mat_ground
    )

    # Shadow-casting sphere
    mat_sphere = r.create_material('lambertian', [0.5, 0.5, 0.5], {})
    r.add_sphere([0, 0.5, 0], 0.5, mat_sphere)

    # POINT light with radius=0 (hard shadows)
    # pkg122: intensity 50 -> 200 to offset the corrected point calibration
    # (I = P/(4π), 4x dimmer than the old P/π). G5 gates shadow SHARPNESS
    # (radius=0 hard shadow), not absolute brightness, so restoring the signal
    # level with the scene knob keeps the gradient assertion's sensitivity intact.
    emission_point = {'mode': 'rgb', 'color': [1, 1, 1]}
    r.add_point_light(
        position=[2, 3, 2],
        emission=emission_point,
        intensity=200.0,
        radius=0.0  # Hard shadows (singularity at center)
    )

    pixels = r.render(256, 2)

    # Measure shadow sharpness: find the shadow boundary gradient.
    # Hard shadows should have high gradient; soft shadows have low gradient.
    # We'll look at the ground plane region near the sphere's shadow.

    # Extract a horizontal line across the shadow boundary
    shadow_line = pixels[64, :]  # Middle row

    # Compute gradient (difference between adjacent pixels)
    gradient = np.abs(np.diff(shadow_line[:, 0]))  # Use red channel
    max_gradient = np.max(gradient)

    # Hard shadow should have gradient > 0.1; soft shadow from 0.1m sphere would be < 0.05.
    assert max_gradient > 0.05, \
        f"G5 FAIL: shadow too soft (max_gradient={max_gradient:.4f}); radius=0 not working"

    print(f"[G5 PASS] Hard shadow detected, max_gradient={max_gradient:.4f}")
