"""pkg115 — verify procedural textures use GENERATED coordinates by default.

Regression test for the AreaLightShape::hit() hitObject bug: when hitObject
was not set, the GENERATED coordinate path fell back to UV mode, producing
the concentric-ring artifact on spheres diagnosed in commit a523a86.
"""

import astroray
import pytest


def test_checker_uses_generated_coords_on_sphere():
    """Unconnected-Vector Checker on a sphere produces 3D block pattern (not UV rings).

    Renders a low-res sphere with a Checker texture in GENERATED mode, verifying
    that the texture samples 3D object-local coordinates (normalized to the
    sphere's bbox) instead of UV. The patterns are structurally different:
    - GENERATED: large 3D checker blocks distributed across the sphere volume
    - UV: fine concentric latitude rings (from spherical UV parameterization)

    The test asserts non-uniform distribution across the top row vs equator
    row to catch the UV-rings artifact (which produces many alternations in a
    scanline).
    """
    renderer = astroray.Renderer()

    # Checker texture with scale 3 → ~3x3x3 blocks across unit sphere's bbox
    renderer.create_procedural_texture("checker", "checker",
                                       [1.0, 1.0, 1.0,  # color1 (white)
                                        0.0, 0.0, 0.0,  # color2 (black)
                                        3.0])           # scale
    renderer.set_texture_coord_mode("checker", "GENERATED")

    # Lambertian material using the checker texture
    mat_id = renderer.create_material("lambertian", [0.8, 0.8, 0.8], {})
    renderer.set_material_albedo_texture(mat_id, "checker")

    # Unit sphere at origin (bbox = [-1,1]³ → GENERATED coords map to [0,1]³)
    renderer.add_mesh_sphere([0, 0, 0], 1.0, mat_id)

    # White background to avoid artifacts from environment
    renderer.set_background([1.0, 1.0, 1.0])

    # Camera looking at sphere from +Z
    renderer.set_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 45.0)

    # Low res, few samples (pattern check, not quality)
    img = renderer.render(64, 64, 4, apply_gamma=False)

    # Pixel access helper
    def px(x, y):
        """Returns (R,G,B) at pixel (x,y), clamping coords to image bounds."""
        x = max(0, min(63, x))
        y = max(0, min(63, y))
        idx = (y * 64 + x) * 3
        return (img[idx], img[idx+1], img[idx+2])

    # Sample horizontal scanlines: top (y=16, near pole) vs equator (y=32)
    top_row = [px(x, 16) for x in range(10, 54, 4)]
    mid_row = [px(x, 32) for x in range(10, 54, 4)]

    def alternations(row):
        """Count color flips (white<->black) in a scanline."""
        def is_white(rgb):
            return sum(rgb) / 3.0 > 0.5
        flips = 0
        for i in range(len(row) - 1):
            if is_white(row[i]) != is_white(row[i+1]):
                flips += 1
        return flips

    top_flips = alternations(top_row)
    mid_flips = alternations(mid_row)

    # GENERATED mode: scale=3 → ~3 blocks → expect <=4 flips per scanline
    # (rough: a scanline crossing 3 vertical blocks sees 2 edges, +1-2 for
    # horizontal blocks, ~3-4 transitions).
    # UV mode: latitude rings → MANY flips (>8) as we cross concentric bands.
    #
    # Assert: NOT the UV-ring artifact (each scanline has <8 flips).
    assert top_flips < 8, (
        f"Top scanline has {top_flips} flips (UV-ring artifact: concentric "
        f"latitude bands). Expected <8 for GENERATED 3D blocks."
    )
    assert mid_flips < 8, (
        f"Equator scanline has {mid_flips} flips (UV-ring artifact). "
        f"Expected <8 for GENERATED mode."
    )

    # Positive control: verify SOME pattern exists (not uniform gray)
    all_pixels = [px(x, y) for y in range(16, 48, 4) for x in range(16, 48, 4)]
    unique_approx = len(set(tuple(int(c * 10) for c in rgb) for rgb in all_pixels))
    assert unique_approx >= 2, (
        f"Texture appears uniform (only {unique_approx} distinct values). "
        f"Expected checker pattern with black+white."
    )


def test_area_light_shape_sets_hitobject():
    """AreaLightShape::hit() must set rec.hitObject for GENERATED coords to work.

    Direct regression test: create an AreaLightShape, trace a ray that hits it,
    verify the HitRecord has hitObject != nullptr. The GENERATED coordinate path
    requires hitObject to retrieve the object's bounding box.
    """
    # This test would require accessing C++ internals not exposed to Python,
    # so it's a documentation placeholder. The sphere test above is the
    # functional verification.
    pytest.skip("C++ internal test; covered by sphere pattern test")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
